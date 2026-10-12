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

Setting up a pod identity for the bucket on EKS, AKS or GKE (IRSA, Entra Workload ID,
Workload Identity Federation) is in
[Kubernetes Deployment](Kubernetes%20Deployment.md#bucket-access-on-eks-aks-and-gke).

---

## What goes through storage

These subsystems call `get_storage()`. When you switch backends, they read and write the
selected store.

| Subsystem | Storage path (relative to `base_dir` or bucket `prefix`) | Operations |
|-----------|----------------------------------------------------------|------------|
| Tools registry | `config/tools/*.json` and `config/tools/<folder>/*.json` (one level; the listing is recursive) | list and read at load; admin config edits and enable/disable persist with `write_json` |
| Prompts registry | `config/prompts/*.json` | list and read at load; create and update use `write_json`; delete uses `delete` |
| MCP Studio generators | `config/tools/<name>.json` | the generated tool **JSON** is written through `write_tool_config()` |
| Guide pages (`/help/guides`, `/help/guides/{name}`) | `docs/**/*.md` except `docs/archive/` and `README.md` files | recursive listing (reused for 30 s) and a read per page; a guide is found by its file name |
| Semantic tool search vector index | `data/tool_search_index.json` | loaded at start and rewritten after re-embedding; only when `ai.tool_search.embedder` is `gateway` (the default `bm25` builds nothing to persist) and `ai.tool_search.persist` is true |
| Document search sources, uploads and memory-store index | `ai.rag.sources[].path`, `ai.rag.uploads_dir` (default `data/rag/uploads`), `ai.rag.index_path` (default `data/rag/index.json`) | sources listed and read at each index build; uploads written and deleted; the index file only with `ai.rag.store: memory` and `ai.rag.persist` true ([Intelligence Layer](../architecture/Intelligence%20Layer.md#stores)) |
| Federation store | `federation.state_path` (default `config/federation/federation.json`) | upstreams added on `/admin/federation` and every item's approval; read at start, rewritten on change ([Federation](../architecture/Federation.md)) |
| DuckDB data folder written `storage://<prefix>` | `<prefix>/*.csv`, `*.tsv`, `*.parquet`, `*.json` (direct children only) | listed and staged into a local temporary directory at each load of the sandbox ([below](#duckdb-data-on-the-storage-backend)) |
| Studio-generated modules and scripts (cloud backends) | `studio/modules/<module>.py`, `config/scripts/<file>` | published when the tool JSON is written; materialised locally before the tool loads ([below](#studio-modules-without-a-shared-file-system)) |
| Plugins (cloud backends) | `config.plugins.dir` (default `config/plugins`) | mirrored into `cache_dir` and loaded from there at start ([below](#plugins-on-a-cloud-backend)) |

The tools and prompts paths come from `config.tools.dir` / `config.prompts.dir` (defaults
`config/tools`, `config/prompts`), taken relative to the working directory.

### Read from local disk regardless of backend

These parts are always read from local disk, even when the backend is a cloud store:

- `config/application.yml` itself (and any file passed with `--config`).
- Tool **implementation** classes (`sajha.tools.impl.*`), imported from the installed package.
- The local backend's Studio-generated `.py` files (`sajha/tools/impl/`) and Script-tool
  scripts (`config/scripts/`): on the local backend they already are the storage. On a cloud
  backend they are also kept in the bucket ([below](#studio-modules-without-a-shared-file-system)).
- A DuckDB data directory that is a plain path (the shipped `./data/duckdb`), the SQL-select
  data directory (`data.sqlselect.dir`) and the advanced OLAP tool's data folder. These are
  scanned with `os.listdir`.
- The other read-mostly folders that still use direct file IO: `config/mcp_servers.json`,
  `mcp.apps.dir`, the tool-quality folders (`config/tool_tests`, `config/evals`,
  `config/tool_versions`), shipped workflows (`config/workflows`) and `config/olap/datasets.json`.

### What must not go through storage

Object stores have no atomic append, rename, or file locking. Keep the following on a real
filesystem (local disk, EBS, EFS) or a managed service, and never on S3, Azure Blob, or GCS:

| State | Where it lives | Placement |
|-------|----------------|-----------|
| Database (SQLite `data/sajha.db`, from `db.path`) | file on disk, via SQLAlchemy | real filesystem or EFS, or set `db.type: postgresql` (e.g. RDS). SQLite on an object store will corrupt. |
| Audit log | `audit_log` table in the same database | follows the database |
| Document search index (sqlite_vec store) | `ai.rag.stores.sqlite_vec.path` (default `data/rag/vectors.db`), its own SQLite file | real filesystem; on ephemeral disk a restart re-embeds every document |
| Tool output cache | `cache.dir` (default `data/cache`) | local or ephemeral disk |
| Snapshots of users, keys and tools | `snapshots.dir` (default `data/snapshots`), owner-only files renamed into place | real filesystem; shared (EFS) when several hosts should continue one chain ([Policy and Audit](../architecture/Policy%20and%20Audit.md#75-snapshots-of-users-api-keys-and-tools)) |
| OAuth signing key | `mcp.auth.builtin.signing_key_path`, default `<data.dir>/oauth/signing_key.pem` | real filesystem, and shared (EFS) when several instances must sign with the same key |
| MCP sessions, MCP tasks, OAuth codes, rate limits | the state store (`state.backend`, [Scaling and State](../architecture/Scaling%20and%20State.md)) | `memory` (default): lost on restart, not shared between workers. `redis` or `database`: shared; task records durable in the database |

### Temporary files

Everything SAJHA writes for a moment goes to one folder, `app.tmp_dir` (env `SAJHA_APP_TMP_DIR`;
empty, the default: the system temp directory, `/tmp` on Linux). The keys and their checks are in
the [Configuration Reference](Configuration%20Reference.md#app). At start-up SAJHA makes it the
process's temp folder, so it holds:

| What | Name | Gone |
|------|------|------|
| Anything that uses Python's `tempfile` (SAJHA's code and its libraries) | the caller's | when the caller removes it |
| Throw-away document indexes (`ai.rag.persist: false` with the sqlite_vec store) | `sajha-rag-p<pid>-*.db` | when the index closes, or at exit |
| DuckDB spill files (every DuckDB connection SAJHA opens) | `sajha-duckdb-p<pid>-<n>/` | DuckDB removes the folder when the connection closes |
| DuckDB files staged from a storage backend (when `data.duckdb.stage_dir` is empty) | `sajha-duckdb-stage-p<pid>-*/` | after each load |
| Sandbox runs (when `sandbox.work_dir` is empty) and their egress proxy sockets | `sajha-sbx-*/`, `sajha-sbx-*.egress/` | after the run |
| Warm sandbox containers' egress proxy sockets | `sajha-pool-p<pid>-*.egress/` | when the container is removed |
| Plugin packages being fetched or replaced | `sajha-plugin-p<pid>-*/`, `sajha-plugin-old-p<pid>-*/` | after the install |
| SAJHA Net mutual-TLS key material, for an instant | `sajha-net-mtls-p<pid>-*.pem` | at once |
| The object-storage read-through cache (when `storage.*.cache_dir` is empty) | `sajha-cache/` | never (it is a cache) |
| The temp files of processes SAJHA starts (sandbox launchers, `isolation: none` stdio upstreams, Playwright's Chromium) | theirs | theirs (they get `TMPDIR`, `TEMP` and `TMP`) |

Code inside a sandbox does not see this folder: its `TMPDIR` is its own work directory.

A crash can leave entries behind. At server start-up SAJHA removes entries named `sajha-*` whose
newest file is older than `app.tmp_max_age_hours` (24) and whose owning process (the `-p<pid>-` in
the name) no longer runs. It never touches anything else in the folder, nor `sajha-cache`.

On Kubernetes the chart mounts an `emptyDir` at `/tmp`, so the default works with a read-only root
file system; to use another volume, mount it and point the key at it
([Kubernetes Deployment](Kubernetes%20Deployment.md#temporary-folder)).

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
    cache_dir: ""                 # empty: <app.tmp_dir>/sajha-cache
    sync_interval: 60            # cloud hot-reload poll seconds (all cloud backends)
  azure:
    container: ""
    account_url: ""              # https://<acct>.blob.core.windows.net (managed identity)
    connection_string: ""        # alternative auth
    prefix: "sajha/"
    cache_dir: ""                 # empty: <app.tmp_dir>/sajha-cache
  gcs:
    bucket: ""
    project: ""
    prefix: "sajha/"
    cache_dir: ""                 # empty: <app.tmp_dir>/sajha-cache
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

So `SAJHA_STORAGE_BACKEND=s3 SAJHA_S3_BUCKET=my-bucket python run_sajha_web.py` starts the S3
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
  state that cannot live on an object store (the SQLite DB, the OAuth key, the cache) and,
  with the local backend, the Studio-generated `.py` files every instance must import. Point
  `base_dir`, `db.path`, or `data.dir` at the mount as needed.
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
    cache_dir: ""                 # empty: <app.tmp_dir>/sajha-cache
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
    cache_dir: ""                 # empty: <app.tmp_dir>/sajha-cache
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
    cache_dir: ""                 # empty: <app.tmp_dir>/sajha-cache
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
  `cache_dir` is never evicted, and every backend defaults to `sajha-cache` in SAJHA's temporary
  folder ([Temporary files](#temporary-files)).
- **Modified time** comes from object metadata (`LastModified` / `last_modified` /
  `updated`). If it cannot be read, it is `0.0`.

---

## Hot reload per backend

Only one tool-reload mechanism is active per deployment.

| Mechanism | Backend | What it watches | Interval |
|-----------|---------|-----------------|----------|
| Tools registry poller | `local` only (skipped on cloud) | `config/tools/*.json` and `config/tools/<folder>/*.json` on disk (new, modified, deleted, removed folders) plus `sajha/tools/impl/*.py` | 5 s (fixed) |
| `ConfigReloader` / `HotReloadManager` | any (local files only) | local tool JSON, tool modules, prompt JSON, and the persistent API key file (`config.apikeys.path`) if present, which is also re-read on change when a key is looked up | `hot_reload.interval_seconds` |
| `S3SyncManager` | `s3`, `azure`, `gcs` | `config/tools` → `reload_all_tools`; `config/prompts` → prompts `reload` | `storage.s3.sync_interval` (default 60 s), used for **all** cloud backends; `storage.events.healthy_poll_interval` while push is healthy |
| Bucket event listener (`storage.events.provider`) | `s3`, `azure`, `gcs` | every object event in the bucket under `prefix`; watched paths go to `S3SyncManager.notify` | push: seconds ([Push-based reload](#push-based-reload)) |
| Prompts auto-refresh | any | full reload of prompts through storage | 600 s |

How `S3SyncManager` works: at start it pulls every object under the watched prefixes into
`cache_dir`. Each later cycle lists the prefix, compares each object's modified time with the
last value seen, re-downloads new or changed objects, notes objects that are gone (a removed tool
folder is its objects gone), and fires the callback once per prefix when anything changed. It runs in a daemon thread named `s3-sync`.

Behaviour you should expect on a cloud backend:

- **One full reload after start.** The first poll has no remembered timestamps, so it treats
  every object as changed and reloads tools and prompts once, about `sync_interval` seconds
  after startup.
- **Deletions are detected.** An object that was listed before and is gone now counts as a
  change, so a deleted tool (or a removed tool folder) disappears at the next poll, or at once
  with push-based reload.
- The docs viewer needs no reload because it reads the store on every request.

> `sajha/core/reload_manager.py` also defines a `ReloadManager` abstraction
> (`LocalReloadManager` / `S3ReloadManager`). Nothing in the server starts it. The live
> mechanisms are the ones in the table above.

## Push-based reload

Polling delays a bucket change by up to `sync_interval` and costs a listing of every watched
prefix each cycle. With `storage.events.provider` set, a listener thread
(`sajha/core/storage_events.py`) reads the bucket's event notifications from a queue and hands
each changed path to the sync manager at once (`S3SyncManager.notify`). The sync manager
refreshes the cached copy (or drops it for a delete) and fires the same reload callback the
poll fires, once per watched prefix per batch, so the tools and prompts registries publish the
same change-bus events (`notifications/tools/list_changed` and the rest) as after a poll.

| `storage.events.provider` | Queue | Notification path | SDK |
|---|---|---|---|
| `sqs` | an SQS queue | S3 event notifications to SQS directly, through SNS (`Type: Notification` is unwrapped), or an EventBridge rule (`source: aws.s3`, `Object Created` / `Object Deleted`) | `boto3` |
| `azure_queue` | an Azure Storage Queue | an Event Grid subscription on the storage account (`Microsoft.Storage.BlobCreated` / `BlobDeleted`, Event Grid or CloudEvents schema, plain or base64 JSON) | `azure-storage-queue` (+ `azure-identity` for `account_url`) |
| `pubsub` | a Pub/Sub pull subscription | a GCS bucket notification on a topic (`OBJECT_FINALIZE`, `OBJECT_DELETE`, `OBJECT_ARCHIVE`, `OBJECT_METADATA_UPDATE`) | `google-cloud-pubsub` |
| `auto` | the row for the backend | `s3` → `sqs`, `azure` → `azure_queue`, `gcs` → `pubsub` | |

How it behaves:

- **Polling stays on.** Push is an accelerator, never the only path. While the listener is
  healthy (its last receive succeeded within three waits, at least a minute) the sync manager
  polls every `storage.events.healthy_poll_interval` seconds (default 600) instead of
  `sync_interval`; as soon as it is not healthy, polling returns to `sync_interval`.
- **Only this bucket and prefix.** An event for another bucket or container, or for a key
  outside `prefix`, is ignored. Every message is acknowledged after it is applied, including
  one that cannot be read, so a malformed message never loops.
- **Order-safe.** A "deleted" path that still exists is treated as changed, and a "changed"
  one that is gone as deleted, so late or reordered events (a versioned GCS overwrite sends
  `OBJECT_ARCHIVE` and `OBJECT_FINALIZE`) end in the bucket's real state.
- **Every path, not only the watched ones.** Each batch also goes to the path listeners: a
  workflow file trigger watching the prefix polls at its next tick instead of waiting out its
  `interval_seconds` ([Workflows](../architecture/Workflows.md#9-limits)), and a DuckDB
  `storage://` folder reloads.
- **Several workers.** A queue delivers each message to one consumer. With a shared state
  store (`state.backend: redis` or `database`) the worker that received a batch relays its
  paths to every other worker (state-store channel `storage_events`). Without one, give each
  replica its own queue or subscription (SNS fan-out, one Event Grid subscription per queue,
  one Pub/Sub subscription per replica), or rely on polling for the others.
- **Never a startup error.** A missing SDK or incomplete settings (no queue URL, queue name or
  subscription) log an info line and raise the system notice `storage.events:<provider>`
  (`info`); receives that fail three times in a row raise it as `warning` until one succeeds
  ([System Notices](../architecture/System%20Notices.md#4-sources)). The listener is per worker
  and ignored on the local backend.

```yaml
storage:
  backend: s3
  events:
    provider: sqs                     # or auto
    healthy_poll_interval: 600
    sqs:
      queue_url: https://sqs.us-east-1.amazonaws.com/123456789012/sajha-config-events
```

Setting up the notifications (prefix-filter on your `prefix`; created and deleted events):

- **S3 → SQS.** Create a queue; allow `s3.amazonaws.com` to `sqs:SendMessage` from the bucket's
  ARN in the queue policy; add an event notification on the bucket for `s3:ObjectCreated:*` and
  `s3:ObjectRemoved:*` with prefix `sajha/`. The identity SAJHA runs as needs
  `sqs:ReceiveMessage` and `sqs:DeleteMessage` on the queue. With EventBridge instead: turn on
  "Send notifications to Amazon EventBridge" on the bucket and add a rule
  (`source: aws.s3`, `detail-type: Object Created | Object Deleted`, the bucket name) with the
  queue as target.
- **Azure Blob → Event Grid → Storage Queue.** Create a queue in a storage account; add an
  Event Grid event subscription on the blob account for *Blob Created* and *Blob Deleted*, with
  subject filter `/blobServices/default/containers/<container>/blobs/sajha/` and the queue as
  endpoint. The identity needs *Storage Queue Data Message Processor* on the queue.
- **GCS → Pub/Sub.** `gcloud storage buckets notifications create gs://<bucket>
  --topic=<topic> --object-prefix=sajha/ --payload-format=json`, then a pull subscription on
  the topic. The identity needs *Pub/Sub Subscriber* on the subscription.

## DuckDB data on the storage backend

Write the DuckDB data directory as `storage://<prefix>` (for example
`data.duckdb.dir: storage://data/duckdb`, which every shipped `duckdb_*` tool config references)
and the data files are read through the storage backend, whichever it is. The DuckDB sandbox
copies each file into an in-memory table and then switches off all file and URL access, so the
files are not queried in place: at each load every supported file directly under the prefix is
staged into a temporary directory under `data.duckdb.stage_dir` (SAJHA's temporary folder,
`app.tmp_dir`, when empty), loaded into its table, and the staged copy deleted at once. A file larger than
`data.duckdb.stage_max_file_mb` (256), or one that would pass `data.duckdb.stage_max_total_mb`
(1024) for that load, is skipped and logged. Change detection (the tools' auto refresh) compares
the objects' modified times; a bucket event under the prefix reloads at once. A prefix that is
empty or contains `..` is refused.

## Studio modules without a shared file system

On a cloud backend, writing a tool's JSON through `write_tool_config` also copies the Studio
module it names (`sajha/tools/impl/<module>.py`) to `studio/modules/<module>.py` and a script
tool's script (`config/scripts/<file>`) to `config/scripts/<file>` in the bucket
(`sajha/core/storage_modules.py`). Every generator writes the Python file before the JSON.
Before the tools registry loads a tool whose module has a Studio-generated name (`studio_*`,
`dbquery_*`, `rest_*`, `livelink_*`, `powerbi_*`, `powerbidax_*`, `*_script_tool`; no built-in
module uses these), it fetches the module and the script when the local copy is missing or
older. A module the package directory lacks is written to `<cache_dir>/studio_modules/`, which
is appended to the `sajha.tools.impl` package path: a file in the package always wins, and the
installed package is not written on an instance that did not generate the tool. An edited module
replaces the cached copy, and an already imported one is reloaded. Other names are never
fetched, so a bucket object cannot replace a built-in module. On the local backend all of this
is a no-op.

## Plugins on a cloud backend

On a cloud backend the plugins folder (`config.plugins.dir`, default `config/plugins`) is a
prefix in the bucket. At start, discovery mirrors every object under it into
`<cache_dir>/config/plugins/` (removing mirrored files that are gone from the bucket) and loads
plugins from the mirror, because importlib, the checksum and `requirements.txt` need real files.
An absolute `config.plugins.dir` is taken as a local mount and read directly.

## Testing the backends

`tests/test_storage_emulators.py` runs one contract (list, read, write, JSON, exists, delete,
modified time, the local mirror) on every backend available: the in-memory object store
always, S3 under `moto` (with bucket events through SQS), MinIO, Azurite and fake-gcs-server
when their variables are set. The unit tests (`tests/test_storage_events.py`,
`tests/test_storage_finished.py`) use fake queue clients and an in-memory store and make no
cloud calls. To run the emulator tests in CI, add a job like:

```yaml
  storage-emulators:
    runs-on: ubuntu-latest
    services:
      minio:
        image: bitnami/minio:latest
        env: {MINIO_ROOT_USER: minio, MINIO_ROOT_PASSWORD: minio12345}
        ports: ['9000:9000']
      azurite:
        image: mcr.microsoft.com/azure-storage/azurite
        ports: ['10000:10000']
      gcs:
        image: fsouza/fake-gcs-server
        options: --entrypoint "/bin/fake-gcs-server -scheme http"
        ports: ['4443:4443']
    env:
      AWS_ACCESS_KEY_ID: minio
      AWS_SECRET_ACCESS_KEY: minio12345
      SAJHA_TEST_S3_ENDPOINT: http://127.0.0.1:9000
      SAJHA_TEST_AZURITE: "UseDevelopmentStorage=true"
      STORAGE_EMULATOR_HOST: http://127.0.0.1:4443
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.13'}
      - run: pip install -r requirements.txt -r requirements-dev.txt "moto[s3,sqs]" boto3 azure-storage-blob google-cloud-storage
      - run: python -m pytest -q tests/test_storage_emulators.py tests/test_storage_events.py tests/test_storage_finished.py
```

`tests/test_storage_finished.py` also guards the subsystems that were moved onto storage
(tools and prompts registries, guides, federation store, tool files, planner registry, report
files): a direct `open('config/...')` in one of them fails the run.

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
6. **Multi-instance with MCP Studio.** Studio writes the tool JSON to the bucket, and on a
   cloud backend the module and script too; other instances materialise them when they load the
   tool ([Studio modules](#studio-modules-without-a-shared-file-system)), so no shared file
   system is needed. Studio's "already exists" check looks only at the local disk.
7. **Optionally turn on push-based reload** ([Push-based reload](#push-based-reload)).

---

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| `SAJHA_STORAGE_BACKEND=s3` set, but the log says `LocalStorageBackend` | Backend construction failed and the server fell back to local; the line before it says why (next row). The environment does win over the YAML (see [Environment variables](#environment-variables)). |
| `Storage backend init failed, falling back to local filesystem` | The constructor raised an error, such as a missing SDK (`ImportError` names the package) or Azure with neither `connection_string` nor `account_url`. The server keeps running on the local backend. |
| No tools load on a cloud backend | The bucket is empty, the prefix is wrong, or the credentials lack `List`. The objects must be at `<prefix>/config/tools/*.json` or `<prefix>/config/tools/<folder>/*.json`. Check the startup line `Loading tools from 'config/tools' via ...`. |
| Bucket edits take a while to appear | Without push, the polling cadence is `storage.s3.sync_interval`. Turn on [push-based reload](#push-based-reload), lower the interval, or call `POST /api/admin/tools/reload`. |
| Push is configured but edits still wait for the poll | Look for the notice `storage.events:<provider>` and the log line `Storage events (...) not started`: a missing SDK, an empty queue setting, or failing receives (permissions). Check that the notification's prefix filter matches `prefix`. |
| Tool JSON loads but the class fails to import on another instance | The module is not in the bucket under `studio/modules/` (the tool was generated before this release, or on the local backend). Save the tool again in Studio, or copy the `.py` there. |
| `database is locked` or a corrupt SQLite file on a shared mount | Never put SQLite on an object store. On EFS, prefer a single writer, or switch `db.type` to `postgresql`. |
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
S3SyncManager                       cloud hot reload (poll → cache → reload callbacks; notify() for pushed paths)
storage_events.StorageEvents        bucket event listener (SQS, Storage Queue, Pub/Sub) → S3SyncManager.notify
storage_modules                     Studio modules and scripts: publish to the bucket, materialise locally
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

- **The remaining direct file IO** onto `get_storage()`: the SQL-select and advanced OLAP data
  folders, `config/mcp_servers.json`, `mcp.apps.dir`, the tool-quality folders, shipped
  workflows and `config/olap/datasets.json` (listed under
  [Read from local disk](#read-from-local-disk-regardless-of-backend)).
- **The emulator job in CI.** The tests and the recipe exist ([Testing the
  backends](#testing-the-backends)); `.github/workflows/tests.yml` does not run that job yet, so
  in CI only the in-memory contract and the fakes run.
- **An `fsspec`-based backend** for other targets (HTTP, FTP, HDFS), behind the same
  `StorageBackend` interface.

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
