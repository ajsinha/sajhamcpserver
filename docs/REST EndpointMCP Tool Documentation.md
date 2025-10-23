# REST Endpoint MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The REST Endpoint MCP Tool provides a flexible interface for interacting with any REST API endpoint. It supports all standard HTTP methods (GET, POST, PUT, DELETE, PATCH) and includes comprehensive authentication, header management, and error handling capabilities.

## Features
- Support for all HTTP methods (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS)
- Multiple authentication methods (Basic, Bearer Token, API Key, Custom Headers)
- Query parameter and request body handling
- Custom header support
- Configurable timeout settings
- Response parsing (JSON and text)
- Connection testing and endpoint validation
- Rate limiting protection
- Detailed error handling and reporting

## Configuration

### Basic Configuration
The tool requires minimal configuration to get started. Edit the `rest_endpoint_mcp_tool.json` file:

```json
{
  "name": "rest_endpoint_tool",
  "max_hits": 500,
  "max_hit_interval": 10
}
```

### Authentication Configuration

#### 1. No Authentication (Default)
```json
{
  "authentication": {
    "type": "none"
  }
}
```

#### 2. Basic Authentication
```json
{
  "authentication": {
    "type": "basic",
    "username": "your_username",
    "password": "your_password"
  }
}
```

#### 3. Bearer Token Authentication
```json
{
  "authentication": {
    "type": "bearer",
    "token": "your_bearer_token"
  }
}
```

#### 4. API Key Authentication
```json
{
  "authentication": {
    "type": "api_key",
    "key": "your_api_key",
    "header_name": "X-API-Key"
  }
}
```

#### 5. Custom Headers Authentication
```json
{
  "authentication": {
    "type": "custom",
    "headers": {
      "X-Custom-Auth": "custom_value",
      "X-Client-ID": "client_123"
    }
  }
}
```

## Available Methods

### 1. get_request
Execute an HTTP GET request to retrieve data from an endpoint.

**Parameters:**
- `url` (required): Full URL of the endpoint
- `query_params` (optional): Query parameters as key-value pairs
- `headers` (optional): Custom headers as key-value pairs
- `timeout` (optional, default: 30): Request timeout in seconds

**Returns:**
- `status_code`: HTTP status code
- `success`: Boolean indicating if request was successful
- `data`: Response data (parsed JSON or text)
- `headers`: Response headers
- `url`: Final URL (after redirects)
- `elapsed_ms`: Request duration in milliseconds

**Example:**
```python
result = tool.handle_tool_call('get_request', {
    'url': 'https://api.example.com/users',
    'query_params': {
        'page': 1,
        'limit': 10
    },
    'headers': {
        'Accept': 'application/json'
    }
})
```

**Response:**
```json
{
  "status_code": 200,
  "success": true,
  "data": {
    "users": [...],
    "total": 100
  },
  "headers": {...},
  "url": "https://api.example.com/users?page=1&limit=10",
  "elapsed_ms": 234.5
}
```

### 2. post_request
Execute an HTTP POST request to send data to an endpoint.

**Parameters:**
- `url` (required): Full URL of the endpoint
- `data` (optional): JSON data to send in request body
- `query_params` (optional): Query parameters as key-value pairs
- `headers` (optional): Custom headers as key-value pairs
- `timeout` (optional, default: 30): Request timeout in seconds

**Returns:**
Same format as GET request

**Example:**
```python
result = tool.handle_tool_call('post_request', {
    'url': 'https://api.example.com/users',
    'data': {
        'name': 'John Doe',
        'email': 'john@example.com',
        'role': 'admin'
    },
    'headers': {
        'Content-Type': 'application/json'
    }
})
```

**Response:**
```json
{
  "status_code": 201,
  "success": true,
  "data": {
    "id": 123,
    "name": "John Doe",
    "email": "john@example.com",
    "created_at": "2025-10-20T10:30:00Z"
  },
  "headers": {...},
  "url": "https://api.example.com/users",
  "elapsed_ms": 456.7
}
```

### 3. put_request
Execute an HTTP PUT request to update data at an endpoint.

**Parameters:**
- `url` (required): Full URL of the endpoint
- `data` (optional): JSON data to send in request body
- `query_params` (optional): Query parameters as key-value pairs
- `headers` (optional): Custom headers as key-value pairs
- `timeout` (optional, default: 30): Request timeout in seconds

**Example:**
```python
result = tool.handle_tool_call('put_request', {
    'url': 'https://api.example.com/users/123',
    'data': {
        'name': 'John Smith',
        'email': 'john.smith@example.com'
    }
})
```

### 4. delete_request
Execute an HTTP DELETE request to remove data from an endpoint.

**Parameters:**
- `url` (required): Full URL of the endpoint
- `query_params` (optional): Query parameters as key-value pairs
- `headers` (optional): Custom headers as key-value pairs
- `timeout` (optional, default: 30): Request timeout in seconds

