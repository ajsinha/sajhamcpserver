"""
SAJHA MCP Server - Window Engine
Version: 2.9.6

Engine for window function calculations including running totals,
rankings, moving averages, and percent of total calculations.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class WindowCalculation:
    """Specification for a single window calculation."""
    calc_type: str
    measure: str
    partition_by: List[str] = field(default_factory=list)
    order_by: Optional[str] = None
    order_direction: str = "ASC"
    alias: Optional[str] = None
    window_size: int = 3  # For moving average
    offset: int = 1  # For lag/lead
    default_value: Any = None  # For lag/lead
    buckets: int = 4  # For ntile
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.calc_type,
            "measure": self.measure,
            "partition_by": self.partition_by,
            "order_by": self.order_by,
            "order_direction": self.order_direction,
            "alias": self.alias,
            "window_size": self.window_size,
            "offset": self.offset,
            "default_value": self.default_value,
            "buckets": self.buckets
        }


@dataclass
class WindowSpec:
    """Specification for window function calculations."""
    dataset: str
    base_dimensions: List[str]
    base_measures: List[str] = field(default_factory=list)
    window_calculations: List[WindowCalculation] = field(default_factory=list)
    filters: List[Dict[str, Any]] = field(default_factory=list)
    limit: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "base_dimensions": self.base_dimensions,
            "base_measures": self.base_measures,
            "window_calculations": [c.to_dict() for c in self.window_calculations],
            "filters": self.filters,
            "limit": self.limit
        }


class WindowEngine:
    """
    Engine for window function calculations.
    
    Supports a wide variety of analytical window functions including:
    - Running totals and averages
    - Moving averages with configurable windows
    - Rankings (rank, dense_rank, row_number, percent_rank, ntile)
    - Lag/Lead for comparing to previous/next rows
    - Percent of total calculations
    - Period-over-period comparisons
    """
    
    # Window function templates
    WINDOW_TEMPLATES = {
        "running_total": "SUM({measure}) OVER ({partition}ORDER BY {order} ROWS UNBOUNDED PRECEDING)",
        "running_average": "AVG({measure}) OVER ({partition}ORDER BY {order} ROWS UNBOUNDED PRECEDING)",
        "running_count": "COUNT({measure}) OVER ({partition}ORDER BY {order} ROWS UNBOUNDED PRECEDING)",
        "running_min": "MIN({measure}) OVER ({partition}ORDER BY {order} ROWS UNBOUNDED PRECEDING)",
        "running_max": "MAX({measure}) OVER ({partition}ORDER BY {order} ROWS UNBOUNDED PRECEDING)",
        "moving_average": "AVG({measure}) OVER ({partition}ORDER BY {order} ROWS BETWEEN {window_size} PRECEDING AND CURRENT ROW)",
        "moving_sum": "SUM({measure}) OVER ({partition}ORDER BY {order} ROWS BETWEEN {window_size} PRECEDING AND CURRENT ROW)",
        "rank": "RANK() OVER ({partition}ORDER BY {measure} {direction})",
        "dense_rank": "DENSE_RANK() OVER ({partition}ORDER BY {measure} {direction})",
        "row_number": "ROW_NUMBER() OVER ({partition}ORDER BY {order})",
        "percent_rank": "ROUND(PERCENT_RANK() OVER ({partition}ORDER BY {measure}) * 100, 2)",
        "ntile": "NTILE({buckets}) OVER ({partition}ORDER BY {measure})",
        "cume_dist": "ROUND(CUME_DIST() OVER ({partition}ORDER BY {measure}) * 100, 2)",
        "lag": "LAG({measure}, {offset}, {default}) OVER ({partition}ORDER BY {order})",
        "lead": "LEAD({measure}, {offset}, {default}) OVER ({partition}ORDER BY {order})",
        "first_value": "FIRST_VALUE({measure}) OVER ({partition}ORDER BY {order})",
        "last_value": "LAST_VALUE({measure}) OVER ({partition}ORDER BY {order} ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)",
        "percent_of_total": "ROUND(100.0 * {measure} / NULLIF(SUM({measure}) OVER ({partition}), 0), 2)",
        "percent_of_partition": "ROUND(100.0 * {measure} / NULLIF(SUM({measure}) OVER ({partition}), 0), 2)",
        "difference_from_previous": "{measure} - LAG({measure}, 1, 0) OVER ({partition}ORDER BY {order})",
        "percent_change": "ROUND(100.0 * ({measure} - LAG({measure}, 1) OVER ({partition}ORDER BY {order})) / NULLIF(LAG({measure}, 1) OVER ({partition}ORDER BY {order}), 0), 2)",
        "difference_from_first": "{measure} - FIRST_VALUE({measure}) OVER ({partition}ORDER BY {order})",
        "difference_from_average": "{measure} - AVG({measure}) OVER ({partition})"
    }
    
    def __init__(self, semantic_layer, connection=None):
        """
        Initialize the window engine.
        
        Args:
            semantic_layer: SemanticLayer instance
            connection: Optional DuckDB connection
        """
        self.semantic = semantic_layer
        self.conn = connection
    
    def build_window_query(self, spec: WindowSpec) -> str:
        """
        Build SQL with window functions.
        
        Args:
            spec: WindowSpec with query specifications
            
        Returns:
            SQL query string
        """
        dataset = self.semantic.get_dataset(spec.dataset)
        if not dataset:
            raise ValueError(f"Dataset '{spec.dataset}' not found")
        
        # Build base query
        base_sql = self._build_base_query(dataset, spec.filters)
        
        # Build dimension columns
        dim_cols = []
        for d in spec.base_dimensions:
            col = self.semantic.resolve_dimension(d, dataset)
            alias = self._safe_alias(d)
            dim_cols.append(f"{col} AS {alias}")
        
        # Build base measure columns
        measure_cols = []
        for m in spec.base_measures:
            measure = self.semantic.get_measure(m)
            alias = self._safe_alias(m)
            if measure:
                measure_cols.append(f"{measure.expression} AS {alias}")
            else:
                measure_cols.append(f"{m} AS {alias}")
        
        # Build window calculation columns
        window_cols = []
        for calc in spec.window_calculations:
            if isinstance(calc, dict):
                calc = WindowCalculation(
                    calc_type=calc.get("type"),
                    measure=calc.get("measure"),
                    partition_by=calc.get("partition_by", []),
                    order_by=calc.get("order_by"),
                    order_direction=calc.get("order_direction", "ASC"),
                    alias=calc.get("alias"),
                    window_size=calc.get("window_size", 3),
                    offset=calc.get("offset", 1),
                    default_value=calc.get("default_value"),
                    buckets=calc.get("buckets", 4)
                )
            
            window_sql = self._build_window_function(calc, dataset)
            alias = calc.alias or f"{calc.calc_type}_{self._safe_alias(calc.measure)}"
            window_cols.append(f"{window_sql} AS {self._safe_alias(alias)}")
        
        # Need to aggregate first, then apply windows
        # Build aggregation CTE
        group_dims = [self.semantic.resolve_dimension(d, dataset) for d in spec.base_dimensions]
        
        sql = f"""
