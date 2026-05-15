# SAJHA MCP Server — Changelog

---

## v5.0.0 (May 2026) — Composition Framework + UX Overhaul

Category-theory-inspired composition, 4 UI themes, full UX redesign, CSS rewrite.

### Composition Framework (from "On the Composability of Intelligence")

- **Kleisli Composition** (`sajha/core/composition.py`): Every tool execution wrapped in `StepResult` envelope carrying value, error, trace, duration, and confidence. Errors short-circuit the pipeline. Traces accumulate across steps. Confidences compound via Giry bind.
- **ParamLens**: Lens-based parameter projection. Child tools receive ONLY mapped fields via `$.field` / `$input.field` syntax. Prevents accidental coupling to upstream output structure.
- **EntropyGuard**: Cumulative confidence tracking with parallel-aware model. Sequential steps multiply (Giry bind). Parallel steps use weakest-link (min). Mixed pipelines combine both. `entropy_threshold` per composite — refuses execution if uncertainty exceeds limit.
- **Tool Confidence Registry**: 497 tools classified by reliability — calculators 1.0, FRED 0.95, FMP 0.93, web crawlers 0.80. Composite results include `_composition.confidence` and `_composition.entropy_bits`.
- **CompositeTool.execute()** rewritten to use composition framework. All composites now return `_composition` metadata block with confidence, entropy, trace, and guard status.

### Client SDK Enhancements

- **Transport Coalgebra**: `TransportCoalgebra` abstract class with `step(input) → (output, new_state)`. `HTTPTransport`, `SSETransport`, `WSTransport` implementations. Enables runtime transport hot-swap.
- **bisimilar()**: Behavioral equivalence testing. Runs same operation sequence against two transports, verifies identical output structure. Proves transport interchangeability.
- **ClientPipeline**: Client-side tool composition. `add_step()` with `$input.` / `$.` param mapping. `execute()` with confidence tracking and entropy guard. Works without server-side composite definitions.

### UX Overhaul (22 recommendations implemented)

- **4 UI Themes**: Light, Dark (landing-page glass-morphism), Wall Street (Bloomberg terminal amber-on-black, Consolas font), Ubuntu (aubergine + orange, Ubuntu font). Variable-driven CSS — 545 lines replaces 4,441.
- **CSS rewrite**: Clean architecture — design tokens → theme definitions (var(--t-*)) → components. Zero hardcoded colors. Every Bootstrap color class overridden for all themes. WCAG AA contrast verified.
- **Landing page**: Standalone dark-navy theme, gradient hero, 9 feature cards, code snippet, stats bar.
- **Login page**: Standalone dark theme matching landing page. Glass-morphism card.
- **Dashboard**: Welcome bar with transport badges, 4 metric cards, quick actions panel, platform stats, status panel, onboarding wizard.
- **Tools list**: Card-grid view toggle, category filter chips (auto-generated from tool data).
- **AI → LLM**: 5 Bootstrap tabs (Providers, Models, Preferences, Semantic Search, Usage). Add Provider form with type-specific fields (Bedrock: region+AWS keys, Azure: deployment+endpoint, Ollama: host+model, Custom: class+JSON).
- **Composite Builder**: Visual SVG flow diagram (updates live), drag-and-drop step reorder.
- **Studio sub-navigation**: Horizontal chip bar across all 10 studio pages.
- **Help page**: Search-within-help, 6 tutorial cards, 5 v4 feature sections.
- **Active nav highlighting**, button press feedback, loading skeletons, keyboard shortcuts (/ = search, Shift+? = help), skip-to-content link, focus-visible outlines, empty state CTAs with action buttons.
- **0 modals** — all replaced with inline forms/banners.
- **table-enhance.js**: Reusable component — search, pagination, rows-per-page for any table via `data-enhance="true"`.
- **Custom SVG icon set**: 8 icons (sajha, mcp, tool, composite, provider, transport, plugin, agent) as inline sprite.

### Infrastructure

