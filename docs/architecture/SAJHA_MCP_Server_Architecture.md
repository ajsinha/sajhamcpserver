# SAJHA MCP Server - System Architecture Document

**Version:** 2.4.0  
**Last Updated:** February 2026  
**Classification:** Technical Reference

---

## Legal Notice

**Copyright © 2025-2030, All Rights Reserved**  
**Ashutosh Sinha**  
**Email:** ajsinha@gmail.com

This document and the associated software architecture are proprietary and confidential. Unauthorized copying, distribution, modification, or use of this document or the software system it describes is strictly prohibited without explicit written permission from the copyright holder. This document is provided "as is" without warranty of any kind, either expressed or implied. The copyright holder shall not be liable for any damages arising from the use of this document or the software system it describes.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Overview](#2-system-overview)
3. [High-Level Architecture](#3-high-level-architecture)
4. [Package Structure](#4-package-structure)
5. [Core Components](#5-core-components)
6. [Tools Framework](#6-tools-framework)
7. [Web Application Layer](#7-web-application-layer)
8. [MCP Studio](#8-mcp-studio)
9. [Investor Relations Module](#9-investor-relations-module)
10. [Configuration System](#10-configuration-system)
11. [Security Architecture](#11-security-architecture)
12. [Data Flow Diagrams](#12-data-flow-diagrams)
13. [API Architecture](#13-api-architecture)
14. [Database Layer](#14-database-layer)
15. [Hot-Reload System](#15-hot-reload-system)
16. [Deployment Architecture](#16-deployment-architecture)
17. [Extension Points](#17-extension-points)
18. [Performance Considerations](#18-performance-considerations)
19. [Appendices](#19-appendices)

---

## 1. Executive Summary

SAJHA MCP Server is a production-ready Python-based implementation of the **Model Context Protocol (MCP)**, providing a standardized interface for AI tools and services. The system is designed with enterprise-grade security, scalability, and extensibility in mind.

### Key Characteristics

| Aspect | Description |
|--------|-------------|
| **Protocol** | MCP (Model Context Protocol) with JSON-RPC 2.0 |
| **Transport** | HTTP REST API + WebSocket (Socket.IO) |
| **Framework** | Flask + Flask-SocketIO |
| **Language** | Python 3.10+ |
| **Architecture** | Modular, Plugin-based, Singleton Pattern |
| **Security** | Role-Based Access Control (RBAC) + API Key Management |

### Primary Capabilities

- **40+ Pre-built Tools** - Financial data, search, government APIs, analytics
- **Dynamic Tool Loading** - Hot-reload without server restart
- **MCP Studio** - Visual tool creation with decorator-based approach
- **Prompts Management** - Template-based prompt system with variable substitution
- **Multi-Encoding Support** - International API compatibility (Japanese, Chinese, European)
- **Real-time Monitoring** - WebSocket-based live updates

---

## 2. System Overview

### 2.1 Architecture Philosophy

SAJHA MCP Server follows these architectural principles:

1. **Separation of Concerns** - Clear boundaries between layers
2. **Singleton Pattern** - Single instance for registries and managers
3. **Plugin Architecture** - Tools are self-contained, independently deployable
4. **Configuration-Driven** - Behavior controlled via JSON/Properties files
5. **Hot-Reload** - Runtime reconfiguration without downtime

### 2.2 Technology Stack

```
┌─────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  Web UI     │  │  REST API   │  │  WebSocket (SIO)    │  │
│  │  (Jinja2)   │  │  (Flask)    │  │  (Flask-SocketIO)   │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                    APPLICATION LAYER                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ MCP Handler │  │ Auth Manager│  │  Prompts Registry   │  │
│  │ (JSON-RPC)  │  │ (RBAC)      │  │  (Templates)        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                      TOOLS LAYER                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Tools       │  │ Base MCP    │  │  HTTP Utils         │  │
│  │ Registry    │  │ Tool        │  │  (Encoding)         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                    INFRASTRUCTURE LAYER                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ DB Pool     │  │ Hot-Reload  │  │  Properties Config  │  │
│  │ Manager     │  │ Manager     │  │  (server.properties)│  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. High-Level Architecture

### 3.1 Component Interaction Diagram

```
                                   ┌──────────────────┐
                                   │   AI Client      │
                                   │ (Claude, GPT, etc)│
                                   └────────┬─────────┘
                                            │
                           ┌────────────────┴────────────────┐
                           │                                  │
                    ┌──────▼──────┐                   ┌──────▼──────┐
                    │  HTTP/REST  │                   │  WebSocket  │
                    │   Endpoint  │                   │   (SIO)     │
                    └──────┬──────┘                   └──────┬──────┘
                           │                                  │
                           └────────────────┬─────────────────┘
                                            │
                                   ┌────────▼────────┐
                                   │   MCP Handler   │
                                   │  (JSON-RPC 2.0) │
                                   └────────┬────────┘
                                            │
                    ┌───────────────────────┼───────────────────────┐
                    │                       │                       │
           ┌────────▼────────┐    ┌─────────▼─────────┐   ┌────────▼────────┐
           │  Auth Manager   │    │  Tools Registry   │   │ Prompts Registry│
           │  (RBAC + Keys)  │    │   (Singleton)     │   │   (Templates)   │
           └────────┬────────┘    └─────────┬─────────┘   └─────────────────┘
                    │                       │
                    │              ┌────────┴────────┐
                    │              │                 │
           ┌────────▼────────┐   ┌─▼───┐  ┌────┐  ┌─▼───┐
           │  API Key Manager│   │Tool1│  │ .. │  │ToolN│
           └─────────────────┘   └─────┘  └────┘  └─────┘
```

### 3.2 Request Processing Flow

1. **Request Arrival** - HTTP/WebSocket request received
2. **Authentication** - Token/API key validation via AuthManager
3. **Authorization** - RBAC check for resource access
4. **Routing** - MCP Handler dispatches to appropriate handler
5. **Tool Execution** - ToolsRegistry locates and executes tool
6. **Response Formation** - JSON-RPC 2.0 response constructed
7. **Delivery** - Response sent via same transport

---

## 4. Package Structure

### 4.1 Directory Layout

```
sajhamcpserver/
├── config/                      # Configuration files
│   ├── apikeys.json            # API key storage
│   ├── application.properties   # Application settings
│   ├── server.properties       # Server configuration
│   ├── users.json              # User credentials & roles
│   ├── tools/                  # Tool JSON configurations (40+ files)
│   ├── prompts/                # Prompt template definitions
│   ├── ir/                     # Investor Relations configurations
│   └── literature/             # Static content configurations
│
├── data/                        # Data storage
│   ├── duckdb/                 # DuckDB database files
│   ├── msdocs/                 # Microsoft document storage
│   └── sqlselect/              # SQL data files (CSV)
│
├── docs/                        # Documentation
│   ├── architecture/           # Architecture documents
│   ├── userguides/             # Tool reference guides (25+ files)
│   └── requirements/           # Requirements specifications
│
├── logs/                        # Log files
│   └── server.log              # Main server log
│
├── sajha/                       # Main package
│   ├── __init__.py             # Package initialization
│   ├── apiclient/              # External API clients
│   ├── core/                   # Core system components
│   ├── examples/               # Example client implementations
│   ├── ir/                     # Investor Relations module
│   ├── studio/                 # MCP Studio (visual tool creator)
│   ├── tools/                  # Tools framework
│   └── web/                    # Web application
│
├── test/                        # Test suite
│   └── test_*.py               # Unit tests for each tool
│
├── run_server.py               # Server entry point
├── verify_installation.py      # Installation verification
└── requirements.txt            # Python dependencies
```

### 4.2 Package Dependencies

```
sajha/
├── core/           → (standalone, foundation layer)
├── tools/          → depends on core/
├── web/            → depends on core/, tools/
├── studio/         → depends on core/, tools/
├── ir/             → depends on tools/
├── apiclient/      → depends on core/
└── examples/       → depends on apiclient/
```

---

## 5. Core Components

### 5.1 Component Overview

The `sajha/core/` package contains foundational system components:

| Component | File | Purpose |
|-----------|------|---------|
| **AuthManager** | `auth_manager.py` | User authentication, session management, RBAC |
| **APIKeyManager** | `apikey_manager.py` | API key storage, validation, access control |
| **MCPHandler** | `mcp_handler.py` | JSON-RPC 2.0 protocol handling |
| **PromptsRegistry** | `prompts_registry.py` | Prompt template management |
| **PropertiesConfigurator** | `properties_configurator.py` | Server configuration |
| **HotReloadManager** | `hot_reload_manager.py` | Runtime configuration reloading |
| **ToolGroupsManager** | `tool_groups_manager.py` | Tool categorization |
| **DBConnectionPool** | `db/db_connection_pool.py` | Database connection pooling |

### 5.2 AuthManager

The AuthManager handles all authentication and authorization operations.

```python
class AuthManager:
    """
    Manages user authentication and authorization
    
    Features:
    - Username/password authentication
    - Session token management
    - Role-based access control (RBAC)
    - Tool-level permissions
    - API key integration
    """
```

**Authentication Flow:**

```
User Login Request
        │
        ▼
┌───────────────────┐
│ Validate Credentials │
│ (users.json)      │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Generate Session  │
│ Token (UUID)      │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Store Session     │
│ (In-memory cache) │
└─────────┬─────────┘
          │
          ▼
    Return Token
```

**RBAC Structure:**

```json
{
  "users": {
    "admin": {
      "password": "hashed_password",
      "role": "admin",
      "tools": ["*"],
      "enabled": true
    },
    "analyst": {
      "password": "hashed_password", 
      "role": "user",
      "tools": ["wikipedia", "yahoo_finance", "world_bank"],
      "enabled": true
    }
  }
}
```

### 5.3 MCPHandler

The MCPHandler implements the JSON-RPC 2.0 protocol for MCP communication.

**Supported Methods:**

| Method | Description |
|--------|-------------|
| `initialize` | Client initialization handshake |
| `initialized` | Initialization confirmation |
| `tools/list` | List available tools |
| `tools/call` | Execute a tool |
| `tool/schema` | Get tool schema |
| `tool/input_schema` | Get input schema |
| `tool/output_schema` | Get output schema |
| `prompts/list` | List available prompts |
| `prompts/get` | Get rendered prompt |
| `ping` | Health check |

**JSON-RPC 2.0 Response Format:**

```json
{
  "jsonrpc": "2.0",
  "id": "request-123",
  "result": {
    "content": [
      {"type": "text", "text": "Tool output here"}
    ]
  }
}
```

### 5.4 PropertiesConfigurator

Manages server configuration via Java-style properties files.

**Configuration Hierarchy:**

```
1. server.properties       (Primary configuration)
2. application.properties  (Application-level settings)
3. Environment Variables   (Runtime overrides)
4. Command-line Arguments  (Highest priority)
```

**Key Configuration Properties:**

```properties
# Server settings
server.host=0.0.0.0
server.port=5000
server.version=2.2.0

# Session management
session.lifetime.seconds=3600

# Hot-reload settings
config.reload.interval.seconds=300

# Logging
logging.level=INFO
logging.file=logs/server.log
```

### 5.5 HotReloadManager

Enables runtime configuration updates without server restart.

**Monitored Components:**

- User credentials (`users.json`)
- API keys (`apikeys.json`)
- Tool configurations (`config/tools/*.json`)
- Prompt templates (`config/prompts/*.json`)
- Python tool modules (`sajha/tools/impl/*.py`)

**Reload Mechanism:**

```
┌─────────────────┐
│ File Watcher    │ ──── Monitors file timestamps
└────────┬────────┘
         │ Change detected
         ▼
┌─────────────────┐
│ Load New Config │ ──── Parse updated file
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Validate Config │ ──── Syntax & schema validation
└────────┬────────┘
         │ Valid
         ▼
┌─────────────────┐
│ Apply Changes   │ ──── Update registry/manager
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Log & Notify    │ ──── WebSocket notification
└─────────────────┘
```

---

## 6. Tools Framework

### 6.1 Framework Overview

The tools framework (`sajha/tools/`) provides the foundation for all MCP tools.

**Components:**

| Component | File | Purpose |
|-----------|------|---------|
| **BaseMCPTool** | `base_mcp_tool.py` | Abstract base class for all tools |
| **ToolsRegistry** | `tools_registry.py` | Singleton tool registration and discovery |
| **HTTPUtils** | `http_utils.py` | Multi-encoding HTTP utilities |
| **Tool Implementations** | `impl/*.py` | Concrete tool classes |

### 6.2 BaseMCPTool

All tools inherit from `BaseMCPTool`, which provides:

```python
class BaseMCPTool(ABC):
    """
    Abstract base class for MCP tools
    
    Properties:
    - name: Tool identifier
    - description: Human-readable description
    - version: Semantic version
    - enabled: Active status
    - input_schema: JSON Schema for inputs
    - output_schema: JSON Schema for outputs
    
    Abstract Methods:
    - execute(arguments) -> Any
    - get_input_schema() -> Dict
    - get_output_schema() -> Dict
    
    Provided Methods:
    - validate_arguments()
    - execute_with_tracking()
    - get_metrics()
    - to_mcp_format()
    """
```

**Tool Lifecycle:**

```
1. Configuration Load    ─→ JSON file parsed
2. Class Import         ─→ Python module loaded
3. Instantiation        ─→ __init__ called with config
4. Registration         ─→ Added to ToolsRegistry
5. Execution            ─→ execute() called per request
6. Metrics Collection   ─→ Performance tracking
7. Unregistration       ─→ Hot-reload or shutdown
```

### 6.3 ToolsRegistry

Singleton pattern implementation for tool management.

```python
class ToolsRegistry:
    """
    Singleton registry for MCP tools
    
    Features:
    - Thread-safe registration
    - Dynamic loading from JSON configs
    - File monitoring for hot-reload
    - Module reloading support
    - Error tracking per tool
    """
    
    _instance = None
    _lock = threading.Lock()
```

**Registration Flow:**

```
config/tools/*.json
        │
        ▼
┌───────────────────┐
│ Scan JSON Files   │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Parse Config      │ ──── name, implementation, metadata
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Import Module     │ ──── importlib.import_module()
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Instantiate Class │ ──── ToolClass(config)
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Register Tool     │ ──── tools[name] = instance
└─────────────────────┘
```

### 6.4 Tool Configuration Schema

Each tool is configured via a JSON file:

```json
{
  "name": "wikipedia_search",
  "implementation": "sajha.tools.impl.wikipedia_tool.WikipediaTool",
  "description": "Search Wikipedia for information on any topic",
  "version": "2.3.0",
  "enabled": true,
  "metadata": {
    "author": "Ashutosh Sinha",
    "category": "Search",
    "tags": ["wikipedia", "encyclopedia", "search"],
    "rateLimit": 60,
    "cacheTTL": 3600,
    "requiresApiKey": false
  }
}
```

### 6.5 HTTP Utilities

The `http_utils.py` module provides multi-encoding support for international APIs:

**Encoding Constants:**

```python
ENCODINGS_DEFAULT = ['utf-8', 'latin-1', 'iso-8859-1']
ENCODINGS_JAPANESE = ['utf-8', 'shift_jis', 'euc-jp', 'cp932', 'iso-2022-jp']
ENCODINGS_CHINESE = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5']
ENCODINGS_KOREAN = ['utf-8', 'euc-kr', 'cp949', 'iso-2022-kr']
ENCODINGS_EUROPEAN = ['utf-8', 'latin-1', 'iso-8859-1', 'iso-8859-15', 'cp1252']
ENCODINGS_ALL = [...all combined...]
```

**Key Functions:**

```python
def safe_json_response(response, encodings) -> Dict:
    """Decompress, decode, and parse JSON with encoding fallback"""

def safe_decode_response(response, encodings) -> str:
    """Decompress and decode with encoding fallback"""

def decompress_response(data, encoding) -> bytes:
    """Handle gzip/deflate compression"""
```

### 6.6 Implemented Tools

The server includes 40+ pre-built tools organized by category:

**Financial Data:**
- Yahoo Finance (quotes, history, options)
- Federal Reserve (FRED API)
- Bank of Canada, ECB, BoJ, PBoC, RBI, Banque de France
- IMF, World Bank
- SEC EDGAR (filings, companies)

**Search & Information:**
- Google Search (Custom Search API)
- Tavily Search (AI-optimized)
- Wikipedia
- Web Crawler

**Government & International:**
- FBI (crime statistics)
- United Nations (data, treaties)

**Data & Analytics:**
- DuckDB (OLAP analytics)
- SQL Select (CSV querying)
- MS Document Search

**Specialized:**
- Investor Relations (company IR pages)
- Enhanced EDGAR (advanced SEC analysis)

---

## 7. Web Application Layer

### 7.1 Flask Application Structure

The web layer (`sajha/web/`) provides the user interface and API endpoints.

**Main Application Class:**

```python
class SajhaMCPServerWebApp:
    """
    Main Flask application class
    
    Attributes:
    - app: Flask instance
    - socketio: Flask-SocketIO instance
    - auth_manager: AuthManager
    - tools_registry: ToolsRegistry
    - prompts_registry: PromptsRegistry
    - mcp_handler: MCPHandler
    - config_reloader: HotReloadManager
    """
```

### 7.2 Route Modules

Routes are organized into separate modules:

| Module | File | Endpoints |
|--------|------|-----------|
| **AuthRoutes** | `auth_routes.py` | `/login`, `/logout`, `/register` |
| **DashboardRoutes** | `dashboard_routes.py` | `/`, `/dashboard` |
| **ToolsRoutes** | `tools_routes.py` | `/tools/*` |
| **AdminRoutes** | `admin_routes.py` | `/admin/*` |
| **MonitoringRoutes** | `monitoring_routes.py` | `/monitoring/*` |
| **ApiRoutes** | `api_routes.py` | `/api/*` |
| **PromptsRoutes** | `prompts_routes.py` | `/prompts/*` |
| **HelpRoutes** | `help_routes.py` | `/help`, `/about` |
| **DocsRoutes** | `docs_routes.py` | `/docs/*` |
| **APIKeysRoutes** | `apikeys_routes.py` | `/apikeys/*` |
| **StudioRoutes** | `studio_routes.py` | `/studio/*` |

### 7.3 Template Structure

Templates use Jinja2 with Bootstrap 5:

```
templates/
├── common/
│   ├── base.html          # Base template with navbar/footer
│   ├── error.html         # Error page template
│   └── navbar.html        # Navigation component
├── admin/
│   ├── admin.html         # Admin dashboard
│   ├── users.html         # User management
│   └── studio/            # MCP Studio templates
├── auth/
│   ├── login.html         # Login form
│   └── register.html      # Registration form
├── dashboard/
│   └── dashboard.html     # Main dashboard
├── help/
│   ├── about.html         # About page
│   ├── help.html          # Help/documentation
│   ├── docs_list.html     # Documentation index
│   └── docs_view.html     # Markdown viewer
├── monitoring/
│   └── monitoring.html    # System monitoring
├── prompts/
│   └── prompts.html       # Prompts management
└── tools/
    ├── tools.html         # Tools listing
    └── tool_detail.html   # Tool details/execution
```

### 7.4 WebSocket Integration

Flask-SocketIO enables real-time communication:

**Event Handlers:**

```python
class SocketIOHandlers:
    """
    WebSocket event handlers
    
    Events:
    - connect: Client connection
    - disconnect: Client disconnection
    - mcp_request: MCP protocol message
    - tool_execute: Tool execution request
    - subscribe_monitoring: Subscribe to metrics
    """
```

**Real-time Features:**
- Live tool execution status
- Monitoring dashboard updates
- Hot-reload notifications
- Error alerts

---

## 8. MCP Studio

### 8.1 Overview

MCP Studio (`sajha/studio/`) provides a visual interface for creating MCP tools without manual coding. Version 2.4.0 introduces comprehensive dark theme support with 3,200+ lines of CSS for accessibility across all pages, plus Database Query Tool Creator and enhanced REST Service Tool Creator with CSV response support.

**Components:**

| Component | File | Purpose |
|-----------|------|---------|
| **Decorator** | `decorator.py` | `@sajhamcptool` decorator definition |
| **CodeAnalyzer** | `code_analyzer.py` | AST-based code analysis |
| **CodeGenerator** | `code_generator.py` | Tool class generation |
| **RESTToolGenerator** | `rest_tool_generator.py` | REST API tool generation (v2.4.0) |
| **DBQueryToolGenerator** | `dbquery_tool_generator.py` | Database query tool generation (v2.4.0) |

### 8.2 Tool Creation Methods

MCP Studio supports three methods for creating tools:

```
                        MCP Studio
                            │
            ┌───────────────┼───────────────┐
            │               │               │
    ┌───────▼───────┐ ┌─────▼─────┐ ┌───────▼───────┐
    │ Python Code   │ │ REST      │ │ DB Query      │
    │ Tool Creator  │ │ Service   │ │ Tool Creator  │
    └───────┬───────┘ └─────┬─────┘ └───────┬───────┘
            │               │               │
    ┌───────▼───────┐ ┌─────▼─────┐ ┌───────▼───────┐
    │ @sajhamcptool │ │ REST      │ │ DBQuery       │
    │ Decorator     │ │ Definition│ │ Definition    │
    └───────┬───────┘ └─────┬─────┘ └───────┬───────┘
            │               │               │
    ┌───────▼───────┐ ┌─────▼─────┐ ┌───────▼───────┐
    │ CodeAnalyzer  │ │ REST Tool │ │ DBQuery Tool  │
    │ (AST Parsing) │ │ Generator │ │ Generator     │
    └───────┬───────┘ └─────┬─────┘ └───────┬───────┘
            │               │               │
            └───────────────┼───────────────┘
                            │
                    ┌───────▼───────┐
                    │ Tool Files    │
                    │ JSON + Python │
                    └───────┬───────┘
                            │
                    ┌───────▼───────┐
                    │ Hot-Reload    │
                    │ & Register    │
                    └───────────────┘
```

### 8.3 The @sajhamcptool Decorator

```python
from sajha.studio import sajhamcptool

@sajhamcptool(
    name="temperature_converter",
    description="Convert temperatures between units",
    version="1.0.0",
    category="Utilities"
)
def convert_temperature(
    value: float,
    from_unit: str = "celsius",
    to_unit: str = "fahrenheit"
) -> dict:
    """Convert temperature between Celsius, Fahrenheit, and Kelvin."""
    # Implementation here
    return {"result": converted_value}
```

### 8.4 REST Service Tool Creator (v2.3.0)

The REST Service Tool Creator allows wrapping any REST API as an MCP tool through a visual interface.

**RESTToolDefinition Data Class:**

```python
@dataclass
class RESTToolDefinition:
    name: str                    # Tool name (lowercase_snake_case)
    endpoint: str               # REST API URL
    method: str                 # GET, POST, PUT, DELETE, PATCH
    description: str            # Tool description
    request_schema: Dict        # JSON Schema for request body
    response_schema: Dict       # JSON Schema for response
    category: str = "REST API"  # Tool category
    tags: List[str] = []        # Tags for categorization
    api_key: str = None         # Optional API key
    api_key_header: str = "X-API-Key"  # API key header name
    basic_auth_username: str = None    # Basic auth username
    basic_auth_password: str = None    # Basic auth password
    headers: Dict[str, str] = {}       # Custom HTTP headers
    timeout: int = 30           # Request timeout in seconds
    content_type: str = "application/json"  # Content-Type header
```

**REST Tool Generation Flow:**

```
REST Tool Creator UI
        │
        ▼
┌───────────────────┐
│ Collect Inputs    │ ──── name, endpoint, method, schemas
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Create Definition │ ──── RESTToolDefinition dataclass
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Validate          │ ──── URL, method, schema syntax
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Generate JSON     │ ──── Tool configuration
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Generate Python   │ ──── Tool implementation class
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Save & Register   │ ──── Write files, reload registry
└─────────────────────┘
```

**Generated REST Tool Features:**

- HTTP method support (GET, POST, PUT, DELETE, PATCH)
- Path parameter substitution (`/users/{user_id}`)
- Query parameter handling for GET requests
- Request body serialization for POST/PUT/PATCH
- Response parsing with encoding fallback
- Error handling with descriptive messages
- Configurable timeout
- Authentication (API Key or Basic Auth)
- Custom HTTP headers

**Example REST Tool Definition:**

```python
definition = RESTToolDefinition(
    name="get_github_user",
    endpoint="https://api.github.com/users/{username}",
    method="GET",
    description="Get public information about a GitHub user",
    request_schema={
        "type": "object",
        "properties": {
            "username": {"type": "string", "description": "GitHub username"}
        },
        "required": ["username"]
    },
    response_schema={
        "type": "object",
        "properties": {
            "login": {"type": "string"},
            "name": {"type": "string"},
            "public_repos": {"type": "integer"}
        }
    },
    category="Developer Tools",
    tags=["github", "users", "api"]
)
```

### 8.5 Code Analysis Pipeline

```
Decorated Function
        │
        ▼
┌───────────────────┐
│ AST Parsing       │ ──── Parse source code to AST
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Extract Metadata  │ ──── name, description, version
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Analyze Arguments │ ──── Type hints → JSON Schema
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Extract Docstring │ ──── Extended description
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Generate Schema   │ ──── Input/Output JSON Schema
└─────────────────────┘
```

### 8.6 Code Generation

The CodeGenerator creates:

1. **Tool Class** (`sajha/tools/impl/{name}.py`)
   - Inherits from BaseMCPTool
   - Implements execute(), get_input_schema(), get_output_schema()

2. **JSON Configuration** (`config/tools/{name}.json`)
   - Tool metadata
   - Implementation path
   - Feature flags

**Generated Structure:**

```python
class TemperatureConverterTool(BaseMCPTool):
    def __init__(self, config=None):
        # Auto-generated initialization
        
    def get_input_schema(self):
        return {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from_unit": {"type": "string", "enum": [...]},
                "to_unit": {"type": "string", "enum": [...]}
            },
            "required": ["value"]
        }
    
    def execute(self, arguments):
        # Calls the original decorated function
        return convert_temperature(**arguments)
```

### 8.7 Web Interface

MCP Studio provides a rich web interface:

**Python Code Tool Creator:**
- Split-pane editor with syntax highlighting
- Real-time code analysis
- Preview generated JSON and Python
- One-click deployment
- Tool name validation

**REST Service Tool Creator:**
- Form-based input collection
- HTTP method selection with visual buttons
- JSON Schema editors for request/response
- Authentication configuration (API Key, Basic Auth)
- Custom headers management
- Quick examples (Weather, JSONPlaceholder, GitHub)
- Preview before deployment

---

## 9. Investor Relations Module

### 9.1 Overview

The IR module (`sajha/ir/`) provides specialized web scraping for company investor relations pages.

**Components:**

| Component | File | Purpose |
|-----------|------|---------|
| **BaseIRWebScraper** | `base_ir_webscraper.py` | Abstract scraper base |
| **CompanyDatabase** | `company_database.py` | Company IR URL mappings |
| **CompanyIRScrapers** | `company_ir_scrapers.py` | Company-specific scrapers |
| **GenericIRScraper** | `generic_ir_scraper.py` | Universal IR page scraper |
| **EnhancedBaseScraper** | `enhanced_base_scraper.py` | Advanced scraping features |
| **SECEdgar** | `sec_edgar.py` | SEC EDGAR integration |
| **HTTPClient** | `http_client.py` | HTTP request handling |

### 9.2 Scraper Architecture

```
Company Request
        │
        ▼
┌───────────────────┐
│ Company Database  │ ──── Lookup IR URL
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Select Scraper    │ ──── Company-specific or Generic
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Fetch IR Page     │ ──── HTTP request with retries
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Parse HTML        │ ──── BeautifulSoup extraction
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Extract Documents │ ──── PDFs, filings, reports
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Normalize Data    │ ──── Standard output format
└─────────────────────┘
```

### 9.3 SEC EDGAR Integration

Direct integration with SEC EDGAR for:
- Company filings (10-K, 10-Q, 8-K)
- Insider transactions
- Institutional holdings
- Full-text search

---

## 10. Configuration System

### 10.1 Configuration Files

| File | Purpose | Format |
|------|---------|--------|
| `server.properties` | Server settings | Java Properties |
| `application.properties` | App settings | Java Properties |
| `users.json` | User accounts & RBAC | JSON |
| `apikeys.json` | External API keys | JSON |
| `config/tools/*.json` | Tool configurations | JSON |
| `config/prompts/*.json` | Prompt templates | JSON |

### 10.2 Configuration Precedence

```
1. Hardcoded Defaults     (Lowest priority)
2. server.properties
3. application.properties
4. Environment Variables
5. Command-line Arguments (Highest priority)
```

### 10.3 API Keys Management

```json
{
  "google_api_key": "AIza...",
  "google_search_engine_id": "a1b2c3...",
  "tavily_api_key": "tvly-...",
  "fred_api_key": "abc123...",
  "openai_api_key": "sk-..."
}
```

**Key Features:**
- Encrypted storage (optional)
- Runtime reload
- Per-tool key requirements
- Usage tracking

---

## 11. Security Architecture

### 11.1 Authentication Mechanisms

1. **Session-Based (Web UI)**
   - Username/password login
   - Session token in cookie
   - Configurable timeout

2. **API Key (Programmatic)**
   - Bearer token header
   - Key-based access control
   - Rate limiting

### 11.2 Authorization Model

```
┌─────────────────────────────────────────────────┐
│                    RBAC Model                    │
├─────────────────────────────────────────────────┤
│                                                  │
│  User ──has──▶ Role ──grants──▶ Permissions     │
│                                                  │
│  Roles:                                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────────────┐  │
│  │  admin  │  │  user   │  │  readonly       │  │
│  │  (all)  │  │(limited)│  │(view only)      │  │
│  └─────────┘  └─────────┘  └─────────────────┘  │
│                                                  │
│  Permissions:                                    │
│  - tools:list    - prompts:edit                 │
│  - tools:execute - admin:access                 │
│  - tools:*       - system:configure             │
│                                                  │
└─────────────────────────────────────────────────┘
```

### 11.3 Security Features

| Feature | Description |
|---------|-------------|
| Password Hashing | SHA-256 + salt |
| Session Tokens | UUID v4, time-limited |
| CORS | Configurable origins |
| Input Validation | JSON Schema validation |
| Path Sanitization | Directory traversal prevention |
| Rate Limiting | Per-user, per-endpoint |
| Audit Logging | All authentication events |

---

## 12. Data Flow Diagrams

### 12.1 Tool Execution Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│  API Route  │────▶│ MCP Handler │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                    ┌──────────────────────────┘
                    │
                    ▼
            ┌───────────────┐
            │ Auth Manager  │
            │  (Validate)   │
            └───────┬───────┘
                    │ Authorized
                    ▼
            ┌───────────────┐
            │Tools Registry │
            │ (Get Tool)    │
            └───────┬───────┘
                    │
                    ▼
            ┌───────────────┐
            │ BaseMCPTool   │
            │ (Execute)     │
            └───────┬───────┘
                    │
                    ▼
            ┌───────────────┐     ┌───────────────┐
            │ Tool Impl     │────▶│ External API  │
            │ (Logic)       │◀────│ (Optional)    │
            └───────┬───────┘     └───────────────┘
                    │
                    ▼
            ┌───────────────┐
            │ Format Result │
            │ (JSON-RPC)    │
            └───────┬───────┘
                    │
                    ▼
            ┌───────────────┐
            │   Response    │
            └───────────────┘
```

### 12.2 Hot-Reload Flow

```
┌───────────────────┐
│ File System Watch │ ──── config/tools/*.json
└─────────┬─────────┘      sajha/tools/impl/*.py
          │
          │ File changed
          ▼
┌───────────────────┐
│ Detect Change     │
│ (Timestamp check) │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Read New Content  │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Validate          │ ──── JSON syntax, schema
└─────────┬─────────┘
          │ Valid
          ▼
┌───────────────────┐
│ Unregister Old    │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Import Module     │ ──── importlib.reload()
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Register New      │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ WebSocket Notify  │ ──── Broadcast to clients
└───────────────────┘
```

---

## 13. API Architecture

### 13.1 REST API Endpoints

**Authentication:**
```
POST /api/auth/login     - User login
POST /api/auth/logout    - User logout
GET  /api/auth/session   - Session info
```

**Tools:**
```
GET  /api/tools                    - List all tools
GET  /api/tools/{name}             - Get tool details
POST /api/tools/{name}/execute     - Execute tool
GET  /api/tools/{name}/schema      - Get tool schema
```

**Prompts:**
```
GET  /api/prompts                  - List prompts
GET  /api/prompts/{name}           - Get prompt
POST /api/prompts/{name}/render    - Render prompt
POST /api/prompts                  - Create prompt
PUT  /api/prompts/{name}           - Update prompt
DELETE /api/prompts/{name}         - Delete prompt
```

**Admin:**
```
GET  /api/admin/status             - System status
POST /api/admin/hot-reload/force   - Force reload
GET  /api/admin/metrics            - System metrics
```

### 13.2 MCP JSON-RPC API

**Endpoint:** `POST /api/mcp`

**Request Format:**
```json
{
  "jsonrpc": "2.0",
  "id": "unique-request-id",
  "method": "tools/call",
  "params": {
    "name": "wikipedia_search",
    "arguments": {
      "query": "artificial intelligence"
    }
  }
}
```

**Response Format:**
```json
{
  "jsonrpc": "2.0",
  "id": "unique-request-id",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Search results here..."
      }
    ]
  }
}
```

### 13.3 WebSocket API

**Namespace:** `/mcp`

**Events:**

| Event | Direction | Purpose |
|-------|-----------|---------|
| `connect` | Client→Server | Establish connection |
| `mcp_request` | Client→Server | MCP protocol message |
| `mcp_response` | Server→Client | MCP response |
| `tool_status` | Server→Client | Execution status |
| `monitoring` | Server→Client | Real-time metrics |

---

## 14. Database Layer

### 14.1 DuckDB Integration

DuckDB provides OLAP analytics capabilities:

**Features:**
- In-process analytics database
- Columnar storage
- SQL interface
- Parquet/CSV import

**Connection Pool:**
```python
class DBConnectionPool:
    """
    Thread-safe connection pool for DuckDB
    
    - Connection reuse
    - Automatic cleanup
    - Query timeout handling
    """
```

### 14.2 Data Storage

| Location | Purpose |
|----------|---------|
| `data/duckdb/` | DuckDB database files |
| `data/sqlselect/` | CSV data for SQL Select tool |
| `data/msdocs/` | Document storage for MS Doc tool |

---

## 15. Hot-Reload System

### 15.1 Architecture

```
┌─────────────────────────────────────────────────┐
│              Hot-Reload Manager                  │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────┐  │
│  │ File Watcher│  │ Reload Timer│  │ Notifier│  │
│  └──────┬──────┘  └──────┬──────┘  └────┬────┘  │
│         │                │               │       │
│         ▼                ▼               ▼       │
│  ┌─────────────────────────────────────────────┐│
│  │           Reload Coordinator                 ││
│  └─────────────────────────────────────────────┘│
│         │                │               │       │
│         ▼                ▼               ▼       │
│  ┌───────────┐   ┌───────────┐   ┌───────────┐  │
│  │ Auth Mgr  │   │ Tools Reg │   │Prompts Reg│  │
│  │ (reload)  │   │ (reload)  │   │ (reload)  │  │
│  └───────────┘   └───────────┘   └───────────┘  │
│                                                  │
└─────────────────────────────────────────────────┘
```

### 15.2 Reload Strategies

| Component | Strategy |
|-----------|----------|
| Users | Full reload from `users.json` |
| API Keys | Incremental update |
| Tools | Per-tool reload (module + config) |
| Prompts | Per-prompt reload |

### 15.3 Configuration

```properties
# Hot-reload settings
config.reload.interval.seconds=300
config.reload.enabled=true
config.reload.watch.tools=true
config.reload.watch.prompts=true
config.reload.watch.users=true
```

---

## 16. Deployment Architecture

### 16.1 Single Server Deployment

```
┌─────────────────────────────────────────────────┐
│                Production Server                 │
│                                                  │
│  ┌─────────────────────────────────────────────┐│
│  │              SAJHA MCP Server                ││
│  │  ┌─────────────────────────────────────────┐││
│  │  │    Flask + Flask-SocketIO              │││
│  │  │    (Gunicorn + Eventlet Worker)        │││
│  │  └─────────────────────────────────────────┘││
│  └─────────────────────────────────────────────┘│
│                       │                          │
│  ┌─────────────────────────────────────────────┐│
│  │              Nginx Reverse Proxy             ││
│  │  - SSL Termination                           ││
│  │  - Static File Serving                       ││
│  │  - WebSocket Proxy                           ││
│  └─────────────────────────────────────────────┘│
│                                                  │
└─────────────────────────────────────────────────┘
```

### 16.2 Gunicorn Configuration

```python
# gunicorn_config.py
bind = "0.0.0.0:5000"
workers = 4
worker_class = "eventlet"
timeout = 120
keepalive = 5
```

### 16.3 Nginx Configuration

```nginx
upstream sajha_backend {
    server 127.0.0.1:5000;
}

server {
    listen 443 ssl;
    server_name mcp.example.com;
    
    ssl_certificate /etc/ssl/certs/mcp.crt;
    ssl_certificate_key /etc/ssl/private/mcp.key;
    
    location / {
        proxy_pass http://sajha_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    location /socket.io {
        proxy_pass http://sajha_backend/socket.io;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## 17. Extension Points

### 17.1 Creating Custom Tools

1. **Create Tool Class** (`sajha/tools/impl/my_tool.py`):

```python
from sajha.tools.base_mcp_tool import BaseMCPTool

class MyCustomTool(BaseMCPTool):
    def __init__(self, config=None):
        super().__init__(config or {
            'name': 'my_custom_tool',
            'description': 'My custom tool',
            'version': '1.0.0'
        })
    
    def get_input_schema(self):
        return {
            "type": "object",
            "properties": {
                "param1": {"type": "string"}
            },
            "required": ["param1"]
        }
    
    def get_output_schema(self):
        return {
            "type": "object",
            "properties": {
                "result": {"type": "string"}
            }
        }
    
    def execute(self, arguments):
        # Tool logic here
        return {"result": "Output"}
```

2. **Create Configuration** (`config/tools/my_custom_tool.json`):

```json
{
  "name": "my_custom_tool",
  "implementation": "sajha.tools.impl.my_tool.MyCustomTool",
  "description": "My custom tool",
  "version": "1.0.0",
  "enabled": true
}
```

3. **Tool is auto-loaded** on next hot-reload cycle

### 17.2 Adding Route Modules

1. Create route class extending `BaseRoutes`
2. Implement `register_routes(app)` method
3. Add to route registration in `SajhaMCPServerWebApp._register_routes()`

### 17.3 Custom Authentication Providers

Extend `AuthManager` to add:
- OAuth integration
- LDAP/Active Directory
- SSO providers

---

## 18. Performance Considerations

### 18.1 Caching Strategies

| Level | Implementation | TTL |
|-------|---------------|-----|
| Tool Results | Per-tool cache | Configurable |
| API Responses | HTTP cache headers | 60s default |
| Sessions | In-memory dict | 1 hour |
| Prompts | Registry cache | Until reload |

### 18.2 Connection Pooling

- DuckDB: Configurable pool size
- HTTP: urllib3 with connection reuse
- WebSocket: Flask-SocketIO async handling

### 18.3 Monitoring Metrics

| Metric | Collection |
|--------|------------|
| Request latency | Per-endpoint timing |
| Tool execution time | Per-tool tracking |
| Memory usage | Process monitoring |
| Active connections | WebSocket count |
| Error rates | Logging aggregation |

---

## 19. Appendices

### 19.1 Glossary

| Term | Definition |
|------|------------|
| **MCP** | Model Context Protocol - Standard for AI tool integration |
| **JSON-RPC** | Remote procedure call protocol using JSON |
| **RBAC** | Role-Based Access Control |
| **Hot-Reload** | Runtime configuration update without restart |
| **Singleton** | Design pattern ensuring single instance |

### 19.2 File Reference

| Extension | Purpose |
|-----------|---------|
| `.py` | Python source files |
| `.json` | Configuration and data |
| `.properties` | Java-style configuration |
| `.html` | Jinja2 templates |
| `.md` | Documentation (Markdown) |
| `.css` | Stylesheets |
| `.js` | JavaScript |

### 19.3 Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-01 | Initial release |
| 2.0.0 | 2025-06 | MCP Studio, Refactored tools |
| 2.1.0 | 2025-09 | Central bank tools, IR module |
| 2.2.0 | 2026-01 | Multi-encoding support, FRED API integration |
| 2.4.0 | 2026-02 | Comprehensive Dark Theme, navbar user context fix |
| 2.3.2 | 2026-02 | DB Query Tool Creator, REST CSV support |

### 19.4 References

- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification)
- [Flask Documentation](https://flask.palletsprojects.com/)
- [Flask-SocketIO Documentation](https://flask-socketio.readthedocs.io/)

---

**End of Document**

---

## Page Glossary

**Key terms referenced in this document:**

- **MCP (Model Context Protocol)**: A standardized protocol enabling AI systems to interact with external tools and data sources through a consistent interface. SAJHA implements MCP specification version 1.0.

- **JSON-RPC 2.0**: A stateless, lightweight remote procedure call protocol using JSON for data encoding. MCP uses JSON-RPC for all request/response communication.

- **Singleton Pattern**: A software design pattern that restricts instantiation of a class to a single instance. Used in SAJHA for ToolsRegistry, PromptsRegistry, and configuration managers to ensure consistent state.

- **RBAC (Role-Based Access Control)**: An authorization approach where permissions are assigned to roles, and roles are assigned to users. SAJHA implements RBAC via the AuthManager component.

- **Hot-Reload**: The capability to update configuration, tools, or code at runtime without restarting the server. A key feature enabling zero-downtime updates in SAJHA.

- **Flask**: A lightweight Python web framework used as the foundation for SAJHA's web layer. Provides routing, templating, and request handling.

- **WebSocket**: A communication protocol providing full-duplex channels over TCP. SAJHA uses WebSockets via Flask-SocketIO for real-time features.

- **Abstract Base Class (ABC)**: A class that cannot be instantiated and defines abstract methods that subclasses must implement. BaseMCPTool is an ABC that all tools inherit from.

- **JSON Schema**: A vocabulary for describing and validating JSON document structure. SAJHA uses JSON Schema to define tool input and output specifications.

- **Connection Pooling**: A technique of maintaining a cache of database connections for reuse, improving performance. SAJHA implements connection pooling for DuckDB.

- **Jinja2**: A Python template engine used by Flask for rendering HTML. SAJHA's web interface uses Jinja2 templates with Bootstrap 5.

- **OLAP (Online Analytical Processing)**: A category of software for rapid, multidimensional analysis of business data. SAJHA's DuckDB integration provides OLAP capabilities.

*For complete definitions of all terms, see the [Glossary](Glossary.md).*

---

*This architecture document is maintained as part of the SAJHA MCP Server project. For updates, corrections, or questions, contact the project maintainer.*
