# Tutorial 8: Custom Configuration

Run SAJHA from your own YAML file, and override individual settings per environment with variables.

## What you'll learn

- How to start the server with a different config file
- How `${VAR:default}` placeholders and `SAJHA_` environment variables are resolved
- How nested YAML keys map to setting names

## Prerequisites

- A SAJHA checkout ([Tutorial 1](TUTORIAL_01_getting_started.md))

## Steps

### 1. Copy the default config

```bash
cp config/application.yml config/production.yml
```

### 2. Edit the settings

Change whatever you need: `server`, `db`, `mcp`, `cache`, `auth`, `ai`, `storage` and so on. For example, to move the server to another port and require credentials on `/mcp`:

```yaml
server:
  host: ${SERVER_HOST:0.0.0.0}
  port: ${SERVER_PORT:8080}

mcp:
  auth:
    mode: "required"        # quote it: a bare off/on is a YAML boolean
```

### 3. Start the server with it

Use either the command-line flag or an environment variable:

```bash
python run_server.py --config config/production.yml
# or
export SAJHA_CONFIG_FILE=config/production.yml
python run_server.py
```

The startup log confirms which file was loaded:

```
Config:  config/production.yml
Server:  http://0.0.0.0:8080
```

`run_server.py` also accepts `--host`, `--port`, `--log-level`, `--workers` and `--reload`. These flags override the file.

### 4. Use placeholders for environment-specific values

Any YAML value can contain `${VAR}` or `${VAR:default}`. `VAR` is read from the environment, and `default` is used when it is unset:

```yaml
db:
  type: postgresql
  host: ${DB_HOST:localhost}
  port: ${DB_PORT:5432}
```

A `.env` file in the working directory is loaded at startup. Its values never replace variables that are already set.

### 5. Override any key with a `SAJHA_` variable

Settings read through SAJHA's settings layer (`sajha/core/config.py`) can also be overridden directly. Take the dotted key, replace each `.` with `_`, uppercase it and prefix it with `SAJHA_`. These variables take precedence over the YAML file:

| YAML key | Environment override |
|----------|----------------------|
| `server.port` | `SAJHA_SERVER_PORT=9000` |
| `mcp.auth.mode` | `SAJHA_MCP_AUTH_MODE=required` |
| `storage.backend` | `SAJHA_STORAGE_BACKEND=s3` |

Resolution order, highest first:

1. `SAJHA_…` environment variable
2. The YAML value, after `${VAR:default}` substitution
3. The built-in default

Not every section follows this rule exactly: `storage.*` also honours a few shorter names, `ai.*` uses its own `SAJHA_AI_<SECTION>_<FIELD>` form ([Intelligence Layer](../architecture/Intelligence%20Layer.md#4-configuration)), and the `${key}` references inside tool configs read the YAML only, so use a `${VAR:default}` placeholder there. Which reader applies to each key is in the [Configuration Reference](../getting-started/Configuration%20Reference.md#three-readers).

### 6. Understand the flattened keys

Nested YAML is flattened to dot notation, and the code reads settings by these names:

```yaml
ai:
  cache:
    ttl_seconds: 3600      # -> ai.cache.ttl_seconds
db:
  host: localhost          # -> db.host
```

A key with an empty value (`key: ""`) counts as set to the empty string. A key that is absent or null falls back to the built-in default.

## What next

- [Configuration Reference](../getting-started/Configuration%20Reference.md): every key, its default and its reader
- [Storage Guide](../getting-started/Storage%20Guide.md): `storage.backend` (local, s3, azure, gcs)
- [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md): the `mcp:` settings, including authentication
- Next tutorial: [Call SAJHA from the Standard MCP Client](TUTORIAL_09_call_sajha_from_the_standard_mcp_client.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
