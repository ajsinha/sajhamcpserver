# Storage Guide

SAJHA reads and writes its read-mostly assets (tool configs, prompts, documentation) through
one storage abstraction, `sajha.core.storage`. The same build can keep those assets on a
local disk, an EFS mount, Amazon S3 (or an S3-compatible store), Azure Blob Storage, or Google
Cloud Storage. Switching is a configuration change; no code changes.

Mutable state (the database, the output cache, the OAuth signing key, in-flight MCP work) does
**not** go through this abstraction and must stay on a real filesystem or a managed service.
The section [What must not go through storage](#what-must-not-go-through-storage) explains why.

Related: [Configuration Reference](Configuration%20Reference.md) ·
[Architecture](../architecture/Architecture.md) · [Deployment](../../deployment/README.md)

---

## Backends at a glance

| Backend | `storage.backend` | Auth | Extra install |
|---------|-------------------|------|---------------|
| Local disk / EBS / EFS mount | `local` (default) | none | none |
| Amazon S3, plus MinIO / Cloudflare R2 / Wasabi via `endpoint_url` | `s3` | boto3 default credential chain (IAM role) | `pip install boto3` |
| Azure Blob Storage | `azure` | connection string, or `account_url` + `DefaultAzureCredential` (managed identity) | `pip install azure-storage-blob azure-identity` |
| Google Cloud Storage | `gcs` | Application Default Credentials (service account / workload identity) | `pip install google-cloud-storage` |

Cloud SDKs are imported lazily inside each backend's constructor. The default `local` backend
needs none of them, and a missing SDK only matters when you select that backend. In that case
startup logs `Storage backend init failed, falling back to local filesystem` with an
`ImportError` that names the package to install.

EFS is not a separate backend. It is a POSIX mount, so the `local` backend reads it as an
ordinary path.

---

## What goes through storage

These subsystems call `get_storage()`. When you switch backends, they read and write the
selected store.

| Subsystem | Storage path (relative to `base_dir` or bucket `prefix`) | Operations |
|-----------|----------------------------------------------------------|------------|
| Tools registry | `config/tools/*.json` | list and read at load; admin config edits and enable/disable persist with `write_json` |
| Prompts registry | `config/prompts/*.json` | list and read at load; create and update use `write_json`; delete uses `delete` |
| MCP Studio generators | `config/tools/<name>.json` | the generated tool **JSON** is written through `write_tool_config()` |
| Guide pages (`/help/guides`, `/help/guides/{name}`) | `docs/**/*.md` except `docs/archive/` and `README.md` files | recursive listing (reused for 30 s) and a read per page; a guide is found by its file name |
| Semantic tool search vector index | `data/tool_search_index.json` | loaded at start and rewritten after re-embedding; only when `ai.tool_search.embedder` is `gateway` (the default `bm25` builds nothing to persist) |

The tools and prompts paths come from `config.tools.dir` / `config.prompts.dir` (defaults
`config/tools`, `config/prompts`), taken relative to the working directory.

### Read from local disk regardless of backend

These parts are always read from local disk, even when the backend is a cloud store:

- `config/application.yml` itself (and any file passed with `--config`).
- Tool **implementation** classes (`sajha.tools.impl.*`), imported from the installed package.
- MCP Studio-generated `.py` files (written to `sajha/tools/impl/`) and Script-tool scripts
  (`config/scripts/`). `importlib` needs a real module on disk.
- Plugins under `config.plugins.dir` (default `config/plugins`).
- DuckDB / SQL-select data directories (`data.duckdb.dir`, `data.sqlselect.dir`). These are
  scanned with `os.listdir`.

### What must not go through storage

Object stores have no atomic append, rename, or file locking. Keep the following on a real
filesystem (local disk, EBS, EFS) or a managed service, and never on S3, Azure Blob, or GCS:

| State | Where it lives | Placement |
|-------|----------------|-----------|
| Database (SQLite `data/sajha.db`, from `db.path`) | file on disk, via SQLAlchemy | real filesystem or EFS, or set `db.type: postgresql` (e.g. RDS). SQLite on an object store will corrupt. |
| Audit log | `audit_log` table in the same database | follows the database |
| Tool output cache | `cache.dir` (default `data/cache`) | local or ephemeral disk |
| OAuth signing key | `mcp.auth.builtin.signing_key_path`, default `<data.dir>/oauth/signing_key.pem` | real filesystem, and shared (EFS) when several instances must sign with the same key |
| MCP sessions, MCP tasks, OAuth codes, rate limits | the state store (`state.backend`, [Scaling and State](../architecture/Scaling%20and%20State.md)) | `memory` (default): lost on restart, not shared between workers. `redis` or `database`: shared; task records durable in the database |

---

## Configuration

Everything lives under `storage:` in `config/application.yml`:

```yaml
storage:
  backend: local                 # local | s3 | azure | gcs
  base_dir: "."                  # local backend root (laptop disk, EBS, or an EFS mount)
  s3:
    bucket: ""
    prefix: "sajha/"             # key prefix inside the bucket
    region: us-east-1
    endpoint_url: ""             # MinIO / Cloudflare R2 / Wasabi
    cache_dir: /tmp/sajha-cache
    sync_interval: 60            # cloud hot-reload poll seconds (all cloud backends)
  azure:
    container: ""
    account_url: ""              # https://<acct>.blob.core.windows.net (managed identity)
    connection_string: ""        # alternative auth
    prefix: "sajha/"
    cache_dir: /tmp/sajha-cache
  gcs:
    bucket: ""
    project: ""
    prefix: "sajha/"
    cache_dir: /tmp/sajha-cache
```

The backend is chosen **once, at startup** (`init_storage` runs before tools and prompts
load). To change `storage.*`, restart the server.

### Environment variables

Every storage key can be overridden from the environment, and the environment wins over
`application.yml`. `init_storage()` resolves each key (`storage_setting` in
`sajha/core/storage.py`) as: the env var in this table → `SAJHA_` + the dotted key in upper
case (for example `SAJHA_STORAGE_S3_BUCKET`) → the YAML → the code default. An env var set to
an empty string is ignored.

| Key | Env override |
|-----|--------------|
| `storage.backend` | `SAJHA_STORAGE_BACKEND` |
| `storage.base_dir` | `SAJHA_BASE_DIR` |
| `storage.s3.bucket` / `prefix` / `region` / `cache_dir` / `endpoint_url` | `SAJHA_S3_BUCKET` / `SAJHA_S3_PREFIX` / `AWS_DEFAULT_REGION` / `SAJHA_S3_CACHE_DIR` / `SAJHA_S3_ENDPOINT_URL` |
| `storage.azure.container` / `account_url` / `connection_string` / `prefix` / `cache_dir` | `SAJHA_AZURE_CONTAINER` / `SAJHA_AZURE_ACCOUNT_URL` / `AZURE_STORAGE_CONNECTION_STRING` / `SAJHA_AZURE_PREFIX` / `SAJHA_AZURE_CACHE_DIR` |
| `storage.gcs.bucket` / `project` / `prefix` / `cache_dir` | `SAJHA_GCS_BUCKET` / `GOOGLE_CLOUD_PROJECT` / `SAJHA_GCS_PREFIX` / `SAJHA_GCS_CACHE_DIR` |

So `SAJHA_STORAGE_BACKEND=s3 SAJHA_S3_BUCKET=my-bucket python run_server.py` starts the S3
backend with the shipped `application.yml`. Keep credentials such as
`AZURE_STORAGE_CONNECTION_STRING` in the environment, never in the YAML. For GCS, an empty
`project` makes SAJHA call `storage.Client()` without a project, and the Google SDK then
resolves it itself (ADC / `GOOGLE_CLOUD_PROJECT`).

---

## Backends

### local (and EFS)

```yaml
storage:
  backend: local
  base_dir: "."            # or an EFS mount, e.g. /mnt/efs/sajha
```

- Paths resolve as `base_dir / <relative path>`. Writes create parent directories.
- Use EFS when several instances need one shared POSIX filesystem on AWS. It can hold the
  state that cannot live on an object store (the SQLite DB, the OAuth key, the cache) and the
  Studio-generated `.py` files that every instance must import. Point `base_dir`, `db.path`,
  or `data.dir` at the mount as needed.
- Keep `base_dir` equal to the working directory unless you have a reason not to. The local
  hot-reload pollers (below) watch `config/tools` and `config/prompts` relative to the
  working directory, while storage reads resolve against `base_dir`.

### Amazon S3 and S3-compatible stores

```yaml
storage:
  backend: s3
  s3:
    bucket: my-sajha-config
    prefix: sajha/
    region: us-east-1
    endpoint_url: ""          # e.g. http://minio:9000 for MinIO
    cache_dir: /tmp/sajha-cache
    sync_interval: 60
```

- **Auth:** the default boto3 credential chain. On EC2, ECS, or EKS, attach an IAM role with
  `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` and `s3:ListBucket` on the bucket and
  prefix. Keep keys out of the config. Locally, `AWS_*` env vars or `~/.aws` work.
- **S3-compatible:** set `endpoint_url` to target MinIO, Cloudflare R2, or Wasabi with the
  same code.
- `exists()` uses `HeadObject` and returns `False` quietly on a missing object.

### Azure Blob Storage

```yaml
storage:
  backend: azure
  azure:
    container: sajha-config
    account_url: https://<account>.blob.core.windows.net
    connection_string: ${AZURE_STORAGE_CONNECTION_STRING:}
    prefix: sajha/
    cache_dir: /tmp/sajha-cache
```

- **Auth precedence:** a non-empty `connection_string` wins. Otherwise SAJHA uses
  `account_url` + `DefaultAzureCredential` (managed identity, workload identity, or `az
  login` locally), which needs `azure-identity`. If both are empty, startup fails with
  `Azure backend needs storage.azure.connection_string or storage.azure.account_url` and
  falls back to local.
- With managed identity, grant the identity a data-plane role on the container, such as
  *Storage Blob Data Contributor*.

### Google Cloud Storage

```yaml
storage:
  backend: gcs
  gcs:
    bucket: my-sajha-config
    project: my-gcp-project      # optional; empty lets the SDK resolve it
    prefix: sajha/
    cache_dir: /tmp/sajha-cache
```

- **Auth:** Application Default Credentials, meaning the attached service account or
  workload identity on GCE, GKE, or Cloud Run, or `gcloud auth application-default login`
  locally. No keys in config. The identity needs object read, write, list, and delete on the
  bucket (e.g. *Storage Object Admin* scoped to it).

---

## How the object-store backends behave

S3, Azure, and GCS share one base class (`_ObjectStorageBackend`). The behaviour below is the
same on all three.

- **Prefix namespacing.** The logical path `config/tools/x.json` maps to the key
  `<prefix>/config/tools/x.json`. A trailing slash on `prefix` is optional.
- **Listing.** `list_files(prefix, pattern)` is always **recursive**. It matches `pattern`
  (fnmatch) against the **filename only** and returns sorted paths relative to the prefix.
  The local backend has the same semantics: recursive `rglob`, with the pattern matched on the
  filename.
- **Reads always hit the store.** `read_bytes` / `read_text` / `read_json` fetch the object
  every time and then mirror it into `cache_dir`. A missing object raises
  `FileNotFoundError`.
- **Writes are write-through.** The object is uploaded, then mirrored into `cache_dir`.
  `delete` removes the object and its cached copy.
- **`cache_dir` is a local mirror, not a serving cache.** `get_local_path()` returns the
  cached file and fetches it only if no cached copy exists. It does not check freshness. In
  the server today the mirror is refreshed by reads, writes, and the sync manager.
  `cache_dir` is never evicted, and every backend defaults to `/tmp/sajha-cache`.
- **Modified time** comes from object metadata (`LastModified` / `last_modified` /
  `updated`). If it cannot be read, it is `0.0`.

---

## Hot reload per backend

Only one tool-reload mechanism is active per deployment.

| Mechanism | Backend | What it watches | Interval |
|-----------|---------|-----------------|----------|
| Tools registry poller | `local` only (skipped on cloud) | `config/tools/*.json` on disk (new, modified, deleted) plus `sajha/tools/impl/*.py` | 5 s (fixed) |
| `ConfigReloader` / `HotReloadManager` | any (local files only) | local tool JSON, tool modules, prompt JSON, and `config/users.json` / `config/apikeys.json` if present | `hot_reload.interval_seconds` |
| `S3SyncManager` | `s3`, `azure`, `gcs` | `config/tools` → `reload_all_tools`; `config/prompts` → prompts `reload` | `storage.s3.sync_interval` (default 60 s), used for **all** cloud backends |
| Prompts auto-refresh | any | full reload of prompts through storage | 600 s |

How `S3SyncManager` works: at start it pulls every object under the watched prefixes into
`cache_dir`. Each later cycle lists the prefix, compares each object's modified time with the
last value seen, re-downloads new or changed objects, and fires the callback once per prefix
when anything changed. It runs in a daemon thread named `s3-sync`.

Behaviour you should expect on a cloud backend:

- **One full reload after start.** The first poll has no remembered timestamps, so it treats
  every object as changed and reloads tools and prompts once, about `sync_interval` seconds
  after startup.
- **Deletions are not detected on their own.** Removing an object does not trigger a reload.
  A deleted tool disappears at the next full reload: when another tool file is added or
  changed, or when an admin calls `POST /api/admin/tools/reload`. A deleted prompt disappears
  at the next prompts auto-refresh.
- The docs viewer needs no reload because it reads the store on every request.

> `sajha/core/reload_manager.py` also defines a `ReloadManager` abstraction
> (`LocalReloadManager` / `S3ReloadManager`). Nothing in the server starts it. The live
> mechanisms are the ones in the table above.

---

## Migrating from local to a bucket

1. **Copy only what goes through storage**, under the configured `prefix`. Do not
   bulk-copy `config/`, because it contains `application.yml` and other local-only files that
   may hold secrets.

   ```bash
   # S3 (prefix sajha/)
   aws s3 sync ./config/tools   s3://my-sajha-config/sajha/config/tools
   aws s3 sync ./config/prompts s3://my-sajha-config/sajha/config/prompts
   aws s3 sync ./docs           s3://my-sajha-config/sajha/docs

   # Azure
   az storage blob upload-batch --account-name <acct> -d sajha-config \
       --destination-path sajha/config/tools -s ./config/tools
   # ...repeat for config/prompts and docs

   # GCS
   gcloud storage rsync -r ./config/tools gs://my-sajha-config/sajha/config/tools
   # ...repeat for config/prompts and docs
   ```

   Copying `data/tool_search_index.json` is optional. It is rebuilt when missing.
2. **Install the SDK** for the backend.
3. **Switch the backend.** Edit `storage.backend` and the backend block, or use the
   `${VAR:default}` placeholders shown above. Then restart.
4. **Verify.** The startup log shows `Storage backend initialized: S3StorageBackend` (or the
   Azure or GCS class) and `Object-store sync manager active for ...`. `/admin/tools` lists the
   expected tools, and `/help/guides` lists the guides.
5. **Keep state off the bucket.** The database, cache, and OAuth key stay on local disk or
   EFS (or PostgreSQL).
6. **Multi-instance with MCP Studio.** Studio writes the tool JSON to the bucket, so every
   instance sees it. It writes the `.py` implementation to the local `sajha/tools/impl/`. Put
   that directory on shared EFS, or other instances will log a load error for the new tool.
   Studio's "already exists" check also looks only at the local disk.

---

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| `SAJHA_STORAGE_BACKEND=s3` set, but the log says `LocalStorageBackend` | The shipped YAML defines `storage.backend`, so the env fallback never applies. Use `${SAJHA_STORAGE_BACKEND:local}` in the YAML (see [Environment variables](#environment-variables-how-overrides-actually-work)). |
| `Storage backend init failed, falling back to local filesystem` | The constructor raised an error, such as a missing SDK (`ImportError` names the package) or Azure with neither `connection_string` nor `account_url`. The server keeps running on the local backend. |
| No tools load on a cloud backend | The bucket is empty, the prefix is wrong, or the credentials lack `List`. The objects must be at `<prefix>/config/tools/*.json`. Check the startup line `Loading tools from 'config/tools' via ...`. |
| Bucket edits take a while to appear | Polling cadence is `storage.s3.sync_interval` (there are no push notifications). Lower it, or call `POST /api/admin/tools/reload`. |
| A tool deleted from the bucket is still listed | Deletions alone do not trigger a reload (see [Hot reload](#hot-reload-per-backend)). Call `POST /api/admin/tools/reload`. |
| Tool JSON loads but the class fails to import on another instance | The Studio `.py` exists only on the instance that generated it. Share `sajha/tools/impl/` via EFS. |
| `database is locked` or a corrupt SQLite file on a shared mount | Never put SQLite on an object store. On EFS, prefer a single writer, or switch `db.type` to `postgresql`. |
| Setting `ai.tool_search.persist: false` still writes `data/tool_search_index.json` | The flag is read as a string and passed through `bool()`, so any non-empty value counts as true. Use the `bm25` embedder (nothing is persisted) if you need no index file. |
| A guide is missing from `/help/guides` | Only `*.md` under `docs/` (recursive, excluding `docs/archive/` and `README.md` files) are listed, and on a cloud backend they must be in the bucket under `<prefix>/docs/`. |

---

## Design (for contributors)

```
StorageBackend (ABC)                list_files, read/write bytes|text, exists, delete,
 │                                  get_local_path, get_modified_time (+ read_json/write_json)
 ├── LocalStorageBackend            filesystem / EFS (default, no SDK)
 └── _ObjectStorageBackend          prefix, cache mirror, recursive listing, sync_prefix
       ├── S3StorageBackend         boto3
       ├── AzureBlobStorageBackend  azure-storage-blob (+ azure-identity)
       └── GCSStorageBackend        google-cloud-storage
S3SyncManager                       cloud hot reload (poll → cache → reload callbacks)
init_storage(config) / get_storage()   factory and process-wide singleton
write_tool_config(path, cfg)           Studio helper → 'config/tools/<basename>'
```

Each object store implements six primitives: `_fetch_bytes`, `_store_bytes`,
`_object_exists`, `_delete_object`, `_list_keys`, `_object_mtime`. If `get_storage()` is
called before `init_storage()`, it returns a `LocalStorageBackend('.')`. New code that reads
or writes read-mostly assets should go through `get_storage()` with storage-relative paths,
not `open()`.

---

## Planned (not yet built)

These items come from the former storage roadmap. Each one was checked against the code and is
not implemented today.

- **Push-based cloud reload.** Bucket event notifications (S3 → SNS/SQS or EventBridge, and
  equivalents) to replace polling.
- **DuckDB reading object storage directly.** Allow `data.duckdb.dir` to be an `s3://` URI
  read via DuckDB's `httpfs` extension. Today the data directory is scanned with `os.listdir`
  and must be local.
- **Studio `.py` propagation without EFS.** Write generated implementations to the backend
  and sync them into a cache directory on `sys.path`.
- **Per-cloud identity setup guides.** Step-by-step IAM role, managed identity, and workload
  identity setup in the deployment guides, especially for Azure and GCS, which have no
  deployment guide yet.
- **Guardrails and CI.** A check that fails on new direct `open('config/...')` IO in migrated
  subsystems, and storage-backend tests in CI (`moto` for S3, injected clients or emulators
  such as Azurite, fake-gcs-server, or MinIO for Azure and GCS).
- **Migrating the remaining direct file IO** (for example plugins under `config/plugins`) onto
  `get_storage()`.
- **An `fsspec`-based backend** for other targets (HTTP, FTP, HDFS), behind the same
  `StorageBackend` interface.

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
