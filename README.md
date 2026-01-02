# SAJHA MCP Server

**Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com**

## Overview

SAJHA MCP Server is a production-ready Python-based implementation of the Model Context Protocol (MCP) that provides a standardized interface for AI tools and services. The server supports both HTTP REST APIs and WebSocket connections for real-time bidirectional communication.

## Features

- ✅ Full MCP (Model Context Protocol) compliance
- ✅ Dual transport: HTTP REST API and WebSocket
- ✅ Role-Based Access Control (RBAC)
- ✅ Plugin-based tool architecture with dynamic loading
- ✅ Web UI for tool discovery and testing
- ✅ Real-time monitoring dashboards
- ✅ Built-in tools: Wikipedia, Yahoo Finance, Google Search, Federal Reserve
- ✅ Properties-based configuration with auto-reload
- ✅ Comprehensive audit logging
- ✅ **MCP Studio** (v2.2.0): Visual tool creator with @sajhamcptool decorator
- ✅ API Key Authentication with tool-level permissions
- ✅ Hot-reload for config changes (zero downtime)

## Requirements

- Python 3.9 or higher
- 2GB RAM minimum (4GB recommended)
- 1GB disk space

## Installation

1. **Clone the repository:**
```bash
git clone <repository-url>
cd sajhamcpserver
```

2. **Create a virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Run the server:**
```bash
python run_server.py
```

The server will start on `http://localhost:8000` by default.

## Default Login

- **Username:** admin
- **Password:** admin123

⚠️ **Important:** Change the default password immediately after first login!

## Configuration

### Server Configuration (`config/server.properties`)

```properties
server.host=0.0.0.0
server.port=8000
server.debug=false
session.timeout.minutes=60
```

### Application Configuration (`config/application.properties`)

```properties
app.name=SAJHA MCP Server
app.version=2.2.0
mcp.protocol.version=1.0
```

### User Management (`config/users.json`)

```json
{
  "users": [
    {
      "user_id": "admin",
      "user_name": "Administrator",
      "password": "admin123",
      "roles": ["admin"],
      "tools": ["*"],
      "enabled": true
    }
  ]
}
```

## Built-in Tools

### 1. Wikipedia Tool
Search and retrieve information from Wikipedia.

**Actions:**
- `search`: Search Wikipedia articles
- `get_page`: Get full page content
- `get_summary`: Get page summary

### 2. Yahoo Finance Tool
Retrieve real-time stock market data.

**Actions:**
- `get_quote`: Get current stock quote
- `get_history`: Get historical data
- `search_symbols`: Search for stock symbols

### 3. Google Search Tool
Web search using Google Custom Search API.

**Actions:**
- Search web, images, or videos
- Site-specific searches
- Safe search filtering

**Note:** Requires Google API key for production use. Demo mode available.

### 4. Federal Reserve Tool
Access economic data from FRED (Federal Reserve Economic Data).

**Actions:**
- `get_series`: Get time series data
- `get_latest`: Get latest observation
- `search_series`: Search for data series
- `get_common_indicators`: Get common economic indicators

**Note:** Requires FRED API key for production use. Demo mode available.

## MCP Studio (New in v2.2.0)

MCP Studio is a visual tool creator that allows administrators to create custom MCP tools using Python code with the `@sajhamcptool` decorator.

### How It Works

1. Write a Python function with the `@sajhamcptool` decorator
2. The system analyzes your function's type hints to generate input/output schemas
3. Preview the generated JSON config and Python implementation
4. Deploy with one click - files are automatically created

### Example

```python
from sajha.studio import sajhamcptool

@sajhamcptool(
    description="Calculate compound interest",
    category="Finance",
    tags=["calculator", "interest"]
)
def compound_interest(
    principal: float,
    rate: float,
    years: int,
    frequency: int = 12
) -> dict:
    """Calculate compound interest."""
    amount = principal * (1 + rate / frequency) ** (frequency * years)
    return {
        "principal": principal,
        "final_amount": round(amount, 2),
        "interest_earned": round(amount - principal, 2)
    }
```

### Access MCP Studio

Navigate to **Admin → MCP Studio** in the web interface (admin access required).

## API Usage

### Authentication

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"user_id": "admin", "password": "admin123"}'
```

### MCP Protocol

```bash
curl -X POST http://localhost:8000/api/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "tools/list",
    "params": {}
  }'
```

### Execute Tool

```bash
curl -X POST http://localhost:8000/api/tools/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "tool": "wikipedia",
    "arguments": {
      "action": "search",
      "query": "Python programming",
      "limit": 5
    }
  }'
```

## WebSocket Usage

```javascript
const socket = io('http://localhost:8000');

// Authenticate
socket.emit('authenticate', { token: 'YOUR_TOKEN' });

