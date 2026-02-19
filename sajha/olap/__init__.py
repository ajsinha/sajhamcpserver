"""
SAJHA MCP Server - OLAP Analytics Module
Version: 2.9.0

This module provides advanced OLAP (Online Analytical Processing) capabilities
built on top of DuckDB, including:

- Semantic Layer: Business-friendly abstraction over raw data
- Pivot Tables: Multi-dimensional cross-tabulation
- Rollup/Cube: Hierarchical aggregations with subtotals
- Window Functions: Running totals, rankings, moving averages
- Time Series: Temporal analysis with period comparisons
- Statistics: Comprehensive statistical analysis
- Cohort Analysis: Track groups over time
- Sample Data: Generate demo data for testing

Components:
- SemanticLayer: Manages datasets, measures, and dimensions
- PivotEngine: Generates and executes pivot table queries
- RollupEngine: Handles ROLLUP and CUBE operations
- WindowEngine: Window function calculations
- TimeSeriesEngine: Time-based analytics
- StatsEngine: Statistical computations
- CohortEngine: Cohort and retention analysis
- SampleDataGenerator: Create demo datasets
"""

from sajha.olap.semantic_layer import SemanticLayer
from sajha.olap.pivot_engine import PivotEngine, PivotSpec
from sajha.olap.rollup_engine import RollupEngine, RollupSpec
from sajha.olap.window_engine import WindowEngine, WindowSpec
from sajha.olap.timeseries_engine import TimeSeriesEngine, TimeSeriesSpec
from sajha.olap.stats_engine import StatsEngine, StatsSpec, HistogramSpec
from sajha.olap.cohort_engine import CohortEngine, CohortSpec, RetentionSpec
from sajha.olap.sample_data_generator import SampleDataGenerator, generate_sample_data_to_files
from sajha.olap.query_builder import OLAPQueryBuilder

__all__ = [
    'SemanticLayer',
    'PivotEngine', 'PivotSpec',
    'RollupEngine', 'RollupSpec',
    'WindowEngine', 'WindowSpec',
    'TimeSeriesEngine', 'TimeSeriesSpec',
    'StatsEngine', 'StatsSpec', 'HistogramSpec',
    'CohortEngine', 'CohortSpec', 'RetentionSpec',
    'SampleDataGenerator', 'generate_sample_data_to_files',
    'OLAPQueryBuilder'
]

__version__ = "2.9.0"
