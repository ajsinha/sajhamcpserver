"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Patent Pending - Abhikarta LLM Platform
Prompts Registry for SAJHA MCP Server - Singleton with Auto-Refresh
"""

import json
import logging
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any


class Prompt:
    """Class representing a single prompt"""
    
    def __init__(self, name: str, config: Dict[str, Any]):
        """
        Initialize prompt
        
        Args:
            name: Prompt name
            config: Prompt configuration dictionary
        """
        self.name = name
        self.description = config.get('description', '')
        self.template = config.get('prompt_template', '')
        self.arguments = config.get('arguments', [])
        self.metadata = config.get('metadata', {})
        self.category = self.metadata.get('category', 'general')
        self.tags = self.metadata.get('tags', [])
        self.author = self.metadata.get('author', 'system')
        self.version = self.metadata.get('version', '1.0')
        self.created_at = self.metadata.get('created_at', datetime.now().isoformat())
        self.updated_at = self.metadata.get('updated_at', datetime.now().isoformat())
        
        # Usage tracking
        self.usage_count = 0
        self.last_used = None
    
    def render(self, arguments: Dict[str, Any]) -> str:
        """
        Render prompt template with provided arguments
        
        Args:
            arguments: Dictionary of argument values
            
        Returns:
            Rendered prompt string
        """
        rendered = self.template
        
        # Simple variable substitution using {variable_name} format
        for arg_name, arg_value in arguments.items():
            placeholder = f"{{{arg_name}}}"
            rendered = rendered.replace(placeholder, str(arg_value))
        
        # Track usage
        self.usage_count += 1
        self.last_used = datetime.now().isoformat()
        
        return rendered
    
    def validate_arguments(self, arguments: Dict[str, Any]) -> tuple:
        """
        Validate provided arguments against prompt requirements
        
        Args:
            arguments: Dictionary of argument values
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check required arguments
        for arg in self.arguments:
            if arg.get('required', False):
                if arg['name'] not in arguments or arguments[arg['name']] is None:
                    return False, f"Required argument '{arg['name']}' is missing"
        
        return True, None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert prompt to dictionary format"""
        return {
            'name': self.name,
            'description': self.description,
            'template': self.template,
            'arguments': self.arguments,
            'metadata': {
                'category': self.category,
                'tags': self.tags,
                'author': self.author,
                'version': self.version,
                'created_at': self.created_at,
                'updated_at': self.updated_at,
                'usage_count': self.usage_count,
                'last_used': self.last_used
            }
        }
    
    def to_mcp_format(self) -> Dict[str, Any]:
        """Convert prompt to MCP protocol format"""
        return {
            'name': self.name,
            'description': self.description,
            'arguments': [
                {
                    'name': arg['name'],
                    'description': arg.get('description', ''),
                    'required': arg.get('required', False)
                }
                for arg in self.arguments
            ]
        }


class PromptsRegistry:
    """
    Registry for managing prompts - Singleton with Auto-Refresh
    
    This class implements a singleton pattern and automatically refreshes
    prompts from the configuration directory every 10 minutes.
    """
    
    _instance = None
    _lock = threading.RLock()
    _initialized = False
    
    def __new__(cls, prompts_config_dir: str = "config/prompts"):
        """
        Create or return the singleton instance
        
        Args:
            prompts_config_dir: Directory containing prompt configuration files
            
        Returns:
            The singleton instance of PromptsRegistry
        """
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking pattern
                if cls._instance is None:
                    cls._instance = super(PromptsRegistry, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, prompts_config_dir: str = "config/prompts"):
        """
        Initialize prompts registry (only once due to singleton)
        
        Args:
            prompts_config_dir: Directory containing prompt configuration files
        """
        # Only initialize once
        if PromptsRegistry._initialized:
            return
            
        with PromptsRegistry._lock:
            if PromptsRegistry._initialized:
                return
                
            self.prompts_config_dir = Path(prompts_config_dir)
            self.prompts: Dict[str, Prompt] = {}
            self.prompt_errors: List[Dict[str, str]] = []
            
            # Statistics
            self.total_renders = 0
            self.render_errors = 0
            
            # Auto-refresh configuration
            self.auto_refresh_enabled = True
            self.refresh_interval = 600  # 10 minutes in seconds
            self.refresh_thread = None
            self.stop_refresh_event = threading.Event()
            
            # Ensure config directory exists
            self.prompts_config_dir.mkdir(parents=True, exist_ok=True)
            
            # Load all prompts (use internal method to avoid deadlock)
            self._load_all_prompts_internal()
            
            PromptsRegistry._initialized = True
            
            logging.info(f"PromptsRegistry singleton initialized with {len(self.prompts)} prompts")
            logging.info(f"Auto-refresh enabled: every {self.refresh_interval} seconds")
        
        # Start auto-refresh thread AFTER releasing the lock
        if PromptsRegistry._initialized and self.auto_refresh_enabled:
            self.start_auto_refresh()
    
    @classmethod
    def get_instance(cls, prompts_config_dir: str = "config/prompts"):
        """
        Get the singleton instance of PromptsRegistry
        
        Args:
            prompts_config_dir: Directory containing prompt configuration files
            
        Returns:
            The singleton instance
        """
        if cls._instance is None:
            cls(prompts_config_dir)
        return cls._instance
    
    @classmethod
    def reset_instance(cls):
        """
        Reset the singleton instance (mainly for testing)
        
        Warning: This will stop the auto-refresh thread
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance.stop_auto_refresh()
            cls._instance = None
            cls._initialized = False
            logging.info("PromptsRegistry instance reset")
    
    def start_auto_refresh(self):
        """Start the auto-refresh background thread"""
        if self.refresh_thread is not None and self.refresh_thread.is_alive():
            logging.warning("Auto-refresh thread already running")
            return
        
        self.stop_refresh_event.clear()
        self.refresh_thread = threading.Thread(
            target=self._auto_refresh_worker,
            daemon=True,
            name="PromptsRegistryAutoRefresh"
        )
        self.refresh_thread.start()
        logging.info("Auto-refresh thread started")
    
    def stop_auto_refresh(self):
        """Stop the auto-refresh background thread"""
        if self.refresh_thread is None or not self.refresh_thread.is_alive():
            logging.warning("Auto-refresh thread not running")
            return
        
        logging.info("Stopping auto-refresh thread...")
        self.stop_refresh_event.set()
        self.refresh_thread.join(timeout=5)
        
        if self.refresh_thread.is_alive():
            logging.warning("Auto-refresh thread did not stop cleanly")
        else:
            logging.info("Auto-refresh thread stopped")
    
    def _auto_refresh_worker(self):
        """
        Background worker that refreshes prompts periodically
        
        This method runs in a separate thread and reloads prompts
        every refresh_interval seconds.
        """
        logging.info(f"Auto-refresh worker started (interval: {self.refresh_interval}s)")
        
        while not self.stop_refresh_event.is_set():
            # Wait for the refresh interval or until stop is signaled
            if self.stop_refresh_event.wait(timeout=self.refresh_interval):
                # Stop was signaled
                break
            
            # Perform refresh
            try:
                logging.info("Auto-refresh: Reloading prompts...")
                previous_count = len(self.prompts)
                
                self.load_all_prompts()
                
                current_count = len(self.prompts)
                if current_count != previous_count:
                    logging.info(
                        f"Auto-refresh: Prompt count changed from {previous_count} to {current_count}"
                    )
                else:
                    logging.info(f"Auto-refresh: Reloaded {current_count} prompts successfully")
                    
            except Exception as e:
                logging.error(f"Auto-refresh: Error reloading prompts: {str(e)}")
        
        logging.info("Auto-refresh worker stopped")
    
    def refresh_now(self):
        """
        Manually trigger an immediate refresh of prompts
        
        This is a thread-safe operation that can be called at any time.
        """
        logging.info("Manual refresh triggered")
        self.load_all_prompts()
    
    def set_refresh_interval(self, seconds: int):
        """
        Change the auto-refresh interval
        
        Args:
            seconds: New refresh interval in seconds
            
        Note: The new interval will take effect after the current interval completes
        """
        if seconds < 60:
            logging.warning(f"Refresh interval {seconds}s is too short, setting to 60s minimum")
            seconds = 60
        
        old_interval = self.refresh_interval
        self.refresh_interval = seconds
        logging.info(f"Refresh interval changed from {old_interval}s to {seconds}s")
    
    def disable_auto_refresh(self):
        """Disable auto-refresh (stops the thread)"""
        self.auto_refresh_enabled = False
        self.stop_auto_refresh()
        logging.info("Auto-refresh disabled")
    
    def enable_auto_refresh(self):
        """Enable auto-refresh (starts the thread if not running)"""
        self.auto_refresh_enabled = True
        if self.refresh_thread is None or not self.refresh_thread.is_alive():
            self.start_auto_refresh()
        logging.info("Auto-refresh enabled")
    
    def load_all_prompts(self):
        """
        Load all prompts from configuration directory (thread-safe)
        
        This method is called both during initialization and periodically
        by the auto-refresh thread. It uses locking to ensure thread safety.
        """
        with PromptsRegistry._lock:
            self._load_all_prompts_internal()
    
    def reload(self):
        """
        Reload all prompts from configuration directory.
        Alias for load_all_prompts() for consistency with other managers.
        """
        logging.info("Reloading all prompts...")
        self.load_all_prompts()
        logging.info(f"Prompts reload complete. Loaded {len(self.prompts)} prompts.")
    
    def _load_all_prompts_internal(self):
        """
        Internal method to load prompts without locking.
        Used during initialization to avoid deadlock.
        """
        if not self.prompts_config_dir.exists():
            logging.warning(f"Prompts config directory not found: {self.prompts_config_dir}")
            return
        
        # Create temporary storage for new prompts
        new_prompts: Dict[str, Prompt] = {}
        new_errors: List[Dict[str, str]] = []
        
        # Load all JSON files
        for config_file in self.prompts_config_dir.glob("*.json"):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                prompt_name = config.get('name', config_file.stem)
                
                # Validate required fields
                if 'prompt_template' not in config:
                    raise ValueError("Missing 'prompt_template' field")
                
                # Create prompt instance
                prompt = Prompt(prompt_name, config)
                new_prompts[prompt_name] = prompt
                
                logging.debug(f"Loaded prompt: {prompt_name}")
                
            except Exception as e:
                error_msg = f"Error loading prompt from {config_file.name}: {str(e)}"
                logging.error(error_msg)
                new_errors.append({
                    'file': config_file.name,
                    'error': str(e)
                })
        
        # Atomically replace the prompts and errors
        self.prompts = new_prompts
        self.prompt_errors = new_errors
        
        logging.info(f"Loaded {len(self.prompts)} prompts, {len(self.prompt_errors)} errors")
    
    def get_prompt(self, name: str) -> Optional[Prompt]:
        """
        Get prompt by name
        
        Args:
            name: Prompt name
            
        Returns:
            Prompt instance or None if not found
        """
        return self.prompts.get(name)
    
    def get_all_prompts(self) -> List[Dict[str, Any]]:
        """
        Get all prompts in simplified format
        
        Returns:
            List of prompt dictionaries
        """
        return [
            {
                'name': prompt.name,
                'description': prompt.description,
                'category': prompt.category,
                'tags': prompt.tags,
                'author': prompt.author,
                'version': prompt.version,
                'argument_count': len(prompt.arguments),
                'usage_count': prompt.usage_count,
                'last_used': prompt.last_used
            }
            for prompt in self.prompts.values()
        ]
    
    def get_prompts_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get all prompts in a specific category"""
        return [
            p for p in self.get_all_prompts()
            if p['category'] == category
        ]
    
    def get_prompts_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        """Get all prompts with a specific tag"""
        return [
            p for p in self.get_all_prompts()
            if tag in p['tags']
        ]
    
    def get_categories(self) -> List[str]:
        """Get list of all unique categories"""
        categories = set(prompt.category for prompt in self.prompts.values())
        return sorted(list(categories))
    
    def get_tags(self) -> List[str]:
        """Get list of all unique tags"""
        tags = set()
        for prompt in self.prompts.values():
            tags.update(prompt.tags)
        return sorted(list(tags))
    
    def render_prompt(self, name: str, arguments: Dict[str, Any]) -> tuple:
        """
        Render a prompt with provided arguments
        
        Args:
            name: Prompt name
            arguments: Dictionary of argument values
            
        Returns:
            Tuple of (success, rendered_prompt_or_error_message)
        """
        prompt = self.get_prompt(name)
        if not prompt:
            self.render_errors += 1
            return False, f"Prompt '{name}' not found"
        
        # Validate arguments
        is_valid, error_msg = prompt.validate_arguments(arguments)
        if not is_valid:
            self.render_errors += 1
            return False, error_msg
        
        try:
            rendered = prompt.render(arguments)
            self.total_renders += 1
            return True, rendered
        except Exception as e:
            self.render_errors += 1
            error_msg = f"Error rendering prompt: {str(e)}"
            logging.error(error_msg)
            return False, error_msg
    
    def create_prompt(self, name: str, config: Dict[str, Any]) -> tuple:
        """
        Create a new prompt
        
        Args:
            name: Prompt name
            config: Prompt configuration
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Check if prompt already exists
            if name in self.prompts:
                return False, f"Prompt '{name}' already exists"
            
            # Validate required fields
            if 'prompt_template' not in config:
                return False, "Missing 'prompt_template' field"
            
            # Add metadata if not present
            if 'metadata' not in config:
                config['metadata'] = {}
            
            config['metadata']['created_at'] = datetime.now().isoformat()
            config['metadata']['updated_at'] = datetime.now().isoformat()
            
            # Create prompt instance
            prompt = Prompt(name, config)
            self.prompts[name] = prompt
            
            # Save to file
            config['name'] = name
            config_file = self.prompts_config_dir / f"{name}.json"
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            
            logging.info(f"Created prompt: {name}")
            return True, f"Prompt '{name}' created successfully"
            
        except Exception as e:
            error_msg = f"Error creating prompt: {str(e)}"
            logging.error(error_msg)
            return False, error_msg
    
    def update_prompt(self, name: str, config: Dict[str, Any]) -> tuple:
        """
        Update an existing prompt
        
        Args:
            name: Prompt name
            config: Updated prompt configuration
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Check if prompt exists
            if name not in self.prompts:
                return False, f"Prompt '{name}' not found"
            
            # Preserve existing metadata
            existing_prompt = self.prompts[name]
            if 'metadata' not in config:
                config['metadata'] = {}
            
            config['metadata']['created_at'] = existing_prompt.created_at
            config['metadata']['updated_at'] = datetime.now().isoformat()
            
            # Create updated prompt instance
            prompt = Prompt(name, config)
            self.prompts[name] = prompt
            
            # Save to file
            config['name'] = name
            config_file = self.prompts_config_dir / f"{name}.json"
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            
            logging.info(f"Updated prompt: {name}")
            return True, f"Prompt '{name}' updated successfully"
            
        except Exception as e:
            error_msg = f"Error updating prompt: {str(e)}"
            logging.error(error_msg)
            return False, error_msg
    
    def delete_prompt(self, name: str) -> tuple:
        """
        Delete a prompt
        
        Args:
            name: Prompt name
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Check if prompt exists
            if name not in self.prompts:
                return False, f"Prompt '{name}' not found"
            
            # Remove from registry
            del self.prompts[name]
            
            # Delete file
            config_file = self.prompts_config_dir / f"{name}.json"
            if config_file.exists():
                config_file.unlink()
            
            logging.info(f"Deleted prompt: {name}")
            return True, f"Prompt '{name}' deleted successfully"
            
        except Exception as e:
            error_msg = f"Error deleting prompt: {str(e)}"
            logging.error(error_msg)
            return False, error_msg
    
    def get_prompt_errors(self) -> List[Dict[str, str]]:
        """Get list of prompt loading errors"""
        return self.prompt_errors
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get registry statistics including auto-refresh status"""
        return {
            'total_prompts': len(self.prompts),
            'total_renders': self.total_renders,
            'render_errors': self.render_errors,
            'categories': len(self.get_categories()),
            'tags': len(self.get_tags()),
            'loading_errors': len(self.prompt_errors),
            'auto_refresh': {
                'enabled': self.auto_refresh_enabled,
                'interval_seconds': self.refresh_interval,
                'thread_alive': self.refresh_thread is not None and self.refresh_thread.is_alive()
            }
        }
    
    def get_refresh_status(self) -> Dict[str, Any]:
        """
        Get detailed auto-refresh status
        
        Returns:
            Dictionary with refresh configuration and status
        """
        return {
            'enabled': self.auto_refresh_enabled,
            'interval_seconds': self.refresh_interval,
            'interval_minutes': self.refresh_interval / 60,
            'thread_alive': self.refresh_thread is not None and self.refresh_thread.is_alive(),
            'thread_name': self.refresh_thread.name if self.refresh_thread else None,
            'can_manual_refresh': True
        }
    
    def search_prompts(self, query: str) -> List[Dict[str, Any]]:
        """
        Search prompts by name, description, or tags
        
        Args:
            query: Search query
            
        Returns:
            List of matching prompts
        """
        query_lower = query.lower()
        results = []
        
        for prompt in self.prompts.values():
            # Search in name
            if query_lower in prompt.name.lower():
                results.append(prompt.to_dict())
                continue
            
            # Search in description
            if query_lower in prompt.description.lower():
                results.append(prompt.to_dict())
                continue
            
            # Search in tags
            if any(query_lower in tag.lower() for tag in prompt.tags):
                results.append(prompt.to_dict())
                continue
        
        return results
