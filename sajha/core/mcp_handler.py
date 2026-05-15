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
        from sajha.core.config import get_settings
        _s = get_settings()

        # MCP 2025-11-25 features
        from sajha.core.mcp_2025_11_25 import TaskManager, ElicitationManager, SamplingManager
        self.task_manager = TaskManager()
        self.elicitation_manager = ElicitationManager()
        self.sampling_manager = SamplingManager()

        self.server_info = {
            "protocolVersion": "2025-11-25",
            "serverInfo": {
                "name": _s.app_name,
                "version": _s.app_version,
                "description": f"{_s.app_name} — Production MCP server with {len(tools_registry.tools) if tools_registry else 0} tools"
            },
            "capabilities": {
                "tools": {
                    "listChanged": True
                },
                "prompts": {
                    "listChanged": True
                },
                "resources": {
                    "subscribe": True,
                    "listChanged": True
                },
                "logging": {},
                "completions": {},
                "elicitation": {
                    "form": {},
                    "url": {}
                },
                "sampling": {
                    "tools": True
                },
                "tasks": {
                    "experimental": True
                },
                "jsonSchema": {
                    "dialect": "https://json-schema.org/draft/2020-12/schema"
                },
                "websocket": {
                    "endpoint": "/mcp/ws",
                    "authMethods": ["token", "api_key"]
                }
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
            elif method in [ 'tools/list' , 'api/tools/list', '/tools/list' , '/api/tools/list']:
                result = self._handle_tools_list(params, session)
            elif method in [ 'tool/schema' ,'api/tool/schema', '/tool/schema' ,'/api/tool/schema']:
                result = self._handle_tool_schema(params, session)
            elif method in ['tool/description', 'api/tool/description', '/tool/description', '/api/tool/description']:
                result = self._handle_tool_description(params, session)
            elif method in[ 'tool/input_schema', 'api/tool/input_schema', '/tool/input_schema', '/api/tool/input_schema']:
                result = self._handle_tool_input_schema(params, session)
            elif method in ['tool/output_schema', 'api/tool/output_schema', '/tool/output_schema', '/api/tool/output_schema']:
                result = self._handle_tool_output_schema(params, session)

            elif method in ['tools/call', 'api/tools/call', '/tools/call', '/api/tools/call']:
                result = self._handle_tools_call(params, session)
            elif method in ['ping', 'api/ping', '/ping', '/api/ping']:
                result = self._handle_ping(params, session)
            elif method in ['prompts/list', 'api/prompts/list','/prompts/list', '/api/prompts/list']:
                return self.handle_prompts_list()
            elif method in ['prompts/get', 'api/prompts/get', '/prompts/get', '/api/prompts/get']:
                return self.handle_prompts_get(request_data)

            # ── MCP v3 additions: Resources ──────────────────────
            elif method == 'resources/list':
                result = self._handle_resources_list(params)
            elif method == 'resources/read':
                result = self._handle_resources_read(params)
            elif method == 'resources/templates/list':
                result = self._handle_resources_templates_list(params)
            elif method == 'resources/subscribe':
                result = self._handle_resources_subscribe(params)
            elif method == 'resources/unsubscribe':
                result = self._handle_resources_unsubscribe(params)

            # ── MCP v3 additions: Completion ─────────────────────
            elif method == 'completion/complete':
                result = self._handle_completion_complete(params)

            # ── MCP v3 additions: Logging ────────────────────────
            elif method == 'logging/setLevel':
                result = self._handle_logging_set_level(params)

            # ── MCP 2025-11-25: Tasks (SEP-1686) ────────────────
            elif method == 'tasks/get':
                result = self.task_manager.handle_tasks_get(params)
            elif method == 'tasks/list':
                result = self.task_manager.handle_tasks_list(params)
            elif method == 'tasks/cancel':
                result = self.task_manager.handle_tasks_cancel(params)

            # ── MCP 2025-11-25: Elicitation (SEP-1330, SEP-1036) ─
            elif method == 'elicitation/respond':
                result = self.elicitation_manager.handle_elicitation_respond(params)

            # ── MCP 2025-11-25: Notifications ────────────────────
            elif method == 'notifications/cancelled':
                result = self._handle_notification_cancelled(params)

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
        
        # Pagination support (MCP spec)
        cursor = params.get('cursor')
        page_size = 100
        if cursor:
            try:
                start = int(cursor)
            except (ValueError, TypeError):
                start = 0
        else:
            start = 0
        
        page = all_tools[start:start + page_size]
        
        # MCP 2025-11-25: Add icon metadata if configured (SEP-973)
        from sajha.core.mcp_2025_11_25 import add_tool_icon
        enriched = []
        for tool_dict in page:
            tool_name = tool_dict.get('name', '')
            tool_obj = self.tools_registry.get_tool(tool_name) if self.tools_registry else None
            if tool_obj:
                cfg = getattr(tool_obj, 'config', {}) or {}
                tool_dict = add_tool_icon(tool_dict, cfg)
            enriched.append(tool_dict)
        
        result = {"tools": enriched}
        if start + page_size < len(all_tools):
            result['nextCursor'] = str(start + page_size)
        
        return result

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

        description = tool.get_description()
        return {
            "name": tool_name,
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


        description = tool.description
        version  =tool.version
        enabled = tool.enabled
        input_schema =  tool.input_schema
        output_schema = tool.output_schema

        return {
            "name" : tool_name,
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
            # MCP 2025-11-25 Minor 5: Return as Tool Execution Error (isError: true)
            # instead of Protocol Error — enables model self-correction
            self.logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            return {
                "content": [{"type": "text", "text": f"Tool execution failed: {str(e)}"}],
                "isError": True
            }
    
    def _handle_notification_cancelled(self, params: Dict) -> Dict:
        """Handle notifications/cancelled — client cancels a pending request."""
        request_id = params.get("requestId")
        reason = params.get("reason", "")
        self.logger.info(f"Request cancelled by client: {request_id} — {reason}")
        # Cancel associated task if any
        if request_id:
            self.task_manager.cancel_task(request_id)
        return {}

    def _handle_ping(self, params: Dict, session: Optional[Dict]) -> Dict:
        """Handle ping request"""
        return {
            "status": "ok",
            "timestamp": datetime.now().isoformat() + "Z"
        }

    # ═════════════════════════════════════════════════════════════
    # MCP v3: Resources
    # ═════════════════════════════════════════════════════════════

    def _handle_resources_list(self, params: Dict) -> Dict:
        """Handle resources/list — expose datasets, tool catalog, data files."""
        import os
        resources = []

        # Tool catalog as a resource
        tool_count = len(self.tools_registry.tools) if self.tools_registry else 0
        resources.append({
            'uri': 'sajha://tools/catalog',
            'name': 'Tool Catalog',
            'mimeType': 'application/json',
            'description': f'Catalog of {tool_count} available MCP tools',
        })

        # Prompt catalog
        prompt_count = len(self.prompts_registry.prompts) if self.prompts_registry else 0
        if prompt_count > 0:
            resources.append({
                'uri': 'sajha://prompts/catalog',
                'name': 'Prompt Catalog',
                'mimeType': 'application/json',
                'description': f'Catalog of {prompt_count} available prompts',
            })

        # Data directory files
        for data_dir in ['data/duckdb', 'data/sqlselect']:
            if os.path.isdir(data_dir):
                for fname in os.listdir(data_dir):
                    if fname.endswith(('.csv', '.parquet', '.json', '.xlsx')):
                        resources.append({
                            'uri': f'sajha://data/{fname}',
                            'name': fname,
                            'mimeType': 'application/octet-stream',
                            'description': f'Data file: {fname}',
                        })

        # Pagination support
        cursor = params.get('cursor')
        page_size = 50
        if cursor:
            try:
                start = int(cursor)
            except (ValueError, TypeError):
                start = 0
        else:
            start = 0

        page = resources[start:start + page_size]
        result = {'resources': page}
        if start + page_size < len(resources):
            result['nextCursor'] = str(start + page_size)

        return result

    def _handle_resources_read(self, params: Dict) -> Dict:
        """Handle resources/read — read a resource by URI."""
        import json as _json
        uri = params.get('uri', '')

        if uri == 'sajha://tools/catalog':
            tools = self.tools_registry.get_all_tools() if self.tools_registry else []
            return {
                'contents': [{
                    'uri': uri,
                    'mimeType': 'application/json',
                    'text': _json.dumps(tools, indent=2, default=str),
                }]
            }

        if uri == 'sajha://prompts/catalog':
            prompts = self.prompts_registry.get_all_prompts() if self.prompts_registry else []
            return {
                'contents': [{
                    'uri': uri,
                    'mimeType': 'application/json',
                    'text': _json.dumps(prompts, indent=2, default=str),
                }]
            }

        if uri.startswith('sajha://data/'):
            fname = uri.replace('sajha://data/', '')
            for data_dir in ['data/duckdb', 'data/sqlselect']:
                import os
                fpath = os.path.join(data_dir, fname)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            content = f.read()
                        return {
                            'contents': [{
                                'uri': uri,
                                'mimeType': 'text/csv' if fname.endswith('.csv') else 'application/json',
                                'text': content,
                            }]
                        }
                    except Exception as e:
                        return {'contents': [{'uri': uri, 'mimeType': 'text/plain', 'text': f'Error reading file: {e}'}]}

        return {'contents': [{'uri': uri, 'mimeType': 'text/plain', 'text': f'Resource not found: {uri}'}]}

    def _handle_resources_templates_list(self, params: Dict) -> Dict:
        """Handle resources/templates/list — parameterized resource templates."""
        return {
            'resourceTemplates': [
                {
                    'uriTemplate': 'sajha://tools/{tool_name}/schema',
                    'name': 'Tool Schema',
                    'description': 'Get the input/output schema for a specific tool',
                    'mimeType': 'application/json',
                },
                {
                    'uriTemplate': 'sajha://data/{filename}',
                    'name': 'Data File',
                    'description': 'Read a data file from the server data directory',
                },
            ]
        }

    def _handle_resources_subscribe(self, params: Dict) -> Dict:
        """Handle resources/subscribe — subscribe to resource changes."""
        uri = params.get('uri', '')
        self.logger.info(f"Client subscribed to resource: {uri}")
        return {}

    def _handle_resources_unsubscribe(self, params: Dict) -> Dict:
        """Handle resources/unsubscribe — unsubscribe from resource changes."""
        uri = params.get('uri', '')
        self.logger.info(f"Client unsubscribed from resource: {uri}")
        return {}

    # ═════════════════════════════════════════════════════════════
    # MCP v3: Completion
    # ═════════════════════════════════════════════════════════════

    def _handle_completion_complete(self, params: Dict) -> Dict:
        """Handle completion/complete — auto-complete for tool/prompt arguments."""
        ref = params.get('ref', {})
        argument = params.get('argument', {})
        arg_name = argument.get('name', '')
        partial = argument.get('value', '')

        values = []

        if ref.get('type') == 'ref/tool':
            tool_name = ref.get('name', '')
            tool = self.tools_registry.get_tool(tool_name) if self.tools_registry else None
            if tool:
                schema = tool.input_schema
                prop = schema.get('properties', {}).get(arg_name, {})
                # Suggest from enum values
                if 'enum' in prop:
                    values = [v for v in prop['enum'] if partial.lower() in v.lower()]
                # Suggest from default
                elif 'default' in prop and partial == '':
                    values = [str(prop['default'])]

        elif ref.get('type') == 'ref/prompt':
            prompt_name = ref.get('name', '')
            if self.prompts_registry:
                prompt = self.prompts_registry.get_prompt(prompt_name)
                if prompt and 'arguments' in prompt:
                    for arg in prompt.get('arguments', []):
                        if arg.get('name') == arg_name and 'enum' in arg:
                            values = [v for v in arg['enum'] if partial.lower() in v.lower()]

        return {
            'completion': {
                'values': values[:20],
                'hasMore': len(values) > 20,
                'total': len(values),
            }
        }

    # ═════════════════════════════════════════════════════════════
    # MCP v3: Logging
    # ═════════════════════════════════════════════════════════════

    def _handle_logging_set_level(self, params: Dict) -> Dict:
        """Handle logging/setLevel — dynamically adjust server log level."""
        level = params.get('level', 'info').upper()
        valid = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL',
                 'ALERT', 'NOTICE', 'EMERGENCY'}  # MCP spec levels
        level_map = {
            'ALERT': 'CRITICAL', 'NOTICE': 'INFO', 'EMERGENCY': 'CRITICAL',
            'DEBUG': 'DEBUG', 'INFO': 'INFO', 'WARNING': 'WARNING',
            'ERROR': 'ERROR', 'CRITICAL': 'CRITICAL',
        }
        if level not in valid:
            return {'error': f'Invalid level: {level}'}

        python_level = level_map.get(level, 'INFO')
        logging.getLogger().setLevel(getattr(logging, python_level))
        self.logger.info(f'Log level changed to {level} (Python: {python_level})')
        return {}
    
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
