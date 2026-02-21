"""
SAJHA MCP Server - Advanced OLAP Tools
Version: 2.9.8

MCP tools for advanced OLAP analytics including pivot tables, rollups,
window functions, time series analysis, statistical calculations,
cohort analysis, and sample data generation.
"""

import json
import logging
import os
import duckdb
from typing import Dict, Any, List, Optional
from pathlib import Path

from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.olap.semantic_layer import SemanticLayer
from sajha.olap.pivot_engine import PivotEngine, PivotSpec
from sajha.olap.rollup_engine import RollupEngine, RollupSpec
from sajha.olap.window_engine import WindowEngine, WindowSpec, WindowCalculation
from sajha.olap.timeseries_engine import TimeSeriesEngine, TimeSeriesSpec
from sajha.olap.stats_engine import StatsEngine, StatsSpec, HistogramSpec
from sajha.olap.cohort_engine import CohortEngine, CohortSpec, RetentionSpec
from sajha.olap.sample_data_generator import SampleDataGenerator

logger = logging.getLogger(__name__)


class DuckDBOLAPAdvancedTool(BaseMCPTool):
    """
    Advanced OLAP analytics tool for DuckDB.
    
    Provides high-level analytics capabilities including:
    - Pivot tables with multi-dimensional aggregations
    - Hierarchical rollups and cubes
    - Window functions for running totals, rankings, etc.
    - Time series analysis with period comparisons
    - Statistical analysis and distributions
    - Cohort and retention analysis
    - Sample data generation for demos
    """
    
    def __init__(self, config=None):
        """
        Initialize the OLAP tool.
        
        Args:
            config: Configuration dict or path string to configuration directory
        """
        # Handle both dict config (from tools_registry) and string path
        if isinstance(config, dict):
            self.config = config
            self.config_path = config.get('config_path') or self._default_config_path()
        elif isinstance(config, str):
            self.config = {}
            self.config_path = config
        else:
            self.config = {}
            self.config_path = self._default_config_path()
        
        # Initialize parent
        super().__init__(self.config)
        
        self.semantic = SemanticLayer(self.config_path)
        self.conn = None
        self._init_connection()
        
        # Initialize engines
        self.pivot_engine = PivotEngine(self.semantic, self.conn)
        self.rollup_engine = RollupEngine(self.semantic, self.conn)
        self.window_engine = WindowEngine(self.semantic, self.conn)
        self.timeseries_engine = TimeSeriesEngine(self.semantic, self.conn)
        self.stats_engine = StatsEngine(self.semantic, self.conn)
        self.cohort_engine = CohortEngine(self.semantic, self.conn)
        self.sample_generator = SampleDataGenerator(self.conn)
    
    def _default_config_path(self) -> str:
        """Get default config path."""
        return str(Path(__file__).parent.parent.parent / "config" / "olap")
    
    def _init_connection(self):
        """Initialize DuckDB connection."""
        try:
            # Connect to in-memory database or configured database
            db_path = Path(self.config_path).parent / "data" / "olap.duckdb"
            if db_path.exists():
                self.conn = duckdb.connect(str(db_path))
            else:
                self.conn = duckdb.connect(":memory:")
            logger.info("DuckDB OLAP connection initialized")
        except Exception as e:
            logger.error(f"Failed to initialize DuckDB: {e}")
            self.conn = duckdb.connect(":memory:")
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """Return list of available OLAP tools."""
        return [
            # Dataset Discovery
            {
                "name": "olap_list_datasets",
                "description": "List all available OLAP datasets with their dimensions and measures. Use this to discover what data is available for analysis.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "include_schema": {
                            "type": "boolean",
                            "description": "Include detailed schema information (dimensions, measures, joins)",
                            "default": False
                        }
                    }
                }
            },
            {
                "name": "olap_describe_dataset",
                "description": "Get detailed information about a specific dataset including all dimensions, measures, and hierarchies available for analysis.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dataset": {
                            "type": "string",
                            "description": "Name of the dataset to describe"
                        }
                    },
                    "required": ["dataset"]
                }
            },
            
            # Pivot Tables
            {
                "name": "olap_pivot_table",
                "description": "Create a pivot table with rows, columns, and aggregated values. Supports multiple measures, automatic totals, and filtering. Perfect for cross-tabulation analysis.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dataset": {
                            "type": "string",
                            "description": "Name of the dataset to query"
                        },
                        "rows": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Dimensions to use as row headers (e.g., ['region', 'product_category'])"
                        },
                        "columns": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Dimensions to pivot as column headers (e.g., ['quarter'])"
                        },
                        "values": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "measure": {"type": "string", "description": "Measure name"},
                                    "aggregation": {"type": "string", "enum": ["SUM", "AVG", "COUNT", "MIN", "MAX", "MEDIAN"]}
                                }
                            },
                            "description": "Measures to aggregate with their aggregation functions"
                        },
                        "filters": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "dimension": {"type": "string"},
                                    "operator": {"type": "string", "enum": ["=", "!=", ">", "<", ">=", "<=", "IN", "NOT IN", "LIKE", "BETWEEN"]},
                                    "value": {}
                                }
                            },
                            "description": "Filters to apply to the data"
                        },
                        "include_totals": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include grand totals row"
                        },
                        "include_subtotals": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include subtotals for each dimension level"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of rows to return"
                        }
                    },
                    "required": ["dataset", "rows", "values"]
                }
            },
            
            # Hierarchical Summary (Rollup/Cube)
            {
                "name": "olap_hierarchical_summary",
                "description": "Create hierarchical summaries using ROLLUP or CUBE operations. Generates subtotals at each level of the dimension hierarchy plus grand totals.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string", "description": "Name of the dataset"},
                        "dimensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Dimensions for hierarchical grouping (order matters for ROLLUP)"
                        },
                        "measures": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "measure": {"type": "string"},
                                    "aggregation": {"type": "string", "default": "SUM"}
                                }
                            },
                            "description": "Measures to aggregate"
                        },
                        "operation": {
                            "type": "string",
                            "enum": ["ROLLUP", "CUBE"],
                            "default": "ROLLUP",
                            "description": "ROLLUP for hierarchical totals (right to left), CUBE for all combinations"
                        },
                        "filters": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["dataset", "dimensions", "measures"]
                }
            },
            
            # Time Series Analysis
            {
                "name": "olap_time_series",
                "description": "Analyze time series data with flexible time grains, automatic gap filling, and period-over-period comparisons (YoY, MoM, etc.).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string"},
                        "time_dimension": {
                            "type": "string",
                            "description": "The date/time dimension to use (e.g., 'order_date')"
                        },
                        "time_grain": {
                            "type": "string",
                            "enum": ["year", "quarter", "month", "week", "day", "hour"],
                            "description": "Time granularity for aggregation"
                        },
                        "measures": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Measures to analyze over time"
                        },
                        "dimensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Additional dimensions for grouping (optional)"
                        },
                        "comparison": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["yoy", "mom", "wow", "qoq", "dod"],
                                    "description": "Period comparison type"
                                }
                            },
                            "description": "Optional period-over-period comparison"
                        },
                        "fill_gaps": {
                            "type": "boolean",
                            "default": True,
                            "description": "Fill missing time periods with zeros"
                        },
                        "date_range": {
                            "type": "object",
                            "properties": {
                                "start_date": {"type": "string"},
                                "end_date": {"type": "string"}
                            },
                            "description": "Optional date range filter"
                        },
                        "filters": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["dataset", "time_dimension", "time_grain", "measures"]
                }
            },
            
            # Window Functions
            {
                "name": "olap_window_analysis",
                "description": "Apply window functions for running totals, rankings, moving averages, percent of total, and period comparisons.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string"},
                        "dimensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Dimensions to include in output"
                        },
                        "measures": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Base measures to include"
                        },
                        "calculations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": [
                                            "running_total", "running_average", "moving_average",
                                            "rank", "dense_rank", "row_number", "percent_rank", "ntile",
                                            "lag", "lead", "first_value", "last_value",
                                            "percent_of_total", "percent_change", "difference_from_previous"
                                        ],
                                        "description": "Type of window calculation"
                                    },
                                    "measure": {"type": "string", "description": "Measure to calculate on"},
                                    "partition_by": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "Dimensions to partition by"
                                    },
                                    "order_by": {"type": "string", "description": "Column to order by"},
                                    "alias": {"type": "string", "description": "Output column name"},
                                    "window_size": {"type": "integer", "description": "Window size for moving calculations"},
                                    "offset": {"type": "integer", "description": "Offset for lag/lead"},
                                    "buckets": {"type": "integer", "description": "Number of buckets for ntile"}
                                },
                                "required": ["type", "measure"]
                            },
                            "description": "Window calculations to apply"
                        },
                        "filters": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["dataset", "dimensions", "calculations"]
                }
            },
            
            # Statistics
            {
                "name": "olap_statistics",
                "description": "Calculate comprehensive statistics including mean, median, standard deviation, percentiles, and distribution metrics.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string"},
                        "measures": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Measures to analyze"
                        },
                        "group_by": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional dimensions to group statistics by"
                        },
                        "statistics": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["summary", "percentiles", "distribution", "correlation"]
                            },
                            "default": ["summary"],
                            "description": "Types of statistics to calculate"
                        },
                        "filters": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["dataset", "measures"]
                }
            },
            
            # Histogram
            {
                "name": "olap_histogram",
                "description": "Generate histogram data for a measure showing frequency distribution across bins.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string"},
                        "measure": {"type": "string", "description": "Measure to create histogram for"},
                        "bins": {
                            "type": "integer",
                            "default": 10,
                            "description": "Number of histogram bins"
                        },
                        "filters": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["dataset", "measure"]
                }
            },
            
            # Top N Analysis
            {
                "name": "olap_top_n",
                "description": "Get top N or bottom N records by a measure, optionally within groups. Includes percentage of total.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string"},
                        "dimensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Dimensions to group by"
                        },
                        "measure": {"type": "string", "description": "Measure to rank by"},
                        "n": {
                            "type": "integer",
                            "default": 10,
                            "description": "Number of top/bottom records"
                        },
                        "direction": {
                            "type": "string",
                            "enum": ["top", "bottom"],
                            "default": "top",
                            "description": "Top N or bottom N"
                        },
                        "within_groups": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Get top N within each group of these dimensions"
                        },
                        "include_others": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include 'Others' row summarizing remaining records"
                        },
                        "filters": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["dataset", "dimensions", "measure"]
                }
            },
            
            # Contribution/Pareto Analysis
            {
                "name": "olap_contribution",
                "description": "Analyze contribution of dimension values to a measure with running totals and Pareto analysis (80/20 rule).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string"},
                        "dimension": {"type": "string", "description": "Dimension to analyze contributions for"},
                        "measure": {"type": "string", "description": "Measure to analyze"},
                        "include_pareto": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include cumulative percentage for Pareto analysis"
                        },
                        "filters": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["dataset", "dimension", "measure"]
                }
            },
            
            # Correlation Analysis
            {
                "name": "olap_correlation",
                "description": "Calculate correlation matrix between multiple measures to identify relationships.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string"},
                        "measures": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                            "description": "Measures to correlate (minimum 2)"
                        },
                        "filters": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["dataset", "measures"]
                }
            },
            
            # Cohort Analysis
            {
                "name": "olap_cohort_analysis",
                "description": "Perform cohort analysis to track groups of users/customers over time. Shows how different cohorts behave across multiple periods, ideal for understanding retention, engagement, and revenue patterns.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string", "description": "Name of the dataset"},
                        "cohort_dimension": {
                            "type": "string",
                            "description": "Dimension that defines the cohort (e.g., 'signup_month', 'first_purchase_date')"
                        },
                        "time_dimension": {
                            "type": "string",
                            "description": "Time dimension for tracking activity over time"
                        },
                        "entity_dimension": {
                            "type": "string",
                            "description": "Entity to track (e.g., 'customer_id', 'user_id')"
                        },
                        "measure": {
                            "type": "string",
                            "description": "Measure to aggregate (e.g., 'revenue', 'order_count')"
                        },
                        "aggregation": {
                            "type": "string",
                            "enum": ["COUNT_DISTINCT", "SUM", "AVG"],
                            "default": "COUNT_DISTINCT",
                            "description": "How to aggregate the measure"
                        },
                        "time_grain": {
                            "type": "string",
                            "enum": ["year", "quarter", "month", "week", "day"],
                            "default": "month",
                            "description": "Time granularity for cohort periods"
                        },
                        "periods": {
                            "type": "integer",
                            "default": 12,
                            "description": "Number of periods to track after cohort formation"
                        },
                        "show_percentages": {
                            "type": "boolean",
                            "default": True,
                            "description": "Show retention percentages (true) or absolute values (false)"
                        },
                        "filters": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["dataset", "cohort_dimension", "time_dimension", "entity_dimension", "measure"]
                }
            },
            
            # Retention Analysis
            {
                "name": "olap_retention_analysis",
                "description": "Analyze user/customer retention over time. Shows what percentage of users from each cohort remain active in subsequent periods.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string", "description": "Name of the dataset"},
                        "cohort_dimension": {
                            "type": "string",
                            "description": "Dimension defining the cohort (e.g., 'signup_date', 'first_order_date')"
                        },
                        "activity_dimension": {
                            "type": "string",
                            "description": "Dimension indicating activity (e.g., 'order_date', 'login_date')"
                        },
                        "entity_dimension": {
                            "type": "string",
                            "description": "Entity to track (e.g., 'customer_id', 'user_id')"
                        },
                        "time_grain": {
                            "type": "string",
                            "enum": ["year", "quarter", "month", "week", "day"],
                            "default": "month"
                        },
                        "periods": {
                            "type": "integer",
                            "default": 12,
                            "description": "Number of periods to track"
                        },
                        "filters": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["dataset", "cohort_dimension", "activity_dimension", "entity_dimension"]
                }
            },
            
            # Sample Data Generation
            {
                "name": "olap_generate_sample_data",
                "description": "Generate sample sales data for OLAP demonstrations and testing. Creates customers, products, and orders tables with realistic data patterns.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "num_customers": {
                            "type": "integer",
                            "default": 500,
                            "description": "Number of customers to generate"
                        },
                        "num_orders": {
                            "type": "integer",
                            "default": 5000,
                            "description": "Number of orders to generate"
                        },
                        "start_date": {
                            "type": "string",
                            "default": "2023-01-01",
                            "description": "Start date for order data (YYYY-MM-DD)"
                        },
                        "end_date": {
                            "type": "string",
                            "default": "2024-12-31",
                            "description": "End date for order data (YYYY-MM-DD)"
                        },
                        "save_config": {
                            "type": "boolean",
                            "default": True,
                            "description": "Save OLAP configuration files for the generated data"
                        }
                    }
                }
            }
        ]
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route tool calls to appropriate handlers.
        
        Args:
            name: Tool name
            arguments: Tool arguments
            
        Returns:
            Tool result
        """
        handlers = {
            "olap_list_datasets": self._list_datasets,
            "olap_describe_dataset": self._describe_dataset,
            "olap_pivot_table": self._pivot_table,
            "olap_hierarchical_summary": self._hierarchical_summary,
            "olap_time_series": self._time_series,
            "olap_window_analysis": self._window_analysis,
            "olap_statistics": self._statistics,
            "olap_histogram": self._histogram,
            "olap_top_n": self._top_n,
            "olap_contribution": self._contribution,
            "olap_correlation": self._correlation,
            "olap_cohort_analysis": self._cohort_analysis,
            "olap_retention_analysis": self._retention_analysis,
            "olap_generate_sample_data": self._generate_sample_data
        }
        
        handler = handlers.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}
        
        try:
            return await handler(arguments)
        except Exception as e:
            logger.error(f"Error in {name}: {e}", exc_info=True)
            return {"error": str(e)}
    
    async def _list_datasets(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List all available datasets."""
        include_schema = args.get("include_schema", False)
        datasets = self.semantic.list_datasets(include_schema)
        return {
            "success": True,
            "datasets": datasets,
            "count": len(datasets)
        }
    
    async def _describe_dataset(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Describe a specific dataset."""
        dataset_name = args.get("dataset")
        description = self.semantic.describe_dataset(dataset_name)
        
        if "error" in description:
            return {"success": False, "error": description["error"]}
        
        return {
            "success": True,
            "dataset": description
        }
    
    async def _pivot_table(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute pivot table query."""
        spec = PivotSpec(
            dataset=args['dataset'],
            rows=args['rows'],
            columns=args.get('columns', []),
            values=args['values'],
            filters=args.get('filters', []),
            include_totals=args.get('include_totals', True),
            include_subtotals=args.get('include_subtotals', False),
            limit=args.get('limit')
        )
        
        result = self.pivot_engine.execute_pivot(spec)
        return result
    
    async def _hierarchical_summary(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute hierarchical summary (rollup/cube)."""
        spec = RollupSpec(
            dataset=args['dataset'],
            dimensions=args['dimensions'],
            measures=args['measures'],
            operation=args.get('operation', 'ROLLUP'),
            filters=args.get('filters', [])
        )
        
        result = self.rollup_engine.execute_rollup(spec)
        return result
    
    async def _time_series(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute time series analysis."""
        spec = TimeSeriesSpec(
            dataset=args['dataset'],
            time_dimension=args['time_dimension'],
            time_grain=args['time_grain'],
            measures=args['measures'],
            dimensions=args.get('dimensions', []),
            comparison=args.get('comparison'),
            fill_gaps=args.get('fill_gaps', True),
            date_range=args.get('date_range'),
            filters=args.get('filters', [])
        )
        
        result = self.timeseries_engine.execute_time_series(spec)
        return result
    
    async def _window_analysis(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute window function analysis."""
        calculations = []
        for calc in args.get('calculations', []):
            calculations.append(WindowCalculation(
                calc_type=calc['type'],
                measure=calc['measure'],
                partition_by=calc.get('partition_by', []),
                order_by=calc.get('order_by'),
                alias=calc.get('alias'),
                window_size=calc.get('window_size', 3),
                offset=calc.get('offset', 1),
                buckets=calc.get('buckets', 4)
            ))
        
        spec = WindowSpec(
            dataset=args['dataset'],
            base_dimensions=args['dimensions'],
            base_measures=args.get('measures', []),
            window_calculations=calculations,
            filters=args.get('filters', [])
        )
        
        result = self.window_engine.execute_window(spec)
        return result
    
    async def _statistics(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute statistical analysis."""
        spec = StatsSpec(
            dataset=args['dataset'],
            measures=args['measures'],
            group_by=args.get('group_by'),
            statistics=args.get('statistics', ['summary']),
            filters=args.get('filters', [])
        )
        
        result = self.stats_engine.execute_statistics(spec)
        return result
    
    async def _histogram(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Generate histogram."""
        spec = HistogramSpec(
            dataset=args['dataset'],
            measure=args['measure'],
            bins=args.get('bins', 10),
            filters=args.get('filters', [])
        )
        
        result = self.stats_engine.execute_histogram(spec)
        return result
    
    async def _top_n(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute top N analysis."""
        dataset = self.semantic.get_dataset(args['dataset'])
        if not dataset:
            return {"success": False, "error": f"Dataset '{args['dataset']}' not found"}
        
        dimensions = args['dimensions']
        measure = args['measure']
        n = args.get('n', 10)
        direction = args.get('direction', 'top')
        within_groups = args.get('within_groups', [])
        include_others = args.get('include_others', False)
        
        # Build the query
        dim_cols = [self.semantic.resolve_dimension(d, dataset) for d in dimensions]
        dim_aliases = [self._safe_alias(d) for d in dimensions]
        
        measure_obj = self.semantic.get_measure(measure)
        if measure_obj:
            measure_expr = measure_obj.expression
        else:
            measure_expr = f"SUM({measure})"
        
        order_dir = "DESC" if direction == "top" else "ASC"
        
        base_sql = self._build_base_query(dataset, args.get('filters', []))
        
        if within_groups:
            # Top N within groups using window function
            partition_cols = [self._safe_alias(g) for g in within_groups]
            sql = f"""
WITH aggregated AS (
    SELECT 
        {', '.join(f'{col} AS {alias}' for col, alias in zip(dim_cols, dim_aliases))},
        {measure_expr} AS {self._safe_alias(measure)}
    FROM ({base_sql}) AS base
    GROUP BY {', '.join(dim_cols)}
),
ranked AS (
    SELECT 
        *,
        ROW_NUMBER() OVER (PARTITION BY {', '.join(partition_cols)} ORDER BY {self._safe_alias(measure)} {order_dir}) AS rank
    FROM aggregated
)
SELECT * FROM ranked WHERE rank <= {n}
ORDER BY {', '.join(partition_cols)}, rank
"""
        else:
            sql = f"""
WITH aggregated AS (
    SELECT 
        {', '.join(f'{col} AS {alias}' for col, alias in zip(dim_cols, dim_aliases))},
        {measure_expr} AS {self._safe_alias(measure)}
    FROM ({base_sql}) AS base
    GROUP BY {', '.join(dim_cols)}
)
SELECT 
    *,
    ROUND(100.0 * {self._safe_alias(measure)} / SUM({self._safe_alias(measure)}) OVER (), 2) AS pct_of_total
FROM aggregated
ORDER BY {self._safe_alias(measure)} {order_dir}
LIMIT {n}
"""
        
        try:
            result = self.conn.execute(sql).fetchall()
            columns = [desc[0] for desc in self.conn.description]
            
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
                "n": n,
                "direction": direction,
                "sql": sql
            }
        except Exception as e:
            return {"success": False, "error": str(e), "sql": sql}
    
    async def _contribution(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute contribution/Pareto analysis."""
        dataset = self.semantic.get_dataset(args['dataset'])
        if not dataset:
            return {"success": False, "error": f"Dataset '{args['dataset']}' not found"}
        
        dimension = args['dimension']
        measure = args['measure']
        include_pareto = args.get('include_pareto', True)
        
        dim_col = self.semantic.resolve_dimension(dimension, dataset)
        dim_alias = self._safe_alias(dimension)
        
        measure_obj = self.semantic.get_measure(measure)
        if measure_obj:
            measure_expr = measure_obj.expression
        else:
            measure_expr = f"SUM({measure})"
        
        base_sql = self._build_base_query(dataset, args.get('filters', []))
        
        sql = f"""
WITH aggregated AS (
    SELECT 
        {dim_col} AS {dim_alias},
        {measure_expr} AS {self._safe_alias(measure)}
    FROM ({base_sql}) AS base
    GROUP BY {dim_col}
)
SELECT 
    {dim_alias},
    {self._safe_alias(measure)},
    ROUND(100.0 * {self._safe_alias(measure)} / SUM({self._safe_alias(measure)}) OVER (), 2) AS pct_of_total,
    SUM({self._safe_alias(measure)}) OVER (ORDER BY {self._safe_alias(measure)} DESC) AS cumulative_value,
    ROUND(100.0 * SUM({self._safe_alias(measure)}) OVER (ORDER BY {self._safe_alias(measure)} DESC) / 
          SUM({self._safe_alias(measure)}) OVER (), 2) AS cumulative_pct,
    ROW_NUMBER() OVER (ORDER BY {self._safe_alias(measure)} DESC) AS rank
FROM aggregated
ORDER BY {self._safe_alias(measure)} DESC
"""
        
        try:
            result = self.conn.execute(sql).fetchall()
            columns = [desc[0] for desc in self.conn.description]
            
            data = []
            for row in result:
                row_dict = {}
                for i, col in enumerate(columns):
                    val = row[i]
                    if hasattr(val, 'isoformat'):
                        val = val.isoformat()
                    row_dict[col] = val
                data.append(row_dict)
            
            # Find 80% threshold for Pareto
            pareto_80_count = 0
            for row in data:
                if row.get('cumulative_pct', 0) <= 80:
                    pareto_80_count += 1
            
            return {
                "success": True,
                "data": data,
                "columns": columns,
                "pareto_insight": f"{pareto_80_count} of {len(data)} items contribute to 80% of total",
                "sql": sql
            }
        except Exception as e:
            return {"success": False, "error": str(e), "sql": sql}
    
    async def _correlation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute correlation analysis."""
        spec = StatsSpec(
            dataset=args['dataset'],
            measures=args['measures'],
            filters=args.get('filters', [])
        )
        
        result = self.stats_engine.execute_correlation(spec)
        return result
    
    async def _cohort_analysis(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute cohort analysis."""
        spec = CohortSpec(
            dataset=args['dataset'],
            cohort_dimension=args['cohort_dimension'],
            time_dimension=args['time_dimension'],
            entity_dimension=args['entity_dimension'],
            measure=args['measure'],
            aggregation=args.get('aggregation', 'COUNT_DISTINCT'),
            time_grain=args.get('time_grain', 'month'),
            periods=args.get('periods', 12),
            filters=args.get('filters', []),
            show_percentages=args.get('show_percentages', True)
        )
        
        result = self.cohort_engine.execute_cohort_analysis(spec)
        
        # Add summary if successful
        if result.get('success'):
            summary = self.cohort_engine.get_cohort_summary(spec)
            if summary.get('success'):
                result['summary'] = summary['summary']
        
        return result
    
    async def _retention_analysis(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute retention analysis."""
        spec = RetentionSpec(
            dataset=args['dataset'],
            cohort_dimension=args['cohort_dimension'],
            activity_dimension=args['activity_dimension'],
            entity_dimension=args['entity_dimension'],
            time_grain=args.get('time_grain', 'month'),
            periods=args.get('periods', 12),
            filters=args.get('filters', [])
        )
        
        result = self.cohort_engine.execute_retention_analysis(spec)
        return result
    
    async def _generate_sample_data(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Generate sample OLAP data for demonstrations."""
        num_customers = args.get('num_customers', 500)
        num_orders = args.get('num_orders', 5000)
        start_date = args.get('start_date', '2023-01-01')
        end_date = args.get('end_date', '2024-12-31')
        save_config = args.get('save_config', True)
        
        # Generate the sample data
        result = self.sample_generator.generate_all_sample_data(
            num_customers=num_customers,
            num_orders=num_orders,
            start_date=start_date,
            end_date=end_date
        )
        
        if not result['success']:
            return result
        
        # Get table statistics
        stats = self.sample_generator.get_table_statistics()
        result['table_statistics'] = stats
        
        # Save config if requested
        if save_config:
            config = self.sample_generator.generate_sample_olap_config()
            result['olap_config'] = {
                "datasets": list(config['datasets'].keys()),
                "measures": list(config['measures'].keys()),
                "dimensions": list(config['dimensions'].keys())
            }
            
            # Reload semantic layer with new config
            import json
            from pathlib import Path
            
            config_dir = Path(self.config_path)
            config_dir.mkdir(parents=True, exist_ok=True)
            
            with open(config_dir / "datasets.json", "w") as f:
                json.dump({"datasets": config["datasets"]}, f, indent=2)
            
            with open(config_dir / "measures.json", "w") as f:
                json.dump({"measures": config["measures"]}, f, indent=2)
            
            with open(config_dir / "dimensions.json", "w") as f:
                json.dump({"dimensions": config["dimensions"]}, f, indent=2)
            
            # Reload semantic layer
            self.semantic = SemanticLayer(self.config_path)
            
            result['config_files_saved'] = True
        
        return result
    
    def _build_base_query(self, dataset, filters: List[Dict]) -> str:
        """Build the base SELECT with joins and filters."""
        sql = f"SELECT * FROM {dataset.source_table}"
        
        for join in dataset.joins:
            alias = f" AS {join.alias}" if join.alias else ""
            sql += f"\n{join.join_type} JOIN {join.table}{alias} ON {join.on_clause}"
        
        if filters:
            where_clauses = []
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
                    where_clauses.append(f"{col} IN ({formatted})")
                else:
                    formatted = f"'{val}'" if isinstance(val, str) else str(val)
                    where_clauses.append(f"{col} {op} {formatted}")
            
            if where_clauses:
                sql += f"\nWHERE {' AND '.join(where_clauses)}"
        
        return sql
    
    def _safe_alias(self, name: str) -> str:
        """Convert a name to a safe SQL alias."""
        safe = ''.join(c if c.isalnum() else '_' for c in str(name))
        if safe and safe[0].isdigit():
            safe = '_' + safe
        return safe
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute tool - routes to call_tool for async handling.
        This is a synchronous wrapper for the async call_tool method.
        """
        import asyncio
        tool_name = arguments.get('_tool_name', 'olap_list_datasets')
        return asyncio.get_event_loop().run_until_complete(self.call_tool(tool_name, arguments))
    
    def get_input_schema(self) -> Dict:
        """Get combined input schema for all OLAP tools."""
        return {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Dataset name"},
                "tool_name": {"type": "string", "description": "OLAP tool to call"}
            }
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for OLAP tools."""
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {"type": "array"},
                "error": {"type": "string"}
            }
        }


class CustomerOLAPTool(BaseMCPTool):
    """
    Customer OLAP Analytics Tool.
    
    Provides pivot table analysis for the customer_olap dataset with
    pre-configured dimensions and measures for customer analytics.
    """
    
    # Define available dimensions and their SQL expressions
    DIMENSIONS = {
        "customer_segment": "customers.customer_segment",
        "customer_tier": "customers.customer_tier",
        "region": "customers.region",
        "country": "customers.country",
        "acquisition_channel": "customers.acquisition_channel",
        "age_group": "customers.age_group",
        "product_category": "orders.product_category",
        "product_name": "orders.product_name",
        "payment_method": "orders.payment_method",
        "sales_rep": "orders.sales_rep",
        "order_date": "orders.order_date",
        "signup_date": "customers.signup_date",
        "order_year": "EXTRACT(YEAR FROM orders.order_date::DATE)",
        "order_month": "EXTRACT(MONTH FROM orders.order_date::DATE)",
        "order_quarter": "CONCAT('Q', EXTRACT(QUARTER FROM orders.order_date::DATE))"
    }
    
    # Define available measures with their SQL expressions
    MEASURES = {
        "order_count": "COUNT(DISTINCT orders.order_id)",
        "customer_count": "COUNT(DISTINCT customers.customer_id)",
        "total_revenue": "COALESCE(SUM(orders.quantity * orders.unit_price * (1 - orders.discount_pct/100.0)), 0)",
        "total_quantity": "COALESCE(SUM(orders.quantity), 0)",
        "avg_order_value": "COALESCE(AVG(orders.quantity * orders.unit_price * (1 - orders.discount_pct/100.0)), 0)",
        "total_discount": "COALESCE(SUM(orders.quantity * orders.unit_price * orders.discount_pct/100.0), 0)",
        "total_shipping": "COALESCE(SUM(orders.shipping_cost), 0)",
        "avg_discount_pct": "COALESCE(AVG(orders.discount_pct), 0)",
        "gross_profit": "COALESCE(SUM((orders.unit_price - COALESCE(products.unit_cost, 0)) * orders.quantity * (1 - orders.discount_pct/100.0)), 0)",
        "profit_margin": "COALESCE(AVG((orders.unit_price - COALESCE(products.unit_cost, 0)) / NULLIF(orders.unit_price, 0) * 100), 0)"
    }
    
    def __init__(self, config: Dict = None):
        """Initialize the Customer OLAP tool."""
        super().__init__(config)
        self.config = config or {}
        self.conn = None
        self._init_connection()
    
    def _init_connection(self):
        """Initialize DuckDB connection."""
        try:
            self.conn = duckdb.connect(":memory:")
            logger.info("CustomerOLAPTool: DuckDB connection initialized")
        except Exception as e:
            logger.error(f"Failed to initialize DuckDB: {e}")
            raise
    
    def _get_data_path(self) -> str:
        """Get the data directory path from config or dynamically."""
        # Try to get from config first (supports ${variable} substitution)
        if self.config and 'data_directory' in self.config:
            data_dir = self.config['data_directory']
            # If it's a relative path, make it absolute from project root
            if data_dir and not os.path.isabs(data_dir):
                module_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(module_dir)))
                data_dir = os.path.join(project_root, data_dir.lstrip('./'))
            return data_dir
        
        # Fall back to relative path from module location
        module_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(module_dir)))
        return os.path.join(project_root, 'data', 'duckdb')
    
    def _get_base_query(self) -> str:
        """Get the base FROM/JOIN clause for customer OLAP queries."""
        base_path = self._get_data_path()
        
        return f"""
        FROM read_csv_auto('{base_path}/customers.csv') AS customers
        LEFT JOIN read_csv_auto('{base_path}/orders.csv') AS orders
            ON customers.customer_id = orders.customer_id
        LEFT JOIN read_csv_auto('{base_path}/products.csv') AS products
            ON orders.product_name = products.product_name
        """
    
    def _build_filter_clause(self, filters: Dict) -> str:
        """Build WHERE clause from filters."""
        if not filters:
            return ""
        
        conditions = []
        for key, value in filters.items():
            if key in self.DIMENSIONS:
                col = self.DIMENSIONS[key]
                if isinstance(value, list):
                    # IN clause for multiple values
                    values_str = ", ".join([f"'{v}'" if isinstance(v, str) else str(v) for v in value])
                    conditions.append(f"{col} IN ({values_str})")
                elif isinstance(value, str):
                    conditions.append(f"{col} = '{value}'")
                else:
                    conditions.append(f"{col} = {value}")
        
        return "WHERE " + " AND ".join(conditions) if conditions else ""
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute customer OLAP pivot query.
        
        Args:
            arguments: Query parameters including rows, columns, measures, filters
            
        Returns:
            Query results with columns, data, and metadata
        """
        import time
        start_time = time.time()
        
        try:
            # Debug: log incoming arguments
            logger.debug(f"CustomerOLAPTool received arguments: {arguments}")
            
            # Get parameters
            rows = arguments.get('rows', [])
            columns = arguments.get('columns', [])
            measures = arguments.get('measures', ['total_revenue'])
            filters = arguments.get('filters', {})
            order_by = arguments.get('order_by')
            limit = arguments.get('limit', 100)
            
            # Helper function to normalize array inputs
            def normalize_list(value, default=None):
                """Convert string or comma-separated string to list."""
                if value is None:
                    return default or []
                if isinstance(value, list):
                    # Handle list of single comma-separated string like ["a, b, c"]
                    if len(value) == 1 and isinstance(value[0], str) and ',' in value[0]:
                        return [item.strip() for item in value[0].split(',')]
                    return value
                if isinstance(value, str):
                    # Handle comma-separated string like "a, b, c"
                    if ',' in value:
                        return [item.strip() for item in value.split(',')]
                    return [value.strip()] if value.strip() else default or []
                return default or []
            
            # Normalize all list inputs
            rows = normalize_list(rows, [])
            columns = normalize_list(columns, [])
            measures = normalize_list(measures, ['total_revenue'])
            
            if filters is None:
                filters = {}
            
            logger.debug(f"Normalized - rows: {rows}, columns: {columns}, measures: {measures}")
            
            # Validate we have at least one row dimension
            if not rows:
                return {
                    "success": False,
                    "error": "At least one row dimension is required. Available: " + ", ".join(self.DIMENSIONS.keys())
                }
            
            # Validate dimensions
            all_dims = list(rows) + list(columns)
            for dim in all_dims:
                if dim not in self.DIMENSIONS:
                    return {
                        "success": False,
                        "error": f"Unknown dimension: {dim}. Available: {list(self.DIMENSIONS.keys())}"
                    }
            
            # Validate measures
            for measure in measures:
                if measure not in self.MEASURES:
                    return {
                        "success": False,
                        "error": f"Unknown measure: {measure}. Available: {list(self.MEASURES.keys())}"
                    }
            
            # Build SELECT clause
            select_parts = []
            
            # Add dimension columns
            for dim in all_dims:
                col_expr = self.DIMENSIONS[dim]
                select_parts.append(f"{col_expr} AS {dim}")
            
            # Add measure columns
            for measure in measures:
                measure_expr = self.MEASURES[measure]
                select_parts.append(f"{measure_expr} AS {measure}")
            
            # Build GROUP BY clause
            group_by_parts = [self.DIMENSIONS[dim] for dim in all_dims]
            
            # Build query
            select_clause = ", ".join(select_parts)
            base_query = self._get_base_query()
            filter_clause = self._build_filter_clause(filters)
            group_by_clause = f"GROUP BY {', '.join(group_by_parts)}" if group_by_parts else ""
            
            # Build ORDER BY clause
            order_clause = ""
            if order_by:
                if order_by.startswith('-'):
                    order_clause = f"ORDER BY {order_by[1:]} DESC"
                else:
                    order_clause = f"ORDER BY {order_by} ASC"
            elif measures:
                order_clause = f"ORDER BY {measures[0]} DESC"
            
            # Build complete query
            query = f"""
            SELECT {select_clause}
            {base_query}
            {filter_clause}
            {group_by_clause}
            {order_clause}
            LIMIT {limit}
            """
            
            # Execute query
            result = self.conn.execute(query)
            
            # Get column names
            result_columns = [desc[0] for desc in result.description]
            
            # Fetch all rows
            rows_data = result.fetchall()
            
            # Convert to list of dicts
            data = []
            for row in rows_data:
                row_dict = {}
                for i, col in enumerate(result_columns):
                    val = row[i]
                    # Format numeric values
                    if isinstance(val, float):
                        row_dict[col] = round(val, 2)
                    else:
                        row_dict[col] = val
                data.append(row_dict)
            
            execution_time = (time.time() - start_time) * 1000
            
            return {
                "success": True,
                "columns": result_columns,
                "data": data,
                "row_count": len(data),
                "query": query.strip(),
                "execution_time_ms": round(execution_time, 2),
                "available_dimensions": list(self.DIMENSIONS.keys()),
                "available_measures": list(self.MEASURES.keys())
            }
            
        except Exception as e:
            logger.error(f"CustomerOLAPTool execution error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_input_schema(self) -> Dict:
        """Get input schema for the tool."""
        return {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": f"Row dimensions. Available: {list(self.DIMENSIONS.keys())}"
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Column dimensions (for pivoting)"
                },
                "measures": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": f"Measures to aggregate. Available: {list(self.MEASURES.keys())}"
                },
                "filters": {"type": "object"},
                "order_by": {"type": "string"},
                "limit": {"type": "integer", "default": 100}
            },
            "required": ["rows", "measures"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for the tool."""
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "columns": {"type": "array"},
                "data": {"type": "array"},
                "row_count": {"type": "integer"},
                "query": {"type": "string"},
                "execution_time_ms": {"type": "number"}
            }
        }


class DuckDBSQLTool(BaseMCPTool):
    """
    Direct SQL Query Tool for DuckDB.
    
    Executes arbitrary SQL queries against the customer/orders/products
    CSV data files using DuckDB.
    """
    
    def __init__(self, config: Dict = None):
        """Initialize the SQL tool."""
        super().__init__(config)
        self.config = config or {}
        self.conn = None
        self.data_dir = self._get_data_path()
        self._init_connection()
    
    def _get_data_path(self) -> str:
        """Get the data directory path from config or dynamically."""
        # Try to get from config first (supports ${variable} substitution)
        if self.config and 'data_directory' in self.config:
            data_dir = self.config['data_directory']
            # If it's a relative path, make it absolute from project root
            if data_dir and not os.path.isabs(data_dir):
                module_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(module_dir)))
                data_dir = os.path.join(project_root, data_dir.lstrip('./'))
            return data_dir
        
        # Fall back to relative path from module location
        module_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(module_dir)))
        return os.path.join(project_root, 'data', 'duckdb')
    
    def _init_connection(self):
        """Initialize DuckDB connection and create views for CSV files."""
        try:
            self.conn = duckdb.connect(":memory:")
            
            # Create views for each CSV file
            csv_files = ['customers', 'orders', 'products']
            for table_name in csv_files:
                file_path = f"{self.data_dir}/{table_name}.csv"
                create_view = f"""
                    CREATE OR REPLACE VIEW {table_name} AS 
                    SELECT * FROM read_csv_auto('{file_path}')
                """
                self.conn.execute(create_view)
            
            logger.info(f"DuckDBSQLTool: Initialized with tables from {self.data_dir}")
        except Exception as e:
            logger.error(f"Failed to initialize DuckDB: {e}")
            raise
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute SQL query.
        
        Args:
            arguments: Contains 'sql' query and optional 'limit'
            
        Returns:
            Query results with columns, data, and metadata
        """
        import time
        start_time = time.time()
        
        try:
            sql = arguments.get('sql', '')
            limit = arguments.get('limit', 100)
            
            if not sql:
                return {
                    "success": False,
                    "error": "SQL query is required"
                }
            
            # Check for dangerous operations
            sql_upper = sql.upper()
            forbidden = ['DROP', 'DELETE', 'TRUNCATE', 'ALTER', 'INSERT', 'UPDATE', 'CREATE TABLE']
            for keyword in forbidden:
                if keyword in sql_upper:
                    return {
                        "success": False,
                        "error": f"Operation not allowed: {keyword}. Only SELECT queries are permitted."
                    }
            
            # Add LIMIT if not present
            if 'LIMIT' not in sql_upper:
                sql = f"{sql.rstrip(';')} LIMIT {limit}"
            
            # Execute query
            result = self.conn.execute(sql)
            
            # Get column names
            columns = [desc[0] for desc in result.description]
            
            # Fetch all rows
            rows = result.fetchall()
            
            # Convert to list of dicts
            data = []
            for row in rows:
                row_dict = {}
                for i, col in enumerate(columns):
                    val = row[i]
                    if isinstance(val, float):
                        row_dict[col] = round(val, 2)
                    else:
                        row_dict[col] = val
                data.append(row_dict)
            
            execution_time = (time.time() - start_time) * 1000
            
            return {
                "success": True,
                "columns": columns,
                "data": data,
                "row_count": len(data),
                "sql": sql,
                "execution_time_ms": round(execution_time, 2),
                "tables_available": ["customers", "orders", "products"]
            }
            
        except Exception as e:
            logger.error(f"DuckDBSQLTool execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "sql": arguments.get('sql', '')
            }
    
    def get_input_schema(self) -> Dict:
        """Get input schema for the tool."""
        return {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "SQL query to execute. Tables: customers, orders, products"
                },
                "limit": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum rows to return"
                }
            },
            "required": ["sql"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for the tool."""
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "columns": {"type": "array"},
                "data": {"type": "array"},
                "row_count": {"type": "integer"},
                "sql": {"type": "string"},
                "execution_time_ms": {"type": "number"}
            }
        }


# Tool registration for SAJHA
def register_tools(registry):
    """Register OLAP tools with the tool registry."""
    tool = DuckDBOLAPAdvancedTool()
    for tool_def in tool.get_tools():
        registry.register_tool(tool_def['name'], tool_def, tool.call_tool)
