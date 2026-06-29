"""
SAJHA MCP Server v5.3.0 — File-Based Tool Output Cache
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

File-based cache with configurable TTL per tool. Each cache entry is a
JSON file on disk under data/cache/{tool_name}/{hash}.json. This prevents
memory bloat regardless of how many tools or results are cached.

Default: NO caching. Each tool opts in via "cache_ttl" in its JSON config.
Example: {"name": "fred_gdp", "cache_ttl": 3600, ...}

Suggested TTLs (for reference):
  Calculators/OLAP: 0 (deterministic, no external call)
  FRED/ECB/World Bank: 3600 (hourly)
  FMP/OpenBB/Alpha Vantage: 300 (5 min)
  Yahoo Finance: 30 (near real-time)
  CoinGecko: 60
  Search/Web crawl: 600 (10 min)

Cache structure on disk:
  data/cache/
    fred_gdp/
      a1b2c3d4e5f6.json    ← {"value": {...}, "expires_at": 1716003600}
      f7e8d9c0b1a2.json
    yahoo_quote/
      ...
"""
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _cache_key(tool_name: str, arguments: Dict) -> str:
    """Generate a deterministic hash from arguments."""
    args_str = json.dumps(arguments, sort_keys=True, default=str)
    return hashlib.md5(args_str.encode()).hexdigest()


def get_tool_ttl(tool_name: str, tool_config: dict = None) -> int:
    """
    Get cache TTL for a tool from its JSON config.
    Default: 0 (no caching). Tool opts in via "cache_ttl" field.
    """
    if tool_config and isinstance(tool_config, dict):
        ttl = tool_config.get('cache_ttl', 0)
        if isinstance(ttl, (int, float)) and ttl > 0:
            return int(ttl)
    return 0


