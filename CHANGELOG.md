# SAJHA MCP Server — Changelog

---

## v3.1.0 (May 2026) — FastAPI Migration

Complete rewrite from Flask to FastAPI. Every component rebuilt, all documentation rewritten.

### Breaking Changes

- **Framework:** Flask → FastAPI (ASGI). All routes converted from Blueprints to APIRouters.
- **Configuration:** `application.properties` and `server.properties` removed. All config now in `config/application.yml`.
- **Database:** Alembic removed. Schema managed via `db/scripts/001_schema.sql` with `CREATE TABLE IF NOT EXISTS`.
- **Transport:** Socket.IO/WebSocket removed. MCP transport now uses HTTP POST and SSE per MCP specification.
- **Password hashing:** passlib removed, replaced with direct bcrypt (bcrypt 4.x compatibility).
- **Entry point:** `run_server.py` now starts Uvicorn directly. `python run_server.py` is the only command needed.

### New in v3.1.0

- **FastAPI orchestrator:** `SajhaMCPServerWebApp` class in `sajha/app.py` — single entry point, zero inline routes.
- **13 route modules** in `sajha/routes/` with 79+ endpoints.
- **MCP compliance (2025-06-18):** 12 MCP methods fully implemented, 5 capabilities declared.
- **A2A protocol:** Agent card at `/.well-known/agent.json`, task lifecycle endpoints.
- **Reporting:** 7 API endpoints + Chart.js dashboard at `/reports`.
- **497 tools** loaded (up from ~150 in v2).
- **Generic tool pattern:** `FMPGenericTool` and `OpenBBGenericTool` auto-map tool names to API endpoints from JSON configs.
- **YAML-only config:** `config/application.yml` with `${ENV_VAR:default}` substitution and `SAJHA_` env prefix override.
- **SQL-based schema:** 9 tables via `db/scripts/001_schema.sql` + `002_seed.sql`.
- **8 ORM models** and **7 DAO classes** for structured database access.
- **FastAPI auth dependencies:** `get_current_user`, `require_auth`, `require_admin`.
- **SSE transport:** `GET /mcp/sse` + `POST /mcp/message` per MCP specification.
- **Starlette 1.0 TemplateResponse API** — `request` as positional parameter.
- **UI enhancements:** Tool group dropdown, description search with highlighting, clickable provider badges, group column in tables.
- **120 tests** across config, auth, database, and endpoint modules.
- **Zero-dependency client SDK** in `clientsdk/` — Python stdlib only.
- **Documentation rewrite:** All docs rewritten for v3, including architecture, glossary, API reference, README.

### Removed

- `sajha/web/app.py` (v2 Flask backward-compat wrapper)
- `sajha/web/sajhamcpserver_web.py` (v2 Flask SajhaMCPServerWebApp)
- `sajha/web/routes/*.py` (14 Flask blueprint files)
- `alembic.ini` + `alembic/` directory
- `config/application.properties`
- `config/server.properties`
- All `.properties` fallback and parsing code

### Known Issues

- 3 SharePoint tools fail to load (abstract class, `get_input_schema`/`get_output_schema` not implemented).
- `${data.sqlselect.dir}` CSV data files absent in fresh install — tools load but warn.
- Dashboard template escaping edge case for tool descriptions with special characters.

---

## v2.9.8 and Earlier (Flask)

Flask-based implementation with .properties configuration. See git history for detailed v2 changelog.

Key v2 milestones:
- v2.9.8: SharePoint Tool Creator, OLAP Dataset Creator, 150+ tools
- v2.8.x: MCP Studio (Python Code, REST, DB Query, Script, PowerBI, LiveLink creators)
- v2.7.x: Hot-reload system, API key management
- v2.5.x: WebSocket support, prompts management
- v2.0.0: Initial release with MCP compliance, web UI, tool framework

---

*SAJHA MCP Server — Changelog*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
