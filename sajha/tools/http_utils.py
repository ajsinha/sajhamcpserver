"""
SAJHA MCP Server - HTTP Utilities v2.2.0

Copyright © 2025-2030, All Rights Reserved

Provides safe HTTP response handling with multi-encoding support.
"""

import gzip
import json
from typing import Optional, List, Tuple, Any
from http.client import HTTPResponse


# Common encodings by region/language
ENCODINGS_DEFAULT = ['utf-8', 'latin-1', 'iso-8859-1']
ENCODINGS_JAPANESE = ['utf-8', 'shift_jis', 'euc-jp', 'cp932', 'iso-2022-jp']
ENCODINGS_CHINESE = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5']
ENCODINGS_KOREAN = ['utf-8', 'euc-kr', 'cp949', 'iso-2022-kr']
ENCODINGS_EUROPEAN = ['utf-8', 'latin-1', 'iso-8859-1', 'iso-8859-15', 'cp1252', 'windows-1252']
ENCODINGS_ALL = ['utf-8', 'latin-1', 'iso-8859-1', 'shift_jis', 'gbk', 'euc-jp', 'gb2312', 'cp1252']


def decompress_response(raw_data: bytes, response: HTTPResponse) -> bytes:
    """
    Decompress response data if gzip or deflate encoded.
    
    Args:
        raw_data: Raw bytes from response
        response: HTTPResponse object to check encoding header
        
    Returns:
        Decompressed bytes
    """
    content_encoding = response.info().get('Content-Encoding', '').lower()
    
    if content_encoding == 'gzip':
        try:
            return gzip.decompress(raw_data)
        except Exception:
            pass  # Return original if decompression fails
    elif content_encoding == 'deflate':
        try:
            import zlib
            return zlib.decompress(raw_data, -zlib.MAX_WBITS)
        except Exception:
            pass
    
    return raw_data


def safe_decode(
    raw_data: bytes,
    encodings: Optional[List[str]] = None,
    fallback_errors: str = 'replace'
) -> str:
    """
    Safely decode bytes to string, trying multiple encodings.
    
    Args:
        raw_data: Raw bytes to decode
        encodings: List of encodings to try (default: ENCODINGS_DEFAULT)
        fallback_errors: Error handling for final fallback ('replace', 'ignore', 'strict')
        
    Returns:
        Decoded string
    """
    if encodings is None:
        encodings = ENCODINGS_DEFAULT
    
    # Try each encoding in order
    for encoding in encodings:
        try:
            return raw_data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    
    # Final fallback: UTF-8 with error handling
    return raw_data.decode('utf-8', errors=fallback_errors)


def safe_decode_response(
    response: HTTPResponse,
    encodings: Optional[List[str]] = None
) -> str:
    """
    Read and safely decode an HTTP response.
    
    Handles gzip/deflate decompression and multi-encoding decoding.
    
    Args:
        response: HTTPResponse object
        encodings: List of encodings to try
        
    Returns:
        Decoded response body as string
    """
    raw_data = response.read()
    raw_data = decompress_response(raw_data, response)
    return safe_decode(raw_data, encodings)


def safe_json_response(
    response: HTTPResponse,
    encodings: Optional[List[str]] = None
) -> Any:
    """
    Read HTTP response and parse as JSON with safe decoding.
    
    Args:
        response: HTTPResponse object
        encodings: List of encodings to try
        
    Returns:
        Parsed JSON data
        
    Raises:
        json.JSONDecodeError: If response is not valid JSON
    """
    decoded = safe_decode_response(response, encodings)
    return json.loads(decoded)


def get_encodings_for_region(region: str) -> List[str]:
    """
    Get appropriate encodings list for a region/language.
    
    Args:
        region: One of 'japanese', 'chinese', 'korean', 'european', 'default', 'all'
        
    Returns:
        List of encodings to try
    """
    mapping = {
        'japanese': ENCODINGS_JAPANESE,
        'japan': ENCODINGS_JAPANESE,
        'jp': ENCODINGS_JAPANESE,
        'chinese': ENCODINGS_CHINESE,
        'china': ENCODINGS_CHINESE,
        'cn': ENCODINGS_CHINESE,
        'korean': ENCODINGS_KOREAN,
        'korea': ENCODINGS_KOREAN,
        'kr': ENCODINGS_KOREAN,
        'european': ENCODINGS_EUROPEAN,
        'europe': ENCODINGS_EUROPEAN,
        'eu': ENCODINGS_EUROPEAN,
        'all': ENCODINGS_ALL,
        'default': ENCODINGS_DEFAULT,
    }
    return mapping.get(region.lower(), ENCODINGS_DEFAULT)
