"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Flask application for SAJHA MCP Server - Backward Compatibility Wrapper

This module provides backward compatibility for code that imports from app.py.
The actual implementation is now in sajhamcpserver_web.py.
"""

import logging

# Get logger (logging is configured by run_server.py)
logger = logging.getLogger(__name__)

# Global instances for backward compatibility
app = None
socketio = None
auth_manager = None
mcp_handler = None
tools_registry = None
config_reloader = None

# Reference to the web app instance
_web_app_instance = None


def create_app():
    """
    Create and configure Flask application.
    
    This is the main factory function that creates a fully configured
    SAJHA MCP Server application.
    
    Returns:
        Tuple of (Flask app, SocketIO instance)
    """
    global app, socketio, auth_manager, mcp_handler, tools_registry, config_reloader, _web_app_instance
    
    # Import here to avoid circular imports
    from web.sajhamcpserver_web import SajhaMCPServerWebApp
    
    # Create the web app
    _web_app_instance = SajhaMCPServerWebApp()
    _web_app_instance.prepare()
    
    # Set global references for backward compatibility
    app = _web_app_instance.get_app()
    socketio = _web_app_instance.get_socketio()
    auth_manager = _web_app_instance.auth_manager
    mcp_handler = _web_app_instance.mcp_handler
    tools_registry = _web_app_instance.tools_registry
    config_reloader = _web_app_instance.config_reloader
    
    return app, socketio


# Legacy function aliases for backward compatibility
def register_all_routes(app, socketio, prompts_registry=None):
    """Legacy function - routes are now registered in SajhaMCPServerWebApp.prepare()"""
    logger.warning("register_all_routes() is deprecated. Routes are auto-registered in prepare().")
    pass


def register_error_handlers(app):
    """Legacy function - error handlers are now registered in SajhaMCPServerWebApp.prepare()"""
    logger.warning("register_error_handlers() is deprecated. Handlers are auto-registered in prepare().")
    pass


def register_health_check(app):
    """Legacy function - health check is now registered in SajhaMCPServerWebApp.prepare()"""
    logger.warning("register_health_check() is deprecated. Endpoints are auto-registered in prepare().")
    pass


if __name__ == '__main__':
    from web.sajhamcpserver_web import SajhaMCPServerWebApp
    
    web_app = SajhaMCPServerWebApp()
    web_app.prepare()
    web_app.run(host='0.0.0.0', port=5000, debug=True)
