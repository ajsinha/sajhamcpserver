"""
SAJHA MCP Server - Semantic Layer
Version: 2.9.8

The Semantic Layer provides a business-friendly abstraction over raw database tables,
defining datasets with measures, dimensions, and hierarchies that can be queried
without SQL knowledge.
"""

import json
import os
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Measure:
    """Definition of a measure (metric) in the semantic layer."""
    name: str
    expression: str
    format: str = "number"
    description: str = ""
    requires_window: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "expression": self.expression,
            "format": self.format,
            "description": self.description,
            "requires_window": self.requires_window
        }


@dataclass
class DimensionLevel:
    """A level within a dimension hierarchy."""
    name: str
    expression: str
    column: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "expression": self.expression,
            "column": self.column
        }


@dataclass
class Hierarchy:
    """A hierarchy within a dimension."""
    name: str
    levels: List[DimensionLevel]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "levels": [level.to_dict() for level in self.levels]
        }


@dataclass
class Dimension:
    """Definition of a dimension in the semantic layer."""
    name: str
    column: str
    dimension_type: str = "standard"  # standard, time
    hierarchies: Dict[str, Hierarchy] = field(default_factory=dict)
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "column": self.column,
            "type": self.dimension_type,
            "hierarchies": {k: v.to_dict() for k, v in self.hierarchies.items()},
            "description": self.description
        }


@dataclass
class Join:
    """Definition of a table join."""
    table: str
    join_type: str  # LEFT, RIGHT, INNER, FULL
    on_clause: str
    alias: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "table": self.table,
            "type": self.join_type,
            "on": self.on_clause,
            "alias": self.alias
        }


@dataclass
class Dataset:
    """Definition of an OLAP dataset."""
    name: str
    display_name: str
    description: str
    source_table: str
    joins: List[Join] = field(default_factory=list)
    dimensions: List[str] = field(default_factory=list)
    measures: List[str] = field(default_factory=list)
    default_time_dimension: Optional[str] = None
    row_level_security: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "source_table": self.source_table,
            "joins": [j.to_dict() for j in self.joins],
            "dimensions": self.dimensions,
            "measures": self.measures,
            "default_time_dimension": self.default_time_dimension,
            "row_level_security": self.row_level_security
        }


