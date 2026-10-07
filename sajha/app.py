"""
SAJHA MCP Server — Application
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

SajhaMCPServerWebApp: the single orchestrator class.
  - Creates the FastAPI app
  - Initializes DB (runs SQL scripts)
  - Initializes core managers (tools, prompts, MCP handler, hot-reload)
  - Registers all routes from sajha.routes.*
  - Registers template globals, filters, error handlers
  - Manages lifecycle (startup / shutdown)

No route definitions live here. All routes are in sajha/routes/.
"""

import os
import json
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sajha.core.config import get_settings

logger = logging.getLogger(__name__)

from sajha.core.config import get_settings as _get_settings
VERSION = _get_settings().app_version  # Single source: config/application.yml → app.version

# ── Template engine (shared across routes) ───────────────────────
_web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
templates = Jinja2Templates(directory=os.path.join(_web_dir, 'templates'))


def render(request: Request, template_name: str, context: dict = None, status_code: int = 200):
    """
    Render a template with automatic session injection.
    Used by all route modules. Keeps base.html's session.token working.
    """
    ctx = context or {}
    if 'session' not in ctx:
        ctx['session'] = {'token': request.cookies.get('sajha_token', '')}
    if 'can_studio' not in ctx:
        # The navigation shows MCP Studio to admins and to roles with a studio permission, and in
        # it only the creators the caller may use (studio:<creator>)
        from sajha.auth import studio_creators
        ctx['studio_creators'] = studio_creators(getattr(request.state, 'auth', None))
        ctx['can_studio'] = bool(ctx['studio_creators'])
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)


def render_standalone(request: Request, template_name: str, context: dict = None, status_code: int = 200):
    """Render a standalone template (not extending base.html). Used for landing page, login."""
    from sajha.core.config import get_settings
    s = get_settings()
    ctx = context or {}
    # Inject same app globals that base.html templates get
    ctx.setdefault('app_version', s.app_version)
    ctx.setdefault('app_name', s.app_name)
    ctx.setdefault('app_author', s.app_author)
    ctx.setdefault('app_email', s.app_email)
    ctx.setdefault('app_github_repo', s.app_github_repo)
    ctx.setdefault('app_copyright_years', s.app_copyright_years)
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)


_JSON_PATH_PREFIXES = ('/api/', '/mcp', '/a2a', '/admin/studio/', '/oauth/')


def _wants_json(request: Request) -> bool:
    """An API / JSON caller (JSON error) rather than a browser page navigation (redirect / HTML)."""
    path = request.url.path
    if path.startswith(_JSON_PATH_PREFIXES) or request.method not in ('GET', 'HEAD'):
        return True
    accept = request.headers.get('accept', '').lower()
    return 'application/json' in accept and 'text/html' not in accept


def _playground_enabled() -> bool:
    """playground.enabled, read live (sajha/web/playground.py)."""
    try:
        from sajha.web.playground import load_settings
        return load_settings().enabled
    except Exception:
        return False


def _notices_view(request) -> dict:
    from sajha.notices import template_view
    try:
        return template_view(request)
    except Exception:
        return {'enabled': False, 'notices': [], 'banner': None, 'others': 0, 'badge': 0}


def _password_change_required(token: str) -> bool:
    """True when the session JWT says the user must change their password (claim ``pwc``)."""
    if not token:
        return False
    from sajha.auth.jwt_handler import decode_access_token
    payload = decode_access_token(token)
    return bool(payload and payload.get('pwc'))


# ── Module-level references (set by SajhaMCPServerWebApp during startup) ─
tools_registry = None
prompts_registry = None
mcp_handler = None
config_reloader = None