WITH aggregated AS (
    SELECT 
        {', '.join(dim_cols)},
        {', '.join(measure_cols) if measure_cols else '1 AS _dummy'}
    FROM ({base_sql}) AS base
    {'GROUP BY ' + ', '.join(group_dims) if group_dims else ''}
)
SELECT 
    *,
    {', '.join(window_cols)}
FROM aggregated
"""
        
        if spec.limit:
            sql += f"\nLIMIT {spec.limit}"
        
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
    
    def _build_window_function(self, calc: WindowCalculation, dataset) -> str:
        """Build a single window function expression."""
        template = self.WINDOW_TEMPLATES.get(calc.calc_type)
        if not template:
            raise ValueError(f"Unknown window calculation type: {calc.calc_type}")
        
        # Resolve measure
        measure_col = self._safe_alias(calc.measure)
        
        # Build partition clause
        if calc.partition_by:
            partition_cols = [self._safe_alias(p) for p in calc.partition_by]
            partition = f"PARTITION BY {', '.join(partition_cols)} "
        else:
            partition = ""
        
        # Build order clause
        order = calc.order_by or calc.measure
        order_col = self._safe_alias(order)
        direction = calc.order_direction or "ASC"
        
        # Format default value for lag/lead
        default_val = "NULL"
        if calc.default_value is not None:
            if isinstance(calc.default_value, str):
                default_val = f"'{calc.default_value}'"
            else:
                default_val = str(calc.default_value)
        
        # Build the expression
        expr = template.format(
            measure=measure_col,
            partition=partition,
            order=order_col,
            direction=direction,
            window_size=calc.window_size - 1,  # -1 because PRECEDING is exclusive
            offset=calc.offset,
            default=default_val,
            buckets=calc.buckets
        )
        
        return expr
    
    def _safe_alias(self, name: str) -> str:
        """Convert a name to a safe SQL alias."""
        safe = ''.join(c if c.isalnum() else '_' for c in str(name))
        if safe and safe[0].isdigit():
            safe = '_' + safe
        return safe
    
    def execute_window(self, spec: WindowSpec) -> Dict[str, Any]:
        """
        Execute a window function query and return formatted results.
        
        Args:
            spec: WindowSpec with query specifications
            
        Returns:
            Dictionary with data, columns, and metadata
        """
        if not self.conn:
            raise RuntimeError("No database connection available")
        
        sql = self.build_window_query(spec)
        
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
            
            # Identify which columns are window calculations
            window_cols = []
            for calc in spec.window_calculations:
                if isinstance(calc, dict):
                    alias = calc.get("alias") or f"{calc.get('type')}_{self._safe_alias(calc.get('measure'))}"
                else:
                    alias = calc.alias or f"{calc.calc_type}_{self._safe_alias(calc.measure)}"
                window_cols.append(self._safe_alias(alias))
            
            return {
                "success": True,
                "data": data,
                "columns": columns,
                "row_count": len(data),
                "base_dimensions": spec.base_dimensions,
                "base_measures": spec.base_measures,
                "window_columns": window_cols,
                "sql": sql
            }
            
        except Exception as e:
            logger.error(f"Window query execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "sql": sql
            }
    
    def get_available_calculations(self) -> List[Dict[str, str]]:
        """Return list of available window calculation types."""
        return [
            {"type": "running_total", "description": "Cumulative sum of values"},
            {"type": "running_average", "description": "Cumulative average of values"},
            {"type": "running_count", "description": "Cumulative count"},
            {"type": "running_min", "description": "Cumulative minimum"},
            {"type": "running_max", "description": "Cumulative maximum"},
            {"type": "moving_average", "description": "Moving average over specified window"},
            {"type": "moving_sum", "description": "Moving sum over specified window"},
            {"type": "rank", "description": "Rank with gaps for ties"},
            {"type": "dense_rank", "description": "Rank without gaps"},
            {"type": "row_number", "description": "Sequential row number"},
            {"type": "percent_rank", "description": "Percentile rank (0-100)"},
            {"type": "ntile", "description": "Divide into N buckets"},
            {"type": "cume_dist", "description": "Cumulative distribution (0-100)"},
            {"type": "lag", "description": "Value from previous row"},
            {"type": "lead", "description": "Value from next row"},
            {"type": "first_value", "description": "First value in partition"},
            {"type": "last_value", "description": "Last value in partition"},
            {"type": "percent_of_total", "description": "Percentage of grand total"},
            {"type": "percent_of_partition", "description": "Percentage of partition total"},
            {"type": "difference_from_previous", "description": "Difference from previous row"},
            {"type": "percent_change", "description": "Percentage change from previous row"},
            {"type": "difference_from_first", "description": "Difference from first value"},
            {"type": "difference_from_average", "description": "Difference from partition average"}
        ]
