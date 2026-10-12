# Database Setup

SAJHA keeps users, roles, API keys, sign-in sessions, the audit log, prompts, composite
tools, LLM settings, the database state store, the usage ledger, the connected-accounts
token vault and the SAJHA Net key directory (`sajhanet_api_keys`: the signed API key records of
every instance in the nets this server is in, hashes only, never a raw key;
[SAJHA Net](../architecture/SAJHA%20Net.md) §10.3) in one SQL database (`db.*` in `config/application.yml`). This guide owns how
that database gets its tables: the first install, upgrades, and the helper for both. The
`db.*` keys themselves are in the [Configuration Reference](Configuration%20Reference.md).

There are no migrations. Each database type has one schema file that holds every table,
column, key and index SAJHA uses:

```
db/scripts/sqlite/schema.sql        db/scripts/sqlite/seed.sql
db/scripts/postgresql/schema.sql    db/scripts/postgresql/seed.sql
```

`seed.sql` adds the default roles (`admin`, `user`, `viewer`, `developer`, `llm_author`),
their permissions and the administrator `admin` / `admin123`, flagged so that the first
sign-in must change the password. Users and keys an administrator keeps in the credential
files (`config/users.json`, `config/apikeys.json`) are not in these files; they win over the
database ([Security Model](../security/Security%20Model.md#credential-storage-and-files)).

| | SQLite | PostgreSQL |
|---|---|---|
| Meant for | development, one process, one host | production, several workers, pods or hosts |
| Who creates the tables | SAJHA, at start-up | an operator, once, with `psql`, before SAJHA starts |
| Tables or columns missing at start-up | created from `schema.sql` (missing columns of an existing table are reported) | SAJHA refuses to start (`db.schema_check: strict`) or warns (`warn`) |
| Does SAJHA ever run DDL on it | yes | no |

**Which one.** SQLite for one machine and light load: one file, one writer at a time (SAJHA opens it
with `journal_mode=WAL`, so readers do not wait for the writer, `synchronous=NORMAL` and a 30 s
`busy_timeout`). PostgreSQL for real concurrency: several workers, pods or hosts, sustained writes,
hundreds of calls in flight. The switch is configuration only (`db.type`, or `DB_TYPE` /
`SAJHA_DB_TYPE`, with the connection keys of section 2); the same code and the same pool settings
(`db.pool.*`) serve both. How large the pool should be for a number of workers, and how SAJHA keeps a
connection only while it reads or writes, is in [Scaling and State](../architecture/Scaling%20and%20State.md)
§7; measured numbers for both databases are in its §9.

---

## 1. SQLite (development)

Nothing to do. At start-up SAJHA runs `db/scripts/sqlite/schema.sql` (every statement is
`CREATE ... IF NOT EXISTS`) and, when the database is new, `seed.sql`. An existing database
is never re-seeded, so a deleted `admin` stays deleted.

SAJHA never alters an existing table. A development database older than a column the code
now uses makes start-up stop with the table and column named. For development, recreate
it: delete the file (`db.path`, default `data/sajha.db`) and SAJHA rebuilds and seeds it at
the next start. That is the policy for the development database: drop and recreate on a
schema change, never alter it. The message also prints the `ALTER TABLE ... ADD COLUMN ...`
statement for each missing column, taken from `db/scripts/sqlite/schema.sql`, for a SQLite
database whose data must be kept; SAJHA prints them and never runs them. SQLite cannot add some columns to an existing table (a primary key or unique column, a
non-constant default such as `CURRENT_TIMESTAMP`, `NOT NULL` without a default); such a
statement is printed with a comment saying so, and recreating the file is the way out. When
an old table makes `schema.sql` fail as a whole (an index on a column the table lacks), SAJHA
runs its statements one by one so that missing tables are still created.

## 2. PostgreSQL: first install

SAJHA does not create tables on PostgreSQL. Until they exist it refuses to start, names
what is missing, and prints the `psql` command.

**1. Create the database and the role SAJHA connects as** (DBA):

```sql
CREATE ROLE sajha LOGIN PASSWORD '...';
CREATE DATABASE sajha OWNER sajha;
```

**2. Run the schema file, then the seed file**, as the role that should own the tables:

```bash
psql -v ON_ERROR_STOP=1 -h db-host -U sajha -d sajha -f db/scripts/postgresql/schema.sql
psql -v ON_ERROR_STOP=1 -h db-host -U sajha -d sajha -f db/scripts/postgresql/seed.sql
```

Both files are one transaction each, so a failure leaves nothing half-done, and
`schema.sql` is safe to run again. Run `seed.sql` once, on the new database: running it
later re-creates any default row someone deleted.

Without a checkout, the image prints the files: `python -m sajha.db sql --dialect postgresql`
(add `--seed` for the seed file).

If you run them as another role (a superuser, an owner role), give the application role
its rights afterwards:

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sajha;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sajha;
```

**3. Point SAJHA at it.** Configuration alone switches the database; no code changes. Either
set the connection keys:

```bash
export SAJHA_DB_TYPE=postgresql SAJHA_DB_HOST=db-host SAJHA_DB_PORT=5432 \
       SAJHA_DB_NAME=sajha SAJHA_DB_USER=sajha SAJHA_DB_PASSWORD='...'
```

or give one URL, which replaces every other connection key:
`SAJHA_DB_URL=postgresql+psycopg2://sajha:PASSWORD@db-host:5432/sajha` (put `?sslmode=require`
on it for TLS; `db.ssl` is not read). The short names `DB_TYPE`, `DB_HOST`, `DB_PORT`, `DB_NAME`,
`DB_USER`, `DB_PASSWORD` and `DB_URL` work too when neither the `SAJHA_DB_*` name nor the YAML sets
the key. Always set the database name: the code default is `sajha_mcp`, not the `sajha` used on
this page ([Configuration Reference](Configuration%20Reference.md)). To run the state store on
PostgreSQL as well, add `SAJHA_STATE_BACKEND=database` (it uses this database unless
`state.database.url` names another).

**4. Check, then start SAJHA:**

```bash
python -m sajha.db check          # exit 0: complete; exit 3: something is missing
```

This procedure, exactly as written (`psql -f` of the two files, then the variables above), was run
on PostgreSQL 17.11 (`postgres:17-alpine`): the start-up check passed, and a server on it (with
`state.backend: database`) passed the console check, both MCP conformance suites, and tool calls,
workflows, reports, BI, Ask SAJHA, API keys, audit, notices and the usage reports.

If `state.database.url` points the state store at a different PostgreSQL database, run
`schema.sql` there too (only its `sajha_state` and `sajha_state_events` tables are used).

## 3. The start-up check

On PostgreSQL, before anything else starts, SAJHA compares the database with every table
and column its code uses (the ORM models in `sajha/db/models` and the tables defined beside
the state store, the usage ledger and the token vault). It reads the catalogue; it never
writes.

| `db.schema_check` | Something missing at start-up |
|---|---|
| `strict` (default) | Logs `Refusing to start: database schema is not ready`, the missing tables and columns, and the SQL to run, and exits. Nothing is created. On an empty database the SQL is the two `psql` commands of section 2; otherwise it is the statements for what is missing (section 6, `upgrade-sql`). |
| `warn` | Logs the same message as a warning and starts. Features whose tables are missing fail when used. The `db.schema` system notice shows the same SQL in the console until the schema is complete. |

Missing indexes never stop start-up: SAJHA logs a warning with the `CREATE INDEX` statements
(and raises the `db.schema` notice as a warning) and starts.

When everything is present but the `roles` table is empty, SAJHA starts and warns that
nobody can sign in until `seed.sql` has run.

Set it with `db.schema_check` or `SAJHA_DB_SCHEMA_CHECK`. The same check runs on SQLite
after `schema.sql`.

Tables SAJHA no longer uses (such as `tool_versions` from earlier releases; tool versions live
in `config/tool_versions/*.yaml`) are ignored by the check and never dropped. Drop them by hand
if you want them gone, for example `DROP TABLE tool_versions;`.

## 4. Upgrades

Most releases do not change the schema. One that does says so in its
[CHANGELOG](../../CHANGELOG.md) entry. With the new release's checkout (or image), print the
statements your database needs and run them before the new release serves traffic:

```
python -m sajha.db upgrade-sql > upgrade.sql      # compares the database with schema.sql
less upgrade.sql                                  # review
psql -v ON_ERROR_STOP=1 -h HOST -U USER -d DBNAME -f upgrade.sql
python -m sajha.db check                          # exit 0: the pods will start
```

`upgrade-sql` prints a `CREATE TABLE` (with its indexes) for each missing table,
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` for each missing column and `CREATE INDEX`
for each missing index, each taken from the release's `schema.sql`. SAJHA never runs them.
Re-running the new release's `schema.sql` is also safe and creates any new tables and
indexes, but it never changes a table that already exists, so new columns come from
`upgrade-sql` (or the CHANGELOG's SQL). Schema changes are additive (new tables, nullable columns or columns
with defaults, new indexes), so pods of the old release keep working during a rolling
update; a release that cannot keep to that says so.

Example: the release that adds SAJHA Net identity adds the table `sajhanet_api_keys` and its two
indexes. On PostgreSQL run what `python -m sajha.db upgrade-sql` prints before the new release
starts (SAJHA refuses to start without the table under `db.schema_check: strict`); on SQLite SAJHA
creates it. The table is written only when SAJHA Net is on.

## 5. Deployments

| Recipe | The schema step |
|---|---|
| Helm chart (`charts/sajha`) | `helm install` prints the commands in its notes; pods crash-loop with the refusal message until the schema exists. `database.postgresql.schemaCheck` sets the check. |
| Kustomize (`deployment/k8s`) | Same as the chart (rendered from it). |
| AWS CDK (`deployment/aws`) | `psql` with the two files from a host that reaches RDS. |
| Hetzner (`deployment/hetzner`) | `deploy.sh` starts only PostgreSQL and prints the commands; then `docker compose up -d`. |
| Bare metal (`deployment/baremetal`) | `install.sh` prints the two `psql` commands; run them, then `systemctl start sajha`. |

Details per recipe: [Kubernetes Deployment](Kubernetes%20Deployment.md) and
[`deployment/README.md`](../../deployment/README.md).

## 6. The helper

`python -m sajha.db` reads `db.*` the way the server does (`config/application.yml`,
`SAJHA_CONFIG_FILE`, `SAJHA_DB_*`). It never changes the database. The `sajha` command line
runs it from a server checkout as `sajha db ...` (`--root` or `SAJHA_HOME` names the
checkout).

| Command | What it does | Database access |
|---|---|---|
| `check [--url URL]` | Lists the tables and columns SAJHA uses that the database lacks; exit 3 when any | read |
| `sql [--dialect postgresql\|sqlite] [--seed]` | Prints `schema.sql` (or `seed.sql`) for review and `psql -f` | none |
| `upgrade-sql [--url URL]` (also `sql --missing`) | Compares the database with its dialect's `schema.sql` and prints the DDL that brings it up to date: missing tables, columns and indexes (section 4); exit 3 when there is something to run, 0 when nothing | read |

All take `--scripts-dir` (default `db.scripts_dir`, `db/scripts`).

## 7. Changing the schema

For contributors:

1. Change the model or `Table` in the code, and the same table in **both**
   `db/scripts/postgresql/schema.sql` and `db/scripts/sqlite/schema.sql`. Every statement
   stays `CREATE ... IF NOT EXISTS`.
2. Use each database's types. PostgreSQL: `BOOLEAN` with `TRUE`/`FALSE`, `TIMESTAMPTZ`
   (SAJHA's sessions run in UTC; `connected_accounts` keeps `TIMESTAMP` because its code
   works in naive UTC), `DOUBLE PRECISION`, `BIGINT GENERATED BY DEFAULT AS IDENTITY` for an
   auto-increment key. SQLite: `BOOLEAN` with `1`/`0`, `TIMESTAMP`, `REAL`,
   `INTEGER NOT NULL PRIMARY KEY` for an auto-increment key.
3. In the CHANGELOG's `Unreleased` section, give the SQL an existing database needs for
   the change, for both types.
4. Never create or alter a table from Python code on PostgreSQL. Code may create its own
   tables on SQLite only, and on PostgreSQL only checks that they exist.

`tests/test_db_schema.py` keeps the three in step: it builds SQLite from its file and
compares it with every `MetaData` in the code (tables, columns, types, nullability, keys,
foreign keys, indexes), parses the PostgreSQL file and compares it the same way, and finds
any `Table(` or `__tablename__` the check would miss. With `SAJHA_TEST_POSTGRES_URL` set to
a disposable database it applies the PostgreSQL file to a real server and compares what it
reflects (it drops and recreates that database's `public` schema).

With `SAJHA_TEST_PG_URL` set to a disposable PostgreSQL database, `tests/test_postgresql.py` runs the
repositories (the DAOs of `sajha/db/dao`, the workflow store, the connected-accounts vault,
conversation memory, the audit chain) on it, and `tests/test_state_store.py` runs the state store's
whole contract there as the `database_pg` backend. Each test process builds its own PostgreSQL schema
from the two files with `psql`-equivalent statements and drops it at exit (`tests/pg_support.py`).
Without the variable these tests skip. To run the application tests on PostgreSQL as well, set
`SAJHA_DB_TYPE=postgresql` and `SAJHA_DB_URL` to a database prepared with section 2; tests that build
their own SQLite database still use SQLite.

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Refusing to start: database schema is not ready` | Tables or columns are missing. New database: section 2. Upgrade: run the statements the message prints (`python -m sajha.db upgrade-sql`, section 4). |
| `No roles in the database: nobody can sign in` | `seed.sql` has not run. Run it once. |
| `state.backend database: table(s) sajha_state ... missing` | The state store's database (`state.database.url`) has no schema. Run `schema.sql` there. |
| `Usage ledger off: table obs_usage_events is missing` | The table is missing (`db.schema_check: warn` let SAJHA start). Run `schema.sql`. |
| `table connected_accounts is missing` | Same, for the connected-accounts vault. |
| SQLite start-up names a missing column | The development database is older than the code. Recreate it (delete the file; section 1); to keep its data, run the printed `ALTER TABLE` instead. |
| `indexes of the schema file are missing` | Start-up continues; run the printed `CREATE INDEX` statements. |

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