class SajhaMCPServerWebApp:
    """
    Main application class. Orchestrates all components.

    Usage:
        webapp = SajhaMCPServerWebApp()
        uvicorn.run(webapp.app, ...)

    Or in PyCharm:
        python run_server.py
    """

    def __init__(self):
        self.settings = get_settings()
        self.app = self._create_app()

    # ── App Factory ──────────────────────────────────────────────

    def _create_app(self) -> FastAPI:
        app = FastAPI(
            title=self.settings.app_name,
            version=self.settings.app_version,
            description=self.settings.app_description,
            lifespan=self._lifespan,
            docs_url='/api/docs',
            redoc_url='/api/redoc',
        )

        self._add_middleware(app)
        self._mount_static(app)
        self._register_routes(app)
        self._register_error_handlers(app)

        return app

    # ── Middleware ────────────────────────────────────────────────

    def _add_middleware(self, app: FastAPI):
        # The server binds 0.0.0.0:3002 but browsers treat localhost / 127.0.0.1 /
        # 0.0.0.0 as distinct origins. Default to all three loopback forms on the
        # configured port so cross-origin XHR isn't rejected during local use;
        # override with SAJHA_CORS_ORIGINS (comma-separated) in production.
        _default_origins = ','.join(
            f'http://{host}:3002' for host in ('localhost', '127.0.0.1', '0.0.0.0')
        )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=os.environ.get('SAJHA_CORS_ORIGINS', _default_origins).split(','),
            allow_credentials=True,
            allow_methods=['*'],
            allow_headers=['*'],
            expose_headers=['Mcp-Session-Id'],
        )

        # Security headers middleware
        from sajha.security import SecurityHeadersMiddleware, RequestSizeLimitMiddleware
        app.add_middleware(SecurityHeadersMiddleware)
        app.add_middleware(RequestSizeLimitMiddleware, max_body_size=10 * 1024 * 1024)

        # SAJHA Net endpoints are not for browsers: no CORS on /sajhanet/ (protocol §7.3)
        from sajha.net.integration.asgi import NoCorsForNetPaths
        app.add_middleware(NoCorsForNetPaths)

        # Outermost: HTTP metrics and the server span (plain ASGI; streams pass through)
        from sajha.observability.middleware import ObservabilityMiddleware
        app.add_middleware(ObservabilityMiddleware)

    # ── Static Files ─────────────────────────────────────────────

    def _mount_static(self, app: FastAPI):
        static_dir = os.path.join(_web_dir, 'static')
        if os.path.isdir(static_dir):
            app.mount('/static', StaticFiles(directory=static_dir), name='static')

    # ── Route Registration ───────────────────────────────────────

    def _register_routes(self, app: FastAPI):
        """Register all route modules. Every route lives in sajha/routes/."""
        from sajha.routes.auth_routes import router as auth_router
        from sajha.routes.dashboard_routes import router as dashboard_router
        from sajha.routes.api_routes import router as api_router
        from sajha.routes.tools_routes import router as tools_router
        from sajha.routes.admin_routes import router as admin_router
        from sajha.routes.reporting_routes import router as reporting_router
        from sajha.routes.mcp_routes import router as mcp_router
        from sajha.routes.health_routes import router as health_router
        from sajha.routes.prompts_routes import router as prompts_router
        from sajha.routes.studio_routes import router as studio_router
        from sajha.routes.apikeys_routes import router as apikeys_router
        from sajha.routes.credential_files_routes import router as credential_files_router
        from sajha.routes.misc_routes import router as misc_router
        from sajha.routes.a2a_routes import router as a2a_router
        from sajha.routes.ai_routes import router as ai_router
        from sajha.routes.composite_routes import router as composite_router
        from sajha.routes.ws_routes import router as ws_router
        from sajha.routes.ops_routes import router as ops_router
        from sajha.routes.oauth_routes import router as oauth_router
        from sajha.routes.help_routes import router as help_router
        from sajha.routes.sandbox_routes import router as sandbox_router
        from sajha.routes.federation_routes import router as federation_router
        from sajha.routes.playground_routes import router as playground_router
        from sajha.routes.observability_routes import router as observability_router
        from sajha.routes.api_import_routes import router as api_import_router
        from sajha.routes.accounts_routes import router as accounts_router
        from sajha.routes.policy_routes import router as policy_router
        from sajha.routes.quality_routes import router as quality_router
        from sajha.routes.workflow_routes import router as workflow_router
        from sajha.routes.connectors_routes import router as connectors_router
        from sajha.routes.notices_routes import router as notices_router
        from sajha.routes.openai_routes import router as openai_router
        from sajha.routes.conversations_routes import router as conversations_router
        from sajha.routes.sajhanet_routes import router as sajhanet_router

        routers = [
            credential_files_router,   # before apikeys/admin: /admin/apikeys/file, /admin/users/file
            auth_router, dashboard_router, api_router, tools_router,
            admin_router, reporting_router, mcp_router, health_router,
            prompts_router, studio_router, apikeys_router, misc_router,
            a2a_router,
            ai_router,
            composite_router,
            ws_router,
            ops_router,
            oauth_router,
            help_router,
            sandbox_router,
            federation_router,
            playground_router,
            observability_router,
            api_import_router,
            accounts_router,
            policy_router,
            quality_router,
            workflow_router,
            connectors_router,
            notices_router,
            openai_router,
            conversations_router,
            sajhanet_router,
        ]

        for router in routers:
            app.include_router(router)

        logger.info(f'Registered {len(routers)} route modules')

    # ── Error Handlers ───────────────────────────────────────────

    def _register_error_handlers(self, app: FastAPI):
        @app.exception_handler(404)
        async def not_found(request: Request, exc):
            return render(request, 'common/error.html', {
                'error': 'Page Not Found',
                'message': 'The requested page does not exist',
            }, status_code=404)

        @app.exception_handler(401)
        async def unauthorized(request: Request, exc):
            # API / JSON requests get JSON 401; browser page navigations redirect to the landing page
            if _wants_json(request):
                headers = getattr(exc, 'headers', None) or {'WWW-Authenticate': 'Bearer realm="sajha"'}
                return JSONResponse({'error': 'Authentication required'}, status_code=401, headers=headers)
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url='/', status_code=302)

        @app.exception_handler(403)
        async def forbidden(request: Request, exc):
            if _wants_json(request):
                detail = getattr(exc, 'detail', None) or 'Forbidden'
                return JSONResponse({'error': detail}, status_code=403)
            return render(request, 'common/error.html', {
                'error': 'Access Forbidden',
                'message': "You don't have permission to access this resource",
            }, status_code=403)

        @app.exception_handler(500)
        async def internal_error(request: Request, exc):
            logger.error(f'Internal server error: {exc}')
            return render(request, 'common/error.html', {
                'error': 'Internal Server Error',
                'message': 'An unexpected error occurred',
            }, status_code=500)

    # ── Template Globals & Filters ───────────────────────────────

    def _register_template_globals(self):
        s = self.settings

        # Flask url_for() compatibility
        _URL_MAP = {
            'dashboard': '/dashboard',
            'login': '/login',
            'logout': '/logout',
            'tools_list': '/tools',
            'admin_users': '/admin/users',
            'admin_user_create': '/admin/users/create',
            'admin_tools': '/admin/tools',
            'admin_prompts': '/admin/prompts',
            'admin_apikeys': '/admin/apikeys',
            'admin_apikeys_create': '/admin/apikeys/create',
            'admin_apikeys_view': '/admin/apikeys/view',
            'admin_apikeys_edit': '/admin/apikeys/edit',
            'admin_apikeys_delete': '/admin/apikeys/delete',
            'admin_apikeys_toggle': '/admin/apikeys/toggle',
            'prompts_list': '/prompts',
            'prompt_create_page': '/prompts/create',
            'prompt_detail': '/prompts/detail',
            'prompt_test': '/prompts/test',
            'prompts_by_category': '/prompts/category',
            'prompts_by_tag': '/prompts/tag',
            'monitoring_tools': '/monitoring/tools',
            'monitoring_users': '/monitoring/users',
            'ai_settings': '/ai/settings',
            'composite_builder': '/composite/builder',
            'tool_execute': '/tools/{tool_name}/execute',
            'tool_schema': '/tools/{tool_name}/schema',
            'tool_config_page': '/tools/{tool_name}/config',
            'studio_home': '/studio',
            'studio.studio_home': '/studio',
            'studio_rest': '/studio/rest',
            'studio_dbquery': '/studio/dbquery',
            'studio_script': '/studio/script',
            'studio_livelink': '/studio/livelink',
            'studio_olap': '/studio/olap',
            'studio_powerbi': '/studio/powerbi',
            'studio_powerbidax': '/studio/powerbidax',
            'studio_sharepoint': '/studio/sharepoint',
            'studio_examples': '/studio/examples',
            'reports_dashboard': '/reports',
        }

        app = self.app

        def url_for(endpoint, **kwargs):
            if endpoint == 'static':
                return f'/static/{kwargs.get("filename", "")}'
            url = _URL_MAP.get(endpoint)
            if url is None:
                # A route's own name (FastAPI: the handler's name unless name= is set)
                try:
                    return str(app.url_path_for(endpoint, **kwargs))
                except Exception:
                    url = f'/{endpoint}'
            for key, value in kwargs.items():
                url = url.replace(f'{{{key}}}', str(value))
            return url

        from sajha.web import help_catalog, page_help, guides
        help_catalog.set_url_for(url_for)

        templates.env.globals.update({
            'app_name': s.app_name,
            'app_version': s.app_version,
            'app_author': s.app_author,
            'app_email': s.app_email,
            'app_copyright_years': s.app_copyright_years,
            'app_github_repo': s.app_github_repo,
            'app_github_repo_name': s.app_github_repo_name,
            'current_year': datetime.now().year,
            'url_for': url_for,
            # Help: catalog links, guide URLs, and each page's "About this page" panel
            'topic_href': help_catalog.href,
            'guide_url': guides.guide_url,
            'page_help_for': lambda request, key=None: page_help.page_help(
                key or page_help.endpoint_of(request)),
            # Banner in common/base.html until a default / admin-set password is changed
            'password_change_required': _password_change_required,
            # Python Playground menu entry and dashboard action (playground.enabled)
            'playground_enabled': _playground_enabled,
            # System notices: banner and navbar badge (sajha/notices; docs/architecture/System Notices.md)
            'notices_view': _notices_view,
        })

        # Template filters
        def dt_filter(value, length=16):
            if value is None:
                return '-'
            if isinstance(value, datetime):
                fmts = {10: '%Y-%m-%d', 16: '%Y-%m-%d %H:%M'}
                return value.strftime(fmts.get(length, '%Y-%m-%d %H:%M:%S'))
            return str(value)[:length] if isinstance(value, str) else str(value)

        def truncate_text(text, length=100, suffix='...'):
            if not text or len(text) <= length:
                return text or ''
            return text[:length - len(suffix)] + suffix

        def json_pretty(value):
            try:
                if isinstance(value, str):
                    value = json.loads(value)
                return json.dumps(value, indent=2, default=str)
            except Exception as e:
                return str(value)

        templates.env.filters['dt'] = dt_filter
        templates.env.filters['truncate_text'] = truncate_text
        templates.env.filters['json_pretty'] = json_pretty

    # ── Core Manager Initialization ──────────────────────────────

    def _init_managers(self):
        global tools_registry, prompts_registry, mcp_handler, config_reloader

        s = self.settings

        # Initialize PropertiesConfigurator with YAML config values
        # so tool configs can resolve ${var} (e.g. ${data.duckdb.dir} in duckdb_sql.json)
        try:
            from sajha.core.properties_configurator import PropertiesConfigurator
            pc = PropertiesConfigurator(yaml_file=os.environ.get('SAJHA_CONFIG_FILE', 'config/application.yml'))  # YAML-native, respects --config
            logger.info(f'PropertiesConfigurator loaded from application.yml ({len(pc.get_all_properties())} values)')
            # Initialize the storage backend (local | s3) from config BEFORE tools/prompts
            # load, so any reader using get_storage() resolves against the right backend.
            # Default 'local' is a transparent filesystem wrapper — no behaviour change on-prem.
            try:
                from sajha.core.storage import init_storage
                backend = init_storage(pc)
                logger.info(f'Storage backend initialized: {type(backend).__name__}')
                self._storage_sync_interval = int(pc.get('storage.s3.sync_interval', 60) or 60)
            except Exception as se:
                logger.warning(f'Storage backend init failed, falling back to local filesystem: {se}', exc_info=True)
        except Exception as e:
            logger.warning(f'PropertiesConfigurator init failed: {e}', exc_info=True)

        from sajha.tools.tools_registry import get_tools_registry
        from sajha.core.prompts_registry import get_prompts_registry
        from sajha.core.mcp_handler import MCPHandler
        from sajha.core.hot_reload_manager import get_config_reloader

        tools_registry = get_tools_registry(
            tools_config_dir=s.config_tools_dir, force_reinit=True,
        )
        logger.info(f'Tools registry: {len(tools_registry.tools)} tools')

        prompts_registry = get_prompts_registry(
            prompts_config_dir=s.config_prompts_dir, force_reinit=True,
        )
        logger.info(f'Prompts registry: {len(prompts_registry.prompts)} prompts')

        # ── Cloud hot-reload (item 4) ────────────────────────────────────────
        # Object stores (s3/azure/gcs) have no inotify, so the local file watcher
        # cannot see changes. For a cloud backend we start the object-store sync
        # manager, which polls the bucket, mirrors changed objects into the local
        # cache, and fires the same reload paths the local watcher uses. For the
        # local backend this is skipped — the registry's own poller handles it.
        self._sync_mgr = None
        try:
            from sajha.core.storage import get_storage, LocalStorageBackend, S3SyncManager
            _storage = get_storage()
            if not isinstance(_storage, LocalStorageBackend):
                interval = getattr(self, '_storage_sync_interval', 60)
                sync_mgr = S3SyncManager(_storage, interval=interval)
                if tools_registry is not None:
                    sync_mgr.watch(tools_registry._config_prefix, tools_registry.reload_all_tools)
                if prompts_registry is not None:
                    sync_mgr.watch(getattr(prompts_registry, '_prompts_prefix', 'config/prompts'),
                                   prompts_registry.reload)
                sync_mgr.start()
                self._sync_mgr = sync_mgr
                logger.info(f'Object-store sync manager active for {type(_storage).__name__} '
                            f'(interval={interval}s) — watching config/tools + config/prompts')
        except Exception as e:
            logger.warning(f'Object-store sync manager init failed: {e}', exc_info=True)

        # Per-caller tool access on every MCP transport (sajha/auth/access.py)
        from sajha.auth.access import SessionToolAccess
        mcp_handler = MCPHandler(
            tools_registry=tools_registry,
            auth_manager=SessionToolAccess(),
            prompts_registry=prompts_registry,
        )
        logger.info('MCP handler initialized')

        # Persistent API keys (config.apikeys.path): the hot-reload watch re-reads the file
        try:
            from sajha.auth.persistent_keys import get_persistent_keys
            _persistent_keys = get_persistent_keys()
        except Exception as e:
            logger.warning(f'Persistent API keys: unavailable ({e})')
            _persistent_keys = None
        config_reloader = get_config_reloader(
            auth_manager=None,
            apikey_manager=_persistent_keys,
            tools_registry=tools_registry,
            prompts_registry=prompts_registry,
            reload_interval=s.hot_reload_interval,
        )
        config_reloader.start()
        logger.info(f'Hot-reload started (interval: {s.hot_reload_interval}s)')

    # ── Lifecycle ────────────────────────────────────────────────

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        s = self.settings

        logger.info('')
        logger.info('=' * 70)
        logger.info(f'       SAJHA MCP Server {s.app_version} — Starting')
        logger.info('=' * 70)

        # 1. Database: SQLite runs db/scripts/sqlite/schema.sql; PostgreSQL is only checked
        #    (db.schema_check), never changed. docs/getting-started/Database Setup.md
        from sajha.db.engine import init_db, get_db_session
        from sajha.db.schema import SchemaNotReady
        try:
            init_db(s)
        except SchemaNotReady as e:
            logger.critical('Refusing to start: ' + str(e))
            raise

        # 1b. Process-shared state (state.backend: memory | redis | database); see
        #     docs/architecture/Scaling and State.md.  A shared store that does not answer stops start-up.
        from sajha.core.state import startup_check as _state_startup_check
        _state_startup_check()

        # 1c. API keys: a default key for every account that has none (sajha/auth/apikeys.py)
        try:
            from sajha.auth.apikeys import ensure_default_keys
            _db = get_db_session()
            try:
                _made = ensure_default_keys(_db)
            finally:
                _db.close()
            if _made:
                logger.info(f'  API keys: created a default key for {_made} account(s)')
        except Exception as e:
            logger.warning(f'  API keys: default keys not ensured ({e})')

        # 2. Initialize storage backend (local or S3)
        from sajha.core.storage import init_storage, get_storage
        storage_config = {
            'storage.backend': getattr(s, 'storage_backend', 'local'),
            'storage.base_dir': getattr(s, 'storage_base_dir', '.'),
            'storage.s3.bucket': getattr(s, 'storage_s3_bucket', ''),
            'storage.s3.prefix': getattr(s, 'storage_s3_prefix', ''),
            'storage.s3.region': getattr(s, 'storage_s3_region', 'us-east-1'),
            'storage.s3.cache_dir': getattr(s, 'storage_s3_cache_dir', '/tmp/sajha-cache'),
        }
        init_storage(storage_config)

        # 2a. Policy and audit (docs/architecture/Policy and Audit.md): load config/policies
        #     through the storage backend; open this process's audit hash chain and SIEM sinks.
        try:
            from sajha.policy.engine import get_engine as _policy_engine
            _policy_engine().policy_set.refresh(force=True)
            from sajha.audit import init_audit
            init_audit()
        except Exception as e:
            logger.warning(f'  Policy/audit: {e}', exc_info=True)

        # 3. Core managers (tools, prompts, MCP, hot-reload)
        self._init_managers()

        # 3a. Federation: upstream MCP servers' tools as registry tools (federation.enabled,
        #     off by default). Before composites and the tool-search index so both see them;
        #     waits at most federation.startup_wait_seconds, never fails start-up.
        try:
            import asyncio as _asyncio
            from sajha.federation import init_federation
            await _asyncio.to_thread(init_federation, tools_registry)
        except Exception as e:
            logger.warning(f'  Federation: unavailable ({e})', exc_info=True)

        # 3a'. Data connectors: each connection's governed tools (config/connectors/*.json;
        #      docs/architecture/Data Connectors.md). Opens no database; never fails start-up.
        try:
            from sajha.connectors import init_connectors
            await _asyncio.to_thread(init_connectors, tools_registry)
        except Exception as e:
            logger.warning(f'  Data connectors: unavailable ({e})', exc_info=True)

        # 3b. Composite tools (load from DB, build schemas, register)
        try:
            from sajha.tools.composite_tool import CompositeToolEngine
            from sajha.db.engine import get_db_session
            db = get_db_session()
            try:
                engine = CompositeToolEngine(tools_registry)
                count = engine.load_from_db(db)
                if count:
                    logger.info(f'  Composite Tools: {count} registered')
            finally:
                db.close()
        except Exception as e:
            logger.info(f'  Composite Tools: none loaded ({e})')

        # 3b'. Workflows (scheduler, triggers, run recovery; docs/architecture/Workflows.md)
        try:
            from sajha.workflows import init_workflows
            init_workflows(tools_registry)
        except Exception as e:
            logger.warning(f'  Workflows: unavailable ({e})')

        # 3c. Observability (metrics, OTEL, health probes)
        try:
            from sajha.observability import init_observability
            collector, otel, health = init_observability()
            health.set_ready(True)
            health.register_check("database", lambda: True)
            health.register_check("tools", lambda: len(tools_registry.tools) > 0)
            logger.info(f"  Observability: metrics collector + health probes ready")
        except Exception as e:
            logger.info(f"  Observability: {e}")

        # 3e. Plugin system
        try:
            from sajha.core.plugins import init_plugin_manager
            plugin_mgr = init_plugin_manager(tools_registry)
            plugins_loaded = plugin_mgr.load_all()
            if plugins_loaded:
                logger.info(f"  Plugins: {plugins_loaded} loaded")
        except Exception as e:
            logger.info(f"  Plugins: {e}")

        # 4. LLM factory (sajha.ai.llm) + Semantic Tool Resolver
        try:
            from sajha.ai.llm import init_llm_factory, llm_factory
            from sajha.ai.tool_resolver import init_resolver
            from sajha.db.engine import get_db_session
            from sajha.core.config import _CFG

            ai_config = _CFG  # the factory reads 'ai.*' from the YAML

            db = get_db_session()
            try:
                gw = init_llm_factory(ai_config, db_session=db)
                logger.info(f'  LLM factory: {len(gw.active_provider_names())} providers active')
            finally:
                db.close()

            # Build semantic tool index (non-blocking — logs warning if no embedding provider)
            if gw and gw.active_provider_names():
                logger.info(f'  LLM factory: {len(gw.active_provider_names())} provider(s) ready')
            else:
                logger.info('  LLM Gateway: no providers configured (set API keys in Admin > AI)')
        except ImportError:
            logger.info('  LLM Gateway: AI packages not installed (pip install anthropic openai)')
        except Exception as e:
            logger.warning(f'  LLM Gateway: initialization failed ({e})', exc_info=True)

        # 4b. Semantic Tool Search (independent of the gateway — default is lexical BM25/TF-IDF)
        try:
            from sajha.core.config import cfg_bool
            if cfg_bool(_CFG, 'ai.tool_search.enabled', True):
                from sajha.ai.embedders import get_embedder
                from sajha.ai.tool_resolver import init_resolver, get_resolver
                try:
                    gw_for_extract = llm_factory()
                except Exception:
                    gw_for_extract = None
                embedder = get_embedder(_CFG, gateway=gw_for_extract)
                persist = cfg_bool(_CFG, 'ai.tool_search.persist', True)
                resolver = init_resolver(embedder, tools_registry, gateway=gw_for_extract, persist=persist)
                # The resolver keeps itself accurate as tools change: it listens to every
                # register/unregister (ToolsRegistry.add_change_listener), re-syncing vectors
                # off a background thread so the reload path never blocks.
                import threading as _t
                # BM25 lexical tier (default) — build now, instant and dependency-free.
                lex = resolver.refresh_lexical()
                if embedder is not None:
                    # Optional API-driven vector index builds off the boot path.
                    _t.Thread(target=resolver.build_index, name='tool-index-build', daemon=True).start()
                    logger.info(f'  Semantic Tool Search: {lex} tools (BM25 ready; '
                                f'vector indexing in background via {embedder.name})')
                else:
                    logger.info(f'  Semantic Tool Search: {lex} tools indexed (lexical BM25/TF-IDF)')
        except Exception as e:
            logger.warning(f'  Semantic Tool Search: unavailable ({e})', exc_info=True)

        # 4c. Intelligence service (POST /api/ai/ask) + the optional sajha_ask MCP tool
        try:
            from sajha.ai.llm import llm_factory as _get_gw
            from sajha.ai.intelligence import init_intelligence
            from sajha.ai.ask_tool import register_if_enabled, TOOL_NAME
            if _get_gw() is not None:
                _svc = init_intelligence(_get_gw(), tools_registry)
                # sajha_ask is an LLM tool (config/tools/sajha_ask.json); ai.ask.mcp_tool_enabled turns
                # it on or off, now and after every reload of the catalog
                register_if_enabled(tools_registry, _svc.settings)
                tools_registry.add_reload_listener(lambda: register_if_enabled(tools_registry, _svc.settings))
                logger.info(f'  Intelligence: ask ready (model alias {_svc.settings.model!r}, '
                            f'sajha_ask MCP tool {"on" if _svc.settings.mcp_tool_enabled else "off"})')
            # LLM tools: the spool janitor clears folders left by a crashed process (LLM Tools §10.5)
            from sajha.ai.llm_tools.runtime import get_runtime as _llm_runtime
            _llm_runtime().tick()
        except Exception as e:
            logger.warning(f'  Intelligence: unavailable ({e})', exc_info=True)

        # 4d. Document index behind sajha_search_docs and "Ask the docs" (ai.rag)
        try:
            from sajha.ai.llm import llm_factory as _get_gw2
            from sajha.ai.rag.index import init_doc_index
            _gw2 = _get_gw2()
            _rag = init_doc_index(getattr(getattr(_gw2, 'settings', None), 'rag', None), _gw2)
            logger.info(f'  RAG: {"document index " + ("building in background" if _rag.settings.build_on_start else "builds on first search") + ", store=" + _rag.store.name if _rag else "off (ai.rag.enabled: false)"}')
        except Exception as e:
            logger.warning(f'  RAG: unavailable ({e})', exc_info=True)

        # 4e. Tool quality: scheduled health probes (quality.probes.enabled; docs/architecture/Tool Quality.md)
        try:
            from sajha.quality import probes as _probes
            logger.info(f'  Tool health probes: {"on" if _probes.start(tools_registry) else "off (quality.probes.enabled: false)"}')
        except Exception as e:
            logger.warning(f'  Tool health probes: unavailable ({e})', exc_info=True)

        # 4f. System notices: the watcher over breakers, LLM, federation and workflows (notices.enabled)
        try:
            from sajha.notices import sources as _notice_sources
            logger.info(f'  System notices: {"on" if _notice_sources.start() else "off (notices.enabled: false)"}')
        except Exception as e:
            logger.warning(f'  System notices: unavailable ({e})', exc_info=True)

        # 4f2. Credential files: config/users.json applied, config/apikeys_db.json dumped, standing notices
        try:
            from sajha.auth import credential_jobs
            credential_jobs.start()
            logger.info('  Credential files: users file applied; API keys dump scheduled')
        except Exception as e:
            logger.warning(f'  Credential files: unavailable ({e})', exc_info=True)

        # 4g. Snapshots of users, API keys and tools (snapshots.enabled; docs/architecture/Policy and Audit.md)
        try:
            from sajha.snapshots import start_snapshots
            logger.info(f'  Snapshots: {"on" if start_snapshots(tools_registry) else "off (snapshots.enabled: false)"}')
        except Exception as e:
            logger.warning(f'  Snapshots: unavailable ({e})', exc_info=True)

        # 4h. Conversation memory: the scheduled purge, once per interval across workers
        #     (ai.llm_tools.memory.purge_interval_minutes; docs/architecture/Intelligence Layer.md)
        try:
            from sajha.ai.memory import start_purge
            logger.info(f'  Conversation purge: {"scheduled" if start_purge() else "off (ai.memory.enabled or purge_interval_minutes)"}')
        except Exception as e:
            logger.warning(f'  Conversation purge: unavailable ({e})', exc_info=True)

        # 4i. SAJHA Net: membership of the configured nets, one gossip agent per net across workers
        #     (sajhanet.enabled, off by default; docs/architecture/SAJHA Net.md). Never fails start-up.
        try:
            import asyncio as _asyncio_sn
            from sajha.net.integration import init_sajhanet
            _sn = await _asyncio_sn.to_thread(init_sajhanet)
            logger.info(f'  SAJHA Net: {"nets " + ", ".join(_sn.runtimes) if _sn.shared.enabled else "off (sajhanet.enabled: false)"}')
        except Exception as e:
            logger.warning(f'  SAJHA Net: unavailable ({e})', exc_info=True)

        # 5. Template globals
        self._register_template_globals()

        logger.info('')
        logger.info('=' * 70)
        logger.info(f'  SAJHA MCP Server {s.app_version} READY')
        logger.info(f'  URL: http://{s.server_host}:{s.server_port}')
        logger.info(f'  Config: {s.config_source}')
        logger.info(f'  Tools: {len(tools_registry.tools)}')
        logger.info(f'  Prompts: {len(prompts_registry.prompts)}')
        logger.info(f'  DB: {s.db_type} → {s.db_path if s.db_type == "sqlite" else s.db_host}')
        try:
            from sajha.ai.llm import llm_factory
            gw = llm_factory()
            if gw:
                logger.info(f'  LLM factory: {len(gw.active_provider_names())} providers, default={gw.config.default_provider}/{gw.config.default_model}')
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            pass
        logger.info(f'  WebSocket: ws://{s.server_host}:{s.server_port}/mcp/ws')
        logger.info('=' * 70)

        yield  # App is running

        # Shutdown
        logger.info('Shutting down SAJHA MCP Server...')
        try:
            from sajha.ai.memory import shutdown_purge
            shutdown_purge()
        except Exception as e:
            logger.debug(f'conversation purge shutdown: {e}')
        try:   # SAJHA Net: leave every net (the gossip agent's holder), release the leases
            from sajha.net.integration import shutdown_sajhanet
            shutdown_sajhanet()
        except Exception as e:
            logger.debug(f'SAJHA Net shutdown: {e}')
        try:
            from sajha.auth import credential_jobs
            credential_jobs.stop()
        except Exception as e:
            logger.debug(f'credential files shutdown: {e}')
        try:
            from sajha.snapshots import shutdown_snapshots
            shutdown_snapshots()
        except Exception as e:
            logger.debug(f'snapshots shutdown: {e}')
        try:
            from sajha.workflows import shutdown_workflows
            shutdown_workflows()
        except Exception as e:
            logger.debug(f'workflows shutdown: {e}')
        try:   # close this process's audit chain (chain.close + a signed anchor) and drain SIEM sinks
            from sajha.audit import shutdown_audit
            shutdown_audit()
        except Exception as e:
            logger.debug(f'audit shutdown: {e}')
        try:
            from sajha.quality import probes as _probes
            _probes.stop()
        except Exception as e:
            logger.debug(f'probes shutdown: {e}')
        try:
            from sajha.notices import sources as _notice_sources
            _notice_sources.stop()
        except Exception as e:
            logger.debug(f'notices shutdown: {e}')
        try:   # flush the usage ledger, stop alerts, the metrics publisher/listener and OTel
            from sajha.observability import shutdown_observability
            shutdown_observability()
        except Exception as e:
            logger.debug(f'observability shutdown: {e}')
        try:   # close upstream MCP connections (sajha/federation)
            from sajha.federation import shutdown_federation
            shutdown_federation()
        except Exception as e:
            logger.debug(f'federation shutdown: {e}')
        try:   # close pooled data-connector connections (sajha/connectors)
            from sajha.connectors import shutdown_connectors
            shutdown_connectors()
        except Exception as e:
            logger.debug(f'connectors shutdown: {e}')
        try:   # end MCP subscriptions/listen streams (and legacy push forwarders)
            from sajha.core.change_bus import get_change_bus
            get_change_bus().shutdown()
        except Exception as e:
            logger.debug(f'change bus shutdown: {e}')
        try:   # stop the state store's heartbeat and pub/sub threads
            from sajha.core.state import shutdown as _state_shutdown
            _state_shutdown()
        except Exception as e:
            logger.debug(f'state shutdown: {e}')
        if config_reloader:
            config_reloader.stop()
        if tools_registry:
            tools_registry.stop_monitoring()
        if prompts_registry:
            prompts_registry.stop_auto_refresh()
        logger.info('Shutdown complete')


# ── Convenience factory (for uvicorn CLI: uvicorn sajha.app:create_app) ──

def create_app() -> FastAPI:
    """Create the app via SajhaMCPServerWebApp. Used by uvicorn --factory."""
    webapp = SajhaMCPServerWebApp()
    return webapp.app
