"""
SAJHA MCP Server - Statistics Engine
Version: 2.9.0

Engine for statistical calculations including summary statistics,
percentiles, distributions, correlations, and histograms.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StatsSpec:
    """Specification for statistical analysis."""
    dataset: str
    measures: List[str]
    group_by: Optional[List[str]] = None
    statistics: List[str] = field(default_factory=lambda: ["summary"])
    filters: List[Dict[str, Any]] = field(default_factory=list)
    percentiles: List[float] = field(default_factory=lambda: [0.25, 0.50, 0.75, 0.90, 0.95, 0.99])
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "measures": self.measures,
            "group_by": self.group_by,
            "statistics": self.statistics,
            "filters": self.filters,
            "percentiles": self.percentiles
        }


@dataclass
class HistogramSpec:
    """Specification for histogram generation."""
    dataset: str
    measure: str
    bins: int = 10
    filters: List[Dict[str, Any]] = field(default_factory=list)
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "measure": self.measure,
            "bins": self.bins,
            "filters": self.filters,
            "min_value": self.min_value,
            "max_value": self.max_value
        }


class StatsEngine:
    """
    Engine for statistical calculations.
    
    Supports:
    - Summary statistics (count, sum, avg, min, max, stddev, variance)
    - Percentile calculations
    - Distribution metrics (skewness, kurtosis)
    - Correlation matrices
    - Histograms
    - Outlier detection
    """
    
    def __init__(self, semantic_layer, connection=None):
        """
        Initialize the statistics engine.
        
        Args:
            semantic_layer: SemanticLayer instance
            connection: Optional DuckDB connection
        """
        self.semantic = semantic_layer
        self.conn = connection
    
    def build_summary_statistics(self, spec: StatsSpec) -> str:
        """
        Build comprehensive summary statistics query.
        
        Args:
            spec: StatsSpec with query specifications
            
        Returns:
            SQL query string
        """
        dataset = self.semantic.get_dataset(spec.dataset)
        if not dataset:
            raise ValueError(f"Dataset '{spec.dataset}' not found")
        
        # Build base query
        base_sql = self._build_base_query(dataset, spec.filters)
        
        # Build stats functions for each measure
        stats_functions = []
        for measure in spec.measures:
            col = self._resolve_measure_column(measure, dataset)
            alias = self._safe_alias(measure)
            
            if "summary" in spec.statistics:
                stats_functions.extend([
                    f"COUNT({col}) AS {alias}_count",
                    f"COUNT(DISTINCT {col}) AS {alias}_distinct",
                    f"SUM({col}) AS {alias}_sum",
                    f"AVG({col}) AS {alias}_mean",
                    f"MIN({col}) AS {alias}_min",
                    f"MAX({col}) AS {alias}_max",
                    f"STDDEV_SAMP({col}) AS {alias}_stddev",
                    f"VAR_SAMP({col}) AS {alias}_variance"
                ])
            
            if "percentiles" in spec.statistics:
                for p in spec.percentiles:
                    p_name = f"p{int(p*100)}"
                    stats_functions.append(
                        f"PERCENTILE_CONT({p}) WITHIN GROUP (ORDER BY {col}) AS {alias}_{p_name}"
                    )
            
            if "distribution" in spec.statistics:
                stats_functions.extend([
                    f"MEDIAN({col}) AS {alias}_median",
                    f"MODE({col}) AS {alias}_mode",
                    # DuckDB supports these aggregate functions
                    f"(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {col}) - "
                    f"PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {col})) AS {alias}_iqr"
                ])
        
        # Build group by clause
        group_clause = ""
        select_cols = ""
        
        if spec.group_by:
            group_cols = []
            for g in spec.group_by:
                col = self.semantic.resolve_dimension(g, dataset)
                alias = self._safe_alias(g)
                group_cols.append(f"{col} AS {alias}")
            select_cols = ", ".join(group_cols) + ", "
            group_clause = f"GROUP BY {', '.join([self.semantic.resolve_dimension(g, dataset) for g in spec.group_by])}"
        
        sql = f"""
SELECT 
    {select_cols}
    {', '.join(stats_functions)}
FROM ({base_sql}) AS base
{group_clause}
"""
        
        return sql
    
    def build_correlation_matrix(self, spec: StatsSpec) -> str:
        """
        Build correlation matrix between measures.
        
        Args:
            spec: StatsSpec with measures to correlate
            
        Returns:
            SQL query string
        """
        dataset = self.semantic.get_dataset(spec.dataset)
        if not dataset:
            raise ValueError(f"Dataset '{spec.dataset}' not found")
        
        # Build base query
        base_sql = self._build_base_query(dataset, spec.filters)
        
        # Build correlation expressions for all pairs
        measures = [self._resolve_measure_column(m, dataset) for m in spec.measures]
        aliases = [self._safe_alias(m) for m in spec.measures]
        
        correlations = []
        for i, (m1, a1) in enumerate(zip(measures, aliases)):
            for j, (m2, a2) in enumerate(zip(measures, aliases)):
                if i <= j:  # Upper triangle including diagonal
                    correlations.append(
                        f"ROUND(CORR({m1}, {m2}), 4) AS corr_{a1}_{a2}"
                    )
        
        sql = f"""