**Example:**
```python
result = tool.handle_tool_call('delete_request', {
    'url': 'https://api.example.com/users/123'
})
```

**Response:**
```json
{
  "status_code": 204,
  "success": true,
  "data": "",
  "headers": {...},
  "url": "https://api.example.com/users/123",
  "elapsed_ms": 123.4
}
```

### 5. patch_request
Execute an HTTP PATCH request to partially update data at an endpoint.

**Parameters:**
- `url` (required): Full URL of the endpoint
- `data` (optional): JSON data to send in request body
- `query_params` (optional): Query parameters as key-value pairs
- `headers` (optional): Custom headers as key-value pairs
- `timeout` (optional, default: 30): Request timeout in seconds

**Example:**
```python
result = tool.handle_tool_call('patch_request', {
    'url': 'https://api.example.com/users/123',
    'data': {
        'email': 'newemail@example.com'
    }
})
```

### 6. custom_request
Execute a custom HTTP request with full control over method and parameters.

**Parameters:**
- `url` (required): Full URL of the endpoint
- `method` (optional, default: GET): HTTP method (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS)
- `data` (optional): JSON data to send in request body
- `query_params` (optional): Query parameters as key-value pairs
- `headers` (optional): Custom headers as key-value pairs
- `timeout` (optional, default: 30): Request timeout in seconds
- `auth` (optional): Authentication tuple [username, password] to override config

**Example:**
```python
result = tool.handle_tool_call('custom_request', {
    'url': 'https://api.example.com/custom',
    'method': 'OPTIONS',
    'headers': {
        'Access-Control-Request-Method': 'POST'
    }
})
```

### 7. test_endpoint
Test endpoint connectivity and measure response time.

**Parameters:**
- `url` (required): Full URL of the endpoint to test

**Returns:**
- `url`: Tested URL
- `reachable`: Boolean indicating if endpoint is reachable
- `status_code`: HTTP status code
- `response_time_ms`: Response time in milliseconds
- `headers`: Response headers

**Example:**
```python
result = tool.handle_tool_call('test_endpoint', {
    'url': 'https://api.example.com/health'
})
```

**Response:**
```json
{
  "url": "https://api.example.com/health",
  "reachable": true,
  "status_code": 200,
  "response_time_ms": 89.3,
  "headers": {
    "Server": "nginx",
    "Content-Type": "application/json"
  }
}
```

### 8. get_endpoint_info
Get information about configured endpoints and authentication settings.

**Parameters:**
None

**Returns:**
- `authentication_type`: Current authentication type
- `default_timeout`: Default timeout in seconds
- `session_headers`: Headers applied to all requests
- `supported_methods`: List of supported HTTP methods

**Example:**
```python
result = tool.handle_tool_call('get_endpoint_info', {})
```

**Response:**
```json
{
  "authentication_type": "bearer",
  "default_timeout": 30,
  "session_headers": {
    "Authorization": "Bearer eyJ...",
    "Content-Type": "application/json"
  },
  "supported_methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
}
```

## Complete Usage Examples

### Example 1: Public API without Authentication
```python
# Search for repositories on GitHub
result = tool.handle_tool_call('get_request', {
    'url': 'https://api.github.com/search/repositories',
    'query_params': {
        'q': 'language:python',
        'sort': 'stars',
        'order': 'desc'
    }
})
```

### Example 2: API with Bearer Token
Configure in JSON:
```json
{
  "authentication": {
    "type": "bearer",
    "token": "your_access_token_here"
  }
}
```

Usage:
```python
# Get user profile
result = tool.handle_tool_call('get_request', {
    'url': 'https://api.example.com/v1/user/profile'
})

# Create a new resource
result = tool.handle_tool_call('post_request', {
    'url': 'https://api.example.com/v1/resources',
    'data': {
        'title': 'New Resource',
        'description': 'Resource description'
    }
})
```

### Example 3: API with Basic Authentication
Configure in JSON:
```json
{
  "authentication": {
    "type": "basic",
    "username": "api_user",
    "password": "api_password"
  }
}
```

Usage:
```python
# Retrieve data
result = tool.handle_tool_call('get_request', {
    'url': 'https://api.private.com/data',
    'query_params': {
        'filter': 'active'
    }
})
```

### Example 4: Working with Query Parameters
```python
# Complex query with multiple parameters
result = tool.handle_tool_call('get_request', {
    'url': 'https://api.example.com/search',
    'query_params': {
        'q': 'machine learning',
        'category': 'technology',
        'date_from': '2025-01-01',
        'date_to': '2025-12-31',
        'page': 1,
        'per_page': 50
    }
})
```

