"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
SocketIO Handlers for SAJHA MCP Server
"""

import logging
from flask import request
from flask_socketio import emit, disconnect


class SocketIOHandlers:
    """WebSocket event handlers"""
    
    def __init__(self, socketio, auth_manager, tools_registry, mcp_handler):
        """
        Initialize SocketIO handlers
        
        Args:
            socketio: SocketIO instance
            auth_manager: Authentication manager instance
            tools_registry: Tools registry instance
            mcp_handler: MCP handler instance
        """
        self.socketio = socketio
        self.auth_manager = auth_manager
        self.tools_registry = tools_registry
        self.mcp_handler = mcp_handler
    
    def register_handlers(self):
        """Register all SocketIO event handlers"""
        
        @self.socketio.on('connect')
        def handle_connect():
            """Handle WebSocket connection"""
            logging.info(f"WebSocket client connected: {request.sid}")
            emit('connected', {'message': 'Connected to SAJHA MCP Server'})
        
        @self.socketio.on('disconnect')
        def handle_disconnect():
            """Handle WebSocket disconnection"""
            logging.info(f"WebSocket client disconnected: {request.sid}")
        
        @self.socketio.on('authenticate')
        def handle_authenticate(data):
            """Handle WebSocket authentication"""
            token = data.get('token')
            if token:
                session_data = self.auth_manager.validate_session(token)
                if session_data:
                    emit('authenticated', {
                        'success': True,
                        'user': session_data['user_name']
                    })
                    return
            
            emit('authenticated', {'success': False, 'error': 'Invalid token'})
            disconnect()
        
        @self.socketio.on('mcp_request')
        def handle_mcp_request(data):
            """Handle MCP request over WebSocket"""
            # Validate session
            token = data.get('token')
            session_data = None
            if token:
                session_data = self.auth_manager.validate_session(token)
            
            # Get request
            request_data = data.get('request')
            if not request_data:
                emit('mcp_response', {
                    'error': 'Invalid request'
                })
                return
            
            # Handle request
            response = self.mcp_handler.handle_request(request_data, session_data)
            emit('mcp_response', response)
        
        @self.socketio.on('tool_execute')
        def handle_tool_execute(data):
            """Handle tool execution over WebSocket"""
            # Validate session
            token = data.get('token')
            if not token:
                emit('tool_result', {'error': 'Unauthorized'})
                return
            
            session_data = self.auth_manager.validate_session(token)
            if not session_data:
                emit('tool_result', {'error': 'Invalid token'})
                return
            
            # Get tool and arguments
            tool_name = data.get('tool')
            arguments = data.get('arguments', {})
            
            # Check access
            if not self.auth_manager.has_tool_access(session_data, tool_name):
                emit('tool_result', {'error': 'Access denied'})
                return
            
            # Execute tool
            try:
                tool = self.tools_registry.get_tool(tool_name)
                if not tool:
                    emit('tool_result', {'error': 'Tool not found'})
                    return
                
                result = tool.execute_with_tracking(arguments)
                emit('tool_result', {
                    'success': True,
                    'result': result
                })
            except Exception as e:
                emit('tool_result', {
                    'success': False,
                    'error': str(e)
                })