- **Deployment restructured**: `aws/` → `deployment/aws/`, added `deployment/hetzner/` (Docker+Caddy+auto-SSL), `deployment/baremetal/` (systemd+Nginx+certbot).
- **AWS CDK** replaces Terraform: `deployment/aws/cdk/sajha_stack.py` (238 lines Python) — VPC, ECS Fargate, RDS, S3, Secrets Manager, CloudWatch dashboard, auto-scaling.
- **Property-driven configuration**: Version, email, author, github, copyright, all paths (data.dir, logging.dir, config.plugins.dir) — all from `config/application.yml`. Footer shows `© {{ app_copyright_years }} {{ app_name }} | {{ app_author }} · Version {{ app_version }}`.
- **PostgreSQL config**: 3 commented-out examples in application.yml (local, AWS RDS, Hetzner managed).
- **Two SQL scripts only**: `001_schema.sql` (19 tables, CREATE IF NOT EXISTS), `002_seed.sql` (INSERT OR IGNORE). No migrations.

### Bug Fixes

- `tool_schema.html` 500 error: `schema_json` passed as separate pre-serialized string, not mutating MCP format dict.
- `tool_enabled` / `tool_version` passed as separate template variables — MCP `to_mcp_format()` dict never modified.
- Help/About/Docs pages made public (`get_current_user` instead of `require_auth`).
- Login POST indentation bug fixed.
- All `ToolsRegistry.get_instance()` calls replaced with `from sajha.app import tools_registry` (6 occurrences across composite_routes.py and ops_routes.py).
- Theme switcher Chrome fix: `<button>` elements replace `<a href="#">`, event delegation via `addEventListener`.
- Navbar dropdown z-index: `z-index: 1050` prevents dropdown hiding behind page content.
- `color-scheme: dark` for dark themes fixes native `<select>` dropdown colors.

---

## v4.0.0 (May 2026) — Production Hardening

WebSocket transport, OpenTelemetry, tool versioning, multi-tenancy, plugin system. See git history.

## v3.1.0 (May 2026) — FastAPI Migration

Complete rewrite from Flask to FastAPI. See git history.

---

*SAJHA MCP Server — Changelog*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*

---

## v5.0.0 (May 2026) — MCP 2025-11-25 Full Compliance

Upgraded from MCP protocol version 2025-06-18 to 2025-11-25. All 19 spec changes implemented.

### Major Features (from MCP 2025-11-25)

- **Tasks (SEP-1686)**: Async task tracking for long-running MCP requests. `TaskManager` with create/get/list/cancel. States: working → input_required → completed/failed/cancelled. Polling-based result retrieval. MCP methods: `tasks/get`, `tasks/list`, `tasks/cancel`.
- **Elicitation (SEP-1330, SEP-1036)**: Server-initiated user input requests. Two modes: Form (structured JSON Schema) and URL (redirect to OAuth/consent page). `ElicitationManager` with create_form/create_url/respond/cancel. MCP method: `elicitation/respond`.
- **Sampling with Tools (SEP-1577)**: Server-initiated LLM calls with tool definitions. `SamplingManager` supports `tools` and `toolChoice` parameters per spec. Enables server-side agent loops.
- **Tool Icons (SEP-973)**: Icon metadata in tools/list responses. Supports `{"type":"url","url":"..."}` and `{"type":"emoji","emoji":"📊"}`. Configured per-tool in JSON config.
- **Origin Validation (Minor 3)**: Streamable HTTP endpoints respond with HTTP 403 for invalid Origin headers. `validate_origin()` in SSE route.
- **Tool Execution Errors (Minor 5)**: Input validation and execution errors now return `{"isError": true}` in tool result content (Tool Execution Error) instead of JSON-RPC Protocol Errors. Enables model self-correction.
- **Server Description (Minor 2)**: `description` field added to `serverInfo` in initialize response.
- **notifications/cancelled**: Client can cancel pending requests via `notifications/cancelled` method.
- **JSON Schema 2020-12 (Minor 10)**: Declared as default dialect for schema definitions.

### Updated Capabilities Declaration

```json
{
  "protocolVersion": "2025-11-25",
  "capabilities": {
    "tools": {"listChanged": true},
    "prompts": {"listChanged": true},
    "resources": {"subscribe": true, "listChanged": true},
    "logging": {},
    "completions": {},
    "elicitation": {"form": {}, "url": {}},
    "sampling": {"tools": true},
    "tasks": {"experimental": true}
  }
}
```

### Exception Handling Overhaul

- 42 bare `except:` blocks → `except Exception as e:` + logging
- 21 swallowed exceptions → added logging with `exc_info=True`
- 280+ `exc_info=True` additions for full stack traces in log files
- Before: 11 good / 304 issues. After: 308 good / 102 issues.

### Files Added

- `sajha/core/mcp_2025_11_25.py` — Tasks, Elicitation, Sampling, Icons, Origin validation
