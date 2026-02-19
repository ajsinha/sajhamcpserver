# SAJHA MCP Server - Glossary of Terms

**Version:** 2.9.0  
**Last Updated:** February 2026  
**Classification:** Reference Document

---

## Legal Notice

**Copyright © 2025-2030, All Rights Reserved**  
**Ashutosh Sinha**  
**Email:** ajsinha@gmail.com

This document and the associated software architecture are proprietary and confidential. Unauthorized copying, distribution, modification, or use of this document or the software system it describes is strictly prohibited without explicit written permission from the copyright holder.

---

## About This Glossary

This glossary provides definitions for technical terms, acronyms, and concepts used throughout the SAJHA MCP Server documentation and codebase. Terms are organized alphabetically and include both project-specific terminology and industry-standard definitions.

---

## A

### Abstract Base Class (ABC)
A class that cannot be instantiated directly and serves as a template for other classes. In Python, defined using the `abc` module. SAJHA uses ABCs for `BaseMCPTool` to ensure all tools implement required methods.

### AJAX (Asynchronous JavaScript and XML)
A web development technique for creating asynchronous web applications. Allows web pages to update content without reloading the entire page. Used in SAJHA's web interface for real-time updates.

### API (Application Programming Interface)
A set of protocols, routines, and tools for building software applications. Specifies how software components should interact. SAJHA exposes REST and WebSocket APIs.

### API Key
A unique identifier used to authenticate requests to an API. SAJHA manages API keys for external services (Google, Tavily, FRED) via `apikeys.json`.

### AST (Abstract Syntax Tree)
A tree representation of the syntactic structure of source code. Used by MCP Studio's CodeAnalyzer to parse Python functions and extract metadata for tool generation.

### Authentication
The process of verifying the identity of a user or system. SAJHA supports username/password and API key authentication.

### Authorization
The process of determining what actions an authenticated user is allowed to perform. Implemented via RBAC in SAJHA.

---

## B

### Base64
A binary-to-text encoding scheme that represents binary data in ASCII string format. Used in SAJHA for encoding document content in templates.

### Bearer Token
An authentication token included in HTTP headers (Authorization: Bearer <token>). Used for API authentication in SAJHA.

### Blueprint (Flask)
A Flask feature for organizing application routes into modular components. SAJHA uses blueprints for separating route modules.

### Bootstrap
A popular CSS framework for building responsive web interfaces. SAJHA's web UI is built with Bootstrap 5.

### Batch Processing
Processing multiple requests or operations together rather than individually. SAJHA's MCPHandler supports batch JSON-RPC requests.

---

## C

### Cache
A hardware or software component that stores data for faster future access. SAJHA implements caching for tool results and API responses.

### Callback
A function passed as an argument to another function, to be executed later. Used extensively in SAJHA's WebSocket event handling.

### CGRT (Chinese Government Bond)
Chinese government-issued debt securities. Referenced in PBoC tools.

### CI/CD (Continuous Integration/Continuous Deployment)
Software development practices for automating testing and deployment. SAJHA is designed to support CI/CD pipelines.

### Client
Software that accesses services from a server. In MCP context, the AI system (Claude, GPT) that calls tools.

### Configuration
Settings that control application behavior. SAJHA uses properties files and JSON for configuration.

### Cohort Analysis
A type of analytics that groups users by a shared characteristic (e.g., signup date) and tracks their behavior over time. Used for understanding retention, engagement, and revenue patterns. SAJHA provides cohort analysis through the `olap_cohort_analysis` and `olap_retention_analysis` tools.

### Connection Pool
A cache of database connections maintained for reuse. SAJHA implements connection pooling for DuckDB.

### Context Processor (Flask)
A function that injects variables into all templates. SAJHA uses context processors for global template variables.

### CORS (Cross-Origin Resource Sharing)
A security mechanism that allows or restricts web resources to be requested from another domain. Configured in SAJHA via Flask-CORS.

### CPI (Consumer Price Index)
A measure of the average change in prices paid by consumers for goods and services. Available via central bank tools.

### CRUD (Create, Read, Update, Delete)
The four basic operations of persistent storage. SAJHA's prompts management implements full CRUD operations.

### CSV (Comma-Separated Values)
A file format for storing tabular data. SAJHA's SQL Select tool queries CSV files.

