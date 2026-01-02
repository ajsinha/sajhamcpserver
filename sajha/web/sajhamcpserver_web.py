"""
SAJHA MCP Server Web Application - Main Flask Application Class v2.1.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Legal Notice:
This document and the associated software architecture are proprietary and confidential.
Unauthorized copying, distribution, modification, or use of this document or the software
system it describes is strictly prohibited without explicit written permission from the
copyright holder. This document is provided "as is" without warranty of any kind, either
expressed or implied. The copyright holder shall not be liable for any damages arising
from the use of this document or the software system it describes.
"""

import os
import logging
from typing import Optional
from datetime import timedelta, datetime

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO
from flask_cors import CORS

# Import core modules
from sajha.core.auth_manager import AuthManager
from sajha.core.mcp_handler import MCPHandler
from sajha.core.prompts_registry import PromptsRegistry, get_prompts_registry
from sajha.core.hot_reload_manager import get_config_reloader
from sajha.core.properties_configurator import PropertiesConfigurator
from sajha.tools.tools_registry import ToolsRegistry, get_tools_registry

# Import route modules
from sajha.web.routes import (
    AuthRoutes,
    DashboardRoutes,
    ToolsRoutes,
    AdminRoutes,
    MonitoringRoutes,
    ApiRoutes,
    SocketIOHandlers,
    PromptsRoutes,
    HelpRoutes,
    DocsRoutes,
    APIKeysRoutes
)

# Get logger (logging is configured by run_server.py)
logger = logging.getLogger(__name__)


