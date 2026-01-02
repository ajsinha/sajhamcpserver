# Investor Relations Tool - Architecture Diagram

## System Overview

```
┌───────────────────────────────────────────────────────────────┐
│                     USER / CLIENT                             │
│                   (Web UI / API Call)                         │
└───────────────────┬───────────────────────────────────────────┘
                    │
                    │ HTTP Request with JSON
                    │ {"action": "get_latest_earnings", "ticker": "TSLA"}
                    │
                    ▼
┌───────────────────────────────────────────────────────────────┐
│              InvestorRelationsTool                            │
│              (Main MCP Tool Entry Point)                      │
│                                                               │
│  • execute(arguments)                                         │
│  • Validates input                                            │
│  • Routes to appropriate action                               │
│  • Handles errors                                             │
└───────────────────┬───────────────────────────────────────────┘
                    │
                    │ ticker = "TSLA"
                    │
                    ▼
┌───────────────────────────────────────────────────────────────┐
│              IRWebScraperFactory                              │
│              (Factory Pattern)                                │
│                                                               │
│  • get_scraper(ticker)                                        │
│  • is_supported(ticker)                                       │
│  • Registry of all scrapers                                   │
└───────────────────┬───────────────────────────────────────────┘
                    │
                    │ Returns TeslaIRScraper instance
                    │
                    ▼
┌───────────────────────────────────────────────────────────────┐
│              BaseIRWebScraper                                 │
│              (Abstract Base Class)                            │
│                                                               │
│  Abstract Methods:                                            │
│  • get_ir_page_url()                                          │
│  • scrape_documents()                                         │
│                                                               │
│  Concrete Helper Methods:                                     │
│  • fetch_page()                                               │
│  • extract_links()                                            │
│  • filter_by_document_type()                                  │
│  • filter_by_year()                                           │
│  • create_document_dict()                                     │
└───────────────────┬───────────────────────────────────────────┘
                    │
                    │ Inheritance
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌──────────────────┐   ┌──────────────────┐
│ TeslaIRScraper   │   │ More Company     │
│ (TSLA)           │   │ Scrapers...      │
│                  │   │                  │
│ • ir_url         │   │ • MicrosoftIR    │
│ • scrape logic   │   │ • CitigroupIR    │
│                  │   │ • BMOIR          │
└────────┬─────────┘   │ • RBCIR          │
         │             │ • JPMorganIR     │
         │             │ • GoldmanSachsIR │
         │             └──────────────────┘
         │
         │ Makes HTTP requests
         │
         ▼
┌───────────────────────────────────────────────────────────────┐
│              Company IR Website                               │
│              (https://ir.tesla.com)                           │
│                                                               │
│  • Annual Reports                                             │
│  • Quarterly Reports                                          │
│  • Earnings Presentations                                     │
│  • Investor Presentations                                     │
│  • Press Releases                                             │
└───────────────────┬───────────────────────────────────────────┘
                    │
                    │ HTML Response
                    │
                    ▼
┌───────────────────────────────────────────────────────────────┐
│              Link Extraction & Parsing                        │
│              (LinkExtractor HTMLParser)                       │
│                                                               │
│  • Parse HTML                                                 │
│  • Extract all <a> tags                                       │
│  • Collect URLs and link text                                │
└───────────────────┬───────────────────────────────────────────┘
                    │
                    │ List of links
                    │
                    ▼
┌───────────────────────────────────────────────────────────────┐
│              Filtering & Classification                       │
│                                                               │
│  • Filter by document type (annual_report, etc.)             │
│  • Filter by year (2024, 2023, etc.)                         │
│  • Filter by file extension (.pdf, .pptx, etc.)              │
│  • Extract metadata (title, date, year)                      │
└───────────────────┬───────────────────────────────────────────┘
                    │
                    │ Filtered & structured documents
                    │
                    ▼
┌───────────────────────────────────────────────────────────────┐
│              Response Formation                               │
│                                                               │
│  {                                                            │
│    "ticker": "TSLA",                                          │
│    "latest_earnings": {                                       │
│      "title": "Q4 2024 Earnings",                            │
│      "url": "https://...",                                    │
│      "type": "earnings_presentation",                         │
│      "year": 2024,                                            │
│      "is_pdf": true                                           │
│    },                                                         │
│    "previous_earnings": [...]                                 │
│  }                                                            │
└───────────────────┬───────────────────────────────────────────┘
                    │
                    │ JSON Response
                    │
                    ▼
┌───────────────────────────────────────────────────────────────┐
│              USER / CLIENT                                    │
│              (Receives structured IR data)                    │
└───────────────────────────────────────────────────────────────┘
```

## Component Interaction Flow

```
┌─────────────────┐
│   User Request  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│ 1. InvestorRelationsTool.execute()                      │
│    • Validates action and ticker                        │
│    • Checks if ticker is supported                      │
└────────┬────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│ 2. IRWebScraperFactory.get_scraper(ticker)              │
│    • Looks up scraper in registry                       │
│    • Creates and returns scraper instance               │
└────────┬────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│ 3. TeslaIRScraper (or other company scraper)            │
│    • get_ir_page_url() → Returns IR page URL            │
│    • scrape_documents() → Fetches and parses documents  │
└────────┬────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│ 4. BaseIRWebScraper Helper Methods                      │
│    • fetch_page(url) → HTTP request                     │
│    • extract_links(html) → Parse HTML                   │
│    • filter_by_document_type() → Apply filters          │
│    • create_document_dict() → Structure data            │
└────────┬────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│ 5. Return Results                                       │
│    • Structured JSON response                           │
│    • Error handling if any step fails                   │
└─────────────────────────────────────────────────────────┘
```

