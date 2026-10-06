# Tutorial 4: Create a Plugin

Package one or more tool configs as a plugin: a directory with a manifest that SAJHA can discover, validate and load as a unit.

## What you'll learn

- The plugin directory layout and the `plugin.json` manifest
- How plugins are discovered, validated and loaded at runtime
- How to unload a plugin

## Prerequisites

- A running server and an administrator JWT, saved as `$TOKEN`. See [Tutorial 1](TUTORIAL_01_getting_started.md), step 8. All `/api/plugins` endpoints require the admin role.
- Write access to the plugins directory. It is set by `config.plugins.dir` in `config/application.yml` and defaults to `config/plugins`.

## Steps

### 1. Create the plugin directory

```
config/plugins/demo-plugin/
├── plugin.json
├── tools/
│   └── demo_pct_change.json
└── requirements.txt        (optional)
```

### 2. Write the manifest

`config/plugins/demo-plugin/plugin.json`:

```json
{
  "name": "demo-plugin",
  "version": "1.0.0",
  "author": "Your Team",
  "description": "A demo tool pack",
  "tools": ["demo_pct_change"],
  "config_keys": []
}
```

| Field | Meaning |
|-------|---------|
| `name`, `version` | Identity. `name` is what you pass to the load and unload endpoints. |
| `tools` | Tool names the plugin provides. Unloading unregisters exactly these. |
| `config_keys` | Environment variables that must be set, or loading fails, e.g. `["BLOOMBERG_API_KEY"]` |
| `min_sajha_version` | Optional minimum server version |
| `checksum` | Optional `sha256:<hex>` over the plugin's files (excluding `plugin.json`). Loading fails on a mismatch. |
| `author`, `description`, `dependencies` | Informational |

### 3. Add tool configs

Put one JSON tool config per tool in `tools/`. The format is the same as a file in `config/tools/` (see [Tutorial 2](TUTORIAL_02_create_a_custom_tool.md)). The `implementation` class must be importable by the server. This example reuses a built-in calculator class under a new name.

`config/plugins/demo-plugin/tools/demo_pct_change.json`:

```json
{
  "name": "demo_pct_change",
  "implementation": "sajha.tools.impl.calc_tools.CalcPercentageChangeTool",
  "description": "Percentage change between two values (demo plugin)",
  "version": "1.0.0",
  "enabled": true,
  "inputSchema": {
    "type": "object",
    "properties": {
      "old_value": {"type": "number"},
      "new_value": {"type": "number"}
    },
    "required": ["old_value", "new_value"]
  },
  "outputSchema": {
    "type": "object",
    "properties": {"result": {"type": "object"}}
  }
}
```

If the plugin has a `requirements.txt`, loading runs `pip install -r requirements.txt` first.

> Only JSON tool configs are supported in `tools/`. The loader also tries to import loose `.py` files from `tools/`, but in the current build that path calls `register_tool` with the wrong arguments and the tools are not registered. Put Python implementations in an importable module and reference them from a JSON config instead.

### 4. Discover the plugin

```bash
curl -s -X POST http://localhost:3002/api/plugins/discover -H "Authorization: Bearer $TOKEN"
# -> {"plugins": [{"name": "demo-plugin", "version": "1.0.0", "tools": ["demo_pct_change"], ...}]}
```

### 5. Load it

```bash
curl -s -X POST http://localhost:3002/api/plugins/demo-plugin/load -H "Authorization: Bearer $TOKEN"
# -> {"name": "demo-plugin", "installed": true, "enabled": true, "tools_registered": 1, "error": ""}
```

If validation fails, for example because of a missing `tools/` directory, an unset `config_keys` variable or a checksum mismatch, `enabled` is `false` and `error` explains why.

The plugin's tools are now registered like any other tool. They appear in MCP `tools/list` and can be called with `tools/call`, or through `POST /api/tools/execute`.

### 6. Check and unload

```bash
curl -s http://localhost:3002/api/plugins -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://localhost:3002/api/plugins/demo-plugin/unload -H "Authorization: Bearer $TOKEN"
```

Plugins in the plugins directory are also discovered and loaded automatically when the server starts.

## What next

- [Architecture](../architecture/Architecture.md)
- [Client SDK Guide](../clients/Client%20SDK%20Guide.md)
- Next tutorial: [Connect the Python SDK](TUTORIAL_05_connect_the_python_sdk.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
