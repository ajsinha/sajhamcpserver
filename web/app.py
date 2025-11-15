"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Flask application for SAJHA MCP Server - Refactored with modular routes
"""

import logging
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO
from flask_cors import CORS
from datetime import timedelta, datetime

# Import core modules
from core.auth_manager import AuthManager
from core.mcp_handler import MCPHandler
from core.prompts_registry import PromptsRegistry
from tools.tools_registry import ToolsRegistry

# Import route modules
from routes import (
    AuthRoutes,
    DashboardRoutes,
    ToolsRoutes,
    AdminRoutes,
    MonitoringRoutes,
    ApiRoutes,
    SocketIOHandlers,
    PromptsRoutes
)

# Global instances
app = None
socketio = None
auth_manager = None
mcp_handler = None
tools_registry = None


def create_app():
    """Create and configure Flask application"""
    global app, socketio, auth_manager, mcp_handler, tools_registry
    
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'sajha-mcp-server-secret-key-2025'
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
    
    # Enable CORS
    CORS(app)
    
    # Initialize SocketIO
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
    
    # Initialize managers
    auth_manager = AuthManager()
    tools_registry = ToolsRegistry()
    prompts_registry = PromptsRegistry()
    mcp_handler = MCPHandler(tools_registry=tools_registry, auth_manager=auth_manager, prompts_registry=prompts_registry)
    
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Register routes
    register_all_routes(app, socketio)
    
    # Register error handlers
    register_error_handlers(app)
    
    # Register health check
    register_health_check(app)
    
    return app, socketio


def register_all_routes(app, socketio):
    """Register all route modules"""
    from core.prompts_registry import PromptsRegistry
    prompts_registry = PromptsRegistry()

    # Initialize route classes
    auth_routes = AuthRoutes(auth_manager)
    dashboard_routes = DashboardRoutes(auth_manager, tools_registry, prompts_registry)
    tools_routes = ToolsRoutes(auth_manager, tools_registry)
    admin_routes = AdminRoutes(auth_manager, tools_registry)
    monitoring_routes = MonitoringRoutes(auth_manager, tools_registry)
    api_routes = ApiRoutes(auth_manager, tools_registry, mcp_handler)
    prompt_routes = PromptsRoutes(auth_manager, prompts_registry)

    socketio_handlers = SocketIOHandlers(socketio, auth_manager, tools_registry, mcp_handler)
    
    # Register blueprints
    auth_routes.register_routes(app)
    dashboard_routes.register_routes(app)
    tools_routes.register_routes(app)
    admin_routes.register_routes(app)
    monitoring_routes.register_routes(app)
    api_routes.register_routes(app)
    prompt_routes.register_routes(app)
    
    # Register SocketIO handlers
    socketio_handlers.register_handlers()
    
    logging.info("All routes registered successfully")


def register_error_handlers(app):
    """Register error handlers"""
    
    @app.errorhandler(404)
    def not_found(error):
        """404 error handler"""
        return render_template('error.html',
                             error="Page Not Found",
                             message="The requested page does not exist"), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        """500 error handler"""
        return render_template('error.html',
                             error="Internal Server Error",
                             message="An unexpected error occurred"), 500


def register_health_check(app):
    """Register health check endpoint"""
    
    @app.route('/health')
    def health():
        """Health check endpoint"""
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'version': '1.0.0'
        })


if __name__ == '__main__':
    app, socketio = create_app()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