---

## D

### Daemon Thread
A background thread that runs without blocking program termination. SAJHA's file monitoring uses daemon threads.

### Decorator (Python)
A function that modifies the behavior of another function. SAJHA's `@sajhamcptool` decorator enables visual tool creation.

### Dependency Injection
A design pattern where dependencies are provided to a class rather than created internally. Used throughout SAJHA's architecture.

### Deserialization
The process of converting data from a serialized format back to an object. SAJHA deserializes JSON for API requests.

### Docker
A platform for containerizing applications. SAJHA can be deployed in Docker containers.

### Docstring
A string literal in Python code that documents a module, class, or function. MCP Studio extracts docstrings for tool descriptions.

### DOM (Document Object Model)
A programming interface for HTML documents. SAJHA's web UI manipulates the DOM via JavaScript.

### DuckDB
An in-process analytical database. SAJHA integrates DuckDB for OLAP analytics capabilities.

---

## E

### EDGAR (Electronic Data Gathering, Analysis, and Retrieval)
The SEC's system for companies to submit required filings electronically. SAJHA provides comprehensive EDGAR tools.

### Encoding
The process of converting data from one format to another. SAJHA supports multiple character encodings (UTF-8, Shift-JIS, GBK, etc.).

### Endpoint
A specific URL where an API can be accessed. SAJHA exposes multiple REST and WebSocket endpoints.

### Environment Variable
A dynamic value that can affect running processes. SAJHA reads configuration from environment variables.

### Error Handling
The process of responding to and recovering from error conditions. SAJHA implements comprehensive error handling with JSON-RPC error codes.

### ETL (Extract, Transform, Load)
A data integration process. SAJHA tools can be used in ETL pipelines.

### Event Loop
A programming construct that waits for and dispatches events. Flask-SocketIO uses an event loop for WebSocket handling.

### Eventlet
A Python networking library for concurrent programming. Used as SAJHA's WebSocket worker.

---

## F

### Factory Pattern
A design pattern for creating objects without specifying exact classes. SAJHA uses factories for tool and scraper creation.

### Flask
A lightweight Python web framework. SAJHA's web layer is built on Flask.

### Flask-SocketIO
A Flask extension for WebSocket support. Enables real-time bidirectional communication in SAJHA.

### FRED (Federal Reserve Economic Data)
A database of economic data maintained by the Federal Reserve Bank of St. Louis. SAJHA's central bank tools use FRED API.

### Full-Text Search
Searching through all words in documents. SAJHA's EDGAR tool supports full-text search of SEC filings.

---

## G

### GDP (Gross Domestic Product)
The total value of goods and services produced by a country. Available via economic data tools.

### Gzip
A file compression format. SAJHA's HTTP utilities handle gzip-compressed responses.

### Gunicorn
A Python WSGI HTTP server. Recommended for SAJHA production deployments.

---

## H

### Handler
A function or method that processes specific events or requests. SAJHA has handlers for MCP methods and WebSocket events.

### Hash Function
A function that converts input data to a fixed-size value. Used for password hashing in SAJHA.

### Hot-Reload
The ability to update configuration or code without restarting the application. A key feature of SAJHA.

### HTML (HyperText Markup Language)
The standard markup language for web pages. SAJHA serves HTML via Jinja2 templates.

### HTTP (HyperText Transfer Protocol)
The protocol for transmitting web data. SAJHA provides HTTP REST APIs.

### HTTPS (HTTP Secure)
HTTP with encryption via TLS/SSL. Recommended for production SAJHA deployments.

---

## I

### Idempotent
An operation that produces the same result regardless of how many times it's performed. Important for API design.

### IMF (International Monetary Fund)
An international organization focused on global monetary cooperation. SAJHA provides IMF data tools.

### Import (Python)
The process of loading modules or packages in Python. SAJHA uses dynamic imports for tool loading.

### Index
A data structure that improves data retrieval speed. Used in SAJHA's search functionality.

### Inheritance
An OOP concept where a class inherits properties from a parent class. All SAJHA tools inherit from BaseMCPTool.

### Input Schema
A JSON Schema definition describing valid tool inputs. Required for all MCP tools.

### Instance
A specific realization of a class. SAJHA creates tool instances from configurations.

### Integration
The process of combining software components. SAJHA integrates with multiple external APIs.

