"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
MCP Protocol Handler - JSON-RPC 2.0 Implementation
"""

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

class MCPHandler:
    """
    Handles MCP protocol messages (JSON-RPC 2.0)
    """
    
    # Standard JSON-RPC 2.0 error codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    
    # Custom error codes
    UNAUTHORIZED = -32001
    FORBIDDEN = -32002
    
    def __init__(self, tools_registry=None, auth_manager=None, prompts_registry=None):
        """
        Initialize the MCP handler
        
        Args:
            tools_registry: Tools registry instance
            auth_manager: Authentication manager instance
        """
        self.tools_registry = tools_registry
        self.auth_manager = auth_manager
        self.logger = logging.getLogger(__name__)
        self.prompts_registry = prompts_registry
        self.server_info = {
            "protocolVersion": "1.0",
            "serverName": "SAJHA MCP Server",
            "serverVersion": "1.0.0",
            "capabilities": {
                "tools": {
                    "listChanged": True
                },
                "prompts": {},
                "resources": {}
            }
        }
    
    def handle_request(self, request_data: Dict, session: Optional[Dict] = None) -> Dict:
        """
        Handle a JSON-RPC 2.0 request
        
        Args:
            request_data: JSON-RPC request dictionary
            session: Session data if authenticated
            
        Returns:
            JSON-RPC response dictionary
        """
        # Validate JSON-RPC structure
        if not self._is_valid_jsonrpc(request_data):
            return self._create_error_response(
                request_data.get('id'),
                self.INVALID_REQUEST,
                "Invalid JSON-RPC 2.0 request"
            )
        
        request_id = request_data.get('id')
        method = request_data.get('method')
        params = request_data.get('params', {})
        
        # Log request
        self.logger.debug(f"Handling request: {method} (ID: {request_id})")
        
        # Route to appropriate handler
        try:
            if method == 'initialize':
                result = self._handle_initialize(params, session)
            elif method == 'initialized':
                result = self._handle_initialized(params, session)
            elif method == 'tools/list':
                result = self._handle_tools_list(params, session)
            elif method == 'tool/schema':
                result = self._handle_tool_schema(params, session)
            elif method == 'tool/description':
                result = self._handle_tool_description(params, session)
            elif method == 'tool/input_schema':
                result = self._handle_tool_input_schema(params, session)
            elif method == 'tool/output_schema':
                result = self._handle_tool_output_schema(params, session)

            elif method == 'tools/call':
                result = self._handle_tools_call(params, session)
            elif method == 'ping':
                result = self._handle_ping(params, session)
            elif method == 'prompts/list':
                return self.handle_prompts_list()
            elif method == 'prompts/get':
                return self.handle_prompts_get(request_data)
            else:
                return self._create_error_response(
                    request_id,
                    self.METHOD_NOT_FOUND,
                    f"Method not found: {method}"
                )
            
            return self._create_success_response(request_id, result)
            
        except PermissionError as e:
            return self._create_error_response(
                request_id,
                self.FORBIDDEN,
                str(e)
            )
        except ValueError as e:
            return self._create_error_response(
                request_id,
                self.INVALID_PARAMS,
                str(e)
            )
        except Exception as e:
            self.logger.error(f"Error handling request: {e}", exc_info=True)
            return self._create_error_response(
                request_id,
                self.INTERNAL_ERROR,
                "Internal server error"
            )

    def handle_prompts_list(self):
        """Handle prompts/list request"""
        prompts = self.prompts_registry.get_all_prompts()
        return {
            "jsonrpc": "2.0",
            "result": {
                "prompts": [
                    {
                        "name": p["name"],
                        "description": p["description"],
                        "arguments": p.get("arguments", [])
                    }
                    for p in prompts
                ]
            }
        }

    def handle_prompts_get(self, request_data):
        """Handle prompts/get request"""
        params = request_data.get('params', {})
        name = params.get('name')
        arguments = params.get('arguments', {})

        try:
            rendered = self.prompts_registry.render_prompt(name, arguments)
            return {
                "jsonrpc": "2.0",
                "result": {
                    "messages": [
                        {
                            "role": "user",
                            "content": {
                                "type": "text",
                                "text": rendered
                            }
                        }
                    ]
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }

    def _is_valid_jsonrpc(self, request: Dict) -> bool:
        """Check if request is valid JSON-RPC 2.0"""
        return (
            isinstance(request, dict) and
            request.get('jsonrpc') == '2.0' and
            'method' in request and
            isinstance(request['method'], str)
        )
    
    def _create_success_response(self, request_id: Any, result: Any) -> Dict:
        """Create a JSON-RPC 2.0 success response"""
        response = {
            "jsonrpc": "2.0",
            "result": result
        }
        if request_id is not None:
            response["id"] = request_id
        return response
    
    def _create_error_response(self, request_id: Any, code: int, message: str, data: Any = None) -> Dict:
        """Create a JSON-RPC 2.0 error response"""
        error = {
            "code": code,
            "message": message
        }
        if data is not None:
            error["data"] = data
        
        response = {
            "jsonrpc": "2.0",
            "error": error
        }
        if request_id is not None:
            response["id"] = request_id
        return response
    
    def _handle_initialize(self, params: Dict, session: Optional[Dict]) -> Dict:
        """
        Handle initialize request
        
        Args:
            params: Request parameters
            session: Session data
            
        Returns:
            Server information and capabilities
        """
        # Client info
        client_info = params.get('clientInfo', {})
        self.logger.info(f"Client initializing: {client_info.get('name', 'Unknown')} "
                        f"v{client_info.get('version', 'Unknown')}")
        
        return self.server_info
    
    def _handle_initialized(self, params: Dict, session: Optional[Dict]) -> Dict:
        """
        Handle initialized notification
        
        Args:
            params: Request parameters
            session: Session data
            
        Returns:
            Empty result
        """
        self.logger.info("Client initialized successfully")
        return {}
    
    def _handle_tools_list(self, params: Dict, session: Optional[Dict]) -> Dict:
        """
        Handle tools/list request
        
        Args:
            params: Request parameters
            session: Session data
            
        Returns:
            List of available tools
        """
        if not self.tools_registry:
            return {"tools": []}
        
        # Get all tools
        all_tools = self.tools_registry.get_all_tools()
        
        # Filter based on user permissions if authenticated
        if session and self.auth_manager:
            accessible_tools = self.auth_manager.get_user_accessible_tools(session)
            if '*' not in accessible_tools:
                all_tools = [
                    tool for tool in all_tools
                    if tool['name'] in accessible_tools
                ]
        
        return {"tools": all_tools}

    def _handle_tool_input_schema(self, params: Dict, session: Optional[Dict]) -> Dict:
        if not self.tools_registry:
            raise ValueError("Tools registry not available")

        tool_name = params.get('name')
        if not tool_name:
            raise ValueError("Tool name is required")

        tool = self.tools_registry.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")
        input_schema = tool.get_input_schema()
        return {"content": input_schema}

    def _handle_tool_output_schema(self, params: Dict, session: Optional[Dict]) -> Dict:
        if not self.tools_registry:
            raise ValueError("Tools registry not available")

        tool_name = params.get('name')
        if not tool_name:
            raise ValueError("Tool name is required")

        tool = self.tools_registry.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")
        output_schema = tool.get_output_schema()
        return {"content": output_schema}

    def _handle_tool_description(self, params: Dict, session: Optional[Dict]) -> Dict:
        if not self.tools_registry:
            raise ValueError("Tools registry not available")

        tool_name = params.get('name')
        if not tool_name:
            raise ValueError("Tool name is required")

        tool = self.tools_registry.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")
        name = tool.name()
        description = tool.description()
        return {
            "name": name,
            "description": description,
        }

    def _handle_tool_schema(self, params: Dict, session: Optional[Dict]) -> Dict:
        if not self.tools_registry:
            raise ValueError("Tools registry not available")

        tool_name = params.get('name')
        if not tool_name:
            raise ValueError("Tool name is required")

        tool = self.tools_registry.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")

        name = tool.name()
        description = tool.description()
        version  =tool.version()
        enabled = tool.enabled()
        input_schema =  tool.get_input_schema()
        output_schema = tool.get_output_schema()

        return {
            "name" : name,
            "description" : description,
            "version" : version,
            "enabled" : enabled,
            "input_schema": input_schema,
            "output_schema": output_schema
        }

    def _handle_tools_call(self, params: Dict, session: Optional[Dict]) -> Dict:
        """
        Handle tools/call request
        
        Args:
            params: Request parameters
            session: Session data
            
        Returns:
            Tool execution result
        """
        if not self.tools_registry:
            raise ValueError("Tools registry not available")
        
        tool_name = params.get('name')
        if not tool_name:
            raise ValueError("Tool name is required")
        
        # Check if user has access to the tool
        if session and self.auth_manager:
            if not self.auth_manager.has_tool_access(session, tool_name):
                raise PermissionError(f"Access denied to tool: {tool_name}")
        
        # Get the tool
        tool = self.tools_registry.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")
        
        # Execute the tool
        arguments = params.get('arguments', {})
        self.logger.info(f"Executing tool: {tool_name} (User: {session.get('user_id', 'anonymous')})")
        
        try:
            result = tool.execute(arguments)
            
            # Format result according to MCP spec
            if isinstance(result, str):
                result = [{"type": "text", "text": result}]
            elif not isinstance(result, list):
                result = [{"type": "text", "text": str(result)}]
            
            return {"content": result}
            
        except Exception as e:
            self.logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            raise ValueError(f"Tool execution failed: {str(e)}")
    
    def _handle_ping(self, params: Dict, session: Optional[Dict]) -> Dict:
        """
        Handle ping request
        
        Args:
            params: Request parameters
            session: Session data
            
        Returns:
            Pong response
        """
        return {
            "status": "ok",
            "timestamp": datetime.now().isoformat() + "Z"
        }
    
    def handle_batch_request(self, requests: List[Dict], session: Optional[Dict] = None) -> List[Dict]:
        """
        Handle a batch of JSON-RPC 2.0 requests
        
        Args:
            requests: List of JSON-RPC requests
            session: Session data if authenticated
            
        Returns:
            List of JSON-RPC responses
        """
        responses = []
        for request in requests:
            response = self.handle_request(request, session)
            # Don't include responses for notifications (requests without id)
            if 'id' in request:
                responses.append(response)
        return responses
