# Integration Guide - Enhanced IR Scraper into Your MCP Server

## 📁 Required Directory Structure

```
your-mcp-server/
├── tools/
│   ├── base_mcp_tool.py                          # Your existing base class
│   └── impl/
│       └── investor_relations_tool.py            # REPLACE with enhanced version
├── ir/                                            # NEW directory
│   ├── __init__.py                               # NEW
│   ├── http_client.py                            # NEW
│   ├── company_database.py                       # NEW
│   ├── sec_edgar.py                              # NEW
│   ├── enhanced_base_scraper.py                  # NEW
│   ├── generic_ir_scraper.py                     # NEW
│   └── enhanced_factory.py                       # NEW
├── config/                                        # NEW or existing
│   └── sp500_companies.json                      # NEW
└── investor_relations.json                        # UPDATE with new schema
```

## 🔧 Step-by-Step Integration

### Step 1: Create IR Package Directory

```bash
mkdir -p ir
touch ir/__init__.py
```

### Step 2: Copy Enhanced Files to IR Directory

Copy these files to `ir/` directory:
- `http_client.py`
- `company_database.py`
- `sec_edgar.py`
- `enhanced_base_scraper.py`
- `generic_ir_scraper.py`
- `enhanced_factory.py`

### Step 3: Copy Configuration File

```bash
mkdir -p config
cp sp500_companies.json config/
```

### Step 4: Update Enhanced Tool File

The `enhanced_investor_relations_tool.py` should be placed at:
```
tools/impl/investor_relations_tool.py
```

Or if you want to keep both versions:
```
tools/impl/investor_relations_tool.py           # Old version (backup)
tools/impl/enhanced_investor_relations_tool.py  # New version
```

### Step 5: Update Tool Registration

In your tool registration file, update to use the enhanced tool:

**Option A: Replace existing tool**
```python
# In tools/impl/investor_relations_tool.py
from tools.base_mcp_tool import BaseMCPTool
from ir.enhanced_factory import EnhancedIRScraperFactory
from ir.company_database import CompanyDatabase

class InvestorRelationsTool(BaseMCPTool):
    # ... use enhanced implementation
```

**Option B: Register as new tool**
```python
from tools.impl.enhanced_investor_relations_tool import EnhancedInvestorRelationsTool

# Register in your tool registry
tool_registry.register('investor_relations', EnhancedInvestorRelationsTool)
```

### Step 6: Update Tool Configuration JSON

Update `investor_relations.json`:

```json
{
  "name": "investor_relations",
  "implementation": "tools.impl.investor_relations_tool.InvestorRelationsTool",
  "description": "Find investor relations documents and links for public companies with SEC EDGAR fallback. Supports 500+ companies.",
  "version": "2.0.1",
  "enabled": true,
  "config": {
    "company_config_file": "config/sp500_companies.json",
    "use_sec_fallback": true
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "action": {
        "type": "string",
        "description": "Action to perform",
        "enum": [
          "find_ir_page",
          "get_documents",
          "get_latest_earnings",
          "get_annual_reports",
          "get_quarterly_reports",
          "get_presentations",
          "get_all_resources",
          "list_supported_companies",
          "get_company_info",
          "search_documents",
          "add_company"
        ]
      },
      "ticker": {
        "type": "string",
        "description": "Stock ticker symbol (e.g., TSLA, MSFT, JPM)"
      },
      "document_type": {
        "type": "string",
        "description": "Type of document to search for",
        "enum": [
          "annual_report",
          "quarterly_report",
          "earnings_presentation",
          "investor_presentation",
          "proxy_statement",
          "press_release",
          "esg_report",
          "all"
        ]
      },
      "year": {
        "type": "integer",
        "description": "Year for documents (e.g., 2024, 2023)",
        "minimum": 2000,
        "maximum": 2030
      },
      "quarter": {
        "type": "string",
        "description": "Quarter for documents (Q1, Q2, Q3, Q4)",
        "enum": ["Q1", "Q2", "Q3", "Q4"]
      },
      "limit": {
        "type": "integer",
        "description": "Maximum number of documents to return",
        "default": 10,
        "minimum": 1,
        "maximum": 50
      },
      "keywords": {
        "type": "array",
        "description": "Keywords to search for in documents",
        "items": {"type": "string"}
      }
    },
    "required": ["action"]
  },
  "metadata": {
    "author": "Ashutosh Sinha",
    "category": "Financial Analysis",
    "tags": ["investor relations", "financial reports", "earnings", "SEC EDGAR"],
    "features": [
      "Bot detection avoidance",
      "SEC EDGAR fallback",
      "Rate limiting",
      "500+ S&P 500 companies"
    ]
  }
}
```

## 📝 Update __init__.py Files

