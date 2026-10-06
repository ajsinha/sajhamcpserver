# MCP Studio REST Tool Creator Guide

The REST Tool Creator wraps a single HTTP endpoint as an MCP tool through a form, with no code to write. It generates a JSON tool config and a Python class that makes the HTTP call with `requests` and returns the parsed response.

Where Studio lives, the common create → preview → deploy workflow, where generated files are stored, hot reload and permissions are covered once in the [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md).

The creator page is `/studio/rest` (**MCP Studio → REST service tool**).

---

## Form reference

### Basic information

| Field | Required | Notes |
|-------|----------|-------|
| Tool Name | Yes | Starts with a lowercase letter; `a-z`, `0-9`, `_` only; at least 3 characters. Lower-cased on submit. |
| Category | No | Defaults to `REST API`. |
| Description | Yes | Shown in tool listings. |
| Tags | No | Type and press Enter. If none are given the page sends `["rest", "api"]`. |

### Endpoint configuration

| Field | Required | Notes |
|-------|----------|-------|
| HTTP Method | Yes | GET, POST, PUT, DELETE or PATCH. Defaults to GET. |
| REST Endpoint URL | Yes | Must start with `http://` or `https://`. May contain path parameters such as `{user_id}`. |
| Content Type | No | `application/json` (default), `application/x-www-form-urlencoded`, `multipart/form-data` or `text/plain`. Sent as the `Content-Type` header. |
| Timeout (seconds) | No | 1–300, default 30. |

### Authentication

| Option | Fields | What the tool does |
|--------|--------|--------------------|
| No Auth | – | Default. |
| API Key | Header name (default `X-API-Key`), key value | Sends the key in that header on every call. |
| Basic Auth | Username, password | Uses HTTP Basic authentication. |

> **The API key and Basic Auth credentials are written as literals into the generated Python file.** Anyone who can read `sajha/tools/impl/` can read them. Prefer an endpoint that needs no secret, or rotate keys you use here.

### Custom headers

Optional name/value pairs, added after the default headers (and able to override them). The defaults are `Content-Type`, an `Accept` header that matches the response format, `User-Agent: SAJHA-MCP-Server/<version>`, and the API key header if configured.

### Request schema

A JSON Schema for the tool's input. The section is labelled **Query Parameters Schema** for GET and DELETE, and **Request Body Schema** for POST, PUT and PATCH. A schema is required for POST, PUT and PATCH.

The schema's `properties` and `required` become the tool's input schema. If the schema has no `properties`, the input schema allows any properties.

### Response format

| Format | Parsing | `data` in the result |
|--------|---------|----------------------|
| JSON (default) | Parsed as JSON; falls back to `{"raw_response": ...}` | The parsed JSON |
| CSV | Parsed with the CSV options below; numeric-looking values become numbers; rows whose column count doesn't match the header are dropped | Array of row objects (plus `columns` and `row_count`) |
| XML | Top-level structure only | `{"root_tag": ..., "children": [child tag names]}`, or `{"raw_xml": ...}` if parsing fails |
| Text | Decoded as text | The text (plus `content_length`) |

**CSV options** (shown when CSV is selected): Delimiter (comma, semicolon, tab, pipe), Header Row (first row is header, or no header, in which case columns are named `column_1`, `column_2`, …) and Skip Rows (0–100 lines skipped before the header or data).

### Response schema (optional)

A JSON Schema for the response. For JSON and XML responses, if it has `properties` it becomes the `data` property of the tool's output schema. Otherwise the output schema is derived from the response format.

---

## How the generated tool calls the endpoint

- **Path parameters.** Each `{name}` in the URL is replaced with the argument of the same name.
- **GET.** All arguments, including those used as path parameters, are also sent as query-string parameters.
- **POST, PUT, PATCH.** All arguments are sent as a JSON body, whatever the Content Type setting.
- **DELETE.** No query string and no body; only path parameters are used.
- **Errors** do not raise. The tool returns `success: false` with an `error` message: a timeout, `HTTP error: <status> - <reason>` (with `status_code` and the first 500 characters of the response as `response_text`), a request failure, or an unexpected error. There is no retry.

