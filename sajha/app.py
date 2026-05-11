"""
SAJHA MCP Server v3 — Application
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

VERSION = '4.0.0'

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
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)


def render_standalone(request: Request, template_name: str, context: dict = None, status_code: int = 200):
    """Render a standalone template (not extending base.html). Used for landing page."""
    ctx = context or {}
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)


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
        app.add_middleware(
            CORSMiddleware,
            allow_origins=['*'],
            allow_credentials=True,
            allow_methods=['*'],
            allow_headers=['*'],
        )

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
        from sajha.routes.misc_routes import router as misc_router
        from sajha.routes.a2a_routes import router as a2a_router
        from sajha.routes.ai_routes import router as ai_router
        from sajha.routes.composite_routes import router as composite_router
        from sajha.routes.ws_routes import router as ws_router
        from sajha.routes.ops_routes import router as ops_router

        routers = [
            auth_router, dashboard_router, api_router, tools_router,
            admin_router, reporting_router, mcp_router, health_router,
            prompts_router, studio_router, apikeys_router, misc_router,
            a2a_router,
            ai_router,
            composite_router,
            ws_router,
            ops_router,
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

        @app.exception_handler(403)
        async def forbidden(request: Request, exc):
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
            'help_page': '/help',
            'about_page': '/about',
            'ai_settings': '/ai/settings',
            'composite_builder': '/composite/builder',
            'docs_list': '/docs',
            'docs_view': '/docs/view/{doc_path}',
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

        def url_for(endpoint, **kwargs):
            if endpoint == 'static':
                return f'/static/{kwargs.get("filename", "")}'
            url = _URL_MAP.get(endpoint, f'/{endpoint}')
            for key, value in kwargs.items():
                url = url.replace(f'{{{key}}}', str(value))
            return url

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
            except Exception:
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
            from sajha.core.config import _CFG
            pc = PropertiesConfigurator()  # Singleton, no files
            with pc._properties_lock:
                pc._properties.update(_CFG)  # Inject flattened YAML values
            logger.info(f'PropertiesConfigurator loaded with {len(_CFG)} values from YAML config')
        except Exception as e:
            logger.warning(f'PropertiesConfigurator init failed: {e}')

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

        mcp_handler = MCPHandler(
            tools_registry=tools_registry,
            auth_manager=None,
            prompts_registry=prompts_registry,
        )
        logger.info('MCP handler initialized')

        config_reloader = get_config_reloader(
            auth_manager=None,
            apikey_manager=None,
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
        logger.info('       SAJHA MCP Server v3 — Starting')
        logger.info('=' * 70)

        # 1. Database (SQL scripts: schema + seed)
        from sajha.db.engine import init_db, get_db_session
        init_db(s)

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

        # 3. Core managers (tools, prompts, MCP, hot-reload)
        self._init_managers()

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

        # 3d. Multi-tenancy
        try:
            from sajha.core.tenancy import init_tenant_manager
            tenant_mgr = init_tenant_manager()
            logger.info(f"  Tenancy: {len(tenant_mgr.list_tenants())} tenants")
        except Exception as e:
            logger.info(f"  Tenancy: {e}")

        # 3e. Plugin system
        try:
            from sajha.core.plugins import init_plugin_manager
            plugin_mgr = init_plugin_manager(tools_registry)
            plugins_loaded = plugin_mgr.load_all()
            if plugins_loaded:
                logger.info(f"  Plugins: {plugins_loaded} loaded")
        except Exception as e:
            logger.info(f"  Plugins: {e}")

        # 4. LLM Gateway + Semantic Tool Resolver
        try:
            from sajha.ai.gateway import init_gateway, get_gateway
            from sajha.ai.tool_resolver import init_resolver
            from sajha.db.engine import get_db_session

            ai_config = {k: getattr(s, k.replace('.', '_'), '')
                         for k in ['ai.default_provider', 'ai.default_model',
                                   'ai.embedding_provider', 'ai.embedding_model',
                                   'ai.cache.enabled', 'ai.cache.ttl_seconds']}

            db = get_db_session()
            try:
                gw = init_gateway(ai_config, db_session=db)
                logger.info(f'  LLM Gateway: {len(gw._providers)} providers registered')
            finally:
                db.close()

            # Build semantic tool index (non-blocking — logs warning if no embedding provider)
            if gw and gw._providers:
                try:
                    resolver = init_resolver(gw, tools_registry)
                    count = resolver.build_index()
                    if count:
                        logger.info(f'  Tool Resolver: {count} tools indexed for semantic search')
                    else:
                        logger.info('  Tool Resolver: initialized (index will build when embedding provider is configured)')
                except Exception as e:
                    logger.warning(f'  Tool Resolver: skipped ({e})')
            else:
                logger.info('  LLM Gateway: no providers configured (set API keys in Admin > AI)')
        except ImportError:
            logger.info('  LLM Gateway: AI packages not installed (pip install anthropic openai)')
        except Exception as e:
            logger.warning(f'  LLM Gateway: initialization failed ({e})')

        # 5. Template globals
        self._register_template_globals()

        logger.info('')
        logger.info('=' * 70)
        logger.info(f'  SAJHA MCP Server v3 READY')
        logger.info(f'  URL: http://{s.server_host}:{s.server_port}')
        logger.info(f'  Config: {s.config_source}')
        logger.info(f'  Tools: {len(tools_registry.tools)}')
        logger.info(f'  Prompts: {len(prompts_registry.prompts)}')
        logger.info(f'  DB: {s.db_type} → {s.db_path if s.db_type == "sqlite" else s.db_host}')
        try:
            from sajha.ai.gateway import get_gateway
            gw = get_gateway()
            if gw:
                logger.info(f'  AI Gateway: {len(gw._providers)} providers, default={gw.config.default_provider}/{gw.config.default_model}')
        except:
            pass
        logger.info(f'  WebSocket: ws://{s.server_host}:{s.server_port}/mcp/ws')
        logger.info('=' * 70)

        yield  # App is running

        # Shutdown
        logger.info('Shutting down SAJHA MCP Server v3...')
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
