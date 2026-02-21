# MCP Studio REST Tool Creator Guide
## SAJHA MCP Server v2.9.8

## Overview

The REST Tool Creator in MCP Studio enables you to create MCP tools that interact with any REST API without writing code. This visual interface guides you through configuring API endpoints, authentication, request/response handling, and error management.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Understanding REST Tools](#understanding-rest-tools)
3. [Creating Your First REST Tool](#creating-your-first-rest-tool)
4. [Configuration Options](#configuration-options)
5. [Authentication Methods](#authentication-methods)
6. [Request Configuration](#request-configuration)
7. [Response Handling](#response-handling)
8. [Error Handling](#error-handling)
9. [Testing and Validation](#testing-and-validation)
10. [Best Practices](#best-practices)
11. [Examples](#examples)
12. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Accessing the REST Tool Creator

1. Navigate to `http://localhost:3002/admin/studio`
2. Click on **REST Service Tool** card
3. Or directly access: `http://localhost:3002/admin/studio/rest`

### Prerequisites

- Admin role access to SAJHA MCP Server
- Understanding of the target REST API
- API documentation or endpoint specifications
- Authentication credentials (if required)

---

## Understanding REST Tools

REST tools in SAJHA act as bridges between MCP clients (like Claude) and external REST APIs. When a user invokes a REST tool:

1. The tool receives input parameters from the MCP client
2. It constructs an HTTP request based on your configuration
3. Sends the request to the external API
4. Processes the response
5. Returns formatted data to the MCP client

### Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌─────────────┐
│  MCP Client │────▶│  REST Tool   │────▶│  External API   │────▶│  Response   │
│  (Claude)   │◀────│  (SAJHA)     │◀────│  (Target)       │◀────│  Processing │
└─────────────┘     └──────────────┘     └─────────────────┘     └─────────────┘
```

---

## Creating Your First REST Tool

### Step 1: Basic Information

Fill in the essential tool details:

| Field | Description | Example |
|-------|-------------|---------|
| **Tool Name** | Unique identifier (snake_case) | `weather_api_get_forecast` |
| **Display Name** | Human-readable name | `Weather Forecast API` |
| **Description** | What the tool does | `Retrieves weather forecast for a location` |
| **Category** | Tool grouping | `Weather Services` |
| **Version** | Semantic version | `1.0.0` |

### Step 2: API Endpoint Configuration

Configure the target API:

```
Base URL: https://api.weather.com
Endpoint: /v1/forecast
Method: GET
```

### Step 3: Input Parameters

Define what inputs the tool accepts:

```json
{
  "location": {
    "type": "string",
    "required": true,
    "description": "City name or coordinates"
  },
  "days": {
    "type": "integer",
    "required": false,
    "default": 7,
    "description": "Number of forecast days"
  }
}
```

### Step 4: Deploy

Click **Deploy Tool** to create and register the tool.

---

## Configuration Options

### Basic Configuration

```json
{
  "name": "my_rest_tool",
  "implementation": "sajha.tools.impl.rest_tool.RESTTool",
  "version": "2.9.8",
  "enabled": true,
  "base_url": "https://api.example.com",
  "endpoint": "/v1/resource",
  "method": "GET",
  "timeout": 30,
  "retry_count": 3,
  "retry_delay": 1
}
```

### Supported HTTP Methods

| Method | Use Case |
|--------|----------|
| **GET** | Retrieve data |
| **POST** | Create resources, submit data |
| **PUT** | Update/replace resources |
| **PATCH** | Partial updates |
| **DELETE** | Remove resources |

### Headers Configuration

```json
{
  "headers": {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "SAJHA-MCP-Server/2.9.8",
    "X-Custom-Header": "${custom.header.value}"
  }
}
```

### Query Parameters

```json
{
  "query_params": {
    "api_key": "${api.key}",
    "format": "json",
    "language": "en"
  }
}
```

---

## Authentication Methods

### 1. API Key Authentication

**In Header:**
```json
{
  "auth": {
    "type": "api_key",
    "location": "header",
    "key_name": "X-API-Key",
    "key_value": "${my.api.key}"
  }
}
```

**In Query String:**
```json
{
  "auth": {
    "type": "api_key",
    "location": "query",
    "key_name": "api_key",
    "key_value": "${my.api.key}"
  }
}
```

### 2. Bearer Token

```json
{
  "auth": {
    "type": "bearer",
    "token": "${bearer.token}"
  }
}
```

### 3. Basic Authentication

```json
{
  "auth": {
    "type": "basic",
    "username": "${api.username}",
    "password": "${api.password}"
  }
}
```

### 4. OAuth 2.0

```json
{
  "auth": {
    "type": "oauth2",
    "client_id": "${oauth.client.id}",
    "client_secret": "${oauth.client.secret}",
    "token_url": "https://auth.example.com/oauth/token",
    "scope": "read write"
  }
}
```

---

## Request Configuration

### URL Path Parameters

For endpoints like `/users/{user_id}/posts/{post_id}`:

```json
{
  "endpoint": "/users/{user_id}/posts/{post_id}",
  "path_params": {
    "user_id": {
      "type": "string",
      "required": true,
      "description": "User identifier"
    },
    "post_id": {
      "type": "string",
      "required": true,
      "description": "Post identifier"
    }
  }
}
```

### Request Body (POST/PUT/PATCH)

**JSON Body:**
```json
{
  "body": {
    "type": "json",
    "schema": {
      "title": {"type": "string", "required": true},
      "content": {"type": "string", "required": true},
      "tags": {"type": "array", "items": "string"}
    }
  }
}
```

**Form Data:**
```json
{
  "body": {
    "type": "form",
    "fields": {
      "name": {"type": "string"},
      "file": {"type": "file"}
    }
  }
}
```

### Dynamic URL Construction

```json
{
  "url_template": "https://api.example.com/{version}/users/{user_id}",
  "url_params": {
    "version": {"default": "v2"},
    "user_id": {"required": true}
  }
}
```

---

## Response Handling

### Response Mapping

Extract and transform response data:

```json
{
  "response": {
    "type": "json",
    "mapping": {
      "id": "$.data.id",
      "name": "$.data.attributes.name",
      "items": "$.data.items[*]",
      "total": "$.meta.total_count"
    }
  }
}
```

### JSONPath Expressions

| Expression | Description |
|------------|-------------|
| `$.field` | Root level field |
| `$.data.nested` | Nested field |
| `$.items[0]` | First array element |
| `$.items[*]` | All array elements |
| `$.items[?(@.active)]` | Filter active items |

### Response Schema

```json
{
  "outputSchema": {
    "type": "object",
    "properties": {
      "success": {"type": "boolean"},
      "data": {
        "type": "object",
        "properties": {
          "id": {"type": "string"},
          "name": {"type": "string"}
        }
      },
      "metadata": {
        "type": "object",
        "properties": {
          "request_id": {"type": "string"},
          "timestamp": {"type": "string"}
        }
      }
    }
  }
}
```

---

## Error Handling

### HTTP Status Code Handling

```json
{
  "error_handling": {
    "400": {"message": "Bad request - check input parameters"},
    "401": {"message": "Authentication failed - verify credentials"},
    "403": {"message": "Access forbidden - insufficient permissions"},
    "404": {"message": "Resource not found"},
    "429": {"message": "Rate limit exceeded", "retry": true},
    "500": {"message": "Server error - try again later", "retry": true}
  }
}
```

### Retry Configuration

```json
{
  "retry": {
    "enabled": true,
    "max_attempts": 3,
    "delay_seconds": 2,
    "backoff_multiplier": 2,
    "retry_on": [429, 500, 502, 503, 504]
  }
}
```

### Timeout Settings

```json
{
  "timeout": {
    "connect": 10,
    "read": 30,
    "total": 60
  }
}
```

---

## Testing and Validation

### Built-in Test Feature

1. Fill in all configuration fields
2. Click **Test Connection** button
3. Provide sample input values
4. Review response preview

### Validation Checks

The creator validates:
- ✅ Required fields are filled
- ✅ URL format is valid
- ✅ JSON schemas are valid
- ✅ Authentication credentials are present
- ✅ Input/output schemas match

### Debug Mode

Enable detailed logging:

```json
{
  "debug": {
    "enabled": true,
    "log_requests": true,
    "log_responses": true,
    "log_headers": false
  }
}
```

---

## Best Practices

### 1. Naming Conventions

- Use `snake_case` for tool names
- Prefix with service name: `github_get_repos`
- Be descriptive: `stripe_create_payment_intent`

### 2. Security

- **Never hardcode credentials** - use `${variable}` syntax
- Store API keys in `application.properties`
- Use HTTPS endpoints only
- Implement rate limiting

### 3. Input Validation

```json
{
  "inputSchema": {
    "email": {
      "type": "string",
      "format": "email",
      "required": true
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 100,
      "default": 10
    }
  }
}
```

### 4. Documentation

- Write clear descriptions
- Provide usage examples
- Document error scenarios
- Include rate limit info

### 5. Performance

- Set appropriate timeouts
- Enable caching where applicable
- Implement pagination for large datasets

---

## Examples

### Example 1: GitHub Repository Search

```json
{
  "name": "github_search_repos",
  "description": "Search GitHub repositories",
  "base_url": "https://api.github.com",
  "endpoint": "/search/repositories",
  "method": "GET",
  "headers": {
    "Accept": "application/vnd.github.v3+json",
    "Authorization": "Bearer ${github.token}"
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "required": true,
        "description": "Search query"
      },
      "sort": {
        "type": "string",
        "enum": ["stars", "forks", "updated"],
        "default": "stars"
      },
      "per_page": {
        "type": "integer",
        "minimum": 1,
        "maximum": 100,
        "default": 10
      }
    }
  },
  "response": {
    "mapping": {
      "total_count": "$.total_count",
      "repositories": "$.items[*]"
    }
  }
}
```

### Example 2: Stripe Payment Creation

```json
{
  "name": "stripe_create_payment",
  "description": "Create a Stripe payment intent",
  "base_url": "https://api.stripe.com",
  "endpoint": "/v1/payment_intents",
  "method": "POST",
  "auth": {
    "type": "bearer",
    "token": "${stripe.secret.key}"
  },
  "body": {
    "type": "form",
    "fields": {
      "amount": {"type": "integer", "required": true},
      "currency": {"type": "string", "required": true},
      "description": {"type": "string"}
    }
  }
}
```

### Example 3: OpenWeather API

```json
{
  "name": "weather_get_current",
  "description": "Get current weather for a city",
  "base_url": "https://api.openweathermap.org",
  "endpoint": "/data/2.5/weather",
  "method": "GET",
  "query_params": {
    "appid": "${openweather.api.key}",
    "units": "metric"
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "city": {
        "type": "string",
        "required": true,
        "description": "City name"
      }
    }
  },
  "response": {
    "mapping": {
      "temperature": "$.main.temp",
      "humidity": "$.main.humidity",
      "description": "$.weather[0].description",
      "wind_speed": "$.wind.speed"
    }
  }
}
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Connection timeout | Slow API or network | Increase timeout value |
| 401 Unauthorized | Invalid credentials | Check API key/token |
| 400 Bad Request | Invalid input | Verify input schema |
| SSL Certificate Error | Self-signed cert | Add to trusted certs |
| Rate Limited (429) | Too many requests | Implement retry with backoff |

### Debug Checklist

1. ✅ Verify base URL is correct
2. ✅ Check endpoint path
3. ✅ Confirm HTTP method
4. ✅ Validate authentication
5. ✅ Test with curl/Postman first
6. ✅ Check server logs

### Log Analysis

```bash
# View REST tool logs
tail -f logs/sajha_mcp.log | grep "REST"
```

---

## Related Documentation

- [MCP Studio Overview](MCP_Studio_User_Guide.md)
- [Variable Substitution Guide](../architecture/SAJHA_MCP_Server_Architecture.md)
- [Authentication Configuration](../architecture/Glossary.md)

---

*SAJHA MCP Server v2.9.8 - REST Tool Creator Guide*
*Copyright © 2025-2030 Ashutosh Sinha*
