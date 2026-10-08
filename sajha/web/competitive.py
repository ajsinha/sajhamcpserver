"""
How SAJHA compares: the single source for the comparison page (/comparison).

Everything the page shows is here: the dimensions, SAJHA's own column, each competitor's
column, the legend and the date the competitor columns were checked. The template only
lays it out, and nothing else in the repository restates it (the README links to the
page). tests/test_competitive.py holds it honest:

  * every competitor cell has a verdict from VERDICTS; every verdict but "Unknown" has a
    source URL and an as-of date;
  * every SAJHA cell names the code that backs it, and the claims that map to code are
    checked against it (protocol versions, routes, the conformance workflow, ...);
  * SAJHA's numbers are never written here: notes carry {tools}, {groups}, {modern} and
    {handshake}, filled from the running registries when the page renders.

Rules for editing (the same ones CLAUDE.md sets for docs):
  * A competitor verdict is what that vendor's own public documentation says, opened on
    the as-of date. If it cannot be verified, the verdict is "Unknown", never a guess.
  * SAJHA's verdicts follow the code, not the roadmap. Where SAJHA lacks something, say
    "No"; where a competitor is stronger, say so in its note and in ``best_for``.
  * Re-check a competitor column when its date is old; change its ``as_of`` with it.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

from typing import Dict, List, Optional

#: When the competitor columns were last checked against the vendors' public pages.
AS_OF = '2026-10-06'

#: Verdict -> (CSS class, what it means). Every cell is one of these; the word is always
#: shown, colour is only a second signal.
VERDICTS: Dict[str, tuple] = {
    'Yes': ('cmp-yes', 'Documented and generally available'),
    'Partial': ('cmp-partial', 'Limited, preview, paid tier only, or covers part of the row (see the note)'),
    'No': ('cmp-no', 'Not offered, or excluded by the product\'s nature (see the note)'),
    'Unknown': ('cmp-unknown', 'Could not be verified from public documentation on the as-of date'),
}

#: (group title, [(id, label, the question the row answers)]), in display order.
GROUPS: List[tuple] = [
    ('Protocol', [
        ('spec_2026', 'MCP 2026-07-28', 'Serves the stateless 2026-07-28 revision of the MCP specification.'),
        ('spec_2025', 'MCP 2025-11-25', 'Serves the session-based 2025-11-25 (or 2025-06-18) Streamable HTTP era.'),
        ('conformance_ci', 'Conformance suite', 'Runs the official MCP conformance suite, or publishes its results.'),
        ('remote_transports', 'SSE / WebSocket', 'Remote transports beyond Streamable HTTP: legacy HTTP+SSE, WebSocket.'),
        ('stdio', 'stdio', 'Serves or bridges the local stdio transport.'),
        ('tasks', 'Tasks', 'MCP tasks: long-running tool calls polled for their result.'),
        ('apps', 'MCP Apps', 'Interactive ui:// tool views (the MCP Apps extension).'),
    ]),
    ('Security', [
        ('oauth_rs', 'OAuth resource server', 'Protects its MCP endpoint as an OAuth 2.1 resource server.'),
        ('oauth_as', 'Built-in authorization server', 'Issues its own OAuth tokens, not only validating an external issuer.'),
        ('rbac', 'Per-tool access control', 'Roles, scopes or allow/deny lists decide who may see and call each tool.'),
    ]),
    ('Tools', [
        ('builtin_tools', 'Tools in the box', 'Ships ready-to-use tools of its own, not only a way to build them.'),
        ('integrations', 'SaaS integrations', 'Third-party apps (Slack, GitHub, Salesforce, ...) with managed per-user auth.'),
        ('nocode', 'No-code tool creation', 'Make a new tool without writing an MCP server (REST, SQL, OpenAPI, ...).'),
        ('composition', 'Composition', 'Chain tools into one, or bundle tools into virtual servers.'),
        ('federation', 'Federation', 'Aggregates other (upstream) MCP servers behind one endpoint.'),
        ('llm', 'Built-in LLM and chat', 'An LLM layer or chat that chooses and calls the tools itself.'),
    ]),
    ('Operations', [
        ('observability', 'Observability', 'Metrics and tracing (Prometheus, OpenTelemetry), logs, audit.'),
        ('admin_ui', 'Admin console', 'A web console for managing tools, servers and access.'),
        ('isolation', 'Isolation', 'Runs tool servers in sandboxes or containers with resource and network limits.'),
    ]),
    ('Deployment', [
        ('self_hosted', 'Self-hosted', 'Can run on your own infrastructure.'),
        ('open_source', 'Open source', 'Published under an OSI-approved open-source licence.'),
        ('managed', 'Managed service', 'The vendor runs it for you as a hosted service.'),
        ('client_sdk', 'Client SDK', 'Ships an MCP client library.'),
    ]),
]

DIMENSION_IDS: List[str] = [d[0] for _g, dims in GROUPS for d in dims]


def _s(verdict, note, code=(), guide=None, page=None):
    """A SAJHA cell: ``code`` is the repository paths that back it (tests check they
    exist), ``guide`` the guide that owns the topic, ``page`` an endpoint to link."""
    return {'verdict': verdict, 'note': note, 'code': list(code), 'guide': guide, 'page': page}


#: SAJHA's own column. Notes may use {tools}, {groups}, {modern}, {handshake}.
SAJHA = {
    'id': 'sajha', 'name': 'SAJHA', 'vendor': 'Ashutosh Sinha', 'kind': 'Server',
    'licence': 'All rights reserved',
    'best_for': 'One self-hosted server that brings its own data tools, a browser tool builder and an LLM '
                'layer that uses them, speaking both MCP eras, and can put a few other MCP servers behind its '
                'own governance, when you do not need to isolate servers in containers or a catalog of '
                'thousands of SaaS actions (it acts as each user in a few services it links).',
    'cells': {
        'spec_2026': _s('Yes', 'Stateless era: {modern}, on the same /mcp endpoint.',
                        ['sajha/core/mcp_modern.py'], 'MCP Protocol Guide.md'),
        'spec_2025': _s('Yes', 'Session era: {handshake}; chosen per request.',
                        ['sajha/core/mcp_2025_11_25.py'], 'MCP Protocol Guide.md'),
        'conformance_ci': _s('Yes', 'Run against a live server on every push, for both eras.',
                             ['.github/workflows/mcp-conformance.yml'], 'MCP 2026-07-28 Compliance.md'),
        'remote_transports': _s('Yes', 'Legacy SSE (/mcp/sse) and WebSocket (/mcp/ws) beside Streamable HTTP.',
                                ['sajha/routes/mcp_routes.py', 'sajha/routes/ws_routes.py'], 'MCP Protocol Guide.md'),
        'stdio': _s('Yes', 'Serves stdio for desktop clients (sajha serve --stdio, run_sajha_web.py --stdio), '
                           'both eras; identity from --user or --api-key.',
                    ['sajha/cli/stdio.py'], 'Command Line.md'),
        'tasks': _s('Yes', 'Tasks extension on 2026-07-28; a tool opts in with execution.taskSupport.',
                    ['sajha/core/mcp_tasks.py'], 'MCP Protocol Guide.md'),
        'apps': _s('Yes', 'ui:// views served as text/html;profile=mcp-app (mcp.apps.enabled).',
                   ['sajha/core/mcp_apps.py'], 'MCP Apps and Headers Guide.md'),
        'oauth_rs': _s('Yes', 'RFC 9728 metadata, audience-bound tokens; off by default (mcp.auth.mode).',
                       ['sajha/auth/oauth/resource_server.py'], 'OAuth Guide.md'),
        'oauth_as': _s('Yes', 'Built in (PKCE S256, client ID metadata documents, rotating refresh tokens) or external.',
                       ['sajha/auth/oauth/authorization_server.py'], 'OAuth Guide.md'),
        'rbac': _s('Yes', 'One policy for REST, MCP and A2A: role permissions, API-key allow/deny/regex lists; '
                          'plus declarative rules on every call (deny, human approval, argument constraints, '
                          'rate limits and quotas, PII redaction, injection screening) with a test bench.',
                   ['sajha/auth/access.py', 'sajha/policy', 'config/policies'], 'Policy and Audit.md',
                   page='admin_policies_page'),
        'builtin_tools': _s('Yes', '{tools} tools in {groups} groups loaded now: market data, central banks, '
                                   'filings, search, analytics.',
                            ['config/tools'], page='help_tools_page'),
        'integrations': _s('Partial', 'Connected accounts: users link GitHub, Slack, Google Workspace, '
                                      'Microsoft (Outlook, Graph), Atlassian or Notion (or any OAuth 2.0 service) once, with '
                                      'PKCE and an encrypted, refreshed token vault; a handful of tools act as '
                                      'them, plus admin-bound endpoints and per-user token passthrough to '
                                      'federated servers. No catalog of thousands of app actions.',
                           ['sajha/accounts', 'sajha/routes/accounts_routes.py'], 'Connected Accounts.md'),
        'nocode': _s('Yes', 'MCP Studio (admins): import an OpenAPI 3 or Swagger 2 spec, or a GraphQL schema, as '
                            'reviewed tools on one generic executor (no code generated; re-import shows a diff; '
                            'multipart bodies not supported); REST, SQL, script, Power BI, LiveLink, '
                            'SharePoint and OLAP creators; and Describe a tool: a sentence becomes a proposed, '
                            'tested tool an admin reviews and approves (the offline mock knows a few shapes; '
                            'real designs need an LLM); an LLM tool creator and a planner editor with dry runs; '
                            'creator permissions per role, and authors may change only what they created.',
                     ['sajha/studio', 'sajha/api_import', 'sajha/studio/describe.py'], 'MCP Studio User Guide.md'),
        'composition': _s('Yes', 'Composite tools with confidence tracking, registered as MCP tools; workflows: '
                                  'DAGs of tool, composite and Ask SAJHA steps with branches, loops, retries, '
                                  'approvals, cron/webhook/file/event triggers and durable, resumable runs, '
                                  'optionally published as tools.',
                          ['sajha/core/composition.py', 'sajha/workflows'], 'Workflows.md'),
        'federation': _s('Yes', 'Fronts upstream MCP servers (both eras, SSE, opt-in stdio) as namespaced '
                                '<prefix>__<tool> registry tools under its own access policy, approval, circuit '
                                'breakers and audit; off by default (federation.enabled).',
                         ['sajha/federation', 'sajha/routes/federation_routes.py'], 'Federation.md'),
        'llm': _s('Yes', 'One OpenAI-style interface over many providers (Ollama, Vertex AI and Entra ID '
                         'included) behind a governed factory; LLM tools: tools whose work is done by a model, '
                         'configured like any tool, in seven modes (answer, complete, extract, classify, '
                         'grounded, narrate, judge) with per-tool memory and limits; configurable planners as '
                         'files (ReAct, plan-and-execute, Reflect, self-consistency, map-reduce, an automatic '
                         'chooser and more) with bounded loops; the Ask SAJHA page; document search over its '
                         'own and admin documents, PDF and Word included, on a disk-based store; MCP sampling; '
                         'and an opt-in OpenAI-compatible endpoint where LLM tools appear as models. Out of the '
                         'box the mock model plans: real reasoning needs a provider and its key.',
                  ['sajha/ai/llm', 'sajha/ai/llm_tools', 'sajha/ai/planners_engine', 'sajha/ai/memory.py',
                   'sajha/ai/rag', 'sajha/ai/openai_api.py'], 'LLM Tools.md'),
        'observability': _s('Yes', 'Prometheus /metrics (protected; HTTP, MCP, tools, LLM tokens and cost), '
                            'OpenTelemetry traces and metrics over OTLP (opt-in), a usage and cost dashboard, '
                            'alert rules, health probes, and a hash-chained audit log with signed anchors, a '
                            'verify command and SIEM export (syslog, Splunk HEC, Datadog, file; JSON, CEF, OCSF).',
                            ['sajha/observability/metrics.py', 'sajha/observability/tracing.py',
                             'sajha/observability/usage.py', 'sajha/observability/alerts.py',
                             'sajha/routes/observability_routes.py', 'sajha/audit'], 'Observability.md',
                            page='monitoring_usage'),
        'admin_ui': _s('Yes', 'Web console: tools, users, roles, API keys, prompts, monitoring.',
                       ['sajha/web/templates/admin'], 'How SAJHA Fits Together.md'),
        'isolation': _s('Partial', 'Code users add in Studio (Python and script tools) and the shell run in a '
                                   'per-call sandbox: by default a subprocess with rlimits, plus Landlock, seccomp '
                                   'and namespaces on Linux; bwrap, nsjail or a container per call (optionally '
                                   'gVisor) by config. Built-in tools and federated servers are not isolated.',
                        ['sajha/sandbox', 'sajha/sandbox/runner.py'], 'Sandbox.md'),
        'self_hosted': _s('Yes', 'One Python process or several pods; SQLite or PostgreSQL; a non-root container '
                                 'image, a Helm chart (HPA, PDB, NetworkPolicy, ServiceMonitor) and Kustomize '
                                 'manifests, plus recipes for AWS, Hetzner and bare metal.',
                          ['deployment/README.md', 'Dockerfile', 'charts/sajha', 'deployment/k8s'],
                          'Kubernetes Deployment.md'),
        'open_source': _s('No', 'All rights reserved: no OSI licence.', ['README.md']),
        'managed': _s('No', 'No hosted service: you run it.'),
        'client_sdk': _s('Yes', 'sajhaclient on the official MCP SDK, plus REST and A2A clients, and the '
                                'sajha command line.',
                         ['clientsdk/sajhaclient', 'clientsdk/sajhaclient/cli'], 'Client SDK Guide.md'),
    },
}


#: "The short version" at the top of the page: what the table says, both ways. Keep it
#: true to the cells; re-read it whenever a verdict changes.
SHORT_VERSION: List[str] = [
    'SAJHA is one self-hosted server that brings its own tools: a catalog of {tools} data and utility '
    'tools, a browser tool builder (MCP Studio), composite tools, and an LLM layer with a chat page that '
    'picks and calls them. It serves both MCP eras ({modern} and {handshake}) on one endpoint over '
    'Streamable HTTP, SSE, WebSocket and stdio, with tasks, MCP Apps and its own OAuth 2.1 authorization server, '
    'and runs the official conformance suite in CI. FastMCP and Cloudflare are the others here that '
    'verifiably serve both eras and run that suite.',
    'Where others are stronger: the gateways (IBM ContextForge, Docker, Microsoft, Kong, Cloudflare) are '
    'built to put many MCP servers behind one endpoint at scale (SAJHA federates upstreams too, off by '
    'default, as one process), and Docker and Microsoft run each server in its own container, which SAJHA '
    'does not (it sandboxes only the code users add in Studio, and the shell). Composio, Zapier and Smithery reach thousands of SaaS apps with per-user sign-in and '
    'run it all for you. SAJHA has no hosted service and no open-source licence.',
]


def _c(verdict, note, url='', as_of=AS_OF):
    return {'verdict': verdict, 'note': note, 'url': url, 'as_of': as_of}


#: The competitors a buyer would put next to SAJHA, each from its vendor's own pages
#: (opened on the cell's as-of date). Product names are the vendors'; ``kind`` is ours.
COMPETITORS: List[dict] = [
    {
        'id': 'fastmcp',
        'name': 'FastMCP',
        'vendor': 'Prefect (jlowin)',
        'kind': 'Framework',
        'homepage': 'https://gofastmcp.com',
        'licence': 'Apache-2.0',
        'summary': 'Python framework for building MCP servers and clients; v4 (Aug 2026) serves both the 2026-07-28 and 2025 protocol eras.',
        'best_for': 'Python teams writing their own MCP servers/clients who want the most spec-current toolkit, with optional Horizon hosting.',
        'cells': {
            'spec_2026': _c('Yes', 'v4.0.0 (2026-08-31) adds full 2026-07-28 support with per-connection negotiation', 'https://gofastmcp.com/changelog'),
            'spec_2025': _c('Yes', "v4 serves both eras; handshake-era (2025) clients keep working; mode='legacy' available", 'https://gofastmcp.com/development/v4-notes'),
            'conformance_ci': _c('Yes', 'CI job runs @modelcontextprotocol/conformance (pinned 0.2.0-alpha.10, --suite all, expected-failures list)', 'https://github.com/PrefectHQ/fastmcp/blob/main/tests/conformance/test_conformance.py'),
            'remote_transports': _c('Yes', 'Legacy SSE still supported for old clients (deprecated); no WebSocket server transport', 'https://gofastmcp.com/deployment/running-server'),
            'stdio': _c('Yes', 'stdio is the default transport; proxy can bridge stdio<->HTTP', 'https://gofastmcp.com/deployment/running-server'),
            'tasks': _c('Yes', 'task=True via io.modelcontextprotocol/tasks; needs fastmcp-tasks/Docket, Redis for durable', 'https://gofastmcp.com/servers/tasks'),
            'apps': _c('Yes', 'app=True tools return Prefab UIs; Prefab has frequent breaking changes, pin version', 'https://gofastmcp.com/apps/overview'),
            'oauth_rs': _c('Yes', 'TokenVerifier / RemoteAuthProvider validate external IdP tokens as resource server', 'https://gofastmcp.com/servers/auth/authentication'),
            'oauth_as': _c('Yes', 'OAuthProvider full AS and OAuthProxy (DCR facade); docs warn full AS needs security expertise', 'https://gofastmcp.com/servers/auth/authentication'),
            'rbac': _c('Yes', 'Per-tool auth checks: require_scopes, require_roles, custom callables; hidden when denied', 'https://gofastmcp.com/servers/authorization'),
            'builtin_tools': _c('No', 'Framework: you write the tools; no ready-made tool library shipped', 'https://github.com/PrefectHQ/fastmcp'),
            'integrations': _c('No', 'No SaaS integration catalog in the framework (Horizon registry is a separate paid platform)', 'https://github.com/PrefectHQ/fastmcp'),
            'nocode': _c('Partial', 'FastMCP.from_openapi() builds a server from OpenAPI but needs Python code; docs advise curation', 'https://gofastmcp.com/integrations/openapi'),
            'composition': _c('Yes', 'mount() combines servers with namespacing; transforms reshape tools', 'https://gofastmcp.com/servers/composition'),
            'federation': _c('Yes', 'Proxy servers aggregate multiple upstream MCP servers behind one endpoint with prefixes', 'https://gofastmcp.com/servers/proxy'),
            'llm': _c('No', 'Client sampling handler is a hook you wire to your own LLM; no built-in chat/agent', 'https://gofastmcp.com/clients/client'),
            'observability': _c('Partial', 'Native OpenTelemetry tracing on by default; no metrics/Prometheus or audit log documented', 'https://gofastmcp.com/servers/telemetry'),
            'admin_ui': _c('Partial', 'Dev-only UIs: `fastmcp dev apps` preview and MCP Inspector; no admin console', 'https://gofastmcp.com/cli/overview'),
            'isolation': _c('No', 'Library runs tools in your Python process; no sandbox/container runtime', 'https://github.com/PrefectHQ/fastmcp'),
            'self_hosted': _c('Yes', 'pip-installable library; run anywhere Python runs', 'https://gofastmcp.com/deployment/running-server'),
            'open_source': _c('Yes', 'Apache-2.0; latest v4.0.11 (2026-10-04)', 'https://github.com/PrefectHQ/fastmcp'),
            'managed': _c('Yes', 'Prefect Horizon hosts MCP servers from GitHub; free for personal, paid teams/RBAC', 'https://www.prefect.io/horizon'),
            'client_sdk': _c('Yes', 'fastmcp.Client connects to any MCP server (stdio/HTTP), with sampling/elicitation handlers', 'https://gofastmcp.com/clients/client'),
        },
    },
    {
        'id': 'contextforge',
        'name': 'IBM ContextForge',
        'vendor': 'IBM (open source)',
        'kind': 'Gateway',
        'homepage': 'https://ibm.github.io/mcp-context-forge/',
        'licence': 'Apache-2.0',
        'summary': 'Self-hosted gateway/registry federating MCP servers, A2A agents and REST/gRPC APIs into virtual servers with RBAC, admin UI and OTel.',
        'best_for': 'Enterprises that need to federate and govern many existing MCP servers and APIs behind one endpoint on Kubernetes.',
        'cells': {
            'spec_2026': _c('Partial', 'v1.0.11 adds 2026-07-28 negotiation behind flags, legacy by default; roadmap: preview, GA late Q3', 'https://github.com/IBM/mcp-context-forge/releases/tag/v1.0.11'),
            'spec_2025': _c('Yes', 'Session-era protocol is the default (PROTOCOL_VERSION default 2025-06-18); 2025-11-25 compliance tests', 'https://raw.githubusercontent.com/IBM/mcp-context-forge/main/docs/docs/manage/configuration.md'),
            'conformance_ci': _c('Partial', 'CI runs `make conformance` (own cf-integration harness, 2025-11-25 legacy); official suite not shown', 'https://github.com/IBM/mcp-context-forge/blob/main/.github/workflows/conformance.yml'),
            'remote_transports': _c('Yes', 'README: HTTP, JSON-RPC, WebSocket, SSE (keepalive) and Streamable HTTP', 'https://github.com/IBM/mcp-context-forge'),
            'stdio': _c('Yes', 'mcpgateway.translate exposes stdio servers over SSE/HTTP; stdio client wrapper removed in v1.0.11', 'https://ibm.github.io/mcp-context-forge/latest/using/mcpgateway-translate/'),
            'tasks': _c('No', 'MCP Tasks listed as planned (Q3 2026) on the roadmap, issues #5677/#5683', 'https://raw.githubusercontent.com/IBM/mcp-context-forge/main/docs/docs/architecture/roadmap.md'),
            'apps': _c('Partial', 'ui:// resources + AppBridge passthrough, feature-flagged off by default (MCPGATEWAY_MCP_APPS_ENABLED)', 'https://raw.githubusercontent.com/IBM/mcp-context-forge/main/docs/docs/architecture/mcp-apps.md'),
            'oauth_rs': _c('Yes', 'RFC 9728 protected resource metadata + WWW-Authenticate; bearer enforcement per server', 'https://raw.githubusercontent.com/IBM/mcp-context-forge/main/docs/docs/architecture/rfc9728-compliance.md'),
            'oauth_as': _c('No', 'Points MCP clients to external authorization servers; issues its own JWT API tokens, not an OAuth AS', 'https://raw.githubusercontent.com/IBM/mcp-context-forge/main/docs/docs/architecture/rfc9728-compliance.md'),
            'rbac': _c('Yes', 'Roles, teams, token scoping; tools.execute/servers.use permissions; public/team/private visibility', 'https://ibm.github.io/mcp-context-forge/manage/rbac/'),
            'builtin_tools': _c('No', 'Gateway/registry; README demos use external sample servers (fast-time-server, mcp-server-git)', 'https://github.com/IBM/mcp-context-forge'),
            'integrations': _c('Partial', 'Catalog of external servers + per-user OAuth token storage/refresh; you register servers yourself', 'https://ibm.github.io/mcp-context-forge/latest/manage/oauth/'),
            'nocode': _c('Yes', 'Virtualizes REST APIs and gRPC (via reflection) as MCP tools without writing a server', 'https://github.com/IBM/mcp-context-forge'),
            'composition': _c('Yes', 'Virtual servers bundle tools/resources/prompts from many sources into one endpoint', 'https://github.com/IBM/mcp-context-forge'),
            'federation': _c('Yes', 'Federates MCP servers, A2A agents, REST/gRPC; Redis-backed multi-cluster federation', 'https://github.com/IBM/mcp-context-forge'),
            'llm': _c('Yes', 'LLM Chat in admin UI calls virtual-server tools; OpenAI, Azure, Anthropic, Bedrock, Ollama, watsonx', 'https://ibm.github.io/mcp-context-forge/using/clients/llm-chat/'),
            'observability': _c('Yes', 'OpenTelemetry (OTLP, Jaeger, Phoenix, Langfuse), Prometheus metrics, internal trace store', 'https://ibm.github.io/mcp-context-forge/latest/manage/observability/'),
            'admin_ui': _c('Yes', 'HTMX/Alpine admin UI for servers, tools, users, logs', 'https://github.com/IBM/mcp-context-forge'),
            'isolation': _c('Unknown', 'No documented sandboxing of upstream tool servers found'),
            'self_hosted': _c('Yes', 'PyPI, container (GHCR), Helm/Kubernetes; SQLite or PostgreSQL', 'https://github.com/IBM/mcp-context-forge'),
            'open_source': _c('Yes', 'Apache-2.0; latest v1.0.11 (2026-09-28)', 'https://github.com/IBM/mcp-context-forge'),
            'managed': _c('Unknown', 'No vendor-hosted offering found in README or docs'),
            'client_sdk': _c('Unknown', 'Has an internal outbound MCP client; no standalone client SDK documented'),
        },
    },
    {
        'id': 'docker',
        'name': 'Docker MCP Gateway',
        'vendor': 'Docker, Inc.',
        'kind': 'Gateway',
        'homepage': 'https://docs.docker.com/ai/mcp-catalog-and-toolkit/',
        'licence': 'MIT (gateway); Docker Desktop proprietary',
        'summary': 'Docker CLI plugin and Desktop UI that run catalog MCP servers in isolated containers behind one gateway, with profiles, secrets and OAuth.',
        'best_for': 'Developers wanting hundreds of ready-made, container-isolated MCP servers on their own machine with minimal setup.',
        'cells': {
            'spec_2026': _c('No', 'Built on MCP go-sdk v1.4.1, whose latest spec is 2025-11-25; no 2026-07-28 in releases', 'https://github.com/docker/mcp-gateway/blob/main/go.mod'),
            'spec_2025': _c('Yes', 'go-sdk v1.4.x supports 2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05', 'https://github.com/modelcontextprotocol/go-sdk/blob/v1.4.1/README.md'),
            'conformance_ci': _c('No', 'CI workflows (ci, main, validate, codeql) contain no conformance-suite run', 'https://github.com/docker/mcp-gateway/tree/main/.github/workflows'),
            'remote_transports': _c('Yes', '--transport stdio, sse or streaming; no WebSocket', 'https://github.com/docker/mcp-gateway/blob/main/docs/generator/reference/mcp_gateway_run.md'),
            'stdio': _c('Yes', 'stdio is the default gateway transport; runs stdio servers in containers', 'https://github.com/docker/mcp-gateway/blob/main/docs/generator/reference/mcp_gateway_run.md'),
            'tasks': _c('Unknown', 'No mention of MCP tasks in docs or releases'),
            'apps': _c('Unknown', 'No mention of MCP Apps / ui:// in docs or releases'),
            'oauth_rs': _c('No', 'HTTP/SSE endpoint uses a static MCP_GATEWAY_AUTH_TOKEN bearer, not OAuth resource metadata', 'https://github.com/docker/mcp-gateway/blob/main/docs/generator/reference/mcp_gateway_run.md'),
            'oauth_as': _c('No', 'OAuth only as a client to upstream services (GitHub, Notion...), no token issuance', 'https://docs.docker.com/ai/mcp-catalog-and-toolkit/toolkit/'),
            'rbac': _c('Yes', 'Per-profile tool allowlists (--enable/--disable); org governance is invite-only', 'https://github.com/docker/mcp-gateway'),
            'builtin_tools': _c('Yes', 'Catalog of 300+ verified containerized servers, Docker-built and signed (mostly third-party)', 'https://docs.docker.com/ai/mcp-catalog-and-toolkit/'),
            'integrations': _c('Yes', 'Toolkit runs OAuth in browser for GitHub, Notion, Linear and stores credentials', 'https://docs.docker.com/ai/mcp-catalog-and-toolkit/toolkit/'),
            'nocode': _c('Unknown', 'No REST/OpenAPI-to-MCP or DB-query tool builder found; custom servers need an image'),
            'composition': _c('Yes', 'Profiles bundle servers; experimental code-mode composes tools in JavaScript', 'https://docs.docker.com/ai/mcp-catalog-and-toolkit/dynamic-mcp/'),
            'federation': _c('Yes', 'One gateway fronts catalog, OCI, MCP Registry and file-defined servers in a profile', 'https://github.com/docker/mcp-gateway'),
            'llm': _c('Unknown', 'Toolkit docs list external clients only; Gordon integration not confirmed in current docs'),
            'observability': _c('Yes', 'OpenTelemetry metrics to OTLP endpoint, --log-calls, interceptors', 'https://github.com/docker/mcp-gateway/blob/main/docs/telemetry/README.md'),
            'admin_ui': _c('Partial', 'MCP Toolkit GUI in Docker Desktop 4.62+ (desktop app, not a web console)', 'https://docs.docker.com/ai/mcp-catalog-and-toolkit/toolkit/'),
            'isolation': _c('Yes', 'Each server in its own container: 1 CPU/2GB default, no-new-privileges, --block-network, signed images', 'https://github.com/docker/mcp-gateway/blob/main/docs/security.md'),
            'self_hosted': _c('Yes', 'Runs locally in Docker Desktop or standalone on Docker CE/Compose', 'https://docs.docker.com/ai/mcp-catalog-and-toolkit/mcp-gateway/'),
            'open_source': _c('Partial', 'Gateway CLI plugin is MIT; Docker Desktop Toolkit UI is proprietary', 'https://github.com/docker/mcp-gateway'),
            'managed': _c('Unknown', 'Gateway via Docker AI Governance is invite-only; hosting model not documented'),
            'client_sdk': _c('Partial', 'docker mcp CLI can list/call tools; no client library', 'https://github.com/docker/mcp-gateway'),
        },
    },
    {
        'id': 'msgateway',
        'name': 'Microsoft MCP Gateway',
        'vendor': 'Microsoft',
        'kind': 'Gateway',
        'homepage': 'https://github.com/microsoft/mcp-gateway',
        'licence': 'MIT',
        'summary': 'Open-source .NET reverse proxy and control plane that deploys MCP servers as Kubernetes pods and routes MCP 2026-07-28 requests to them with Entra ID auth.',
        'best_for': 'Azure/Kubernetes shops that want to deploy, route and govern many containerised MCP servers under Entra ID roles.',
        'cells': {
            'spec_2026': _c('Yes', 'Current release requires MCP 2026-07-28 clients and adapters (stateless, server/discover)', 'https://github.com/microsoft/mcp-gateway/blob/main/docs/mcp-2026-07-28.md'),
            'spec_2025': _c('No', 'No legacy initialize/sessions or downgrade; 2025-era clients need an older gateway image', 'https://github.com/microsoft/mcp-gateway/blob/main/docs/mcp-2026-07-28.md'),
            'conformance_ci': _c('No', 'CI runs dotnet build/test, proxy pytest and Bicep checks; no MCP conformance suite', 'https://github.com/microsoft/mcp-gateway/blob/main/.github/workflows/main.yml'),
            'remote_transports': _c('No', 'POST with JSON or request-scoped SSE only; GET streams/legacy HTTP+SSE rejected; no WebSocket', 'https://github.com/microsoft/mcp-gateway/blob/main/docs/mcp-2026-07-28.md'),
            'stdio': _c('Partial', 'Sample mcp-proxy image wraps a stdio server (npx/uvx) in a pod; you build it into ACR', 'https://github.com/microsoft/mcp-gateway/blob/main/sample-servers/mcp-proxy/README.md'),
            'tasks': _c('Unknown', 'No mention of the MCP tasks extension in README or migration guide'),
            'apps': _c('Unknown', 'No mention of MCP Apps / ui:// in README or migration guide'),
            'oauth_rs': _c('Yes', 'Entra ID bearer auth; serves protected resource metadata and WWW-Authenticate resource_metadata', 'https://github.com/microsoft/mcp-gateway/blob/main/dotnet/Microsoft.McpGateway.Service/src/McpSubPathAwareAuthenticationHandler.cs'),
            'oauth_as': _c('No', 'Relies on Azure Entra ID as the authorization server; gateway issues no tokens', 'https://github.com/microsoft/mcp-gateway'),
            'rbac': _c('Yes', 'Basic Entra app-role checks per adapter/tool (requiredRoles, mcp.admin); catalogs filtered per caller', 'https://github.com/microsoft/mcp-gateway'),
            'builtin_tools': _c('No', 'No bundled tools; builtin:bash/read_file/write_file are disabled for all callers', 'https://github.com/microsoft/mcp-gateway'),
            'integrations': _c('No', 'Hosts/proxies servers you supply; no SaaS connector catalogue or managed per-user app auth', 'https://github.com/microsoft/mcp-gateway'),
            'nocode': _c('No', 'Tools are registered as container images plus tool definitions; no REST/OpenAPI-to-MCP builder', 'https://github.com/microsoft/mcp-gateway'),
            'composition': _c('Partial', 'Tool Gateway Router exposes all registered tools on one /mcp endpoint; no chaining/toolkits', 'https://github.com/microsoft/mcp-gateway'),
            'federation': _c('Partial', 'Proxies local/remote MCP servers per adapter endpoint; /mcp aggregates registered tools only', 'https://github.com/microsoft/mcp-gateway'),
            'llm': _c('Partial', 'Preview, opt-in agents/sessions calling registered tools; needs Azure AI Foundry endpoint; single-replica', 'https://github.com/microsoft/mcp-gateway'),
            'observability': _c('Partial', 'Application Insights telemetry and pod-log APIs; no Prometheus/OTel or audit log documented', 'https://github.com/microsoft/mcp-gateway/blob/main/dotnet/Microsoft.McpGateway.Service/src/Program.cs'),
            'admin_ui': _c('Yes', 'React management portal at /portal: CRUD adapters/tools, status, pod logs, JSON-RPC test console', 'https://github.com/microsoft/mcp-gateway'),
            'isolation': _c('Yes', 'Each adapter/tool runs as its own K8s pod with securityContext, resource limits, NetworkPolicy', 'https://github.com/microsoft/mcp-gateway/blob/main/dotnet/Microsoft.McpGateway.Management/src/Deployment/KubernetesAdapterDeploymentManager.cs'),
            'self_hosted': _c('Yes', 'Self-deploy to local Kubernetes or AKS via Bicep/scripts; stronger scale-out than one server', 'https://github.com/microsoft/mcp-gateway'),
            'open_source': _c('Yes', 'MIT licence', 'https://github.com/microsoft/mcp-gateway'),
            'managed': _c('No', "Not a hosted service; Azure API Management is Microsoft's separate managed MCP option", 'https://learn.microsoft.com/en-us/azure/api-management/mcp-server-overview'),
            'client_sdk': _c('No', 'No client library; docs point to VS Code or the portal test console as the client', 'https://github.com/microsoft/mcp-gateway'),
        },
    },
    {
        'id': 'kong',
        'name': 'Kong AI Gateway',
        'vendor': 'Kong Inc.',
        'kind': 'Gateway',
        'homepage': 'https://developer.konghq.com/ai-gateway/mcp/',
        'licence': 'Apache-2.0 core; MCP plugins proprietary (AI Gateway Enterprise)',
        'summary': 'Kong Gateway plugins (AI MCP Proxy, AI MCP OAuth2) and Konnect AI MCP Server entities that convert REST APIs to MCP tools and proxy, aggregate, secure and observe MCP traffic.',
        'best_for': 'Organisations already running Kong/Konnect that want to expose existing REST APIs as MCP tools and govern MCP traffic with enterprise policies.',
        'cells': {
            'spec_2026': _c('Partial', '2026-07-28 accepted only on Konnect AI Gateway v2.1+ AI MCP Server; page marked incompatible with on-prem', 'https://developer.konghq.com/ai-gateway/mcp-version-support/'),
            'spec_2025': _c('Yes', 'Accepts client revisions 2025-03-26, 2025-06-18 and 2025-11-25', 'https://developer.konghq.com/ai-gateway/mcp-version-support/'),
            'conformance_ci': _c('Unknown', 'Closed-source plugins; no published MCP conformance results found'),
            'remote_transports': _c('No', 'Streamable HTTP only; WebSocket/gRPC upstreams unsupported; legacy HTTP+SSE not documented', 'https://developer.konghq.com/ai-gateway/entities/ai-mcp-server/'),
            'stdio': _c('No', 'HTTP/HTTPS only; non-HTTP protocols are listed as not supported', 'https://developer.konghq.com/plugins/ai-mcp-proxy/'),
            'tasks': _c('Unknown', 'MCP tasks not mentioned in plugin, entity or changelog pages'),
            'apps': _c('Unknown', 'MCP Apps / ui:// not mentioned in plugin, entity or changelog pages'),
            'oauth_rs': _c('Yes', 'AI MCP OAuth2 plugin (3.12+, Enterprise): PRM, JWKS or introspection token validation', 'https://developer.konghq.com/plugins/ai-mcp-oauth2/'),
            'oauth_as': _c('Partial', 'Plugin only validates external AS tokens; Kong Identity (Konnect-only) can act as AS with DCR', 'https://developer.konghq.com/identity/'),
            'rbac': _c('Yes', 'Per-tool ACL allow/deny for Consumers/Consumer Groups; OAuth-scope ACLs (Enterprise)', 'https://developer.konghq.com/plugins/ai-mcp-proxy/'),
            'builtin_tools': _c('Partial', 'Only the hosted Konnect MCP Server (tools to manage/debug Kong Konnect); no general tools', 'https://developer.konghq.com/mcp/kong-mcp/tools/'),
            'integrations': _c('No', 'Proxies/converts APIs and servers you bring; no managed SaaS connector catalogue', 'https://developer.konghq.com/ai-gateway/mcp/'),
            'nocode': _c('Yes', 'conversion modes turn OpenAPI-described REST routes into MCP tools by config (Enterprise)', 'https://developer.konghq.com/plugins/ai-mcp-proxy/'),
            'composition': _c('Yes', 'listener mode bundles tools from multiple conversion-only/upstream servers into one endpoint', 'https://developer.konghq.com/ai-gateway/entities/ai-mcp-server/'),
            'federation': _c('Yes', 'Aggregates multiple MCP servers into one endpoint; upstream-server mode is Konnect-only', 'https://developer.konghq.com/ai-gateway/configure-on-prem/'),
            'llm': _c('Unknown', 'AI Gateway proxies LLM calls, but no server-side agent/chat that calls MCP tools was found'),
            'observability': _c('Yes', 'MCP metrics, audit logs (JSON-RPC methods, latency, errors) and OpenTelemetry', 'https://developer.konghq.com/ai-gateway/mcp/'),
            'admin_ui': _c('Yes', 'AI MCP Servers configured through the Konnect UI (Konnect UI flow documented)', 'https://developer.konghq.com/ai-gateway/entities/ai-mcp-server/'),
            'isolation': _c('No', 'Gateway proxies upstream services; it does not run or sandbox MCP servers', 'https://developer.konghq.com/ai-gateway/mcp/'),
            'self_hosted': _c('Partial', 'Self-hosted Kong Gateway 3.12+ via plugins (Enterprise); some features Konnect-only', 'https://developer.konghq.com/ai-gateway/configure-on-prem/'),
            'open_source': _c('Partial', 'Kong Gateway core is Apache-2.0, but MCP plugins are AI Gateway Enterprise only', 'https://developer.konghq.com/plugins/ai-mcp-proxy/'),
            'managed': _c('Yes', 'Konnect SaaS manages AI Gateway entities (AI MCP Server) and the control plane', 'https://developer.konghq.com/ai-gateway/configure-on-prem/'),
            'client_sdk': _c('Unknown', 'No MCP client library found in Kong docs'),
        },
    },
    {
        'id': 'cloudflare',
        'name': 'Cloudflare remote MCP',
        'vendor': 'Cloudflare',
        'kind': 'Edge platform',
        'homepage': 'https://developers.cloudflare.com/agents/model-context-protocol/',
        'licence': 'MIT (Agents SDK, workers-oauth-provider); Proprietary SaaS (Workers, portals)',
        'summary': 'TypeScript Agents SDK (createMcpHandler, legacy McpAgent, MCP client) and workers-oauth-provider for MCP servers on Workers, plus Zero Trust MCP server portals that aggregate and govern upstream servers.',
        'best_for': 'Teams wanting globally deployed, managed remote MCP servers with built-in OAuth and a Zero Trust portal, and who accept Cloudflare lock-in.',
        'cells': {
            'spec_2026': _c('Yes', 'Portals accept stateless 2026-07-28; SDK createMcpHandler serves it via MCP SDK v2 beta peer', 'https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/'),
            'spec_2025': _c('Yes', 'Stateless handler accepts 2025 clients; deprecated McpAgent keeps sessionful 2025 transport', 'https://github.com/cloudflare/agents/blob/main/docs/agents/mcp-transports.md'),
            'conformance_ci': _c('Yes', 'GitHub Actions runs pinned official conformance suite (client and server) with baselines', 'https://github.com/cloudflare/agents/blob/main/.github/workflows/conformance.yml'),
            'remote_transports': _c('Yes', 'Legacy HTTP+SSE via deprecated McpAgent serveSSE/auto; portals reach SSE upstreams; RPC (exp.)', 'https://github.com/cloudflare/agents/blob/main/docs/agents/mcp-transports.md'),
            'stdio': _c('No', 'Workers-hosted; portals connect to upstreams only over Streamable HTTP or SSE', 'https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/'),
            'tasks': _c('Unknown', 'MCP tasks extension not documented; agents/tasks is unrelated durable execution'),
            'apps': _c('Partial', 'Example servers return ui:// widgets for OpenAI Apps SDK; no MCP Apps docs found', 'https://github.com/cloudflare/agents/blob/main/openai-sdk/pizzaz/src/index.ts'),
            'oauth_rs': _c('Yes', 'workers-oauth-provider validates tokens and passes authInfo to tools; Access can front servers', 'https://developers.cloudflare.com/agents/model-context-protocol/protocol/authorization/'),
            'oauth_as': _c('Yes', 'workers-oauth-provider is an OAuth 2.1 provider issuing its own tokens; PKCE, DCR endpoint', 'https://developers.cloudflare.com/agents/model-context-protocol/protocol/authorization/'),
            'rbac': _c('Yes', 'Portals: per-tool allowlist and Access policies; SDK: conditional tool registration by permission', 'https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/'),
            'builtin_tools': _c('Yes', 'Managed Cloudflare API server plus 16 product servers (docs, browser, radar...), Cloudflare-only', 'https://developers.cloudflare.com/agents/model-context-protocol/mcp-servers-for-cloudflare/'),
            'integrations': _c('Partial', 'Portals proxy third-party OAuth MCP servers with per-user auth; no SaaS connector catalogue', 'https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/'),
            'nocode': _c('Unknown', 'No no-code tool builder found; tools are written in TypeScript'),
            'composition': _c('Yes', 'Portals bundle many servers into one endpoint; Code Mode collapses tools into search+execute', 'https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/'),
            'federation': _c('Yes', 'MCP server portals aggregate multiple upstream MCP servers behind one /mcp endpoint', 'https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/'),
            'llm': _c('Partial', 'SDK framework: agents get MCP tools via getAITools() for AI SDK; you write the agent', 'https://github.com/cloudflare/agents/blob/main/docs/agents/mcp-client.md'),
            'observability': _c('Yes', 'Portal logs per tool call (status, duration), tool-call analytics, Gateway HTTP logs/DLP', 'https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/'),
            'admin_ui': _c('Yes', 'Cloudflare One dashboard to create portals, add servers, toggle tools, view logs', 'https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/'),
            'isolation': _c('Yes', 'Workers isolates; portal Code Mode runs agent code in isolated Dynamic Workers', 'https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/'),
            'self_hosted': _c('No', 'Servers deploy to Cloudflare Workers (wrangler local dev only); portals are Cloudflare One SaaS', 'https://developers.cloudflare.com/agents/guides/remote-mcp-server/'),
            'open_source': _c('Partial', 'Agents SDK and workers-oauth-provider are MIT; Workers runtime services and portals are not', 'https://github.com/cloudflare/agents'),
            'managed': _c('Yes', "Runs on Cloudflare's global network; strongly managed vs a single self-hosted server", 'https://developers.cloudflare.com/agents/guides/remote-mcp-server/'),
            'client_sdk': _c('Yes', 'Agents SDK MCP client (addMcpServer; streamable-http, sse, auto, RPC transports)', 'https://github.com/cloudflare/agents/blob/main/docs/agents/mcp-client.md'),
        },
    },
    {
        'id': 'composio',
        'name': 'Composio',
        'vendor': 'Composio',
        'kind': 'Hosted platform',
        'homepage': 'https://composio.dev',
        'licence': 'Proprietary SaaS (Python/TS SDK MIT)',
        'summary': 'Hosted agent tool platform: 1,500+ toolkits with managed per-user OAuth, exposed via SDK sessions or a hosted MCP endpoint (Tool Router meta-tools).',
        'best_for': 'Products that need many SaaS integrations with per-user managed auth and do not want to build or host connectors themselves.',
        'cells': {
            'spec_2026': _c('Unknown', 'No mention of the 2026-07-28 revision found in docs or changelog.'),
            'spec_2025': _c('Yes', 'Streamable HTTP with RFC 9728 protected-resource metadata (2025-06-18+ auth); exact version undocumented', 'https://connect.composio.dev/.well-known/oauth-protected-resource'),
            'conformance_ci': _c('Unknown', 'No published conformance-suite results found; server is closed source.'),
            'remote_transports': _c('No', 'Session MCP transport is Streamable HTTP POST only; GET (SSE) and DELETE not supported', 'https://docs.composio.dev/reference/authenticating-to-composio/project-api-key-permissions'),
            'stdio': _c('No', 'Remote-only; Custom MCP excludes local/STDIO-only servers. Coding agents use its CLI/plugin instead', 'https://docs.composio.dev/docs/extending-sessions/custom-mcp'),
            'tasks': _c('Unknown', 'No documentation of the MCP tasks extension found.'),
            'apps': _c('Unknown', 'No documentation of MCP Apps / ui:// resources found.'),
            'oauth_rs': _c('Yes', 'connect.composio.dev/mcp returns 401 + WWW-Authenticate resource_metadata; PRM published', 'https://connect.composio.dev/.well-known/oauth-protected-resource'),
            'oauth_as': _c('Yes', 'Own AS metadata: auth code + PKCE S256, dynamic client registration endpoint, refresh tokens', 'https://connect.composio.dev/.well-known/oauth-authorization-server'),
            'rbac': _c('Yes', 'Session toolkit/tool enable-disable lists, tag filters, scoped API keys; per-role perms on Enterprise', 'https://docs.composio.dev/kb/guide/platform-session-tool-policies'),
            'builtin_tools': _c('Yes', '1,500+ hosted toolkits plus 7 Tool Router meta-tools (search, connect, multi-execute, workbench)', 'https://docs.composio.dev/docs/composio-connect'),
            'integrations': _c('Yes', '1,500+ toolkits with managed OAuth/API-key auth per user (connected accounts); far broader than one server', 'https://docs.composio.dev/llms.txt'),
            'nocode': _c('No', 'Custom tools are defined in SDK code in your process; Custom MCP needs your own deployed server', 'https://docs.composio.dev/docs/extending-sessions/custom-tools-and-toolkits'),
            'composition': _c('Yes', 'Sessions bundle many toolkits behind one MCP URL; multi-execute meta-tool runs tools in parallel', 'https://docs.composio.dev/docs/configuring-sessions'),
            'federation': _c('Partial', "Custom MCP (experimental, API-only) syncs a remote HTTPS MCP server's tools into sessions; 500-tool cap", 'https://docs.composio.dev/docs/extending-sessions/custom-mcp'),
            'llm': _c('No', 'Tool layer only: you bring the agent/LLM framework or an existing MCP client; no built-in chat', 'https://docs.composio.dev/docs'),
            'observability': _c('Partial', 'Tool-execution logs API and SIEM/Datadog export recipe; no OpenTelemetry/Prometheus documented', 'https://docs.composio.dev/docs/poc-to-prod/stream-logs-to-a-siem'),
            'admin_ui': _c('Yes', 'Web dashboard manages MCP configs, auth configs, connected accounts and logs', 'https://docs.composio.dev/docs/single-toolkit-mcp'),
            'isolation': _c('Partial', 'Remote sandbox (workbench) runs agent code in 1-8 vCPU tiers; not per-tool-server containers', 'https://docs.composio.dev/docs/sandbox/remote'),
            'self_hosted': _c('Partial', 'Self-hosting (Helm, own VPC) only on the Enterprise tier', 'https://composio.dev/enterprise'),
            'open_source': _c('Partial', 'SDK/CLI repo is MIT; the hosted platform itself is proprietary', 'https://github.com/ComposioHQ/composio'),
            'managed': _c('Yes', 'Hosted SaaS with Hobby (free), Pro ($29/mo) and Enterprise plans', 'https://composio.dev/pricing'),
            'client_sdk': _c('Partial', 'Python/TS SDKs for sessions/tools; MCP use relies on third-party MCP clients (e.g. fastmcp)', 'https://docs.composio.dev/docs/sessions-via-mcp'),
        },
    },
    {
        'id': 'zapier',
        'name': 'Zapier MCP',
        'vendor': 'Zapier',
        'kind': 'Hosted platform',
        'homepage': 'https://zapier.com/mcp',
        'licence': 'Proprietary SaaS',
        'summary': "Zapier's hosted MCP server exposing actions across 9,000+ apps via one Streamable HTTP endpoint, with Zapier holding app credentials; billed at 2 tasks per call.",
        'best_for': 'Teams already on Zapier who want an MCP client to act across thousands of business apps with no code and no hosting.',
        'cells': {
            'spec_2026': _c('Unknown', 'Docs do not state a supported protocol version; no mention of 2026-07-28.'),
            'spec_2025': _c('Yes', 'Streamable HTTP + RFC 9728 PRM and DCR (2025-06-18+ auth); exact version not documented', 'https://mcp.zapier.com/.well-known/oauth-protected-resource/api/v1/connect'),
            'conformance_ci': _c('Unknown', 'No published conformance-suite results found; service is closed source.'),
            'remote_transports': _c('No', 'Streamable HTTP only; SSE-only clients cannot connect', 'https://docs.zapier.com/mcp/overview/how-connections-work'),
            'stdio': _c('Partial', 'Hosted server is HTTP-only; zapier-sdk-mcp runs a local stdio server (npx zapier-sdk mcp)', 'https://www.npmjs.com/package/@zapier/zapier-sdk-mcp'),
            'tasks': _c('Unknown', 'No documentation of the MCP tasks extension found.'),
            'apps': _c('Unknown', 'No documentation of MCP Apps / ui:// resources found.'),
            'oauth_rs': _c('Yes', 'Endpoint returns 401 with resource_metadata; PRM published; connection-token bearer as fallback', 'https://mcp.zapier.com/.well-known/oauth-protected-resource/api/v1/connect'),
            'oauth_as': _c('Yes', 'Own AS: auth code + PKCE (S256), dynamic client registration, refresh, revocation', 'https://mcp.zapier.com/.well-known/oauth-authorization-server'),
            'rbac': _c('Yes', 'Managed mode fixes tool list; account app/action restrictions; server Owner/Editor/View roles (Team+)', 'https://docs.zapier.com/mcp/manage/security'),
            'builtin_tools': _c('Yes', '16 meta-tools plus 40,000+ actions; workflow tools in early access', 'https://docs.zapier.com/mcp/overview/how-tools-work'),
            'integrations': _c('Yes', '9,000+ apps; Zapier holds and refreshes app credentials per user', 'https://docs.zapier.com/mcp/overview/how-connections-work'),
            'nocode': _c('Yes', 'Private integrations built on Zapier Developer Platform become MCP tools; no MCP server needed', 'https://docs.zapier.com/mcp/manage/security'),
            'composition': _c('Yes', 'Tool bundles share tool sets; Skills; Next Gen Zap workflow tools (early access)', 'https://docs.zapier.com/mcp/get-started/tool-bundles'),
            'federation': _c('No', 'Users cannot bring third-party tools in; MCP Client (beta) calls remote servers from Zaps only', 'https://docs.zapier.com/mcp/manage/security'),
            'llm': _c('Partial', 'Separate product Zapier Agents (chat agents over 9,000+ apps); Zapier MCP itself serves external clients', 'https://zapier.com/agents'),
            'observability': _c('Partial', 'Per-call History tab and account audit log; no metrics/tracing export documented', 'https://docs.zapier.com/mcp/manage/security'),
            'admin_ui': _c('Yes', 'mcp.zapier.com dashboard to add tools, share access, view history', 'https://docs.zapier.com/mcp/manage/server-access'),
            'isolation': _c('Partial', 'write_code_action runs generated code in a secure sandbox; rolling out, not all accounts', 'https://docs.zapier.com/mcp/overview/how-tools-work'),
            'self_hosted': _c('No', 'Multi-tenant cloud only; dedicated VPC or on-prem deployments not available', 'https://docs.zapier.com/mcp/manage/security'),
            'open_source': _c('No', 'Service and SDK are under Zapier ToS; only the plugin-manifest repo (zapier/zapier-mcp) is MIT', 'https://www.npmjs.com/package/@zapier/zapier-sdk-mcp'),
            'managed': _c('Yes', 'Hosted at mcp.zapier.com; included in Zapier plans, 2 tasks per tool call', 'https://docs.zapier.com/mcp/manage/security'),
            'client_sdk': _c('Partial', 'MCP Client app (beta) lets Zaps call remote MCP servers; no MCP client library', 'https://help.zapier.com/hc/en-us/articles/38777069364109'),
        },
    },
    {
        'id': 'smithery',
        'name': 'Smithery',
        'vendor': 'Smithery (acquired by Arcade.dev, Aug 2026)',
        'kind': 'Hosted platform',
        'homepage': 'https://smithery.ai',
        'licence': 'Proprietary SaaS (CLI AGPL-3.0, agent.pw MIT)',
        'summary': 'Public MCP registry (25,000+ listed servers) plus a gateway that proxies/hosts servers and a Connect API with managed OAuth and credential storage.',
        'best_for': 'Discovering and connecting to many third-party MCP servers, or distributing your own server to a wide audience.',
        'cells': {
            'spec_2026': _c('Unknown', 'Docs reference 2025-11-25; no mention of 2026-07-28 found.'),
            'spec_2025': _c('Yes', 'Docs use protocolVersion 2025-11-25; gateway supports CIMD client registration (2025-11-25 auth)', 'https://smithery.ai/docs/build/triggers'),
            'conformance_ci': _c('Unknown', 'No published conformance-suite results found.'),
            'remote_transports': _c('Partial', 'Published servers must speak Streamable HTTP; WebSocket used only for the Uplink CLI tunnel', 'https://smithery.ai/docs/use/uplink'),
            'stdio': _c('Yes', 'Uplink bridges a local stdio server; MCPB bundles distribute stdio servers; CLI installs to clients', 'https://smithery.ai/docs/use/uplink'),
            'tasks': _c('Unknown', 'No documentation of the MCP tasks extension found.'),
            'apps': _c('Unknown', 'No documentation of MCP Apps / ui:// support found.'),
            'oauth_rs': _c('Yes', 'Gateway returns 401 + resource_metadata; per-server PRM at server.smithery.ai', 'https://server.smithery.ai/.well-known/oauth-protected-resource/exa'),
            'oauth_as': _c('Yes', 'Per-server AS at auth.smithery.ai: PKCE S256, DCR endpoint, CIMD supported', 'https://auth.smithery.ai/.well-known/oauth-authorization-server/exa'),
            'rbac': _c('Partial', 'Service tokens scoped by namespace/connection/operation/metadata (preview); not per-tool', 'https://smithery.ai/docs/use/token-scoping'),
            'builtin_tools': _c('Partial', 'Mostly a registry of third-party servers; a few first-party ones (e.g. mouseless computer-use)', 'https://smithery.ai/docs/use/uplink'),
            'integrations': _c('Yes', 'Connect API: Smithery-maintained OAuth apps, auto token refresh, per-user connections', 'https://smithery.ai/docs/use/connect'),
            'nocode': _c('No', 'Publishing requires an existing MCP server (URL or MCPB bundle); no tool builder', 'https://smithery.ai/docs/build/index'),
            'composition': _c('Partial', 'Namespaces group connections; REST lists tools across a namespace; no virtual servers', 'https://smithery.ai/docs/concepts/namespaces'),
            'federation': _c('Partial', 'Gateway proxies upstream servers, one endpoint per server; not merged into one MCP endpoint', 'https://smithery.ai/docs/build/publish'),
            'llm': _c('Unknown', 'Server pages offer "Try now"; no documented built-in LLM chat found.'),
            'observability': _c('Partial', 'Tool-call analytics for publishers, runtime and release logs API; no OTel/Prometheus', 'https://smithery.ai/docs/build/index'),
            'admin_ui': _c('Yes', 'Web UI for publishing, server settings, configuration UI and verification', 'https://smithery.ai/docs/build/publish'),
            'isolation': _c('Unknown', 'Hosted release type exists (JS module upload); sandbox/isolation not documented.'),
            'self_hosted': _c('Partial', 'Registry/gateway are SaaS; only CLI/Uplink and the agent.pw credential library run locally', 'https://smithery.ai/docs/use/uplink'),
            'open_source': _c('Partial', 'CLI is AGPL-3.0 and agent.pw is MIT; registry and gateway are proprietary', 'https://github.com/arcadeai-labs/smithery-cli'),
            'managed': _c('Yes', 'Hosted gateway/registry; release API supports hosted, external URL and stdio bundle types', 'https://smithery.ai/docs/api-reference/servers/publish-a-server'),
            'client_sdk': _c('Yes', '@smithery/api createConnection gives an MCP transport for MCP/AI SDK clients; typed SDKs in preview', 'https://smithery.ai/docs/use/connect'),
        },
    },
]


# ── What the template needs ─────────────────────────────────────────────────

def _live() -> dict:
    """The numbers SAJHA's notes refer to, read from the running server."""
    from sajha.core.mcp_modern import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS
    from sajha.web.help_catalog import live_tool_groups
    live = live_tool_groups()
    return {'tools': live['total_tools'], 'groups': live['total_groups'],
            'modern': ', '.join(MODERN_PROTOCOL_VERSIONS),
            'handshake': ', '.join(HANDSHAKE_PROTOCOL_VERSIONS)}