### IR (Investor Relations)
The function responsible for company communications with investors. SAJHA has a dedicated IR module.

---

## J

### JGB (Japanese Government Bond)
Japanese government-issued debt securities. Referenced in BoJ tools.

### Jinja2
A Python template engine used by Flask. SAJHA uses Jinja2 for HTML rendering.

### JSON (JavaScript Object Notation)
A lightweight data interchange format. SAJHA uses JSON extensively for configuration and APIs.

### JSON-RPC
A remote procedure call protocol encoded in JSON. MCP uses JSON-RPC 2.0.

### JSON Schema
A vocabulary for annotating and validating JSON documents. SAJHA uses JSON Schema for tool input/output definitions.

---

## K

### Key-Value Store
A data storage paradigm using keys to access values. SAJHA's configuration uses key-value patterns.

---

## L

### Latency
The time delay between a request and response. SAJHA tracks request latency for monitoring.

### Lazy Loading
Deferring initialization until needed. SAJHA uses lazy loading for some components.

### Load Balancing
Distributing workloads across multiple resources. Relevant for scaled SAJHA deployments.

### Logging
Recording application events for debugging and monitoring. SAJHA uses Python's logging module.

### LPR (Loan Prime Rate)
China's benchmark lending rate. Referenced in PBoC tools.

---

## M

### Markdown
A lightweight markup language for formatting text. SAJHA documentation is written in Markdown.

### MCP (Model Context Protocol)
A protocol for AI systems to interact with external tools and data sources. The core protocol SAJHA implements.

### MCP Studio
A visual tool creation platform within SAJHA that allows administrators to create MCP tools without manual coding. Includes seven creation methods: Python Code Tool Creator (using @sajhamcptool decorator), REST Service Tool Creator (for wrapping external APIs), Database Query Tool Creator (for SQL-based tools), Script Tool Creator (for shell/Python scripts), PowerBI Report Tool Creator (for PDF/PPTX/PNG export), PowerBI DAX Query Tool Creator (for executing DAX queries), and IBM LiveLink Document Tool Creator (for ECM document retrieval).

### MCP Studio - Python Code Creator
A component of MCP Studio that analyzes Python functions decorated with @sajhamcptool and automatically generates tool configuration (JSON) and implementation (Python class) files.

### MCP Studio - REST Service Tool Creator
A form-based component of MCP Studio (v2.7.0) that allows creating MCP tools from REST API endpoints. Supports GET, POST, PUT, DELETE, PATCH methods, API Key and Basic Auth, custom headers, JSON Schema validation, path parameters, and multiple response formats (JSON, CSV, XML, text). CSV responses support configurable delimiter, header detection, and row skipping. Includes 6 built-in examples including FRED CSV data. Full dark theme support.

### MCP Studio - Database Query Tool Creator
A form-based component of MCP Studio (v2.7.0) that allows creating MCP tools from SQL queries. Supports DuckDB, SQLite, PostgreSQL, and MySQL databases. Features parameterized queries with auto-generated input/output schemas, multiple parameter types (string, integer, number, boolean, date, enum), tool literature for AI context, and configurable row limits. Full dark theme support.

### MCP Studio - Script Tool Creator
A form-based component of MCP Studio (v2.7.0) that allows creating MCP tools from shell scripts, Python scripts, and other executable scripts. Scripts receive an array of string arguments as input and return STDOUT, STDERR, exit code, and execution time as output. Supports Bash, Sh, Zsh, Python, Node.js, Ruby, and Perl interpreters. Includes security validation to detect dangerous patterns, configurable timeout, working directory, and environment variables. Scripts can be uploaded or pasted directly in the editor. Full dark theme support.

### MCP Studio - PowerBI Report Tool Creator
A form-based component of MCP Studio (v2.7.0) that allows creating MCP tools to retrieve PowerBI reports as PDF, PPTX, or PNG in base64 encoded format. Requires Azure AD authentication with Service Principal. Features configurable workspace and report IDs, optional page selection, multiple export formats, timeout handling, and environment variable-based credential management. The caller receives base64-encoded data which can be decoded to the actual file. Full dark theme support.

