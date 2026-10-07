"""
SAJHA MCP Server — the ``io.sajha/net`` MCP extension: advertisement and client declaration.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Normative text: docs/protocol/SAJHA Net Protocol.md section 6.

* ``extension_object()``: the object a server with ``sajhanet.enabled`` advertises, in the
  2026-07-28 ``server/discover`` result at ``capabilities.extensions["io.sajha/net"]`` and in
  the 2025-11-25 ``initialize`` result at ``capabilities.experimental["io.sajha/net"]`` (that
  era's ServerCapabilities has no ``extensions``). Nothing is advertised when SAJHA Net is off.
* To a request that is not signed by a participant the object is reduced to
  ``protocol_versions`` and ``endpoint``, so an anonymous client learns neither the net name nor
  the feature list. A request whose signature was verified for a net (``signed_for(net)``,
  set by the SAJHA Net request verifier) gets the full object for that net only; other nets
  are never named.
* What the full object lists (``features``, ``user_identity``, ``signature_algorithms``) is
  declared by the SAJHA Net components as they start (``advertise``), so the advertisement
  never claims something this build does not do.
* ``client_declaration(caps)``: a client's own declaration, from either era's place.
"""

from __future__ import annotations

import contextlib
import contextvars
import copy
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

logger = logging.getLogger(__name__)

EXTENSION_ID = 'io.sajha/net'
PROTOCOL_VERSIONS = [1]
ENDPOINT = '/sajhanet/v1/'
DEFAULT_NET = 'default'

_signed_net: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('sajha_net_signed_for', default=None)
_advertised: Dict[str, List[str]] = {'features': [], 'user_identity': [], 'signature_algorithms': []}


# ── configuration ───────────────────────────────────────────────────

def enabled() -> bool:
    from sajha.core.config import _bool
    return _bool('sajhanet.enabled', False)


def configured_nets() -> List[Dict[str, Any]]:
    """``sajhanet.nets`` as a list of objects (``SAJHA_SAJHANET_NETS`` as a JSON list, else the
    YAML list); an entry without a name is the net ``default``."""
    raw = os.environ.get('SAJHA_SAJHANET_NETS')
    nets: Any = None
    if raw is not None:
        try:
            nets = json.loads(raw or '[]')
        except ValueError:
            logger.warning('SAJHA_SAJHANET_NETS is not a JSON list; ignored')
            nets = []
    else:
        path = Path(os.environ.get('SAJHA_CONFIG_FILE', 'config/application.yml'))
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding='utf-8')) or {} if path.exists() else {}
            nets = (data.get('sajhanet') or {}).get('nets') or []
        except Exception as e:
            logger.warning(f'sajhanet.nets: cannot read {path}: {e}')
            nets = []
    out = []
    for n in nets if isinstance(nets, list) else []:
        if isinstance(n, dict):
            n = dict(n)
            n['name'] = str(n.get('name') or DEFAULT_NET)
            out.append(n)
    return out


# ── advertisement ───────────────────────────────────────────────────

def advertise(features: Iterable[str] = (), user_identity: Iterable[str] = (),
              signature_algorithms: Iterable[str] = ()) -> None:
    """Add what a starting SAJHA Net component offers to the full extension object."""
    for key, values in (('features', features), ('user_identity', user_identity),
                        ('signature_algorithms', signature_algorithms)):
        for v in values:
            if isinstance(v, str) and v and v not in _advertised[key]:
                _advertised[key].append(v)


def reset_advertised() -> None:
    """Forget what was declared with ``advertise`` (tests, restart of the SAJHA Net components)."""
    for v in _advertised.values():
        v.clear()


@contextlib.contextmanager
def signed_for(net: Optional[str]) -> Iterator[None]:
    """Within this block the MCP request is one whose signature was verified for ``net``."""
    token = _signed_net.set(net)
    try:
        yield
    finally:
        _signed_net.reset(token)


def extension_object(net: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The ``io.sajha/net`` object for this request, or None when SAJHA Net is off. ``net``
    (default: the net the current request was signed for) selects the full form."""
    if not enabled():
        return None
    net = net if net is not None else _signed_net.get()
    reduced = {'protocol_versions': list(PROTOCOL_VERSIONS), 'endpoint': ENDPOINT}
    if not net:
        return reduced
    entry = next((n for n in configured_nets() if n['name'] == net), None)
    if entry is None:
        return reduced
    obj: Dict[str, Any] = {**reduced, 'net': net}
    instance = entry.get('instance_name') or entry.get('advertise_address')
    if instance:
        obj['instance'] = str(instance)
    obj['kind'] = 'sajha'
    obj['features'] = list(_advertised['features'])
    obj['user_identity'] = list(_advertised['user_identity']) or ['none']
    obj['signature_algorithms'] = list(_advertised['signature_algorithms'])
    # key order as in the specification's example
    order = ('protocol_versions', 'net', 'instance', 'kind', 'endpoint', 'features', 'user_identity',
             'signature_algorithms')
    return {k: obj[k] for k in order if k in obj}


def with_legacy_capabilities(capabilities: Dict[str, Any]) -> Dict[str, Any]:
    """2025-11-25 ``initialize`` capabilities with the extension under ``experimental``."""
    ext = extension_object()
    if ext is None:
        return capabilities
    caps = copy.deepcopy(capabilities)
    caps.setdefault('experimental', {})[EXTENSION_ID] = ext
    return caps


def add_modern_extension(extensions: Dict[str, Any]) -> None:
    """2026-07-28 ``server/discover``: the extension in ``capabilities.extensions``."""
    ext = extension_object()
    if ext is not None:
        extensions[EXTENSION_ID] = ext


# ── client declaration ──────────────────────────────────────────────

def client_declaration(client_capabilities: Any) -> Optional[Dict[str, Any]]:
    """The client's ``io.sajha/net`` declaration: ``extensions`` (2026-07-28) or ``experimental``
    (2025-11-25); a receiver looks in both. None when absent or not an object."""
    caps = client_capabilities if isinstance(client_capabilities, dict) else {}
    for place in ('extensions', 'experimental'):
        group = caps.get(place)
        if isinstance(group, dict) and isinstance(group.get(EXTENSION_ID), dict):
            return group[EXTENSION_ID]
    return None


def declared_protocol_version(client_capabilities: Any) -> Optional[int]:
    """The SAJHA Net protocol version the client declared, or None. A declaration is a hint:
    whether a request is a net request is decided by its signature, never by this."""
    decl = client_declaration(client_capabilities)
    v = decl.get('protocol_version') if decl else None
    return v if isinstance(v, int) and not isinstance(v, bool) else None