SELECT 
    {', '.join(correlations)}
FROM ({base_sql}) AS base
"""
        return sql
    
    def build_histogram(self, spec: HistogramSpec) -> str:
        """
        Build histogram data for a measure.
        
        Args:
            spec: HistogramSpec with histogram specifications
            
        Returns:
            SQL query string
        """
        dataset = self.semantic.get_dataset(spec.dataset)
        if not dataset:
            raise ValueError(f"Dataset '{spec.dataset}' not found")
        
        # Build base query
        base_sql = self._build_base_query(dataset, spec.filters)
        col = self._resolve_measure_column(spec.measure, dataset)
        
        # Use provided bounds or calculate from data
        min_expr = str(spec.min_value) if spec.min_value is not None else f"MIN({col})"
        max_expr = str(spec.max_value) if spec.max_value is not None else f"MAX({col})"
        
        sql = f"""
WITH bounds AS (
    SELECT 
        {min_expr} AS min_val,
        {max_expr} AS max_val,
        ({max_expr} - {min_expr}) / {spec.bins}.0 AS bin_width
    FROM ({base_sql}) AS b
),
binned AS (
    SELECT 
        CASE 
            WHEN bin_width = 0 THEN 0
            ELSE LEAST(FLOOR(({col} - min_val) / NULLIF(bin_width, 0)), {spec.bins - 1})
        END AS bin_num,
        min_val,
        bin_width,
        COUNT(*) AS frequency
    FROM ({base_sql}) AS base, bounds
    WHERE {col} IS NOT NULL
    GROUP BY 1, 2, 3
)
SELECT 
    bin_num,
    min_val + (bin_num * bin_width) AS bin_start,
    min_val + ((bin_num + 1) * bin_width) AS bin_end,
    frequency,
    ROUND(100.0 * frequency / SUM(frequency) OVER (), 2) AS percentage,
    SUM(frequency) OVER (ORDER BY bin_num) AS cumulative_freq,
    ROUND(100.0 * SUM(frequency) OVER (ORDER BY bin_num) / SUM(frequency) OVER (), 2) AS cumulative_pct
FROM binned
ORDER BY bin_num
"""
        return sql
    
    def build_outlier_detection(self, spec: StatsSpec, method: str = "iqr") -> str:
        """
        Build query to detect outliers.
        
        Args:
            spec: StatsSpec with measure specifications
            method: Detection method ('iqr' for IQR method, 'zscore' for Z-score)
            
        Returns:
            SQL query string
        """
        dataset = self.semantic.get_dataset(spec.dataset)
        if not dataset:
            raise ValueError(f"Dataset '{spec.dataset}' not found")
        
        base_sql = self._build_base_query(dataset, spec.filters)
        
        if method == "iqr":
            return self._build_iqr_outliers(base_sql, spec, dataset)
        else:
            return self._build_zscore_outliers(base_sql, spec, dataset)
    
    def _build_iqr_outliers(self, base_sql: str, spec: StatsSpec, dataset) -> str:
        """Build IQR-based outlier detection query."""
        outlier_cols = []
        
        for measure in spec.measures:
            col = self._resolve_measure_column(measure, dataset)
            alias = self._safe_alias(measure)
            
            outlier_cols.append(f"""
CASE 
    WHEN {col} < (PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {col}) OVER () - 
                  1.5 * (PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {col}) OVER () - 
                         PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {col}) OVER ()))
    THEN 'low_outlier'
    WHEN {col} > (PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {col}) OVER () + 
                  1.5 * (PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {col}) OVER () - 
                         PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {col}) OVER ()))
    THEN 'high_outlier'
    ELSE 'normal'
END AS {alias}_outlier_status
""")
        
        sql = f"""
SELECT 
    *,
    {', '.join(outlier_cols)}
FROM ({base_sql}) AS base
"""
        return sql
    
    def _build_zscore_outliers(self, base_sql: str, spec: StatsSpec, dataset) -> str:
        """Build Z-score based outlier detection query."""
        outlier_cols = []
        
        for measure in spec.measures:
            col = self._resolve_measure_column(measure, dataset)
            alias = self._safe_alias(measure)
            
            outlier_cols.append(f"""