class ToolCache:
    """
    File-based cache with per-tool TTL.

    All settings driven by config/application.yml:
      cache.enabled: true/false (master switch)
      cache.dir: data/cache (file location)
      cache.max_files: 50000 (eviction threshold)
      cache.max_file_size_kb: 512 (skip large results)
      cache.cleanup_interval_seconds: 300

    Per-tool TTL set in tool JSON config: "cache_ttl": 3600

    Structure: {cache_dir}/{tool_name}/{md5_hash}.json
    """

    def __init__(self, cache_dir: str = 'data/cache', max_files: int = 50000,
                 max_file_size_kb: int = 512, enabled: bool = True):
        self._cache_dir = Path(cache_dir)
        self._max_files = max_files
        self._max_file_size_bytes = max_file_size_kb * 1024
        self._enabled = enabled
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._writes = 0
        self._skipped_oversize = 0
        if self._enabled:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"File cache: {self._cache_dir} (max {max_files} files, max {max_file_size_kb} KB/file)")
        else:
            logger.info("File cache: DISABLED by config")

    def _file_path(self, tool_name: str, args_hash: str) -> Path:
        """Get the file path for a cache entry."""
        tool_dir = self._cache_dir / tool_name.replace('/', '_')
        return tool_dir / f"{args_hash}.json"

    def get(self, tool_name: str, arguments: Dict) -> Optional[Any]:
        """Get cached result from disk. Returns None on miss or expiry."""
        if not self._enabled:
            return None
        args_hash = _cache_key(tool_name, arguments)
        path = self._file_path(tool_name, args_hash)

        if not path.exists():
            self._misses += 1
            return None

        try:
            with self._lock:
                data = json.loads(path.read_text())
                if time.time() > data.get('expires_at', 0):
                    # Expired — delete file
                    path.unlink(missing_ok=True)
                    self._misses += 1
                    return None
                self._hits += 1
                return data.get('value')
        except Exception as e:
            logger.debug(f"Cache read error for {tool_name}: {e}", exc_info=True)
            self._misses += 1
            return None

    def put(self, tool_name: str, arguments: Dict, value: Any, ttl: int = None):
        """Write a result to disk cache. If ttl=0 or cache disabled, skip."""
        if not self._enabled:
            return
        if ttl is None:
            ttl = get_tool_ttl(tool_name)
        if ttl <= 0:
            return

        # Check result size before writing
        try:
            serialized = json.dumps(value, default=str)
            if len(serialized) > self._max_file_size_bytes:
                self._skipped_oversize += 1
                logger.debug(f"Cache skip: {tool_name} result too large ({len(serialized)} bytes > {self._max_file_size_bytes})")
                return
        except Exception:
            return

        args_hash = _cache_key(tool_name, arguments)
        path = self._file_path(tool_name, args_hash)

        try:
            with self._lock:
                # Create tool subdirectory
                path.parent.mkdir(parents=True, exist_ok=True)

                now = time.time()
                entry = {
                    'value': value,
                    'expires_at': now + ttl,
                    'created_at': now,
                    'tool_name': tool_name,
                    'ttl': ttl,
                }
                path.write_text(json.dumps(entry, default=str))
                self._writes += 1

                # Check total file count (lazy — every 100 writes)
                if self._writes % 100 == 0:
                    self._enforce_max_files()

        except Exception as e:
            logger.warning(f"Cache write error for {tool_name}: {e}", exc_info=True)

    def invalidate(self, tool_name: str = None):
        """Delete cache entries. If tool_name given, only that tool's directory."""
        import shutil
        with self._lock:
            if tool_name is None:
                # Clear entire cache
                if self._cache_dir.exists():
                    for child in self._cache_dir.iterdir():
                        if child.is_dir():
                            shutil.rmtree(child, ignore_errors=True)
                    logger.info("Cache invalidated: all entries removed")
            else:
                tool_dir = self._cache_dir / tool_name.replace('/', '_')
                if tool_dir.exists():
                    shutil.rmtree(tool_dir, ignore_errors=True)
                    logger.info(f"Cache invalidated: {tool_name}")

    def stats(self) -> Dict:
        """Cache statistics."""
        total_files = 0
        total_bytes = 0
        tools_cached = 0
        try:
            for tool_dir in self._cache_dir.iterdir():
                if tool_dir.is_dir():
                    files = list(tool_dir.glob('*.json'))
                    if files:
                        tools_cached += 1
                        total_files += len(files)
                        total_bytes += sum(f.stat().st_size for f in files)
        except Exception as e:
            logger.debug(f"Cache stats error: {e}", exc_info=True)

        total_requests = self._hits + self._misses
        return {
            'type': 'file',
            'cache_dir': str(self._cache_dir),
            'size': total_files,
            'size_bytes': total_bytes,
            'size_human': _fmt_bytes(total_bytes),
            'max_files': self._max_files,
            'tools_cached': tools_cached,
            'hits': self._hits,
            'misses': self._misses,
            'writes': self._writes,
            'hit_rate': round(self._hits / max(total_requests, 1) * 100, 1),
            'skipped_oversize': self._skipped_oversize,
            'enabled': self._enabled,
            'max_file_size_kb': self._max_file_size_bytes // 1024,
        }

    def cleanup_expired(self):
        """Remove all expired cache files."""
        now = time.time()
        removed = 0
        try:
            for tool_dir in self._cache_dir.iterdir():
                if not tool_dir.is_dir():
                    continue
                for cache_file in tool_dir.glob('*.json'):
                    try:
                        data = json.loads(cache_file.read_text())
                        if now > data.get('expires_at', 0):
                            cache_file.unlink()
                            removed += 1
                    except Exception:
                        # Corrupted file — remove it
                        cache_file.unlink(missing_ok=True)
                        removed += 1
                # Remove empty tool directories
                if not any(tool_dir.iterdir()):
                    tool_dir.rmdir()
        except Exception as e:
            logger.warning(f"Cache cleanup error: {e}", exc_info=True)
        if removed:
            logger.info(f"Cache cleanup: removed {removed} expired/corrupt files")

    def _enforce_max_files(self):
        """Evict oldest files if total count exceeds max."""
        all_files = []
        try:
            for tool_dir in self._cache_dir.iterdir():
                if tool_dir.is_dir():
                    for f in tool_dir.glob('*.json'):
                        all_files.append((f.stat().st_mtime, f))
        except Exception:
            return

        if len(all_files) <= self._max_files:
            return

        # Sort by modification time, delete oldest
        all_files.sort()
        to_remove = len(all_files) - self._max_files
        for _, path in all_files[:to_remove]:
            try:
                path.unlink()
            except Exception:
                pass
        logger.info(f"Cache eviction: removed {to_remove} oldest files (limit: {self._max_files})")


def _fmt_bytes(b: int) -> str:
    if b >= 1073741824: return f"{b/1073741824:.1f} GB"
    if b >= 1048576: return f"{b/1048576:.1f} MB"
    if b >= 1024: return f"{b/1024:.1f} KB"
    return f"{b} B"


# Module-level singleton
_tool_cache: Optional[ToolCache] = None


def get_tool_cache() -> ToolCache:
    global _tool_cache
    if _tool_cache is None:
        # Read all cache settings from config/application.yml
        cache_dir = 'data/cache'
        max_files = 50000
        max_file_size_kb = 512
        enabled = True
        try:
            from sajha.core.config import get_settings
            s = get_settings()
            cache_dir = s.cache_dir
            max_files = s.cache_max_files
            max_file_size_kb = s.cache_max_file_size_kb
            enabled = s.cache_enabled
        except Exception:
            pass
        _tool_cache = ToolCache(
            cache_dir=cache_dir,
            max_files=max_files,
            max_file_size_kb=max_file_size_kb,
            enabled=enabled,
        )
    return _tool_cache
