# MSDOC Search MCP Tool Reference Guide

**Copyright © 2025-2030 Ashutosh Sinha**  
**Email: ajsinha@gmail.com**  
**All Rights Reserved**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [System Requirements](#system-requirements)
4. [Tool Inventory](#tool-inventory)
5. [Detailed Tool Specifications](#detailed-tool-specifications)
6. [Schema Definitions](#schema-definitions)
7. [Working Mechanism](#working-mechanism)
8. [Authentication & Security](#authentication--security)
9. [Limitations & Constraints](#limitations--constraints)
10. [Sample Code & Usage](#sample-code--usage)
11. [Error Handling](#error-handling)
12. [Performance Considerations](#performance-considerations)
13. [Architecture Diagrams](#architecture-diagrams)

---

## Overview

The **MSDOC Search MCP Tool** is a comprehensive suite of tools designed to interact with Microsoft Office documents (Word and Excel) through a unified Model Context Protocol (MCP) interface. The toolkit provides capabilities for reading, searching, extracting metadata, and analyzing content from `.docx`, `.doc`, `.xlsx`, `.xls`, and `.xlsm` files.

### Key Features

- **Document Reading**: Extract full content from Word and Excel documents
- **Advanced Search**: Search for specific text across documents
- **Metadata Extraction**: Retrieve document properties and metadata
- **Sheet Management**: List and navigate Excel worksheets
- **Text Extraction**: Convert documents to plain text format
- **File Discovery**: List and filter available documents

### Use Cases

- Document management systems
- Content analysis and extraction pipelines
- Document search and indexing
- Data migration and conversion
- Automated report generation
- Document metadata tracking

---

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Client Layer                      │
│            (User Applications/AI Systems)                │
└──────────────────────┬──────────────────────────────────┘
                       │
                       │ MCP Protocol
                       │
┌──────────────────────▼──────────────────────────────────┐
│              MSDOC Tool Registry                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  - msdoc_list_files                               │  │
│  │  - msdoc_read_word                                │  │
│  │  - msdoc_read_excel                               │  │
│  │  - msdoc_search_word                              │  │
│  │  - msdoc_search_excel                             │  │
│  │  - msdoc_get_word_metadata                        │  │
│  │  - msdoc_get_excel_metadata                       │  │
│  │  - msdoc_extract_text                             │  │
│  │  - msdoc_get_excel_sheets                         │  │
│  │  - msdoc_read_excel_sheet                         │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              MsDocBaseTool (Base Class)                  │
│  ┌───────────────────────────────────────────────────┐  │
│  │  - File path resolution                           │  │
│  │  - Directory management                           │  │
│  │  - Word document processing                       │  │
│  │  - Excel document processing                      │  │
│  │  - File type filtering                            │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              External Libraries                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │  - python-docx: Word document processing          │  │
│  │  - openpyxl: Excel spreadsheet processing         │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              File System Layer                           │
│         (data/msdocs directory)                          │
│  - Word Documents (.docx, .doc)                          │
│  - Excel Spreadsheets (.xlsx, .xls, .xlsm)               │
└─────────────────────────────────────────────────────────┘
```

### Component Architecture

```
BaseMCPTool (Abstract)
       │
       │ inherits
       │
MsDocBaseTool (Abstract)
       │
       ├── Shared Functionality:
       │   ├── _get_file_path()
       │   ├── _list_files_by_type()
       │   ├── _read_word_document()
       │   └── _read_excel_document()
       │
       ├── Concrete Tool Classes:
       ├─────► MsDocListFilesTool
       ├─────► MsDocReadWordTool
       ├─────► MsDocReadExcelTool
       ├─────► MsDocSearchWordTool
       ├─────► MsDocSearchExcelTool
       ├─────► MsDocGetWordMetadataTool
       ├─────► MsDocGetExcelMetadataTool
       ├─────► MsDocExtractTextTool
       ├─────► MsDocGetExcelSheetsTool
       └─────► MsDocReadExcelSheetTool
```

---

## System Requirements

### Python Version
- Python 3.7 or higher

### Required Dependencies

```bash
# Core dependencies
python-docx>=0.8.11   # For Word document processing
openpyxl>=3.0.0       # For Excel spreadsheet processing

# Optional but recommended
pathlib               # For path operations (built-in Python 3.4+)
```

### Installation

```bash
pip install python-docx openpyxl
```

### File System Requirements

- Default documents directory: `data/msdocs`
- Configurable via tool configuration
- Requires read permissions on the documents directory
- Automatic directory creation if not exists

---

## Tool Inventory

| Tool Name | Version | Purpose | Document Type |
|-----------|---------|---------|---------------|
| msdoc_list_files | 1.0.0 | List all Word and Excel documents | Both |
| msdoc_read_word | 1.0.0 | Read Word document content | Word |
| msdoc_read_excel | 1.0.0 | Read Excel spreadsheet data | Excel |
| msdoc_search_word | 1.0.0 | Search text in Word documents | Word |
| msdoc_search_excel | 1.0.0 | Search values in Excel spreadsheets | Excel |
| msdoc_get_word_metadata | 1.0.0 | Extract Word document metadata | Word |
| msdoc_get_excel_metadata | 1.0.0 | Extract Excel workbook metadata | Excel |
| msdoc_extract_text | 1.0.0 | Extract plain text from documents | Both |
| msdoc_get_excel_sheets | 1.0.0 | List all Excel worksheets | Excel |
| msdoc_read_excel_sheet | 1.0.0 | Read specific Excel worksheet | Excel |

---

## Detailed Tool Specifications

### 1. msdoc_list_files

**Description**: List all Word and Excel documents in the configured directory

**Category**: Document Processing

**Input Parameters**:
```json
{
  "file_type": {
    "type": "string",
    "enum": ["all", "word", "excel"],
    "default": "all",
    "description": "Type of files to list"
  }
}
```

**Output Schema**:
```json
{
  "directory": "string - Path to documents directory",
  "file_type": "string - Type filter applied",
  "count": "integer - Number of files found",
  "files": [
    {
      "filename": "string",
      "path": "string",
      "extension": "string",
      "size": "integer - File size in bytes",
      "modified": "number - Unix timestamp"
    }
  ]
}
```

**Rate Limit**: 60 requests/minute  
**Cache TTL**: 60 seconds

---

### 2. msdoc_read_word

**Description**: Read and extract content from Word documents including paragraphs and tables

**Category**: Document Processing

**Input Parameters**:
```json
{
  "filename": {
    "type": "string",
    "required": true,
    "description": "Name of the Word file to read (.docx)"
  }
}
```

**Output Schema**:
```json
{
  "filename": "string",
  "paragraphs": ["string array - Text paragraphs"],
  "paragraph_count": "integer",
  "tables": [
    [
      ["string - Cell values"]
    ]
  ],
  "table_count": "integer"
}
```

**Rate Limit**: 60 requests/minute  
**Cache TTL**: 300 seconds

---

### 3. msdoc_read_excel

**Description**: Read and extract data from Excel spreadsheets with optional sheet selection

**Category**: Document Processing

**Input Parameters**:
```json
{
  "filename": {
    "type": "string",
    "required": true,
    "description": "Name of Excel file"
  },
  "sheet_name": {
    "type": "string",
    "optional": true,
    "description": "Name of sheet to read"
  },
  "sheet_index": {
    "type": "integer",
    "optional": true,
    "minimum": 0,
    "description": "0-based sheet index"
  },
  "max_rows": {
    "type": "integer",
    "default": 100,
    "minimum": 1,
    "maximum": 10000,
    "description": "Maximum rows to return"
  },
  "include_formulas": {
    "type": "boolean",
    "default": false,
    "description": "Include cell formulas"
  }
}
```

**Output Schema**:
```json
{
  "filename": "string",
  "sheet_name": "string",
  "data": [["array - 2D array of cell values"]],
  "row_count": "integer",
  "column_count": "integer",
  "formulas": [
    [
      {
        "cell": "string - Cell coordinate (e.g., A1)",
        "formula": "string - Cell formula"
      }
    ]
  ]
}
```

**Rate Limit**: 60 requests/minute  
**Cache TTL**: 300 seconds

---

### 4. msdoc_search_word

**Description**: Search for specific text within Word documents and return matching paragraphs

**Category**: Document Processing

**Input Parameters**:
```json
{
  "filename": {
    "type": "string",
    "required": true,
    "description": "Word file to search"
  },
  "search_term": {
    "type": "string",
    "required": true,
    "description": "Text to search for (case-insensitive)"
  }
}
```

**Output Schema**:
```json
{
  "filename": "string",
  "search_term": "string",
  "matches": [
    {
      "paragraph_index": "integer",
      "text": "string - Full paragraph text"
    }
  ],
  "match_count": "integer"
}
```

**Rate Limit**: 60 requests/minute  
**Cache TTL**: 300 seconds

---

### 5. msdoc_search_excel

**Description**: Search for specific text or values within Excel spreadsheets

**Category**: Document Processing

**Input Parameters**:
```json
{
  "filename": {
    "type": "string",
    "required": true,
    "description": "Excel file to search"
  },
  "search_term": {
    "type": "string",
    "required": true,
    "description": "Text or value to search for (case-insensitive)"
  },
  "sheet_name": {
    "type": "string",
    "optional": true,
    "description": "Sheet to search (optional)"
  }
}
```

**Output Schema**:
```json
{
  "filename": "string",
  "sheet_name": "string",
  "search_term": "string",
  "matches": [
    {
      "row_index": "integer",
      "column_index": "integer",
      "value": "string - Cell value"
    }
  ],
  "match_count": "integer"
}
```

**Rate Limit**: 60 requests/minute  
**Cache TTL**: 300 seconds

---

### 6. msdoc_get_word_metadata

**Description**: Extract metadata and document properties from Word files

**Category**: Document Processing

**Input Parameters**:
```json
{
  "filename": {
    "type": "string",
    "required": true,
    "description": "Word file name"
  }
}
```

**Output Schema**:
```json
{
  "filename": "string",
  "metadata": {
    "author": "string",
    "title": "string",
    "subject": "string",
    "created": "string - ISO datetime",
    "modified": "string - ISO datetime"
  }
}
```

**Rate Limit**: 60 requests/minute  
**Cache TTL**: 3600 seconds

---

### 7. msdoc_get_excel_metadata

**Description**: Extract metadata and workbook properties from Excel files

**Category**: Document Processing

**Input Parameters**:
```json
{
  "filename": {
    "type": "string",
    "required": true,
    "description": "Excel file name"
  }
}
```

**Output Schema**:
```json
{
  "filename": "string",
  "metadata": {
    "creator": "string",
    "title": "string",
    "subject": "string",
    "created": "string - ISO datetime",
    "modified": "string - ISO datetime"
  }
}
```

**Rate Limit**: 60 requests/minute  
**Cache TTL**: 3600 seconds

---

### 8. msdoc_extract_text

**Description**: Extract all plain text content from Word or Excel documents

**Category**: Document Processing

**Input Parameters**:
```json
{
  "filename": {
    "type": "string",
    "required": true,
    "description": "File to extract text from"
  }
}
```

**Output Schema**:
```json
{
  "filename": "string",
  "text": "string - Extracted plain text",
  "character_count": "integer"
}
```

**Rate Limit**: 60 requests/minute  
**Cache TTL**: 300 seconds

---

### 9. msdoc_get_excel_sheets

**Description**: List all worksheets in an Excel workbook

**Category**: Document Processing

**Input Parameters**:
```json
{
  "filename": {
    "type": "string",
    "required": true,
    "description": "Excel file name"
  }
}
```

**Output Schema**:
```json
{
  "filename": "string",
  "sheets": [
    {
      "index": "integer - 0-based index",
      "name": "string - Sheet name"
    }
  ],
  "count": "integer - Total sheets"
}
```

**Rate Limit**: 60 requests/minute  
**Cache TTL**: 3600 seconds

---

### 10. msdoc_read_excel_sheet

**Description**: Read data from a specific worksheet by name or index

**Category**: Document Processing

**Input Parameters**:
```json
{
  "filename": {
    "type": "string",
    "required": true
  },
  "sheet_name": {
    "type": "string",
    "optional": true,
    "description": "Sheet name to read"
  },
  "sheet_index": {
    "type": "integer",
    "optional": true,
    "minimum": 0,
    "description": "0-based sheet index"
  },
  "max_rows": {
    "type": "integer",
    "default": 100,
    "minimum": 1,
    "maximum": 10000
  }
}
```

**Note**: Either `sheet_name` OR `sheet_index` must be provided

**Output Schema**:
```json
{
  "filename": "string",
  "sheet_name": "string",
  "data": [["array - Worksheet data"]],
  "row_count": "integer",
  "column_count": "integer"
}
```

**Rate Limit**: 60 requests/minute  
**Cache TTL**: 300 seconds

---

## Schema Definitions

### Common Data Types

#### FileInfo
```json
{
  "filename": "string - File name with extension",
  "path": "string - Absolute file path",
  "extension": "string - File extension",
  "size": "integer - File size in bytes",
  "modified": "number - Unix timestamp of last modification"
}
```

#### DocumentMetadata (Word)
```json
{
  "author": "string - Document author",
  "title": "string - Document title",
  "subject": "string - Document subject",
  "created": "string - Creation datetime (ISO format)",
  "modified": "string - Last modified datetime (ISO format)"
}
```

#### WorkbookMetadata (Excel)
```json
{
  "creator": "string - Workbook creator",
  "title": "string - Workbook title",
  "subject": "string - Workbook subject",
  "created": "string - Creation datetime (ISO format)",
  "modified": "string - Last modified datetime (ISO format)"
}
```

#### SearchMatch (Word)
```json
{
  "paragraph_index": "integer - 0-based paragraph index",
  "text": "string - Full paragraph containing match"
}
```

#### SearchMatch (Excel)
```json
{
  "row_index": "integer - 0-based row index",
  "column_index": "integer - 0-based column index",
  "value": "string - Cell value containing match"
}
```

#### SheetInfo
```json
{
  "index": "integer - 0-based sheet index",
  "name": "string - Worksheet name"
}
```

#### FormulaInfo
```json
{
  "cell": "string - Cell coordinate (e.g., A1, B2)",
  "formula": "string - Excel formula (starts with =)"
}
```

---

## Working Mechanism

### Data Access Method

**File System Access (Local)**

The MSDOC Search MCP Tool operates entirely on **local file system access**. It does not perform:

- ❌ Web scraping
- ❌ API calls to external services
- ❌ Database queries
- ❌ Network operations
- ❌ Cloud storage access

**Process Flow:**

1. **File Discovery**: Tools scan the configured `data/msdocs` directory
2. **File Reading**: Documents are read directly from the file system using Python libraries
3. **Content Processing**: 
   - **Word**: Uses `python-docx` library to parse `.docx` files
   - **Excel**: Uses `openpyxl` library to parse `.xlsx`, `.xls`, `.xlsm` files
4. **Data Extraction**: Content is extracted in-memory
5. **Result Return**: Processed data is returned as JSON structures

### Processing Pipeline

```
┌─────────────────┐
│  Tool Invocation│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Input Validation│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  File Path      │
│  Resolution     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ File Existence  │
│ Check           │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Library Import  │
│ (docx/openpyxl) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Document Parse  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Content Extract │
│ or Search       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Format Output   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Return JSON     │
└─────────────────┘
```

### Error Handling Flow

```
Error Type          → Handler            → Response
─────────────────────────────────────────────────────
File Not Found      → ValueError         → "File not found: {filename}"
Library Missing     → ImportError        → "Library not installed: {library}"
Invalid Extension   → ValueError         → "Unsupported file type: {ext}"
Read Permission     → PermissionError    → "Access denied: {filename}"
Corrupt File        → Exception          → "Failed to read: {error}"
Invalid Sheet Name  → KeyError           → "Sheet not found: {sheet_name}"
Invalid Sheet Index → IndexError         → "Invalid sheet index: {index}"
```

---

## Authentication & Security

### Authentication Requirements

**None Required**

The MSDOC Search MCP Tool does not require:
- API keys
- OAuth tokens
- Username/password authentication
- Network credentials

### Security Considerations

1. **File System Access**:
   - Tools have read-only access to the `data/msdocs` directory
   - No write or delete operations are performed
   - Directory traversal is limited to configured path

2. **Data Privacy**:
   - All processing occurs locally
   - No data is sent to external services
   - No logging of document content (only errors)

3. **Access Control**:
   - Relies on underlying file system permissions
   - Requires read access to documents directory
   - Recommend appropriate file system ACLs

4. **Safe Operations**:
   - No code execution from documents
   - Macro execution is disabled
   - Only data extraction, no document modification

---

## Limitations & Constraints

### Document Format Limitations

1. **Word Documents**:
   - Only `.docx` format fully supported
   - `.doc` format has limited support
   - Embedded objects not extracted
   - Complex formatting may be lost
   - Comments and tracked changes not extracted
   - Headers and footers may not be included

2. **Excel Spreadsheets**:
   - Maximum 10,000 rows per read operation
   - Charts and images not extracted
   - Complex formulas may not calculate correctly
   - Pivot tables read as static data
   - Conditional formatting not preserved
   - VBA macros not accessible

### Performance Constraints

1. **Large Files**:
   - Files > 100MB may cause memory issues
   - Processing time increases with file size
   - Recommended max file size: 50MB

2. **Search Operations**:
   - Case-insensitive substring matching only
   - No regular expression support
   - No fuzzy matching
   - Sequential search (no indexing)

3. **Rate Limiting**:
   - 60 requests per minute per tool
   - Cache TTL varies by operation
   - No request queuing

### Functional Limitations

1. **Search Capabilities**:
   - Text search only (no semantic search)
   - No multi-file search
   - No wildcard support
   - Results not ranked

2. **Metadata**:
   - Only core properties extracted
   - Custom properties not available
   - Extended attributes not supported

3. **File Operations**:
   - Read-only access
   - No file creation or modification
   - No file deletion
   - No batch operations

### Technical Constraints

1. **Dependencies**:
   - Requires `python-docx` and `openpyxl`
   - Python 3.7+ required
   - Platform-dependent file paths

2. **Encoding**:
   - UTF-8 text encoding assumed
   - Non-UTF-8 characters may cause issues
   - Special characters may not render correctly

---

## Sample Code & Usage

### Python Integration Example

```python
"""
Sample usage of MSDOC Search MCP Tools
"""
import json
from tools.impl.msdoc_tools_tool_refactored import MSDOC_TOOLS

# Initialize configuration
config = {
    'docs_directory': 'data/msdocs',
    'enabled': True
}

# Example 1: List all files
list_tool = MSDOC_TOOLS['msdoc_list_files'](config)
result = list_tool.execute({'file_type': 'all'})
print(f"Found {result['count']} files")
for file in result['files']:
    print(f"  - {file['filename']} ({file['size']} bytes)")

# Example 2: Read Word document
read_word_tool = MSDOC_TOOLS['msdoc_read_word'](config)
result = read_word_tool.execute({'filename': 'report.docx'})
print(f"Document has {result['paragraph_count']} paragraphs")
print(f"Document has {result['table_count']} tables")

# Example 3: Search in Excel
search_excel_tool = MSDOC_TOOLS['msdoc_search_excel'](config)
result = search_excel_tool.execute({
    'filename': 'data.xlsx',
    'search_term': 'revenue'
})
print(f"Found {result['match_count']} matches")
for match in result['matches']:
    print(f"  Row {match['row_index']}, "
          f"Col {match['column_index']}: {match['value']}")

# Example 4: Extract metadata
metadata_tool = MSDOC_TOOLS['msdoc_get_word_metadata'](config)
result = metadata_tool.execute({'filename': 'contract.docx'})
print(f"Author: {result['metadata']['author']}")
print(f"Created: {result['metadata']['created']}")

# Example 5: Get Excel sheets
sheets_tool = MSDOC_TOOLS['msdoc_get_excel_sheets'](config)
result = sheets_tool.execute({'filename': 'workbook.xlsx'})
print(f"Workbook has {result['count']} sheets:")
for sheet in result['sheets']:
    print(f"  {sheet['index']}: {sheet['name']}")

# Example 6: Read specific sheet
read_sheet_tool = MSDOC_TOOLS['msdoc_read_excel_sheet'](config)
result = read_sheet_tool.execute({
    'filename': 'sales.xlsx',
    'sheet_name': 'Q4 Results',
    'max_rows': 50
})
print(f"Sheet '{result['sheet_name']}' has "
      f"{result['row_count']} rows and "
      f"{result['column_count']} columns")

# Example 7: Extract all text
extract_tool = MSDOC_TOOLS['msdoc_extract_text'](config)
result = extract_tool.execute({'filename': 'document.docx'})
print(f"Extracted {result['character_count']} characters")
print(result['text'][:200] + "...")  # First 200 chars

# Example 8: Search Word document
search_word_tool = MSDOC_TOOLS['msdoc_search_word'](config)
result = search_word_tool.execute({
    'filename': 'annual_report.docx',
    'search_term': 'profit'
})
print(f"Found '{result['search_term']}' in "
      f"{result['match_count']} paragraphs")
for match in result['matches']:
    print(f"\nParagraph {match['paragraph_index']}:")
    print(f"  {match['text'][:100]}...")

# Example 9: Read Excel with formulas
read_excel_tool = MSDOC_TOOLS['msdoc_read_excel'](config)
result = read_excel_tool.execute({
    'filename': 'calculations.xlsx',
    'include_formulas': True,
    'max_rows': 100
})
if 'formulas' in result:
    print("Formulas found:")
    for row_formulas in result['formulas']:
        for formula_info in row_formulas:
            print(f"  {formula_info['cell']}: "
                  f"{formula_info['formula']}")

# Example 10: List only Word files
list_word_tool = MSDOC_TOOLS['msdoc_list_files'](config)
result = list_word_tool.execute({'file_type': 'word'})
print(f"Found {result['count']} Word documents")
```

### MCP Protocol Integration

```python
"""
Example MCP server integration
"""
from typing import Dict, Any

class MCPDocumentServer:
    def __init__(self, docs_directory: str = 'data/msdocs'):
        self.config = {'docs_directory': docs_directory}
        self.tools = {}
        
        # Register all tools
        for tool_name, tool_class in MSDOC_TOOLS.items():
            self.tools[tool_name] = tool_class(self.config)
    
    def list_tools(self) -> list:
        """List available tools"""
        return [
            {
                'name': tool_name,
                'description': tool.config.get('description', ''),
                'input_schema': tool.get_input_schema(),
                'output_schema': tool.get_output_schema()
            }
            for tool_name, tool in self.tools.items()
        ]
    
    def execute_tool(self, tool_name: str, 
                     arguments: Dict[str, Any]) -> Dict:
        """Execute a specific tool"""
        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        tool = self.tools[tool_name]
        
        try:
            result = tool.execute(arguments)
            return {
                'success': True,
                'tool': tool_name,
                'result': result
            }
        except Exception as e:
            return {
                'success': False,
                'tool': tool_name,
                'error': str(e),
                'error_type': type(e).__name__
            }

# Usage
server = MCPDocumentServer()

# List available tools
tools = server.list_tools()
print(f"Available tools: {len(tools)}")

# Execute tool
response = server.execute_tool('msdoc_read_word', {
    'filename': 'report.docx'
})
if response['success']:
    print(f"Success: {response['result']}")
else:
    print(f"Error: {response['error']}")
```

### Command-Line Interface Example

```python
"""
CLI wrapper for MSDOC tools
"""
import sys
import json
import argparse
from tools.impl.msdoc_tools_tool_refactored import MSDOC_TOOLS

def main():
    parser = argparse.ArgumentParser(
        description='MSDOC Search MCP Tool CLI'
    )
    parser.add_argument('tool', choices=MSDOC_TOOLS.keys(),
                       help='Tool to execute')
    parser.add_argument('--args', type=str, required=True,
                       help='JSON arguments')
    parser.add_argument('--docs-dir', default='data/msdocs',
                       help='Documents directory')
    
    args = parser.parse_args()
    
    # Parse arguments
    try:
        tool_args = json.loads(args.args)
    except json.JSONDecodeError:
        print("Error: Invalid JSON arguments")
        sys.exit(1)
    
    # Initialize tool
    config = {'docs_directory': args.docs_dir}
    tool = MSDOC_TOOLS[args.tool](config)
    
    # Execute
    try:
        result = tool.execute(tool_args)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
```

**CLI Usage:**

```bash
# List files
python msdoc_cli.py msdoc_list_files \
    --args '{"file_type": "all"}'

# Read Word document
python msdoc_cli.py msdoc_read_word \
    --args '{"filename": "report.docx"}'

# Search Excel
python msdoc_cli.py msdoc_search_excel \
    --args '{"filename": "data.xlsx", "search_term": "total"}'
```

---

## Error Handling

### Error Response Format

All tools return errors in a consistent format:

```python
{
    'error': True,
    'error_type': 'ValueError',
    'message': 'File not found: document.docx',
    'tool': 'msdoc_read_word',
    'timestamp': '2025-10-31T10:30:00Z'
}
```

### Common Error Types

| Error Type | Description | Common Causes | Resolution |
|------------|-------------|---------------|------------|
| ValueError | Invalid input or file | Wrong filename, unsupported format | Check filename and extension |
| ImportError | Missing library | python-docx or openpyxl not installed | Run `pip install` |
| FileNotFoundError | File doesn't exist | Wrong path, file moved | Verify file location |
| PermissionError | Access denied | Insufficient permissions | Check file permissions |
| KeyError | Invalid sheet name | Sheet doesn't exist | List sheets first |
| IndexError | Invalid sheet index | Index out of range | Use valid index (0-based) |

### Error Handling Best Practices

```python
from tools.impl.msdoc_tools_tool_refactored import MSDOC_TOOLS

def safe_execute_tool(tool_name, arguments):
    """Execute tool with comprehensive error handling"""
    try:
        # Initialize tool
        tool = MSDOC_TOOLS[tool_name]()
        
        # Execute
        result = tool.execute(arguments)
        
        return {
            'success': True,
            'data': result
        }
        
    except FileNotFoundError as e:
        return {
            'success': False,
            'error_type': 'file_not_found',
            'message': f"Document not found: {str(e)}",
            'suggestion': "Check the filename and directory"
        }
        
    except ImportError as e:
        return {
            'success': False,
            'error_type': 'missing_library',
            'message': f"Required library not installed: {str(e)}",
            'suggestion': "Run: pip install python-docx openpyxl"
        }
        
    except ValueError as e:
        return {
            'success': False,
            'error_type': 'invalid_input',
            'message': str(e),
            'suggestion': "Verify input parameters"
        }
        
    except Exception as e:
        return {
            'success': False,
            'error_type': 'unknown',
            'message': f"Unexpected error: {str(e)}",
            'suggestion': "Check logs for details"
        }

# Usage
result = safe_execute_tool('msdoc_read_word', {
    'filename': 'report.docx'
})

if result['success']:
    process_data(result['data'])
else:
    print(f"Error: {result['message']}")
    print(f"Suggestion: {result['suggestion']}")
```

---

## Performance Considerations

### Optimization Strategies

1. **Caching**:
```python
from functools import lru_cache

@lru_cache(maxsize=100)
def cached_read_document(filename):
    """Cache document reads"""
    tool = MSDOC_TOOLS['msdoc_read_word']()
    return tool.execute({'filename': filename})
```

2. **Batch Processing**:
```python
def batch_extract_text(filenames):
    """Process multiple files efficiently"""
    tool = MSDOC_TOOLS['msdoc_extract_text']()
    results = []
    
    for filename in filenames:
        try:
            result = tool.execute({'filename': filename})
            results.append(result)
        except Exception as e:
            results.append({'error': str(e), 'filename': filename})
    
    return results
```

3. **Limit Row Reads**:
```python
# Instead of reading all rows
result = tool.execute({
    'filename': 'large_file.xlsx',
    'max_rows': 100  # Limit to 100 rows
})
```

### Performance Metrics

| Operation | Small File (<1MB) | Medium File (1-10MB) | Large File (>10MB) |
|-----------|-------------------|----------------------|--------------------|
| List Files | <100ms | <100ms | <100ms |
| Read Word | 100-500ms | 500ms-2s | 2-10s |
| Read Excel | 200-800ms | 1-5s | 5-30s |
| Search Word | 150-600ms | 600ms-3s | 3-15s |
| Search Excel | 300ms-1s | 1-6s | 6-45s |
| Extract Metadata | <200ms | <500ms | <1s |

---

## Architecture Diagrams

### Tool Execution Flow

```
┌──────────────┐
│   Client     │
│  Request     │
└──────┬───────┘
       │
       │ {tool_name, arguments}
       │
       ▼
┌──────────────────────────────────┐
│      MCP Tool Registry           │
│                                  │
│  Lookup: MSDOC_TOOLS[tool_name]  │
└──────┬───────────────────────────┘
       │
       │ Tool Instance
       │
       ▼
┌──────────────────────────────────┐
│    Tool Class Instance           │
│                                  │
│  ┌────────────────────────────┐  │
│  │  1. Validate Input         │  │
│  │  2. Get File Path          │  │
│  │  3. Check Existence        │  │
│  │  4. Load Document          │  │
│  │  5. Process Content        │  │
│  │  6. Format Output          │  │
│  └────────────────────────────┘  │
└──────┬───────────────────────────┘
       │
       │ Result Dictionary
       │
       ▼
┌──────────────┐
│   Client     │
│  Response    │
└──────────────┘
```

### Class Hierarchy Diagram

```
           BaseMCPTool
                │
                │ (abstract inheritance)
                │
           MsDocBaseTool
         ┌──────┴───────┐
         │              │
    [Shared Methods]  [Configuration]
         │              │
         ├─ _get_file_path()
         ├─ _list_files_by_type()
         ├─ _read_word_document()
         ├─ _read_excel_document()
         │
         └─────┬────────────────────────────┐
               │                            │
    ┌──────────▼──────────┐    ┌───────────▼──────────┐
    │   Word Tools        │    │   Excel Tools         │
    ├────────────────────┤    ├──────────────────────┤
    │ ReadWordTool       │    │ ReadExcelTool        │
    │ SearchWordTool     │    │ SearchExcelTool      │
    │ GetWordMetadata    │    │ GetExcelMetadata     │
    └────────────────────┘    │ GetExcelSheets       │
                              │ ReadExcelSheet       │
    ┌──────────────────────┐  └──────────────────────┘
    │   General Tools      │
    ├─────────────────────┤
    │ ListFilesTool       │
    │ ExtractTextTool     │
    └─────────────────────┘
```

### Data Flow for Search Operation

```
Search Request
      │
      ▼
┌─────────────────┐
│ Validate Input  │
│ - filename      │
│ - search_term   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Resolve Path    │
│ data/msdocs/    │
│  + filename     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Check File      │
│ Exists?         │
└────┬───────┬────┘
     │ No    │ Yes
     │       │
     ▼       ▼
  Error   ┌──────────────┐
          │ Load Document│
          │ (docx/openpyxl)│
          └──────┬───────┘
                 │
                 ▼
          ┌─────────────────┐
          │ Parse Content   │
          │ - Paragraphs    │
          │ - Cells         │
          └──────┬──────────┘
                 │
                 ▼
          ┌─────────────────┐
          │ Search Logic    │
          │ For each item:  │
          │  if term in item│
          │   -> add match  │
          └──────┬──────────┘
                 │
                 ▼
          ┌─────────────────┐
          │ Format Results  │
          │ - matches[]     │
          │ - match_count   │
          └──────┬──────────┘
                 │
                 ▼
          Search Response
```

---

## Appendix A: Configuration Options

### Tool Configuration Schema

```json
{
  "docs_directory": {
    "type": "string",
    "default": "data/msdocs",
    "description": "Path to documents directory"
  },
  "enabled": {
    "type": "boolean",
    "default": true,
    "description": "Enable/disable tool"
  },
  "version": {
    "type": "string",
    "default": "1.0.0",
    "description": "Tool version"
  },
  "cache_ttl": {
    "type": "integer",
    "description": "Cache time-to-live in seconds"
  },
  "rate_limit": {
    "type": "integer",
    "default": 60,
    "description": "Requests per minute"
  }
}
```

---

## Appendix B: File Format Support Matrix

| Format | Extension | Read | Search | Metadata | Tables | Formulas |
|--------|-----------|------|--------|----------|--------|----------|
| Word (DOCX) | .docx | ✅ | ✅ | ✅ | ✅ | ❌ |
| Word (DOC) | .doc | ⚠️ | ⚠️ | ❌ | ⚠️ | ❌ |
| Excel (XLSX) | .xlsx | ✅ | ✅ | ✅ | ✅ | ✅ |
| Excel (XLS) | .xls | ⚠️ | ⚠️ | ⚠️ | ✅ | ⚠️ |
| Excel (XLSM) | .xlsm | ✅ | ✅ | ✅ | ✅ | ✅ |

Legend:
- ✅ Fully supported
- ⚠️ Partially supported or limited functionality
- ❌ Not supported

---

## Appendix C: Quick Reference

### Command Cheat Sheet

```bash
# List all documents
{"file_type": "all"}

# Read Word document
{"filename": "report.docx"}

# Read Excel with formulas
{"filename": "calc.xlsx", "include_formulas": true}

# Search Word
{"filename": "doc.docx", "search_term": "keyword"}

# Search Excel in specific sheet
{"filename": "data.xlsx", "search_term": "value", "sheet_name": "Sheet1"}

# Get metadata
{"filename": "document.docx"}

# Extract all text
{"filename": "file.xlsx"}

# List Excel sheets
{"filename": "workbook.xlsx"}

# Read specific sheet by name
{"filename": "workbook.xlsx", "sheet_name": "Summary"}

# Read specific sheet by index
{"filename": "workbook.xlsx", "sheet_index": 0}
```

---

## Support & Contact

**Copyright © 2025-2030 Ashutosh Sinha**  
**Email:** ajsinha@gmail.com  
**All Rights Reserved**

For issues, questions, or contributions, please contact the author.

---

**Document Version:** 1.0.0  
**Last Updated:** October 31, 2025  
**Status:** Production Ready
