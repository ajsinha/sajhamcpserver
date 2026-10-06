"""
SAJHA MCP Server - Cohort Analysis Engine
Version: 2.9.8

Engine for cohort analysis including customer retention, 
revenue cohorts, and behavioral segmentation.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from sajha.olap import sql_safety as sq

logger = logging.getLogger(__name__)


@dataclass
class CohortSpec:
    """Specification for cohort analysis."""
    dataset: str
    cohort_dimension: str  # Dimension defining the cohort (e.g., signup_month)
    time_dimension: str    # Time dimension for tracking
    entity_dimension: str  # Entity to track (e.g., customer_id)
    measure: str          # Measure to aggregate
    aggregation: str = "COUNT_DISTINCT"  # COUNT_DISTINCT, SUM, AVG
    time_grain: str = "month"  # year, quarter, month, week, day
    periods: int = 12     # Number of periods to track
    filters: List[Dict[str, Any]] = field(default_factory=list)
    show_percentages: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "cohort_dimension": self.cohort_dimension,
            "time_dimension": self.time_dimension,
            "entity_dimension": self.entity_dimension,
            "measure": self.measure,
            "aggregation": self.aggregation,
            "time_grain": self.time_grain,
            "periods": self.periods,
            "filters": self.filters,
            "show_percentages": self.show_percentages
        }


@dataclass
class RetentionSpec:
    """Specification for retention analysis."""
    dataset: str
    cohort_dimension: str  # Dimension defining the cohort (e.g., first_purchase_month)
    activity_dimension: str  # Dimension indicating activity (e.g., order_date)
    entity_dimension: str   # Entity to track (e.g., customer_id)
    time_grain: str = "month"
    periods: int = 12
    filters: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "cohort_dimension": self.cohort_dimension,
            "activity_dimension": self.activity_dimension,
            "entity_dimension": self.entity_dimension,
            "time_grain": self.time_grain,
            "periods": self.periods,
            "filters": self.filters
        }


class CohortEngine:
    """
    Engine for cohort analysis.
    
    Supports:
    - Customer cohort retention analysis
    - Revenue cohort tracking
    - Behavioral cohort segmentation
    - Period-over-period cohort comparison
    """
    
    TIME_GRAIN_TRUNC = {
        "year": "DATE_TRUNC('year', {col})",
        "quarter": "DATE_TRUNC('quarter', {col})",
        "month": "DATE_TRUNC('month', {col})",
        "week": "DATE_TRUNC('week', {col})",
        "day": "DATE_TRUNC('day', {col})"
    }
    
    TIME_GRAIN_DIFF = {
        "year": "DATE_DIFF('year', {start}, {end})",
        "quarter": "DATE_DIFF('month', {start}, {end}) / 3",
        "month": "DATE_DIFF('month', {start}, {end})",
        "week": "DATE_DIFF('week', {start}, {end})",
        "day": "DATE_DIFF('day', {start}, {end})"
    }
    
    def __init__(self, semantic_layer, connection=None):
        """
        Initialize the cohort engine.
        
        Args:
            semantic_layer: SemanticLayer instance
            connection: Optional DuckDB connection
        """
        self.semantic = semantic_layer
        self.conn = connection
    
    def build_cohort_analysis(self, spec: CohortSpec) -> str:
        """
        Build SQL for cohort analysis.
        
        Creates a cohort matrix showing measure values for each cohort
        across multiple time periods.
        
        Args:
            spec: CohortSpec with query specifications
            
        Returns:
            SQL query string
        """
        dataset = self.semantic.get_dataset(spec.dataset)
        if not dataset:
            raise ValueError(f"Dataset '{spec.dataset}' not found")
        
        # Build base query
        base_sql = self._build_base_query(dataset, spec.filters)
        
        # Resolve columns
        cohort_col = sq.dimension_expr(self.semantic, dataset, spec.cohort_dimension)
        time_col = sq.dimension_expr(self.semantic, dataset, spec.time_dimension)
        entity_col = sq.dimension_expr(self.semantic, dataset, spec.entity_dimension)
        
        # For cohort, we need the raw column behind the (declared) measure
        measure_col = sq.measure_column(self.semantic, dataset, spec.measure)
        self._check_grain(spec.time_grain)
        periods = sq.integer(spec.periods, "periods", 0, 1000)
        
        # Build time grain expression
        time_trunc = self.TIME_GRAIN_TRUNC[spec.time_grain].format(col=time_col)
        cohort_trunc = self.TIME_GRAIN_TRUNC[spec.time_grain].format(col=cohort_col)
        period_diff = self.TIME_GRAIN_DIFF[spec.time_grain].format(
            start=f"cohort_period", end=f"activity_period"
        )
        
        # Build aggregation
        if spec.aggregation == "COUNT_DISTINCT":
            agg_expr = f"COUNT(DISTINCT {entity_col})"
        elif spec.aggregation == "SUM":
            agg_expr = f"SUM({measure_col})"
        elif spec.aggregation == "AVG":
            agg_expr = f"AVG({measure_col})"
        else:
            agg_expr = f"COUNT(DISTINCT {entity_col})"
        
        sql = f"""
