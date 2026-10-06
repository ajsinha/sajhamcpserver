# MCP Studio Script Tool Creator Guide

The Script Tool Creator (`/studio/script`) turns a script into an MCP tool. The tool takes an array of string arguments, runs the script with its interpreter and returns STDOUT, STDERR and the exit code.

Where Studio lives, the common create → preview → deploy workflow, where generated files are stored, hot reload and permissions are covered once in the [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md).

---

## Supported script types

The form has a button for each of the following types:

| Type (`script_type`) | File extension | Command used to run it | Shebang added if missing |
|----------------------|----------------|-----------------------|--------------------------|
| `bash` (default) | `.sh` | `/bin/bash` | `#!/bin/bash` |
| `shell` | `.sh` | `/bin/sh` | `#!/bin/sh` |
| `python` | `.py` | `python3` | `#!/usr/bin/env python3` |
| `node` | `.js` | `node` | `#!/usr/bin/env node` |
| `perl` | `.pl` | `perl` | `#!/usr/bin/env perl` |
| `ruby` | `.rb` | `ruby` | `#!/usr/bin/env ruby` |

The interpreter must be installed on the server and on its `PATH`. The generator also knows a `powershell` type (`.ps1`, run with `pwsh -File`), but the form has no button for it.

---

## Form fields

### Basic information

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| Tool Name | Yes | – | Lowercase letters, digits and underscores. It must not start with a digit. It names the config, script and wrapper files. |
| Category | No | `Script` | The form sends it, but it is not written into the generated config. |
| Description | Yes | – | |
| Tags | No | – | Type a tag and press Enter. |

### Script content

You can paste the code into the **Script Code** editor, or drag and drop a file onto the page (`.sh`, `.bash`, `.py`, `.js`, `.pl`, `.rb` and `.ps1` are accepted). Script content is required.

Arguments reach the script as ordinary command-line arguments: `$1`, `$2`, … in shell, and `sys.argv[1:]` in Python.

### Execution settings

| Field | Default | Allowed range | Notes |
|-------|---------|---------------|-------|
| Timeout (seconds) | 30 | 1–300 (checked by the generator) | Passed to `subprocess.run(timeout=...)`. |
| Max Arguments | 10 | 0–100 | Becomes `maxItems` on the `args` array. |
| Working Directory | empty | – | Used as `cwd` for the process. If you leave it empty, the script runs in the server process's current directory. |
| Environment Variables | none | – | Key/value rows. They are merged over the server's environment. |
| Capture STDERR | on | – | When off, `stderr` is returned as an empty string. |

### Tool literature (AI context)

Optional free text that helps an AI client decide when to use the tool. It is stored as `literature` in the generated config.

### Quick examples

The sidebar has four examples you can load: **System Information** (Bash), **File Search** (Bash), **JSON Processor** (Python) and **Log Analyzer** (Python).

### Preview and Deploy

**Preview Tool** shows the generated config and the Python wrapper. **Deploy Tool** creates the files. Both buttons send POST requests to `/admin/studio/script/preview` and `/admin/studio/script/deploy`. A successful deploy loads the tool at once; see [Action endpoints](MCP%20Studio%20User%20Guide.md#action-endpoints-deploy-load-and-delete).

---

## Generated files

A script tool produces three files:

| File | Location |
|------|----------|
| Tool config | `config/tools/<tool_name>.json`, written through the storage backend |
| Script | `config/scripts/<tool_name><ext>`. The script is written to local disk, gets a shebang if it has none, and is marked executable for every script type except PowerShell. |
| Python wrapper | `sajha/tools/impl/<tool_name>_script_tool.py`, class `<ToolName>ScriptTool` |

At runtime, the wrapper looks for the script at `<project root>/config/scripts/<file>`. If it is not there, it falls back to a relative path.

### Input schema

Every script tool has a single optional input:

```json
{
  "type": "object",
  "properties": {
    "args": {
      "type": "array",
      "items": {"type": "string"},
      "maxItems": 10,
      "description": "Array of string arguments to pass to the script"
    }
  },
  "required": []
}
```

Every argument is converted to a string before the script runs. If the generator is given argument descriptions, the `args` description becomes `Arguments: [0] ..., [1] ...`. The Studio form has no field for these descriptions.

### Output shape

```json
{
  "stdout": "...",
  "stderr": "...",
  "exit_code": 0,
  "success": true
}
```

`success` is true only when the exit code is 0. The wrapper returns its own exit codes in these cases:

| `exit_code` | Meaning |
|-------------|---------|
| `-1` | The script timed out. |
| `-2` | The script file or the interpreter was not found. |
| `-3` | Any other execution error. The message is in `stderr`. |

If you want structured data, print JSON to STDOUT and let the caller parse it.

### Config format

The generated config sets `implementation` to the wrapper's dotted class path, `sajha.tools.impl.<tool_name>_script_tool.<ToolName>ScriptTool`, like every other tool, and keeps the script settings under `script`. Configs written by earlier releases, where `implementation` was an object, still load: the registry maps them to the same wrapper module.

---

## Security notes

- The generator does **not** scan script content for dangerous commands. It runs whatever you deploy, with the server process's user and permissions.
- Arguments are passed as an argument list (`subprocess.run([...])`, no shell), so they cannot inject shell syntax into the command line. Your script must still treat `$1` and the other arguments as untrusted.
- Environment variable values are written in plain text into the generated wrapper file. Do not put secrets there unless the file is protected.
- Limit who can reach Studio. See the permissions section of the [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md).

---

## Troubleshooting

| Symptom | Cause |
|---------|-------|
| `Timeout must be between 1 and 300 seconds` | The timeout is outside the range the generator accepts. |
| `Invalid script type` | `script_type` is not one of the types above. |
| `exit_code: -2`, `Script file not found` | The script is not in `config/scripts/`, or the interpreter is not installed. |
| `exit_code: -1` | The script ran longer than the timeout. |
| Tool does not appear after deploy | See [the known issue](#known-issue-the-config-format-does-not-match-the-registry) above, and check the tool errors on the Tools admin page. |

---

## Related documentation

- [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md)
- [Storage Guide](../getting-started/Storage%20Guide.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
