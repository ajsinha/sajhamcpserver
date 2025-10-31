# Investor Relations Tool - Testing Guide

## Quick Start Tests

### Test 1: List All Supported Companies
```json
{
  "action": "list_supported_companies"
}
```

✅ **Expected Result**: List of 7 companies (TSLA, MSFT, C, BMO, RY, JPM, GS)

---

### Test 2: Find IR Pages (All Companies)

**Tesla:**
```json
{"action": "find_ir_page", "ticker": "TSLA"}
```
Expected: `https://ir.tesla.com`

**Microsoft:**
```json
{"action": "find_ir_page", "ticker": "MSFT"}
```
Expected: `https://www.microsoft.com/en-us/investor`

**Citigroup:**
```json
{"action": "find_ir_page", "ticker": "C"}
```
Expected: `https://www.citigroup.com/global/investors`

**Bank of Montreal:**
```json
{"action": "find_ir_page", "ticker": "BMO"}
```
Expected: `https://investor.bmo.com/english`

**Royal Bank of Canada:**
```json
{"action": "find_ir_page", "ticker": "RY"}
```
Expected: `https://www.rbc.com/investor-relations`

**JPMorgan Chase:**
```json
{"action": "find_ir_page", "ticker": "JPM"}
```
Expected: `https://www.jpmorganchase.com/ir`

**Goldman Sachs:**
```json
{"action": "find_ir_page", "ticker": "GS"}
```
Expected: `https://www.goldmansachs.com/investor-relations`

---

### Test 3: Get Latest Earnings

**Tesla Latest Earnings:**
```json
{
  "action": "get_latest_earnings",
  "ticker": "TSLA"
}
```

**Microsoft Latest Earnings:**
```json
{
  "action": "get_latest_earnings",
  "ticker": "MSFT"
}
```

**JPMorgan Latest Earnings:**
```json
{
  "action": "get_latest_earnings",
  "ticker": "JPM"
}
```

✅ **Expected Result**: JSON with latest earnings document and previous earnings

---

### Test 4: Get Annual Reports

**Tesla Annual Reports (Last 3):**
```json
{
  "action": "get_annual_reports",
  "ticker": "TSLA",
  "limit": 3
}
```

**Microsoft Annual Reports (Last 5):**
```json
{
  "action": "get_annual_reports",
  "ticker": "MSFT",
  "limit": 5
}
```

**Goldman Sachs Annual Reports:**
```json
{
  "action": "get_annual_reports",
  "ticker": "GS",
  "limit": 3
}
```

✅ **Expected Result**: List of annual reports sorted by year (newest first)

---

### Test 5: Get Presentations

**Citigroup Presentations:**
```json
{
  "action": "get_presentations",
  "ticker": "C",
  "limit": 10
}
```

**RBC Presentations:**
```json
{
  "action": "get_presentations",
  "ticker": "RY",
  "limit": 5
}
```

✅ **Expected Result**: List of investor and earnings presentations

---

### Test 6: Get Specific Document Types

**Tesla Quarterly Reports:**
```json
{
  "action": "get_documents",
  "ticker": "TSLA",
  "document_type": "quarterly_report",
  "limit": 5
}
```

**Microsoft Earnings Presentations:**
```json
{
  "action": "get_documents",
  "ticker": "MSFT",
  "document_type": "earnings_presentation",
  "limit": 10
}
```

**JPMorgan Proxy Statements:**
```json
{
  "action": "get_documents",
  "ticker": "JPM",
  "document_type": "proxy_statement",
  "limit": 3
}
```

✅ **Expected Result**: Filtered list of specific document type

---

### Test 7: Filter by Year

**Tesla 2024 Documents:**
```json
{
  "action": "get_documents",
  "ticker": "TSLA",
  "year": 2024,
  "limit": 10
}
```

**Microsoft 2023 Annual Report:**
```json
{
  "action": "get_documents",
  "ticker": "MSFT",
  "document_type": "annual_report",
  "year": 2023
}
```

