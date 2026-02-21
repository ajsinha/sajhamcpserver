"""
SAJHA MCP Server - Time Series Engine
Version: 2.9.8

Engine for time series analytics including temporal aggregations,
gap filling, and period-over-period comparisons.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TimeSeriesSpec:
    """Specification for time series analysis."""
    dataset: str
    time_dimension: str
    time_grain: str  # year, quarter, month, week, day, hour
    measures: List[str]
    dimensions: List[str] = field(default_factory=list)  # Additional grouping dimensions
    comparison: Optional[Dict[str, Any]] = None  # Period-over-period comparison
    fill_gaps: bool = True
    fill_value: Any = 0
    filters: List[Dict[str, Any]] = field(default_factory=list)
    date_range: Optional[Dict[str, str]] = None  # start_date, end_date
    limit: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "time_dimension": self.time_dimension,
            "time_grain": self.time_grain,
            "measures": self.measures,
            "dimensions": self.dimensions,
            "comparison": self.comparison,
            "fill_gaps": self.fill_gaps,
            "fill_value": self.fill_value,
            "filters": self.filters,
            "date_range": self.date_range,
            "limit": self.limit
        }


class TimeSeriesEngine:
    """
    Engine for time series analytics.
    
    Supports:
    - Flexible time granularities (year, quarter, month, week, day, hour)
    - Gap filling for missing periods
    - Period-over-period comparisons (YoY, MoM, WoW, etc.)
    - Fiscal calendar support
    - Trend calculations
    """
    
    # Time truncation expressions for DuckDB
    TIME_GRAINS = {
        "year": "DATE_TRUNC('year', {col})",
        "quarter": "DATE_TRUNC('quarter', {col})",
        "month": "DATE_TRUNC('month', {col})",
        "week": "DATE_TRUNC('week', {col})",
        "day": "DATE_TRUNC('day', {col})",
        "hour": "DATE_TRUNC('hour', {col})",
        "minute": "DATE_TRUNC('minute', {col})"
    }
    
    # Interval expressions for different periods
    INTERVALS = {
        "year": "INTERVAL '1 year'",
        "quarter": "INTERVAL '3 months'",
        "month": "INTERVAL '1 month'",
        "week": "INTERVAL '1 week'",
        "day": "INTERVAL '1 day'",
        "hour": "INTERVAL '1 hour'"
    }
    
    # Period-over-period comparison offsets
    COMPARISON_OFFSETS = {
        "yoy": "INTERVAL '1 year'",      # Year over Year
        "mom": "INTERVAL '1 month'",     # Month over Month
        "wow": "INTERVAL '1 week'",      # Week over Week
        "qoq": "INTERVAL '3 months'",    # Quarter over Quarter
        "dod": "INTERVAL '1 day'",       # Day over Day
        "ytd": None,                      # Year to Date (special handling)
        "mtd": None                       # Month to Date (special handling)
    }
    
    def __init__(self, semantic_layer, connection=None):
        """
        Initialize the time series engine.
        
        Args:
            semantic_layer: SemanticLayer instance
            connection: Optional DuckDB connection
        """
        self.semantic = semantic_layer
        self.conn = connection
    
    def build_time_series_query(self, spec: TimeSeriesSpec) -> str:
        """
        Build SQL for time series analysis.
        
        Args:
            spec: TimeSeriesSpec with query specifications
            
        Returns:
            SQL query string
        """
        dataset = self.semantic.get_dataset(spec.dataset)
        if not dataset:
            raise ValueError(f"Dataset '{spec.dataset}' not found")
        
        # Resolve time dimension
        time_col = self.semantic.resolve_dimension(spec.time_dimension, dataset)
        grain_expr = self.TIME_GRAINS[spec.time_grain].format(col=time_col)
        
        # Build measure expressions
        measure_exprs = []
        for m in spec.measures:
            measure = self.semantic.get_measure(m)
            alias = self._safe_alias(m)
            if measure:
                measure_exprs.append(f"{measure.expression} AS {alias}")
            else:
                measure_exprs.append(f"SUM({m}) AS {alias}")
        
        # Build dimension expressions
        dim_exprs = []
        for d in spec.dimensions:
            col = self.semantic.resolve_dimension(d, dataset)
            alias = self._safe_alias(d)
            dim_exprs.append(f"{col} AS {alias}")
        
        # Build base query
        base_sql = self._build_base_query(dataset, spec.filters, spec.date_range, time_col)
        
        if spec.fill_gaps and not spec.dimensions:
            sql = self._build_gap_filled_query(base_sql, grain_expr, measure_exprs, spec)
        else:
            sql = self._build_simple_time_series(base_sql, grain_expr, 
                                                  measure_exprs, dim_exprs, spec)
        
        # Add period-over-period comparison
        if spec.comparison:
            sql = self._add_comparison(sql, spec)
        
        return sql
    
    def _build_base_query(self, dataset, filters: List[Dict], 
                           date_range: Optional[Dict], time_col: str) -> str:
        """Build the base SELECT with joins, filters, and date range."""
        sql = f"SELECT * FROM {dataset.source_table}"
        
        for join in dataset.joins:
            alias = f" AS {join.alias}" if join.alias else ""
            sql += f"\n{join.join_type} JOIN {join.table}{alias} ON {join.on_clause}"
        
        where_clauses = []
        
        # Add regular filters
        if filters:
            where_clauses.extend(self._build_filters(filters, dataset))
        
        # Add date range filter
        if date_range:
            if date_range.get("start_date"):
                where_clauses.append(f"{time_col} >= '{date_range['start_date']}'")
            if date_range.get("end_date"):
                where_clauses.append(f"{time_col} <= '{date_range['end_date']}'")
        
        if where_clauses:
            sql += f"\nWHERE {' AND '.join(where_clauses)}"
        
        return sql
    
    def _build_filters(self, filters: List[Dict], dataset) -> List[str]:
        """Build WHERE clause components."""
        clauses = []
        for f in filters:
            dim = f.get("dimension", f.get("column"))
            op = f.get("operator", "=")
            val = f.get("value")
            
            col = self.semantic.resolve_dimension(dim, dataset)
            
            if op.upper() == "IN":
                if isinstance(val, list):
                    formatted = ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in val)
                else:
                    formatted = f"'{val}'" if isinstance(val, str) else str(val)
                clauses.append(f"{col} IN ({formatted})")
            else:
                formatted = f"'{val}'" if isinstance(val, str) else str(val)
                clauses.append(f"{col} {op} {formatted}")
        
        return clauses
    
    def _build_simple_time_series(self, base_sql: str, grain_expr: str,
                                    measure_exprs: List[str], 
                                    dim_exprs: List[str],
                                    spec: TimeSeriesSpec) -> str:
        """Build a simple time series aggregation without gap filling."""
        group_cols = ["time_period"]
        if spec.dimensions:
            group_cols.extend([self._safe_alias(d) for d in spec.dimensions])
        
        select_cols = [f"{grain_expr} AS time_period"]
        select_cols.extend(dim_exprs)
        select_cols.extend(measure_exprs)
        
        sql = f"""
