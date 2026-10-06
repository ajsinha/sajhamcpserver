# SAJHA on Kubernetes without Helm

Plain manifests for `kubectl apply -k`, rendered from the Helm chart in
[`charts/sajha`](../../charts/sajha/) by [`render.py`](render.py). The guide, including what
every object does, is
[Kubernetes Deployment](../../docs/getting-started/Kubernetes%20Deployment.md).

| Path | What |
|---|---|
| `base/` | ServiceAccount, ConfigMap (config overrides and the seed script), Service |
| `overlays/dev/` | one pod, SQLite on a PVC, in-process state (`values-dev.yaml`) |
| `overlays/prod/` | 3 to 10 pods (HPA), PDB, PostgreSQL, bundled Redis, two Ingress objects, NetworkPolicies (`values-prod.yaml`) |

## Create the Secrets first

The manifests reference Secrets; they never contain one.

```bash
NS=sajha-dev        # or sajha for prod
kubectl create namespace $NS
kubectl -n $NS create secret generic sajha-secrets \
  --from-literal=jwt-secret="$(openssl rand -base64 48)" \
  --from-literal=session-secret="$(openssl rand -base64 48)" \
  --from-literal=metrics-token="$(openssl rand -hex 24)" \
  --from-file=oauth-signing-key=<(openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048)

# prod only
kubectl -n $NS create secret generic sajha-postgres --from-literal=password='<database password>'
kubectl -n $NS create secret generic sajha-redis --from-literal=redis-password="$(openssl rand -hex 24)"
```

## Apply

```bash
kubectl apply -k deployment/k8s/overlays/dev
kubectl apply -k deployment/k8s/overlays/prod     # after setting the host in its kustomization.yaml
```

The prod overlay expects a PostgreSQL server reachable as `postgres:5432` (database and
user `sajha`) and ingress-nginx; change `values-prod.yaml` and re-render for anything else.
Its tables must exist first: SAJHA never creates them, and the pods refuse to start until
an operator has run the schema file and the seed file once
([Database Setup](../../docs/getting-started/Database%20Setup.md)):

```bash
psql -v ON_ERROR_STOP=1 "postgresql://sajha@postgres:5432/sajha" -f db/scripts/postgresql/schema.sql
psql -v ON_ERROR_STOP=1 "postgresql://sajha@postgres:5432/sajha" -f db/scripts/postgresql/seed.sql
```

## Re-render after a chart change

```bash
python deployment/k8s/render.py           # needs helm on PATH
python deployment/k8s/render.py --check   # what tests/test_k8s_deployment.py runs
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
