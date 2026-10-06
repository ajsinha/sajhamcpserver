"""
SAJHA sandbox — runs user-supplied code (Studio Python code tools, Studio script
tools, the admin shell) outside the server's privileges.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Design and threat model: docs/architecture/Sandbox.md.

    from sajha.sandbox import get_backend, policy_from_config
    backend = get_backend()                       # sandbox.default_backend
    res = backend.run({'op': 'exec', 'argv': ['/bin/sh', '-c', 'echo hi']},
                      policy_from_config({'timeout_seconds': 5}))
"""

from typing import Any, Dict

from .backends import (BACKENDS, Sandbox, SandboxError, SandboxOutputLimit, SandboxResult,
                       SandboxTimeout, SandboxToolError, SandboxUnavailable, get_backend, reset)
from .policy import PolicyError, SandboxPolicy, policy_from_config
from .settings import SandboxSettings, load_settings

__all__ = ['BACKENDS', 'Sandbox', 'SandboxError', 'SandboxOutputLimit', 'SandboxResult',
           'SandboxTimeout', 'SandboxToolError', 'SandboxUnavailable', 'PolicyError',
           'SandboxPolicy', 'SandboxSettings', 'get_backend', 'load_settings',
           'policy_from_config', 'reset', 'status', 'studio_policy']


def status(probe: bool = True) -> Dict[str, Any]:
    """Which backend is active, what each backend here can do, and what it guarantees.

    ``probe`` runs the active backend's runner once (cached) so the guarantees are
    what the runner actually applied on this host, not what it was asked to apply.
    """
    settings = load_settings()
    backends = {}
    for name, cls in BACKENDS.items():
        b = cls(settings)
        ok, why = b.available()
        backends[name] = {'available': ok, 'detail': why, 'summary': cls.summary}
    error = None
    try:
        active = get_backend(None, settings)
    except SandboxError as e:
        active, error = None, str(e)
    out: Dict[str, Any] = {
        'default_backend': settings.default_backend,
        'active_backend': active.name if active else None,
        'enforce_for_generated_tools': settings.enforce_for_generated_tools,
        'strict': settings.strict,
        'defaults': settings.defaults,
        'max': settings.max,
        'backends': backends,
    }
    if error:
        out['error'] = error
    if active is not None:
        out['guarantees'] = active.guarantees(probe=probe)
        if probe:
            p = active.probe()
            out['probe'] = {'ok': p.get('ok'), 'error': p.get('error')}
    return out


def studio_policy(kind: str = 'python') -> Dict[str, Any]:
    """What a new Studio tool of this kind will get: for the creator pages."""
    settings = load_settings()
    st = status(probe=True)
    pol = policy_from_config({}, settings)
    return {
        'sandboxed': settings.enforce_for_generated_tools,
        'kind': kind,
        'backend': st.get('active_backend'),
        'policy': pol.to_dict(),
        'guarantees': st.get('guarantees', []),
        'secrets_allowlist': settings.secrets_allowlist,
    }
