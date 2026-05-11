"""
SAJHA MCP Server v4.0.0 — Plugin System
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Standardized plugin format for tool packs.
Install, validate, and deploy from a registry.

Plugin structure (directory):
    bloomberg-tools/
        plugin.json         # manifest: name, version, author, dependencies, tools
        tools/
            bloomberg_quote.json
            bloomberg_news.json
        requirements.txt    # Python dependencies (optional)
        README.md

Plugin manifest (plugin.json):
    {
        "name": "bloomberg-tools",
        "version": "1.0.0",
        "author": "Trading Desk",
        "description": "Bloomberg Terminal API tools",
        "min_sajha_version": "4.0.0",
        "dependencies": ["requests>=2.28"],
        "tools": ["bloomberg_quote", "bloomberg_news", "bloomberg_portfolio"],
        "config_keys": ["BLOOMBERG_API_KEY"],
        "checksum": "sha256:abc123..."
    }
"""

import os
import json
import shutil
import hashlib
import logging
import importlib
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class PluginManifest:
    """Parsed plugin.json."""
    name: str
    version: str
    author: str = ''
    description: str = ''
    min_sajha_version: str = '4.0.0'
    dependencies: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    config_keys: List[str] = field(default_factory=list)
    checksum: str = ''
    path: str = ''     # directory path after install

    def to_dict(self) -> Dict:
        return {
            'name': self.name, 'version': self.version, 'author': self.author,
            'description': self.description, 'min_sajha_version': self.min_sajha_version,
            'dependencies': self.dependencies, 'tools': self.tools,
            'config_keys': self.config_keys, 'path': self.path,
        }


@dataclass
class PluginStatus:
    name: str
    version: str
    installed: bool = False
    enabled: bool = False
    tools_registered: int = 0
    installed_at: Optional[str] = None
    error: str = ''

    def to_dict(self):
        return self.__dict__