WITH base_data AS (
    {base_sql}
),
cohort_data AS (
    SELECT 
        {entity_col} AS entity_id,
        {cohort_trunc} AS cohort_period,
        {time_trunc} AS activity_period,
        {measure_col} AS measure_value
    FROM base_data
),
cohort_sizes AS (
    SELECT 
        cohort_period,
        COUNT(DISTINCT entity_id) AS cohort_size
    FROM cohort_data
    GROUP BY cohort_period
),
cohort_activity AS (
    SELECT 
        cd.cohort_period,
        {period_diff} AS period_number,
        {agg_expr.replace(entity_col, 'cd.entity_id').replace(measure_col, 'cd.measure_value')} AS measure_value
    FROM cohort_data cd
    WHERE {period_diff} >= 0 AND {period_diff} <= {periods}
    GROUP BY cd.cohort_period, {period_diff}
)
SELECT 
    ca.cohort_period,
    cs.cohort_size,
    ca.period_number,
    ca.measure_value,
    ROUND(100.0 * ca.measure_value / NULLIF(cs.cohort_size, 0), 2) AS retention_pct
FROM cohort_activity ca
JOIN cohort_sizes cs ON ca.cohort_period = cs.cohort_period
ORDER BY ca.cohort_period, ca.period_number
"""
        
        return sql
    
    def build_retention_analysis(self, spec: RetentionSpec) -> str:
        """
        Build SQL for retention analysis.
        
        Creates a retention matrix showing what percentage of users
        from each cohort were active in subsequent periods.
        
        Args:
            spec: RetentionSpec with query specifications
            
        Returns:
            SQL query string
        """
        dataset = self.semantic.get_dataset(spec.dataset)
        if not dataset:
            raise ValueError(f"Dataset '{spec.dataset}' not found")
        
        # Build base query
        base_sql = self._build_base_query(dataset, spec.filters)
        
        # Resolve columns
        cohort_col = sq.dimension_expr(self.semantic, dataset, spec.cohort_dimension)
        activity_col = sq.dimension_expr(self.semantic, dataset, spec.activity_dimension)
        entity_col = sq.dimension_expr(self.semantic, dataset, spec.entity_dimension)
        
        # Build time expressions
        self._check_grain(spec.time_grain)
        periods = sq.integer(spec.periods, "periods", 0, 1000)
        cohort_trunc = self.TIME_GRAIN_TRUNC[spec.time_grain].format(col=cohort_col)
        activity_trunc = self.TIME_GRAIN_TRUNC[spec.time_grain].format(col=activity_col)
        period_diff = self.TIME_GRAIN_DIFF[spec.time_grain].format(
            start="first_activity", end="activity_period"
        )
        
        sql = f"""
WITH base_data AS (
    {base_sql}
),
-- Get first activity date for each entity (cohort assignment)
entity_cohorts AS (
    SELECT 
        {entity_col} AS entity_id,
        MIN({cohort_trunc}) AS first_activity
    FROM base_data
    GROUP BY {entity_col}
),
-- Get all activity periods for each entity
entity_activities AS (
    SELECT DISTINCT
        {entity_col} AS entity_id,
        {activity_trunc} AS activity_period
    FROM base_data
),
-- Join to get period number for each activity
cohort_activity AS (
    SELECT 
        ec.first_activity AS cohort_period,
        {period_diff} AS period_number,
        ea.entity_id
    FROM entity_cohorts ec
    JOIN entity_activities ea ON ec.entity_id = ea.entity_id
    WHERE {period_diff} >= 0 AND {period_diff} <= {periods}
),
-- Count cohort sizes
cohort_sizes AS (
    SELECT 
        first_activity AS cohort_period,
        COUNT(DISTINCT entity_id) AS cohort_size
    FROM entity_cohorts
    GROUP BY first_activity
),
-- Count retained users per period
retention_counts AS (
    SELECT 
        cohort_period,
        period_number,
        COUNT(DISTINCT entity_id) AS retained_count
    FROM cohort_activity
    GROUP BY cohort_period, period_number
)
SELECT 
    rc.cohort_period,
    cs.cohort_size,
    rc.period_number,
    rc.retained_count,
    ROUND(100.0 * rc.retained_count / NULLIF(cs.cohort_size, 0), 2) AS retention_pct
