# MCP Server - Model Context Protocol Server

Sajha in Hindi means shared, that is the core idea be=hind this project i.e. use MCP to share data that can be procured from just about anywhere.

It is a comprehensive Python-based MCP (Model Context Protocol) server implementation with multiple data source integrations and a web-based dashboard.

## © 2025-2030 Ashutosh Sinha

## Features

### Core Functionality
- **Dynamic Tool Registry**: Hot-reload tool configurations without server restart
- **Rate Limiting**: Protect against denial of service attacks
- **Web Dashboard**: Monitor and manage tools through an intuitive interface
- **Authentication**: Role-based access control (admin/user)
- **Properties Management**: Centralized configuration with environment variable support

### Integrated Tools

1. **Google Search MCP Tool**
   - Web search, image search, news search
   - Google Scholar search support
   - Site-specific search capabilities

2. **Tavily MCP Tool**
   - Advanced entity search
   - News aggregation
   - Content extraction from URLs

3. **Yahoo Finance MCP Tool**
   - Real-time stock quotes
   - Historical data
   - Financial statements
   - Options chains
   - Market analysis

4. **SEC MCP Tool**
   - EDGAR database access
   - Company filings retrieval
   - Insider transactions
   - Financial facts from XBRL

5. **Federal Reserve MCP Tool**
   - Economic indicators (GDP, inflation, unemployment)
   - Interest rates
   - Money supply data
   - Treasury yields

6. **Census MCP Tool**
   - Population demographics
   - Economic statistics
   - Housing data
   - Education metrics

7. **Wikipedia MCP Tool**
   - Article search and retrieval
   - Content extraction
   - Category and link analysis

8. **MS Office MCP Tool**
   - Word document processing
   - Excel spreadsheet operations
   - File creation and manipulation

9. **SQL MCP Tool**
   - SQLite database operations
   - Query execution
   - Schema management

10. **DuckDB OLAP MCP Tool**
    - Analytical queries
    - Data aggregation
    - Time series analysis
    - CSV data loading

## Installation

### Prerequisites
- Python 3.8 or higher
- pip package manager

### Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/sajhamcpserver.git
cd sajhamcpserver
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables (optional):
```bash
export GOOGLE_API_KEY="your-google-api-key"
export TAVILY_API_KEY="your-tavily-api-key"
export FRED_API_KEY="your-fred-api-key"
export CENSUS_API_KEY="your-census-api-key"
export SEC_USER_AGENT="YourApp/1.0 (your-email@example.com)"
```

4. Run the server:
```bash
python run_server.py
```

## Configuration

### Application Properties
Edit `config/application.properties` to configure:
- Server host and port
- Tool registry settings
- Database paths
- API keys

### User Configuration
Edit `config/users.json` to manage user accounts:
```json
{
  "users": [
    {
      "id": "admin",
      "password": "admin123",
      "full_name": "Administrator",
      "roles": ["admin", "user"]
    }
  ]
}
```

### Tool Configuration
Each tool has a JSON configuration file in `config/tools/`:
- Define tool methods and parameters
- Set rate limiting rules
- Configure MCP protocol details

## Usage

### Web Dashboard
Access the dashboard at `http://localhost:5000`

Default credentials:
- Admin: `admin` / `admin123`
- User: `user1` / `user123`

### API Endpoints

#### List Tools
```http
GET /api/tools
Authorization: Required
```

#### Call Tool Method
```http
POST /api/tool/<tool_name>/call
Content-Type: application/json
Authorization: Required

{
  "method": "method_name",
  "arguments": {
    "param1": "value1"
  }
}
```

#### Get Tool Statistics
```http
GET /api/tool/<tool_name>/stats
Authorization: Required
```

#### Reload Tool (Admin only)
```http
POST /api/tool/<tool_name>/reload
Authorization: Admin required
```

## Architecture

### Directory Structure
```
sajhamcpserver/
├── core/               # Core utilities
│   ├── core_utils.py
│   └── properties_configurator.py
├── tools/              # MCP tool implementations
│   ├── base_mcp_tool.py
│   ├── tools_registry.py
│   └── [tool implementations]
├── web/                # Flask web application
│   ├── mcp_app.py
│   ├── templates/
│   └── static/
├── config/             # Configuration files
│   ├── application.properties
│   ├── users.json
│   └── tools/         # Tool configurations
├── data/               # Data storage
│   ├── sample.db
│   ├── olap.duckdb
│   └── office_files/
├── logs/               # Application logs
├── run_server.py       # Main entry point
├── requirements.txt    # Python dependencies
└── README.md          # This file
```

### Key Components

1. **PropertiesConfigurator**: Manages application configuration with property resolution and auto-reload
2. **ToolsRegistry**: Singleton registry for tool management with hot-reload capability
3. **BaseMCPTool**: Abstract base class for all MCP tools
4. **Flask Application**: Web interface and REST API

## Development

### Adding a New Tool

1. Create a new tool class inheriting from `BaseMCPTool`:
```python
from tools.base_mcp_tool import BaseMCPTool

class MyNewTool(BaseMCPTool):
    def handle_tool_call(self, tool_name, arguments):
        # Implementation
        pass
```

2. Create a configuration file in `config/tools/`:
```json
{
  "name": "my_new_tool",
  "module": "tools.my_new_tool.MyNewTool",
  "max_hits": 1000,
  "max_hit_interval": 10,
  "tool_description": {
    "tools": [...]
  }
}
```

3. The tool will be automatically loaded by the registry.

### Testing

Run the test suite:
```bash
python -m pytest tests/
```

## Security Considerations

- Always change default passwords in production
- Use HTTPS in production environments
- Set proper API rate limits
- Keep API keys secure and never commit them to version control
- Regularly update dependencies

## Troubleshooting

### Common Issues

1. **Tool fails to load**
   - Check the configuration file syntax
   - Verify module path is correct
   - Check logs for import errors

2. **Rate limit errors**
   - Adjust `max_hits` and `max_hit_interval` in tool configuration
   - Monitor tool statistics via dashboard

3. **Database connection errors**
   - Verify database file paths
   - Check file permissions
   - Ensure data directories exist

## Support

For issues, questions, or contributions, please contact:
- Email: ajsinha@gmail.com
- GitHub: https://github.com/ajsinha/sajhamcpserver

## License

© 2025-2030 Ashutosh Sinha. All rights reserved.

This software is proprietary and confidential. Unauthorized copying, distribution, or use is strictly prohibited.