A successful call returns:

```json
{
  "success": true,
  "status_code": 200,
  "format": "json",
  "data": { "...": "..." },
  "endpoint": "<the URL actually called>",
  "method": "GET"
}
```

---

## Generated files

For tool name `get_weather_forecast`:

| File | Content |
|------|---------|
| `config/tools/get_weather_forecast.json` | Tool config |
| `sajha/tools/impl/rest_get_weather_forecast.py` | Class `RESTGetWeatherForecastTool(BaseMCPTool)` |

The JSON config:

```json
{
  "name": "get_weather_forecast",
  "implementation": "sajha.tools.impl.rest_get_weather_forecast.RESTGetWeatherForecastTool",
  "description": "Get weather forecast for a location",
  "version": "<generator version>",
  "enabled": true,
  "metadata": {
    "author": "MCP Studio - REST Generator",
    "category": "Weather",
    "tags": ["rest", "api"],
    "rateLimit": 60,
    "cacheTTL": 60,
    "requiresApiKey": false,
    "source": "rest_service",
    "endpoint": "https://api.open-meteo.com/v1/forecast",
    "method": "GET"
  }
}
```

Deploying fails if either file already exists. Remove the old files first, or choose another name.

---

## Quick examples

The **Quick Examples** sidebar fills the form with a working configuration:

| Example | Method | Shows |
|---------|--------|-------|
| Open-Meteo Weather | GET | No-auth query parameters |
| JSONPlaceholder Posts | POST | JSON request body |
| GitHub User Info | GET | Path parameter (`/users/{username}`) |
| Coinbase Prices | GET | Path parameter (`/prices/{currency_pair}/spot`) |
| Random Cat Facts | GET | No parameters |
| FRED Economic Data | GET | CSV response |

---

## Walkthrough: a weather tool

1. Click **Open-Meteo Weather** in Quick Examples, or fill the form yourself:
   - **Tool Name**: `get_weather_forecast`
   - **Category**: `Weather`
   - **Description**: `Get weather forecast for a location`
   - **Method**: GET
   - **URL**: `https://api.open-meteo.com/v1/forecast`
2. Enter the request schema:
   ```json
   {
     "type": "object",
     "properties": {
       "latitude": {"type": "number", "description": "Latitude"},
       "longitude": {"type": "number", "description": "Longitude"},
       "current_weather": {"type": "boolean", "default": true}
     },
     "required": ["latitude", "longitude"]
   }
   ```
3. Leave the response format as **JSON**.
4. Click **Preview Tool** to see the generated JSON and the start of the Python file. **Deploy Tool** is enabled after a successful preview.
5. Click **Deploy Tool** and confirm.

> The buttons post to `/admin/studio/rest/preview` and `/admin/studio/rest/deploy`. A successful deploy loads the tool at once; see [Action endpoints](MCP%20Studio%20User%20Guide.md#action-endpoints-deploy-load-and-delete).

---

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| "Invalid request schema JSON" | The request schema text is not valid JSON. |
| "Endpoint must start with http:// or https://" | Use a full URL. |
| "Request schema is required for POST/PUT/PATCH methods" | Provide a schema with the body properties. |
| "Tool configuration already exists" / "Tool implementation already exists" | A tool with that name has already been generated. |
| `HTTP error: 401 - Unauthorized` | Check the auth option, header name and key. |
| A path parameter appears unreplaced in the URL | The argument name doesn't match the `{name}` in the URL, or isn't in the schema. |
| GET endpoint rejects unexpected query parameters | Path-parameter arguments are also sent as query parameters on GET. |
| CSV `data` is empty | Wrong delimiter or Skip Rows value, or rows have a different column count from the header. |

---

## Related documentation

- [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md)
- [Python Code Tool Creator Guide](MCP%20Studio%20Python%20Code%20Tool%20Creator%20Guide.md), for HTTP calls that need custom logic
- [Architecture](../architecture/Architecture.md)
- [Glossary](../../GLOSSARY.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