({col} - AVG({col}) OVER ()) / NULLIF(STDDEV({col}) OVER (), 0) AS {alias}_zscore,
CASE 
    WHEN ABS(({col} - AVG({col}) OVER ()) / NULLIF(STDDEV({col}) OVER (), 0)) > 3 THEN 'extreme_outlier'
    WHEN ABS(({col} - AVG({col}) OVER ()) / NULLIF(STDDEV({col}) OVER (), 0)) > 2 THEN 'outlier'
    ELSE 'normal'
END AS {alias}_outlier_status
""")
        
        sql = f"""
SELECT 
    *,
    {', '.join(outlier_cols)}
FROM ({base_sql}) AS base
"""
        return sql
    
    def _build_base_query(self, dataset, filters: List[Dict]) -> str:
        """Build the base SELECT with joins and filters."""
        sql = f"SELECT * FROM {dataset.source_table}"
        
        for join in dataset.joins:
            alias = f" AS {join.alias}" if join.alias else ""
            sql += f"\n{join.join_type} JOIN {join.table}{alias} ON {join.on_clause}"
        
        if filters:
            where_clauses = self._build_filters(filters, dataset)
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
    
    def _resolve_measure_column(self, measure: str, dataset) -> str:
        """Resolve a measure name to its column expression."""
        m = self.semantic.get_measure(measure)
        if m:
            # Extract column from expression like "SUM(amount)"
            expr = m.expression
            # Simple extraction - real implementation would parse properly
            if "(" in expr and ")" in expr:
                start = expr.index("(") + 1
                end = expr.rindex(")")
                return expr[start:end]
            return expr
        return measure
    
    def _safe_alias(self, name: str) -> str:
        """Convert a name to a safe SQL alias."""
        safe = ''.join(c if c.isalnum() else '_' for c in str(name))
        if safe and safe[0].isdigit():
            safe = '_' + safe
        return safe
    
    def execute_statistics(self, spec: StatsSpec) -> Dict[str, Any]:
        """
        Execute statistics query and return formatted results.
        
        Args:
            spec: StatsSpec with query specifications
            
        Returns:
            Dictionary with statistics data
        """
        if not self.conn:
            raise RuntimeError("No database connection available")
        
        sql = self.build_summary_statistics(spec)
        
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
            
            return {
                "success": True,
                "data": data,
                "columns": columns,
                "measures": spec.measures,
                "statistics_types": spec.statistics,
                "grouped_by": spec.group_by,
                "sql": sql
            }
            
        except Exception as e:
            logger.error(f"Statistics query execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "sql": sql
            }
    
    def execute_histogram(self, spec: HistogramSpec) -> Dict[str, Any]:
        """
        Execute histogram query and return formatted results.
        
        Args:
            spec: HistogramSpec with histogram specifications
            
        Returns:
            Dictionary with histogram data
        """
        if not self.conn:
            raise RuntimeError("No database connection available")
        
        sql = self.build_histogram(spec)
        
        try:
            result = self.conn.execute(sql).fetchall()
            columns = [desc[0] for desc in self.conn.description]
            
            data = []
            for row in result:
                row_dict = {}
                for i, col in enumerate(columns):
                    row_dict[col] = row[i]
                data.append(row_dict)
            
            return {
                "success": True,
                "data": data,
                "columns": columns,
                "measure": spec.measure,
                "bins": spec.bins,
                "sql": sql
            }
            
        except Exception as e:
            logger.error(f"Histogram query execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "sql": sql
            }
    
    def execute_correlation(self, spec: StatsSpec) -> Dict[str, Any]:
        """
        Execute correlation matrix query and return formatted results.
        
        Args:
            spec: StatsSpec with measures to correlate
            
        Returns:
            Dictionary with correlation matrix
        """
        if not self.conn:
            raise RuntimeError("No database connection available")
        
        sql = self.build_correlation_matrix(spec)
        
        try:
            result = self.conn.execute(sql).fetchone()
            columns = [desc[0] for desc in self.conn.description]
            
            # Build correlation matrix
            matrix = {}
            for i, col in enumerate(columns):
                # Parse column name like "corr_revenue_quantity"
                parts = col.split("_")[1:]  # Remove "corr_" prefix
                matrix[col] = result[i]
            
            return {
                "success": True,
                "correlations": matrix,
                "measures": spec.measures,
                "sql": sql
            }
            
        except Exception as e:
            logger.error(f"Correlation query execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "sql": sql
            }
    
    def get_available_statistics(self) -> List[Dict[str, str]]:
        """Return list of available statistics types."""
        return [
            {"type": "summary", "description": "Basic statistics: count, sum, avg, min, max, stddev, variance"},
            {"type": "percentiles", "description": "Percentile values: p25, p50, p75, p90, p95, p99"},
            {"type": "distribution", "description": "Distribution metrics: median, mode, IQR"},
            {"type": "correlation", "description": "Correlation matrix between measures"}
        ]
