# Kubernetes Deployment

How to run SAJHA on Kubernetes: the container image, the Helm chart, the Kustomize
manifests generated from it, and what changes when more than one pod serves `/mcp`. For a
walkthrough on a local kind cluster, see
[Tutorial 17](../tutorials/TUTORIAL_17_deploy_sajha_on_kubernetes.md). Configuration keys
are in the [Configuration Reference](Configuration%20Reference.md). What several processes
share, and how, is in [Scaling and State](../architecture/Scaling%20and%20State.md).

| Artefact | Where | Use it for |
|---|---|---|
| Container image | `Dockerfile`, `.dockerignore` (repository root) | every Kubernetes install; also plain `docker run` |
| Helm chart | `charts/sajha/` (`values.yaml`, `values.schema.json`) | the supported way to install and upgrade |
| Kustomize manifests | `deployment/k8s/` (`base/`, `overlays/dev/`, `overlays/prod/`) | clusters without Helm; rendered from the chart |

The other recipes (AWS CDK, Hetzner, bare metal) are in
[`deployment/README.md`](../../deployment/README.md).

---

## 1. The image

```bash
docker build -t sajha:6 .                                   # defaults
docker build -t sajha:6-full \
    --build-arg EXTRAS="redis s3 azure gcs otel" \
    --build-arg WITH_OPENBB=true \
    --build-arg PLAYGROUND_ASSETS=true .
```

| Build argument | Default | Effect |
|---|---|---|
| `PYTHON_VERSION` | `3.13` | Base image `python:<version>-slim`. |
| `EXTRAS` | `redis` | Optional packages, space separated: `redis` (`state.backend: redis`), `s3` (boto3, for `storage.backend: s3` and the Bedrock provider), `azure`, `gcs`, `otel` (OTLP export). |
| `WITH_OPENBB` | `false` | `true` installs the OpenBB SDK (several hundred MB). Without it the `openbb_*` tools return an error. |
| `PLAYGROUND_ASSETS` | `false` | `true` runs `scripts/fetch_pyodide.py` at build time and puts Pyodide in the image. Otherwise set `playground.assets: cdn` (chart value `playground.assets`), or the [Python Playground](Python%20Playground.md) reports that its assets are missing. |

The image is multi-stage: dependencies are installed into `/opt/venv` in a build stage, and
the runtime stage gets only that venv, the code, `config/`, `db/`, `scripts/`, `docs/` and
the root Markdown files (the in-app help renders `docs/` and `GLOSSARY.md`). Test packages,
`tests/`, `clientsdk/`, `data/`, `.env` and generated keys are excluded by `.dockerignore`.

At run time the image:

