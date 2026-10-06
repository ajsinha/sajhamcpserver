# Tutorial 2: Create a Custom Tool

Add a new tool by writing a small Python class and a JSON config. SAJHA picks up the config while it is running and serves the tool over MCP and REST.

## What you'll learn

- How a SAJHA tool is put together: a JSON config plus an implementation class
- How the running server detects a new tool config
- How to check and call the new tool

## Prerequisites

- A running server ([Tutorial 1](TUTORIAL_01_getting_started.md)) using the default **local** storage backend
- Write access to the server's `sajha/tools/impl/` and `config/tools/` directories

> **About MCP Studio:** The **MCP Studio** menu (`/studio`, `/studio/rest`, `/studio/dbquery`, `/studio/script`, …) opens the tool-creator pages. In the current build, their **Preview Tool** and **Deploy Tool** buttons post to `/admin/studio/...` endpoints that the server does not register, so they return 404. Until those endpoints come back, create tools by hand as shown below. The result is the same pair of files that Studio generates.

## Steps

### 1. Write the implementation class

Every tool extends `sajha.tools.base_mcp_tool.BaseMCPTool` and implements three methods: `execute`, `get_input_schema` and `get_output_schema`. Create `sajha/tools/impl/word_count_tool.py`:

```python
from typing import Any, Dict
from sajha.tools.base_mcp_tool import BaseMCPTool


class WordCountTool(BaseMCPTool):
    """Count words and characters in a piece of text."""

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        text = arguments["text"]
        return {"words": len(text.split()), "characters": len(text)}

    def get_input_schema(self) -> Dict:
        return self.config.get("inputSchema", {})

    def get_output_schema(self) -> Dict:
        return self.config.get("outputSchema", {})
```

`self.config` is the parsed JSON config from the next step. Before calling `execute`, the base class checks that the tool is enabled and that every `required` argument is present. It also applies caching (see [Tutorial 6](TUTORIAL_06_configure_tool_caching.md)) and the circuit breaker.

### 2. Write the JSON config

Create `config/tools/text_word_count.json`. Tool configs sit directly in `config/tools/`, one file per tool, and the file name should match the tool `name`:

```json
{
  "name": "text_word_count",
  "implementation": "sajha.tools.impl.word_count_tool.WordCountTool",
  "description": "Count the words and characters in a piece of text.",
  "version": "1.0.0",
  "enabled": true,
  "inputSchema": {
    "type": "object",
    "properties": {
      "text": {"type": "string", "description": "The text to analyse"}
    },
    "required": ["text"]
  },
  "outputSchema": {
    "type": "object",
    "properties": {
      "words": {"type": "integer"},
      "characters": {"type": "integer"}
    }
  },
  "metadata": {"category": "Utilities", "tags": ["text"]}
}
```

`implementation` is the dotted path to your class. String values may use `${key}` / `${key:default}` placeholders, which are resolved against `application.yml`.

### 3. Let the server pick it up

With the local storage backend, the tools registry polls `config/tools/` every few seconds. Within about five seconds the server log shows:

```
New tool configuration detected: text_word_count.json
Loaded custom tool: text_word_count
```

The poller works the same way when you edit a config later: a changed file is reloaded, and a deleted file unregisters its tool. To force a full reload, an admin can call `POST /api/admin/tools/reload`.

### 4. Call the tool

From the web UI, open **Tools → All tools**, search for `text_word_count` and click **Run**.

Over MCP, using a 2025-11-25 session as in [Tutorial 1](TUTORIAL_01_getting_started.md), step 6:

```bash
curl -s -X POST http://localhost:3002/mcp "${H[@]}" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call",
       "params":{"name":"text_word_count","arguments":{"text":"hello MCP world"}}}'
# -> "structuredContent": {"words": 3, "characters": 15}
```

The tool now appears in `tools/list` on every transport: Streamable HTTP `/mcp`, the legacy SSE endpoints and the WebSocket `/mcp/ws`.

### 5. (Optional) Disable or remove it

- **Admin → Tools** lets you enable or disable the tool. The API equivalents are `POST /api/admin/tools/text_word_count/disable` and `/enable`.
- Deleting `config/tools/text_word_count.json` unregisters the tool at the next poll.

## What next

- [MCP Studio User Guide](../studio/MCP%20Studio%20User%20Guide.md): the generated tool types (REST, DB query, script, …)
- [Composition Framework](../architecture/Composition%20Framework.md)
- Next tutorial: [Build a Composite Tool](TUTORIAL_03_build_a_composite_tool.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
