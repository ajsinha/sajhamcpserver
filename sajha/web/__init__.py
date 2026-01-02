"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Web module for SAJHA MCP Server v2.2.0
"""

from .app import create_app
from .sajhamcpserver_web import SajhaMCPServerWebApp

__all__ = ['create_app', 'SajhaMCPServerWebApp']
