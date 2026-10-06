# MCP Studio Python Code Tool Creator Guide

The Python Code Tool Creator turns a Python function marked with the `@sajhamcptool` decorator into an MCP tool. Studio parses your code (it does not run it), reads the decorator arguments and the function signature, and generates a JSON tool config plus a `BaseMCPTool` subclass that wraps your function body.

Where Studio lives, the common create → preview → deploy workflow, where generated files are stored, hot reload and permissions are covered once in the [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md).

The creator is the **Python Code Tool Creator** section at the bottom of the Studio home page (`/studio`). The **Examples** page (`/studio/examples`) shows a decorator reference and a starter template.

---

## The @sajhamcptool decorator

```python
from sajha.studio import sajhamcptool

@sajhamcptool(
    description="Your tool description here",
    category="Category Name",
    tags=["tag1", "tag2"]
)
def your_function_name(param1: str, param2: int = 10) -> dict:
    """Optional docstring."""
    return {"result": param1, "count": param2}
```

### Decorator parameters

These are the parameters `sajhamcptool()` accepts (`sajha/studio/decorator.py`).

| Parameter | Type | Required | Default | Used for |
|-----------|------|----------|---------|----------|
| `description` | str | Yes | – | Tool description in tool listings (may also be the first positional argument) |
| `category` | str | No | `"General"` | `metadata.category` |
| `tags` | list[str] | No | `[]` | `metadata.tags` (Studio appends `"mcp-studio"` and `"generated"`) |
| `author` | str | No | `"MCP Studio User"` | `metadata.author` |
| `version` | str | No | `"1.0.0"` | Accepted and parsed, but the generated config carries the generator's own version string, not this value |
| `rate_limit` | int | No | `60` | `metadata.rateLimit` |
| `cache_ttl` | int | No | `300` | `metadata.cacheTTL` (seconds) |
| `enabled` | bool | No | `True` | `enabled` in the config and the class |

Decorator argument values must be literals (strings, numbers, booleans, lists, dicts), because Studio reads them from the syntax tree rather than executing the code. The decorator must be called with parentheses: a bare `@sajhamcptool` is ignored with a warning that `description` is required.

---

## Type hints → JSON Schema

The analyzer (`sajha/studio/code_analyzer.py`) maps each parameter's type hint to a JSON Schema type. For subscripted hints only the outer name counts, so `List[str]` is an `array` with no `items`.

| Python hint | JSON Schema `type` |
|-------------|--------------------|
| `str` | `string` |
| `int` | `integer` |
| `float` | `number` |
| `bool` | `boolean` |
| `list`, `List[...]` | `array` |
| `dict`, `Dict[...]` | `object` |
| `Optional[...]` | `string` (whatever the inner type) |
| `Any`, no hint, anything else | `string` |

- A parameter **without** a default value is listed in `required`.
- A parameter with a literal default gets `"default"` in its schema (a default of `None` is omitted).
- Keyword-only parameters are included; `self` is skipped.
- The output schema comes from the return annotation (`dict` → `object`, `list` → `array`, and so on). With no return annotation it is `object`.

Example:

```python
@sajhamcptool(description="Example")
def example(required_param: str, optional_param: int = 10) -> dict:
    ...
```

Generated input schema:

```json
{
  "type": "object",
  "properties": {
    "required_param": {"type": "string"},
    "optional_param": {"type": "integer", "default": 10}
  },
  "required": ["required_param"]
}
```

---

## Using the creator

1. **Tool Name** – must start with a lowercase letter and use only `a-z`, `0-9` and `_`; at least 3 characters and at most 64; must not match an existing tool name or a reserved word (`self`, `class`, `def`, `import`, `from`, `return`, `tool`, `mcp`). The page checks format, length and conflicts as you type.
2. **Code editor** – paste a function decorated with `@sajhamcptool(...)`.
3. **Analyze Code** – shows the description, category, function name and parameter badges (required/optional, with defaults), and fills the two preview panes with the generated JSON config and Python file.
4. **Deploy Tool** – enabled only after a successful analysis; asks for confirmation, then writes the two files.
5. **Delete if Exists** – after two confirmations, unregisters the tool and deletes `config/tools/<name>.json` and its generated module (`sajha/tools/impl/studio_<name>.py`, or the module of whichever creator made it) so the name can be reused. It refuses tools that Studio did not generate.
6. **Clear** – resets the form.

