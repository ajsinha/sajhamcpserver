# Quick Reference Guide

## SEC EDGAR - Common Operations

### Search Company
```python
{"action": "search_company", "ticker": "AAPL"}
{"action": "search_company", "company_name": "Apple"}
```

### Get Company Info
```python
{"action": "get_company_info", "ticker": "AAPL"}
{"action": "get_company_info", "cik": "0000320193"}
```

### Get Filings
```python
# Recent 10-K filings
{"action": "get_company_filings", "ticker": "AAPL", "filing_type": "10-K", "limit": 5}

# Recent 10-Q filings
{"action": "get_company_filings", "ticker": "MSFT", "filing_type": "10-Q", "limit": 4}

# Insider trading (Form 4)
{"action": "get_insider_trading", "ticker": "TSLA", "limit": 10}
```

### Get Financial Data
```python
{"action": "get_financial_data", "ticker": "AAPL", "fact_type": "Assets"}
{"action": "get_financial_data", "ticker": "AAPL", "fact_type": "Revenues"}
{"action": "get_company_facts", "ticker": "AAPL"}
```

---

## World Bank - Common Operations

### Country Data
```python
{"action": "get_country_data", "country_code": "USA"}
{"action": "get_countries", "income_level": "HIC"}
{"action": "get_countries", "region": "NAC"}
```

### GDP Indicators
```python
{"action": "get_indicator_data", "country_code": "USA", "indicator": "gdp", "start_year": 2015}
{"action": "get_indicator_data", "country_code": "CHN", "indicator": "gdp_growth", "start_year": 2010}
{"action": "get_indicator_data", "country_code": "IND", "indicator": "gdp_per_capita", "start_year": 2015}
```

### Population & Demographics
```python
{"action": "get_indicator_data", "country_code": "USA", "indicator": "population"}
{"action": "get_indicator_data", "country_code": "JPN", "indicator": "life_expectancy", "start_year": 2000}
{"action": "get_indicator_data", "country_code": "DEU", "indicator": "urban_population"}
```

### Compare Countries
```python
{"action": "compare_countries", "country_codes": ["USA", "CHN", "JPN"], "indicator": "gdp_per_capita", "start_year": 2015}
{"action": "compare_countries", "country_codes": ["IND", "IDN", "BRA"], "indicator": "inflation", "start_year": 2018}
```

### Search Indicators
```python
{"action": "search_indicators", "search_term": "renewable energy"}
{"action": "search_indicators", "search_term": "poverty"}
{"action": "search_indicators", "search_term": "education"}
```

---

## IMF - Common Operations

### Exchange Rates
```python
{"action": "get_ifs_data", "country_code": "US", "indicator": "exchange_rate", "frequency": "M"}
{"action": "get_ifs_data", "country_code": "GB", "indicator": "exchange_rate_avg", "start_year": 2020}
```

### Interest Rates
```python
{"action": "get_ifs_data", "country_code": "US", "indicator": "policy_rate", "frequency": "M"}
{"action": "get_ifs_data", "country_code": "CA", "indicator": "lending_rate", "start_year": 2020}
```

### Prices & Inflation
```python
{"action": "get_ifs_data", "country_code": "US", "indicator": "cpi", "frequency": "M"}
{"action": "get_weo_data", "country_code": "US", "indicator": "inflation_avg", "start_year": 2015}
```

### Economic Outlook
```python
{"action": "get_weo_data", "country_code": "US", "indicator": "gdp_growth"}
{"action": "get_weo_data", "country_code": "CN", "indicator": "unemployment"}
{"action": "get_weo_data", "country_code": "JP", "indicator": "current_account"}
```

### Country Profile
```python
{"action": "get_country_profile", "country_code": "US"}
{"action": "get_country_profile", "country_code": "CN"}
```

### Compare Countries
```python
{"action": "compare_countries", "country_codes": ["US", "CN", "JP"], "database": "WEO", "indicator": "gdp_growth"}
{"action": "compare_countries", "country_codes": ["US", "GB", "CA"], "database": "IFS", "indicator": "cpi"}
```

---

## United Nations - Common Operations

### Sustainable Development Goals
```python
# Get all SDGs
{"action": "get_sdgs"}

# Get indicators for Climate Action (SDG 13)
{"action": "get_sdg_indicators", "sdg_code": "13"}

# Get targets for Clean Energy (SDG 7)
{"action": "get_sdg_targets", "sdg_code": "7"}
```

### SDG Data
```python
# Poverty data (SDG 1)
{"action": "get_sdg_data", "indicator_code": "1.1.1", "country_code": "USA", "start_year": 2015}

# Health data (SDG 3)
{"action": "get_sdg_data", "indicator_code": "3.1.1", "country_code": "IND", "start_year": 2015}

# Education data (SDG 4)
{"action": "get_sdg_data", "indicator_code": "4.1.1", "country_code": "BRA"}
```

### Country Progress
```python
{"action": "get_sdg_progress", "country_code": "USA", "sdg_code": "13"}
{"action": "get_sdg_progress", "country_code": "CHN", "sdg_code": "7"}
```

---

## Common Country Codes

### ISO 2-Letter (IMF, World Bank)
- **US** - United States
- **CN** - China
- **JP** - Japan
- **DE** - Germany
- **GB** - United Kingdom
- **FR** - France
- **IN** - India
- **IT** - Italy
- **BR** - Brazil
- **CA** - Canada
- **AU** - Australia
- **KR** - South Korea
- **MX** - Mexico
- **ES** - Spain
- **RU** - Russia

