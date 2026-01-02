"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Authentication Routes for SAJHA MCP Server
"""

from flask import render_template, request, redirect, url_for, session
from datetime import timedelta
from routes.base_routes import BaseRoutes


class AuthRoutes(BaseRoutes):
    """Authentication-related routes"""

    def __init__(self, auth_manager):
        """Initialize authentication routes"""
        super().__init__(auth_manager)

    def register_routes(self, app):
        """Register authentication routes"""

        @app.route('/login', methods=['GET', 'POST'])
        def login():
            """Login page"""
            if request.method == 'POST':
                user_id = request.form.get('user_id')
                password = request.form.get('password')

                # Authenticate user
                token = self.auth_manager.authenticate(user_id, password)
                if token:
                    session['token'] = token
                    session.permanent = True

                    # Redirect to next page or dashboard
                    next_page = request.args.get('next', url_for('dashboard'))
                    return redirect(next_page)
                else:
                    return render_template('auth/login.html', error="Invalid credentials")

            return render_template('auth/login.html')

        @app.route('/logout')
        def logout():
            """Logout"""
            token = session.get('token')
            if token:
                self.auth_manager.logout(token)
            session.pop('token', None)
            return redirect(url_for('login'))