def sajha_cell(dim: str, live: Optional[dict] = None) -> dict:
    """SAJHA's cell for a dimension, its note filled from the running server."""
    cell = dict(SAJHA['cells'][dim])
    cell['note'] = cell['note'].format(**(live if live is not None else _live()))
    return cell


def sources() -> List[dict]:
    """Every source URL, numbered once, with the cells that cite it."""
    out: Dict[str, dict] = {}
    for comp in COMPETITORS:
        for dim in DIMENSION_IDS:
            cell = comp['cells'][dim]
            if not cell['url']:
                continue
            s = out.setdefault(cell['url'], {'url': cell['url'], 'as_of': cell['as_of'], 'cites': []})
            s['cites'].append((comp['name'], _label(dim)))
            s['as_of'] = max(s['as_of'], cell['as_of'])
    for n, s in enumerate(out.values(), 1):
        s['n'] = n
    return list(out.values())


def _label(dim: str) -> str:
    return next(d[1] for _g, dims in GROUPS for d in dims if d[0] == dim)


def tally(cells: Dict[str, dict]) -> Dict[str, int]:
    """How many of each verdict a column has."""
    out = {v: 0 for v in VERDICTS}
    for c in cells.values():
        out[c['verdict']] += 1
    return out


def page_context() -> dict:
    """Everything /comparison renders."""
    live = _live()
    src = sources()
    num = {s['url']: s['n'] for s in src}
    sajha = {d: sajha_cell(d, live) for d in DIMENSION_IDS}
    groups = []
    for title, dims in GROUPS:
        rows = []
        for dim, label, question in dims:
            rows.append({'id': dim, 'label': label, 'question': question, 'sajha': sajha[dim],
                         'cells': [dict(comp['cells'][dim], n=num.get(comp['cells'][dim]['url']))
                                   for comp in COMPETITORS]})
        groups.append({'title': title, 'rows': rows})
    return {'as_of': AS_OF, 'verdicts': VERDICTS,
            'short_version': [p.format(**live) for p in SHORT_VERSION], 'groups': groups, 'competitors': COMPETITORS,
            'sajha': SAJHA, 'sajha_tally': tally(sajha), 'sources': src, 'live': live,
            'dimension_count': len(DIMENSION_IDS)}