class SajhaMCPServerWebApp:
    """
    Main Flask application class for SAJHA MCP Server.
    
    This class encapsulates the Flask application and manages route registration,
    core managers (auth, tools, prompts), and the hot-reload system.
    
    Attributes:
        app: Flask application instance
        socketio: SocketIO instance for WebSocket support
        auth_manager: AuthManager instance for authentication
        tools_registry: ToolsRegistry instance for tool management
        prompts_registry: PromptsRegistry instance for prompt management
        mcp_handler: MCPHandler instance for MCP protocol handling
        config_reloader: ConfigReloader instance for hot-reload functionality
        prop_conf: PropertiesConfigurator instance for configuration
    """
    
    VERSION = '2.1.0'
    
    def __init__(self, secret_key: Optional[str] = None, config_path: Optional[str] = None):
        """
        Initialize the SAJHA MCP Server Web Application.
        
        Args:
            secret_key: Secret key for session management (generated if not provided)
            config_path: Path to server.properties file (optional)
        """
        # Get web module directory for template and static paths
        web_dir = os.path.dirname(os.path.abspath(__file__))
        
        self.app = Flask(
            __name__,
            template_folder=os.path.join(web_dir, 'templates'),
            static_folder=os.path.join(web_dir, 'static')
        )
        
        # Get properties configurator (singleton)
        self.prop_conf = PropertiesConfigurator(config_path) if config_path else PropertiesConfigurator()
        
        # Initialize managers (will be set up in prepare())
        self.auth_manager: Optional[AuthManager] = None
        self.tools_registry: Optional[ToolsRegistry] = None
        self.prompts_registry: Optional[PromptsRegistry] = None
        self.mcp_handler: Optional[MCPHandler] = None
        self.config_reloader = None
        self.socketio: Optional[SocketIO] = None
        
        # Configure application
        self._configure_app(secret_key)
        
        # Register template context processors
        self._register_context_processors()
        
        # Register template filters
        self._register_template_filters()
        
        logger.info("SAJHA MCP Server Web Application initialized")
    
    def _configure_app(self, secret_key: Optional[str] = None):
        """Configure Flask application settings."""
        # Secret key
        self.app.config['SECRET_KEY'] = secret_key or self.prop_conf.get(
            'app.secret.key',
            os.urandom(24).hex()
        )
        
        # Session configuration
        self.app.config['SESSION_TYPE'] = 'filesystem'
        self.app.config['SESSION_PERMANENT'] = False
        self.app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(
            seconds=self.prop_conf.get_int('session.lifetime.seconds', 3600)
        )
        
        # Application metadata
        self.app.config['APP_NAME'] = self.prop_conf.get('app.name', 'SAJHA MCP Server')
        self.app.config['APP_VERSION'] = self.prop_conf.get('server.version', self.VERSION)
        
        # Session directory
        session_dir = self.prop_conf.get('flask.session.dir', './data/flask_session')
        os.makedirs(session_dir, exist_ok=True)
        self.app.config['SESSION_FILE_DIR'] = session_dir
        
        logger.info(f"Application configured: {self.app.config['APP_NAME']} v{self.app.config['APP_VERSION']}")
    
    def _register_context_processors(self):
        """Register template context processors for global variables."""
        
        @self.app.context_processor
        def inject_globals():
            """Inject global variables into all templates."""
            return {
                'app_name': self.app.config.get('APP_NAME', 'SAJHA MCP Server'),
                'app_version': self.app.config.get('APP_VERSION', self.VERSION),
                'current_year': datetime.now().year,
                'prop_conf': self.prop_conf
            }
    
    def _register_template_filters(self):
        """Register custom Jinja2 template filters."""
        
        @self.app.template_filter('datetime')
        def format_datetime(value, format_str='%Y-%m-%d %H:%M:%S'):
            """Format datetime object."""
            if value is None:
                return ''
            if isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value)
                except:
                    return value
            return value.strftime(format_str)
        
        @self.app.template_filter('dt')
        def dt_filter(value, length=16):
            """
            Short filter to format datetime - handles strings and datetime objects.
            Usage: {{ task.created_at|dt }} or {{ task.created_at|dt(10) }}
            """
            if value is None:
                return '-'
            
            if isinstance(value, datetime):
                if length <= 10:
                    return value.strftime('%Y-%m-%d')
                elif length <= 16:
                    return value.strftime('%Y-%m-%d %H:%M')
                else:
                    return value.strftime('%Y-%m-%d %H:%M:%S')
            
            if isinstance(value, str):
                return value[:length] if len(value) >= length else value
            
            return str(value)
        
        @self.app.template_filter('truncate_text')
        def truncate_text(text, length=100, suffix='...'):
            """Truncate text to specified length."""
            if not text:
                return ''
            if len(text) <= length:
                return text
            return text[:length - len(suffix)] + suffix
        
        @self.app.template_filter('json_pretty')
        def json_pretty(value):
            """Pretty print JSON."""
            import json
            try:
                if isinstance(value, str):
                    value = json.loads(value)
                return json.dumps(value, indent=2, default=str)
            except:
                return str(value)
    
    def prepare(self):
        """
        Prepare the application by initializing all managers and registering routes.
        Call this after __init__ and before run().
        """
        logger.info("Preparing SAJHA MCP Server...")
        
        # Enable CORS
        CORS(self.app)
        
        # Initialize SocketIO
        self.socketio = SocketIO(
            self.app, 
            cors_allowed_origins="*", 
            async_mode='threading'
        )
        
        # Initialize core managers
        self._initialize_managers()
        
        # Initialize hot-reload system
        self._initialize_hot_reload()
        
        # Register routes
        self._register_routes()
        
        # Register error handlers
        self._register_error_handlers()
        
        # Register health check endpoints
        self._register_health_check()
        
        logger.info("SAJHA MCP Server prepared successfully")
    
    def _initialize_managers(self):
        """Initialize all core managers with paths from properties."""
        logger.info("Initializing core managers...")
        
        # Get config paths from properties (with defaults)
        users_path = self.prop_conf.get('config.users.path', 'config/users.json')
        apikeys_path = self.prop_conf.get('config.apikeys.path', 'config/apikeys.json')
        tools_dir = self.prop_conf.get('config.tools.dir', 'config/tools')
        prompts_dir = self.prop_conf.get('config.prompts.dir', 'config/prompts')
        
        logger.info(f"Config paths from properties:")
        logger.info(f"  users: {users_path}")
        logger.info(f"  apikeys: {apikeys_path}")
        logger.info(f"  tools: {tools_dir}")
        logger.info(f"  prompts: {prompts_dir}")
        logger.info(f"  cwd: {os.getcwd()}")
        
        # Auth Manager (includes API Key Manager) - force reinit to ensure correct paths
        self.auth_manager = AuthManager(
            users_config_path=users_path,
            apikeys_config_path=apikeys_path
        )
        logger.info(f"Auth manager initialized (users: {self.auth_manager.users_config_path})")
        
        # Tools Registry - use factory function with force_reinit
        self.tools_registry = get_tools_registry(tools_config_dir=tools_dir, force_reinit=True)
        logger.info(f"Tools registry initialized with {len(self.tools_registry.tools)} tools from {self.tools_registry.tools_config_dir}")
        
        # Prompts Registry - use factory function with force_reinit
        self.prompts_registry = get_prompts_registry(prompts_config_dir=prompts_dir, force_reinit=True)
        logger.info(f"Prompts registry initialized with {len(self.prompts_registry.prompts)} prompts from {self.prompts_registry.prompts_config_dir}")
        
        # MCP Handler
        self.mcp_handler = MCPHandler(
            tools_registry=self.tools_registry,
            auth_manager=self.auth_manager,
            prompts_registry=self.prompts_registry
        )
        logger.info("MCP handler initialized")
    
    def _initialize_hot_reload(self):
        """Initialize the hot-reload system."""
        reload_interval = self.prop_conf.get_int('hot_reload.interval.seconds', 300)
        
        self.config_reloader = get_config_reloader(
            auth_manager=self.auth_manager,
            apikey_manager=self.auth_manager.apikey_manager,
            tools_registry=self.tools_registry,
            prompts_registry=self.prompts_registry,
            reload_interval=reload_interval
        )
        self.config_reloader.start()
        
        logger.info(f"Hot-reload manager started (interval: {reload_interval} seconds)")
    
    def _register_routes(self):
        """Register all route modules."""
        logger.info("Registering routes...")
        
        # Initialize route classes
        route_classes = [
            (AuthRoutes, [self.auth_manager]),
            (DashboardRoutes, [self.auth_manager, self.tools_registry, self.prompts_registry]),
            (ToolsRoutes, [self.auth_manager, self.tools_registry]),
            (AdminRoutes, [self.auth_manager, self.tools_registry]),
            (MonitoringRoutes, [self.auth_manager, self.tools_registry]),
            (ApiRoutes, [self.auth_manager, self.tools_registry, self.mcp_handler]),
            (PromptsRoutes, [self.auth_manager, self.prompts_registry]),
            (HelpRoutes, [self.auth_manager]),
            (DocsRoutes, [self.auth_manager]),
            (APIKeysRoutes, [self.auth_manager, self.tools_registry]),
        ]
        
        for route_class, args in route_classes:
            logger.debug(f"Registering routes: {route_class.__name__}")
            route_handler = route_class(*args)
            route_handler.register_routes(self.app)
        
        # Register SocketIO handlers
        socketio_handlers = SocketIOHandlers(
            self.socketio,
            self.auth_manager,
            self.tools_registry,
            self.mcp_handler
        )
        socketio_handlers.register_handlers()
        
        logger.info("All routes registered successfully")
    
    def _register_error_handlers(self):
        """Register error handlers for the application."""
        
        @self.app.errorhandler(404)
        def not_found(error):
            """Handle 404 errors."""
            return render_template('common/error.html',
                                 error="Page Not Found",
                                 message="The requested page does not exist"), 404
        
        @self.app.errorhandler(403)
        def forbidden(error):
            """Handle 403 errors."""
            return render_template('common/error.html',
                                 error="Access Forbidden",
                                 message="You don't have permission to access this resource"), 403
        
        @self.app.errorhandler(500)
        def internal_error(error):
            """Handle 500 errors."""
            logger.error(f"Internal server error: {error}")
            return render_template('common/error.html',
                                 error="Internal Server Error",
                                 message="An unexpected error occurred"), 500
        
        logger.info("Error handlers registered")
    
    def _register_health_check(self):
        """Register health check and hot-reload status endpoints."""
        
        @self.app.route('/health')
        def health():
            """Health check endpoint."""
            hot_reload_status = None
            if self.config_reloader:
                hot_reload_status = self.config_reloader.get_status()
            
            return jsonify({
                'status': 'healthy',
                'timestamp': datetime.now().isoformat(),
                'version': self.VERSION,
                'app_name': self.app.config.get('APP_NAME'),
                'tools_count': len(self.tools_registry.tools) if self.tools_registry else 0,
                'prompts_count': len(self.prompts_registry.prompts) if self.prompts_registry else 0,
                'hot_reload': hot_reload_status
            })
        
        @self.app.route('/api/admin/hot-reload/status')
        def hot_reload_status():
            """Get hot-reload status."""
            if self.config_reloader:
                return jsonify({
                    'success': True,
                    'status': self.config_reloader.get_status()
                })
            return jsonify({
                'success': False,
                'error': 'Hot-reload manager not initialized'
            }), 500
        
        @self.app.route('/api/admin/hot-reload/force', methods=['POST'])
        def force_hot_reload():
            """Force immediate reload of all configurations."""
            if self.config_reloader:
                self.config_reloader.force_reload()
                return jsonify({
                    'success': True,
                    'message': 'Force reload triggered',
                    'status': self.config_reloader.get_status()
                })
            return jsonify({
                'success': False,
                'error': 'Hot-reload manager not initialized'
            }), 500
        
        logger.info("Health check endpoints registered")
    
    def run(self, host: str = None, port: int = None, debug: bool = None):
        """
        Run the Flask application with SocketIO support.
        
        Args:
            host: Host address to bind to (defaults to config or 0.0.0.0)
            port: Port number to listen on (defaults to config or 5000)
            debug: Enable debug mode (defaults to config or False)
        """
        # Get values from config if not provided
        if host is None:
            host = self.prop_conf.get('server.host', '0.0.0.0')
        if port is None:
            port = self.prop_conf.get_int('server.port', 5000)
        if debug is None:
            debug = self.prop_conf.get_bool('app.debug', False)
        
        logger.info(f"Starting SAJHA MCP Server on {host}:{port} (debug={debug})")
        
        if self.socketio:
            self.socketio.run(self.app, host=host, port=port, debug=debug)
        else:
            self.app.run(host=host, port=port, debug=debug)
    
    def get_app(self):
        """
        Get the Flask application instance.
        
        Returns:
            Flask application instance
        """
        return self.app
    
    def get_socketio(self):
        """
        Get the SocketIO instance.
        
        Returns:
            SocketIO instance
        """
        return self.socketio
    
    def shutdown(self):
        """
        Gracefully shutdown the application.
        Stops the hot-reload manager and other background tasks.
        """
        logger.info("Shutting down SAJHA MCP Server...")
        
        if self.config_reloader:
            self.config_reloader.stop()
            logger.info("Hot-reload manager stopped")
        
        if self.tools_registry:
            self.tools_registry.stop_monitoring()
            logger.info("Tools monitoring stopped")
        
        if self.prompts_registry:
            self.prompts_registry.stop_auto_refresh()
            logger.info("Prompts auto-refresh stopped")
        
        logger.info("SAJHA MCP Server shutdown complete")


def create_app(secret_key: str = None, config_path: str = None) -> tuple:
    """
    Factory function to create and configure the SAJHA MCP Server application.
    
    This is a convenience function for creating a fully configured application.
    
    Args:
        secret_key: Secret key for session management
        config_path: Path to server.properties file
        
    Returns:
        Tuple of (Flask app, SocketIO instance)
    """
    web_app = SajhaMCPServerWebApp(secret_key=secret_key, config_path=config_path)
    web_app.prepare()
    return web_app.get_app(), web_app.get_socketio()


# For backward compatibility and direct execution
if __name__ == '__main__':
    web_app = SajhaMCPServerWebApp()
    web_app.prepare()
    web_app.run(debug=True)
