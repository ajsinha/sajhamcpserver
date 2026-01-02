"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Base Routes Class for SAJHA MCP Server
"""

from functools import wraps
from flask import request, redirect, url_for, session, render_template


class BaseRoutes:
    """Base class for all route classes with common decorators and utilities"""
    
    def __init__(self, auth_manager, tools_registry=None, mcp_handler=None):
        """
        Initialize base routes
        
        Args:
            auth_manager: Authentication manager instance
            tools_registry: Tools registry instance (optional)
            mcp_handler: MCP handler instance (optional)
        """
        self.auth_manager = auth_manager
        self.tools_registry = tools_registry
        self.mcp_handler = mcp_handler
    
    def login_required(self, f):
        """Decorator to require login for routes"""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'token' not in session:
                return redirect(url_for('login', next=request.url))

            # Validate session
            session_data = self.auth_manager.validate_session(session['token'])
            if not session_data:
                session.pop('token', None)
                return redirect(url_for('login', next=request.url))

            # Store session data in request for use in view
            request.user_session = session_data
            return f(*args, **kwargs)
        return decorated_function

    def admin_required(self, f):
        """Decorator to require admin privileges"""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'token' not in session:
                return redirect(url_for('login'))

            session_data = self.auth_manager.validate_session(session['token'])
            if not session_data or not self.auth_manager.is_admin(session_data):
                return render_template('common/error.html',
                                     error="Access Denied",
                                     message="Admin privileges required"), 403

            request.user_session = session_data
            return f(*args, **kwargs)
        return decorated_function

    def register_routes(self, app):
        """
        Register routes to Flask app
        Must be implemented by subclasses

        Args:
            app: Flask app instance
        """
        raise NotImplementedError("Subclasses must implement register_routes()")

    def get_user_session(self):
        """Get current user session from request"""
        return getattr(request, 'user_session', None)