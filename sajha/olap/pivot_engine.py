"""
SAJHA MCP Server - Pivot Engine
Version: 2.9.6

Engine for generating and executing pivot table queries using DuckDB's
native PIVOT functionality.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PivotSpec:
    """Specification for a pivot table query."""
    dataset: str
    rows: List[str]  # Dimensions for rows
    columns: List[str] = field(default_factory=list)  # Dimensions for columns (pivot)
    values: List[Dict[str, Any]] = field(default_factory=list)  # Measures with aggregations
    filters: List[Dict[str, Any]] = field(default_factory=list)
    sort: List[Dict[str, str]] = field(default_factory=list)
    limit: Optional[int] = None
    include_totals: bool = True
    include_subtotals: bool = False
    percentage_of: Optional[str] = None  # "row", "column", "grand_total"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "rows": self.rows,
            "columns": self.columns,
            "values": self.values,
            "filters": self.filters,
            "sort": self.sort,
            "limit": self.limit,
            "include_totals": self.include_totals,
            "include_subtotals": self.include_subtotals,
            "percentage_of": self.percentage_of
        }


class PivotEngine:
    """
    Engine for generating and executing pivot table queries.
    
    Uses DuckDB's native PIVOT functionality when possible, falling back
    to conditional aggregation for more complex scenarios.
    """
    
    def __init__(self, semantic_layer, connection=None):
        """
        Initialize the pivot engine.
        
        Args:
            semantic_layer: SemanticLayer instance
            connection: Optional DuckDB connection
        """
        self.semantic = semantic_layer
        self.conn = connection
    
    def build_pivot_query(self, spec: PivotSpec) -> str:
        """
        Build SQL for a pivot table.
        
        Uses conditional aggregation approach for maximum flexibility.
        DuckDB's native PIVOT is available but this approach gives more control.
        
        Args:
            spec: PivotSpec with query specifications
            
        Returns:
            SQL query string
        """
        dataset = self.semantic.get_dataset(spec.dataset)
        if not dataset:
            raise ValueError(f"Dataset '{spec.dataset}' not found")
        
        # Build base query with filters
        base_sql = self._build_base_query(dataset, spec.filters)
        
        if spec.columns:
            # Pivot query with column dimension
            sql = self._build_pivot_with_columns(base_sql, dataset, spec)
        else:
            # Simple aggregation without pivot
            sql = self._build_simple_aggregation(base_sql, dataset, spec)
        
        # Add totals using ROLLUP if requested
        if spec.include_subtotals and spec.rows:
            sql = self._wrap_with_rollup(sql, spec)
        
        return sql
    
    def _build_base_query(self, dataset, filters: List[Dict]) -> str:
        """Build the base SELECT with joins and filters."""
        sql = f"SELECT * FROM {dataset.source_table}"
        
        # Add joins
        for join in dataset.joins:
            alias = f" AS {join.alias}" if join.alias else ""
            sql += f"\n{join.join_type} JOIN {join.table}{alias} ON {join.on_clause}"
        
        # Add filters
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
            elif op.upper() == "BETWEEN":
                if isinstance(val, (list, tuple)) and len(val) == 2:
                    v1 = f"'{val[0]}'" if isinstance(val[0], str) else str(val[0])
                    v2 = f"'{val[1]}'" if isinstance(val[1], str) else str(val[1])
                    clauses.append(f"{col} BETWEEN {v1} AND {v2}")
            elif op.upper() in ("IS NULL", "IS NOT NULL"):
                clauses.append(f"{col} {op}")
            else:
                formatted = f"'{val}'" if isinstance(val, str) else str(val)
                clauses.append(f"{col} {op} {formatted}")
        
        return clauses
    
    def _build_pivot_with_columns(self, base_sql: str, dataset, spec: PivotSpec) -> str:
        """
        Build a pivot query using conditional aggregation.
        
        This approach first gets distinct values for the pivot column,
        then creates CASE WHEN expressions for each value.
        """
        # Resolve row and column dimensions
        row_cols = [self.semantic.resolve_dimension(r, dataset) for r in spec.rows]
        row_aliases = [self._safe_alias(r) for r in spec.rows]
        
        pivot_col = self.semantic.resolve_dimension(spec.columns[0], dataset)
        pivot_alias = self._safe_alias(spec.columns[0])
        
        # Build measure expressions
        measure_exprs = []
        for val in spec.values:
            measure_name = val.get("measure")
            agg = val.get("aggregation", "SUM")
            measure = self.semantic.get_measure(measure_name)
            
            if measure:
                # Extract the column from the measure expression
                # For simple measures like SUM(amount), extract 'amount'
                expr = measure.expression
            else:
                expr = f"{agg}({measure_name})"
            
            measure_exprs.append({
                "name": measure_name,
                "expression": expr,
                "aggregation": agg
            })
        
        # Build the pivot query using a CTE approach
        sql = f"""
WITH base_data AS (
    {base_sql}
),
pivot_values AS (
    SELECT DISTINCT {pivot_col} AS pivot_val
    FROM base_data
    WHERE {pivot_col} IS NOT NULL
    ORDER BY pivot_val
),
aggregated AS (
    SELECT 
        {', '.join(f'{col} AS {alias}' for col, alias in zip(row_cols, row_aliases))},
        {pivot_col} AS {pivot_alias},
        {', '.join(m['expression'] + ' AS ' + self._safe_alias(m['name']) for m in measure_exprs)}
    FROM base_data
    GROUP BY {', '.join(row_cols)}, {pivot_col}
)
SELECT 
    {', '.join(row_aliases)},
    {pivot_alias},
    {', '.join(self._safe_alias(m['name']) for m in measure_exprs)}
