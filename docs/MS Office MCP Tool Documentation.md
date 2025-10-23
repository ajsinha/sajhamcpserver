# MS Office MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The MS Office MCP Tool provides operations for Microsoft Word and Excel files including reading, searching, creating, and analyzing Office documents.

## Configuration
- **Environment Variables:**
  - `OFFICE_DATA_FOLDER` (default: 'data/office_files'): Folder for Office files
- Supports .docx (Word) and .xlsx/.xls (Excel) files
- Document and spreadsheet caching for performance

## Available Methods

### File Management

#### 1. list_files
List available Office files.

**Parameters:**
- `file_type` (default: 'all'): 'word', 'excel', or 'all'

**Returns:**
- File details (name, size, modified date, type)
- File count
- Folder location

### Word Document Operations

#### 2. read_word_document
Read content from a Word document.

**Parameters:**
- `filename`: Document filename (required)
- `max_paragraphs` (default: 50): Maximum paragraphs to return

**Returns:**
- Paragraphs with text and style
- Tables with data
- Headers and footers
- Document statistics

#### 3. search_word_documents
Search for text in Word documents.

**Parameters:**
- `search_term`: Text to search for (required)
- `case_sensitive` (default: False): Case-sensitive search

**Returns:**
- Matching documents
- Match locations (paragraphs, tables)
- Match count per document
- Context around matches

#### 4. get_word_metadata
Get metadata from a Word document.

**Parameters:**
- `filename`: Document filename (required)

**Returns:**
- Document properties (title, author, subject)
- Creation and modification dates
- Statistics (paragraphs, tables, word count)

#### 5. create_word_document
Create a new Word document.

**Parameters:**
- `filename` (default: 'new_document.docx'): Output filename
- `content`: List of content items

**Content Format:**
- Simple string: Creates paragraph
- Dictionary with type='heading': Creates heading
- Dictionary with type='paragraph': Creates paragraph

**Returns:**
- Created filename and path
- Success message

### Excel Operations

#### 6. read_excel_sheet
Read data from an Excel sheet.

**Parameters:**
- `filename`: Excel filename (required)
- `sheet_name` (optional): Specific sheet name
- `max_rows` (default: 100): Maximum rows to return

**Returns:**
- Column names
- Data as list of dictionaries
- Sheet dimensions
- Data types

#### 7. get_excel_sheets
Get list of sheets in an Excel file.

**Parameters:**
- `filename`: Excel filename (required)

**Returns:**
- Sheet names
- Row and column counts per sheet
- Sheet count

#### 8. query_excel_data
Query Excel data with filters.

**Parameters:**
- `filename`: Excel filename (required)
- `sheet_name` (optional): Sheet to query
- `filters`: Dictionary of column-value pairs
- `columns` (optional): Columns to return

**Returns:**
- Filtered data
- Row count
- Applied filters

#### 9. get_excel_statistics
Get statistics from Excel data.

**Parameters:**
- `filename`: Excel filename (required)
- `sheet_name` (optional): Sheet to analyze

**Returns:**
- Shape (rows, columns)
- Column names and types
- Null counts per column
- Unique value counts
- Numeric statistics (mean, median, min, max, std)

#### 10. search_excel_files
Search for values in Excel files.

**Parameters:**
- `search_value`: Value to search for (required)

**Returns:**
- Files containing matches
- Sheet and column locations
- Row indices of matches
- Match counts

#### 11. create_excel_file
Create a new Excel file.

**Parameters:**
- `filename` (default: 'new_spreadsheet.xlsx'): Output filename
- `data`: Dictionary of sheet_name: data pairs

**Data Format:**
- Dictionary or list of dictionaries for each sheet
- Automatically converted to DataFrame

**Returns:**
- Created filename and path
- Sheet names
- Success message

## Document Structure

### Word Document Content
```json
{
  "paragraphs": [
    {
      "index": 0,
      "text": "Paragraph text",
      "style": "Normal"
    }
  ],
  "tables": [
    {
      "index": 0,
      "rows": 5,
      "columns": 3,
      "data": [["cell1", "cell2", "cell3"]]
    }
  ],
  "headers": ["Header text"],
  "footers": ["Footer text"]
}
```

### Excel Data Format
```json
{
  "columns": ["Name", "Value", "Date"],
  "data": [
    {"Name": "Item1", "Value": 100, "Date": "2024-01-15"}
  ],
  "shape": {
    "rows": 100,
    "columns": 3
  },
  "dtypes": {
    "Name": "object",
    "Value": "int64",
    "Date": "datetime64"
  }
}
```

## Example Usage
```python
# List all files
result = office_tool.handle_tool_call('list_files', {
    'file_type': 'all'
})

# Read Word document
result = office_tool.handle_tool_call('read_word_document', {
    'filename': 'report.docx',
    'max_paragraphs': 20
})

# Search in Word documents
result = office_tool.handle_tool_call('search_word_documents', {
    'search_term': 'quarterly results',
    'case_sensitive': False
})

# Get Word metadata
result = office_tool.handle_tool_call('get_word_metadata', {
    'filename': 'report.docx'
})

# Read Excel sheet
result = office_tool.handle_tool_call('read_excel_sheet', {
    'filename': 'data.xlsx',
    'sheet_name': 'Sheet1',
    'max_rows': 50
})

# Query Excel data
result = office_tool.handle_tool_call('query_excel_data', {
    'filename': 'sales.xlsx',
    'filters': {'Region': 'North', 'Product': 'Laptop'},
    'columns': ['Date', 'Amount']
})

# Get Excel statistics
result = office_tool.handle_tool_call('get_excel_statistics', {
    'filename': 'data.xlsx'
})

# Create Word document
result = office_tool.handle_tool_call('create_word_document', {
    'filename': 'new_report.docx',
    'content': [
        {'type': 'heading', 'text': 'Report Title', 'level': 1},
        'This is a paragraph.',
        {'type': 'paragraph', 'text': 'Another paragraph.'}
    ]
})

# Create Excel file
result = office_tool.handle_tool_call('create_excel_file', {
    'filename': 'new_data.xlsx',
    'data': {
        'Sheet1': [
            {'Name': 'Item1', 'Value': 100},
            {'Name': 'Item2', 'Value': 200}
        ],
        'Sheet2': [
            {'Date': '2024-01-15', 'Amount': 1000}
        ]
    }
})
```

## Supported Features

### Word Documents
- Read paragraphs with styles
- Extract tables
- Search across documents
- Access headers/footers
- Document metadata
- Create new documents

### Excel Spreadsheets
- Read multiple sheets
- Filter and query data
- Statistical analysis
- Search across files
- Create new spreadsheets
- Support for formulas and formatting (read-only)

## Limitations

- Word: Limited to .docx format (not .doc)
- Excel: Best support for .xlsx format
- Large files may impact performance
- Formatting preserved in read operations only
- Complex Word features (images, charts) have limited support
- Excel formulas read as values


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.