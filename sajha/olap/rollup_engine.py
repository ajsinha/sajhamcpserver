"""
SAJHA MCP Server - Rollup Engine
Version: 2.9.0

Engine for hierarchical aggregations using ROLLUP, CUBE, and GROUPING SETS.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RollupSpec:
    """Specification for ROLLUP/CUBE operations."""
    dataset: str
    dimensions: List[str]
    measures: List[Dict[str, Any]]
    operation: str = "ROLLUP"  # ROLLUP, CUBE, or GROUPING_SETS
    grouping_sets: Optional[List[List[str]]] = None
    filters: List[Dict[str, Any]] = field(default_factory=list)
    include_grouping_id: bool = True
    sort_by_hierarchy: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "dimensions": self.dimensions,
            "measures": self.measures,
            "operation": self.operation,
            "grouping_sets": self.grouping_sets,
            "filters": self.filters,
            "include_grouping_id": self.include_grouping_id,
            "sort_by_hierarchy": self.sort_by_hierarchy
        }


class RollupEngine:
    """
    Engine for hierarchical aggregations using ROLLUP and CUBE.
    
    ROLLUP creates subtotals from right to left in the dimension list,
    plus a grand total row.
    
    CUBE creates subtotals for all possible combinations of dimensions.
    
    GROUPING SETS allows custom grouping combinations.
    """
    
    def __init__(self, semantic_layer, connection=None):
        """
        Initialize the rollup engine.
        
        Args:
            semantic_layer: SemanticLayer instance
            connection: Optional DuckDB connection
        """
        self.semantic = semantic_layer
        self.conn = connection
    
    def build_rollup_query(self, spec: RollupSpec) -> str:
        """
        Build SQL with ROLLUP/CUBE for hierarchical summaries.
        
        Args:
            spec: RollupSpec with query specifications
            
        Returns:
            SQL query string
        """
        dataset = self.semantic.get_dataset(spec.dataset)
        if not dataset:
            raise ValueError(f"Dataset '{spec.dataset}' not found")
        
        # Build base query
        base_sql = self._build_base_query(dataset, spec.filters)
        
        # Resolve dimensions
        dim_cols = []
        dim_aliases = []
        for d in spec.dimensions:
            col = self.semantic.resolve_dimension(d, dataset)
            alias = self._safe_alias(d)
            dim_cols.append(col)
            dim_aliases.append(alias)
        
        # Build measure expressions
        measure_exprs = self._build_measure_expressions(spec.measures)
        
        # Build grouping clause
        if spec.operation.upper() == "GROUPING_SETS" and spec.grouping_sets:
            grouping = self._build_grouping_sets(spec.grouping_sets, dim_cols, dim_aliases)
        elif spec.operation.upper() == "CUBE":
            grouping = f"CUBE({', '.join(dim_cols)})"
        else:
            grouping = f"ROLLUP({', '.join(dim_cols)})"
        
        # Build GROUPING() indicators
        grouping_indicators = ""
        if spec.include_grouping_id:
            grouping_funcs = [f"GROUPING({col}) AS is_{alias}_total" 
                            for col, alias in zip(dim_cols, dim_aliases)]
            grouping_indicators = ",\n    " + ",\n    ".join(grouping_funcs)
        
        # Build the query
        sql = f"""
SELECT 
    {', '.join(f'COALESCE(CAST({col} AS VARCHAR), \'[TOTAL]\') AS {alias}' 
               for col, alias in zip(dim_cols, dim_aliases))},
    {', '.join(measure_exprs)}{grouping_indicators}