### Example 5: Custom Headers and Authentication Override
```python
# Use custom authentication for a specific request
result = tool.handle_tool_call('custom_request', {
    'url': 'https://api.example.com/secure',
    'method': 'POST',
    'data': {'key': 'value'},
    'headers': {
        'X-Custom-Header': 'custom_value',
        'X-Request-ID': 'req_123456'
    },
    'auth': ['specific_user', 'specific_password']
})
```

### Example 6: Error Handling
```python
result = tool.handle_tool_call('get_request', {
    'url': 'https://api.example.com/data',
    'timeout': 5
})

if result.get('success'):
    data = result['data']
    print(f"Success! Status: {result['status_code']}")
    print(f"Response time: {result['elapsed_ms']}ms")
else:
    print(f"Error: {result.get('error')}")
    print(f"Status: {result.get('status_code')}")
```

## Error Handling

### Common Error Responses

#### Timeout Error
```json
{
  "error": "Request timeout",
  "status_code": 408,
  "success": false
}
```

#### Connection Error
```json
{
  "error": "Connection error",
  "status_code": 503,
  "success": false
}
```

#### Rate Limit Exceeded
```json
{
  "error": "Rate limit exceeded",
  "status": 429
}
```

#### Invalid URL
```json
{
  "error": "URL is required"
}
```

#### Unsupported Method
```json
{
  "error": "Unsupported HTTP method: INVALID"
}
```

## Security Best Practices

1. **Store Credentials Securely**: Never hardcode credentials in your code. Use environment variables or secure configuration files.

2. **Use HTTPS**: Always use HTTPS endpoints when transmitting sensitive data.

3. **Validate SSL Certificates**: The tool validates SSL certificates by default.

4. **Set Appropriate Timeouts**: Configure reasonable timeout values to prevent hanging requests.

5. **Rate Limiting**: The tool includes built-in rate limiting. Configure `max_hits` and `max_hit_interval` appropriately.

6. **Authentication Types**: Choose the most secure authentication method supported by your API:
   - Bearer Token (recommended for modern APIs)
   - API Key
   - Basic Auth (use only over HTTPS)

## Performance Optimization

1. **Reuse Sessions**: The tool uses a persistent session for better performance.

2. **Set Appropriate Timeouts**: Balance between allowing sufficient time and preventing long waits.

3. **Monitor Response Times**: Use `elapsed_ms` in responses to monitor API performance.

4. **Test Endpoints**: Use `test_endpoint` to verify connectivity before making actual requests.

## Limitations

- Default timeout: 30 seconds
- Rate limiting: 500 requests per 10 seconds (configurable)
- JSON responses preferred (text fallback available)
- No support for multipart/form-data uploads (JSON only)
- No WebSocket support (REST only)
- Response size not limited (be cautious with large responses)

## Troubleshooting

### Issue: Connection Timeout
**Solution**: Increase the timeout value or check network connectivity.

### Issue: Authentication Failure
**Solution**: Verify credentials in configuration. Check if token/key has expired.

### Issue: SSL Certificate Error
**Solution**: Ensure the endpoint has a valid SSL certificate.

### Issue: Rate Limit Exceeded
**Solution**: Reduce request frequency or adjust `max_hits` configuration.

### Issue: Unexpected Response Format
**Solution**: Check API documentation. Use `custom_request` with appropriate headers.

## Advanced Features

### Session Management
The tool maintains a persistent session across requests, improving performance and maintaining authentication state.

### Automatic Header Management
Default headers (like Content-Type) are automatically added and can be overridden per request.

### URL Building
The tool automatically handles URL construction, query parameter encoding, and path joining.

## API Versioning Support

Many REST APIs use versioning. Handle this by including the version in the URL:

```python
# Version in URL path
result = tool.handle_tool_call('get_request', {
    'url': 'https://api.example.com/v2/resource'
})

# Version in header
result = tool.handle_tool_call('get_request', {
    'url': 'https://api.example.com/resource',
    'headers': {
        'API-Version': '2.0'
    }
})
```

## Integration Examples

### Integration with JSON Data Pipelines
```python
# Fetch data from API
data_response = tool.handle_tool_call('get_request', {
    'url': 'https://api.example.com/data'
})

if data_response['success']:
    # Process the JSON data
    data = data_response['data']
    # Continue with your pipeline
```

### Integration with Monitoring Systems
```python
# Test endpoint health
health_check = tool.handle_tool_call('test_endpoint', {
    'url': 'https://api.example.com/health'
})

if not health_check['reachable']:
    # Alert monitoring system
    send_alert(f"Endpoint unreachable: {health_check.get('error')}")
```

## Support and Contribution

For issues, feature requests, or contributions, please refer to the project repository.

## Changelog

### Version 1.0.0 (2025-10-20)
- Initial release
- Support for all HTTP methods
- Multiple authentication methods
- Query parameter and header support
- Error handling and rate limiting
- Endpoint testing capabilities

---

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.