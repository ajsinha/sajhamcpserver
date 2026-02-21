# MCP Studio Script Tool Creator Guide
## SAJHA MCP Server v2.9.8

## Overview

The Script Tool Creator enables you to create MCP tools that execute custom scripts - including Python, Bash, PowerShell, and other scripting languages. This provides maximum flexibility for complex data processing, system integration, and custom business logic.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Supported Script Types](#supported-script-types)
3. [Creating Script Tools](#creating-script-tools)
4. [Python Script Tools](#python-script-tools)
5. [Bash Script Tools](#bash-script-tools)
6. [PowerShell Script Tools](#powershell-script-tools)
7. [Input/Output Handling](#inputoutput-handling)
8. [Environment Configuration](#environment-configuration)
9. [Security Considerations](#security-considerations)
10. [Best Practices](#best-practices)
11. [Examples](#examples)
12. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Accessing the Script Tool Creator

1. Navigate to `http://localhost:3002/admin/studio`
2. Click on **Script Tool** card
3. Or directly access: `http://localhost:3002/admin/studio/script`

### Prerequisites

- Admin role access
- Script interpreter installed (Python, Bash, PowerShell)
- Understanding of the scripting language
- Required libraries/dependencies installed

---

## Supported Script Types

| Type | Extension | Interpreter | Use Cases |
|------|-----------|-------------|-----------|
| **Python** | `.py` | python3 | Data processing, API calls, ML |
| **Bash** | `.sh` | bash | System tasks, file operations |
| **PowerShell** | `.ps1` | pwsh | Windows admin, Azure tasks |
| **Node.js** | `.js` | node | Web tasks, JSON processing |
| **Ruby** | `.rb` | ruby | Text processing, scripting |

---

## Creating Script Tools

### Step 1: Basic Information

```json
{
  "name": "data_processor_script",
  "display_name": "Data Processor",
  "description": "Process and transform data files",
  "category": "Data Processing",
  "version": "2.9.8",
  "script_type": "python"
}
```

### Step 2: Script Configuration

```json
{
  "script": {
    "type": "python",
    "inline": true,
    "code": "# Your Python code here",
    "timeout": 300,
    "working_dir": "./scripts"
  }
}
```

### Step 3: Input Schema

Define parameters your script accepts:

```json
{
  "inputSchema": {
    "type": "object",
    "properties": {
      "input_file": {
        "type": "string",
        "description": "Path to input file"
      },
      "output_format": {
        "type": "string",
        "enum": ["json", "csv", "xml"],
        "default": "json"
      }
    },
    "required": ["input_file"]
  }
}
```

### Step 4: Deploy

Click **Deploy Tool** to create the script tool.

---

## Python Script Tools

### Inline Python Script

```json
{
  "name": "python_data_analyzer",
  "script": {
    "type": "python",
    "inline": true,
    "code": "import json\nimport sys\n\ndef main(args):\n    data = args.get('data', [])\n    result = {\n        'count': len(data),\n        'sum': sum(data) if data else 0,\n        'average': sum(data)/len(data) if data else 0\n    }\n    return result\n\nif __name__ == '__main__':\n    import json\n    args = json.loads(sys.argv[1])\n    result = main(args)\n    print(json.dumps(result))"
  }
}
```

### External Python Script

```json
{
  "name": "python_external_script",
  "script": {
    "type": "python",
    "inline": false,
    "file": "scripts/data_processor.py",
    "entry_function": "process_data"
  }
}
```

### Python Script Template

```python
#!/usr/bin/env python3
"""
MCP Tool Script: Data Processor
Version: 2.9.8
"""

import json
import sys
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def process_data(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main processing function.
    
    Args:
        args: Input parameters from MCP tool call
        
    Returns:
        Dictionary with processing results
    """
    try:
        # Extract input parameters
        input_data = args.get('data', [])
        operation = args.get('operation', 'analyze')
        
        # Process data
        if operation == 'analyze':
            result = {
                'count': len(input_data),
                'stats': calculate_stats(input_data)
            }
        elif operation == 'transform':
            result = {
                'transformed': transform_data(input_data)
            }
        else:
            raise ValueError(f"Unknown operation: {operation}")
        
        return {
            'success': True,
            'result': result
        }
        
    except Exception as e:
        logger.error(f"Processing error: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def calculate_stats(data):
    """Calculate basic statistics."""
    if not data:
        return {}
    return {
        'min': min(data),
        'max': max(data),
        'sum': sum(data),
        'avg': sum(data) / len(data)
    }


def transform_data(data):
    """Transform data."""
    return [item * 2 for item in data]


if __name__ == '__main__':
    # Read arguments from command line
    if len(sys.argv) > 1:
        args = json.loads(sys.argv[1])
    else:
        args = {}
    
    # Execute and output result
    result = process_data(args)
    print(json.dumps(result))
```

### Required Python Packages

Specify dependencies in your configuration:

```json
{
  "script": {
    "type": "python",
    "requirements": [
      "pandas>=1.5.0",
      "numpy>=1.23.0",
      "requests>=2.28.0"
    ]
  }
}
```

---

## Bash Script Tools

### Inline Bash Script

```json
{
  "name": "system_info_script",
  "script": {
    "type": "bash",
    "inline": true,
    "code": "#!/bin/bash\n\n# Get system information\nHOSTNAME=$(hostname)\nUPTIME=$(uptime -p)\nDISK_USAGE=$(df -h / | tail -1 | awk '{print $5}')\nMEMORY=$(free -h | grep Mem | awk '{print $3\"/\"$2}')\n\n# Output as JSON\ncat << EOF\n{\n  \"hostname\": \"$HOSTNAME\",\n  \"uptime\": \"$UPTIME\",\n  \"disk_usage\": \"$DISK_USAGE\",\n  \"memory\": \"$MEMORY\"\n}\nEOF"
  }
}
```

### Bash Script Template

```bash
#!/bin/bash
#
# MCP Tool Script: File Processor
# Version: 2.9.8
#

set -e  # Exit on error

# Parse JSON input
INPUT_FILE=$(echo "$1" | jq -r '.input_file')
OUTPUT_DIR=$(echo "$1" | jq -r '.output_dir // "/tmp"')
OPERATION=$(echo "$1" | jq -r '.operation // "copy"')

# Validate inputs
if [ -z "$INPUT_FILE" ] || [ ! -f "$INPUT_FILE" ]; then
    echo '{"success": false, "error": "Input file not found"}'
    exit 1
fi

# Process based on operation
case $OPERATION in
    "copy")
        cp "$INPUT_FILE" "$OUTPUT_DIR/"
        RESULT="File copied successfully"
        ;;
    "compress")
        gzip -c "$INPUT_FILE" > "$OUTPUT_DIR/$(basename "$INPUT_FILE").gz"
        RESULT="File compressed successfully"
        ;;
    "analyze")
        LINES=$(wc -l < "$INPUT_FILE")
        WORDS=$(wc -w < "$INPUT_FILE")
        SIZE=$(stat -f%z "$INPUT_FILE" 2>/dev/null || stat -c%s "$INPUT_FILE")
        RESULT="Lines: $LINES, Words: $WORDS, Size: $SIZE bytes"
        ;;
    *)
        echo '{"success": false, "error": "Unknown operation"}'
        exit 1
        ;;
esac

# Output result as JSON
cat << EOF
{
    "success": true,
    "operation": "$OPERATION",
    "input_file": "$INPUT_FILE",
    "result": "$RESULT"
}
EOF
```

---

## PowerShell Script Tools

### Inline PowerShell Script

```json
{
  "name": "windows_system_info",
  "script": {
    "type": "powershell",
    "inline": true,
    "code": "$computerInfo = Get-ComputerInfo\n$result = @{\n    ComputerName = $env:COMPUTERNAME\n    OS = $computerInfo.OsName\n    Version = $computerInfo.OsVersion\n    Memory = \"$([math]::Round($computerInfo.CsTotalPhysicalMemory/1GB, 2)) GB\"\n}\n$result | ConvertTo-Json"
  }
}
```

### PowerShell Script Template

```powershell
#
# MCP Tool Script: Azure Resource Manager
# Version: 2.9.8
#

param(
    [Parameter(Mandatory=$true)]
    [string]$InputJson
)

# Parse input
$params = $InputJson | ConvertFrom-Json

try {
    # Connect to Azure (if needed)
    # Connect-AzAccount -Identity
    
    $resourceGroup = $params.resource_group
    $operation = $params.operation
    
    switch ($operation) {
        "list_vms" {
            $vms = Get-AzVM -ResourceGroupName $resourceGroup
            $result = @{
                success = $true
                vms = $vms | Select-Object Name, Location, VmSize
            }
        }
        "get_storage" {
            $storage = Get-AzStorageAccount -ResourceGroupName $resourceGroup
            $result = @{
                success = $true
                storage_accounts = $storage | Select-Object StorageAccountName, Location
            }
        }
        default {
            throw "Unknown operation: $operation"
        }
    }
    
    $result | ConvertTo-Json -Depth 5
}
catch {
    @{
        success = $false
        error = $_.Exception.Message
    } | ConvertTo-Json
}
```

---

## Input/Output Handling

### Input Methods

**1. Command Line Arguments:**
```json
{
  "script": {
    "input_method": "args",
    "args_format": "json"
  }
}
```

**2. Environment Variables:**
```json
{
  "script": {
    "input_method": "env",
    "env_prefix": "MCP_"
  }
}
```

**3. Standard Input:**
```json
{
  "script": {
    "input_method": "stdin",
    "stdin_format": "json"
  }
}
```

**4. Temporary File:**
```json
{
  "script": {
    "input_method": "file",
    "input_file_pattern": "/tmp/mcp_input_{uuid}.json"
  }
}
```

### Output Formats

**JSON Output (Recommended):**
```python
import json
print(json.dumps({
    "success": True,
    "data": result_data
}))
```

**Structured Output:**
```json
{
  "script": {
    "output_format": "json",
    "output_schema": {
      "type": "object",
      "properties": {
        "success": {"type": "boolean"},
        "data": {"type": "object"}
      }
    }
  }
}
```

---

## Environment Configuration

### Environment Variables

```json
{
  "script": {
    "environment": {
      "API_KEY": "${external.api.key}",
      "DATABASE_URL": "${db.connection.string}",
      "LOG_LEVEL": "INFO",
      "PYTHONPATH": "./lib:./modules"
    }
  }
}
```

### Working Directory

```json
{
  "script": {
    "working_dir": "/opt/sajha/scripts",
    "create_if_missing": true
  }
}
```

### Virtual Environment (Python)

```json
{
  "script": {
    "type": "python",
    "venv": {
      "enabled": true,
      "path": "./venvs/data_processing",
      "auto_create": true
    }
  }
}
```

---

## Security Considerations

### Sandboxing

```json
{
  "script": {
    "security": {
      "sandboxed": true,
      "allowed_paths": [
        "/tmp",
        "./data",
        "./output"
      ],
      "blocked_commands": [
        "rm -rf",
        "sudo",
        "chmod"
      ],
      "max_memory_mb": 512,
      "max_cpu_percent": 50
    }
  }
}
```

### Resource Limits

```json
{
  "script": {
    "limits": {
      "timeout_seconds": 300,
      "max_output_size_kb": 1024,
      "max_file_size_mb": 100
    }
  }
}
```

### Credential Handling

```json
{
  "script": {
    "credentials": {
      "inject_method": "env",
      "mask_in_logs": true,
      "variables": {
        "DB_PASSWORD": "${db.password}",
        "API_SECRET": "${api.secret}"
      }
    }
  }
}
```

---

## Best Practices

### 1. Error Handling

Always return structured errors:

```python
try:
    result = process_data(args)
    return {"success": True, "data": result}
except ValueError as e:
    return {"success": False, "error": str(e), "error_type": "validation"}
except Exception as e:
    return {"success": False, "error": str(e), "error_type": "internal"}
```

### 2. Logging

Use structured logging:

```python
import logging
import json

logger = logging.getLogger(__name__)

def process(args):
    logger.info(json.dumps({
        "event": "process_start",
        "args": args
    }))
    # ... processing ...
    logger.info(json.dumps({
        "event": "process_complete",
        "result_count": len(results)
    }))
```

### 3. Idempotency

Design scripts to be safely re-runnable:

```python
def process_file(filepath):
    output_path = filepath + ".processed"
    
    # Check if already processed
    if os.path.exists(output_path):
        logger.info("File already processed, skipping")
        return {"status": "skipped", "reason": "already_processed"}
    
    # Process file
    # ...
```

### 4. Testing

Include test mode:

```python
def main(args):
    if args.get('test_mode'):
        return {"success": True, "message": "Test mode - no actions taken"}
    
    # Normal processing
    # ...
```

---

## Examples

### Example 1: CSV Data Analyzer

```json
{
  "name": "csv_analyzer",
  "description": "Analyze CSV files and generate statistics",
  "script": {
    "type": "python",
    "file": "scripts/csv_analyzer.py"
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "file_path": {"type": "string", "required": true},
      "columns": {"type": "array", "items": {"type": "string"}},
      "operations": {
        "type": "array",
        "items": {"type": "string", "enum": ["mean", "median", "std", "count"]}
      }
    }
  }
}
```

### Example 2: Log File Parser

```json
{
  "name": "log_parser",
  "description": "Parse and analyze log files",
  "script": {
    "type": "bash",
    "inline": true,
    "code": "#!/bin/bash\nLOG_FILE=$(echo \"$1\" | jq -r '.log_file')\nPATTERN=$(echo \"$1\" | jq -r '.pattern // \"ERROR\"')\n\nif [ ! -f \"$LOG_FILE\" ]; then\n    echo '{\"success\": false, \"error\": \"Log file not found\"}'\n    exit 1\nfi\n\nMATCHES=$(grep -c \"$PATTERN\" \"$LOG_FILE\" 2>/dev/null || echo 0)\nLAST_MATCH=$(grep \"$PATTERN\" \"$LOG_FILE\" | tail -1)\n\ncat << EOF\n{\n    \"success\": true,\n    \"file\": \"$LOG_FILE\",\n    \"pattern\": \"$PATTERN\",\n    \"match_count\": $MATCHES,\n    \"last_match\": \"$(echo $LAST_MATCH | sed 's/\"/\\\\\"/g')\"\n}\nEOF"
  }
}
```

### Example 3: Database Backup Script

```json
{
  "name": "db_backup",
  "description": "Create database backup",
  "script": {
    "type": "bash",
    "file": "scripts/db_backup.sh",
    "environment": {
      "DB_HOST": "${db.host}",
      "DB_USER": "${db.user}",
      "DB_PASSWORD": "${db.password}"
    }
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "database": {"type": "string", "required": true},
      "output_path": {"type": "string", "default": "/backups"},
      "compress": {"type": "boolean", "default": true}
    }
  }
}
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Script not found | Wrong path | Check file path and permissions |
| Permission denied | No execute permission | Run `chmod +x script.sh` |
| Module not found | Missing dependency | Install required packages |
| Timeout | Long execution | Increase timeout or optimize script |
| JSON parse error | Invalid output | Ensure valid JSON output |

### Debugging

Enable debug mode:

```json
{
  "script": {
    "debug": true,
    "verbose_output": true,
    "preserve_temp_files": true
  }
}
```

Check logs:

```bash
tail -f logs/sajha_mcp.log | grep "Script"
```

---

*SAJHA MCP Server v2.9.8 - Script Tool Creator Guide*
*Copyright © 2025-2030 Ashutosh Sinha*