### MCP Studio - PowerBIToolConfig
A Python dataclass (`sajha.studio.powerbi_tool_generator.PowerBIToolConfig`) that defines the configuration for PowerBI report tools. Includes fields for tool_name, description, report_name, workspace_id, report_id, tenant_id, client_id, client_secret_env, page_name, export_format (PDF/PPTX/PNG), timeout_seconds, author, and tags.

### MCP Studio - PowerBIToolGenerator
The generator class (`sajha.studio.powerbi_tool_generator.PowerBIToolGenerator`) that creates Python tool implementations and JSON configurations from PowerBIToolConfig objects. Handles GUID validation, Azure AD authentication setup, and file generation.

### MCP Studio - PowerBI DAX Query Tool Creator
A form-based component of MCP Studio (v2.7.0) that allows creating MCP tools to execute DAX queries against PowerBI datasets. Features parameterized queries with @parameter substitution, Azure AD Service Principal authentication, configurable timeout and max rows, and auto-generated input/output schemas. Returns structured JSON with columns and row data. Full dark theme support.

### MCP Studio - PowerBIDAXToolConfig
A Python dataclass (`sajha.studio.powerbidax_tool_generator.PowerBIDAXToolConfig`) that defines the configuration for PowerBI DAX query tools. Includes fields for tool_name, description, dataset_name, workspace_id, dataset_id, dax_query, tenant_id, client_id, client_secret_env, parameters, timeout_seconds, max_rows, author, and tags.

### MCP Studio - PowerBIDAXToolGenerator
The generator class (`sajha.studio.powerbidax_tool_generator.PowerBIDAXToolGenerator`) that creates Python tool implementations and JSON configurations from PowerBIDAXToolConfig objects. Handles DAX query validation, parameter substitution, and Azure AD authentication setup.

### MCP Studio - IBM LiveLink Document Tool Creator
A form-based component of MCP Studio (v2.7.0) that allows creating MCP tools to query and download documents from IBM LiveLink (OpenText Content Server). Supports search, list, get metadata, and download operations. Documents are returned as base64 encoded data. Multiple authentication types: Basic Auth, OAuth, and OTDS (OpenText Directory Services). Supports REST API v1 and v2. Full dark theme support.

### MCP Studio - LiveLinkToolConfig
A Python dataclass (`sajha.studio.livelink_tool_generator.LiveLinkToolConfig`) that defines the configuration for IBM LiveLink document tools. Includes fields for tool_name, description, server_url, auth_type, username_env, password_env, oauth_token_env, default_parent_id, document_types, timeout_seconds, max_file_size_mb, api_version, author, and tags.

### MCP Studio - LiveLinkToolGenerator
The generator class (`sajha.studio.livelink_tool_generator.LiveLinkToolGenerator`) that creates Python tool implementations and JSON configurations from LiveLinkToolConfig objects. Handles server URL validation, authentication setup, and file generation.

### MCP Studio - ScriptToolConfig
A Python dataclass (`sajha.studio.script_tool_generator.ScriptToolConfig`) that defines the configuration for script-based tools. Includes fields for tool_name, description, script_type, script_content, version, author, tags, timeout_seconds, working_directory, environment_vars, max_args, arg_descriptions, and security settings.

### MCP Studio - ScriptToolGenerator
The generator class (`sajha.studio.script_tool_generator.ScriptToolGenerator`) that creates Python tool implementations, JSON configurations, and script files from ScriptToolConfig objects. Handles validation, security checks, code generation, and file saving.

### MCP Studio - RESTToolDefinition
A Python dataclass (`sajha.studio.rest_tool_generator.RESTToolDefinition`) that defines the configuration for REST-based tools. Includes fields for name, endpoint, method, description, request/response schemas, authentication, headers, timeout, content type, response format (json/csv/xml/text), and CSV parsing options (delimiter, has_header, skip_rows).

### MCP Studio - RESTToolGenerator
The generator class (`sajha.studio.rest_tool_generator.RESTToolGenerator`) that creates Python tool implementations and JSON configurations from RESTToolDefinition objects. Handles validation, code generation, response format handling, and file saving.

### MCP Studio - DBQueryToolDefinition
A Python dataclass (`sajha.studio.dbquery_tool_generator.DBQueryToolDefinition`) that defines the configuration for database query tools. Includes fields for name, description, db_type, connection_string, query_template, parameters list, category, tags, literature, timeout, and max_rows.