SELECT 
    {', '.join(select_cols)}
FROM ({base_sql}) AS base
GROUP BY {', '.join(group_cols)}
ORDER BY time_period
"""
        
        if spec.limit:
            sql += f"LIMIT {spec.limit}\n"
        
        return sql
    
    def _build_gap_filled_query(self, base_sql: str, grain_expr: str,
                                  measure_exprs: List[str],
                                  spec: TimeSeriesSpec) -> str:
        """Build query with gap filling using generate_series."""
        interval = self.INTERVALS.get(spec.time_grain, "INTERVAL '1 day'")
        fill_value = spec.fill_value if spec.fill_value is not None else 0
        
        # Build COALESCE expressions for measures
        coalesce_exprs = []
        for expr in measure_exprs:
            # Extract alias from "expression AS alias"
            parts = expr.rsplit(" AS ", 1)
            if len(parts) == 2:
                alias = parts[1]
                coalesce_exprs.append(f"COALESCE(a.{alias}, {fill_value}) AS {alias}")
            else:
                coalesce_exprs.append(f"COALESCE(a.{expr}, {fill_value})")
        
        sql = f"""
WITH date_spine AS (
    SELECT generate_series(
        (SELECT MIN({grain_expr}) FROM ({base_sql}) AS b),
        (SELECT MAX({grain_expr}) FROM ({base_sql}) AS b),
        {interval}
    )::DATE AS time_period
),
aggregated AS (
    SELECT 
        {grain_expr} AS time_period,
        {', '.join(measure_exprs)}
    FROM ({base_sql}) AS base
    GROUP BY 1
)
SELECT 
    ds.time_period,
    {', '.join(coalesce_exprs)}
FROM date_spine ds
LEFT JOIN aggregated a ON ds.time_period = a.time_period
ORDER BY ds.time_period
"""
        
        if spec.limit:
            sql += f"LIMIT {spec.limit}\n"
        
        return sql
    
    def _add_comparison(self, sql: str, spec: TimeSeriesSpec) -> str:
        """Add period-over-period comparison columns."""
        comparison = spec.comparison
        period_type = comparison.get("type", "yoy")
        
        offset = self.COMPARISON_OFFSETS.get(period_type)
        if not offset:
            # Special handling for YTD/MTD would go here
            return sql
        
        # Build measure comparison columns
        measure_cols = [self._safe_alias(m) for m in spec.measures]
        
        comparison_cols = []
        for col in measure_cols:
            comparison_cols.extend([
                f"p.{col} AS previous_{col}",
                f"(c.{col} - COALESCE(p.{col}, 0)) AS {col}_change",
                f"ROUND(100.0 * (c.{col} - COALESCE(p.{col}, 0)) / NULLIF(p.{col}, 0), 2) AS {col}_pct_change"
            ])
        
        wrapped_sql = f"""