- runs as UID/GID 10001 under `tini` (which reaps the sandbox's child processes);
- starts `run_server.py --host 0.0.0.0` on port 3002 (`SERVER_PORT`);
- writes only to `/app/data`, `/app/logs`, `/app/temp`, `/app/config`,
  `/app/sajha/tools/impl` (MCP Studio output) and `/tmp`, so it runs with a read-only root
  filesystem when those are mounted;
- has a `HEALTHCHECK` on `GET /health`.

---

## 2. Install with Helm

```bash
helm install sajha charts/sajha -n sajha --create-namespace \
    --set image.repository=registry.example.com/sajha --set image.tag=<tag>
kubectl -n sajha port-forward svc/sajha 3002:80     # then http://127.0.0.1:3002
```

The release name `sajha` gives objects named `sajha-sajha`; set `fullnameOverride: sajha`
for shorter names. Sign in as `admin` / `admin123` and change the password at once (see the
[Security Model](../security/Security%20Model.md#default-admin-account)). `helm test sajha -n sajha`
runs a pod that checks `/health` and sends an MCP `initialize` through the Service.

Every value is documented in `charts/sajha/values.yaml` and validated by
`charts/sajha/values.schema.json`, so a misspelled key fails `helm install` instead of being
ignored. The defaults are one pod, SQLite on a `ReadWriteOnce` volume, no ingress.

### How a pod is laid out

| Piece | What it does |
|---|---|
| Init container `seed` | Same image. Runs `charts/sajha/files/seed.py`: copies the image's `config/` and `sajha/tools/impl/` into the writable volumes (only files the volume lacks, unless `persistence.config.seedMode: overwrite`), writes `config/application.yml` as the image's file with `config.overrides` deep-merged in, and waits for the bundled Redis and the PostgreSQL host to accept connections. |
| Container `sajha` | `run_server.py --workers <workers>`. `readOnlyRootFilesystem`, no capabilities, no privilege escalation, `RuntimeDefault` seccomp, non-root. |
| `/app/data` | PVC (`persistence.data`) or `emptyDir`: SQLite database, generated secrets file, caches, DuckDB data. |
| `/app/config`, `/app/sajha/tools/impl` | `emptyDir` seeded at every start, or one PVC (`persistence.config`) with sub-paths `config` and `impl`, so admin edits and MCP Studio tools outlive the pod. |
| `/app/logs`, `/app/temp`, `/tmp` | `emptyDir` with size limits (`/tmp` holds sandbox work directories and the object-store cache). |
| Probes | startup and liveness `GET /health`, readiness `GET /ready`. |
| `enableServiceLinks: false` | A Service named `sajha` would otherwise inject `SAJHA_PORT=tcp://...`, which the configuration reads as a `SAJHA_*` override. |

### Configuration

Three ways in, in order of preference:

1. **Chart values** for what the chart knows about: database, state store, storage,
   secrets, ingress, metrics, sandbox backend, playground assets. The chart turns them into
   `SAJHA_*` environment variables.
2. **`config.overrides`**: any part of `application.yml`, deep-merged by the seed step. Maps
   merge; lists (such as `ai.providers`) and scalars replace. This is the way to change
   nested structures such as `ai.providers` or `ai.policy`; single `ai.*` fields can also be
   set as `SAJHA_AI_<SECTION>_<FIELD>` variables.
3. **`config.env` / `config.extraEnv` / `config.envFrom`**: raw environment variables, for
   example `SAJHA_HOT_RELOAD_INTERVAL_SECONDS: 60`.

```yaml
config:
  publicUrl: https://mcp.example.com      # mcp.auth.public_url (default: https://<first ingress host>)
  overrides:
    mcp:
      auth: {mode: required}
    ai:
      aliases: {default: [anthropic]}
providerKeys:
  existingSecrets: [llm-keys]              # every key becomes an env var: ANTHROPIC_API_KEY, FMP_API_KEY ...
```

`config.forwardedAllowIps` (default `"*"`) sets `FORWARDED_ALLOW_IPS`, so uvicorn takes the
scheme and client address from the ingress controller's `X-Forwarded-*` headers. That is
safe only when nothing but the controller can reach the pods; turn on `networkPolicy`.

---

## 3. Secrets

Every replica must sign and verify with the same keys
([Scaling and State §5](../architecture/Scaling%20and%20State.md#5-secrets-every-worker-must-share)).
A key generated into a pod's own data directory would make each pod reject the others'
sign-ins, CSRF tokens and OAuth access tokens, so the chart always passes them from one
Secret:

| Secret key | Environment variable | Used for |
|---|---|---|
| `jwt-secret` | `SAJHA_JWT_SECRET` | web sign-in and API JWTs |
| `session-secret` | `SAJHA_SECRET_KEY` | OAuth consent CSRF tokens; seeds the MRTR key |
| `oauth-signing-key` (optional) | `SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PEM` | RS256 key of the built-in OAuth authorization server |
| `metrics-token` (optional) | `SAJHA_OBSERVABILITY_METRICS_TOKEN` | bearer token for `/metrics` scrapes |

With `secrets.existingSecret` empty, the chart creates `<release>-secrets` with random
values and an RSA key, reuses them on every upgrade (`lookup`), and keeps the Secret when
the release is uninstalled (`helm.sh/resource-policy: keep`). Back it up. `helm template`
and GitOps tools that render without cluster access cannot `lookup`, so they would
generate new values on every render: create the Secret yourself and set
`secrets.existingSecret`:

```bash
kubectl -n sajha create secret generic sajha-secrets \
  --from-literal=jwt-secret="$(openssl rand -base64 48)" \
  --from-literal=session-secret="$(openssl rand -base64 48)" \
  --from-literal=metrics-token="$(openssl rand -hex 24)" \
  --from-file=oauth-signing-key=<(openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048)
```

Database and Redis passwords come from their own Secrets (`database.postgresql.existingSecret`,
`state.redis.existingSecret`, `redis.existingSecret`); provider keys from
`providerKeys.existingSecrets`; bucket credentials from `storage.credentialsSecret`, or
better from workload identity through `serviceAccount.annotations`.

---

## 4. Several replicas

`replicaCount > 1` or `autoscaling.enabled` means several pods behind one Service. The
chart refuses to render a combination that would split state silently:

| Requirement | Why | Value |
|---|---|---|
| PostgreSQL | Users, API keys, audit and durable task records live in the database; SQLite cannot be shared between pods. | `database.type: postgresql` and `database.postgresql.*` |
| A shared state store | MCP sessions, OAuth codes, tasks, rate limits and change notifications are per process otherwise. | `state.backend: auto` resolves to `redis` when Redis is configured, else `database` |
| No `ReadWriteOnce` volume | Pods on different nodes cannot mount it. | `persistence.data.enabled: false` (PostgreSQL holds the data), or `ReadWriteMany`, or `existingClaim` |
| Shared tool configuration | An admin edit or MCP Studio tool made on one pod must reach the others. | `storage.backend: s3`, `azure` or `gcs` for tool and prompt JSON, and `persistence.config` on a `ReadWriteMany` volume for Studio-generated `.py` files ([Storage Guide](Storage%20Guide.md)) |

`redis.enabled: true` adds a single-node Redis StatefulSet with a generated password; for
production prefer a managed Redis and `state.redis.existingSecret` (a Secret holding the
`redis://` or `rediss://` URL). With several pods the chart also adds a
PodDisruptionBudget (`minAvailable: 1`), spreads pods over nodes
(`topologySpread`), and uses a rolling update that never removes a pod before its
replacement is ready. With one pod on a `ReadWriteOnce` volume it uses `Recreate`, because
the new pod cannot mount the volume until the old one lets go.

Prefer `workers: 1` and more replicas over several workers per pod: probes, resource limits
and metrics then each describe one process. With one worker per pod the chart sets
`observability.metrics.multiworker` to `off`, so each pod reports only its own series and
Prometheus does not count other pods' snapshots twice.

Streams stay on the pod that opened them; the messages they need are relayed through the
state store, so no session affinity is needed. `ingress.sessionAffinity: true` adds cookie
affinity to save relay hops for browser sessions.

---

## 5. Ingress and streaming

`ingress.enabled: true` creates two Ingress objects for the same hosts:

| Object | Paths | ingress-nginx settings |
|---|---|---|
| `<release>` | `/` | `proxy-read-timeout` / `proxy-send-timeout` `ingress.timeoutSeconds` (60), `proxy-body-size` `ingress.bodySize` |
| `<release>-streams` | `/mcp` (with `/mcp/sse`, `/mcp/message`, `/mcp/ws`), `/api/mcp`, `/api/ai/ask` | `proxy-buffering: "off"`, `proxy-request-buffering: "off"`, HTTP/1.1 upstream, timeouts `ingress.streamTimeoutSeconds` (3600) |

Streamable HTTP responses, the legacy SSE stream, the WebSocket transport and the Ask SAJHA
event stream must reach the client as they are written, and may stay open for an hour; the
same rules as the bare-metal `deployment/baremetal/nginx.conf`. ingress-nginx upgrades
WebSocket connections on its own.

For another controller set `ingress.nginx: false` and give the equivalent settings in
`ingress.annotations` (both objects) and `ingress.streamAnnotations` (streams only): for
example Traefik needs no buffering setting but a long `respondingTimeouts` on its
entry point, and the AWS Load Balancer Controller needs
`alb.ingress.kubernetes.io/load-balancer-attributes: idle_timeout.timeout_seconds=3600`.

TLS: list Secrets in `ingress.tls` (cert-manager annotations go in `ingress.annotations`).
With TLS the public URL defaults to `https://<first host>`; it becomes
`mcp.auth.public_url`, the OAuth issuer and token audience.

---

## 6. Database, state and storage values

| Value | Becomes |
|---|---|
| `database.type` | `SAJHA_DB_TYPE` (`sqlite` keeps `/app/data/sajha.db`) |
| `database.postgresql.host`, `port`, `name`, `user`, `existingSecret`/`passwordKey` | `SAJHA_DB_HOST`, `SAJHA_DB_PORT`, `SAJHA_DB_NAME`, `SAJHA_DB_USER`, `SAJHA_DB_PASSWORD` |
| `database.postgresql.urlSecret`/`urlKey` | `SAJHA_DB_URL` (wins over the fields) |
| `database.postgresql.schemaCheck` | `SAJHA_DB_SCHEMA_CHECK` (`strict` default, or `warn`) |
| `state.backend` | `SAJHA_STATE_BACKEND` after resolving `auto` |
| `redis.enabled`, `state.redis.url`, `state.redis.existingSecret` | `SAJHA_STATE_REDIS_URL` |
| `storage.backend` and `storage.s3/azure/gcs.*` | `SAJHA_STORAGE_BACKEND`, `SAJHA_S3_BUCKET`, `SAJHA_S3_PREFIX`, `AWS_DEFAULT_REGION`, `SAJHA_S3_ENDPOINT_URL`, `SAJHA_AZURE_CONTAINER`, `SAJHA_AZURE_ACCOUNT_URL`, `SAJHA_GCS_BUCKET`, `GOOGLE_CLOUD_PROJECT`; every cache directory is `/tmp/sajha-cache` |

The image needs the matching extra: `redis` for the Redis backend, `s3`, `azure` or `gcs`
for a bucket (section 1).

**PostgreSQL schema.** The chart never creates tables, and there are no migrations. Before
the first install an operator runs `db/scripts/postgresql/schema.sql` and `seed.sql` with
`psql` (the chart's install notes print the commands; the procedure, and what an upgrade
that changes the schema needs, are in [Database Setup](Database%20Setup.md)). Until then
the pods exit with `Refusing to start: database schema is not ready` and the missing
tables, and restart.

### SAJHA Net

The `sajhanet` values write the `sajhanet` section of the configuration (merged into
`config.overrides`; the keys are in the
[Configuration Reference](Configuration%20Reference.md#sajha-net), the design in
[SAJHA Net](../architecture/SAJHA%20Net.md)). Certificates and keys are never values: each
net's come from Secrets you create, mounted read-only.

```yaml
sajhanet:
  enabled: true
  allowedNetworks: [10.20.0.0/16]      # sajhanet.allowed_networks
  nets:
    - name: acme-net
      instanceName: risk-eu
      advertiseAddress: 10.20.4.17:443 # the Service or load-balancer address peers use
      seeds: [https://sajha-cust-na.example.internal]
      identitySecret: acme-net-identity
      settings: {default_trust: review}
```

| Value | Becomes |
|---|---|
| `sajhanet.enabled` | `sajhanet.enabled: true` (off: no `sajhanet` section is written) |
| `sajhanet.allowedNetworks` | `sajhanet.allowed_networks`; with `networkPolicy.enabled`, also ingress from and egress to these ranges on the HTTP ports (`networkPolicy.egress.internetPorts`) |
| `nets[].name`, `instanceName`, `advertiseAddress`, `founder`, `seeds` | the net entry's `name`, `instance_name`, `advertise_address`, `founder`, `seeds` |
| `nets[].identitySecret` | a Secret with keys `instance.crt`, `instance.key` and `ca.pem`, mounted at `/etc/sajhanet/<net>/`; the entry's `identity` refers to those files (`file:` references) |
| `nets[].revocationList` | `true`: the same Secret also has `revoked.json` (`identity.revocation_list_ref`) |
| `nets[].caKeySecret` | the CA instance only: a Secret with key `ca.key`, mounted at `/etc/sajhanet-ca/<net>/`; becomes `ca: {enabled: true, key_ref: ...}` |
| `nets[].settings` | any other key of the net entry, passed through as written (`default_trust`, `export`, `import`, `peer_cache` ...) |

```bash
kubectl -n sajha create secret generic acme-net-identity \
    --from-file=instance.crt --from-file=instance.key --from-file=ca.pem
```

The chart refuses to render a net listed twice, a net without `seeds` that is not the
`founder`, and, with more than one pod, a net without `instanceName` and
`advertiseAddress`: every pod is the same instance, and an address name would differ from
pod to pod. The schema checks net and instance names against the
[protocol's rules](../protocol/SAJHA%20Net%20Protocol.md#5-names).

---

## 7. Metrics

`metrics.enabled` (default `true`) keeps `/metrics` on; `metrics.auth` (default `token`)
sets `observability.metrics.auth`, and scrapes send the `metrics-token` key of the secrets
Secret as a bearer token. `metrics.serviceMonitor.enabled: true` adds a Prometheus
Operator ServiceMonitor that does exactly that (add `metrics.serviceMonitor.labels` to match
your Prometheus `serviceMonitorSelector`). OpenTelemetry export is configured through
`config.env` (`OTEL_EXPORTER_OTLP_ENDPOINT`, ...) and needs the `otel` image extra. The
metrics themselves are in [Observability](../architecture/Observability.md).

---

## 8. Security

- **Pod and container.** Non-root UID 10001, `fsGroup` 10001, `RuntimeDefault` seccomp,
  read-only root filesystem, all capabilities dropped, no privilege escalation, no service
  account token (`serviceAccount.automountServiceAccountToken: false`).
- **NetworkPolicy** (`networkPolicy.enabled`). Ingress to the HTTP port only from the
  namespaces in `networkPolicy.ingress.namespaceSelectors` (default `ingress-nginx` and
  `monitoring`), from other SAJHA pods, and from pods labelled `sajha-client: "true"` (the
  `helm test` pod). Egress: DNS, the bundled Redis, the PostgreSQL port, and public HTTPS/HTTP
  with private, link-local (cloud metadata) and carrier-grade NAT ranges excluded. Add
  allowlist rules in `networkPolicy.egress.extra` (a VPC endpoint, an in-cluster MCP server
  you federate, an internal LLM). The bundled Redis gets its own policy: only SAJHA pods
  may connect, and it may connect nowhere.
- **Sandbox for user code.** Studio Python and script tools run through the `subprocess`
  backend by default ([Sandbox](../architecture/Sandbox.md)). Inside a pod with the
  `RuntimeDefault` seccomp profile, the runner's user and PID namespace step is normally
  refused, and the runner skips it: the environment, work-directory, timeout and output
  limits, rlimits, Landlock and its own seccomp filter still apply, but a process a tool
  forks is not confined to a PID namespace, and Landlock needs a node kernel that has it
  (5.13 or later; network rules 6.7 or later). Check what a pod actually applies with
  `GET /api/sandbox/status` (admin). Do not loosen the pod to get namespaces back
  (`seccompProfile: Unconfined`, `privileged`, `SYS_ADMIN`): that weakens the whole
  server to strengthen one tool. The `bwrap` and `docker` backends are not in the image;
  docker-in-pod needs a privileged daemon or the node's socket, which is worse. When
  untrusted users write tools, run SAJHA on a node pool with a sandboxed runtime (gVisor
  `runtimeClassName`, Kata Containers) through the pod spec instead.
- **Default admin.** The seeded `admin` / `admin123` account exists in every new database.
  Change it before you expose the ingress.

---

## 9. Without Helm: Kustomize

`deployment/k8s/` holds the same objects as plain manifests, rendered from the chart by
`deployment/k8s/render.py` (needs the `helm` binary):

| Directory | Contents | From |
|---|---|---|
| `base/` | ServiceAccount, ConfigMap (overrides and seed script), Service | objects identical in both overlays |
| `overlays/dev/` | one pod, SQLite on a PVC, in-process state | `deployment/k8s/values-dev.yaml` |
| `overlays/prod/` | three to ten pods (HPA), PDB, PostgreSQL, bundled Redis, two Ingress objects, NetworkPolicies | `deployment/k8s/values-prod.yaml` |

```bash
kubectl create namespace sajha-dev
kubectl -n sajha-dev create secret generic sajha-secrets ...    # as in section 3
kubectl apply -k deployment/k8s/overlays/dev
```

The manifests reference Secrets instead of creating them (Kustomize cannot generate
random values safely): `sajha-secrets` always, and in prod `sajha-postgres` (key
`password`) and `sajha-redis` (key `redis-password`). Change the image with Kustomize's
`images:` and the host name with the patches in `overlays/prod/kustomization.yaml`. After
changing the chart or a values file, run `python deployment/k8s/render.py`;
`tests/test_k8s_deployment.py` runs `render.py --check` when Helm is installed.

---

## 10. Checking an install

```bash
helm lint charts/sajha
helm template sajha charts/sajha -f my-values.yaml | kubeconform -strict -summary
helm test sajha -n sajha
kubectl -n sajha exec deploy/sajha -c sajha -- python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:3002/health').read()[:400])"
```

The `state` block of `/health` names the backend in use, whether it answers, and the pod's
worker id. The MCP conformance suites can be run against the ingress the same way as
against a local server; the commands are in the
[2026-07-28 compliance report](../protocol/MCP%202026-07-28%20Compliance.md#5-conformance-results).

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `helm install` fails with "more than one pod ..." | A multi-pod setting without PostgreSQL, a shared store, or with a `ReadWriteOnce` volume | Section 4 |
| `values don't meet the specifications of the schema` | A misspelled or unknown key | Compare with `charts/sajha/values.yaml` |
| Pods crash-loop with `Refusing to start: database schema is not ready` | The PostgreSQL schema file has not been run | [Database Setup](Database%20Setup.md) |
| Pod restarts once at install with "the store does not answer" | Redis was not up yet and the seed step's wait timed out | The seed step waits up to 180 s; check the Redis pod and `networkPolicy.egress` |
| Users signed out when a request lands on another pod | Pods have different JWT or session secrets | Use one Secret for all pods (section 3); never set `JWT_SECRET` per pod |
| Streams cut after 60 s | The request did not hit the streams Ingress, or another controller is buffering | Section 5 |
| `/metrics` answers 401 | The scrape sends no token or the wrong one | `metrics.serviceMonitor`, or `Authorization: Bearer <metrics-token>` |
| A Studio tool loads on one pod only | Its `.py` is on that pod's `emptyDir` | `persistence.config` on `ReadWriteMany` (section 4) |
| Playground says its assets are missing | Image built without `PLAYGROUND_ASSETS=true` | Rebuild, or `playground.assets: cdn` |
| `Read-only file system` in the log | Code writing outside the mounted directories | Report it; mount the path with `extraVolumes` / `extraVolumeMounts` meanwhile |

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