// Execute tool
socket.emit('tool_execute', {
  token: 'YOUR_TOKEN',
  tool: 'wikipedia',
  arguments: {
    action: 'search',
    query: 'Python'
  }
});

// Listen for results
socket.on('tool_result', (data) => {
  console.log('Result:', data);
});
```

## Adding Custom Tools

1. **Create tool implementation** in `tools/impl/`:

```python
from tools.base_mcp_tool import BaseMCPTool

class MyCustomTool(BaseMCPTool):
    def __init__(self, config):
        super().__init__(config)
    
    def execute(self, arguments):
        # Tool logic here
        return result
    
    def get_input_schema(self):
        return {
            "type": "object",
            "properties": {
                # Define parameters
            }
        }
```

2. **Create configuration** in `config/tools/my_tool.json`:

```json
{
  "name": "my_tool",
  "type": "custom",
  "implementation": "tools.impl.my_custom_tool.MyCustomTool",
  "description": "My custom tool",
  "enabled": true,
  "inputSchema": {
    // Schema definition
  }
}
```

The tool will be automatically loaded and available.

## Web Interface

Access the web interface at `http://localhost:8000`

### Features:
- **Dashboard**: Overview of available tools and system status
- **Tools**: Browse and execute tools
- **Monitoring**: Real-time metrics and performance graphs
- **Admin Panel**: User and tool management (admin only)

## Project Structure

```
sajhamcpserver/
├── run_server.py           # Main entry point
├── requirements.txt        # Python dependencies
├── core/                   # Core modules
│   ├── properties_configurator.py
│   ├── auth_manager.py
│   └── mcp_handler.py
├── tools/                  # Tools module
│   ├── base_mcp_tool.py
│   ├── tools_registry.py
│   └── impl/              # Tool implementations
│       ├── wikipedia_tool.py
│       ├── yahoo_finance_tool.py
│       ├── google_search_tool.py
│       └── fed_reserve_tool.py
├── web/                    # Web interface
│   ├── app.py             # Flask application
│   ├── templates/         # HTML templates
│   └── static/           # CSS, JS, images
├── config/                # Configuration files
│   ├── server.properties
│   ├── application.properties
│   ├── users.json
│   └── tools/            # Tool configurations
└── logs/                  # Log files
```

## Performance

- Supports 100+ concurrent users
- 200+ concurrent WebSocket connections
- 1000+ requests per second
- Sub-200ms response time (p95)

## Security

- Session-based authentication
- Bearer token for API access
- Rate limiting
- Input validation
- Audit logging
- CORS support

## Monitoring

The server provides real-time monitoring of:
- Tool execution metrics
- User activity
- System performance
- Error rates
- Response times

## Troubleshooting

### Port Already in Use
```bash
# Change port in config/server.properties
server.port=8001
```

### Tools Not Loading
- Check `config/tools/` directory for JSON files
- Verify JSON syntax is valid
- Check logs in `logs/server.log`

### Authentication Issues
- Verify user exists in `config/users.json`
- Check if user is enabled
- Verify password is correct

## Development

### Running Tests
```bash
pytest tests/
```

### Debug Mode
```bash
# Set in config/server.properties
server.debug=true
```

## Production Deployment

1. **Use a reverse proxy** (Nginx/Apache)
2. **Enable HTTPS**
3. **Set strong passwords**
4. **Configure firewall rules**
5. **Set up log rotation**
6. **Use a process manager** (systemd/supervisor)

### Example Nginx Configuration

```nginx
server {
    listen 443 ssl;
    server_name mcp.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## API Documentation

Full API documentation is available at:
- Swagger UI: `http://localhost:8000/api/docs`
- MCP Protocol Spec: https://modelcontextprotocol.io

## Support

For issues, questions, or contributions:
- Email: ajsinha@gmail.com
- GitHub Issues: [Create an issue]

## License

Copyright All rights Reserved 2025-2030, Ashutosh Sinha

## Changelog

### Version 2.1.0 (2026-01)
- Professional UI redesign with modern theme
- Reorganized template structure for better maintainability
- Added comprehensive Help documentation
- Added About page with capabilities overview
- Template subfolders: auth, dashboard, tools, prompts, admin, monitoring, help, common
- Help and About accessible without authentication
- Enhanced card-driven layouts throughout

### Version 1.0.0 (2025-10-26)
- Initial release
- Full MCP protocol implementation
- Built-in tools: Wikipedia, Yahoo Finance, Google Search, Fed Reserve
- Web interface with monitoring
- WebSocket support
- RBAC implementation

## Acknowledgments

- Model Context Protocol specification
- Flask and Flask-SocketIO communities
- Bootstrap for UI components

---

**SAJHA MCP Server** - A robust, scalable, and secure MCP implementation.