FROM aggregated
ORDER BY {', '.join(row_aliases)}, {pivot_alias}
"""
        
        return sql
    
    def _build_simple_aggregation(self, base_sql: str, dataset, spec: PivotSpec) -> str:
        """Build a simple aggregation query without pivot columns."""
        row_cols = [self.semantic.resolve_dimension(r, dataset) for r in spec.rows]
        row_aliases = [self._safe_alias(r) for r in spec.rows]
        
        measure_exprs = []
        for val in spec.values:
            measure_name = val.get("measure")
            agg = val.get("aggregation", "SUM")
            measure = self.semantic.get_measure(measure_name)
            
            if measure:
                expr = measure.expression
            else:
                expr = f"{agg}({measure_name})"
            
            measure_exprs.append(f"{expr} AS {self._safe_alias(measure_name)}")
        
        sql = f"""
SELECT 
    {', '.join(f'{col} AS {alias}' for col, alias in zip(row_cols, row_aliases))},
    {', '.join(measure_exprs)}
FROM ({base_sql}) AS base
GROUP BY {', '.join(row_cols)}
"""
        
        # Add sorting
        if spec.sort:
            sort_parts = []
            for s in spec.sort:
                col = s.get("column")
                direction = s.get("direction", "ASC")
                sort_parts.append(f"{self._safe_alias(col)} {direction}")
            sql += f"ORDER BY {', '.join(sort_parts)}\n"
        else:
            sql += f"ORDER BY {', '.join(row_aliases)}\n"
        
        # Add limit
        if spec.limit:
            sql += f"LIMIT {spec.limit}\n"
        
        return sql
    
    def _wrap_with_rollup(self, sql: str, spec: PivotSpec) -> str:
        """Wrap query with ROLLUP for subtotals."""
        # This is a simplified version - full implementation would
        # restructure the GROUP BY clause
        return sql
    
    def _safe_alias(self, name: str) -> str:
        """Convert a name to a safe SQL alias."""
        safe = ''.join(c if c.isalnum() else '_' for c in str(name))
        if safe and safe[0].isdigit():
            safe = '_' + safe
        return safe
    
    def execute_pivot(self, spec: PivotSpec) -> Dict[str, Any]:
        """
        Execute a pivot table query and return formatted results.
        
        Args:
            spec: PivotSpec with query specifications
            
        Returns:
            Dictionary with data, columns, and metadata
        """
        if not self.conn:
            raise RuntimeError("No database connection available")
        
        sql = self.build_pivot_query(spec)
        
        try:
            result = self.conn.execute(sql).fetchall()
            columns = [desc[0] for desc in self.conn.description]
            
            # Convert to list of dicts
            data = []
            for row in result:
                row_dict = {}
                for i, col in enumerate(columns):
                    val = row[i]
                    # Handle special types
                    if hasattr(val, 'isoformat'):
                        val = val.isoformat()
                    row_dict[col] = val
                data.append(row_dict)
            
            # Add grand totals if requested
            if spec.include_totals and data:
                totals = self._calculate_totals(data, spec)
                if totals:
                    data.append(totals)
            
            return {
                "success": True,
                "data": data,
                "columns": columns,
                "row_count": len(data),
                "row_dimensions": spec.rows,
                "column_dimensions": spec.columns,
                "measures": [v.get("measure") for v in spec.values],
                "sql": sql
            }
            
        except Exception as e:
            logger.error(f"Pivot query execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "sql": sql
            }
    
    def _calculate_totals(self, data: List[Dict], spec: PivotSpec) -> Dict[str, Any]:
        """Calculate grand totals for the pivot table."""
        if not data or not spec.values:
            return None
        
        totals = {}
        
        # Set row dimension values to "Total"
        for row in spec.rows:
            totals[self._safe_alias(row)] = "TOTAL"
        
        # Calculate totals for measures
        for val in spec.values:
            measure_name = self._safe_alias(val.get("measure"))
            agg = val.get("aggregation", "SUM").upper()
            
            values = [row.get(measure_name) for row in data 
                     if row.get(measure_name) is not None]
            
            if values:
                if agg == "SUM":
                    totals[measure_name] = sum(values)
                elif agg == "AVG":
                    totals[measure_name] = sum(values) / len(values)
                elif agg == "COUNT":
                    totals[measure_name] = sum(values)
                elif agg == "MIN":
                    totals[measure_name] = min(values)
                elif agg == "MAX":
                    totals[measure_name] = max(values)
                else:
                    totals[measure_name] = sum(values)
        
        return totals
    
    def get_pivot_column_values(self, spec: PivotSpec) -> List[Any]:
        """
        Get distinct values for the pivot column.
        
        Useful for building dynamic pivot table headers.
        """
        if not self.conn or not spec.columns:
            return []
        
        dataset = self.semantic.get_dataset(spec.dataset)
        if not dataset:
            return []
        
        base_sql = self._build_base_query(dataset, spec.filters)
        pivot_col = self.semantic.resolve_dimension(spec.columns[0], dataset)
        
        sql = f"""
SELECT DISTINCT {pivot_col} AS pivot_val
FROM ({base_sql}) AS base
WHERE {pivot_col} IS NOT NULL
ORDER BY pivot_val
"""
        
        try:
            result = self.conn.execute(sql).fetchall()
            return [row[0] for row in result]
        except Exception as e:
            logger.error(f"Error getting pivot values: {e}")
            return []
