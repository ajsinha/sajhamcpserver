"""
SAJHA sandbox — per-tool policy.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A tool's JSON config may carry a ``sandbox`` block::

    "sandbox": {
      "backend": "bwrap",                      # optional; else sandbox.default_backend
      "network": "none",                       # none | allowlist
      "allow_hosts": ["api.example.com:443"],  # with network: allowlist
      "timeout_seconds": 20, "cpu_seconds": 20, "memory_mb": 256,
      "max_output_bytes": 65536, "max_processes": 16, "max_file_mb": 8,
      "packages": ["pandas"],                  # python tools: imports allowed besides the stdlib
      "secrets": ["WEATHER_API_KEY"],          # env vars copied in; each must be in sandbox.secrets_allowlist
      "env": {"UNITS": "metric"}               # literal, non-secret
    }

Anything not set takes the administrator's ``sandbox.defaults``; every number is
capped by ``sandbox.max``. Secrets are the only way a server environment value
reaches a sandbox, and only by name, only if the administrator allowlisted it,
and never a ``SAJHA_*`` variable.
"""

import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .settings import NUMERIC_KEYS, SandboxSettings, as_list, load_settings

logger = logging.getLogger(__name__)

_ENV_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,127}$')
#: Set by the sandbox itself; a tool cannot override them.
RESERVED_ENV = {'HOME', 'TMPDIR', 'TMP', 'TEMP', 'PWD', 'LD_PRELOAD', 'LD_LIBRARY_PATH',
                'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'BASH_ENV', 'ENV'}


class PolicyError(ValueError):
    """A tool's sandbox block asks for something the administrator does not allow."""


@dataclass
class SandboxPolicy:
    timeout_seconds: int = 30
    cpu_seconds: int = 30
    memory_mb: int = 512
    max_output_bytes: int = 1048576
    max_processes: int = 64
    max_file_mb: int = 64
    network: str = 'none'
    allow_hosts: List[str] = field(default_factory=list)
    packages: List[str] = field(default_factory=list)
    secrets: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    backend: Optional[str] = None

    @property
    def allow_ports(self) -> List[int]:
        ports = set()
        for h in self.allow_hosts:
            host, _, port = h.rpartition(':') if ':' in h else (h, '', '443')
            try:
                ports.add(int(port))
            except ValueError:
                ports.add(443)
        return sorted(ports)

    @property
    def allow_hostnames(self) -> List[str]:
        return [h.rsplit(':', 1)[0] if ':' in h else h for h in self.allow_hosts]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['allow_ports'] = self.allow_ports
        return d

    def secret_env(self, settings: Optional[SandboxSettings] = None) -> Dict[str, str]:
        """Values of the declared secrets, read from the server environment now."""
        settings = settings or load_settings()
        out = {}
        for name in self.secrets:
            if name not in settings.secrets_allowlist or name.upper().startswith('SAJHA_'):
                raise PolicyError(f"secret '{name}' is not in sandbox.secrets_allowlist")
            if name in os.environ:
                out[name] = os.environ[name]
            else:
                logger.warning(f"sandbox secret '{name}' is declared but not set in the server environment")
        return out


def policy_from_config(block: Optional[Dict[str, Any]], settings: Optional[SandboxSettings] = None,
                       **overrides) -> SandboxPolicy:
    """The effective policy: tool block (or overrides) over admin defaults, capped by admin max."""
    settings = settings or load_settings()
    block = dict(block or {})
    block.update({k: v for k, v in overrides.items() if v is not None})
    vals: Dict[str, Any] = {}
    for key in NUMERIC_KEYS:
        default = settings.defaults.get(key)
        if key == 'cpu_seconds' and 'cpu_seconds' not in block and 'timeout_seconds' in block:
            default = block['timeout_seconds']
        try:
            v = int(block.get(key, default))
        except (TypeError, ValueError):
            raise PolicyError(f'sandbox.{key} must be an integer')
        cap = settings.max.get(key)
        vals[key] = max(1, min(v, cap) if cap else v)
    network = str(block.get('network', settings.defaults.get('network', 'none')) or 'none').lower()
    if network not in ('none', 'allowlist'):
        raise PolicyError("sandbox.network must be 'none' or 'allowlist'")
    hosts = as_list(block.get('allow_hosts') or [])
    if network == 'allowlist' and not hosts:
        raise PolicyError('sandbox.network is allowlist but sandbox.allow_hosts is empty')
    env = {}
    for k, v in (block.get('env') or {}).items():
        if not _ENV_NAME.match(str(k)) or k in RESERVED_ENV or str(k).upper().startswith('SAJHA_'):
            raise PolicyError(f"sandbox.env name '{k}' is not allowed")
        env[str(k)] = str(v)
    secrets = as_list(block.get('secrets') or [])
    for name in secrets:
        if not _ENV_NAME.match(name):
            raise PolicyError(f"sandbox.secrets name '{name}' is not a valid variable name")
    packages = as_list(block.get('packages') or [])
    for p in packages:
        if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', p):
            raise PolicyError(f"sandbox.packages entry '{p}' is not a top-level module name")
    backend = block.get('backend') or None
    return SandboxPolicy(network=network, allow_hosts=hosts if network == 'allowlist' else [],
                         packages=packages, secrets=secrets, env=env,
                         backend=str(backend).lower() if backend else None, **vals)
