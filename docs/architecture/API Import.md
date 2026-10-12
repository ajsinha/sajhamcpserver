# SAJHA MCP Server — API Import (OpenAPI, Swagger and GraphQL)

API Import turns an API description into a reviewed set of tools in one pass: an
OpenAPI 3.x or Swagger 2.0 document (a URL, an uploaded file or pasted text), or a
GraphQL endpoint read by introspection. Someone with Studio access previews every operation the
document describes, chooses which become tools, sets the credentials and the base URL,
test-calls one, and deploys the selection. The tools are live at once and behave like
every other registry tool: listed by `tools/list` on both protocol eras, shown on the
Tools page, offered to Ask SAJHA and usable in composites, with the same access policy,
argument validation, cache, circuit breaker, metrics and audit.

This document owns the topic: the design, what was built and its limits. The page is
**Studio → Import an API** (`/studio/api-import`, Studio access: admin or the `studio` permission); the hands-on walkthrough is
[Tutorial 19](../tutorials/TUTORIAL_19_import_an_openapi_spec.md); the configuration keys
and their defaults are in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#api_import); the
terms are in the [Glossary](../../GLOSSARY.md). The code is `sajha/api_import/`.

---

## 1. Shape

```
 source        URL ──► SSRF-guarded fetch (fetch.py)        upload / paste ──┐
                                   │                                         │
 parse         JSON or YAML ─► Swagger 2.0? convert to 3.0 (swagger2.py) ◄───┘
               $ref resolution, local and remote (refs.py) · 3.0 → JSON Schema 2020-12 (schema.py)
               GraphQL: introspection result (graphql.py)
                                   │
 plan          one entry per operation: tool name, inputSchema, outputSchema, annotations,
 (service.py)  flags (unsupported body, name conflict), diff against the last import
                                   │   the administrator selects, names, sets auth + server
 deploy        one JSON tool config per operation in config/tools/<folder>/ (storage backend;
               folder: the request's "folder", else the one recorded, else the prefix)
               + the import record in config/api_imports/<api_id>.json
                                   │   hot-loaded into the registry
 execute       ImportedAPITool (executor.py): one generic class, configured per tool;
               file bodies (bodies.py), opt-in page following (paging.py)
```

No Python is generated. Every imported tool has the same implementation,
`sajha.api_import.executor.ImportedAPITool`, and an `api_import` block in its JSON config
that says how to make the HTTP call. Nothing user-written runs, so these tools need no
sandbox, and a fix to the executor reaches every imported tool at once. (The REST
creator generates a Python module per tool; its HTTP code was not reused because it
builds the request in generated source.)

## 2. Parsing

* **Formats.** JSON or YAML (`yaml.safe_load`). `openapi: 3.0.x` and `3.1.x` are read
  natively; `swagger: "2.0"` is converted to the 3.0 shape first (below). Anything else is
  refused with a message naming what was found. The document size is capped
  (`api_import.max_spec_bytes`).
* **`$ref`.** Every reference is inlined, so each tool's schema is self-contained (MCP
  clients do not resolve references). Local pointers (`#/components/schemas/Pet`),
  relative documents (`common.yaml#/Error`, resolved against the spec URL) and absolute
  URLs are followed. Remote documents are fetched through the same SSRF guard as the spec
  itself, at most `api_import.max_ref_documents` of them. A reference cycle is cut where
  it closes: the inner occurrence becomes `{}` (anything) with a `$comment` naming the
  reference, so a recursive `Category.parent` is still described one level deep. A
  relative reference in an uploaded document (no URL to resolve against) is reported as
  an error, and so is a document the guard refuses or that cannot be read: the operations
  that use it are flagged with the reason and cannot be selected.
* **Schema dialect.** Tool schemas are JSON Schema 2020-12 (the dialect MCP and
  `BaseMCPTool.validate_arguments` use). OpenAPI 3.1 schemas already are; 3.0 schemas are
  converted: `nullable: true` → a `"null"` member in `type`, boolean
  `exclusiveMinimum`/`exclusiveMaximum` → the numeric form, `example` → `examples`,
  Swagger `type: file` → `string` with `format: binary`; `discriminator`, `xml`,
  `externalDocs` and `x-*` extensions are dropped. In an input schema, properties marked
  `readOnly` are removed (the server sets them); in an output schema, `writeOnly` ones.