## Class Hierarchy

```
                    BaseMCPTool (from framework)
                           │
                           │ inherits
                           ▼
                 InvestorRelationsTool
                           │
                           │ uses
                           ▼
                 IRWebScraperFactory
                           │
                           │ creates
                           ▼
                  BaseIRWebScraper (ABC)
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
        TeslaIR    MicrosoftIR    CitigroupIR
         (TSLA)       (MSFT)          (C)
              │            │            │
              ▼            ▼            ▼
         BMOIR        RBCIR       JPMorganIR
         (BMO)         (RY)         (JPM)
                           │
                           ▼
                     GoldmanSachsIR
                          (GS)
```

## Data Flow

```
User Input JSON
    ↓
Input Validation
    ↓
Factory Pattern (Get Scraper)
    ↓
Web Scraping (HTTP Request)
    ↓
HTML Parsing (Extract Links)
    ↓
Filtering & Classification
    ↓
Data Structuring
    ↓
JSON Response
```

## Factory Pattern Detail

```
┌───────────────────────────────────────────────────────┐
│          IRWebScraperFactory                          │
│                                                       │
│  Registry (Dict):                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │ "TSLA"  → TeslaIRScraper                    │    │
│  │ "MSFT"  → MicrosoftIRScraper                │    │
│  │ "C"     → CitigroupIRScraper                │    │
│  │ "BMO"   → BMOIRScraper                      │    │
│  │ "RY"    → RBCIRScraper                      │    │
│  │ "JPM"   → JPMorganIRScraper                 │    │
│  │ "GS"    → GoldmanSachsIRScraper             │    │
│  └─────────────────────────────────────────────┘    │
│                                                       │
│  Methods:                                             │
│  • get_scraper(ticker) → Returns scraper instance    │
│  • register_scraper(ticker, class) → Adds to registry│
│  • is_supported(ticker) → Boolean check              │
└───────────────────────────────────────────────────────┘
```

## Web Scraping Process

```
┌─────────────────────┐
│ 1. Fetch IR Page    │
│    (HTTP GET)       │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ 2. Parse HTML       │
│    (LinkExtractor)  │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ 3. Extract Links    │
│    (All <a> tags)   │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ 4. Filter Links     │
│    • By extension   │
│    • By keywords    │
│    • By year        │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ 5. Classify Docs    │
│    • Annual report  │
│    • Quarterly      │
│    • Earnings       │
│    • Presentations  │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ 6. Structure Data   │
│    • Title          │
│    • URL            │
│    • Type           │
│    • Year           │
│    • Metadata       │
└─────────────────────┘
```

## Error Handling Flow

```
                User Request
                     │
                     ▼
        ┌────────────────────────┐
        │ Validate Input         │
        │ • Action required?     │
        │ • Ticker required?     │
        └────────┬───────────────┘
                 │
                 ▼
        ┌────────────────────────┐
        │ Check Ticker Support   │
        │ • Is ticker supported? │
        └────┬───────────┬───────┘
             │           │
     Supported      Unsupported
             │           │
             ▼           ▼
    ┌────────────┐  ┌──────────────────┐
    │Get Scraper │  │Return Error:     │
    └────┬───────┘  │"Not supported"   │
         │          │+ List of         │
         ▼          │  supported tickers│
    ┌────────────┐  └──────────────────┘
    │Scrape Data │
    └────┬───┬───┘
         │   │
    Success Failure
         │   │
         ▼   ▼
   ┌────────┐  ┌──────────────┐
   │Return  │  │Return Error: │
   │Results │  │With details  │
   └────────┘  └──────────────┘
```

## Deployment Architecture

```
┌─────────────────────────────────────────────────────┐
│             SAJHA MCP Server                        │
│                                                     │
│  ┌───────────────────────────────────────────┐    │
│  │         Tool Registry                     │    │
│  │  • investor_relations                     │    │
│  │  • wikipedia                              │    │
│  │  • sec_edgar                              │    │
│  │  • ... other tools                        │    │
│  └───────────────────────────────────────────┘    │
│                                                     │
│  ┌───────────────────────────────────────────┐    │
│  │    /tools/investor_relations_tool.py      │    │
│  │    /tools/base_ir_webscraper.py           │    │
│  │    /tools/company_ir_scrapers.py          │    │
│  │    /tools/ir_webscraper_factory.py        │    │
│  └───────────────────────────────────────────┘    │
│                                                     │
│  ┌───────────────────────────────────────────┐    │
│  │   /config/tools/investor_relations.json   │    │
│  └───────────────────────────────────────────┘    │
│                                                     │
└─────────────────────────────────────────────────────┘
                       │
                       │ HTTP/JSON
                       ▼
┌─────────────────────────────────────────────────────┐
│              Web UI / API Clients                   │
└─────────────────────────────────────────────────────┘
```

## Key Design Principles

### 1. Single Responsibility
```
BaseIRWebScraper      → Common scraping logic
TeslaIRScraper        → Tesla-specific logic
IRWebScraperFactory   → Scraper creation
InvestorRelationsTool → User interface
```

### 2. Open/Closed Principle
```
✅ Open for extension   → Add new company scrapers
❌ Closed for modification → Don't change base class
```

### 3. Dependency Inversion
```
InvestorRelationsTool → Depends on Factory
Factory → Depends on Abstract Base
Concrete Scrapers → Implement Abstract Base
```

### 4. Factory Pattern Benefits
```
• Centralized scraper creation
• Easy to add new companies
• Runtime scraper selection
• Loose coupling
```

---

**This architecture ensures:**
- ✅ Maintainability
- ✅ Scalability
- ✅ Testability
- ✅ Extensibility
- ✅ Reliability