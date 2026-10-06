# SAJHA MCP Server — AWS Deployment (CDK)

Deploy SAJHA to AWS ECS Fargate using AWS CDK (Python).

## Architecture

```
Internet → ALB (port 443/80)
             → ECS Fargate (port 3002) ← S3 (tool and prompt configs, Studio .py files)
                  → RDS PostgreSQL (port 5432)
                  → Secrets Manager (API keys, JWT)
                  → CloudWatch (logs, metrics, dashboard)
                  → Bedrock (LLM Gateway)
```

## Prerequisites

- AWS account with CLI configured (`aws configure`)
- Python 3.9+, Node.js 18+ (for CDK CLI)
- Docker (for building container image)

## Quick Deploy

```bash
# 1. Install CDK CLI
npm install -g aws-cdk

# 2. Install CDK Python dependencies
cd deployment/aws/cdk
pip install -r requirements.txt

# 3. Bootstrap CDK (first time only)
cdk bootstrap

# 4. Build and push container image
cd ..
docker build -f Dockerfile -t sajha-mcp-server ../..   # deployment/aws/Dockerfile, repository root as context
aws ecr get-login-password | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com
docker tag sajha-mcp-server:latest <account>.dkr.ecr.<region>.amazonaws.com/sajha-mcp-server:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/sajha-mcp-server:latest

# 5. Deploy
cd cdk
cdk deploy
```

## Configuration

Override defaults via CDK context:

```bash
# Production (2 tasks, auto-scaling, Multi-AZ RDS, NAT gateway)
cdk deploy -c environment=prod

# Custom sizing
cdk deploy -c cpu=2048 -c memory=4096 -c desired_count=3

# Larger database
cdk deploy -c db_instance=r6g.large
```

### Several tasks

Production runs 2–6 Fargate tasks behind the ALB. The stack sets
`SAJHA_STATE_BACKEND=database`, so OAuth codes, MCP sessions and tasks, rate limits and
change notifications are shared through RDS. The tasks must also share the session secret
and the OAuth signing key: their data directories are not shared. Set them through the
environment, as listed in
[Scaling and State §5](../../docs/architecture/Scaling%20and%20State.md#5-secrets-every-worker-must-share).
The stack does this for the JWT and session secrets: it creates `sajha/<env>/jwt` and
`sajha/<env>/session` in Secrets Manager (generated once) and passes them to every task as
`SAJHA_JWT_SECRET` and `SAJHA_SECRET_KEY`. Secrets Manager cannot generate an RSA key, so
if you use the built-in OAuth authorization server, store a PEM yourself and name it:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out key.pem
aws secretsmanager create-secret --name sajha/prod/oauth-signing-key --secret-string file://key.pem
cdk deploy -c environment=prod -c oauth_signing_key_secret=sajha/prod/oauth-signing-key
```

The tasks then get it as `SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PEM`.
To use ElastiCache Redis instead of RDS, set `SAJHA_STATE_BACKEND=redis` and
`SAJHA_STATE_REDIS_URL`.

## What CDK Creates

| Resource | Dev | Prod |
|----------|-----|------|
| VPC | 2 AZs, no NAT | 2 AZs, NAT gateway |
| ECS Fargate | 0.5 vCPU / 1 GB, 1 task | 1 vCPU / 2 GB, 2–6 tasks (auto-scaling) |
| RDS PostgreSQL | t4g.micro, single-AZ | t4g.medium, Multi-AZ, 7-day backups |
| S3 | Auto-delete on destroy | Versioned, retained |
| ALB | Public, HTTP | Public, health checks |
| CloudWatch | 1-week logs | 1-month logs, dashboard |
| Secrets Manager | DB password + app secrets | Same |

## Environment Variables (set in ECS task)

| Variable | Set By CDK | Description |
|----------|-----------|-------------|
| `SAJHA_STORAGE_BACKEND` | `s3` | Use S3 for tool configs |
| `SAJHA_S3_BUCKET` | Auto | S3 bucket name |
| `SAJHA_S3_PREFIX` | `config/` | Key prefix: SAJHA reads `config/tools/*.json` at `s3://<bucket>/config/config/tools/` |
| `SAJHA_DB_TYPE` | `postgresql` | Database type |
| `SAJHA_DB_HOST` | From Secrets | RDS endpoint |
| `SAJHA_DB_PASSWORD` | From Secrets | DB password |
| `SAJHA_JWT_SECRET` | From Secrets (`sajha/<env>/jwt`) | JWT signing key |
| `SAJHA_SECRET_KEY` | From Secrets (`sajha/<env>/session`) | Session secret |
| `SAJHA_STATE_BACKEND` | `database` | Shared state through RDS |
| `SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PEM` | From Secrets, with `-c oauth_signing_key_secret=...` | Built-in OAuth signing key |

## Post-Deploy Setup

**Database schema first.** SAJHA does not create tables on RDS; the tasks refuse to start
(and the service stays unhealthy) until an operator runs the schema file and the seed file
(default roles and admin) once, after the first deploy. There are no migrations. From a
checkout on a host that reaches RDS:

```bash
psql -v ON_ERROR_STOP=1 "postgresql://<user>@<rds-endpoint>:5432/sajha" -f db/scripts/postgresql/schema.sql
psql -v ON_ERROR_STOP=1 "postgresql://<user>@<rds-endpoint>:5432/sajha" -f db/scripts/postgresql/seed.sql
```

Upgrades that change the schema list their SQL in the CHANGELOG. Details:
[Database Setup](../../docs/getting-started/Database%20Setup.md).

```bash
# Upload tool and prompt configs and Studio .py files under the stack's prefix (config/),
# from the repository root
deployment/aws/scripts/sync_to_s3.sh <bucket> config/
```

The script also uploads `config/application.yml`; keep secrets out of it (they come from
Secrets Manager). Plugins are not read from S3 (only from a local `config/plugins`, which this image does not include).
What goes through storage is in the [Storage Guide](../../docs/getting-started/Storage%20Guide.md).

Provider API keys (LLM, FMP, FRED, SharePoint, ...) go in the `sajha/<env>/app` secret the
stack creates, as one JSON object keyed by the variable names `config/application.yml` reads,
e.g. `{"FRED_API_KEY": "...", "OPENAI_API_KEY": "..."}`. The stack passes its ARN to the tasks
as `SAJHA_SECRETS_ARN`; `bootstrap.sh` reads it at container start and exports each key both
as itself and as `SAJHA_<KEY>`. A key added later reaches tasks when they restart.

## Useful Commands

```bash
cdk diff        # Preview changes before deploy
cdk synth       # Generate CloudFormation template
cdk destroy     # Tear down all resources
cdk ls          # List stacks
```

## Costs (Estimated)

| Component | Dev | Prod |
|-----------|----:|-----:|
| ECS Fargate | ~$15/mo | ~$60/mo |
| RDS | ~$15/mo | ~$50/mo |
| ALB | ~$20/mo | ~$20/mo |
| S3 + Secrets | ~$2/mo | ~$5/mo |
| NAT Gateway | $0 | ~$35/mo |
| **Total** | **~$52/mo** | **~$170/mo** |

## Local Development

```bash
# Run with Docker Compose (no AWS needed)
cd deployment/aws
docker compose up
# → SAJHA at http://localhost:3002
# → PostgreSQL at localhost:5432
```

---

*SAJHA MCP Server — AWS CDK Deployment*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