* **Swagger 2.0 conversion.** `host` + `basePath` + `schemes` → `servers`;
  `definitions` → `components/schemas` (every `$ref` rewritten); `in: body` →
  `requestBody` for each `consumes` type; `in: formData` → an
  `application/x-www-form-urlencoded` body (or `multipart/form-data` when a field is a
  file); `collectionFormat` → `style`/`explode`; response `schema` → `content` for each
  `produces` type; `securityDefinitions` → `securitySchemes` (`basic` → HTTP basic,
  OAuth2 `application` flow → client credentials, `accessCode` → authorization code).
  Shared `#/parameters/...` and `#/responses/...` are inlined. Remote references
  (`common.yaml#/definitions/Error`, `#/parameters/Limit` or `#/responses/Problem` in
  another document) are bundled before the conversion (`swagger2.bundle`): each
  referenced document is fetched once through the SSRF guard (within
  `api_import.max_ref_documents` documents of at most `api_import.max_spec_bytes` each),
  the target is copied into the spec's own `definitions`, `parameters` or `responses`
  under a fresh name, and references inside the copied part are bundled the same way
  (a cycle ends at the name already given; nesting deeper than 64 levels is left as it is).
  The bundled spec then converts like a single-file one.
* **Untrusted text.** Summaries, descriptions and schema descriptions are what a model
  reads when it picks a tool, so they pass through the federation screen
  (`sajha/federation/security.py::screen_text`/`screen_schema`): control characters
  stripped, length capped, prompt-injection markers replaced. A screened operation is
  flagged in the preview.

## 3. Operation → tool

