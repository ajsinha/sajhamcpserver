# Prompts Management Guide

## Table of Contents

1. [Overview](#overview)
2. [Where Prompts Live](#where-prompts-live)
3. [Prompt JSON Format](#prompt-json-format)
4. [Arguments and Variable Substitution](#arguments-and-variable-substitution)
5. [Bundled Prompts](#bundled-prompts)
6. [Web UI](#web-ui)
7. [REST API](#rest-api)
8. [MCP Access](#mcp-access)
9. [Creating a Prompt](#creating-a-prompt)
10. [Troubleshooting](#troubleshooting)
11. [Page Glossary](#page-glossary)

---

## Overview

SAJHA keeps a library of reusable, parameterised prompt templates. Each prompt is one JSON file. The server loads them into the prompts registry (`sajha/core/prompts_registry.py`) and serves them three ways:

- **Web UI**: browse, view, test, create, edit and delete prompts (`/prompts`, `/admin/prompts`).
- **REST API**: `/api/prompts/...` endpoints for listing, fetching, rendering and admin CRUD.
- **MCP**: the standard `prompts/list` and `prompts/get` methods on `POST /mcp`, so any MCP client can discover and use the same prompts.

Rendering is plain placeholder substitution. A prompt does not call an LLM; it produces the text that a client sends to one.

---

## Where Prompts Live

Prompts are read from the directory set by `config.prompts.dir` in `config/application.yml` (default `config/prompts`). All prompt I/O goes through the storage abstraction (`sajha/core/storage.py`). With the default `local` backend this is a directory on disk. With `s3`, `azure` or `gcs` the same relative path is used inside the bucket or container. See the [Storage Guide](../../getting-started/Storage%20Guide.md) for backend configuration.

- Every `*.json` file in that directory is one prompt.
- The prompt name is the file's `name` field if present, otherwise the file name without `.json`.
- A file without `prompt_template` is skipped and logged as a loading error.

**Reloading.** You do not need to restart the server when prompts change:

- The registry rescans the directory every 10 minutes.
- The config hot-reload watcher (`hot_reload.enabled`, `hot_reload.interval_seconds`) reloads prompts when a prompt file changes.
- On the `s3`/`azure`/`gcs` backends, the object-store sync manager polls the prompts prefix and reloads on change.
- Creating, updating or deleting a prompt through the UI or REST API takes effect immediately.

When the prompt set changes, MCP clients with a push channel get `notifications/prompts/list_changed` (see [MCP Access](#mcp-access)).

---

## Prompt JSON Format

```json
{
  "name": "code_review",
  "description": "Comprehensive code review assistant that analyzes code quality, security, and performance",
  "prompt_template": "Review the following {language} code:\n\n```{language}\n{code}\n```\n\nProvide a comprehensive code review covering ...",
  "arguments": [
    { "name": "code",     "description": "The code to review", "required": true },
    { "name": "language", "description": "Programming language of the code (e.g., python, javascript, java)", "required": true }
  ],
  "metadata": {
    "category": "development",
    "tags": ["code", "review", "quality", "security"],
    "author": "admin",
    "version": "1.0"
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `prompt_template` | Yes | The template text, with `{argument_name}` placeholders. |
| `name` | No | Prompt name. Defaults to the file name. Names created through the API must match `^[A-Za-z0-9_-]{1,100}$`. |
| `description` | No | Shown in the UI and in MCP `prompts/list`. |
| `arguments` | No | List of `{ "name", "description", "required" }` objects. |
| `metadata.category` | No | Grouping used by the UI filters. Default `general`. |
| `metadata.tags` | No | List of tags used by the UI filters. |
| `metadata.author` | No | Default `system`. |
| `metadata.version` | No | The prompt's own version label. Default `1.0`. |

The server adds `metadata.created_at` and `metadata.updated_at` when a prompt is created or updated through the UI or API. Usage counters (`usage_count`, `last_used`) are kept in memory only and reset when the server restarts.

---

## Arguments and Variable Substitution

Rendering replaces each `{name}` in `prompt_template` with the string value of the argument called `name`.

- **Required arguments.** If an argument marked `"required": true` is missing or `null`, rendering fails with `Required argument '<name>' is missing`.
- **Optional arguments are not defaulted.** If an optional argument is left out, its `{placeholder}` stays in the output as literal text. Write templates so that this still reads sensibly, or have clients always pass every argument.
- **Substitution only.** There are no conditionals, loops or filters (the template is not Jinja2). Every `{x}` whose name matches a supplied argument is replaced, including arguments that are not declared in `arguments`.
- **Literal braces.** Braces that do not match an argument name are left alone, so JSON or code samples in the template are safe as long as they do not contain `{argname}` for a real argument.

---

## Bundled Prompts

These prompts ship in `config/prompts/`:

| Prompt | Category | Required arguments | Optional arguments |
|--------|----------|--------------------|--------------------|
| `code_review` | development | `code`, `language` | none |
| `bug_diagnosis` | development | `bug_description`, `error_message`, `code`, `language` | `version`, `platform` |
| `documentation_generator` | development | `content`, `doc_type` | `audience`, `format`, `detail_level` |
| `data_analysis` | analytics | `data`, `dataset_description` | `analysis_focus` |
| `business_plan` | business | `business_name`, `description`, `industry`, `target_market`, `objectives` | `plan_type` |
| `content_writing` | content | `topic`, `content_type`, `audience` | `tone`, `length`, `key_points`, `context` |

---

## Web UI

| Page | Path | Who |
|------|------|-----|
| Prompts Library: cards with category and tag filters | `/prompts` | Any signed-in user |
| Filter by category | `/prompts/category/{category}` | Any signed-in user |
| Filter by tag | `/prompts/tag/{tag}` | Any signed-in user |
| Prompt detail: information, template, arguments, and (for admins) an Edit Prompt JSON editor with Save and Delete | `/prompts/{name}` | Any signed-in user; editing needs admin |
| Test Prompt: fill in arguments and see the rendered output | `/prompts/{name}/test` | Any signed-in user |
| Create New Prompt: form plus JSON editor | `/prompts/create` | Admin |
| Manage Prompts: admin table with delete | `/admin/prompts` | Admin |

---

## REST API

Authenticated endpoints accept a browser session, `Authorization: Bearer <token>` (a JWT from `POST /api/auth/login` with `{"user_id": "...", "password": "..."}`), or `X-API-Key: <key>`.

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/prompts/list` | None | Summary of every prompt: `name`, `description`, `category`, `tags`, `author`, `version`, `argument_count`, `usage_count`, `last_used`. |
| GET | `/api/prompts/{name}` | None | Full prompt: `name`, `description`, `template`, `arguments`, `metadata`. 404 if unknown. |
| POST | `/api/prompts/{name}/render` | User | Body `{"arguments": {...}}`. Returns `{"success": true, "rendered": "..."}`, or 400 with `error`. |
| POST | `/api/prompts/create` | Admin | Body: `name` plus the prompt fields. Writes `<name>.json` to the prompts directory. |
| POST | `/api/prompts/{name}/update` | Admin | Body: the prompt fields. The template may be sent as `prompt_template` or `template`. |
| POST | `/api/prompts/{name}/delete` | Admin | Deletes the prompt file. |

Create and update accept `description`, `prompt_template` (or `template`), `arguments` and `metadata`. From `metadata`, only `category`, `tags`, `author` and `version` are stored. Write endpoints return `{"success": true, "message": "..."}` or `{"success": false, "error": "..."}`.

```bash
# Log in and keep the token
TOKEN=$(curl -s -X POST http://localhost:3002/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"admin","password":"<password>"}' | jq -r .token)

# List and fetch
curl -s http://localhost:3002/api/prompts/list
curl -s http://localhost:3002/api/prompts/code_review

# Render
curl -s -X POST http://localhost:3002/api/prompts/code_review/render \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"arguments": {"language": "python", "code": "def add(a, b): return a + b"}}'

# Create (admin)
curl -s -X POST http://localhost:3002/api/prompts/create \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
        "name": "email_composer",
        "description": "Draft a professional email",
        "prompt_template": "Write a {tone} email to {recipient} about {subject}.",
        "arguments": [
          {"name": "recipient", "description": "Who the email is for", "required": true},
          {"name": "subject",   "description": "What it is about",     "required": true},
          {"name": "tone",      "description": "e.g. formal, friendly", "required": true}
        ],
        "metadata": {"category": "communication", "tags": ["email"]}
      }'

# Delete (admin)
curl -s -X POST http://localhost:3002/api/prompts/email_composer/delete -H "Authorization: Bearer $TOKEN"
```

Adjust host and port to your deployment.

---

## MCP Access

MCP clients use the standard prompt methods on `POST /mcp`. For transports, protocol versions, sessions and authentication, see the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md).

**`prompts/list`** returns each prompt's `name`, `description` and `arguments` (`name`, `description`, `required`). The template text is not included.

```json
{"jsonrpc": "2.0", "id": 1, "method": "prompts/list", "params": {}}
```

**`prompts/get`** renders the prompt with the given arguments and returns it as a single user message:

```json
{"jsonrpc": "2.0", "id": 2, "method": "prompts/get",
 "params": {"name": "code_review", "arguments": {"language": "python", "code": "def add(a, b): return a + b"}}}
```

```json
{"jsonrpc": "2.0", "id": 2, "result": {
  "description": "Comprehensive code review assistant that analyzes code quality, security, and performance",
  "messages": [{"role": "user", "content": {"type": "text", "text": "Review the following python code: ..."}}]
}}
```

An unknown prompt name or a missing required argument returns JSON-RPC error `-32602` (invalid params) with the reason in `message`.

**Change notifications.** When the prompt set changes (file edit, reload, or UI/API create/update/delete), the server publishes `notifications/prompts/list_changed` to clients that have a push channel. Which clients can receive it depends on the protocol era and transport; the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md) explains this.

---

## Creating a Prompt

Three ways, all producing the same JSON file:

1. **Web UI.** Open `/prompts/create` as an admin, fill in the form or the JSON editor, and save. You are taken to the new prompt's detail page.
2. **REST API.** `POST /api/prompts/create` as shown above.
3. **File.** Put a `<name>.json` file in the prompts directory (or the matching bucket prefix). It is picked up by hot reload or the periodic rescan.

Then check it on `/prompts/{name}/test`, or render it with `POST /api/prompts/{name}/render`.

Guidelines:

- Give each prompt a specific `description`. MCP clients show it to users and models when they choose a prompt.
- Mark an argument `required` unless the template still reads correctly with the literal `{placeholder}` left in it.
- Use argument names that are unlikely to appear in braces elsewhere in the template.
- Keep `category` values consistent, because the UI filters on exact matches.

---

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| Prompt does not appear | The file is not valid JSON, lacks `prompt_template`, or is outside `config.prompts.dir`. Loading errors are logged as `Error loading prompt from <file>`. Validate with `python -m json.tool <file>`. |
| New file not picked up yet | Wait for hot reload or the 10-minute rescan, or create the prompt through the UI/API instead. |
| `Required argument '<x>' is missing` | Pass every argument marked `required` (REST: in `arguments`; MCP: in `params.arguments`). |
| `{placeholder}` appears in the output | An optional argument was not supplied, or the argument name does not exactly match the placeholder (names are case-sensitive). |
| 401 / 403 on create, update or delete | These need an admin user. Render needs any authenticated user. |
| `Name must be letters, digits, _ or - (max 100)` | Rename the prompt; the name becomes a file name. |
| `Prompt '<name>' already exists` | Use `/api/prompts/{name}/update`, or choose another name. |

---

## Page Glossary

- **Prompt template**: Text with `{argument}` placeholders that is filled in at render time.
- **Prompts registry**: The server component that loads, reloads, renders and saves prompts.
- **Render**: Substituting argument values into a template to produce the final prompt text.

*For complete definitions, see the [Glossary](../../../GLOSSARY.md).*

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