FROM retention_counts rc
JOIN cohort_sizes cs ON rc.cohort_period = cs.cohort_period
ORDER BY rc.cohort_period, rc.period_number
"""
        
        return sql
    
    def build_cohort_pivot(self, spec: CohortSpec) -> str:
        """
        Build pivoted cohort table with periods as columns.
        
        Creates a traditional cohort triangle with cohort periods as rows
        and period numbers as columns.
        
        Args:
            spec: CohortSpec with query specifications
            
        Returns:
            SQL query string
        """
        dataset = self.semantic.get_dataset(spec.dataset)
        if not dataset:
            raise ValueError(f"Dataset '{spec.dataset}' not found")
        
        # Build base cohort query first
        base_cohort_sql = self.build_cohort_analysis(spec)
        
        # Build pivot columns for each period
        pivot_cols = []
        for i in range(sq.integer(spec.periods, "periods", 0, 1000) + 1):
            if spec.show_percentages:
                pivot_cols.append(
                    f"MAX(CASE WHEN period_number = {i} THEN retention_pct END) AS period_{i}_pct"
                )
            else:
                pivot_cols.append(
                    f"MAX(CASE WHEN period_number = {i} THEN measure_value END) AS period_{i}"
                )
        
        sql = f"""
WITH cohort_data AS (
    {base_cohort_sql}
)
SELECT 
    cohort_period,
    MAX(cohort_size) AS cohort_size,
    {', '.join(pivot_cols)}
FROM cohort_data
GROUP BY cohort_period
ORDER BY cohort_period
"""
        
        return sql
    
    def build_cohort_comparison(self, spec: CohortSpec, baseline_cohort: str = None) -> str:
        """
        Build cohort comparison showing difference from baseline.
        
        Compares each cohort's retention/values to a baseline cohort
        or the average across all cohorts.
        
        Args:
            spec: CohortSpec with query specifications
            baseline_cohort: Specific cohort to use as baseline, or None for average
            
        Returns:
            SQL query string
        """
        dataset = self.semantic.get_dataset(spec.dataset)
        if not dataset:
            raise ValueError(f"Dataset '{spec.dataset}' not found")
        
        # Build base cohort query
        base_cohort_sql = self.build_cohort_analysis(spec)
        
        if baseline_cohort:
            # A value, so a parameter: bind {"olap_baseline_cohort": baseline_cohort} (plus the
            # filter parameters) when executing this SQL.
            baseline_filter = f"WHERE cohort_period = ${sq.PARAM_PREFIX}baseline_cohort"
        else:
            baseline_filter = ""
        
        sql = f"""
WITH cohort_data AS (
    {base_cohort_sql}
),
baseline AS (
    SELECT 
        period_number,
        AVG(retention_pct) AS baseline_pct
    FROM cohort_data
    {baseline_filter}
    GROUP BY period_number
)
SELECT 
    cd.cohort_period,
    cd.cohort_size,
    cd.period_number,
    cd.retention_pct,
    b.baseline_pct,
    ROUND(cd.retention_pct - b.baseline_pct, 2) AS diff_from_baseline,
    CASE 
        WHEN cd.retention_pct > b.baseline_pct THEN 'above'
        WHEN cd.retention_pct < b.baseline_pct THEN 'below'
        ELSE 'equal'
    END AS performance