### MCP Studio - DBQueryParameter
A Python dataclass (`sajha.studio.dbquery_tool_generator.DBQueryParameter`) that defines a single parameter for a database query tool. Includes fields for name, param_type (string, integer, number, boolean, date), description, required flag, default value, and optional enum values.

### MCP Studio - DBQueryToolGenerator
The generator class (`sajha.studio.dbquery_tool_generator.DBQueryToolGenerator`) that creates Python tool implementations and JSON configurations from DBQueryToolDefinition objects. Handles query validation, parameter schema generation, and file saving.

### Metadata
Data that describes other data. SAJHA tools include metadata for categorization and configuration.

### Middleware
Software that acts as a bridge between systems. Flask middleware handles requests in SAJHA.

### Migration
The process of moving data or systems from one state to another. SAJHA supports configuration migrations.

### Mock
A simulated object for testing. SAJHA's test suite uses mocks for external APIs.

### Module (Python)
A file containing Python code. SAJHA organizes functionality into modules.

### Mutex (Mutual Exclusion)
A synchronization mechanism preventing simultaneous access to shared resources. SAJHA uses threading locks.

---

## N

### Namespace
A container for identifiers to avoid naming conflicts. SAJHA uses Python namespaces and Flask-SocketIO namespaces.

### Nginx
A high-performance web server. Recommended as reverse proxy for SAJHA.

### Node
A point in a network or data structure. Used in SAJHA's IR module for document parsing.

---

## O

### OAuth
An authorization framework for third-party access. SAJHA can be extended to support OAuth.

### Object-Oriented Programming (OOP)
A programming paradigm based on objects and classes. SAJHA is built using OOP principles.

### OLAP (Online Analytical Processing)
A category of software for analyzing data from multiple perspectives. SAJHA's DuckDB tools provide OLAP capabilities.

### Output Schema
A JSON Schema definition describing tool outputs. Part of MCP tool specification.

---

## P

### Package (Python)
A directory of Python modules. SAJHA is organized as the `sajha` package.

### Pagination
Dividing content into discrete pages. SAJHA APIs support pagination for large result sets.

### Parameter
A variable in a function definition. Tools define parameters via input schemas.

### Parser
Software that analyzes syntax. SAJHA uses parsers for JSON, HTML, and Python code.

### Payload
The data transmitted in a request or response. MCP payloads are JSON-formatted.

### PBoC (People's Bank of China)
China's central bank. SAJHA provides PBoC data tools.

### PDF (Portable Document Format)
A file format for documents. Some SAJHA tools retrieve and process PDFs.

### Persistence
The ability to store data beyond application execution. SAJHA persists configuration and some data.

### Plugin
A software component that adds features to an existing application. SAJHA tools function as plugins.

### Polling
Repeatedly checking for changes or updates. SAJHA's hot-reload uses file polling.

### Pool
A collection of reusable resources. SAJHA implements connection and thread pools.

### PPI (Producer Price Index)
A measure of the average change in selling prices. Available via central bank tools.

### Production
A live environment serving real users. SAJHA is designed for production deployment.

### Promise
A JavaScript object representing eventual completion of an async operation. Used in SAJHA's frontend.

### Properties File
A configuration file format using key=value pairs. SAJHA uses Java-style properties files.

### Protocol
A set of rules governing communication. MCP is the protocol SAJHA implements.

### Proxy
An intermediary server that forwards requests. Nginx serves as a proxy for SAJHA.

---

## Q

### Query
A request for data. SAJHA tools accept queries for searching and data retrieval.

### Query String
URL parameters following the ? character. Used in SAJHA's REST API.

### Queue
A data structure for ordered processing. SAJHA uses queues for request handling.

---

## R

### Rate Limiting
Restricting the number of requests in a time period. SAJHA implements rate limiting for API protection.

### RBAC (Role-Based Access Control)
An authorization approach based on user roles. SAJHA's security model uses RBAC.

### Refactoring
Restructuring code without changing behavior. SAJHA tools have been refactored for consistency.

### Regex (Regular Expression)
A pattern for matching text. Used in SAJHA for input validation and parsing.

### Registry
A central repository for components. SAJHA has registries for tools and prompts.

### Rendering
Generating output from templates. Jinja2 renders HTML in SAJHA.

### Request
A message sent to request an action or data. SAJHA handles HTTP and WebSocket requests.

