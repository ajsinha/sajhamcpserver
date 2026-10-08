# Tutorial 19: Import an OpenAPI Spec

Turn a REST API's OpenAPI description into tools in one pass: run a small petstore API,
import its spec in Studio, set its API key, test an operation, deploy three, and call them
over MCP and from Ask SAJHA. Then change the spec and re-import it. The design (how
operations map to tools, the SSRF guard, the limits) is in
[API Import](../architecture/API%20Import.md).

## What you'll learn

- How to let SAJHA reach an API on the same machine, and why it refuses to by default
- How an OpenAPI operation becomes a tool: name, input and output schema, hints
- How to give an imported API its credential as a secret reference
- How a re-import shows what changed, and updates the tools in place

## Prerequisites

- A SAJHA checkout with its virtual environment, and an admin sign-in
  ([Tutorial 1](TUTORIAL_01_getting_started.md))
- Nothing else: the petstore server is in the repository and uses only the standard library

## Steps

### 1. Run the petstore API

```bash
PETSTORE_KEY=demo-key python sajha/examples/api_import/petstore_server.py --port 8766
```

It serves its OpenAPI 3.0 description at `http://127.0.0.1:8766/openapi.yaml` (its
`servers` entry points at itself) and the API under `/v1`, with three pets in memory.
Because `PETSTORE_KEY` is set, every `/v1` call must carry `X-API-Key: demo-key`, the
`api_key` scheme the spec declares.

### 2. Start SAJHA so it may reach localhost

API Import refuses loopback and private addresses unless told otherwise, so an imported
spec cannot be used to reach internal services. For this tutorial allow loopback, and put
the API key where SAJHA can read it by reference:

```bash
SAJHA_API_IMPORT_ALLOW_LOCALHOST=true PETSTORE_KEY=demo-key python run_sajha_web.py
```

