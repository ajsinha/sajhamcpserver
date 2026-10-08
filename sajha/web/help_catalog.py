"""
Help catalog: the single registry of help topics.

The Help landing page renders searchable category tiles from here, each category's page
renders its cards from here, and every page's "related help" chips come from here. A
topic lives in exactly one place, so a new guide or page registers once instead of
drifting across hand-written help pages (which is how the old help pages came to claim
"497 tools", "three transports" and "fully compliant" long after none was true).

What the catalog covers, and the tests that hold it to that (tests/test_help_catalog.py):

  * every guide under docs/ (excluding docs/archive/ and README.md files), addressed by
    its unique file name (sajha/web/guides.py);
  * the live pages: the tool catalog (/help/tools, derived from the registry), the
    glossary (/glossary, rendered from GLOSSARY.md), the guide library, the interactive
    API docs, About and the comparison (/comparison, from sajha/web/competitive.py).

Each topic is a dict:
  * title, summary, icon      what the card shows
  * kind = 'guide'            link is /help/guides/<file>
         | 'page' | 'browser' link is url_for(endpoint) (a browser is a sub-index)
  * badge (optional)          a small tag

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

# ── Superseded help pages: endpoint -> (old path, where it went) ─────────────
# The hand-written pages these served restated what the guides own; each now answers
# 301 to its owner, so old bookmarks and links still land on current content.
REDIRECTS: Dict[str, tuple] = {
    'help_tutorials_page': ('/help/tutorials', '/help/c/tutorials'),
    'help_storage_page': ('/help/storage', '/help/guides/Storage%20Guide.md'),
    'help_glossary_page': ('/help/glossary', '/glossary'),
    'help_ai_page': ('/help/ai', '/help/guides/Intelligence%20Layer.md'),
    'help_enterprise_page': ('/help/enterprise', '/help/guides/Security%20Model.md'),
}

#: Endpoints that only redirect to a topic listed elsewhere.
ALIASES = set(REDIRECTS)

# ── Page -> owning guide ("Full reference: ...") ────────────────────────────
#: Help pages here; every console page's guide comes from sajha/web/page_help.py, so
#: the two cannot disagree.
_HELP_PAGE_GUIDES = {
    'help_tools_page': 'How SAJHA Fits Together.md',
    'about_page': 'How SAJHA Fits Together.md',
}


def _companions() -> Dict[str, str]:
    from sajha.web.page_help import PAGE_HELP
    out = {ep: e['guide'] for ep, e in PAGE_HELP.items() if e.get('guide')}
    out.update(_HELP_PAGE_GUIDES)
    return out


COMPANION_GUIDE: Dict[str, str] = _companions()


def _p(title, endpoint, icon, summary, badge=None):
    return {'kind': 'page', 'title': title, 'endpoint': endpoint, 'icon': icon,
            'summary': summary, 'badge': badge}


def _g(title, file, icon, summary, badge=None):
    return {'kind': 'guide', 'title': title, 'file': file, 'icon': icon,
            'summary': summary, 'badge': badge}


def _b(title, endpoint, icon, summary, badge=None):
    return {'kind': 'browser', 'title': title, 'endpoint': endpoint, 'icon': icon,
            'summary': summary, 'badge': badge}


def _tool(provider, icon, summary):
    return _g(provider, f'{provider} Tool Reference Guide.md', icon, summary)


CATALOG: List[dict] = [
    {
        'id': 'start', 'name': 'Getting started', 'icon': 'bi-rocket-takeoff',
        'blurb': 'The map of SAJHA, the first run, and how it is configured and stored.',
        'topics': [
            _g('How SAJHA Fits Together', 'How SAJHA Fits Together.md', 'bi-map',
               'The map: what each part is for, how the parts connect, and which document '
               'owns each topic. Read this first.'),
            _g('Quick Start', 'Quick Start.md', 'bi-play-circle',
               'Install, sign in, and make your first MCP call.'),
            _g('Configuration Reference', 'Configuration Reference.md', 'bi-sliders',
               'config/application.yml, ${ENV:default}, SAJHA_* overrides, and every key.'),
            _g('Database Setup', 'Database Setup.md', 'bi-database',
               'SQLite for development, PostgreSQL for production: one schema file per database, '
               'run once by the operator; the start-up schema check, upgrades, python -m sajha.db.'),
            _g('Storage Guide', 'Storage Guide.md', 'bi-hdd-stack',
               'Where configs, prompts, Studio output and docs live: local disk, S3, Azure '
               'Blob or GCS, and hot reload on each.'),
            _g('Python Playground', 'Python Playground.md', 'bi-filetype-py',
               'Python in the browser (Pyodide): the notebook, the sajha module for calling tools, '
               'vendored or CDN assets, and the headers that make Stop work.'),
            _g('Kubernetes Deployment', 'Kubernetes Deployment.md', 'bi-boxes',
               'The container image, the Helm chart and Kustomize manifests: secrets every pod '
               'shares, several replicas, streaming-friendly ingress, metrics, NetworkPolicy.'),
        ],
    },
    {
        'id': 'protocol', 'name': 'MCP protocol', 'icon': 'bi-diagram-3',
        'blurb': 'Both protocol eras on one /mcp endpoint, the evidence, OAuth, and every HTTP endpoint.',
        'groups': [
            ('How it works', ['MCP Protocol Guide', 'OAuth Guide', 'MCP Apps and Headers Guide',
                              'SAJHA Net protocol (spec)']),
            ('Evidence', ['MCP 2026-07-28 Compliance', 'MCP 2025-11-25 Compliance']),
            ('Endpoints', ['API Reference', 'Interactive API docs', 'ReDoc API reference']),
        ],
        'topics': [
            _g('MCP Protocol Guide', 'MCP Protocol Guide.md', 'bi-diagram-3',
               'The stateless 2026-07-28 era and the session-based 2025-11-25 era, transports, '
               'streaming, subscriptions, MRTR and tasks.'),
            _g('MCP 2026-07-28 Compliance', 'MCP 2026-07-28 Compliance.md', 'bi-patch-check',
               'Requirement by requirement, with conformance-suite results and known limits.'),
            _g('MCP 2025-11-25 Compliance', 'MCP 2025-11-25 Compliance.md', 'bi-patch-check',
               'The session-based era: requirements, conformance results and known limits.'),
            _g('OAuth Guide', 'OAuth Guide.md', 'bi-shield-lock',
               'OAuth 2.1 on /mcp: modes off, optional and required; the built-in authorization '
               'server or an external issuer.'),
            _g('MCP Apps and Headers Guide', 'MCP Apps and Headers Guide.md', 'bi-window-stack',
               'Interactive tool views (ui:// resources) and x-mcp-header argument mirroring.'),
            _g('SAJHA Net protocol (spec)', 'SAJHA Net Protocol.md', 'bi-share',
               'Specification of the io.sajha/net extension: /sajhanet/ endpoints, RFC 9421 '
               'signed requests, gossip, key directory, call forwarding headers, error codes, conformance tests.'),
            _g('API Reference', 'API Reference.md', 'bi-signpost-split',
               'Every HTTP endpoint the server registers: REST, MCP, OAuth, A2A, AI, Studio, '
               'workflows, policy, quality and connector routes.'),
            _b('Interactive API docs', 'swagger_ui_html', 'bi-braces',
               'The OpenAPI description of the REST API, explorable and callable (Swagger UI).'),
            _b('ReDoc API reference', 'redoc_html', 'bi-book',
               'The same OpenAPI description, as a reference page.'),
        ],
    },
    {
        'id': 'architecture', 'name': 'Architecture', 'icon': 'bi-boxes',
        'blurb': 'How the server is built inside, and the design of each subsystem: composition, the '
                 'intelligence layer, federation, governance, data access, workflows, quality, scale.',
        'topics': [
            _g('Architecture', 'Architecture.md', 'bi-boxes',
               'The process, the registries, the request path, and how each subsystem fits in, '
               'with a link to the guide that owns it.'),
            _g('Composition Framework', 'Composition Framework.md', 'bi-bezier2',
               'Composite tools: StepResult, ParamLens, EntropyGuard and confidence.'),
            _g('Intelligence Layer', 'Intelligence Layer.md', 'bi-stars',
               'LLM providers and models, the gateway, the mock provider, /api/ai/ask, planners, '
               'conversation memory, document search (RAG) and the Ask SAJHA chat page.'),
            _g('Extending the Intelligence Layer', 'Extending the Intelligence Layer.md', 'bi-plug',
               'Write a provider, a model or a planner: settings, error mapping, registration, '
               'testing, with runnable examples.', badge='Developers'),
            _g('Federation', 'Federation.md', 'bi-diagram-2',
               'Front other MCP servers: their tools under SAJHA\'s access control, audit, cache, '
               'circuit breakers and approval; the Proxied MCP servers page and config/mcp_servers.json.'),
            _g('Connected Accounts', 'Connected Accounts.md', 'bi-link-45deg',
               'Users link GitHub, Slack, Google, Microsoft 365 and other accounts once; tools and '
               'federated servers act as them. Providers, PKCE flow, token vault, refresh, security.'),
            _g('Sandbox', 'Sandbox.md', 'bi-shield-lock',
               'Where Studio code and script tools and the shell run: threat model, backends '
               '(subprocess, bwrap, nsjail, docker), what each guarantees, tool policy.'),
            _g('Scaling and State', 'Scaling and State.md', 'bi-hdd-network',
               'Run several workers or hosts: the state store (memory, Redis, database), what is '
               'shared and what stays per worker, durable tasks, secrets to share.'),
            _g('Observability', 'Observability.md', 'bi-activity',
               'Prometheus /metrics, OpenTelemetry traces over OTLP, the usage ledger behind the '
               'Usage & cost page, and alert rules.'),
            _g('Workflows', 'Workflows.md', 'bi-diagram-3',
               'DAGs of tools, composites and Ask SAJHA steps; cron, webhook, file and event triggers; '
               'durable runs that resume after a crash, re-run from a step, publish as a tool.'),
            _g('Tool Quality', 'Tool Quality.md', 'bi-heart-pulse',
               'Test cases with recorded HTTP cassettes and JUnit output, the schema linter, health probes, '
               'evals for Ask SAJHA, and tool versions with canary routing, rollback and sunset dates.'),
            _g('Policy and Audit', 'Policy and Audit.md', 'bi-shield-check',
               'Declarative rules on every tool call (deny, approval, argument constraints, rate limits, '
               'quotas, PII redaction, injection screening); hash-chained, signed audit; SIEM export.'),
            _g('Data Connectors', 'Data Connectors.md', 'bi-database-gear',
               'Enterprise databases, warehouses, vector stores and search clusters as governed, read-only '
               'tools: drivers, the statement guard, limits, masking, curated views, per-user credentials.'),
            _g('LLM tools', 'LLM Tools.md', 'bi-chat-square-text',
               'Tools whose work is done by a model, configured like any tool: seven modes, running as the '
               'caller, conversation memory, spill to disk and the memory guard; config-driven planners (design).'),
            _g('Planner reference', 'Planner Reference.md', 'bi-signpost-split',
               'Planner files in full: keys, every stage type, transitions and bounded loops, the when '
               'expression grammar, verify checks, validation messages, JSON Schema, shipped strategies, '
               'and the planner editor.'),
            _g('SAJHA Net (design)', 'SAJHA Net.md', 'bi-diagram-3',
               'SAJHA servers sharing tools across domains (core built; section 5.5 says what): gossip membership, '
               'automatic proxy tools, API-key identity with a synced key directory, two-sided authorization, blocks.'),
            _p('SAJHA Net instances', 'net_instances_page', 'bi-hdd-network',
               'Every instance in your nets, this server first, and the tools each offers you, with Try it.'),
            _p('Your net access', 'net_access_page', 'bi-person-check',
               'Every remote tool by name, the hosts offering it in resolution order, and which you may use.'),
            _p('Net overview', 'admin_sajhanet_overview_page', 'bi-diagram-3',
               'Administrators: one net at a glance, with its topology map, members, admission, notices, conflicts, blocks and recent calls.'),
            _g('System notices', 'System Notices.md', 'bi-exclamation-triangle',
               'One place where SAJHA shows what needs attention: notices from the schema check, circuit '
               'breakers, workflows, LLM providers, federation and alert rules; the console banner, the '
               'dashboard System status panel, the navbar badge, acknowledgement and the admin API.'),
            _g('Implementation plan', 'Implementation Plan.md', 'bi-list-ol',
               'The build order for LLM tools, SAJHA Net and the open roadmap items, in five waves, '
               'each a release with its contents, dependencies, exit gates and risks.'),
            _g('Roadmap', 'Roadmap.md', 'bi-signpost-2',
               'What is not built yet and what should come next: release hygiene, the gaps the guides record, '
               'and recommended enhancements, each with its size, dependencies and the guide that owns it.'),
        ],
    },
    {
        'id': 'studio', 'name': 'MCP Studio', 'icon': 'bi-magic',
        'blurb': 'Build tools in the browser, from code, services and enterprise sources.',
        'groups': [
            ('Start here', ['MCP Studio User Guide', 'Describe a tool']),
            ('Code and services', ['Python code tools', 'REST service tools', 'Import an API',
                                   'DB query tools', 'Script tools']),
            ('Enterprise sources', ['Power BI reports', 'Power BI DAX queries', 'IBM LiveLink',
                                    'SharePoint', 'OLAP datasets']),
            ('Language models', ['LLM tool creator']),
        ],
        'topics': [
            _g('MCP Studio User Guide', 'MCP Studio User Guide.md', 'bi-magic',
               'What Studio builds, how a generated tool is deployed, and a guide per creator.'),
            _g('Describe a tool', 'Tool Generation.md', 'bi-chat-square-text',
               'Say what a tool should do; review the proposed files, run its tests, approve the deploy.'),
            _g('Python code tools', 'MCP Studio Python Code Tool Creator Guide.md', 'bi-code-slash',
               'Turn a Python function with the @sajhamcptool decorator into a tool.'),
            _g('REST service tools', 'MCP Studio REST Tool Creator Guide.md', 'bi-cloud-arrow-up',
               'Wrap an HTTP endpoint as a tool.'),
            _g('Import an API', 'API Import.md', 'bi-filetype-json',
               'OpenAPI 3.x, Swagger 2.0 or GraphQL to a reviewed set of tools: mapping, auth, SSRF '
               'guard, re-import diff.'),
            _g('DB query tools', 'MCP Studio DBQuery Tool Creator Guide.md', 'bi-database',
               'A parameterised SQL query as a tool.'),
            _g('Script tools', 'MCP Studio Script Tool Creator Guide.md', 'bi-terminal',
               'Run a shell or Python script as a tool.'),
            _g('Power BI reports', 'MCP Studio PowerBI Tool Creator Guide.md', 'bi-bar-chart-fill',
               'Export a Power BI report as a tool.'),
            _g('Power BI DAX queries', 'MCP Studio PowerBI DAX Tool Creator Guide.md', 'bi-braces',
               'A DAX query against a Power BI dataset as a tool.'),
            _g('IBM LiveLink', 'MCP Studio LiveLink Tool Creator Guide.md', 'bi-folder2-open',
               'Search and fetch LiveLink documents.'),
            _g('SharePoint', 'MCP Studio SharePoint Tool Creator Guide.md', 'bi-microsoft',
               'Search and fetch SharePoint content.'),
            _g('OLAP datasets', 'MCP Studio OLAP Tool Creator Guide.md', 'bi-graph-up-arrow',
               'Slice an OLAP dataset as a tool.'),
            _g('LLM tool creator', 'MCP Studio LLM Tool Creator Guide.md', 'bi-chat-square-text',
               'A tool a language model runs: mode, model, allowed tools, limits and memory in a form; '
               'tried on the mock model, deployed or edited as a config file.'),
        ],
    },
    {
        'id': 'tools', 'name': 'Tools and prompts', 'icon': 'bi-tools',
        'blurb': 'The live tool catalog, one reference guide per provider, and prompts.',
        'groups': [
            ('Live', ['Tool catalog']),
            ('Market data', ['Alpha Vantage', 'CoinGecko', 'FMP', 'FRED', 'OpenBB', 'Yahoo Finance']),
            ('Central banks', ['Bank of Canada', 'Bank of Japan', 'Banque de France',
                               'European Central Bank', 'Federal Reserve',
                               'Peoples Bank of China', 'Reserve Bank of India']),
            ('Public data', ['FBI', 'IMF', 'United Nations', 'World Bank']),
            ('Filings', ['SEC EDGAR', 'Investor Relations']),
            ('Search', ['Google Search', 'MSDOC Search', 'Tavily Search', 'Web Crawler',
                        'Wikipedia Search']),
            ('Analytics', ['DuckDB', 'Financial Calculators', 'OLAP Analytics', 'SQL Select']),
            ('Enterprise', ['SharePoint (tools)', 'Connected accounts (tools)', 'Data connectors (tools)']),
            ('Prompts', ['Prompts Management Guide']),
        ],
        'topics': [
            _b('Tool catalog', 'help_tools_page', 'bi-grid-3x3-gap',
               'Every tool the server has loaded right now, by provider group. Derived from the '
               'registry, so it is never out of date.'),
            _tool('Alpha Vantage', 'bi-graph-up', 'Stock quotes and time series, fundamentals, technical indicators, forex and crypto.'),
            _tool('CoinGecko', 'bi-currency-bitcoin', 'Coin prices and charts, exchanges, categories, DeFi, derivatives and NFTs.'),
            _tool('FMP', 'bi-building', 'Financial Modeling Prep: statements, valuation, market data and screens.'),
            _tool('FRED', 'bi-bank', "The St. Louis Fed's economic series."),
            _tool('OpenBB', 'bi-box-seam', 'The OpenBB Platform SDK: equities, ETFs, fixed income, economy and more.'),
            _tool('Yahoo Finance', 'bi-graph-up-arrow', 'Quotes, price history and company information.'),
            _tool('Bank of Canada', 'bi-bank2', 'Bank of Canada rates and series.'),
            _tool('Bank of Japan', 'bi-bank2', 'Bank of Japan rates and series.'),
            _tool('Banque de France', 'bi-bank2', 'Banque de France series.'),
            _tool('European Central Bank', 'bi-bank2', 'ECB rates, exchange rates and series.'),
            _tool('Federal Reserve', 'bi-bank2', 'Federal Reserve rates and series.'),
            _tool('Peoples Bank of China', 'bi-bank2', "People's Bank of China rates and series."),
            _tool('Reserve Bank of India', 'bi-bank2', 'Reserve Bank of India rates and series.'),
            _tool('FBI', 'bi-shield', 'FBI crime data.'),
            _tool('IMF', 'bi-globe', 'International Monetary Fund datasets.'),
            _tool('United Nations', 'bi-globe2', 'United Nations statistics.'),
            _tool('World Bank', 'bi-globe-americas', 'World Bank development indicators.'),
            _tool('SEC EDGAR', 'bi-file-earmark-text', 'Filings and company facts from the public SEC APIs.'),
            _tool('Investor Relations', 'bi-briefcase', 'Annual reports, presentations and releases from company IR sites.'),
            _tool('Google Search', 'bi-google', 'Web search through the Google Custom Search API.'),
            _tool('MSDOC Search', 'bi-microsoft', 'Search Microsoft documentation.'),
            _tool('Tavily Search', 'bi-search', 'Web search built for agents.'),
            _tool('Web Crawler', 'bi-globe', 'Fetch and extract web pages.'),
            _tool('Wikipedia Search', 'bi-wikipedia', 'Search and read Wikipedia.'),
            _tool('DuckDB', 'bi-database', 'SQL over local files with DuckDB.'),
            _tool('Financial Calculators', 'bi-calculator', 'Pure-math financial calculators that need no API key.'),
            _tool('OLAP Analytics', 'bi-graph-up-arrow', 'Slice and aggregate OLAP datasets.'),
            _tool('SQL Select', 'bi-table', 'Read-only SQL queries against configured databases.'),
            _g('SharePoint (tools)', 'SharePoint Tool Reference Guide.md', 'bi-microsoft',
               'Documents, lists and search on a SharePoint Online site, and their known issues.'),
            _g('Connected accounts (tools)', 'Connected Account Tools Reference Guide.md', 'bi-link-45deg',
               'GitHub, Slack, Google Drive and Outlook tools that act as the signed-in user, and '
               'connected_http_request.'),
            _g('Data connectors (tools)', 'Data Connectors Reference Guide.md', 'bi-database-gear',
               'Per-kind setup (PostgreSQL, MySQL, SQL Server, Oracle, Snowflake, BigQuery, Databricks, '
               'Redshift, SQLite, DuckDB, pgvector, Qdrant, Elasticsearch) and the tools each connection gets.'),
            _g('Prompts Management Guide', 'Prompts Management Guide.md', 'bi-chat-square-text',
               'Prompt configs, arguments, and the prompt pages.'),
        ],
    },
    {
        'id': 'tutorials', 'name': 'Tutorials', 'icon': 'bi-mortarboard',
        'blurb': 'Step-by-step walkthroughs, in reading order.',
        'topics': [
            _g('1. Getting started', 'TUTORIAL_01_getting_started.md', 'bi-1-circle',
               'Browse, execute and connect.'),
            _g('2. Create a custom tool', 'TUTORIAL_02_create_a_custom_tool.md', 'bi-2-circle',
               'A tool configuration and its implementation.'),
            _g('3. Build a composite tool', 'TUTORIAL_03_build_a_composite_tool.md', 'bi-3-circle',
               'Chain tools into one.'),
            _g('4. Create a plugin', 'TUTORIAL_04_create_a_plugin.md', 'bi-4-circle',
               'Package tools as a plugin.'),
            _g('5. Connect the Python SDK', 'TUTORIAL_05_connect_the_python_sdk.md', 'bi-5-circle',
               'Call SAJHA from Python.'),
            _g('6. Configure tool caching', 'TUTORIAL_06_configure_tool_caching.md', 'bi-6-circle',
               'cache_ttl, the cache statistics, and circuit breakers.'),
            _g('7. Submit async tool execution', 'TUTORIAL_07_submit_async_tool_execution.md', 'bi-7-circle',
               'Background runs and where their results go.'),
            _g('8. Custom configuration', 'TUTORIAL_08_custom_configuration.md', 'bi-8-circle',
               'Your own application.yml and environment overrides.'),
            _g('9. Call SAJHA from the standard MCP client', 'TUTORIAL_09_call_sajha_from_the_standard_mcp_client.md',
               'bi-9-circle', 'The official MCP Python SDK against SAJHA.'),
            _g('10. Ask SAJHA', 'TUTORIAL_10_ask_sajha.md', 'bi-stars',
               'Ask a question in the console and read the tool chain behind the answer.'),
            _g('11. Federate an MCP server', 'TUTORIAL_11_federate_an_mcp_server.md', 'bi-diagram-2',
               'Run a small MCP server, put it behind SAJHA, approve its tools and call them.'),
            _g('12. Python Playground', 'TUTORIAL_12_python_playground.md', 'bi-filetype-py',
               'Call a SAJHA tool from Python in the browser, analyse the result with pandas and chart it.'),
            _g('13. Run SAJHA on several workers', 'TUTORIAL_13_run_sajha_on_several_workers.md', 'bi-hdd-stack',
               'Share state through Redis, check /health, watch a change reach another worker.'),
            _g('14. Sandboxed Studio tools', 'TUTORIAL_14_sandboxed_studio_tools.md', 'bi-shield-check',
               'Deploy a Python and a script tool, watch the sandbox block them, grant network access.'),
            _g('15. The sajha CLI and Claude Desktop', 'TUTORIAL_15_sajha_cli_and_claude_desktop.md', 'bi-terminal',
               'Sign in, call tools and ask from a terminal; add SAJHA to Claude Code and Claude Desktop over stdio.'),
            _g('16. Metrics, costs and alerts', 'TUTORIAL_16_metrics_costs_and_alerts.md', 'bi-cash-coin',
               'Scrape /metrics with Prometheus, import the Grafana dashboard, read the Usage & cost page, '
               'fire an alert.'),
            _g('17. Deploy SAJHA on Kubernetes', 'TUTORIAL_17_deploy_sajha_on_kubernetes.md', 'bi-boxes',
               'Build the image, install the Helm chart on kind behind ingress-nginx, scale to three '
               'pods on Redis and PostgreSQL.'),
            _g('18. Connect your accounts', 'TUTORIAL_18_connect_your_accounts.md', 'bi-link-45deg',
               'Register a GitHub OAuth app, link your account, call a tool as you from the console, '
               'REST, MCP and Ask SAJHA, then disconnect.'),
            _g('19. Import an OpenAPI spec', 'TUTORIAL_19_import_an_openapi_spec.md', 'bi-filetype-json',
               'Import the petstore spec, deploy three operations, call one over MCP and from Ask SAJHA, '
               're-import a changed spec.'),
            _g('20. Policies, approvals and audit', 'TUTORIAL_20_policies_approvals_and_audit.md', 'bi-shield-check',
               'Write a policy, try it on the test bench, approve a held call, redact a result, verify the '
               'audit chain and catch a tampered record, stream to a SIEM.'),
            _g('21. Planners, memory and document search', 'TUTORIAL_21_planners_memory_and_rag.md', 'bi-diagram-3',
               'Run a plan with parallel steps, add a recipe and a router, ask a follow-up, delete your history, '
               'ask the docs and index your own documents.'),
            _g('22. Schedule a workflow', 'TUTORIAL_22_schedule_a_workflow.md', 'bi-calendar-check',
               'Build a workflow with a branch and a loop, run it, schedule it, trigger it from a signed '
               'webhook, watch a run resume, re-run a failed step, publish it as a tool.'),
            _g('23. Test and canary your tools', 'TUTORIAL_23_test_and_canary_your_tools.md', 'bi-heart-pulse',
               'Write test cases, record a cassette and replay it offline in CI, lint the catalog, probe a tool, '
               'run an eval on the mock provider, canary a new version and watch it roll back.'),
            _g('24. Describe a tool', 'TUTORIAL_24_describe_a_tool.md', 'bi-chat-square-text',
               'Describe three tools in plain words, read the proposals, run their tests in the sandbox and '
               'against fixtures, approve one, and watch the checks refuse an unsafe proposal.'),
            _g('25. Connect a database', 'TUTORIAL_25_connect_a_database.md', 'bi-database-gear',
               'Run PostgreSQL in Docker, connect it read-only, browse the catalog, mask a column, add a curated '
               'view, watch the guard refuse writes, and ask SAJHA a question about the data.'),
            _g('26. Build an LLM tool', 'TUTORIAL_26_build_an_llm_tool.md', 'bi-chat-square-text',
               'Write a classifier and a summariser as config files, call them on the mock model, add memory to '
               'an assistant, watch it run as the caller, and evaluate it before enabling it.'),
            _g('27. Write a planner', 'TUTORIAL_27_write_a_planner.md', 'bi-signpost-split',
               'Write a planner file for a desk: match a known question shape, call one tool, check the figures, '
               'loop a bounded number of times, dry-run it on the mock model, pin it in an LLM tool and version it.'),
            _g('28. Build a SAJHA Net', 'TUTORIAL_28_build_a_sajha_net.md', 'bi-share',
               'Three instances in one net: a founder with its CA, two joining through it, a tool called across '
               'as yourself, a block, the test admin key and per-member keys.'),
        ],
    },
    {
        'id': 'connect', 'name': 'Clients and security', 'icon': 'bi-shield-lock',
        'blurb': 'Calling SAJHA from code, and how it is secured.',
        'topics': [
            _g('Client SDK Guide', 'Client SDK Guide.md', 'bi-plug',
               'SajhaMCPClient on the official SDK; the REST and A2A clients.'),
            _g('Command Line', 'Command Line.md', 'bi-terminal',
               'The sajha CLI (tools, prompts, ask, Studio, federation) and MCP over stdio for '
               'Claude Desktop, Claude Code and IDEs.'),
            _g('SAJHA Net Agent', 'SAJHA Net Agent.md', 'bi-hdd-network',
               'Any MCP server as a SAJHA Net participant: the agent, the reference library, sponsoring '
               'instead, and the conformance suite.'),
            _g('Security Model', 'Security Model.md', 'bi-shield-check',
               'Credentials, roles, tool access, OAuth, Origin checks, headers, rate limits, the '
               'security fixes, known limitations and the deployment checklist.'),
        ],
    },
    {
        'id': 'reference', 'name': 'Reference', 'icon': 'bi-journal-bookmark',
        'blurb': 'Every guide in one list, every term defined, what this server is, and how it compares.',
        'topics': [
            _b('Guide library', 'help_guides', 'bi-collection',
               'Every guide, grouped by folder.'),
            _p('Glossary', 'glossary', 'bi-journal-text',
               'Every term, acronym and SAJHA-specific word, defined once.'),
            _p('About SAJHA', 'about_page', 'bi-info-circle',
               'What this server is, and what it is running now.'),
            _p('How SAJHA compares', 'comparison_page', 'bi-bar-chart-steps',
               'Next to MCP frameworks, gateways and hosted platforms: sourced verdicts, dated, '
               'including where the others are stronger.'),
        ],
    },
]


# ── Lookups ─────────────────────────────────────────────────────────────────

_url_for: Optional[Callable] = None


def set_url_for(fn: Callable) -> None:
    """Install the app's url_for (sajha/app.py does this at startup)."""
    global _url_for
    _url_for = fn