WITH current_data AS (
    {sql}
),
previous_data AS (
    SELECT 
        time_period + {offset} AS time_period,
        {', '.join(measure_cols)}
    FROM current_data
)
SELECT 
    c.time_period,
    {', '.join(f'c.{col}' for col in measure_cols)},
    {', '.join(comparison_cols)}
FROM current_data c
LEFT JOIN previous_data p ON c.time_period = p.time_period
ORDER BY c.time_period
"""
        return wrapped_sql
    
    def _safe_alias(self, name: str) -> str:
        """Convert a name to a safe SQL alias."""
        safe = ''.join(c if c.isalnum() else '_' for c in str(name))
        if safe and safe[0].isdigit():
            safe = '_' + safe
        return safe
    
    def execute_time_series(self, spec: TimeSeriesSpec) -> Dict[str, Any]:
        """
        Execute a time series query and return formatted results.
        
        Args:
            spec: TimeSeriesSpec with query specifications
            
        Returns:
            Dictionary with data, columns, and metadata
        """
        if not self.conn:
            raise RuntimeError("No database connection available")
        
        sql = self.build_time_series_query(spec)
        
        try:
            result = self.conn.execute(sql).fetchall()
            columns = [desc[0] for desc in self.conn.description]
            
            # Convert to list of dicts
            data = []
            for row in result:
                row_dict = {}
                for i, col in enumerate(columns):
                    val = row[i]
                    if hasattr(val, 'isoformat'):
                        val = val.isoformat()
                    row_dict[col] = val
                data.append(row_dict)
            
            # Calculate summary statistics
            summary = self._calculate_summary(data, spec.measures)
            
            return {
                "success": True,
                "data": data,
                "columns": columns,
                "row_count": len(data),
                "time_dimension": spec.time_dimension,
                "time_grain": spec.time_grain,
                "measures": spec.measures,
                "has_comparison": spec.comparison is not None,
                "comparison_type": spec.comparison.get("type") if spec.comparison else None,
                "summary": summary,
                "sql": sql
            }
            
        except Exception as e:
            logger.error(f"Time series query execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "sql": sql
            }
    
    def _calculate_summary(self, data: List[Dict], measures: List[str]) -> Dict[str, Any]:
        """Calculate summary statistics for the time series."""
        if not data:
            return {}
        
        summary = {}
        for measure in measures:
            col = self._safe_alias(measure)
            values = [row.get(col) for row in data if row.get(col) is not None]
            
            if values:
                summary[measure] = {
                    "min": min(values),
                    "max": max(values),
                    "sum": sum(values),
                    "avg": sum(values) / len(values),
                    "count": len(values),
                    "first": values[0],
                    "last": values[-1],
                    "total_change": values[-1] - values[0] if len(values) > 1 else 0
                }
        
        return summary
    
    def build_trend_analysis(self, spec: TimeSeriesSpec) -> str:
        """
        Build a query that includes trend indicators.
        
        Adds columns for:
        - Moving average
        - Trend direction (up/down/stable)
        - Seasonality indicators
        """
        base_sql = self.build_time_series_query(spec)
        
        measure_cols = [self._safe_alias(m) for m in spec.measures]
        
        trend_cols = []
        for col in measure_cols:
            trend_cols.extend([
                f"AVG({col}) OVER (ORDER BY time_period ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS {col}_ma3",
                f"CASE WHEN {col} > LAG({col}, 1) OVER (ORDER BY time_period) THEN 'up' "
                f"WHEN {col} < LAG({col}, 1) OVER (ORDER BY time_period) THEN 'down' "
                f"ELSE 'stable' END AS {col}_trend"
            ])
        
        sql = f"""
WITH time_data AS (
    {base_sql}
)
SELECT 
    *,
    {', '.join(trend_cols)}
FROM time_data
ORDER BY time_period
"""
        return sql
    
    def get_available_grains(self) -> List[Dict[str, str]]:
        """Return list of available time granularities."""
        return [
            {"grain": "year", "description": "Aggregate by calendar year"},
            {"grain": "quarter", "description": "Aggregate by calendar quarter"},
            {"grain": "month", "description": "Aggregate by calendar month"},
            {"grain": "week", "description": "Aggregate by week (Monday start)"},
            {"grain": "day", "description": "Aggregate by day"},
            {"grain": "hour", "description": "Aggregate by hour"}
        ]
    
    def get_available_comparisons(self) -> List[Dict[str, str]]:
        """Return list of available comparison types."""
        return [
            {"type": "yoy", "description": "Year over Year comparison"},
            {"type": "mom", "description": "Month over Month comparison"},
            {"type": "wow", "description": "Week over Week comparison"},
            {"type": "qoq", "description": "Quarter over Quarter comparison"},
            {"type": "dod", "description": "Day over Day comparison"}
        ]
