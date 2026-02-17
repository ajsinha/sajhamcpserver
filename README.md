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
- ✅ 40+ Built-in tools: Financial, Search, Government APIs, Analytics
- ✅ Properties-based configuration with auto-reload
- ✅ Comprehensive audit logging
- ✅ **MCP Studio** (v2.4.0): Visual Tool Creation Platform
  - Python Code Tool Creator with @sajhamcptool decorator
  - **REST Service Tool Creator** - Wrap any REST API as MCP tool
    - Supports JSON, CSV, XML, and plain text response formats
    - CSV parsing with configurable delimiter, header, and skip rows
  - **Database Query Tool Creator** - Create SQL-based MCP tools
    - Supports DuckDB, SQLite, PostgreSQL, MySQL
    - Parameterized queries with auto-generated schemas
  - JSON Schema guided form interface
  - Multiple authentication options (API Key, Basic Auth)
  - Live preview and one-click deployment
- ✅ API Key Authentication with tool-level permissions
- ✅ Hot-reload for config changes (zero downtime)
- ✅ Multi-encoding support for international APIs (Japanese, Chinese, European)
- ✅ **Dark Theme Support** (v2.4.0): Comprehensive light/dark mode toggle
  - 3,200+ lines of CSS for complete accessibility
  - Full text visibility across all pages
  - Persistent preference via localStorage

## Requirements

- Python 3.10 or higher
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

The server will start on `http://localhost:3002` by default.

## Default Login

- **Username:** admin
- **Password:** admin123

⚠️ **Important:** Change the default password immediately after first login!

## Configuration

### Server Configuration (`config/server.properties`)

```properties
server.host=0.0.0.0
server.port=3002
server.debug=false
server.version=2.3.1
session.timeout.minutes=60
```

### Application Configuration (`config/application.properties`)

```properties
app.name=SAJHA MCP Server
app.version=2.3.1
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

## Built-in Tools (40+)

### Financial Data Tools
- **Yahoo Finance**: Real-time stock quotes, historical data, symbol search
- **Federal Reserve (FRED)**: Economic indicators, interest rates, GDP
- **Bank of Canada**: Policy rates, exchange rates, bond yields
- **European Central Bank**: Interest rates, inflation, exchange rates
- **Bank of Japan**: Policy rates, JGB yields, money supply (via FRED)
- **People's Bank of China**: LPR, CGB yields, exchange rates (via FRED)
- **Reserve Bank of India**: Repo rates, G-Sec yields, forex reserves
- **Banque de France**: OAT yields, Eurozone indicators
- **IMF**: World Economic Outlook, Balance of Payments, country data
- **World Bank**: Development indicators, country comparisons

### Search & Information Tools
- **Google Search**: Web search using Custom Search API
- **Tavily Search**: AI-optimized web, news, and research search
- **Wikipedia**: Article search, page content, summaries
- **Web Crawler**: URL crawling, sitemap parsing, content extraction

### Government & International Tools
- **FBI**: Crime statistics, agency data, state comparisons
- **United Nations**: SDG data, trade statistics
- **SEC EDGAR**: Company filings, financial data, insider trading

### Analytics Tools
- **DuckDB**: OLAP queries, table management, aggregations
- **SQL Select**: Query CSV files with SQL
- **MS Document Search**: Word and Excel document processing

## MCP Studio (v2.3.0) - Visual Tool Creation Platform

MCP Studio is a comprehensive visual tool creation platform that allows administrators to create custom MCP tools without manual coding.

### Two Creation Methods

#### 1. Python Code Tool Creator
Write Python functions with the `@sajhamcptool` decorator:

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

#### 2. REST Service Tool Creator (NEW in v2.3.0)
Wrap any REST API endpoint as an MCP tool:

- **Supported Methods**: GET, POST, PUT, DELETE, PATCH
- **Authentication**: API Key or Basic Auth
- **Custom Headers**: Add any HTTP headers
- **JSON Schema**: Define request/response schemas
- **Path Parameters**: Support for URL path variables

**Example - Creating a Weather API Tool:**
1. Navigate to Admin → MCP Studio → REST Service Tool Creator
2. Enter tool name: `get_weather`
3. Set endpoint: `https://api.open-meteo.com/v1/forecast`
4. Choose method: GET
5. Define request schema with latitude/longitude parameters
6. Click Deploy - tool is immediately available!

### Access MCP Studio

Navigate to **Admin → MCP Studio** in the web interface (admin access required).

## API Usage

### Authentication

```bash
curl -X POST http://localhost:3002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"user_id": "admin", "password": "admin123"}'
```

### MCP Protocol

```bash
curl -X POST http://localhost:3002/api/mcp \
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
curl -X POST http://localhost:3002/api/tools/execute \
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
const socket = io('http://localhost:3002');

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

### Method 1: MCP Studio (Recommended)
Use the visual tool creator - no manual file editing required!

### Method 2: Manual Creation

1. **Create tool implementation** in `sajha/tools/impl/`:

```python
from sajha.tools.base_mcp_tool import BaseMCPTool

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
  "implementation": "sajha.tools.impl.my_custom_tool.MyCustomTool",
  "description": "My custom tool",
  "enabled": true,
  "version": "2.3.0"
}
```

The tool will be automatically loaded via hot-reload.

## Web Interface

Access the web interface at `http://localhost:3002`

