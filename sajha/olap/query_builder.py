"""
SAJHA MCP Server - OLAP Query Builder
Version: 2.9.0

Base query building utilities used by all OLAP engines.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Filter:
    """Represents a filter condition."""
    dimension: str
    operator: str
    value: Any
    
    OPERATORS = {
        "=": "{col} = {val}",
        "!=": "{col} != {val}",
        ">": "{col} > {val}",
        "<": "{col} < {val}",
        ">=": "{col} >= {val}",
        "<=": "{col} <= {val}",
        "IN": "{col} IN ({val})",
        "NOT IN": "{col} NOT IN ({val})",
        "LIKE": "{col} LIKE {val}",
        "NOT LIKE": "{col} NOT LIKE {val}",
        "BETWEEN": "{col} BETWEEN {val}",
        "IS NULL": "{col} IS NULL",
        "IS NOT NULL": "{col} IS NOT NULL",
        "CONTAINS": "{col} LIKE '%' || {val} || '%'"
    }
    
    def to_sql(self, column_expr: str) -> str:
        """Convert filter to SQL WHERE clause component."""
        template = self.OPERATORS.get(self.operator.upper(), "{col} = {val}")
        
        # Format value based on type
        if self.operator.upper() in ("IS NULL", "IS NOT NULL"):
            return template.format(col=column_expr, val="")
        elif self.operator.upper() in ("IN", "NOT IN"):
            if isinstance(self.value, (list, tuple)):
                formatted = ", ".join(self._format_value(v) for v in self.value)
            else:
                formatted = self._format_value(self.value)
            return template.format(col=column_expr, val=formatted)
        elif self.operator.upper() == "BETWEEN":
            if isinstance(self.value, (list, tuple)) and len(self.value) == 2:
                return f"{column_expr} BETWEEN {self._format_value(self.value[0])} AND {self._format_value(self.value[1])}"
            return f"{column_expr} = {self._format_value(self.value)}"
        else:
            return template.format(col=column_expr, val=self._format_value(self.value))
    
    def _format_value(self, val: Any) -> str:
        """Format a value for SQL."""
        if val is None:
            return "NULL"
        elif isinstance(val, bool):
            return "TRUE" if val else "FALSE"
        elif isinstance(val, (int, float)):
            return str(val)
        elif isinstance(val, str):
            # Escape single quotes
            escaped = val.replace("'", "''")
            return f"'{escaped}'"
        else:
            return f"'{str(val)}'"


@dataclass
class SortSpec:
    """Represents a sort specification."""
    column: str
    direction: str = "ASC"  # ASC or DESC
    nulls: Optional[str] = None  # FIRST or LAST
    
    def to_sql(self) -> str:
        """Convert to SQL ORDER BY component."""
        sql = f"{self.column} {self.direction}"
        if self.nulls:
            sql += f" NULLS {self.nulls}"
        return sql


class OLAPQueryBuilder:
    """
    Builds SQL queries for OLAP operations.
    
    Provides utilities for constructing complex analytical queries with
    proper handling of joins, filters, aggregations, and groupings.
    """
    
    def __init__(self, semantic_layer):
        """
        Initialize the query builder.
        
        Args:
            semantic_layer: SemanticLayer instance for resolving names
        """
        self.semantic = semantic_layer
    
    def build_base_query(self, dataset_name: str, 
                         filters: List[Dict[str, Any]] = None) -> str:
        """
        Build the base query with table joins and filters.
        
        Args:
            dataset_name: Name of the dataset
            filters: Optional list of filter specifications
            
        Returns:
            SQL query string for the base data
        """
        dataset = self.semantic.get_dataset(dataset_name)
        if not dataset:
            raise ValueError(f"Dataset '{dataset_name}' not found")
        
        # Start with source table
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
    
    def _build_filters(self, filters: List[Dict[str, Any]], 
                       dataset) -> List[str]:
        """Build WHERE clause components from filter specifications."""
        clauses = []
        
        for f in filters:
            dim_name = f.get("dimension") or f.get("column")
            operator = f.get("operator", "=")
            value = f.get("value")
            
            # Resolve dimension to column expression
            col_expr = self.semantic.resolve_dimension(dim_name, dataset)
            
            filter_obj = Filter(
                dimension=dim_name,
                operator=operator,
                value=value
            )
            clauses.append(filter_obj.to_sql(col_expr))
        
        return clauses
    
    def build_select_columns(self, dimensions: List[str], 
                             measures: List[Dict[str, Any]],
                             dataset) -> Tuple[List[str], List[str]]:
        """
        Build SELECT column expressions for dimensions and measures.
        
        Returns:
            Tuple of (dimension expressions, measure expressions)
        """
        dim_exprs = []
        for dim in dimensions:
            expr = self.semantic.resolve_dimension(dim, dataset)
            dim_exprs.append(f"{expr} AS {self._safe_alias(dim)}")
        
        measure_exprs = []
        for m in measures:
            if isinstance(m, str):
                m = {"measure": m}
            
            measure_name = m.get("measure")
            aggregation = m.get("aggregation")
            alias = m.get("alias", measure_name)
            
            expr = self.semantic.resolve_measure(measure_name, aggregation)
            measure_exprs.append(f"{expr} AS {self._safe_alias(alias)}")
        
        return dim_exprs, measure_exprs
    
    def build_group_by(self, dimensions: List[str], dataset) -> str:
        """Build GROUP BY clause."""
        if not dimensions:
            return ""
        
        exprs = []
        for dim in dimensions:
            expr = self.semantic.resolve_dimension(dim, dataset)
            exprs.append(expr)
        
        return f"GROUP BY {', '.join(exprs)}"
    
    def build_order_by(self, sort_specs: List[Dict[str, str]]) -> str:
        """Build ORDER BY clause."""
        if not sort_specs:
            return ""
        
        parts = []
        for spec in sort_specs:
            sort = SortSpec(
                column=spec.get("column"),
                direction=spec.get("direction", "ASC"),
                nulls=spec.get("nulls")
            )
            parts.append(sort.to_sql())
        
        return f"ORDER BY {', '.join(parts)}"
    
    def build_aggregation_query(self, dataset_name: str,
                                 dimensions: List[str],
                                 measures: List[Dict[str, Any]],
                                 filters: List[Dict[str, Any]] = None,
                                 sort: List[Dict[str, str]] = None,
                                 limit: int = None) -> str:
        """
        Build a complete aggregation query.
        
        Args:
            dataset_name: Name of the dataset
            dimensions: Dimensions to group by
            measures: Measures to aggregate
            filters: Optional filters
            sort: Optional sort specifications
            limit: Optional row limit
            
        Returns:
            Complete SQL query string
        """
        dataset = self.semantic.get_dataset(dataset_name)
        if not dataset:
            raise ValueError(f"Dataset '{dataset_name}' not found")
        
        # Build base query
        base_sql = self.build_base_query(dataset_name, filters)
        
        # Build select columns
        dim_exprs, measure_exprs = self.build_select_columns(
            dimensions, measures, dataset
        )
        
        select_cols = dim_exprs + measure_exprs
        
        # Build the query
        sql = f"""
SELECT 
    {', '.join(select_cols) if select_cols else '*'}
FROM ({base_sql}) AS base
{self.build_group_by(dimensions, dataset)}
"""
        
        if sort:
            sql += f"\n{self.build_order_by(sort)}"
        
        if limit:
            sql += f"\nLIMIT {limit}"
        
        return sql.strip()
    
    def _safe_alias(self, name: str) -> str:
        """Convert a name to a safe SQL alias."""
        # Replace non-alphanumeric characters with underscores
        safe = ''.join(c if c.isalnum() else '_' for c in name)
        # Ensure it doesn't start with a number
        if safe and safe[0].isdigit():
            safe = '_' + safe
        return safe
    
    def wrap_with_cte(self, query: str, cte_name: str = "base_data") -> str:
        """Wrap a query as a Common Table Expression."""
        return f"WITH {cte_name} AS (\n{query}\n)"
    
    def add_cte(self, existing_cte: str, new_query: str, 
                new_name: str) -> str:
        """Add another CTE to an existing CTE chain."""
        if existing_cte.startswith("WITH "):
            return f"{existing_cte},\n{new_name} AS (\n{new_query}\n)"
        else:
            return f"WITH {new_name} AS (\n{new_query}\n)"