(The keys are in the [Configuration Reference](../getting-started/Configuration%20Reference.md#api_import).)

### 3. Read the spec

Sign in as an administrator and open **MCP Studio → Import an API** (`/studio/api-import`).

1. Leave **OpenAPI 3.x / Swagger 2.0** selected. **Spec URL**:
   `http://127.0.0.1:8766/openapi.yaml`. **Prefix**: `petstore`.
2. Click **Read the API**.

Section 2 shows *Swagger Petstore 1.0.0* and the server `http://127.0.0.1:8766/{basePath}`
with its variable `basePath` (`v1` or `v2`); the effective base URL is
`http://127.0.0.1:8766/v1`. Section 4 lists six operations, all **new**:

| Tool | Operation | Hints |
|---|---|---|
| `petstore_list_pets` | `GET /pets` | read-only, paged (`limit`) |
| `petstore_create_pets` | `POST /pets` | |
| `petstore_show_pet_by_id` | `GET /pets/{petId}` | read-only |
| `petstore_update_pet` | `PUT /pets/{petId}` | destructive, idempotent |
| `petstore_delete_pet` | `DELETE /pets/{petId}` | destructive, idempotent |
| `petstore_upload_pet_image` | `POST /pets/{petId}/image` | flagged: multipart bodies are not supported, so it cannot be selected |

The names come from each `operationId` (`showPetById` → `show_pet_by_id`) after the
prefix; each one can be edited before deploying.

### 4. Give it the API key

Section 3 has one row, `api_key`, already set to **apiKey** in **header** `X-API-Key`
(from the spec). In the value field type `env:PETSTORE_KEY`: a secret reference, not the
key. The tool configs store the reference; the value is read from the environment on each
call and never written anywhere. Typing the key itself is refused.

### 5. Test one operation

In section 5 pick `GET /pets/{petId}`; the arguments box is filled with
`{"petId": 1}`. Click **Call once (not deployed)**:

```json
{"status": 200, "body": {"id": 1, "name": "Rex", "tag": "dog"}}
```

That is the result envelope every imported tool returns: the HTTP status and the parsed
body. Try `{"petId": 99}`: the answer is the error `HTTP 404 Not Found from GET
/pets/{petId}: {"code": 404, "message": "pet 99 not found"}`. Try `{"petId": "one"}`: it
is refused before any call, because `petId` is an integer in the input schema.

### 6. Deploy three tools

Untick everything except `GET /pets`, `GET /pets/{petId}` and `DELETE /pets/{petId}`
(**Select none**, then tick the three), and click **Deploy selected**. The result reads
`petstore: 3 added, 0 updated, 0 removed`, with links to each tool. **Imported APIs** on the
right now lists `petstore` with 3 tools loaded.

Each tool is a JSON config in `config/tools/` (open one from the Tools page, **Config**):
its `inputSchema`, `outputSchema`, `annotations`, and an `api_import` block with the
method, path, server and the credential reference. There is no generated code; every
imported tool runs on one executor.

### 7. Call it over MCP

Any MCP client sees the tools at once. With the `sajha` CLI
([Tutorial 15](TUTORIAL_15_sajha_cli_and_claude_desktop.md)):

```bash
sajha tools call petstore_list_pets --arg limit=2
```

or as raw JSON-RPC:

```bash
curl -s http://localhost:3002/mcp -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"petstore_show_pet_by_id","arguments":{"petId":2}}}'
```

The result carries `structuredContent`
`{"status": 200, "body": {"id": 2, "name": "Tom", "tag": "cat"}}`. `tools/list` shows
`petstore_delete_pet` with `destructiveHint: true`, so well-behaved clients ask before
calling it.

### 8. Ask SAJHA

Open **Ask SAJHA** and ask **Show the petstore pet with petId 1**. With the built-in mock
planner ([Tutorial 10](TUTORIAL_10_ask_sajha.md)) the chain is one link,
`petstore_show_pet_by_id` with `petId=1`, and the answer cites it. Ask **Show the petstore
pet with petId 2** after deploying `petstore_delete_pet` and the planner may also pick the
delete tool: because it is marked destructive, Ask SAJHA stops and shows a confirmation
card instead of running it.

### 9. Change the spec and re-import

Edit `sajha/examples/api_import/petstore.yaml`: under `GET /pets` add a query parameter

```yaml
        - name: owner
          in: query
          schema:
            type: string
```

and save (the server reads the file on every request). In **Imported APIs** click
**Re-import** on `petstore`: the source, prefix, server and credentials are filled in from
the import record and the spec is read again. Now `GET /pets` is **changed**,
`GET /pets/{petId}` and `DELETE /pets/{petId}` are **unchanged**, and the rest are **new**.
The deployed ones are ticked; click **Deploy selected** and `petstore_list_pets` is updated
in place (`0 added, 3 updated`): its input schema now has `owner`. An operation deleted from
the spec would be listed under **Gone from the spec**, with a box to remove its tool.
Undo the edit afterwards.

### 10. Clean up

**Delete** on the `petstore` card removes the three tools and the import record.

## The same from the command line

```bash
sajha studio import-openapi http://127.0.0.1:8766/openapi.yaml --prefix petstore --dry-run
sajha studio import-openapi http://127.0.0.1:8766/openapi.yaml --prefix petstore \
  --auth '{"api_key": {"type": "apiKey", "value_ref": "env:PETSTORE_KEY"}}' \
  --select 'GET /pets' --select 'GET /pets/{petId}' --select 'DELETE /pets/{petId}'
```

`--dry-run` prints each operation, its proposed tool name and status; without it the
selected operations are deployed ([Command Line](../clients/Command%20Line.md)). A local
spec file works the same way, and `--graphql` imports a GraphQL endpoint by introspection.

## What you learned

- A spec URL, an upload or a GraphQL endpoint becomes a reviewed list of operations, each
  with a generated name, JSON Schema input and output, and read-only / destructive hints.
- Credentials are secret references; URLs pass an SSRF guard at import and on every call.
- An import record makes re-importing a diff: new, changed, unchanged and removed.

## Next

- [API Import](../architecture/API%20Import.md): Swagger 2.0 conversion, `$ref` handling,
  OAuth client credentials, per-user connected accounts, GraphQL, and the limits
- [MCP Studio User Guide](../studio/MCP%20Studio%20User%20Guide.md#import-an-api)
- Next tutorial: [Policies, Approvals and a Tamper-Evident Audit](TUTORIAL_20_policies_approvals_and_audit.md)

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