class PluginManager:
    """
    Discovers, validates, installs, and loads tool plugins.

    Plugins directory: config/plugins/
    Each subdirectory with a plugin.json is a plugin.
    """

    PLUGINS_DIR = 'config/plugins'

    def __init__(self, tools_registry, storage_backend=None):
        self._registry = tools_registry
        self._storage = storage_backend
        self._plugins: Dict[str, PluginManifest] = {}
        self._status: Dict[str, PluginStatus] = {}

    def discover(self) -> List[PluginManifest]:
        """Scan plugins directory for installed plugins."""
        plugins = []
        plugins_dir = self.PLUGINS_DIR
        if not os.path.isdir(plugins_dir):
            os.makedirs(plugins_dir, exist_ok=True)
            return plugins

        for entry in os.listdir(plugins_dir):
            plugin_dir = os.path.join(plugins_dir, entry)
            manifest_path = os.path.join(plugin_dir, 'plugin.json')
            if os.path.isdir(plugin_dir) and os.path.isfile(manifest_path):
                try:
                    with open(manifest_path, 'r') as f:
                        data = json.load(f)
                    manifest = PluginManifest(
                        name=data['name'], version=data.get('version', '0.0.0'),
                        author=data.get('author', ''), description=data.get('description', ''),
                        min_sajha_version=data.get('min_sajha_version', '4.0.0'),
                        dependencies=data.get('dependencies', []),
                        tools=data.get('tools', []),
                        config_keys=data.get('config_keys', []),
                        checksum=data.get('checksum', ''),
                        path=plugin_dir,
                    )
                    plugins.append(manifest)
                    self._plugins[manifest.name] = manifest
                except Exception as e:
                    logger.warning(f"Failed to load plugin manifest {manifest_path}: {e}")
        return plugins

    def validate(self, manifest: PluginManifest) -> tuple:
        """Validate a plugin before loading. Returns (valid, errors)."""
        errors = []

        # Version check
        from sajha.app import VERSION
        if manifest.min_sajha_version > VERSION:
            errors.append(f"Requires SAJHA >= {manifest.min_sajha_version} (current: {VERSION})")

        # Check tools directory exists
        tools_dir = os.path.join(manifest.path, 'tools')
        if not os.path.isdir(tools_dir):
            errors.append(f"Missing tools/ directory in {manifest.path}")

        # Check config keys are set
        for key in manifest.config_keys:
            if not os.environ.get(key):
                errors.append(f"Required config key not set: {key}")

        # Checksum verification
        if manifest.checksum:
            actual = self._compute_checksum(manifest.path)
            if manifest.checksum != f"sha256:{actual}":
                errors.append(f"Checksum mismatch: expected {manifest.checksum}")

        return len(errors) == 0, errors

    def load_plugin(self, name: str) -> PluginStatus:
        """Load and register all tools from a plugin."""
        manifest = self._plugins.get(name)
        if not manifest:
            return PluginStatus(name=name, version='', error='Plugin not found')

        valid, errors = self.validate(manifest)
        if not valid:
            status = PluginStatus(name=name, version=manifest.version,
                                   installed=True, error='; '.join(errors))
            self._status[name] = status
            return status

        # Install Python dependencies if requirements.txt exists
        req_file = os.path.join(manifest.path, 'requirements.txt')
        if os.path.isfile(req_file):
            try:
                import subprocess
                subprocess.check_call([
                    'pip', 'install', '-r', req_file,
                    '--break-system-packages', '--quiet'])
            except Exception as e:
                logger.warning(f"Failed to install plugin deps: {e}")

        # Load tool JSON configs
        tools_dir = os.path.join(manifest.path, 'tools')
        tools_loaded = 0
        for fname in os.listdir(tools_dir):
            if fname.endswith('.json'):
                try:
                    fpath = os.path.join(tools_dir, fname)
                    with open(fpath, 'r') as f:
                        tool_config = json.load(f)
                    tool_name = tool_config.get('name', fname.replace('.json', ''))
                    self._registry.load_tool_from_config(tool_name, tool_config)
                    tools_loaded += 1
                except Exception as e:
                    logger.warning(f"Failed to load plugin tool {fname}: {e}")

            elif fname.endswith('.py') and fname != '__init__.py':
                try:
                    fpath = os.path.join(tools_dir, fname)
                    spec = importlib.util.spec_from_file_location(fname[:-3], fpath)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    # Look for classes that extend BaseMCPTool
                    for attr_name in dir(mod):
                        attr = getattr(mod, attr_name)
                        if (isinstance(attr, type) and
                            hasattr(attr, 'execute') and
                            attr_name != 'BaseMCPTool'):
                            instance = attr({})
                            self._registry.register_tool(attr_name.lower(), instance)
                            tools_loaded += 1
                except Exception as e:
                    logger.warning(f"Failed to load plugin Python tool {fname}: {e}")

        status = PluginStatus(
            name=name, version=manifest.version, installed=True,
            enabled=True, tools_registered=tools_loaded,
            installed_at=datetime.utcnow().isoformat())
        self._status[name] = status
        logger.info(f"Plugin loaded: {name} v{manifest.version} ({tools_loaded} tools)")
        return status

    def load_all(self) -> int:
        """Discover and load all plugins."""
        manifests = self.discover()
        count = 0
        for m in manifests:
            status = self.load_plugin(m.name)
            if status.enabled:
                count += 1
        return count

    def unload_plugin(self, name: str) -> bool:
        manifest = self._plugins.get(name)
        if not manifest:
            return False
        for tool_name in manifest.tools:
            try:
                self._registry.unregister_tool(tool_name)
            except:
                pass
        self._status[name] = PluginStatus(
            name=name, version=manifest.version, installed=True, enabled=False)
        return True

    def get_status(self, name: str = '') -> any:
        if name:
            return self._status.get(name, PluginStatus(name=name, version='')).to_dict()
        return [s.to_dict() for s in self._status.values()]

    def list_plugins(self) -> List[Dict]:
        return [m.to_dict() for m in self._plugins.values()]

    def _compute_checksum(self, path: str) -> str:
        h = hashlib.sha256()
        for root, dirs, files in os.walk(path):
            for fname in sorted(files):
                if fname == 'plugin.json':
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath, 'rb') as f:
                    h.update(f.read())
        return h.hexdigest()


# ── Singleton ────────────────────────────────────────────────

_plugin_manager: Optional[PluginManager] = None

def init_plugin_manager(tools_registry) -> PluginManager:
    global _plugin_manager
    _plugin_manager = PluginManager(tools_registry)
    return _plugin_manager

def get_plugin_manager() -> Optional[PluginManager]:
    return _plugin_manager