def href(topic: dict) -> str:
    """The URL a topic card links to."""
    if topic['kind'] == 'guide':
        from sajha.web.guides import guide_url
        return guide_url(topic['file'])
    if _url_for is None:
        raise RuntimeError('help_catalog.set_url_for() has not been called')
    return _url_for(topic['endpoint'])


def category(cid: str) -> Optional[dict]:
    """The category with this id, or None."""
    return next((c for c in CATALOG if c['id'] == cid), None)


def grouped(cat: dict) -> list:
    """[(group title or None, [topic, ...])] for a category's page. A topic named by no
    group is shown last, under "More", so adding a card can never make it vanish."""
    topics = {t['title']: t for t in cat['topics']}
    if not cat.get('groups'):
        return [(None, list(cat['topics']))]
    out, used = [], set()
    for title, names in cat['groups']:
        members = [topics[n] for n in names if n in topics]
        used.update(n for n in names if n in topics)
        if members:
            out.append((title, members))
    rest = [t for t in cat['topics'] if t['title'] not in used]
    if rest:
        out.append(('More', rest))
    return out


def guide_files() -> List[str]:
    """Every guide file the catalog names."""
    return [t['file'] for c in CATALOG for t in c['topics'] if t['kind'] == 'guide']


def _find(pred):
    for cat in CATALOG:
        for t in cat['topics']:
            if pred(t):
                return cat, t
    return None


