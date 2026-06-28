# SAJHA MCP Server — AWS Deployment (CDK)

Deploy SAJHA to AWS ECS Fargate using AWS CDK (Python).

## Architecture

```
Internet → ALB (port 443/80)
             → ECS Fargate (port 3002) ← S3 (configs, plugins)
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
cd aws/cdk
pip install -r requirements.txt

# 3. Bootstrap CDK (first time only)
cdk bootstrap

# 4. Build and push container image
cd ..
docker build -t sajha-mcp-server .
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
| `SAJHA_DB_TYPE` | `postgresql` | Database type |
| `SAJHA_DB_HOST` | From Secrets | RDS endpoint |
| `SAJHA_DB_PASSWORD` | From Secrets | DB password |
| `SAJHA_JWT_SECRET` | From Secrets | JWT signing key |

## Post-Deploy Setup

```bash
# Upload tool configs to S3
aws s3 sync config/ s3://<bucket>/config/

# Upload plugins
aws s3 sync config/plugins/ s3://<bucket>/config/plugins/

# Set application secrets
aws secretsmanager put-secret-value \
  --secret-id sajha/dev/app \
  --secret-string '{"jwt_secret":"your-secret","anthropic_api_key":"sk-..."}'
```

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
cd aws
docker compose up
# → SAJHA at http://localhost:3002
# → PostgreSQL at localhost:5432
```

---

*SAJHA MCP Server v5.1.0 — AWS CDK Deployment*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
