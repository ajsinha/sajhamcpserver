# MCP Studio User Guide

**Version: 2.2.0**  
**Copyright © 2025-2030 Ashutosh Sinha, All Rights Reserved**

---

## Overview

MCP Studio is an innovative visual tool creation feature that allows administrators to create custom MCP tools using Python code with the `@sajhamcptool` decorator. Instead of manually writing JSON configuration files and Python class boilerplate, you simply write a decorated function and the system generates everything automatically.

---

## Key Features

- **Visual Code Editor** - Write and edit Python code directly in the browser
- **Automatic Schema Generation** - Type hints become JSON schemas automatically
- **Real-time Preview** - See generated JSON and Python files before deployment
- **Syntax Validation** - Code is validated before saving to prevent errors
- **One-Click Deployment** - Deploy tools instantly with hot-reload
- **Safe Deletion** - Delete existing tools with double confirmation

---

## The @sajhamcptool Decorator

The `@sajhamcptool` decorator marks a Python function for conversion to an MCP tool.

### Basic Syntax

```python
from sajha.studio import sajhamcptool

@sajhamcptool(
    description="Your tool description here",
    category="Category Name",
    tags=["tag1", "tag2"]
)
def your_function_name(param1: str, param2: int = 10) -> dict:
    """Optional docstring."""
    # Your implementation
    return {"result": "value"}
```

### Decorator Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `description` | str | **Yes** | - | What the tool does (shown in tool listings) |
| `category` | str | No | "General" | Category for organization |
| `tags` | list[str] | No | [] | Tags for searchability |
| `author` | str | No | "MCP Studio User" | Tool author name |
| `version` | str | No | "1.0.0" | Tool version |
| `rate_limit` | int | No | 60 | Requests per minute limit |
| `cache_ttl` | int | No | 300 | Cache time-to-live (seconds) |
| `enabled` | bool | No | True | Whether tool is enabled |

---

## Type Hints → JSON Schema

MCP Studio uses Python type hints to generate JSON schemas automatically.

### Type Mapping

| Python Type | JSON Schema Type | Example |
|-------------|-----------------|---------|
| `str` | `string` | `name: str` |
| `int` | `integer` | `count: int` |
| `float` | `number` | `price: float` |
| `bool` | `boolean` | `enabled: bool` |
| `list` | `array` | `items: list` |
| `dict` | `object` | `data: dict` |
| `List[str]` | `array` | `names: List[str]` |
| `Dict[str, int]` | `object` | `scores: Dict[str, int]` |
| `Optional[str]` | `string` | `nickname: Optional[str]` |

### Required vs Optional Parameters

- **Required**: Parameters without default values
- **Optional**: Parameters with default values

```python
@sajhamcptool(description="Example")
def example(
    required_param: str,          # Required (no default)
    optional_param: int = 10      # Optional (has default)
) -> dict:
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

## Step-by-Step Usage

### Step 1: Access MCP Studio

1. Log in as an administrator
2. Navigate to **Admin → MCP Studio** in the navigation menu
3. The MCP Studio interface will load

### Step 2: Enter Tool Name

1. In the **Tool Name** field, enter a unique name
2. Use only lowercase letters, numbers, and underscores
3. Name must be at least 3 characters
4. Name cannot conflict with existing tools

**Valid names:** `my_tool`, `calculate_tax`, `fetch_data_v2`  
**Invalid names:** `MyTool`, `calculate-tax`, `ab`

### Step 3: Write Your Code

Enter your Python function with the `@sajhamcptool` decorator:

```python
from sajha.studio import sajhamcptool

@sajhamcptool(
    description="Calculate the factorial of a number",
    category="Mathematics",
    tags=["math", "factorial", "calculation"]
)
def calculate_factorial(n: int) -> dict:
    """Calculate factorial of n."""
    if n < 0:
        return {"error": "Factorial not defined for negative numbers"}
    
    result = 1
    for i in range(1, n + 1):
        result *= i
    
    return {
        "input": n,
        "factorial": result
    }
