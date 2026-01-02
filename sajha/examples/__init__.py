"""
SAJHA MCP Server - Example Clients Module v2.1.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

This module contains standalone Python client examples demonstrating
how to use the SAJHA MCP Server API with API key authentication.

Each example file contains:
- Complete working client code
- Multiple usage examples
- Error handling
- Pretty-printed output

Usage:
    1. Set your API key as environment variable:
       export SAJHA_API_KEY="sja_your_key_here"
    
    2. Run any example:
       python -m sajha.examples.wikipedia_client
       python -m sajha.examples.yahoo_finance_client
       etc.
"""

__version__ = '2.1.0'
__author__ = 'Ashutosh Sinha'
__email__ = 'ajsinha@gmail.com'

from .base_client import SajhaClient

__all__ = ['SajhaClient', '__version__']