### Features:
- **Dashboard**: Overview of available tools and system status
- **Tools**: Browse and execute tools with input forms
- **Monitoring**: Real-time metrics and performance graphs
- **Admin Panel**: User, tool, and API key management
- **MCP Studio**: Visual tool creation platform
- **Help & Documentation**: Built-in user guides and glossary
- **Theme Switcher**: Toggle between light and dark themes (preference persisted)

## Project Structure

```
sajhamcpserver/
├── run_server.py           # Main entry point
├── requirements.txt        # Python dependencies
├── sajha/                  # Main package
│   ├── core/              # Core modules
│   │   ├── auth_manager.py
│   │   ├── mcp_handler.py
│   │   └── hot_reload_manager.py
│   ├── tools/             # Tools framework
│   │   ├── base_mcp_tool.py
│   │   ├── tools_registry.py
│   │   ├── http_utils.py
│   │   └── impl/          # Tool implementations (25+ files)
│   ├── studio/            # MCP Studio
│   │   ├── decorator.py
│   │   ├── code_analyzer.py
│   │   ├── code_generator.py
│   │   └── rest_tool_generator.py  # NEW
│   └── web/               # Web interface
│       ├── routes/        # Route modules
│       └── templates/     # HTML templates (30+ files)
├── config/                # Configuration
│   ├── server.properties
│   ├── users.json
│   ├── apikeys.json
│   └── tools/            # Tool configurations (170+ files)
├── docs/                  # Documentation
│   ├── architecture/     # Architecture docs
│   └── userguides/       # User guides (25+ files)
└── logs/                  # Log files
```

## Performance

- Supports 100+ concurrent users
- 200+ concurrent WebSocket connections
- 1000+ requests per second
- Sub-200ms response time (p95)

## Security

- Session-based authentication with secure cookies
- Bearer token for API access
- API Key authentication with tool-level permissions
- Rate limiting (100 requests/minute default)
- Input validation via JSON Schema
- Comprehensive audit logging
- CORS support with configurable origins
- CSRF protection

## Monitoring

The server provides real-time monitoring of:
- Tool execution metrics (count, success rate, latency)
- User activity and sessions
- System performance (CPU, memory)
- Error rates and stack traces
- Response time percentiles

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
        proxy_pass http://127.0.0.1:3002;
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
- Help Pages: `http://localhost:3002/help`
- MCP Protocol Spec: https://modelcontextprotocol.io

## Support

For issues, questions, or contributions:
- Email: ajsinha@gmail.com

## License

Copyright All rights Reserved 2025-2030, Ashutosh Sinha

## Changelog

### Version 2.4.0 (February 2026)
- **Comprehensive Dark Theme**: 3,200+ lines of CSS for complete dark mode support
  - Full text visibility across all pages (Dashboard, Help, About, MCP Studio, Tools, Documentation)
  - Table row visibility fixes for all striped and hover tables
  - Alert boxes, cards, forms, modals all properly themed
  - MCP Studio pages (Python, REST, DB Query) fully dark-mode compatible
- **Navbar User Context Fix**: MCP Studio menu now persists across all studio pages
- **Enhanced Accessibility**: Improved contrast and readability in dark mode

### Version 2.3.2 (February 2026)
- **DB Query Tool Creator**: Create MCP tools from SQL queries
  - Support for DuckDB, SQLite, PostgreSQL, MySQL
  - Parameterized queries with auto-generated schemas
- **REST CSV Response Support**: Handle CSV data from REST APIs
- **Theme Switcher**: Light/dark mode toggle in navbar

### Version 2.3.0 (February 2026)
- **MCP Studio Enhancement**: REST Service Tool Creator
  - Wrap any REST API as MCP tool via visual interface
  - Supports GET, POST, PUT, DELETE, PATCH methods
  - API Key and Basic Authentication support
  - Custom HTTP headers configuration
  - JSON Schema for request/response validation
  - Path parameter support in URLs
  - Quick examples for Weather, JSONPlaceholder, GitHub APIs
- Reorganized MCP Studio with card-based navigation
- Added Page Glossary to REST Tool Creator
- Updated documentation and architecture guides

### Version 2.2.0 (January 2026)
- MCP Studio: Visual tool creator with @sajhamcptool decorator
- Master Glossary with 169 terms and 52 acronyms
- Page Glossary sections in all templates
- Multi-encoding support for international APIs
- Bank of Japan and People's Bank of China tools via FRED
- Architecture documentation (1,400+ lines)

### Version 2.1.0 (January 2026)
- Professional UI redesign with modern theme
- Reorganized template structure
- Added comprehensive Help documentation
- Added About page with capabilities overview
- API Key management with tool-level permissions

### Version 2.0.0 (December 2025)
- 40+ pre-built tools across financial, search, government domains
- Hot-reload for zero-downtime updates
- Enhanced EDGAR tools for SEC filings
- Investor Relations module

### Version 1.0.0 (October 2025)
- Initial release
- Full MCP protocol implementation
- Built-in tools: Wikipedia, Yahoo Finance, Google Search, Fed Reserve
- Web interface with monitoring
- WebSocket support
- RBAC implementation

## Acknowledgments

- Anthropic for Model Context Protocol specification
- Flask and Flask-SocketIO communities
- Bootstrap for UI components
- Federal Reserve FRED API
- All open data providers

---

**SAJHA MCP Server** - A robust, scalable, and secure MCP implementation for enterprise AI tool integration.