def _related(hit, companion_file: Optional[str]) -> dict:
    companion = ({'file': companion_file, 'title': companion_file[:-3]}
                 if companion_file else None)
    if hit is None:
        return {'category': None, 'cid': None, 'siblings': [], 'companion': companion}
    cat, self_topic = hit
    siblings = [t for t in cat['topics'] if t is not self_topic
                and not (companion_file and t.get('file') == companion_file)][:6]
    return {'category': cat['name'], 'cid': cat['id'], 'siblings': siblings,
            'companion': companion}


def related_for(endpoint: Optional[str]) -> Optional[dict]:
    """Context for the shared help footer of a page: its category siblings and its
    companion guide (the guide that owns its topic). None when there is neither."""
    if not endpoint:
        return None
    hit = _find(lambda t: t.get('endpoint') == endpoint)
    fn = COMPANION_GUIDE.get(endpoint)
    if hit is None and fn:
        hit = _find(lambda t: t.get('file') == fn)        # the companion's own category
    if hit is None and not fn:
        return None
    return _related(hit, fn)


def related_for_guide(name: str) -> Optional[dict]:
    """Footer context for a guide page: the other topics in its category."""
    hit = _find(lambda t: t.get('file') == name)
    if hit is None:
        return None
    return _related(hit, None)