### Response
A message sent in reply to a request. SAJHA formats responses per JSON-RPC specification.

### Retention Analysis
A subset of cohort analysis focused specifically on measuring what percentage of users from each cohort remain active over time. Produces retention matrices showing period-over-period user engagement. See `olap_retention_analysis` tool.

### REST (Representational State Transfer)
An architectural style for web services. SAJHA provides REST APIs.

### RPC (Remote Procedure Call)
A protocol for executing procedures on remote systems. MCP uses JSON-RPC.

### Runtime
The period when a program is executing. SAJHA supports runtime configuration changes.

---

## S

### SAJHA
The name of this MCP server implementation. Derived from Sanskrit, meaning "shared" or "collaborative."

### Sanitization
Cleaning input to prevent security vulnerabilities. SAJHA sanitizes user input and file paths.

### Schema
A structure that defines data organization. JSON Schema defines tool inputs/outputs.

### Scraper
Software that extracts data from websites. SAJHA's IR module includes web scrapers.

### SDK (Software Development Kit)
Tools for developing applications for a platform. SAJHA provides client examples as an SDK.

### SEC (Securities and Exchange Commission)
The U.S. agency regulating securities markets. SAJHA provides SEC EDGAR tools.

### Serialization
Converting objects to a storable/transmittable format. SAJHA serializes data as JSON.

### Server
A system that provides services to clients. SAJHA is an MCP server.

### Session
A period of interaction between client and server. SAJHA manages user sessions with tokens.

### Singleton
A design pattern ensuring only one instance of a class exists. SAJHA uses singletons for registries.

### Socket
An endpoint for network communication. SAJHA uses WebSockets via Socket.IO.

### Socket.IO
A library for real-time web applications. Flask-SocketIO integrates Socket.IO with Flask.

### SQL (Structured Query Language)
A language for managing relational databases. SAJHA's DuckDB and SQL Select tools use SQL.

### SSL/TLS (Secure Sockets Layer/Transport Layer Security)
Protocols for encrypted communication. Used for HTTPS in SAJHA deployments.

### Static Files
Files served without processing (CSS, JS, images). SAJHA serves static files via Flask.

### Status Code
HTTP response codes indicating request outcome. SAJHA returns appropriate status codes.

### Streaming
Continuous data transmission. SAJHA supports WebSocket streaming.

### String
A sequence of characters. Python strings are used throughout SAJHA.

---

## T

### Template
A file with placeholders for dynamic content. Jinja2 templates generate SAJHA's HTML.

### Theme Switcher
A UI component (v2.7.0) that allows users to toggle between light and dark themes. The preference is persisted in browser localStorage and applied instantly without page reload. Located in the navbar next to the About link. Version 2.7.0 includes comprehensive dark theme support with 3,400+ lines of CSS ensuring text visibility across all pages including Dashboard, Help, About, MCP Studio, Tools, and Documentation pages.

### Thread
A unit of execution within a process. SAJHA uses threads for concurrent operations.

### Thread Safety
Code that functions correctly during simultaneous execution by multiple threads. SAJHA registries are thread-safe.

### Timeout
A limit on operation duration. SAJHA implements timeouts for HTTP requests and tool execution.

### Token
A unit of authentication or a lexical unit. SAJHA uses session tokens for authentication.

### Tool (MCP)
A function exposed via MCP that AI systems can call. SAJHA provides 40+ tools.

### Traceback
A report of function calls leading to an error. SAJHA logs tracebacks for debugging.

### Transport
The mechanism for transmitting data. MCP supports HTTP and WebSocket transports.

### TTL (Time To Live)
Duration before cached data expires. SAJHA tools have configurable cache TTL.

### Type Hint
Python annotations indicating expected types. MCP Studio uses type hints for schema generation.

---

## U

### UI (User Interface)
The means by which users interact with software. SAJHA provides a web-based UI.

### Unicode
A standard for text encoding. SAJHA supports Unicode via UTF-8 and other encodings.

### Unit Test
A test that verifies individual components. SAJHA includes unit tests for each tool.

### URL (Uniform Resource Locator)
A web address. SAJHA tools access external URLs and expose URL endpoints.

### UTF-8
A character encoding capable of encoding all Unicode characters. The default encoding in SAJHA.