✅ **Expected Result**: Only documents from specified year

---

### Test 8: Get All Resources

**Tesla All Resources:**
```json
{
  "action": "get_all_resources",
  "ticker": "TSLA"
}
```

**Citigroup All Resources:**
```json
{
  "action": "get_all_resources",
  "ticker": "C"
}
```

**Goldman Sachs All Resources:**
```json
{
  "action": "get_all_resources",
  "ticker": "GS"
}
```

✅ **Expected Result**: Comprehensive package with IR page, annual reports, earnings, and presentations

---

### Test 9: Error Handling - Unsupported Ticker

**Unsupported Ticker:**
```json
{
  "action": "find_ir_page",
  "ticker": "AAPL"
}
```

✅ **Expected Result**: 
```json
{
  "ticker": "AAPL",
  "supported": false,
  "message": "Ticker AAPL is not currently supported",
  "supported_tickers": ["BMO", "C", "GS", "JPM", "MSFT", "RY", "TSLA"],
  "suggestion": "Please use one of the supported tickers..."
}
```

---

### Test 10: Error Handling - Missing Ticker

**Missing Ticker:**
```json
{
  "action": "get_documents"
}
```

✅ **Expected Result**: Error message indicating ticker is required

---

## Comprehensive Test Matrix

| Ticker | find_ir_page | get_latest_earnings | get_annual_reports | get_presentations | get_all_resources |
|--------|--------------|---------------------|-------------------|-------------------|-------------------|
| TSLA   | ✓            | ✓                   | ✓                 | ✓                 | ✓                 |
| MSFT   | ✓            | ✓                   | ✓                 | ✓                 | ✓                 |
| C      | ✓            | ✓                   | ✓                 | ✓                 | ✓                 |
| BMO    | ✓            | ✓                   | ✓                 | ✓                 | ✓                 |
| RY     | ✓            | ✓                   | ✓                 | ✓                 | ✓                 |
| JPM    | ✓            | ✓                   | ✓                 | ✓                 | ✓                 |
| GS     | ✓            | ✓                   | ✓                 | ✓                 | ✓                 |

## Document Type Filter Tests

Test each document type filter with different companies:

### Annual Reports
```json
{"action": "get_documents", "ticker": "TSLA", "document_type": "annual_report", "limit": 3}
{"action": "get_documents", "ticker": "JPM", "document_type": "annual_report", "limit": 3}
```

### Quarterly Reports
```json
{"action": "get_documents", "ticker": "MSFT", "document_type": "quarterly_report", "limit": 5}
{"action": "get_documents", "ticker": "C", "document_type": "quarterly_report", "limit": 5}
```

### Earnings Presentations
```json
{"action": "get_documents", "ticker": "GS", "document_type": "earnings_presentation", "limit": 5}
{"action": "get_documents", "ticker": "RY", "document_type": "earnings_presentation", "limit": 5}
```

### Investor Presentations
```json
{"action": "get_documents", "ticker": "BMO", "document_type": "investor_presentation", "limit": 5}
{"action": "get_documents", "ticker": "TSLA", "document_type": "investor_presentation", "limit": 5}
```

### ESG Reports
```json
{"action": "get_documents", "ticker": "MSFT", "document_type": "esg_report", "limit": 3}
{"action": "get_documents", "ticker": "GS", "document_type": "esg_report", "limit": 3}
```

## Year Filter Tests

Test year filtering across multiple years:

```json
{"action": "get_documents", "ticker": "TSLA", "year": 2024, "limit": 10}
{"action": "get_documents", "ticker": "MSFT", "year": 2023, "limit": 10}
{"action": "get_documents", "ticker": "JPM", "year": 2022, "limit": 10}
```

## Combined Filter Tests

Test multiple filters together:

```json
{
  "action": "get_documents",
  "ticker": "TSLA",
  "document_type": "annual_report",
  "year": 2024
}
```

