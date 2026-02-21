# MCP Studio Python Code Tool Creator Guide
## SAJHA MCP Server v2.9.8

## Overview

The Python Code Tool Creator in MCP Studio enables you to create MCP tools that execute Python code for data processing, analysis, automation, and integration tasks. This visual interface guides you through configuring Python execution environments, dependencies, input/output handling, and security controls.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Understanding Python Tools](#understanding-python-tools)
3. [Creating Your First Python Tool](#creating-your-first-python-tool)
4. [Configuration Options](#configuration-options)
5. [Input Parameters](#input-parameters)
6. [Output Handling](#output-handling)
7. [Dependencies Management](#dependencies-management)
8. [Security Configuration](#security-configuration)
9. [Testing and Debugging](#testing-and-debugging)
10. [Best Practices](#best-practices)
11. [Examples](#examples)
12. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Accessing the Python Code Tool Creator

1. Navigate to `http://localhost:3002/admin/studio`
2. Click on **Script Tool** card (select Python type)
3. Or directly access: `http://localhost:3002/admin/studio/script?type=python`

### Prerequisites

- Admin role access to SAJHA MCP Server
- Python 3.8+ installed on the server
- Required packages installed or pip access
- Understanding of Python programming

---

## Understanding Python Tools

Python tools in SAJHA enable sophisticated data processing and integration capabilities. When a Python tool is invoked:

1. The tool receives input parameters from the MCP client
2. Creates an isolated execution environment
3. Injects parameters into the Python namespace
4. Executes the Python code
5. Captures the return value and output
6. Returns structured results to the MCP client

### Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌─────────────┐
│  MCP Client │────▶│  Python Tool │────▶│  Python Runtime │────▶│  Libraries  │
│  (Claude)   │◀────│  (SAJHA)     │◀────│  (Subprocess)   │◀────│  & Modules  │
└─────────────┘     └──────────────┘     └─────────────────┘     └─────────────┘
```

### Execution Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| **inline** | Execute embedded Python code | Simple scripts |
| **module** | Import and call Python module | Reusable libraries |
| **script** | Execute Python script file | Complex applications |
| **function** | Call specific function | Modular design |

---

## Creating Your First Python Tool

### Step 1: Basic Information

Fill in the essential tool details:

| Field | Description | Example |
|-------|-------------|---------|
| **Tool Name** | Unique identifier (snake_case) | `data_analyzer_python` |
| **Display Name** | Human-readable name | `Data Analyzer` |
| **Description** | What the tool does | `Analyzes CSV data and returns statistics` |
| **Category** | Tool grouping | `Data Analysis` |
| **Version** | Semantic version | `1.0.0` |

### Step 2: Python Configuration

Configure the Python execution:

```
Python Version: 3.11
Execution Mode: Inline Code
Virtual Environment: /opt/venvs/analytics
```

### Step 3: Write Python Code

```python
import pandas as pd
import json

def analyze(data_path, columns=None):
    """Analyze CSV data and return statistics."""
    df = pd.read_csv(data_path)
    
    if columns:
        df = df[columns]
    
    stats = {
        'row_count': len(df),
        'columns': list(df.columns),
        'summary': df.describe().to_dict(),
        'null_counts': df.isnull().sum().to_dict()
    }
    
    return stats

# Execute with provided parameters
result = analyze(data_path, columns)
```

### Step 4: Deploy

Click **Deploy Tool** to create and register the tool.

---

## Configuration Options

### Basic Configuration

```json
{
  "name": "my_python_tool",
  "implementation": "sajha.tools.impl.python_tool.PythonTool",
  "version": "2.9.8",
  "enabled": true,
  "python": {
    "version": "3.11",
    "execution_mode": "inline",
    "interpreter": "/usr/bin/python3",
    "virtual_env": "/opt/venvs/myenv"
  },
  "timeout_seconds": 300,
  "max_memory_mb": 1024
}
```

### Inline Code Configuration

```json
{
  "python": {
    "execution_mode": "inline",
    "code": "import json\n\ndef process(data):\n    return {'processed': len(data)}\n\nresult = process(input_data)"
  }
}
```

### Module Configuration

```json
{
  "python": {
    "execution_mode": "module",
    "module_path": "/opt/python/my_module.py",
    "function": "process_data",
    "class": null
  }
}
```

### Script File Configuration

```json
{
  "python": {
    "execution_mode": "script",
    "script_path": "/opt/scripts/analyzer.py",
    "working_directory": "/opt/data"
  }
}
```

### Function Call Configuration

```json
{
  "python": {
    "execution_mode": "function",
    "module": "my_package.analysis",
    "function": "run_analysis",
    "class": "DataAnalyzer",
    "method": "analyze"
  }
}
```

---

## Input Parameters

### Parameter Schema

```json
{
  "inputSchema": {
    "type": "object",
    "properties": {
      "data_path": {
        "type": "string",
        "required": true,
        "description": "Path to input data file"
      },
      "columns": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Columns to analyze"
      },
      "options": {
        "type": "object",
        "properties": {
          "include_nulls": {"type": "boolean", "default": true},
          "decimal_places": {"type": "integer", "default": 2}
        }
      }
    },
    "required": ["data_path"]
  }
}
```

### Parameter Injection

Parameters are injected into the Python namespace:

```python
# These variables are automatically available:
# - data_path: str
# - columns: List[str] or None
# - options: dict

print(f"Processing: {data_path}")
print(f"Columns: {columns}")
print(f"Options: {options}")
```

### Type Conversion

| JSON Type | Python Type |
|-----------|-------------|
| `string` | `str` |
| `integer` | `int` |
| `number` | `float` |
| `boolean` | `bool` |
| `array` | `list` |
| `object` | `dict` |
| `null` | `None` |

### File Input Handling

```json
{
  "inputSchema": {
    "properties": {
      "file_content": {
        "type": "string",
        "format": "base64",
        "description": "Base64 encoded file content"
      },
      "file_path": {
        "type": "string",
        "format": "file-path",
        "description": "Server file path"
      }
    }
  }
}
```

---

## Output Handling

### Return Value

The last expression or explicit `result` variable is returned:

```python
# Option 1: Assign to 'result'
result = {'status': 'success', 'data': processed_data}

# Option 2: Last expression (for simple scripts)
{'status': 'success', 'data': processed_data}
```

### Output Schema

```json
{
  "outputSchema": {
    "type": "object",
    "properties": {
      "success": {"type": "boolean"},
      "data": {
        "type": "object",
        "properties": {
          "row_count": {"type": "integer"},
          "columns": {"type": "array"},
          "summary": {"type": "object"}
        }
      },
      "execution_time_ms": {"type": "integer"},
      "warnings": {"type": "array"}
    }
  }
}
```

### Structured Output

```python
import json
from dataclasses import dataclass, asdict

@dataclass
class AnalysisResult:
    success: bool
    row_count: int
    summary: dict
    warnings: list = None

result = asdict(AnalysisResult(
    success=True,
    row_count=len(df),
    summary=df.describe().to_dict(),
    warnings=[]
))
```

### Binary Output

```python
import base64

# For binary data (images, files, etc.)
with open('output.png', 'rb') as f:
    image_data = base64.b64encode(f.read()).decode('utf-8')

result = {
    'type': 'image',
    'format': 'png',
    'data': image_data
}
```

---

## Dependencies Management

### Requirements File

```json
{
  "python": {
    "requirements": [
      "pandas>=2.0.0",
      "numpy>=1.24.0",
      "scikit-learn>=1.3.0",
      "requests>=2.31.0"
    ]
  }
}
```

### Virtual Environment

```json
{
  "python": {
    "virtual_env": "/opt/venvs/analytics",
    "create_venv": true,
    "install_requirements": true
  }
}
```

### Conda Environment

```json
{
  "python": {
    "conda_env": "analytics",
    "conda_path": "/opt/conda"
  }
}
```

### Import Restrictions

```json
{
  "security": {
    "allowed_imports": [
      "pandas", "numpy", "json", "datetime",
      "collections", "itertools", "functools"
    ],
    "blocked_imports": [
      "os", "subprocess", "sys", "socket",
      "importlib", "__builtins__"
    ]
  }
}
```

---

## Security Configuration

### Sandbox Settings

```json
{
  "security": {
    "sandbox_enabled": true,
    "allowed_paths": [
      "/opt/data",
      "/tmp/sajha"
    ],
    "blocked_paths": [
      "/etc", "/root", "/home"
    ],
    "network_access": false,
    "file_write": false
  }
}
```

### Resource Limits

```json
{
  "limits": {
    "timeout_seconds": 300,
    "max_memory_mb": 1024,
    "max_cpu_percent": 80,
    "max_output_bytes": 10485760,
    "max_file_size_mb": 100
  }
}
```

### Restricted Builtins

```json
{
  "security": {
    "restricted_builtins": [
      "eval", "exec", "compile",
      "open", "__import__",
      "globals", "locals"
    ],
    "safe_builtins": true
  }
}
```

### Audit Logging

```json
{
  "audit": {
    "log_code_execution": true,
    "log_imports": true,
    "log_file_access": true,
    "log_network_calls": false
  }
}
```

---

## Testing and Debugging

### Interactive Testing

1. Write your Python code
2. Click **Test Code** button
3. Provide sample input values
4. View output and any errors

### Debug Mode

```json
{
  "debug": {
    "enabled": true,
    "verbose_errors": true,
    "include_traceback": true,
    "capture_stdout": true,
    "capture_stderr": true
  }
}
```

### Logging in Python Code

```python
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def process(data):
    logger.info(f"Processing {len(data)} records")
    logger.debug(f"Data sample: {data[:5]}")
    
    try:
        result = analyze(data)
        logger.info("Analysis complete")
        return result
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise
```

### Unit Testing

```python
# test_mode is injected as True during testing
if test_mode:
    # Run tests instead of main execution
    def test_analyze():
        test_data = [1, 2, 3, 4, 5]
        result = analyze(test_data)
        assert result['count'] == 5
        assert result['mean'] == 3.0
    
    test_analyze()
    result = {'tests_passed': True}
```

---

## Best Practices

### 1. Code Organization

```python
# Good: Modular structure
def validate_input(data):
    """Validate input data."""
    if not data:
        raise ValueError("Empty data")
    return True

def process_data(data):
    """Process the data."""
    validate_input(data)
    return [x * 2 for x in data]

def format_output(processed):
    """Format output for return."""
    return {
        'count': len(processed),
        'data': processed
    }

# Main execution
result = format_output(process_data(input_data))
```

### 2. Error Handling

```python
from typing import Dict, Any

def safe_process(data: list) -> Dict[str, Any]:
    """Process data with comprehensive error handling."""
    try:
        # Validate
        if not isinstance(data, list):
            return {'success': False, 'error': 'Data must be a list'}
        
        # Process
        processed = [x * 2 for x in data]
        
        return {
            'success': True,
            'result': processed,
            'count': len(processed)
        }
    
    except TypeError as e:
        return {'success': False, 'error': f'Type error: {e}'}
    except Exception as e:
        return {'success': False, 'error': f'Unexpected error: {e}'}

result = safe_process(input_data)
```

### 3. Memory Efficiency

```python
import pandas as pd

def process_large_file(file_path: str, chunk_size: int = 10000):
    """Process large files in chunks."""
    results = []
    
    for chunk in pd.read_csv(file_path, chunksize=chunk_size):
        # Process each chunk
        chunk_result = chunk.describe().to_dict()
        results.append(chunk_result)
    
    # Aggregate results
    return {'chunks_processed': len(results), 'summaries': results}

result = process_large_file(data_path)
```

### 4. Type Hints

```python
from typing import List, Dict, Optional, Any

def analyze_data(
    data: List[Dict[str, Any]],
    columns: Optional[List[str]] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Analyze data with optional column filtering.
    
    Args:
        data: List of records to analyze
        columns: Optional list of columns to include
        options: Optional configuration options
    
    Returns:
        Analysis results as dictionary
    """
    # Implementation
    pass
```

### 5. Documentation

```python
"""
Data Analysis Tool
==================

This tool analyzes CSV data and returns statistical summaries.

Usage:
    result = analyze(data_path, columns=['col1', 'col2'])

Parameters:
    data_path (str): Path to CSV file
    columns (list): Optional list of columns to analyze

Returns:
    dict: Analysis results including row count, summary stats
"""
```

---

## Examples

### Example 1: CSV Data Analysis

```json
{
  "name": "csv_analyzer",
  "description": "Analyze CSV files and return statistics",
  "python": {
    "execution_mode": "inline",
    "code": "import pandas as pd\nimport json\n\ndef analyze_csv(file_path, columns=None):\n    df = pd.read_csv(file_path)\n    \n    if columns:\n        df = df[columns]\n    \n    return {\n        'rows': len(df),\n        'columns': list(df.columns),\n        'dtypes': df.dtypes.astype(str).to_dict(),\n        'summary': df.describe().to_dict(),\n        'null_counts': df.isnull().sum().to_dict(),\n        'sample': df.head(5).to_dict('records')\n    }\n\nresult = analyze_csv(file_path, columns)",
    "requirements": ["pandas>=2.0.0"]
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "file_path": {"type": "string", "required": true},
      "columns": {"type": "array", "items": {"type": "string"}}
    }
  }
}
```

### Example 2: Machine Learning Prediction

```json
{
  "name": "ml_predictor",
  "description": "Make predictions using trained ML model",
  "python": {
    "execution_mode": "inline",
    "code": "import pickle\nimport numpy as np\n\ndef predict(model_path, features):\n    # Load model\n    with open(model_path, 'rb') as f:\n        model = pickle.load(f)\n    \n    # Prepare features\n    X = np.array(features).reshape(1, -1)\n    \n    # Predict\n    prediction = model.predict(X)[0]\n    probabilities = model.predict_proba(X)[0].tolist() if hasattr(model, 'predict_proba') else None\n    \n    return {\n        'prediction': int(prediction),\n        'probabilities': probabilities,\n        'model_type': type(model).__name__\n    }\n\nresult = predict(model_path, features)",
    "requirements": ["numpy>=1.24.0", "scikit-learn>=1.3.0"]
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "model_path": {"type": "string", "required": true},
      "features": {"type": "array", "items": {"type": "number"}, "required": true}
    }
  }
}
```

### Example 3: Web Scraping

```json
{
  "name": "web_scraper",
  "description": "Scrape data from web pages",
  "python": {
    "execution_mode": "inline",
    "code": "import requests\nfrom bs4 import BeautifulSoup\n\ndef scrape(url, selectors):\n    response = requests.get(url, timeout=30)\n    response.raise_for_status()\n    \n    soup = BeautifulSoup(response.text, 'html.parser')\n    \n    results = {}\n    for name, selector in selectors.items():\n        elements = soup.select(selector)\n        results[name] = [el.get_text(strip=True) for el in elements]\n    \n    return {\n        'url': url,\n        'status': response.status_code,\n        'data': results\n    }\n\nresult = scrape(url, selectors)",
    "requirements": ["requests>=2.31.0", "beautifulsoup4>=4.12.0"]
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "url": {"type": "string", "required": true},
      "selectors": {"type": "object", "required": true}
    }
  },
  "security": {
    "network_access": true,
    "allowed_domains": ["example.com", "api.example.com"]
  }
}
```

### Example 4: Image Processing

```json
{
  "name": "image_processor",
  "description": "Process and analyze images",
  "python": {
    "execution_mode": "inline",
    "code": "from PIL import Image\nimport base64\nimport io\n\ndef process_image(image_path, operations):\n    img = Image.open(image_path)\n    original_size = img.size\n    \n    for op in operations:\n        if op['type'] == 'resize':\n            img = img.resize((op['width'], op['height']))\n        elif op['type'] == 'rotate':\n            img = img.rotate(op['angle'])\n        elif op['type'] == 'grayscale':\n            img = img.convert('L')\n        elif op['type'] == 'thumbnail':\n            img.thumbnail((op['size'], op['size']))\n    \n    # Convert to base64\n    buffer = io.BytesIO()\n    img.save(buffer, format='PNG')\n    img_base64 = base64.b64encode(buffer.getvalue()).decode()\n    \n    return {\n        'original_size': original_size,\n        'final_size': img.size,\n        'operations_applied': len(operations),\n        'image_data': img_base64\n    }\n\nresult = process_image(image_path, operations)",
    "requirements": ["Pillow>=10.0.0"]
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "image_path": {"type": "string", "required": true},
      "operations": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "type": {"type": "string", "enum": ["resize", "rotate", "grayscale", "thumbnail"]}
          }
        }
      }
    }
  }
}
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| ModuleNotFoundError | Missing package | Add to requirements list |
| MemoryError | Data too large | Use chunked processing |
| Timeout | Long execution | Increase timeout or optimize |
| Permission denied | File access blocked | Check allowed_paths |
| Import blocked | Security restriction | Add to allowed_imports |

### Debug Checklist

1. ✅ Python version matches requirements
2. ✅ All dependencies installed
3. ✅ Input parameters are correct types
4. ✅ File paths are accessible
5. ✅ Memory limits are sufficient
6. ✅ Check server logs for errors

### Log Analysis

```bash
# View Python tool execution logs
tail -f logs/sajha_mcp.log | grep "PythonTool"

# Check Python errors
grep "Traceback" logs/sajha_mcp.log
```

### Common Fixes

```python
# Fix 1: Handle missing optional parameters
columns = columns if columns else []

# Fix 2: Ensure JSON-serializable output
import json
result = json.loads(json.dumps(result, default=str))

# Fix 3: Memory cleanup
import gc
del large_dataframe
gc.collect()
```

---

## Related Documentation

- [MCP Studio Overview](MCP_Studio_User_Guide.md)
- [Script Tool Guide](MCP_Studio_Script_Tool_Creator_Guide.md)
- [DuckDB Analytics Guide](DuckDB_MCP_Tool_Reference_Guide.md)

---

*SAJHA MCP Server v2.9.8 - Python Code Tool Creator Guide*
*Copyright © 2025-2030 Ashutosh Sinha*
