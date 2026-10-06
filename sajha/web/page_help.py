"""
"About this page": the short help at the foot of every console page.

Each page ends with one line saying what it is for, the terms it uses (as tiles), and
the guide that owns its topic ("Full reference"), plus related help from the catalog.
The definitions are NOT written here: every term is looked up in GLOSSARY.md, the single
source of definitions (sajha/web/glossary.py). This replaced 25 hand-written
``{% block page_glossary %}`` blocks that had drifted from the glossary and the code.

One entry per page, keyed by the route's endpoint name (the FastAPI route name, which is
the handler's function name unless the route sets ``name=``). ``tests/`` fail when a
console page has no entry, when a term is not in GLOSSARY.md, or when a guide does not
exist, so a new screen cannot be added without saying what it is.

    endpoint: {"what": one line, "terms": [glossary term names], "guide": guide file name}

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

from typing import Optional

_TOOLS_TERMS = ['Tool', 'Tool group', 'Enabled / Tool Status', 'Semantic tool search']
_PROMPT_LIST_TERMS = ['Prompt', 'Prompt template / Template', 'Variable substitution',
                      'Prompts Registry', 'Category', 'Arguments (prompt)']

PAGE_HELP: dict = {
    # ── Use ──────────────────────────────────────────────────────────────────
    'dashboard': {
        'what': 'Server status at a glance: what is loaded, operational metrics, and where to start.',
        'terms': ['Tool', 'Prompt', 'Circuit breaker', 'Tool cache / cache_ttl'],
        'guide': 'Quick Start.md'},
    'tools_list': {
        'what': 'Every tool the server has loaded; open one to inspect its schema, run it or see its configuration.',
        'terms': _TOOLS_TERMS,
        'guide': 'TUTORIAL_01_getting_started.md'},
    'tool_execute_page': {
        'what': 'Run one tool with arguments you enter, and see the result exactly as an MCP client would.',
        'terms': ['Execute', 'Input Schema', 'Arguments (tool)', 'Execution Result',
                  'JSON-RPC 2.0', 'Execution History'],
        'guide': 'TUTORIAL_01_getting_started.md'},
    'tool_schema_page': {
        'what': "A tool's contract: the arguments it accepts and the result it returns.",
        'terms': ['JSON Schema', 'Input Schema', 'Output Schema', 'Properties', 'Required', 'Type'],
        'guide': 'TUTORIAL_02_create_a_custom_tool.md'},
    'tool_config_page': {
        'what': "A tool's JSON configuration as loaded from config/tools/.",
        'terms': ['Tool configuration', 'JSON Schema', 'Input Schema', 'Output Schema',
                  'Hot-reload', 'Enabled / Tool Status'],
        'guide': 'TUTORIAL_02_create_a_custom_tool.md'},
    'reports_dashboard': {
        'what': 'Usage and performance reports: calls, errors and latency over time, by tool and by user.',
        'terms': ['Execution count', 'Error rate', 'Latency', 'User activity', 'Audit log'],
        'guide': 'Architecture.md'},
    # ── Prompts ──────────────────────────────────────────────────────────────
    'prompts_list': {
        'what': 'The prompt library: reusable templates that MCP clients list and fill in.',
        'terms': _PROMPT_LIST_TERMS, 'guide': 'Prompts Management Guide.md'},
    'prompts_by_category': {
        'what': 'The prompts in one category.',
        'terms': _PROMPT_LIST_TERMS, 'guide': 'Prompts Management Guide.md'},
    'prompts_by_tag': {
        'what': 'The prompts carrying one tag.',
        'terms': _PROMPT_LIST_TERMS, 'guide': 'Prompts Management Guide.md'},
    'prompt_detail': {
        'what': "One prompt: its template, its arguments and its configuration.",
        'terms': ['Prompt', 'Prompt template / Template', 'Arguments (prompt)', 'Category',
                  'JSON Configuration', 'Test (prompt)'],
        'guide': 'Prompts Management Guide.md'},
    'prompt_test': {
        'what': 'Fill in a prompt\'s arguments and see the messages it renders, before a client does.',
        'terms': ['Test (prompt)', 'Render', 'Variable substitution', 'Arguments (prompt)',
                  'Output (prompt)', 'Copy'],
        'guide': 'Prompts Management Guide.md'},
    'prompt_create_page': {
        'what': 'Write a new prompt: its template, its arguments and where it is listed.',
        'terms': ['Prompt template / Template', 'Variable substitution', 'Arguments (prompt)',
                  'Category', 'Description', 'Jinja2'],
        'guide': 'Prompts Management Guide.md'},
    'admin_prompts': {
        'what': 'Create, edit and retire prompts; changes reach clients without a restart.',
        'terms': ['Prompt management', 'Prompt template / Template', 'Variable substitution',
                  'Hot-reload', 'Category', 'Arguments (prompt)'],
        'guide': 'Prompts Management Guide.md'},
    # ── AI ───────────────────────────────────────────────────────────────────
    'ai_settings_page': {
        'what': 'LLM providers, their models and the default the server uses.',
        'terms': ['LLM gateway', 'Semantic tool search', 'Embedding', 'bm25 (embedder)',
                  'gateway (embedder)'],
        'guide': 'Architecture.md'},
    # ── Monitor ──────────────────────────────────────────────────────────────
    'monitoring_tools': {
        'what': 'Calls, latency and errors per tool, refreshed while the page is open.',
        'terms': ['Monitoring', 'Execution count', 'Average execution time', 'Error rate',
                  'Latency', 'Real-time updates'],
        'guide': 'Architecture.md'},
    'monitoring_users': {
        'what': 'Who is signed in, and who called what, and when.',
        'terms': ['User activity', 'Session (web)', 'Active users', 'Request count',
                  'Last activity', 'Audit log'],
        'guide': 'Security Model.md'},
    # ── Admin ────────────────────────────────────────────────────────────────
    'admin_tools_page': {
        'what': 'Enable, disable and reload tools, with their call counts and timings.',
        'terms': ['Tool management', 'Hot-reload', 'Execution count', 'Average execution time',
                  'Enabled / Tool Status', 'Force reload'],
        'guide': 'TUTORIAL_02_create_a_custom_tool.md'},
    'admin_users_page': {
        'what': 'Accounts and their roles.',
        'terms': ['RBAC', 'User ID', 'Role', 'Password hash', 'Session token', 'Account status'],
        'guide': 'Security Model.md'},
    'admin_user_create_page': {
        'what': 'Create an account and give it a role.',
        'terms': ['User ID', 'RBAC', 'Password hash', 'Role', 'Tool access', 'Account status'],
        'guide': 'Security Model.md'},
    'apikeys_list': {
        'what': 'API keys: credentials for programs, each limited to the tools it may call.',
        'terms': ['API key', 'Bearer token', 'X-API-Key header', 'Tool access', 'Rate limiting',
                  'Key rotation'],
        'guide': 'Security Model.md'},
    'apikey_create_page': {
        'what': 'Create an API key and choose the tools it may call. The key is shown once.',
        'terms': ['API key', 'Tool access mode', 'Allowlist', 'Denylist', 'Regex pattern',
                  'Expiration'],
        'guide': 'Security Model.md'},
    'apikey_view': {
        'what': 'One API key: its access, its use, and how to call SAJHA with it.',
        'terms': ['API key', 'X-API-Key header', 'Tool access', 'curl', 'Key revocation',
                  'Created at'],
        'guide': 'Security Model.md'},
    'admin_system_monitor_page': {
        'what': 'The process: CPU, memory, connections, provider health and the tool cache.',
        'terms': ['Monitoring', 'Circuit breaker', 'ProviderHealth', 'Tool cache / cache_ttl',
                  'Latency'],
        'guide': 'TUTORIAL_06_configure_tool_caching.md'},
    'admin_async_tasks_page': {
        'what': 'Background tool runs submitted for asynchronous execution, and where their results go.',
        'terms': ['Async execution', 'AsyncTask', 'DeliveryRouter', 'Backpressure'],
        'guide': 'TUTORIAL_07_submit_async_tool_execution.md'},
    # ── MCP Studio ───────────────────────────────────────────────────────────
    'studio_home': {
        'what': 'Build tools in the browser; this page is also the Python code tool creator.',
        'terms': ['MCP Studio', 'Creator', '@sajhamcptool decorator', 'AST', 'Type hints',
                  'Code generation'],
        'guide': 'MCP Studio User Guide.md'},
    'studio_examples': {
        'what': 'Worked examples to start a Python code tool from.',
        'terms': ['Template (Studio)', '@sajhamcptool decorator', 'Type hints', 'Docstring'],
        'guide': 'MCP Studio Python Code Tool Creator Guide.md'},
    'studio_rest': {
        'what': 'Wrap an HTTP endpoint as a tool.',
        'terms': ['REST', 'HTTP method', 'Endpoint', 'Path parameter', 'Content-Type',
                  'Basic authentication', 'API key (REST creator)', 'JSON Schema'],
        'guide': 'MCP Studio REST Tool Creator Guide.md'},
    'studio_dbquery': {
        'what': 'Turn a parameterised SQL query into a tool.',
        'terms': ['Query template', 'Parameter escaping', 'Connection string', 'DuckDB',
                  'SQLite', 'PostgreSQL', 'MySQL', 'Literature'],
        'guide': 'MCP Studio DBQuery Tool Creator Guide.md'},
    'studio_script': {
        'what': 'Run a shell or Python script as a tool.',
        'terms': ['Creator', 'Shell tools / ShellExecutor', 'Input Schema', 'Code generation'],
        'guide': 'MCP Studio Script Tool Creator Guide.md'},
    'studio_powerbi': {
        'what': 'Export a Power BI report as a tool.',
        'terms': ['Power BI', 'Creator', 'Code generation'],
        'guide': 'MCP Studio PowerBI Tool Creator Guide.md'},
    'studio_powerbidax': {
        'what': 'Run a DAX query against a Power BI dataset as a tool.',
        'terms': ['DAX', 'Power BI', 'Creator'],
        'guide': 'MCP Studio PowerBI DAX Tool Creator Guide.md'},
    'studio_livelink': {
        'what': 'Search and fetch IBM LiveLink documents as a tool.',
        'terms': ['LiveLink', 'Creator', 'Code generation'],
        'guide': 'MCP Studio LiveLink Tool Creator Guide.md'},
    'studio_sharepoint': {
        'what': 'Search and fetch SharePoint content as a tool.',
        'terms': ['SharePoint', 'Creator', 'Code generation'],
        'guide': 'MCP Studio SharePoint Tool Creator Guide.md'},
    'studio_olap': {
        'what': 'Slice an OLAP dataset as a tool.',
        'terms': ['OLAP', 'DuckDB', 'Creator'],
        'guide': 'MCP Studio OLAP Tool Creator Guide.md'},
    'composite_builder': {
        'what': 'Chain tools into one composite tool, with the confidence of its result tracked.',
        'terms': ['Composite tool', 'Sibling (composite)', 'Parent-child (composite)',
                  'ParamLens', 'EntropyGuard', 'Confidence score'],
        'guide': 'Composition Framework.md'},
    # ── Not a route: common/error.html asks for this entry by name ──────────
    'error': {
        'what': 'Something went wrong; the message above says what.',
        'terms': ['Error', 'HTTP status code', 'Exception'],
        'guide': 'How SAJHA Fits Together.md'},
}

#: Keys that are not route names (looked up explicitly by a template).
NON_ROUTE_KEYS = {'error'}


def endpoint_of(request) -> Optional[str]:
    """The FastAPI route name that served ``request``, or None (e.g. a 404)."""
    try:
        route = request.scope.get('route')
    except Exception:
        return None
    return getattr(route, 'name', None)


def page_help(endpoint: Optional[str]) -> Optional[dict]:
    """The rendered panel for a page: {what, terms: [glossary rows], guide: {file,
    title, url}, related: help_related} or None when the page has no entry."""
    entry = PAGE_HELP.get(endpoint or '')
    if not entry:
        return None
    from sajha.web.glossary import lookup
    from sajha.web.guides import guide_url
    from sajha.web.help_catalog import related_for
    terms = [t for t in (lookup(n) for n in entry['terms']) if t]
    guide = entry.get('guide')
    return {
        'what': entry['what'],
        'terms': terms,
        'guide': {'file': guide, 'title': guide[:-3], 'url': guide_url(guide)} if guide else None,
        'related': related_for(endpoint),
    }