> The buttons post to `/admin/studio/analyze`, `/admin/studio/deploy` and `/admin/studio/delete`. A successful deploy loads the tool at once; see [Action endpoints](MCP%20Studio%20User%20Guide.md#action-endpoints-deploy-load-and-delete).

### What gets generated

For tool name `your_tool`:

| File | Content |
|------|---------|
| `config/tools/your_tool.json` | Tool config (written through the storage backend) |
| `sajha/tools/impl/studio_your_tool.py` | Class `YourToolTool(BaseMCPTool)` |

The class name is the tool name in PascalCase plus `Tool`. The JSON config looks like this:

```json
{
  "name": "your_tool",
  "implementation": "sajha.tools.impl.studio_your_tool.YourToolTool",
  "description": "Your tool description",
  "version": "<generator version>",
  "enabled": true,
  "metadata": {
    "author": "MCP Studio User",
    "category": "General",
    "tags": ["mcp-studio", "generated"],
    "rateLimit": 60,
    "cacheTTL": 300,
    "createdAt": "<ISO timestamp>",
    "source": "MCP Studio"
  },
  "sandbox": {"network": "none"}
}
```

The generated `execute(arguments)` method:

- reads each parameter from `arguments` (`arguments['x']` for required parameters, `arguments.get('x', default)` for optional ones), then
- runs **your function body** (the docstring is dropped). If the body has no `return`, `return {"status": "success"}` is appended.

The generated Python is checked for syntax errors before it is saved.

### Where your code runs

Your function runs in the [sandbox](../architecture/Sandbox.md), never in the server: the
generated module is not imported by the server, and each call starts a fresh sandbox with
no server environment, no access to the server's files, a temp work directory, CPU,
memory, process and output limits, and **no network** unless the tool's `sandbox` block
allowlists hosts:

```json
"sandbox": {"network": "allowlist", "allow_hosts": ["api.example.com:443"], "timeout_seconds": 20}
```

The page shows the policy a new tool gets and what the active backend enforces on this
host. Inside the sandbox only the standard library and the packages installed for the
sandbox's interpreter can be imported; `sajha` itself is not available (apart from the
`BaseMCPTool` base class the generated code needs). Secrets come only through
`sandbox.secrets` (names the administrator allowlisted).

**Only the function body is copied.** Module-level imports, helper functions and constants outside the decorated function are not carried into the generated file. Put imports inside the function, as in the examples below.

---

## Best practices

- **Write a specific description.** `"Calculate compound interest with a configurable compounding frequency"` is more useful to a model than `"Interest calc"`.
- **Annotate every parameter.** Unannotated parameters become `string`.
- **Return a dict.** Studio tools return what your body returns; a dict with clear keys is easiest for clients.
- **Return errors rather than raising**, for example `{"success": False, "error": "Division by zero"}`.
- **Import inside the function** (see above).

---

## Examples

### Simple calculator

```python
@sajhamcptool(
    description="Perform basic arithmetic operations",
    category="Mathematics",
    tags=["calculator", "math", "arithmetic"]
)
def simple_calc(a: float, b: float, operation: str = "add") -> dict:
    ops = {
        "add": a + b,
        "subtract": a - b,
        "multiply": a * b,
        "divide": a / b if b != 0 else None
    }
    result = ops.get(operation)
    if result is None:
        return {"error": "Invalid operation or division by zero"}
    return {"a": a, "b": b, "operation": operation, "result": result}
```

### Text analyzer

```python
@sajhamcptool(
    description="Analyze text and return statistics",
    category="Text Processing",
    tags=["text", "analysis", "statistics"]
)
def analyze_text(text: str, include_word_freq: bool = False) -> dict:
    words = text.split()
    result = {
        "character_count": len(text),
        "word_count": len(words),
        "sentence_count": text.count('.') + text.count('!') + text.count('?'),
        "avg_word_length": sum(len(w) for w in words) / len(words) if words else 0
    }
    if include_word_freq:
        freq = {}
        for word in words:
            w = word.lower().strip('.,!?')
            freq[w] = freq.get(w, 0) + 1
        result["word_frequency"] = freq
    return result
```

### API wrapper

```python
@sajhamcptool(
    description="Fetch JSON from a REST API endpoint",
    category="API Integration",
    tags=["api", "http"],
    rate_limit=30,
    cache_ttl=600
)
def fetch_api(url: str, method: str = "GET", timeout: int = 30) -> dict:
    import json
    import urllib.request
    try:
        req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode('utf-8'))
            return {"success": True, "status": response.status, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

This tool needs network access: give it `"sandbox": {"network": "allowlist", "allow_hosts": [...]}` with the hosts it may call. For wrapping an HTTP endpoint without code, see the [REST Tool Creator Guide](MCP%20Studio%20REST%20Tool%20Creator%20Guide.md).

---

## Troubleshooting

| Message | Cause and fix |
|---------|---------------|
| Analysis finds no function | The decorator is missing or used without parentheses (`@sajhamcptool` alone is ignored). |
| Tool name already exists | Pick another name, or use **Delete if Exists** first. |
| Must start with lowercase letter… / at least 3 characters | Fix the tool name format. |
| Syntax error in code: … | The analyzer could not parse the code. Check indentation, colons and brackets. |
| Generated Python has syntax error on line N | The function body did not survive re-indentation. Check the Python preview pane at that line. |
| `NameError` when the tool runs | The body uses an import or helper defined outside the function. Move it inside. |
| `PermissionError` / `OSError` reading a file or opening a connection | The sandbox blocks it. Files: use the work directory (the current directory). Network: allowlist the host in the tool's `sandbox` block. |
| `SandboxTimeout` / `SandboxOutputLimit` | The call hit the sandbox's `timeout_seconds` or `max_output_bytes`. |

---

## Related documentation

- [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md)
- [Script Tool Creator Guide](MCP%20Studio%20Script%20Tool%20Creator%20Guide.md)
- [Architecture](../architecture/Architecture.md)
- [Glossary](../../GLOSSARY.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