# ── The live tool catalog (registry-derived) ────────────────────────────────

_GROUP_ICONS = ['bi-tools', 'bi-graph-up', 'bi-database', 'bi-globe', 'bi-bank',
                'bi-search', 'bi-calculator', 'bi-file-text', 'bi-currency-exchange']
_GROUP_TONES = ['crimson', 'ok', 'indigo', 'warn', 'bad', 'slate']


def live_tool_groups(registry=None, with_names: bool = False, visible=None) -> dict:
    """{'total_tools', 'total_groups', 'groups': [...]} from the tools registry.

    Counts cover the whole catalog; tool *names* and descriptions (``examples``, ``tools``)
    are limited to those ``visible(name)`` allows, so a page can pass the viewer's
    ``ToolPolicy.can_see`` (sajha/auth/access.py) and show nobody a tool that ``tools/list``
    would hide from them. ``visible=None`` shows every name (callers that print counts only).

    A tool's group is the text before the first '_' in its name (GLOSSARY: Tool group).
    This is the one implementation; the landing page, /help/tools and Ask SAJHA use it.
    ``with_names`` adds each group's sorted tool names as 'tools' (Ask SAJHA's sky: one star
    per named tool)."""
    if registry is None:
        from sajha.app import tools_registry as registry
    tools = getattr(registry, 'tools', None) or {}
    group_map: Dict[str, dict] = {}
    for name, tool in tools.items():
        prefix = name.split('_')[0] if '_' in name else name
        g = group_map.setdefault(prefix, {'count': 0, 'enabled': 0, 'examples': [], 'names': []})
        g['count'] += 1
        cfg = getattr(tool, 'config', {}) or {}
        if cfg.get('enabled', True):
            g['enabled'] += 1
        if visible is not None and not visible(name):
            continue
        g['names'].append(name)
        if len(g['examples']) < 3:
            g['examples'].append({'name': name, 'description': (cfg.get('description') or '')[:90]})
    groups = []
    for i, (gname, g) in enumerate(sorted(group_map.items(), key=lambda x: (-x[1]['count'], x[0]))):
        groups.append({'name': gname, 'tool_count': g['count'], 'enabled_count': g['enabled'],
                       'icon': _GROUP_ICONS[i % len(_GROUP_ICONS)],
                       'tone': _GROUP_TONES[i % len(_GROUP_TONES)],
                       'examples': g['examples']})
        if with_names:
            groups[-1]['tools'] = sorted(g['names'])
    return {'total_tools': len(tools), 'total_groups': len(group_map), 'groups': groups}