FROM ({base_sql}) AS base
GROUP BY {grouping}
"""
        
        # Add ordering
        if spec.sort_by_hierarchy:
            # Sort by grouping level first (totals at end), then by dimension values
            order_parts = [f"GROUPING({col})" for col in dim_cols] + dim_aliases
            sql += f"ORDER BY {', '.join(order_parts)}\n"
        
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
            elif op.upper() == "BETWEEN":
                if isinstance(val, (list, tuple)) and len(val) == 2:
                    v1 = f"'{val[0]}'" if isinstance(val[0], str) else str(val[0])
                    v2 = f"'{val[1]}'" if isinstance(val[1], str) else str(val[1])
                    clauses.append(f"{col} BETWEEN {v1} AND {v2}")
            else:
                formatted = f"'{val}'" if isinstance(val, str) else str(val)
                clauses.append(f"{col} {op} {formatted}")
        
        return clauses
    
    def _build_measure_expressions(self, measures: List[Dict]) -> List[str]:
        """Build measure aggregation expressions."""
        exprs = []
        for m in measures:
            measure_name = m.get("measure")
            agg = m.get("aggregation", "SUM")
            alias = self._safe_alias(m.get("alias", measure_name))
            
            measure = self.semantic.get_measure(measure_name)
            if measure:
                # Use the defined expression
                exprs.append(f"{measure.expression} AS {alias}")
            else:
                # Direct column with aggregation
                exprs.append(f"{agg}({measure_name}) AS {alias}")
        
        return exprs
    
    def _build_grouping_sets(self, grouping_sets: List[List[str]], 
                              dim_cols: List[str], dim_aliases: List[str]) -> str:
        """Build GROUPING SETS clause for custom groupings."""
        # Create mapping from alias to column
        alias_to_col = dict(zip(dim_aliases, dim_cols))
        
        sets = []
        for group_set in grouping_sets:
            if not group_set:
                sets.append("()")  # Empty set for grand total
            else:
                cols = [alias_to_col.get(self._safe_alias(g), g) for g in group_set]
                sets.append(f"({', '.join(cols)})")
        
        return f"GROUPING SETS ({', '.join(sets)})"
    
    def _safe_alias(self, name: str) -> str:
        """Convert a name to a safe SQL alias."""
        safe = ''.join(c if c.isalnum() else '_' for c in str(name))
        if safe and safe[0].isdigit():
            safe = '_' + safe
        return safe
    
    def execute_rollup(self, spec: RollupSpec) -> Dict[str, Any]:
        """
        Execute a rollup/cube query and return formatted results.
        
        Args:
            spec: RollupSpec with query specifications
            
        Returns:
            Dictionary with data, columns, and metadata
        """
        if not self.conn:
            raise RuntimeError("No database connection available")
        
        sql = self.build_rollup_query(spec)
        
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
            
            # Identify hierarchy levels
            hierarchy_info = self._analyze_hierarchy(data, spec)
            
            return {
                "success": True,
                "data": data,
                "columns": columns,
                "row_count": len(data),
                "dimensions": spec.dimensions,
                "measures": [m.get("measure") for m in spec.measures],
                "operation": spec.operation,
                "hierarchy_info": hierarchy_info,
                "sql": sql
            }
            
        except Exception as e:
            logger.error(f"Rollup query execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "sql": sql
            }
    
    def _analyze_hierarchy(self, data: List[Dict], spec: RollupSpec) -> Dict[str, Any]:
        """Analyze the hierarchy levels in the result."""
        if not data or not spec.include_grouping_id:
            return {}
        
        levels = {}
        total_indicator_cols = [f"is_{self._safe_alias(d)}_total" for d in spec.dimensions]
        
        for row in data:
            # Calculate hierarchy level based on grouping indicators
            level = sum(row.get(col, 0) for col in total_indicator_cols if col in row)
            level_key = f"level_{level}"
            
            if level_key not in levels:
                levels[level_key] = {
                    "depth": level,
                    "is_subtotal": level > 0,
                    "is_grand_total": level == len(spec.dimensions),
                    "count": 0
                }
            levels[level_key]["count"] += 1
        
        return levels
    
    def build_comparison_query(self, spec: RollupSpec, 
                                compare_dimension: str) -> str:
        """
        Build a query that compares each row's values to its parent subtotal.
        
        Useful for showing percentages of parent totals.
        """
        base_query = self.build_rollup_query(spec)
        
        # This is a simplified version - full implementation would use window functions
        # to compare each row to its parent in the hierarchy
        sql = f"""
WITH hierarchy_data AS (
    {base_query}
)
SELECT 
    *,
    -- Calculate percentage of grand total for each measure
    {', '.join(f'{self._safe_alias(m["measure"])} * 100.0 / '
               f'SUM({self._safe_alias(m["measure"])}) OVER () AS {self._safe_alias(m["measure"])}_pct_total'
               for m in spec.measures)}
FROM hierarchy_data
"""
        return sql