class SemanticLayer:
    """
    Manages the semantic layer configuration including datasets, measures, and dimensions.
    
    The semantic layer abstracts raw database tables into business-friendly concepts,
    enabling users to perform analytics without writing SQL.
    """
    
    def __init__(self, config_path: str = None):
        """
        Initialize the semantic layer.
        
        Args:
            config_path: Path to the configuration directory containing OLAP configs
        """
        self.config_path = config_path or self._default_config_path()
        self.datasets: Dict[str, Dataset] = {}
        self.measures: Dict[str, Measure] = {}
        self.dimensions: Dict[str, Dimension] = {}
        self._load_configuration()
    
    def _default_config_path(self) -> str:
        """Get the default configuration path."""
        base_path = Path(__file__).parent.parent.parent / "config" / "olap"
        return str(base_path)
    
    def _load_configuration(self):
        """Load all OLAP configurations from files."""
        config_dir = Path(self.config_path)
        
        # Load datasets
        datasets_file = config_dir / "datasets.json"
        if datasets_file.exists():
            self._load_datasets(datasets_file)
        
        # Load measures
        measures_file = config_dir / "measures.json"
        if measures_file.exists():
            self._load_measures(measures_file)
        
        # Load dimensions
        dimensions_file = config_dir / "dimensions.json"
        if dimensions_file.exists():
            self._load_dimensions(dimensions_file)
        
        logger.info(f"Loaded semantic layer: {len(self.datasets)} datasets, "
                   f"{len(self.measures)} measures, {len(self.dimensions)} dimensions")
    
    def _load_datasets(self, file_path: Path):
        """Load dataset definitions from JSON file."""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            for name, config in data.get("datasets", {}).items():
                joins = [
                    Join(
                        table=j["table"],
                        join_type=j.get("type", "LEFT"),
                        on_clause=j["on"],
                        alias=j.get("alias")
                    )
                    for j in config.get("joins", [])
                ]
                
                dataset = Dataset(
                    name=name,
                    display_name=config.get("display_name", name),
                    description=config.get("description", ""),
                    source_table=config["source_table"],
                    joins=joins,
                    dimensions=config.get("dimensions", []),
                    measures=config.get("measures", []),
                    default_time_dimension=config.get("default_time_dimension"),
                    row_level_security=config.get("row_level_security")
                )
                self.datasets[name] = dataset
                
        except Exception as e:
            logger.error(f"Error loading datasets: {e}")
    
    def _load_measures(self, file_path: Path):
        """Load measure definitions from JSON file."""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            for name, config in data.get("measures", {}).items():
                measure = Measure(
                    name=config.get("name", name),
                    expression=config["expression"],
                    format=config.get("format", "number"),
                    description=config.get("description", ""),
                    requires_window=config.get("requires_window", False)
                )
                self.measures[name] = measure
                
        except Exception as e:
            logger.error(f"Error loading measures: {e}")
    
    def _load_dimensions(self, file_path: Path):
        """Load dimension definitions from JSON file."""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            for name, config in data.get("dimensions", {}).items():
                hierarchies = {}
                for h_name, h_config in config.get("hierarchies", {}).items():
                    levels = [
                        DimensionLevel(
                            name=l["name"],
                            expression=l.get("expression", l.get("column", "")),
                            column=l.get("column")
                        )
                        for l in h_config.get("levels", [])
                    ]
                    hierarchies[h_name] = Hierarchy(name=h_name, levels=levels)
                
                dimension = Dimension(
                    name=config.get("name", name),
                    column=config.get("column", name),
                    dimension_type=config.get("type", "standard"),
                    hierarchies=hierarchies,
                    description=config.get("description", "")
                )
                self.dimensions[name] = dimension
                
        except Exception as e:
            logger.error(f"Error loading dimensions: {e}")
    
    def get_dataset(self, name: str) -> Optional[Dataset]:
        """Get a dataset by name."""
        return self.datasets.get(name)
    
    def get_measure(self, name: str) -> Optional[Measure]:
        """Get a measure by name."""
        return self.measures.get(name)
    
    def get_dimension(self, name: str) -> Optional[Dimension]:
        """Get a dimension by name."""
        return self.dimensions.get(name)
    
    def list_datasets(self, include_schema: bool = False) -> List[Dict[str, Any]]:
        """List all available datasets."""
        result = []
        for name, dataset in self.datasets.items():
            info = {
                "name": name,
                "display_name": dataset.display_name,
                "description": dataset.description
            }
            if include_schema:
                info["source_table"] = dataset.source_table
                info["dimensions"] = dataset.dimensions
                info["measures"] = dataset.measures
                info["joins"] = [j.to_dict() for j in dataset.joins]
            result.append(info)
        return result
    
    def describe_dataset(self, name: str) -> Dict[str, Any]:
        """Get detailed information about a dataset."""
        dataset = self.get_dataset(name)
        if not dataset:
            return {"error": f"Dataset '{name}' not found"}
        
        # Get full measure definitions
        measures_info = []
        for m_name in dataset.measures:
            measure = self.get_measure(m_name)
            if measure:
                measures_info.append(measure.to_dict())
            else:
                measures_info.append({"name": m_name, "expression": m_name})
        
        # Get full dimension definitions
        dimensions_info = []
        for d_name in dataset.dimensions:
            dimension = self.get_dimension(d_name)
            if dimension:
                dimensions_info.append(dimension.to_dict())
            else:
                dimensions_info.append({"name": d_name, "column": d_name})
        
        return {
            "name": dataset.name,
            "display_name": dataset.display_name,
            "description": dataset.description,
            "source_table": dataset.source_table,
            "joins": [j.to_dict() for j in dataset.joins],
            "dimensions": dimensions_info,
            "measures": measures_info,
            "default_time_dimension": dataset.default_time_dimension
        }
    
    def resolve_dimension(self, dim_name: str, dataset: Dataset, 
                          hierarchy: str = None, level: str = None) -> str:
        """
        Resolve a dimension name to its SQL expression.
        
        Args:
            dim_name: Name of the dimension
            dataset: The dataset context
            hierarchy: Optional hierarchy name
            level: Optional level within the hierarchy
            
        Returns:
            SQL expression for the dimension
        """
        dimension = self.get_dimension(dim_name)
        
        if not dimension:
            # Assume it's a direct column reference
            return dim_name
        
        if hierarchy and level and hierarchy in dimension.hierarchies:
            hier = dimension.hierarchies[hierarchy]
            for lvl in hier.levels:
                if lvl.name == level:
                    return lvl.expression if lvl.expression else lvl.column
        
        return dimension.column
    
    def resolve_measure(self, measure_name: str, aggregation: str = None) -> str:
        """
        Resolve a measure name to its SQL expression.
        
        Args:
            measure_name: Name of the measure
            aggregation: Optional override aggregation function
            
        Returns:
            SQL expression for the measure
        """
        measure = self.get_measure(measure_name)
        
        if not measure:
            # Assume it's a direct column, apply default aggregation
            agg = aggregation or "SUM"
            return f"{agg}({measure_name})"
        
        if aggregation:
            # Override the aggregation in the expression
            # This is a simplified approach - real implementation would parse the expression
            return measure.expression
        
        return measure.expression
    
    def add_dataset(self, dataset: Dataset) -> bool:
        """Add a new dataset to the semantic layer."""
        self.datasets[dataset.name] = dataset
        self._save_datasets()
        return True
    
    def add_measure(self, measure: Measure) -> bool:
        """Add a new measure to the semantic layer."""
        self.measures[measure.name] = measure
        self._save_measures()
        return True
    
    def add_dimension(self, dimension: Dimension) -> bool:
        """Add a new dimension to the semantic layer."""
        self.dimensions[dimension.name] = dimension
        self._save_dimensions()
        return True
    
    def _save_datasets(self):
        """Save datasets to configuration file."""
        config_dir = Path(self.config_path)
        config_dir.mkdir(parents=True, exist_ok=True)
        
        data = {
            "datasets": {name: ds.to_dict() for name, ds in self.datasets.items()}
        }
        
        with open(config_dir / "datasets.json", 'w') as f:
            json.dump(data, f, indent=2)
    
    def _save_measures(self):
        """Save measures to configuration file."""
        config_dir = Path(self.config_path)
        config_dir.mkdir(parents=True, exist_ok=True)
        
        data = {
            "measures": {name: m.to_dict() for name, m in self.measures.items()}
        }
        
        with open(config_dir / "measures.json", 'w') as f:
            json.dump(data, f, indent=2)
    
    def _save_dimensions(self):
        """Save dimensions to configuration file."""
        config_dir = Path(self.config_path)
        config_dir.mkdir(parents=True, exist_ok=True)
        
        data = {
            "dimensions": {name: d.to_dict() for name, d in self.dimensions.items()}
        }
        
        with open(config_dir / "dimensions.json", 'w') as f:
            json.dump(data, f, indent=2)
    
    def validate_query(self, dataset_name: str, dimensions: List[str], 
                       measures: List[str]) -> Dict[str, Any]:
        """
        Validate that a query specification is valid.
        
        Args:
            dataset_name: Name of the dataset
            dimensions: List of dimension names to use
            measures: List of measure names to use
            
        Returns:
            Validation result with any errors
        """
        errors = []
        warnings = []
        
        dataset = self.get_dataset(dataset_name)
        if not dataset:
            errors.append(f"Dataset '{dataset_name}' not found")
            return {"valid": False, "errors": errors, "warnings": warnings}
        
        # Validate dimensions
        for dim in dimensions:
            if dim not in dataset.dimensions and not self.get_dimension(dim):
                errors.append(f"Dimension '{dim}' not found in dataset")
        
        # Validate measures
        for measure in measures:
            if measure not in dataset.measures and not self.get_measure(measure):
                warnings.append(f"Measure '{measure}' not in dataset definition, will use as raw expression")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
