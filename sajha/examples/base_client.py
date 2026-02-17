"""
SAJHA MCP Server - Base Client v2.3.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Base client class for all SAJHA MCP Server API interactions.
Provides common functionality for authentication and tool execution.
"""

import os
import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List


class SajhaClient:
    """
    Base client for SAJHA MCP Server API.
    
    Supports authentication via:
    - API Key (X-API-Key header)
    - Bearer token (Authorization header)
    
    Example:
        client = SajhaClient(api_key="sja_your_key")
        result = client.execute_tool("wiki_search", {"query": "Python"})
    """
    
    VERSION = '2.2.0'
    DEFAULT_BASE_URL = 'http://localhost:3002'
    
    def __init__(self, 
                 api_key: Optional[str] = None,
                 bearer_token: Optional[str] = None,
                 base_url: Optional[str] = None):
        """
        Initialize the SAJHA client.
        
        Args:
            api_key: API key for authentication (sja_xxx format)
            bearer_token: Bearer token for authentication
            base_url: Base URL of the SAJHA server (default: http://localhost:3002)
        """
        self.api_key = api_key or os.environ.get('SAJHA_API_KEY')
        self.bearer_token = bearer_token or os.environ.get('SAJHA_BEARER_TOKEN')
        self.base_url = (base_url or os.environ.get('SAJHA_BASE_URL', self.DEFAULT_BASE_URL)).rstrip('/')
        
        if not self.api_key and not self.bearer_token:
            raise ValueError(
                "Authentication required. Provide api_key, bearer_token, "
                "or set SAJHA_API_KEY/SAJHA_BEARER_TOKEN environment variable."
            )
    
    def _get_headers(self) -> Dict[str, str]:
        """Get authentication headers."""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': f'SajhaClient/{self.VERSION}'
        }
        
        if self.api_key:
            headers['X-API-Key'] = self.api_key
        elif self.bearer_token:
            headers['Authorization'] = f'Bearer {self.bearer_token}'
        
        return headers
    
    def _make_request(self, 
                      endpoint: str, 
                      method: str = 'GET',
                      data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Make HTTP request to the SAJHA server.
        
        Args:
            endpoint: API endpoint (e.g., '/api/tools/list')
            method: HTTP method (GET, POST, etc.)
            data: Request body data for POST requests
            
        Returns:
            Response data as dictionary
            
        Raises:
            SajhaAPIError: If the request fails
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        
        request_data = None
        if data:
            request_data = json.dumps(data).encode('utf-8')
        
        req = urllib.request.Request(
            url,
            data=request_data,
            headers=headers,
            method=method
        )
        
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                response_data = response.read().decode('utf-8')
                return json.loads(response_data)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''
            try:
                error_data = json.loads(error_body)
                error_msg = error_data.get('error', str(e))
            except:
                error_msg = error_body or str(e)
            raise SajhaAPIError(f"HTTP {e.code}: {error_msg}", e.code)
        except urllib.error.URLError as e:
            raise SajhaAPIError(f"Connection error: {e.reason}")
        except json.JSONDecodeError as e:
            raise SajhaAPIError(f"Invalid JSON response: {e}")
    
    def execute_tool(self, 
                     tool_name: str, 
                     arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a tool on the SAJHA server.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments as dictionary
            
        Returns:
            Tool execution result
            
        Example:
            result = client.execute_tool("wiki_search", {"query": "Python", "limit": 5})
        """
        data = {
            'tool': tool_name,
            'arguments': arguments or {}
        }
        
        response = self._make_request('/api/tools/execute', method='POST', data=data)
        
        if response.get('success'):
            return response.get('result', {})
        else:
            raise SajhaAPIError(response.get('error', 'Tool execution failed'))
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """
        Get list of all available tools.
        
        Returns:
            List of tool definitions
        """
        response = self._make_request('/api/tools/list')
        return response.get('tools', [])
    
    def get_tool_schema(self, tool_name: str) -> Dict[str, Any]:
        """
        Get the input schema for a specific tool.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Tool schema in MCP format
        """
        return self._make_request(f'/api/tools/{tool_name}/schema')
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check server health status.
        
        Returns:
            Health status information
        """
        return self._make_request('/health')
    
    def mcp_request(self, 
                    method: str, 
                    params: Optional[Dict] = None,
                    request_id: int = 1) -> Dict[str, Any]:
        """
        Send a raw MCP protocol request.
        
        Args:
            method: MCP method (e.g., 'tools/list', 'tools/call')
            params: Method parameters
            request_id: JSON-RPC request ID
            
        Returns:
            MCP response
        """
        data = {
            'jsonrpc': '2.0',
            'id': request_id,
            'method': method,
            'params': params or {}
        }
        
        return self._make_request('/api/mcp', method='POST', data=data)


class SajhaAPIError(Exception):
    """Exception raised for SAJHA API errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


def pretty_print(data: Any, title: str = None):
    """Helper function to pretty-print JSON data."""
    if title:
        print(f"\n{'='*60}")
        print(f" {title}")
        print('='*60)
    print(json.dumps(data, indent=2, default=str))


def run_example(func):
    """Decorator to run example functions with error handling."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except SajhaAPIError as e:
            print(f"\n❌ API Error: {e.message}")
            if e.status_code:
                print(f"   Status Code: {e.status_code}")
        except Exception as e:
            print(f"\n❌ Error: {e}")
    return wrapper


if __name__ == '__main__':
    # Quick test
    print(f"SAJHA Client v{SajhaClient.VERSION}")
    print("\nUsage:")
    print("  from sajha.examples import SajhaClient")
    print("  client = SajhaClient(api_key='sja_your_key')")
    print("  result = client.execute_tool('wiki_search', {'query': 'Python'})")