### UUID (Universally Unique Identifier)
A 128-bit identifier. SAJHA uses UUIDs for session tokens and request IDs.

---

## V

### Validation
Checking that data meets requirements. SAJHA validates inputs against JSON schemas.

### Variable
A named storage location. SAJHA templates use variables for dynamic content.

### Version
An identifier for a release. SAJHA uses semantic versioning (e.g., 2.2.0).

### Virtual Environment
An isolated Python environment. Recommended for SAJHA installation.

---

## W

### Web Crawler
Software that browses the web automatically. SAJHA includes a web crawler tool.

### WebSocket
A protocol for full-duplex communication over TCP. SAJHA uses WebSockets for real-time features.

### Wildcard
A character representing any value. SAJHA uses "*" for universal tool access.

### Worker
A process or thread handling tasks. Gunicorn workers serve SAJHA requests.

### World Bank
An international financial institution. SAJHA provides World Bank data tools.

### WSGI (Web Server Gateway Interface)
A Python specification for web server communication. Flask uses WSGI.

---

## X

### XML (eXtensible Markup Language)
A markup language for encoding documents. Some external APIs return XML.

### XSS (Cross-Site Scripting)
A security vulnerability. SAJHA sanitizes output to prevent XSS.

---

## Y

### YAML (YAML Ain't Markup Language)
A human-readable data serialization format. Alternative to JSON for configuration.

### Yield
A Python keyword for generator functions. Used in some SAJHA iterators.

---

## Z

### Zero-Downtime Deployment
Updating software without service interruption. SAJHA's hot-reload enables this.

---

## Acronyms Quick Reference

| Acronym | Full Form |
|---------|-----------|
| ABC | Abstract Base Class |
| AJAX | Asynchronous JavaScript and XML |
| API | Application Programming Interface |
| AST | Abstract Syntax Tree |
| BoC | Bank of Canada |
| BoJ | Bank of Japan |
| CGB | Chinese Government Bond |
| CI/CD | Continuous Integration/Continuous Deployment |
| CORS | Cross-Origin Resource Sharing |
| CPI | Consumer Price Index |
| CRUD | Create, Read, Update, Delete |
| CSS | Cascading Style Sheets |
| CSV | Comma-Separated Values |
| DOM | Document Object Model |
| ECB | European Central Bank |
| EDGAR | Electronic Data Gathering, Analysis, and Retrieval |
| ETL | Extract, Transform, Load |
| FRED | Federal Reserve Economic Data |
| GDP | Gross Domestic Product |
| HTML | HyperText Markup Language |
| HTTP | HyperText Transfer Protocol |
| HTTPS | HTTP Secure |
| IMF | International Monetary Fund |
| IR | Investor Relations |
| JGB | Japanese Government Bond |
| JSON | JavaScript Object Notation |
| LPR | Loan Prime Rate |
| MCP | Model Context Protocol |
| OAuth | Open Authorization |
| OLAP | Online Analytical Processing |
| OOP | Object-Oriented Programming |
| PBoC | People's Bank of China |
| PDF | Portable Document Format |
| PPI | Producer Price Index |
| RBAC | Role-Based Access Control |
| RBI | Reserve Bank of India |
| REST | Representational State Transfer |
| RPC | Remote Procedure Call |
| SDK | Software Development Kit |
| SEC | Securities and Exchange Commission |
| SQL | Structured Query Language |
| SSL | Secure Sockets Layer |
| TLS | Transport Layer Security |
| TTL | Time To Live |
| UI | User Interface |
| URL | Uniform Resource Locator |
| UTF | Unicode Transformation Format |
| UUID | Universally Unique Identifier |
| WSGI | Web Server Gateway Interface |
| XML | eXtensible Markup Language |
| XSS | Cross-Site Scripting |
| YAML | YAML Ain't Markup Language |

---

## Page Glossary

**Terms relevant to this document:**

- **Glossary**: A list of terms with definitions, typically arranged alphabetically. This document serves as the master glossary for the SAJHA MCP Server project.
- **Technical Documentation**: Written material explaining how software works, including architecture, APIs, and user guides.
- **Reference Document**: A document designed for quick lookup rather than sequential reading.

---

**End of Glossary**

*This glossary is maintained as part of the SAJHA MCP Server project documentation. For additions or corrections, contact the project maintainer.*