### ir/__init__.py
```python
"""
Enhanced Investor Relations Package
"""

from .http_client import EnhancedHTTPClient, RateLimiter
from .company_database import CompanyDatabase, CompanyConfig
from .sec_edgar import SECEdgarClient
from .enhanced_base_scraper import EnhancedBaseIRScraper
from .generic_ir_scraper import GenericIRScraper
from .enhanced_factory import EnhancedIRScraperFactory

__all__ = [
    'EnhancedHTTPClient',
    'RateLimiter',
    'CompanyDatabase',
    'CompanyConfig',
    'SECEdgarClient',
    'EnhancedBaseIRScraper',
    'GenericIRScraper',
    'EnhancedIRScraperFactory',
]

__version__ = '2.0.1'
```

## 🧪 Testing the Integration

### Test 1: Import Test
```python
# Test imports work
from tools.impl.investor_relations_tool import InvestorRelationsTool
from ir.enhanced_factory import EnhancedIRScraperFactory

print("✓ Imports successful")
```

### Test 2: Tool Initialization
```python
tool = InvestorRelationsTool(config={
    'company_config_file': 'config/sp500_companies.json',
    'use_sec_fallback': True
})

print(f"✓ Tool initialized: {tool.name}")
print(f"✓ Version: {tool.version}")
```

### Test 3: List Companies
```python
result = tool.execute({'action': 'list_supported_companies'})

if result.get('success'):
    print(f"✓ Supports {result['total_supported']} companies")
else:
    print("✗ Failed to list companies")
```

### Test 4: Scrape Documents
```python
result = tool.execute({
    'action': 'get_latest_earnings',
    'ticker': 'AAPL'
})

if result.get('success'):
    print("✓ Successfully scraped documents")
else:
    print(f"✗ Failed: {result.get('error')}")
```

## 🔄 Backwards Compatibility

If you need to maintain backwards compatibility with existing code:

### Option 1: Wrapper Class
```python
# tools/impl/investor_relations_tool.py
from tools.impl.enhanced_investor_relations_tool import EnhancedInvestorRelationsTool

# Alias for backwards compatibility
InvestorRelationsTool = EnhancedInvestorRelationsTool
```

### Option 2: Keep Both Versions
```python
# Register both tools
from tools.impl.investor_relations_tool import InvestorRelationsTool  # Old
from tools.impl.enhanced_investor_relations_tool import EnhancedInvestorRelationsTool  # New

# Users can choose which to use
tool_registry.register('investor_relations', InvestorRelationsTool)
tool_registry.register('investor_relations_v2', EnhancedInvestorRelationsTool)
```

## 🚨 Important Notes

### 1. Path Updates in Enhanced Tool
Make sure the enhanced tool imports use the correct paths:

```python
# In enhanced_investor_relations_tool.py
from tools.base_mcp_tool import BaseMCPTool  # Your base class
from ir.enhanced_factory import EnhancedIRScraperFactory
from ir.company_database import CompanyDatabase
```

### 2. Configuration File Path
The tool needs to find `sp500_companies.json`. Options:

**Absolute path:**
```python
config = {
    'company_config_file': '/absolute/path/to/config/sp500_companies.json'
}
```

**Relative path:**
```python
config = {
    'company_config_file': 'config/sp500_companies.json'
}
```

**Dynamic path:**
```python
from pathlib import Path

config_dir = Path(__file__).parent.parent / 'config'
config = {
    'company_config_file': str(config_dir / 'sp500_companies.json')
}
```

### 3. Python Version
Requires Python 3.8+ (uses typing features)

### 4. No External Dependencies
All code uses Python standard library only

## 📊 Verifying the Integration

### Check List
- [ ] `ir/` directory created with all files
- [ ] `config/sp500_companies.json` in place
- [ ] `ir/__init__.py` created
- [ ] Tool file updated with correct imports
- [ ] Tool registered in tool registry
- [ ] Configuration JSON updated
- [ ] Test imports work
- [ ] Test tool initialization
- [ ] Test listing companies
- [ ] Test scraping documents

### Common Issues

**Issue: ImportError for ir package**
```python
# Solution: Add ir package to Python path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
```

**Issue: Config file not found**
```python
# Solution: Use absolute path or verify working directory
import os
config_path = os.path.abspath('config/sp500_companies.json')
```

**Issue: BaseMCPTool not found**
```python
# Solution: Verify import path matches your structure
from tools.base_mcp_tool import BaseMCPTool
# or
from your_package.tools.base_mcp_tool import BaseMCPTool
```

## 🎉 Success!

Once integrated, you should be able to:
- Scrape investor relations pages for 500+ companies
- Automatically fall back to SEC EDGAR
- Avoid bot detection with smart rate limiting
- Add new companies via JSON configuration

## 📞 Support

If you encounter issues:
1. Check the test imports
2. Verify file paths are correct
3. Review logs for specific errors
4. Ensure config file is accessible
5. Test with a simple company first (e.g., AAPL)
