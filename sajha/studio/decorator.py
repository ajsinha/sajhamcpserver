"""
SAJHA MCP Server - @sajhamcptool Decorator v2.2.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

The @sajhamcptool decorator marks a function for conversion to an MCP tool.
When MCP Studio processes code containing this decorator, it extracts:
- The function name
- The description from the decorator
- Input parameters and their types from the function signature
- Return type for output schema

Usage:
    @sajhamcptool(description="Fetch weather data for a city")
    def get_weather(city: str, units: str = "metric") -> dict:
        '''Get weather information'''
        return {"city": city, "temperature": 25, "units": units}

    @sajhamcptool(
        description="Calculate compound interest",
        category="Finance",
        tags=["calculation", "interest"]
    )
    def calculate_interest(
        principal: float,
        rate: float,
        years: int,
        compound_frequency: int = 12
    ) -> dict:
        '''Calculate compound interest'''
        amount = principal * (1 + rate / compound_frequency) ** (compound_frequency * years)
        return {"principal": principal, "final_amount": amount, "interest": amount - principal}
"""

from functools import wraps
from typing import Any, Callable, Dict, List, Optional


class SajhaMCPToolMetadata:
    """
    Metadata container for @sajhamcptool decorated functions.
    Stores all information needed to generate an MCP tool.
    """
    
    def __init__(
        self,
        description: str,
        category: str = "General",
        tags: List[str] = None,
        author: str = "MCP Studio User",
        version: str = "1.0.0",
        rate_limit: int = 60,
        cache_ttl: int = 300,
        enabled: bool = True
    ):
        self.description = description
        self.category = category
        self.tags = tags or []
        self.author = author
        self.version = version
        self.rate_limit = rate_limit
        self.cache_ttl = cache_ttl
        self.enabled = enabled
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary format."""
        return {
            'description': self.description,
            'category': self.category,
            'tags': self.tags,
            'author': self.author,
            'version': self.version,
            'rate_limit': self.rate_limit,
            'cache_ttl': self.cache_ttl,
            'enabled': self.enabled
        }


def sajhamcptool(
    description: str,
    category: str = "General",
    tags: List[str] = None,
    author: str = "MCP Studio User",
    version: str = "1.0.0",
    rate_limit: int = 60,
    cache_ttl: int = 300,
    enabled: bool = True
) -> Callable:
    """
    Decorator to mark a function as an MCP tool.
    
    This decorator is used by MCP Studio to identify functions that should
    be converted into MCP tools. The decorator stores metadata that is used
    during code analysis and tool generation.
    
    Args:
        description: Description of what the tool does (required)
        category: Tool category for organization (default: "General")
        tags: List of tags for searchability
        author: Tool author name
        version: Tool version string
        rate_limit: Requests per minute limit
        cache_ttl: Cache time-to-live in seconds
        enabled: Whether the tool is enabled by default
    
    Returns:
        Decorated function with _sajhamcptool_metadata attribute
    
    Example:
        @sajhamcptool(
            description="Search for products by name",
            category="E-commerce",
            tags=["search", "products"]
        )
        def search_products(query: str, limit: int = 10) -> dict:
            # Implementation
            return {"results": [...]}
    """
    def decorator(func: Callable) -> Callable:
        # Create metadata object
        metadata = SajhaMCPToolMetadata(
            description=description,
            category=category,
            tags=tags or [],
            author=author,
            version=version,
            rate_limit=rate_limit,
            cache_ttl=cache_ttl,
            enabled=enabled
        )
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        
        # Attach metadata to the function
        wrapper._sajhamcptool_metadata = metadata
        wrapper._is_sajhamcptool = True
        
        return wrapper
    
    return decorator


def is_sajhamcptool(func: Callable) -> bool:
    """Check if a function is decorated with @sajhamcptool."""
    return getattr(func, '_is_sajhamcptool', False)


def get_tool_metadata(func: Callable) -> Optional[SajhaMCPToolMetadata]:
    """Get the metadata from a @sajhamcptool decorated function."""
    if is_sajhamcptool(func):
        return func._sajhamcptool_metadata
    return None
