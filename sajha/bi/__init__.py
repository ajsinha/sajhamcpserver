"""
SAJHA MCP Server — Business Intelligence: the metrics layer and the bi_* tools.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

    metrics.py    metric definitions: parse, check, load from bi.metrics_dir (notices), who may query
    periods.py    human periods (2025-Q3, FY2025, YTD, last 12 months, {from, to}) as date ranges
    compiler.py   a metric query compiled to one SELECT (values bound, identifiers from the definition)
                  and run through its source's own path (connector engine, DuckDB sandbox, OLAP)
    analysis.py   compare, top N, crosstab, contribution analysis, cumulative and rolling values

Design: docs/architecture/Business Intelligence.md.
"""
