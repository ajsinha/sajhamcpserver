#!/usr/bin/env python3
"""
Example: Financial Analysis Workflow

Demonstrates chaining multiple SAJHA tools to build
a comprehensive stock analysis report.
"""

from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(
    base_url="http://localhost:3002",
    username="admin",
    password="admin123",
))

SYMBOL = "AAPL"
print(f"{'='*60}")
print(f"  Financial Analysis: {SYMBOL}")
print(f"{'='*60}")

# 1. Company Profile
print("\n1. Company Profile")
profile = client.execute_tool("fmp_company_profile", symbol=SYMBOL)
p = profile.get('result', profile).get('profile', {})
if isinstance(p, dict):
    print(f"   Name:       {p.get('companyName', 'N/A')}")
    print(f"   Sector:     {p.get('sector', 'N/A')}")
    print(f"   Industry:   {p.get('industry', 'N/A')}")
    print(f"   Market Cap: ${p.get('mktCap', 0):,.0f}")
    print(f"   CEO:        {p.get('ceo', 'N/A')}")

# 2. Current Quote
print("\n2. Current Quote")
quote = client.execute_tool("fmp_stock_quote", symbol=SYMBOL)
q = quote.get('result', quote).get('quote', {})
if isinstance(q, dict):
    print(f"   Price:      ${q.get('price', 0):.2f}")
    print(f"   Change:     {q.get('changesPercentage', 0):.2f}%")
    print(f"   Volume:     {q.get('volume', 0):,.0f}")

# 3. Key Metrics
print("\n3. Key Financial Ratios")
metrics = client.execute_tool("fmp_key_metrics", symbol=SYMBOL, period="annual", limit=1)
ratios = metrics.get('result', metrics).get('ratios', [])
if ratios and isinstance(ratios[0], dict):
    r = ratios[0]
    print(f"   P/E:           {r.get('peRatioTTM', 'N/A')}")
    print(f"   P/B:           {r.get('priceToBookRatioTTM', 'N/A')}")
    print(f"   ROE:           {r.get('returnOnEquityTTM', 'N/A')}")
    print(f"   Dividend Yield: {r.get('dividendYieldTTM', 'N/A')}")

# 4. Analyst Targets
print("\n4. Analyst Price Targets")
targets = client.execute_tool("fmp_price_target", symbol=SYMBOL, limit=3)
for t in targets.get('result', targets).get('targets', [])[:3]:
    if isinstance(t, dict):
        print(f"   {t.get('analystName', '?'):20s} | ${t.get('priceTarget', 0):>8.2f} | {t.get('publishedDate', '')[:10]}")

# 5. Recent News
print("\n5. Recent News")
news = client.execute_tool("fmp_stock_news", symbol=SYMBOL, limit=3)
for a in news.get('result', news).get('articles', [])[:3]:
    if isinstance(a, dict):
        print(f"   • {a.get('title', '')[:70]}")

# 6. Insider Trading
print("\n6. Recent Insider Trades")
insider = client.execute_tool("fmp_insider_trading", symbol=SYMBOL, limit=3)
for t in insider.get('result', insider).get('transactions', [])[:3]:
    if isinstance(t, dict):
        print(f"   {t.get('reportingName', '?'):20s} | {t.get('transactionType', ''):10s} | {t.get('securitiesTransacted', 0):>10,} shares")

print(f"\n{'='*60}")
print(f"  Analysis complete for {SYMBOL}")
print(f"{'='*60}")
