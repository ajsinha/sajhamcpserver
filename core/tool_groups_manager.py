"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Tool Groups Manager - Dynamic tool grouping for Help page
Scans tool JSON configs and groups them logically, with periodic refresh
"""

import os
import json
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class ToolGroupsManager:
    """
    Manages dynamic grouping of tools based on their JSON configurations.
    Automatically refreshes every N minutes to stay current with config changes.
    """
    
    # Category mappings - maps raw categories to display groups
    CATEGORY_MAPPINGS = {
        # Central Banks & Economic Data
        'Economic Data': 'Central Banks & Economic Data',
        'Monetary Policy': 'Central Banks & Economic Data',
        'Monetary Data': 'Central Banks & Economic Data',
        'Inflation Data': 'Central Banks & Economic Data',
        'Foreign Exchange': 'Central Banks & Economic Data',
        
        # Financial & SEC Data
        'SEC EDGAR': 'SEC EDGAR & Regulatory',
        'Financial Analysis': 'Financial Markets',
        'Financial Data': 'Financial Markets',
        
        # Web Tools
        'Web Search': 'Web Search & Research',
        'Web Scraping': 'Web Crawling & Scraping',
        'Targeted Search': 'Web Search & Research',
        'Research': 'Web Search & Research',
        'News Search': 'Web Search & Research',
        
        # Data & Analytics
        'Data Analytics': 'Database & Analytics',
        'Data Query': 'Database & Analytics',
        
        # Document Processing
        'Document Processing': 'Document Processing',
        
        # Statistics
        'Global Statistics': 'Global Statistics & Data',
        'Crime Statistics': 'Government & Public Data',
        
        # Knowledge
        'Information Retrieval': 'Knowledge & Encyclopedia',
    }
    
    # Group metadata - icons, colors, descriptions
    GROUP_METADATA = {
        'Central Banks & Economic Data': {
            'icon': 'bi-bank',
            'color': 'primary',
            'description': 'Access economic indicators from Federal Reserve, ECB, Bank of Canada, Bank of Japan, and other central banks worldwide.',
            'order': 1
        },
        'SEC EDGAR & Regulatory': {
            'icon': 'bi-file-earmark-ruled',
            'color': 'danger',
            'description': 'Search SEC filings, company facts, insider trading, institutional holdings, and regulatory documents.',
            'order': 2
        },
        'Financial Markets': {
            'icon': 'bi-graph-up-arrow',
            'color': 'success',
            'description': 'Real-time stock quotes, historical data, company investor relations, earnings reports, and financial analysis.',
            'order': 3
        },
        'Web Search & Research': {
            'icon': 'bi-search',
            'color': 'info',
            'description': 'Search the web using Google, Tavily for AI research, and domain-specific searches.',
            'order': 4
        },
        'Web Crawling & Scraping': {
            'icon': 'bi-globe',
            'color': 'warning',
            'description': 'Crawl websites, extract content, links, metadata, and check robots.txt compliance.',
            'order': 5
        },
        'Database & Analytics': {
            'icon': 'bi-database',
            'color': 'secondary',
            'description': 'Query databases using DuckDB and SQL, analyze CSV/Parquet/JSON files with powerful analytics.',
            'order': 6
        },
        'Document Processing': {
            'icon': 'bi-file-earmark-word',
            'color': 'primary',
            'description': 'Read and extract data from Microsoft Word documents, Excel spreadsheets, and other office formats.',
            'order': 7
        },
        'Global Statistics & Data': {
            'icon': 'bi-globe2',
            'color': 'info',
            'description': 'Access World Bank indicators, IMF economic data, UN sustainable development goals, and trade statistics.',
            'order': 8
        },
        'Government & Public Data': {
            'icon': 'bi-building',
            'color': 'dark',
            'description': 'FBI crime statistics, government agency data, and public records.',
            'order': 9
        },
        'Knowledge & Encyclopedia': {
            'icon': 'bi-wikipedia',
            'color': 'secondary',
            'description': 'Search and retrieve information from Wikipedia and other knowledge bases.',
            'order': 10
        },
        'Other Tools': {
            'icon': 'bi-tools',
            'color': 'secondary',
            'description': 'Additional utility tools and miscellaneous functionality.',
            'order': 99
        }
    }
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, tools_dir: str = None, refresh_interval: int = 300):
        """
        Initialize the Tool Groups Manager
        
        Args:
            tools_dir: Path to tools config directory
            refresh_interval: Refresh interval in seconds (default 5 minutes)
        """
        # Only initialize once (singleton)
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self._initialized = True
        self.tools_dir = Path(tools_dir) if tools_dir else Path(__file__).parent.parent / 'config' / 'tools'
        self.refresh_interval = refresh_interval
        
        self._groups: Dict[str, Dict] = {}
        self._tools_by_group: Dict[str, List[Dict]] = {}
        self._last_refresh: Optional[datetime] = None
        self._refresh_lock = threading.Lock()
        self._stop_refresh = threading.Event()
        self._refresh_thread: Optional[threading.Thread] = None
        
        # Initial load
        self.refresh()
        
        # Start background refresh thread
        self._start_refresh_thread()
    
    def _start_refresh_thread(self):
        """Start the background refresh thread"""
        self._refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._refresh_thread.start()
        logger.info(f"Tool groups refresh thread started (interval: {self.refresh_interval}s)")
    
    def _refresh_loop(self):
        """Background refresh loop"""
        while not self._stop_refresh.is_set():
            time.sleep(self.refresh_interval)
            if not self._stop_refresh.is_set():
                try:
                    self.refresh()
                except Exception as e:
                    logger.error(f"Error refreshing tool groups: {e}")
    
    def stop(self):
        """Stop the background refresh thread"""
        self._stop_refresh.set()
        if self._refresh_thread:
            self._refresh_thread.join(timeout=5)
    
    def refresh(self):
        """Scan tools directory and rebuild groups"""
        with self._refresh_lock:
            start_time = time.time()
            
            groups = {}
            tools_by_group = {}
            
            if not self.tools_dir.exists():
                logger.warning(f"Tools directory not found: {self.tools_dir}")
                return
            
            # Scan all JSON files
            json_files = list(self.tools_dir.glob('*.json'))
            
            for json_file in json_files:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        tool_config = json.load(f)
                    
                    # Extract tool info
                    tool_name = tool_config.get('name', json_file.stem)
                    description = tool_config.get('description', '')
                    enabled = tool_config.get('enabled', True)
                    metadata = tool_config.get('metadata', {})
                    raw_category = metadata.get('category', 'Unknown')
                    tags = metadata.get('tags', [])
                    
                    # Map to display group
                    display_group = self.CATEGORY_MAPPINGS.get(raw_category, 'Other Tools')
                    
                    # Initialize group if needed
                    if display_group not in groups:
                        group_meta = self.GROUP_METADATA.get(display_group, self.GROUP_METADATA['Other Tools'])
                        groups[display_group] = {
                            'name': display_group,
                            'icon': group_meta['icon'],
                            'color': group_meta['color'],
                            'description': group_meta['description'],
                            'order': group_meta['order'],
                            'tool_count': 0,
                            'enabled_count': 0,
                            'categories': set()
                        }
                        tools_by_group[display_group] = []
                    
                    # Add tool to group
                    tool_info = {
                        'name': tool_name,
                        'description': description[:200] + '...' if len(description) > 200 else description,
                        'full_description': description,
                        'enabled': enabled,
                        'category': raw_category,
                        'tags': tags,
                        'filename': json_file.name
                    }
                    
                    tools_by_group[display_group].append(tool_info)
                    groups[display_group]['tool_count'] += 1
                    groups[display_group]['categories'].add(raw_category)
                    if enabled:
                        groups[display_group]['enabled_count'] += 1
                        
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON in {json_file}: {e}")
                except Exception as e:
                    logger.warning(f"Error processing {json_file}: {e}")
            
            # Convert sets to lists for JSON serialization
            for group in groups.values():
                group['categories'] = sorted(list(group['categories']))
            
            # Sort tools within each group
            for group_name in tools_by_group:
                tools_by_group[group_name].sort(key=lambda x: x['name'])
            
            # Update instance variables
            self._groups = groups
            self._tools_by_group = tools_by_group
            self._last_refresh = datetime.now()
            
            elapsed = time.time() - start_time
            total_tools = sum(g['tool_count'] for g in groups.values())
            logger.info(f"Tool groups refreshed: {len(groups)} groups, {total_tools} tools in {elapsed:.2f}s")
    
    def get_groups(self) -> List[Dict]:
        """
        Get all tool groups sorted by order
        
        Returns:
            List of group dictionaries
        """
        return sorted(self._groups.values(), key=lambda x: x['order'])
    
    def get_group(self, group_name: str) -> Optional[Dict]:
        """
        Get a specific group by name
        
        Args:
            group_name: Name of the group
            
        Returns:
            Group dictionary or None
        """
        return self._groups.get(group_name)
    
    def get_tools_in_group(self, group_name: str) -> List[Dict]:
        """
        Get all tools in a specific group
        
        Args:
            group_name: Name of the group
            
        Returns:
            List of tool dictionaries
        """
        return self._tools_by_group.get(group_name, [])
    
    def get_all_tools(self) -> List[Dict]:
        """
        Get all tools across all groups
        
        Returns:
            List of all tool dictionaries
        """
        all_tools = []
        for tools in self._tools_by_group.values():
            all_tools.extend(tools)
        return sorted(all_tools, key=lambda x: x['name'])
    
    def search_tools(self, query: str) -> List[Dict]:
        """
        Search tools by name, description, or tags
        
        Args:
            query: Search query
            
        Returns:
            List of matching tool dictionaries with group info
        """
        query = query.lower()
        results = []
        
        for group_name, tools in self._tools_by_group.items():
            group = self._groups.get(group_name, {})
            for tool in tools:
                if (query in tool['name'].lower() or 
                    query in tool['full_description'].lower() or
                    any(query in tag.lower() for tag in tool.get('tags', []))):
                    results.append({
                        **tool,
                        'group': group_name,
                        'group_icon': group.get('icon', 'bi-tools'),
                        'group_color': group.get('color', 'secondary')
                    })
        
        return results
    
    def get_stats(self) -> Dict:
        """
        Get statistics about tool groups
        
        Returns:
            Dictionary with statistics
        """
        total_tools = sum(g['tool_count'] for g in self._groups.values())
        enabled_tools = sum(g['enabled_count'] for g in self._groups.values())
        
        return {
            'total_groups': len(self._groups),
            'total_tools': total_tools,
            'enabled_tools': enabled_tools,
            'disabled_tools': total_tools - enabled_tools,
            'last_refresh': self._last_refresh.isoformat() if self._last_refresh else None,
            'refresh_interval': self.refresh_interval
        }
    
    def to_dict(self) -> Dict:
        """
        Export all data as dictionary (for API responses)
        
        Returns:
            Dictionary with all groups and tools
        """
        return {
            'groups': self.get_groups(),
            'tools_by_group': {k: v for k, v in self._tools_by_group.items()},
            'stats': self.get_stats()
        }


# Singleton instance
_tool_groups_manager: Optional[ToolGroupsManager] = None


def get_tool_groups_manager(tools_dir: str = None, refresh_interval: int = 300) -> ToolGroupsManager:
    """
    Get the singleton ToolGroupsManager instance
    
    Args:
        tools_dir: Path to tools config directory (only used on first call)
        refresh_interval: Refresh interval in seconds (only used on first call)
        
    Returns:
        ToolGroupsManager instance
    """
    global _tool_groups_manager
    if _tool_groups_manager is None:
        _tool_groups_manager = ToolGroupsManager(tools_dir, refresh_interval)
    return _tool_groups_manager
