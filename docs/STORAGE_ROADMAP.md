# Storage Abstraction Roadmap

SAJHA routes IO through a pluggable storage backend (`sajha/core/storage.py`) so the
same build runs on-prem (local filesystem) or on AWS (S3). This document records what
has shipped and the prioritized path to full adoption.

## Guiding principle: S3 is object storage, not a filesystem

Split IO into two classes and treat them differently:

| Class | Examples | Target |
|---|---|---|
| **Read-mostly assets** | tool JSON configs, prompts, docs/markdown, reference CSVs, DuckDB source data | **Object store** (`backend: s3`/`azure`/`gcs`) — read-through cache for real-file needs |
| **Mutable state** | SQLite `sajha.db`, audit log, output cache, sessions | **NOT S3.** EFS mount (POSIX path) or a managed service (RDS / DynamoDB / ElastiCache) |

"EFS" is not a third backend — it is a normal mount the `local` backend reads as an
ordinary path. Combining S3 (for assets) with EFS (for state) is a *deployment*
arrangement, not a single storage mode.

## Done (v5.3.0) — least-risky slice + multi-cloud backends

- **Config block** `storage:` in `application.yml` (`backend: local|s3|azure|gcs`, `base_dir`, per-backend `s3.* / azure.* / gcs.*`), with env overrides (`SAJHA_STORAGE_BACKEND`, `SAJHA_S3_BUCKET`, `AZURE_STORAGE_CONNECTION_STRING`, `GOOGLE_CLOUD_PROJECT`, …).
- **Startup init**: `init_storage(pc)` runs in `_init_managers` before tools/prompts load; `get_storage()` is available app-wide. Default `local` is a transparent filesystem wrapper — zero behaviour change on-prem, and it needs none of the cloud SDKs.
- **Four backends, one interface**: `LocalStorageBackend` (default) plus **S3**, **Azure Blob**, and **GCS** object stores sharing an `_ObjectStorageBackend` base (prefix namespacing, local read-through cache, recursive listing, `get_local_path`). Each object store implements only six primitives; cloud SDKs are lazy-imported.
- **First migrated reader**: the docs viewer (`/docs`, `/docs/view/...`) now reads through `get_storage()` — listing and content both. Added a path-traversal guard.
- **Contract fix**: `LocalStorageBackend.list_files` aligned to object-store semantics — **recursive listing, `pattern` matched against the filename**.
- **Validated**: S3 via `moto`; Azure + GCS via real-SDK API introspection + injected-client logic tests; local default proven to boot with all cloud SDKs blocked. S3 `exists()` no longer logs tracebacks on expected-missing objects, and `endpoint_url` (MinIO/R2/Wasabi) is supported.

## Roadmap (prioritized)

### 1. Migrate `tools_registry` config reads (highest signal) — ✅ DONE (v5.3.0)
- `load_all_tools` enumerates via `get_storage().list_files('config/tools', '*.json')` and reads via `get_storage().read_json(rel)`. ✓
- The loader (`load_tool_from_config`) now accepts a **logical path** (storage-relative string, `Path`, or filename), normalized internally; all callers updated. ✓
- `register_tool_from_dict(config, source)` extracted as the shared register path (also fixed a latent two-arg `plugins.py` bug). Config writes (`_save_tool_config`) go through `write_json()`. ✓
- Implementation classes resolve by **dotted module path** via `importlib` and ship with the package, so they import locally regardless of where the JSON lives — `get_local_path()` materialization is reserved for the future case of custom `.py` tools stored in the backend. ✓
- Verified end to end: real tool configs uploaded to a mocked S3 bucket load and instantiate. **"Tool configs live in S3" works.**

### 2. Migrate `prompts_registry` reads — ✅ DONE (v5.3.0)
Reads (`_load_all_prompts_internal`) list/read through storage; writes (`create_prompt`/`update_prompt`) via `write_json()`; `delete_prompt` via `delete()`. Auto-refresh reloads from the active backend.

### 3. MCP Studio writes — ✅ DONE (v5.3.0)
All eight generators write tool/config JSON via the shared `write_tool_config()` storage helper. Generated `.py` implementations stay local (importlib needs a module on the path); on multi-instance cloud, place that dir on shared EFS — see item 6.

### 4. Object-store hot-reload activation — ✅ DONE (baseline, v5.3.0)
- `S3SyncManager` starts at app startup when `backend` is a cloud store, watching `config/tools` + `config/prompts`, polling every `sync_interval`s, mirroring changes to cache, and firing `reload_all_tools` / `reload`. The registry's local poller is gated off on cloud so exactly one mechanism runs. Verified via mocked S3 (initial cache sync + change-triggered callback). ✓
- **Upgrade (future)**: S3 event notifications → SNS/SQS or EventBridge → push reload (lower latency, no polling cost).

### 5. DuckDB / OLAP via native httpfs
DuckDB reads `s3://` directly through its `httpfs` extension — pass the URI through and
configure credentials once; do **not** route DuckDB through `get_local_path()`/cache.
Set `${data.duckdb.dir}` to an `s3://...` URI in that deployment.

### 6. Studio `.py` propagation for multi-instance cloud
Generated tool `.py` files are written locally for `importlib`. For multi-instance cloud
deployments either (a) put the generated-impl dir on shared EFS, or (b) write the `.py` to
the backend and sync it into a cache dir placed on `sys.path`. Single-instance and
local/EFS deployments work today.

### 6. Mutable-state placement (architectural decision)
- **SQLite `sajha.db`** → never on S3. Use an EFS mount (`db.path`) or switch to `db.type: postgresql` → **RDS** (already supported).
- **Audit log** → DB-backed (RDS) or CloudWatch/DynamoDB.
- **Output cache** → local EBS/ephemeral or ElastiCache; not S3 (latency).
- **Sessions** → already stateless (cookie/JWT). No change.

### 7. Credentials & compatible targets — DONE for the basics
- S3: default boto3 chain → **IAM role** (no secrets in YAML); `endpoint_url` for MinIO / R2 / Wasabi. ✓
- Azure: connection string (env) or `account_url` + **managed identity** (DefaultAzureCredential). ✓
- GCS: **Application Default Credentials** / workload identity. ✓
- Remaining: document the IAM/role/identity setup per cloud in the deployment guides.

### 8. Polish & guardrails
- `S3StorageBackend.exists()` no longer logs a traceback on the expected "object missing" case — returns `False` quietly. ✓ (Apply the same care to Azure/GCS `_object_exists`, which already swallow quietly.)
- Add a test/pre-commit check that fails on new direct `open('config/...')` / `Path(...).read_text` in migrated subsystems, to prevent drift back to direct IO.
- Promote the in-session validation to CI: `moto` for S3, injected-client tests for Azure/GCS; optionally Azurite / fake-gcs-server / MinIO containers for real-emulator integration tests.

### 9. Future: fsspec option
S3, Azure Blob, and GCS are now native backends. If *other* backends are ever needed
(HTTP, FTP, HDFS) or tighter pandas/pyarrow/DuckDB interop is wanted, re-implement an
object backend's internals on top of `fsspec` **without changing the `StorageBackend`
interface** — callers are unaffected. Not needed today.

## Remaining direct-IO call sites (for tracking)

~69 direct `open()` / `Path.read_text` sites remain, concentrated in `core` (11),
`studio` (8), `tools` (4), `db` (3). Migrate in the order above (reads before writes,
assets before state). The SQLite/audit/cache writers stay on a real filesystem until
their managed-service target (item 6) is decided.