```json
{
  "action": "get_documents",
  "ticker": "GS",
  "document_type": "earnings_presentation",
  "year": 2023,
  "limit": 5
}
```

## Performance Tests

### Test Caching
1. Run any query
2. Run the same query again immediately
3. Verify second response is faster (cached)

### Test Rate Limiting
1. Send 35 requests in 1 minute
2. Verify rate limiting kicks in around 30 requests

### Test Timeout Handling
Simulate slow network and verify timeout handling works

## Expected Response Structure

### Successful Response
```json
{
  "ticker": "TSLA",
  "action": "get_documents",
  "success": true,
  "documents": [
    {
      "title": "Q4 2024 Update",
      "url": "https://ir.tesla.com/...",
      "type": "earnings_presentation",
      "year": 2024,
      "date": null,
      "description": null,
      "ticker": "TSLA",
      "is_pdf": true
    }
  ]
}
```

### Error Response
```json
{
  "ticker": "AAPL",
  "supported": false,
  "message": "Ticker AAPL is not currently supported",
  "supported_tickers": [...]
}
```

## Validation Checklist

- [ ] All 7 supported tickers work
- [ ] `list_supported_companies` returns correct list
- [ ] `find_ir_page` returns correct URLs
- [ ] `get_latest_earnings` returns recent earnings
- [ ] `get_annual_reports` returns annual reports
- [ ] `get_presentations` returns presentations
- [ ] `get_all_resources` returns comprehensive data
- [ ] Document type filtering works
- [ ] Year filtering works
- [ ] Combined filters work
- [ ] Unsupported tickers handled gracefully
- [ ] Missing parameters caught with proper error messages
- [ ] Response format is consistent
- [ ] URLs are valid and accessible
- [ ] Document years are correctly extracted
- [ ] PDF detection works
- [ ] No duplicate documents in results
- [ ] Results sorted by year (newest first)

## Common Issues & Solutions

### Issue: No documents returned
**Possible Causes:**
- Website structure changed
- Documents not available yet for the year
- Filters too restrictive

**Solution:**
- Check IR page manually
- Try without year filter
- Try with `document_type: "all"`

### Issue: Wrong document type detected
**Possible Causes:**
- Ambiguous document title
- New document naming convention

**Solution:**
- Update document patterns in base class
- Add company-specific pattern overrides

### Issue: Timeout errors
**Possible Causes:**
- Slow website
- Network issues
- Rate limiting by website

**Solution:**
- Increase timeout value
- Add retry logic
- Wait before retrying

## Automated Test Script

```python
# test_investor_relations.py

test_cases = [
    # Basic tests
    {"action": "list_supported_companies"},
    {"action": "find_ir_page", "ticker": "TSLA"},
    {"action": "get_latest_earnings", "ticker": "MSFT"},
    {"action": "get_annual_reports", "ticker": "JPM", "limit": 3},
    {"action": "get_presentations", "ticker": "GS", "limit": 5},
    {"action": "get_all_resources", "ticker": "C"},
    
    # Filter tests
    {"action": "get_documents", "ticker": "TSLA", "document_type": "annual_report"},
    {"action": "get_documents", "ticker": "MSFT", "year": 2024},
    {"action": "get_documents", "ticker": "JPM", "document_type": "earnings_presentation", "year": 2024},
    
    # Error handling
    {"action": "find_ir_page", "ticker": "AAPL"},  # Unsupported
    {"action": "get_documents"},  # Missing ticker
]

for test in test_cases:
    result = investor_relations_tool.execute(test)
    validate_response(result)
```

---

## Success Criteria

✅ **All tests pass**  
✅ **No crashes or exceptions**  
✅ **Consistent response format**  
✅ **Reasonable response times (< 15 seconds)**  
✅ **Accurate document classification**  
✅ **Proper error handling**  
✅ **All supported companies work**

---

**Testing Status**: Ready for Testing  
**Last Updated**: 2025  
**Version**: 1.0.0