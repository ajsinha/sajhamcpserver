"""
SAJHA sandbox — administrator settings (the ``sandbox:`` section of application.yml).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Every key resolves through ``sajha.core.config._get``: ``SAJHA_SANDBOX_<KEY>`` in the
environment, then the YAML, then the default below. Settings are read on every
call (a dictionary lookup), so tests and a config reload see changes at once.
"""

from dataclasses import dataclass, field
from typing import Dict, List

#: Built-in defaults. ``defaults`` apply when a tool's ``sandbox`` block does not
#: set a value; ``max`` caps what a tool may ask for.
DEFAULTS = {
    'default_backend': 'subprocess',
    'enforce_for_generated_tools': True,
    'strict': False,
    'work_dir': '',
    'python': '',
    'extra_read_paths': [],
    'secrets_allowlist': [],
    'defaults': {
        'timeout_seconds': 30,
        'cpu_seconds': 30,
        'memory_mb': 512,
        'max_output_bytes': 1048576,
        'max_processes': 64,
        'max_file_mb': 64,
        'network': 'none',
    },
    'max': {
        'timeout_seconds': 300,
        'cpu_seconds': 300,
        'memory_mb': 4096,
        'max_output_bytes': 16777216,
        'max_processes': 512,
        'max_file_mb': 1024,
    },
    'docker': {
        'binary': 'docker',
        'image': 'python:3.13-slim',
        'runtime': '',
        'cpus': '1',
    },
}

NUMERIC_KEYS = ('timeout_seconds', 'cpu_seconds', 'memory_mb', 'max_output_bytes',
                'max_processes', 'max_file_mb')


def _raw(key: str, default):
    try:
        from sajha.core.config import _get
        return _get(f'sandbox.{key}', '' if default is None else str(default))
    except Exception:
        return default


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    v = str(value).strip().lower()
    if v in ('1', 'true', 'yes', 'on'):
        return True
    if v in ('0', 'false', 'no', 'off'):
        return False
    return default


def _as_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def as_list(value) -> List[str]:
    """A YAML list arrives flattened as "['a', 'b']"; an env var as "a,b"."""
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value or '').strip().strip('[]')
    return [p.strip().strip('\'"') for p in text.split(',') if p.strip().strip('\'"')]


@dataclass
class SandboxSettings:
    default_backend: str = 'subprocess'
    enforce_for_generated_tools: bool = True
    strict: bool = False
    work_dir: str = ''
    python: str = ''
    extra_read_paths: List[str] = field(default_factory=list)
    secrets_allowlist: List[str] = field(default_factory=list)
    defaults: Dict = field(default_factory=dict)
    max: Dict = field(default_factory=dict)
    docker: Dict = field(default_factory=dict)


def load_settings() -> SandboxSettings:
    d = DEFAULTS
    defaults = {k: _as_int(_raw(f'defaults.{k}', v), v) for k, v in d['defaults'].items()
                if k in NUMERIC_KEYS}
    defaults['network'] = str(_raw('defaults.network', d['defaults']['network']) or 'none').lower()
    return SandboxSettings(
        default_backend=str(_raw('default_backend', d['default_backend']) or 'subprocess').lower(),
        enforce_for_generated_tools=_as_bool(_raw('enforce_for_generated_tools', True), True),
        strict=_as_bool(_raw('strict', False), False),
        work_dir=str(_raw('work_dir', '') or ''),
        python=str(_raw('python', '') or ''),
        extra_read_paths=as_list(_raw('extra_read_paths', '')),
        secrets_allowlist=as_list(_raw('secrets_allowlist', '')),
        defaults=defaults,
        max={k: _as_int(_raw(f'max.{k}', v), v) for k, v in d['max'].items()},
        docker={k: str(_raw(f'docker.{k}', v) or v) for k, v in d['docker'].items()},
    )
