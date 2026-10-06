"""
``sajha`` CLI — profiles and stored credentials.

One JSON file, ``<config dir>/config.json``, mode 0600 in a 0700 directory::

    {"current": "default",
     "profiles": {"default": {"url": "http://localhost:3002", "user": "admin", "token": "eyJ..."},
                  "prod":    {"url": "https://sajha.example.com", "api_key": "sja_..."}}}

The config directory is ``$SAJHA_CONFIG_DIR``, else ``$XDG_CONFIG_HOME/sajha``,
else ``~/.config/sajha``.

Every setting resolves flag -> environment -> profile -> default, and
:func:`resolve` records where each value came from (``sajha config show``).
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_URL = "http://localhost:3002"
DEFAULT_PROFILE = "default"
SECRET_KEYS = ("token", "api_key")


def config_dir() -> Path:
    env = os.environ.get("SAJHA_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "sajha"


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> Dict[str, Any]:
    path = config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"current": DEFAULT_PROFILE, "profiles": {}}
    except (OSError, ValueError):
        return {"current": DEFAULT_PROFILE, "profiles": {}}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("current", DEFAULT_PROFILE)
    if not isinstance(data.get("profiles"), dict):
        data["profiles"] = {}
    return data


def save(data: Dict[str, Any]) -> Path:
    """Write atomically, owner-only (0700 directory, 0600 file)."""
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, stat.S_IRWXU)
    except OSError:
        pass
    path = config_path()
    fd, tmp = tempfile.mkstemp(prefix=".config.", suffix=".json", dir=str(directory))
    try:
        # mkstemp creates the file 0600 already
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def update_profile(name: str, **values: Any) -> Path:
    """Set (or, for ``None`` values, remove) keys of one profile."""
    data = load()
    profile = data["profiles"].setdefault(name, {})
    for k, v in values.items():
        if v is None:
            profile.pop(k, None)
        else:
            profile[k] = v
    return save(data)


def redact(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    return value[:6] + "..." if len(value) > 10 else "***"


@dataclass
class Settings:
    """The CLI's effective settings, with the source of each."""

    profile: str
    url: str
    api_key: Optional[str] = None
    token: Optional[str] = None
    user: Optional[str] = None
    timeout: int = 30
    sources: Dict[str, str] = field(default_factory=dict)

    def describe(self) -> Dict[str, Any]:
        return {
            "config_file": str(config_path()),
            "profile": self.profile,
            "url": self.url,
            "user": self.user,
            "auth": "api_key" if self.api_key else ("token" if self.token else "none"),
            "api_key": redact(self.api_key),
            "token": redact(self.token),
            "timeout": self.timeout,
            "sources": dict(self.sources),
        }


def resolve(server: Optional[str] = None, api_key: Optional[str] = None, profile: Optional[str] = None,
            timeout: Optional[int] = None) -> Settings:
    data = load()
    sources: Dict[str, str] = {}

    if profile:
        name, sources["profile"] = profile, "flag"
    elif os.environ.get("SAJHA_PROFILE"):
        name, sources["profile"] = os.environ["SAJHA_PROFILE"], "env SAJHA_PROFILE"
    else:
        name, sources["profile"] = data.get("current") or DEFAULT_PROFILE, "config file"
    stored = data["profiles"].get(name) or {}

    def pick(key: str, flag_value, env_name: Optional[str], default=None):
        if flag_value:
            sources[key] = "flag"
            return flag_value
        if env_name and os.environ.get(env_name):
            sources[key] = f"env {env_name}"
            return os.environ[env_name]
        if stored.get(key):
            sources[key] = f"profile {name}"
            return stored[key]
        sources[key] = "default"
        return default

    url = pick("url", server, "SAJHA_URL", DEFAULT_URL).rstrip("/")
    key = pick("api_key", api_key, "SAJHA_API_KEY")
    token = pick("token", None, "SAJHA_TOKEN")
    user = stored.get("user")
    t = pick("timeout", timeout, "SAJHA_TIMEOUT", 30)
    try:
        t = int(t)
    except (TypeError, ValueError):
        t = 30
    # A key given on the command line or in the environment wins over a stored login
    if key and token and sources.get("token", "").startswith("profile") and not sources["api_key"].startswith("profile"):
        token = None
    return Settings(profile=name, url=url, api_key=key, token=token, user=user, timeout=t, sources=sources)
