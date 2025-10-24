"""
Echo MCP Tool implementation
"""
import wikipedia
from typing import Dict, Any, List
from .base_mcp_tool import BaseMCPTool


class EchoMCPTool(BaseMCPTool):
    """MCP Tool for Wikipedia operations"""

    def _initialize(self):
        """Initialize Wikipedia specific components"""
        wikipedia.set_lang('en')  # Default to English

    def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Wikipedia tool calls"""
        try:
            if self.check_rate_limit():
                error_msg = "Rate limit exceeded"
                self.record_call(tool_name, arguments, error=error_msg)
                return {"error": error_msg, "status": 429}

            result = None

            tool_methods = {
                "echo": self._echo
            }

            if tool_name in tool_methods:
                result = tool_methods[tool_name](arguments)
            else:
                result = {"error": f"Unknown tool: {tool_name}"}

            self.record_call(tool_name, arguments, result=result)
            return result

        except Exception as e:
            error_msg = str(e)
            self.record_call(tool_name, arguments, error=error_msg)
            return {"error": error_msg, "status": 500}

    def _echo(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search for Wikipedia articles"""
        input = params.get('input', '')

        if not input:
            return {"error": "Input is required"}

        try:
            results = input
            return {
                "input": input,
                "results": input,
                "count": len(results)
            }
        except Exception as e:
            return {"error": str(e)}

