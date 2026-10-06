# Storage Management

SAJHA routes all configuration and asset IO through a single storage abstraction
(`sajha.core.storage`). The same build runs unchanged on a laptop, on-prem, or in any
cloud — you change one config value. Tool configs, prompts, MCP Studio output, and docs all
read and write through the selected backend.

The default backend is **local**. Cloud SDKs are imported lazily, so the default install
pulls none of them.

## Selecting a backend

Set `storage.backend` in `config/application.yml` (or the `SAJHA_STORAGE_BACKEND`
environment variable):

| Backend | Value | Auth | Install |
|---------|-------|------|---------|
| Local / EFS | `local` (default) | — | none |
| AWS S3 (+ MinIO / R2 / Wasabi) | `s3` | IAM role / boto3 chain | `boto3` |
| Azure Blob | `azure` | managed identity or connection string | `azure-storage-blob azure-identity` |
| Google Cloud Storage | `gcs` | Application Default Credentials | `google-cloud-storage` |

## What belongs where

Object stores (S3, Azure, GCS) are excellent for **read-mostly assets** but are **not a
filesystem** — they have no atomic append or rename.

| Data class | Examples | Location |
|------------|----------|----------|
| Read-mostly | tool JSON configs, prompts, docs, reference CSVs, DuckDB source data | object store — fine |
| Mutable state | SQLite `sajha.db`, audit log, output cache, sessions | EFS path or managed service (RDS) — **never object storage** |

Running SQLite on an object store will corrupt the database. Keep it on a real filesystem
(EFS) or switch `db.type` to `postgresql`.

## local & EFS

The `local` backend reads and writes ordinary filesystem paths. It is the default and needs
no cloud SDK. The path can be a laptop disk, an EBS volume, or an **Amazon EFS mount** — to
the application they are identical, because EFS is just a path, not a separate backend.

```yaml
storage:
  backend: local
  base_dir: "."            # or an EFS mount, e.g. /mnt/efs/sajha
```

Use EFS when you need a shared, POSIX, multi-instance filesystem on AWS: for the mutable
state that cannot live on S3 (the SQLite DB, audit log, cache) and for MCP Studio-generated
Python implementations that every instance must `import`. Mount EFS and point `base_dir`
(or the specific data dirs / `db.path`) at it — no code changes.

## Amazon S3 (and S3-compatible)

```yaml
storage:
  backend: s3
  s3:
    bucket: my-sajha-config
    prefix: sajha/
    region: us-east-1
    endpoint_url: ""        # set for MinIO / Cloudflare R2 / Wasabi
    cache_dir: /tmp/sajha-cache
    sync_interval: 60
```

- **Auth:** the default boto3 credential chain. On EC2/ECS/EKS attach an IAM role — no keys
  in config. Locally, standard `AWS_*` env vars or `~/.aws` work.
- **S3-compatible:** set `endpoint_url` to target MinIO, Cloudflare R2, or Wasabi with the
  same code.
- **Install:** `pip install boto3`

## Azure Blob Storage

```yaml
storage:
  backend: azure
  azure:
    container: sajha-config
    account_url: https://<account>.blob.core.windows.net   # managed identity
    connection_string: ""   # alternative auth — keep in env, not in config
    prefix: sajha/
    cache_dir: /tmp/sajha-cache
```

- **Auth precedence:** a connection string (`AZURE_STORAGE_CONNECTION_STRING`), otherwise
  `account_url` + `DefaultAzureCredential` (managed identity — no secrets in config).
- **Install:** `pip install azure-storage-blob azure-identity`

## Google Cloud Storage

```yaml
storage:
  backend: gcs
  gcs:
    bucket: my-sajha-config
    project: my-gcp-project   # GOOGLE_CLOUD_PROJECT
    prefix: sajha/
    cache_dir: /tmp/sajha-cache
```

- **Auth:** Application Default Credentials — the attached service account / workload
  identity on GCE/GKE/Cloud Run. No keys in config.
- **Install:** `pip install google-cloud-storage`

## How it works

- **Read-through cache.** Cloud backends mirror fetched objects into `cache_dir`, so anything
  that needs a real file (e.g. `importlib`) still works.
- **Hot-reload.** On `local`, a filesystem poller watches tool configs. On a cloud backend
  (no inotify), `S3SyncManager` polls the bucket every `sync_interval` seconds, mirrors
  changes to the cache, and reloads tools and prompts. Exactly one mechanism runs per
  deployment.
- **Tool implementations.** Tool JSON configs live in the chosen backend; the Python
  implementation classes ship with the package and import locally. MCP Studio-generated `.py`
  files are written locally for `importlib` — on multi-instance cloud deployments, place that
  directory on shared EFS so every instance can import them.
- **Migrating data.** To move from local to a bucket, copy `config/` and `docs/` under the
  configured `prefix`, then switch `storage.backend`. Example:
  `aws s3 sync ./config s3://my-sajha-config/sajha/config`.

## Design (for contributors)

```
StorageBackend (ABC)
 ├── LocalStorageBackend            filesystem / EFS (default, no SDK)
 └── _ObjectStorageBackend          shared object-store base (cache, prefix, listing)
       ├── S3StorageBackend         boto3
       ├── AzureBlobStorageBackend  azure-storage-blob
       └── GCSStorageBackend        google-cloud-storage
S3SyncManager                       cloud hot-reload (poll → cache → reload callbacks)
```

Each object store implements only six primitives (`_fetch_bytes`, `_store_bytes`,
`_object_exists`, `_delete_object`, `_list_keys`, `_object_mtime`); the shared base provides
the SAJHA contract on top. See `docs/STORAGE_ROADMAP.md` for design history and remaining
work.