FROM cohort_data cd
JOIN baseline b ON cd.period_number = b.period_number
ORDER BY cd.cohort_period, cd.period_number
"""
        
        return sql
    
    def _build_base_query(self, dataset, filters: List[Dict]) -> str:
        """Build the base SELECT with joins and (parameterised) filters."""
        return sq.base_query(self.semantic, dataset, filters)
    
    def _build_filters(self, filters: List[Dict], dataset) -> List[str]:
        """WHERE clause components; values are $olap_* parameters (see sql_safety)."""
        return sq.compile_filters(self.semantic, dataset, filters)[0]

    def _params(self, spec) -> Dict[str, Any]:
        dataset = self.semantic.get_dataset(spec.dataset)
        return sq.filter_params(self.semantic, dataset, spec.filters) if dataset else {}

    def _check_grain(self, grain: str) -> None:
        if grain not in self.TIME_GRAIN_TRUNC:
            raise sq.OLAPQueryError(f"Unsupported time_grain {grain!r}. "
                                    f"Allowed: {sorted(self.TIME_GRAIN_TRUNC)}")
    
    def _extract_column_from_expression(self, expression: str) -> str:
        """Extract column name from aggregation expression like SUM(amount)."""
        if "(" in expression and ")" in expression:
            start = expression.index("(") + 1
            end = expression.rindex(")")
            return expression[start:end].strip()
        return expression
    
    def _safe_alias(self, name: str) -> str:
        """Convert a name to a safe SQL alias."""
        safe = ''.join(c if c.isalnum() else '_' for c in str(name))
        if safe and safe[0].isdigit():
            safe = '_' + safe
        return safe
    
    def execute_cohort_analysis(self, spec: CohortSpec) -> Dict[str, Any]:
        """
        Execute cohort analysis and return formatted results.
        
        Args:
            spec: CohortSpec with query specifications
            
        Returns:
            Dictionary with cohort analysis data
        """
        if not self.conn:
            raise RuntimeError("No database connection available")
        
        sql = self.build_cohort_pivot(spec)
        
        try:
            result = sq.execute(self.conn, sql, self._params(spec)).fetchall()
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
                "cohort_dimension": spec.cohort_dimension,
                "time_dimension": spec.time_dimension,
                "periods": spec.periods,
                "time_grain": spec.time_grain,
                "sql": sql
            }
            
        except Exception as e:
            logger.error(f"Cohort analysis error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "sql": sql
            }
    
    def execute_retention_analysis(self, spec: RetentionSpec) -> Dict[str, Any]:
        """
        Execute retention analysis and return formatted results.
        
        Args:
            spec: RetentionSpec with query specifications
            
        Returns:
            Dictionary with retention analysis data
        """
        if not self.conn:
            raise RuntimeError("No database connection available")
        
        sql = self.build_retention_analysis(spec)
        
        try:
            result = sq.execute(self.conn, sql, self._params(spec)).fetchall()
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
            
            # Calculate average retention by period
            retention_by_period = {}
            for row in data:
                period = row.get('period_number')
                pct = row.get('retention_pct')
                if period is not None and pct is not None:
                    if period not in retention_by_period:
                        retention_by_period[period] = []
                    retention_by_period[period].append(pct)
            
            avg_retention = {
                period: round(sum(pcts) / len(pcts), 2) 
                for period, pcts in retention_by_period.items()
            }
            
            return {
                "success": True,
                "data": data,
                "columns": columns,
                "average_retention_by_period": avg_retention,
                "cohort_dimension": spec.cohort_dimension,
                "time_grain": spec.time_grain,
                "periods": spec.periods,
                "sql": sql
            }
            
        except Exception as e:
            logger.error(f"Retention analysis error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "sql": sql
            }
    
    def get_cohort_summary(self, spec: CohortSpec) -> Dict[str, Any]:
        """
        Get summary statistics for cohort analysis.
        
        Returns:
            Dictionary with cohort summary metrics
        """
        if not self.conn:
            raise RuntimeError("No database connection available")
        
        sql = self.build_cohort_analysis(spec)
        
        try:
            # Wrap in summary query
            summary_sql = f"""
WITH cohort_data AS (
    {sql}
)
SELECT 
    COUNT(DISTINCT cohort_period) AS total_cohorts,
    MIN(cohort_period) AS first_cohort,
    MAX(cohort_period) AS last_cohort,
    AVG(cohort_size) AS avg_cohort_size,
    AVG(CASE WHEN period_number = 0 THEN retention_pct END) AS avg_period_0_retention,
    AVG(CASE WHEN period_number = 1 THEN retention_pct END) AS avg_period_1_retention,
    AVG(CASE WHEN period_number = 3 THEN retention_pct END) AS avg_period_3_retention,
    AVG(CASE WHEN period_number = 6 THEN retention_pct END) AS avg_period_6_retention,
    AVG(CASE WHEN period_number = 12 THEN retention_pct END) AS avg_period_12_retention
FROM cohort_data
"""
            
            result = sq.execute(self.conn, summary_sql, self._params(spec)).fetchone()
            columns = [desc[0] for desc in self.conn.description]
            
            summary = dict(zip(columns, result))
            
            return {
                "success": True,
                "summary": summary
            }
            
        except Exception as e:
            logger.error(f"Cohort summary error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