| Part | Rule |
|---|---|
| Name | `<prefix>_<operationId>` in snake case; without an `operationId`, the method and path (`GET /pets/{petId}` → `get_pets_by_petid`). Lowercase letters, digits and underscores, 3–64 characters, never `__` (the Studio rule, a subset of the MCP name rule; `__` is reserved for namespaced tools). A name longer than 64 is cut and given an 8-character hash suffix. Duplicates within one import get `_2`, `_3`. |
| Prefix | Per API; it is also the API's id (`api_id`). Default: the spec title, sanitised. |
| Title, description | `summary`, and `summary` + `description` + `METHOD /path`, screened. |
| Parameters | Every path, query, header and cookie parameter becomes a top-level property of `inputSchema`, its schema converted, `required` kept (path parameters are always required), `enum`, `format`, `default` and `description` carried over. Path-level parameters merge with operation-level ones (the operation wins). A property name that is not `[A-Za-z0-9_.-]{1,64}` (some model APIs reject others) is sanitised, and the same name in two locations is disambiguated (`id`, `id_header`); the config keeps the mapping back to the wire name. |
| Request body | One property, `body` (`request_body` if a parameter is already called `body`), holding the body schema; required when the spec says so. JSON (`application/json`, `*+json`) is preferred, then `application/x-www-form-urlencoded`, then `text/plain`, then `multipart/form-data`, then a binary body (`application/octet-stream`, or any other media type whose schema is a binary string or absent, such as `image/png`). In a multipart body each binary property (`format: binary` or `base64`, `contentMediaType`, `contentEncoding`, Swagger `type: file`) becomes a **file value**, an array of them an array of file values; a binary body is one file value ([§5.1](#51-file-arguments)). Any other body (XML with an object schema, say) is flagged and the operation cannot be selected. |
| Output | `outputSchema` is an envelope, always an object (MCP requires one): `{"status": <HTTP status>, "body": <2xx JSON schema>, "next_page": <URL, when the response has a Link rel="next">}`; an operation that follows pages adds `pages`, `items`, `truncated`, `stopped` and `next_arguments` ([§5.2](#52-following-pages)). The first 2xx response with JSON content gives `body`'s schema (nested deeper than 8 levels is cut to `{}`); a 204 or non-JSON response leaves it open. |
| Annotations | `readOnlyHint: true` for GET, HEAD and OPTIONS; `destructiveHint: true` for DELETE, PUT and PATCH, `false` for POST; `idempotentHint: true` for PUT and DELETE; `openWorldHint: true` for every imported tool (it reaches an external system); `title` from `summary`. |
| Pagination | A query parameter named like a pager (`page`, `per_page`, `limit`, `offset`, `cursor`, `page_token`, `after`, ...) is noted in the description and the config (`api_import.pagination`); the executor returns `next_page` from a `Link: <...>; rel="next"` header. Following pages is off unless it is turned on for the operation ([§5.2](#52-following-pages)). |

### Large specs

A filter narrows the operations before anything else: tags (any of), HTTP methods, and a
path substring or glob; deprecated operations can be hidden. A cap,
`api_import.max_tools`, bounds how many tools one API may have: the preview marks the
operations beyond it and a deploy that would exceed it is refused.

### Name collisions

A proposed name that already belongs to a tool not created by this import (another
import, a built-in, a Studio tool) is marked as a conflict and is not selectable until
it is renamed in the preview. An import only ever writes, updates or deletes tool configs
whose `api_import.api_id` is its own.

## 4. Servers, authentication, limits

* **Base URL.** The administrator picks one of the spec's `servers` and fills in its
  variables (defaults and `enum` from the spec), or types a base URL. A relative server
  URL (a path with no host) is resolved against the spec URL; an uploaded spec with only relative
  servers needs a base URL. A path-level `servers` entry overrides the API's base URL for
  that path.
* **SSRF guard.** The spec URL, every remote `$ref` document, GraphQL endpoints, OAuth
  token URLs and every call an imported tool makes go through one guard
  (`sajha/api_import/fetch.py`): http(s) only, no credentials in the URL, the host must
  match `api_import.allowed_hosts` when set, and every address it resolves to must pass
  `address_allowed` (the guard shared with OAuth CIMD fetches, webhooks and federation):
  public addresses only unless `api_import.allow_localhost` (loopback) or
  `api_import.allow_private_networks` (RFC 1918 / ULA, never link-local, so never cloud
  metadata). The connection is pinned to the vetted address (no DNS-rebinding window),
  TLS still verifies the real host name, proxies from the environment are not used, and a
  redirect is followed only for GET and only after the new URL passes the guard again
  (at most 3). The checks run at deploy time and again on every call.
* **Credentials.** Each scheme the spec declares can be given credentials as
  **secret references** (`env:NAME`, `file:/path`, `db:llm_providers/<type>`), the same
  references federation and the LLM providers use. Resolved values are never written to a
  tool config, never logged, and masked in error text.

  | Scheme | Configuration |
  |---|---|
  | `apiKey` in header, query or cookie | `value_ref` |
  | HTTP bearer | `token_ref` |
  | HTTP basic | `username`, `password_ref` |
  | OAuth 2.0 client credentials | `token_url` (from the spec), `client_id`, `client_secret_ref`, `scope`; the token is cached until shortly before it expires and fetched again once on a 401 |
  | Per-user OAuth (authorization code) | Bound to the caller's connected account when the connected-accounts feature is installed (`sajha.accounts`), detected at run time: the tool config carries `auth.connected_account` and the token is the calling user's. Without that feature, the scheme can only be satisfied with a static bearer token. |

  An operation is called with the first of its `security` alternatives whose schemes all
  have credentials. A scheme added by hand (for a spec that declares none, or for GraphQL)
  applies to every operation.
* **Timeouts and size.** `api_import.timeout_seconds` per call (overridable per import);
  the response body is read up to `api_import.max_response_bytes`.
* **Rate limit.** An optional calls-per-minute limit per API, counted per process, so a
  model cannot hammer an upstream; a 429 from the upstream is reported with its
  `Retry-After`.

## 5. Execution and errors

`ImportedAPITool.execute` builds the request from the arguments (validated against
`inputSchema` by `BaseMCPTool` before it runs): path parameters percent-encoded into the
path, query parameters serialised by `style`/`explode` (`form`, `spaceDelimited`,
`pipeDelimited`, `deepObject`), header and cookie parameters, the body as JSON, a form,
text, `multipart/form-data` or raw bytes. A 2xx answer is returned as the envelope above (JSON parsed, otherwise text). Any
other status raises, so MCP returns `isError: true` with `HTTP <status> <reason> from
<METHOD> <path>` and the first 500 characters of the body; a timeout, a connection
failure and a refused address do the same with their own message. Failures count toward
the tool's circuit breaker like any tool's.

### 5.1 File arguments

A file value is an object with exactly one of:

| Field | Meaning |
|---|---|
| `content_base64` | The bytes, base64 (the URL-safe alphabet is accepted too). |
| `text` | The content as UTF-8 text. |
| `path` | A file in the storage backend, under one of `api_import.file_roots`. |

plus an optional `filename` and `content_type` (guessed from the file name when absent). In
a multipart body a file part is sent with `Content-Disposition: form-data; name=...;
filename=...` and its content type (the value's, else the spec's `encoding.contentType`,
else `application/octet-stream`); an object or array field is sent as a JSON part, anything
else as a text part. A binary body is sent with the spec's media type, or the value's
`content_type` when the spec gives a wildcard.

* **Paths.** `api_import.file_roots` lists storage-backend folders a `path` may name; it is
  empty by default, so file content travels inline only. A root containing `{user}` is
  per caller: `uploads/{user}` lets user `alice` send `uploads/alice/...` and nothing else,
  and a caller the server cannot identify cannot use it. A path must be relative and
  without `..`; on the local storage backend a symbolic link that leads out of its root is
  refused. Anyone allowed to call the tool may send any file under a shared root, so
  choose roots with that in mind.
* **Size.** The whole request body (every part together) is capped at
  `api_import.max_upload_bytes`; a larger one is refused before any connection is made.
  The request then goes through the SSRF guard like every other call.

### 5.2 Following pages

Off by default. On the import request (the **Pages** column of the preview, or the
`pagination` object of the API: operation key → block) a GET operation can be given a
`paginate` block; it is written into the tool config and kept in the import record, so a
re-import keeps it.

| Field | Meaning |
|---|---|
| `mode` | `link` (the `Link: <...>; rel="next"` header), `next_url` (a URL in a body field), `cursor` (a token in a body field sent back as a query parameter), `page` (a page-number parameter plus one), `offset` (an offset parameter advanced by the rows received) |
| `items` | Dot path to the row array in the body; empty: the body itself when it is an array, else the first of `items`, `data`, `results`, `values`, `records`, `entries` that is one |
| `next_field` | `next_url` and `cursor`: dot path to the next URL or token (for example `links.next`, `meta.next_cursor`) |
| `cursor_param`, `page_param`, `offset_param` | The query parameter to send; guessed from the operation's pager parameters when omitted, and it must be one of its query parameters |
| `max_pages`, `max_items` | Per-operation caps; never above `api_import.pagination_max_pages` and `api_import.pagination_max_items` |

One call fetches the first page, then the next ones until there is no next page, a page is
empty, or a cap is reached; the rows are merged into the first page's body at the `items`
path. Every page is a separate guarded request with the credentials and counts toward the
API's rate limit. A next URL is checked against the SSRF guard before it is followed, and it
must keep the first request's origin (scheme, host and port) so credentials never travel
to another host; one that fails either check is not requested. The answer then says how
far it got: `pages`, `items`, `truncated` (more rows exist than were collected), `stopped`
(why following ended early: a refused or foreign next URL, a repeated page, a failed
page), and, when a cap cut it short, `next_page` (the next URL) or `next_arguments` (the
arguments that continue from there).

## 6. GraphQL

The endpoint is read with the standard introspection query (sent with the configured
credentials), or an introspection result is uploaded. Every field of the query type and
of the mutation type becomes one tool (`<prefix>_<field>`):

* **Variables.** Each argument becomes a property; `NON_NULL` → required, `LIST` →
  array, `Int` → integer, `Float` → number, `String`/`ID` → string, `Boolean` → boolean,
  enums → `enum`, input objects → nested objects (5 levels deep), custom scalars open.
* **Selection set.** Generated to `api_import.graphql_depth` levels (default 2): scalar and
  enum fields; object fields that need no required arguments, recursively; `__typename`
  plus inline fragments for unions. The document is stored in the tool config and can be
  read there.
* **Annotations.** Queries are `readOnlyHint: true`; mutations `destructiveHint: true`.
* **Result.** The envelope's `body` is the field's value. `errors` with no data raise;
  partial data is returned with the `errors` alongside.

## 7. Re-import and versioning

Each import is recorded in `config/api_imports/<api_id>.json` through the storage
backend (no database table): the source, the chosen server, the credential references,
the filter, and for every deployed operation its tool name and a fingerprint (a hash of
the method, path, parameters, body and both schemas). Importing again under the same
prefix shows a diff: **new**, **changed** (fingerprint differs), **unchanged** and
**removed** (in the record, gone from the spec). Deploying updates changed tools in place
(same name, new config, hot-reloaded), adds the selected new ones, and deletes the
removed ones only when they are selected for removal. Deleting an import removes all of
its tools and the record.

## 8. Limits

* Callbacks, webhooks and links are not imported, and neither are GraphQL subscriptions:
  each needs the server to receive or hold a connection, which a tool call does not. They
  are out of scope, not planned.
* Request bodies other than JSON, form, text, multipart and binary (XML with an object
  schema, for example) are not imported. A multipart part's per-part headers
  (`encoding.headers`) are not sent.
* XML responses are returned as text; a binary response is returned as text too (decoded
  with replacement characters), not as a file.
* Per-user OAuth needs the connected-accounts feature; otherwise use a static credential.
* Following pages is for GET operations only, one call at a time (each page is read up to
  `api_import.max_response_bytes`); GraphQL connections (`pageInfo`) are not followed.
* `file_roots` grants by folder, not by file: there is no per-file ownership check beyond
  the `{user}` placeholder.
* Environment proxies are not used for imported calls (the address pin needs a direct
  connection).

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