```

### Step 4: Analyze Code

1. Click the **Analyze Code** button
2. The system will parse your code and extract:
   - Function name
   - Description from decorator
   - Parameters and their types
   - Return type
3. If successful, you'll see:
   - Analysis results panel with parameters
   - Generated JSON configuration (right panel, top)
   - Generated Python implementation (right panel, bottom)
4. If there are errors, they'll be displayed in the status bar

### Step 5: Review Generated Files

**JSON Configuration** (`config/tools/your_tool.json`):
```json
{
  "name": "your_tool",
  "implementation": "sajha.tools.impl.studio_your_tool.YourToolTool",
  "description": "Your tool description",
  "version": "2.2.0",
  "enabled": true,
  "metadata": {
    "author": "MCP Studio User",
    "category": "General",
    "tags": ["mcp-studio", "generated"],
    "rateLimit": 60,
    "cacheTTL": 300,
    "source": "MCP Studio"
  }
}
```

**Python Implementation** (`sajha/tools/impl/studio_your_tool.py`):
- Complete class extending `BaseMCPTool`
- Automatic argument extraction from `arguments` dict
- Your function body in the `execute()` method
- Proper input/output schema methods

### Step 6: Deploy Tool

1. Review the generated files carefully
2. Click the **Deploy Tool** button
3. Confirm the deployment
4. Files are saved:
   - JSON: `config/tools/{tool_name}.json`
   - Python: `sajha/tools/impl/studio_{tool_name}.py`
5. Tools registry is automatically reloaded
6. Your tool is now available!

---

## Managing Existing Tools

### Delete if Exists

If you need to recreate a tool (fix bugs, update functionality):

1. Enter the tool name in the Tool Name field
2. Click the red **Delete if Exists** button
3. Confirm in the first dialog (shows files to be deleted)
4. Confirm in the second dialog (final warning)
5. Files are deleted and tool is unregistered
6. You can now redeploy with the same name

**Warning:** This permanently deletes the tool files. Make sure you have backups if needed.

---

## Best Practices

### 1. Use Clear Descriptions

```python
# Good
@sajhamcptool(description="Calculate compound interest with customizable compounding frequency")

# Bad
@sajhamcptool(description="Interest calc")
```

### 2. Use Meaningful Type Hints

```python
# Good - clear types
def fetch_stock(symbol: str, days: int = 30) -> dict:

# Bad - no types
def fetch_stock(symbol, days=30):
```

### 3. Return Dictionaries

Always return a `dict` from your function for consistent output:

```python
# Good
return {"status": "success", "data": result}

# Bad
return result  # Could be any type
```

### 4. Handle Errors Gracefully

```python
@sajhamcptool(description="Divide two numbers")
def divide(a: float, b: float) -> dict:
    if b == 0:
        return {"error": "Division by zero", "success": False}
    return {"result": a / b, "success": True}
```

### 5. Use Categories and Tags

```python
@sajhamcptool(
    description="Get weather data",
    category="Weather",
    tags=["weather", "api", "forecast", "temperature"]
)
```

---

## Troubleshooting

### "No @sajhamcptool decorated functions found"

- Ensure you have `@sajhamcptool(description="...")` decorator
- The `description` parameter is required
- Don't use `@sajhamcptool` without parentheses

### "Tool name already exists"

- Use **Delete if Exists** to remove the old tool first
- Or choose a different tool name

### "Syntax error in generated code"

- Check your function body for syntax errors
- Ensure proper indentation in your code
- Verify all variables are defined

### "Generated Python has syntax error on line X"

- The system validates generated code before saving
- Check the preview panel for the exact error location
- Common issues: missing colons, unbalanced brackets, indentation

---

## Examples

### Example 1: Simple Calculator

```python
@sajhamcptool(
    description="Perform basic arithmetic operations",
    category="Mathematics",
    tags=["calculator", "math", "arithmetic"]
)
def simple_calc(a: float, b: float, operation: str = "add") -> dict:
    """Perform basic math operation."""
    ops = {
        "add": a + b,
        "subtract": a - b,
        "multiply": a * b,
        "divide": a / b if b != 0 else None
    }
    result = ops.get(operation)
    if result is None:
        return {"error": f"Invalid operation or division by zero"}
    return {"a": a, "b": b, "operation": operation, "result": result}
```

### Example 2: Text Analyzer

```python
@sajhamcptool(
    description="Analyze text and return statistics",
    category="Text Processing",
    tags=["text", "analysis", "statistics", "nlp"]
)
def analyze_text(text: str, include_word_freq: bool = False) -> dict:
    """Analyze text content."""
    words = text.split()
    sentences = text.count('.') + text.count('!') + text.count('?')
    
    result = {
        "character_count": len(text),
        "word_count": len(words),
        "sentence_count": sentences,
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

### Example 3: API Wrapper

```python
@sajhamcptool(
    description="Fetch data from a REST API endpoint",
    category="API Integration",
    tags=["api", "http", "rest", "fetch"],
    rate_limit=30,
    cache_ttl=600
)
def fetch_api(
    url: str,
    method: str = "GET",
    timeout: int = 30
) -> dict:
    """Fetch data from API."""
    import urllib.request
    import json
    
    try:
        req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode('utf-8'))
            return {"success": True, "status": response.status, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

---

## File Locations

After deployment, files are saved to:

| File Type | Location |
|-----------|----------|
| JSON Config | `config/tools/{tool_name}.json` |
| Python Code | `sajha/tools/impl/studio_{tool_name}.py` |

---

## Related Documentation

- [Tool Development Guide](Tool_Development_Guide.md)
- [API Reference](API_Reference.md)
- [Configuration Guide](Configuration_Guide.md)

---

*Last Updated: January 2026*