### ISO 3-Letter (UN, World Bank)
- **USA** - United States
- **CHN** - China
- **JPN** - Japan
- **DEU** - Germany
- **GBR** - United Kingdom
- **FRA** - France
- **IND** - India
- **ITA** - Italy
- **BRA** - Brazil
- **CAN** - Canada
- **AUS** - Australia
- **KOR** - South Korea
- **MEX** - Mexico
- **ESP** - Spain
- **RUS** - Russia

---

## Popular Indicators Reference

### World Bank Top Indicators
| Indicator | Code | Description |
|-----------|------|-------------|
| GDP | NY.GDP.MKTP.CD | GDP (current US$) |
| GDP per capita | NY.GDP.PCAP.CD | GDP per capita (current US$) |
| GDP growth | NY.GDP.MKTP.KD.ZG | GDP growth (annual %) |
| Population | SP.POP.TOTL | Population, total |
| Life expectancy | SP.DYN.LE00.IN | Life expectancy at birth |
| Unemployment | SL.UEM.TOTL.ZS | Unemployment, total (% of labor force) |
| Inflation | FP.CPI.TOTL.ZG | Inflation, consumer prices (annual %) |
| Exports | NE.EXP.GNFS.CD | Exports of goods and services (current US$) |
| Imports | NE.IMP.GNFS.CD | Imports of goods and services (current US$) |
| CO2 emissions | EN.ATM.CO2E.PC | CO2 emissions (metric tons per capita) |

### IMF IFS Common Indicators
| Indicator | Code | Description |
|-----------|------|-------------|
| Exchange Rate | ENDA_XDC_USD_RATE | End of Period Exchange Rate |
| Policy Rate | FPOLM_PA | Monetary Policy-Related Interest Rate |
| CPI | PCPI_IX | Consumer Price Index |
| Int'l Reserves | RAXG_USD | Total Reserves (Gold excluded) |
| GDP | NGDP_XDC | Gross Domestic Product (Current) |

### IMF WEO Common Indicators
| Indicator | Code | Description |
|-----------|------|-------------|
| GDP growth | NGDP_RPCH | GDP growth (annual %) |
| Inflation | PCPIPCH | Inflation, average consumer prices |
| Unemployment | LUR | Unemployment rate |
| Current Account | BCA_NGDPD | Current account balance (% of GDP) |
| Public Debt | GGXWDG_NGDP | General government gross debt |

---

## Filing Types Reference (SEC EDGAR)

| Form | Description |
|------|-------------|
| 10-K | Annual Report |
| 10-Q | Quarterly Report |
| 8-K | Current Report (material events) |
| DEF 14A | Proxy Statement |
| S-1 | Initial Registration Statement |
| 4 | Insider Trading Statement |
| 13F-HR | Institutional Holdings Report |
| 20-F | Annual Report (Foreign Company) |
| SC 13D/G | Beneficial Ownership Report |

---

## Tips & Best Practices

1. **Start with broad queries** before narrowing down to specific indicators
2. **Use recent years** for most up-to-date data (2015-2023)
3. **Check data availability** - not all indicators available for all countries
4. **Cache results** when possible to reduce API calls
5. **Use comparison actions** when analyzing multiple countries
6. **Validate country codes** before making requests
7. **Handle missing data** gracefully in your applications
8. **Respect rate limits** - add delays for bulk operations

---

## Example Workflows

### 1. Complete Country Economic Analysis
```python
# Step 1: Get country info
world_bank.execute({"action": "get_country_data", "country_code": "USA"})

# Step 2: Get key economic indicators
world_bank.execute({"action": "get_indicator_data", "country_code": "USA", "indicator": "gdp_growth", "start_year": 2010})
world_bank.execute({"action": "get_indicator_data", "country_code": "USA", "indicator": "unemployment", "start_year": 2010})

# Step 3: Get IMF outlook
imf.execute({"action": "get_country_profile", "country_code": "US"})

# Step 4: Get SDG progress
united_nations.execute({"action": "get_sdg_progress", "country_code": "USA"})
```

### 2. Company Research & Analysis
```python
# Step 1: Find company
sec_edgar.execute({"action": "search_company", "ticker": "AAPL"})

# Step 2: Get company details
sec_edgar.execute({"action": "get_company_info", "ticker": "AAPL"})

# Step 3: Get recent filings
sec_edgar.execute({"action": "get_company_filings", "ticker": "AAPL", "filing_type": "10-K", "limit": 3})

# Step 4: Get financial data
sec_edgar.execute({"action": "get_financial_data", "ticker": "AAPL", "fact_type": "Assets"})
sec_edgar.execute({"action": "get_financial_data", "ticker": "AAPL", "fact_type": "Revenues"})
```

### 3. Regional Comparison
```python
# Compare Asian economies
countries = ["CHN", "JPN", "IND", "KOR"]

world_bank.execute({
    "action": "compare_countries",
    "country_codes": countries,
    "indicator": "gdp_growth",
    "start_year": 2015
})

imf.execute({
    "action": "compare_countries",
    "country_codes": ["CN", "JP", "IN", "KR"],
    "database": "WEO",
    "indicator": "inflation_avg"
})
```
