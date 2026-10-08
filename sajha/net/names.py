"""
Names (protocol §5): net names, instance names (configured or address), safe prefixes,
qualified tool names and net users.

Pure functions; nothing here touches the network except :func:`default_route_address`, which
asks the operating system which local address carries the default route (a UDP ``connect``
sends no packet).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Callable, Optional, Tuple

DEFAULT_NET = 'default'

NET_NAME_RE = re.compile(r'^(?!.*__)(?!.*_$)[a-z][a-z0-9_-]{0,15}$')
CONFIGURED_NAME_RE = re.compile(r'^[a-z][a-z0-9-]{0,30}[a-z0-9]$')
_IPV4_NAME_RE = re.compile(r'^([0-9]{1,3}(?:\.[0-9]{1,3}){3}):([0-9]{1,5})$')
_IPV6_NAME_RE = re.compile(r'^\[([0-9a-f:.]+)\]:([0-9]{1,5})$')
_TOOL_PART_RE = re.compile(r'[^A-Za-z0-9_-]')
VENDOR_RE = re.compile(r'^(?!.*__)(?!.*_$)[a-z][a-z0-9_]{0,23}$')
PUBLISHED_NAME_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$')

MAX_QUALIFIED = 128
VENDOR_SEPARATOR = '__'


class NameError_(ValueError):
    """A name that does not satisfy protocol §5."""


# ── net names (§5.1) ────────────────────────────────────────────────

def is_net_name(name) -> bool:
    return isinstance(name, str) and bool(NET_NAME_RE.match(name))


def net_name_or_default(name: Optional[str]) -> str:
    """The configured net name, ``default`` when none is given; raises on an invalid one."""
    if name is None or name == '':
        return DEFAULT_NET
    if not is_net_name(name):
        raise NameError_(f'invalid net name {name!r}: lowercase letters, digits, "-" and "_", starting with a '
                         f'letter, at most 16 characters, never "__" and not ending with "_"')
    return name


# ── instance names (§5.2) ───────────────────────────────────────────

def is_configured_name(name) -> bool:
    return isinstance(name, str) and bool(CONFIGURED_NAME_RE.match(name)) and '--' not in name


def address_refusal(ip) -> Optional[str]:
    """Why ``ip`` may not name an instance (None when it may): unspecified, loopback, link-local."""
    try:
        a = ip if isinstance(ip, (ipaddress.IPv4Address, ipaddress.IPv6Address)) else ipaddress.ip_address(str(ip))
    except ValueError:
        return f'{ip!r} is not an IP address'
    if isinstance(a, ipaddress.IPv6Address) and a.scope_id:
        return f'{a} carries an IPv6 zone'
    mapped = getattr(a, 'ipv4_mapped', None)
    for x in (a, mapped) if mapped else (a,):
        if x.is_unspecified:
            return f'{a} is unspecified (0.0.0.0 or ::)'
        if x.is_loopback:
            return f'{a} is a loopback address'
        if x.is_link_local:
            return f'{a} is link-local'
    return None


def parse_address_name(name: str) -> Optional[Tuple[ipaddress._BaseAddress, int]]:
    """``(ip, port)`` for a well-formed address name, else None (also None for a configured name)."""
    if not isinstance(name, str):
        return None
    m = _IPV4_NAME_RE.match(name)
    if m:
        try:
            ip = ipaddress.IPv4Address(m.group(1))
        except ValueError:
            return None
        if str(ip) != m.group(1):          # no leading zeros: one spelling per address
            return None
    else:
        m = _IPV6_NAME_RE.match(name)
        if not m:
            return None
        try:
            ip = ipaddress.IPv6Address(m.group(1))
        except ValueError:
            return None
        if str(ip) != m.group(1):          # RFC 5952 canonical text form only
            return None
    port = int(m.group(2))
    if not 1 <= port <= 65535 or str(port) != m.group(2):
        return None
    return ip, port


def is_address_name(name) -> bool:
    p = parse_address_name(name)
    return p is not None and address_refusal(p[0]) is None


def is_instance_name(name) -> bool:
    return is_configured_name(name) or is_address_name(name)


def format_address_name(ip, port: int) -> str:
    """``10.20.4.17:3002`` or ``[2001:db8::7]:3002`` (RFC 5952 form); raises when unacceptable."""
    a = ipaddress.ip_address(str(ip).strip('[]'))
    why = address_refusal(a)
    if why:
        raise NameError_(why)
    port = int(port)
    if not 1 <= port <= 65535:
        raise NameError_(f'port {port} is out of range')
    return f'[{a}]:{port}' if a.version == 6 else f'{a}:{port}'


def default_route_address(family: int = socket.AF_INET) -> Optional[str]:
    """The local address of the interface that carries the default route (no packet is sent)."""
    probe = ('192.0.2.1', 9) if family == socket.AF_INET else ('2001:db8::1', 9)
    s = None
    try:
        s = socket.socket(family, socket.SOCK_DGRAM)
        s.connect(probe)
        return s.getsockname()[0].split('%')[0]
    except OSError:
        return None
    finally:
        if s is not None:
            s.close()


def _split_host_port(text: str, default_port: int) -> Tuple[str, int]:
    text = text.strip()
    if text.startswith('['):
        host, _, rest = text[1:].partition(']')
        return host, int(rest[1:]) if rest.startswith(':') and rest[1:] else default_port
    if text.count(':') == 1:
        host, port = text.split(':')
        return host, int(port) if port else default_port
    return text, default_port                      # an IPv6 address without brackets, or a bare IPv4


def resolve_instance_name(configured: Optional[str], advertise_address: Optional[str], bind_host: str,
                          port: int, route_address: Callable[[], Optional[str]] = default_route_address,
                          ) -> Tuple[Optional[str], Optional[str]]:
    """This participant's instance name in a net (design §6.1): ``(name, None)`` or ``(None, why)``.

    A configured name is used as is (it must be valid). Otherwise the address name comes from the
    net's ``advertise_address``, else a specific bind address, else the address of the interface
    carrying the default route; never an unspecified, loopback, ``localhost`` or link-local address.
    """
    if configured:
        if not is_configured_name(configured):
            return None, (f'instance_name {configured!r} is not a valid instance name (lowercase letters, digits '
                          f'and single hyphens, starting with a letter, 2 to 32 characters)')
        return configured, None
    if advertise_address:
        try:
            host, p = _split_host_port(str(advertise_address), port)
        except ValueError:
            return None, f'advertise_address {advertise_address!r} cannot be parsed as ip:port'
        if host.lower() == 'localhost':
            return None, 'advertise_address is localhost, which other participants cannot reach'
        try:
            return format_address_name(host, p), None
        except (ValueError, NameError_) as e:
            return None, f'advertise_address {advertise_address!r} cannot name this instance: {e}'
    host = (bind_host or '').strip().strip('[]')
    if host.lower() == 'localhost':
        return None, ('the server is bound to localhost, which other participants cannot reach; set an '
                      'instance_name or advertise_address for the net')
    try:
        a = ipaddress.ip_address(host) if host else None
    except ValueError:
        return None, f'bind address {host!r} is not an IP address; set an instance_name or advertise_address'
    if a is not None and not a.is_unspecified:
        why = address_refusal(a)
        if why:
            return None, f'the bind address cannot name this instance: {why}; set an instance_name or advertise_address'
        return format_address_name(a, port), None
    r = route_address()
    if not r:
        return None, ('the server is bound to all interfaces and no default-route interface was found; set an '
                      'instance_name or advertise_address for the net')
    why = address_refusal(r)
    if why:
        return None, f'the default-route interface address cannot name this instance: {why}'
    return format_address_name(r, port), None


# ── safe prefix and qualified names (§5.3) ─────────────────────────

def safe_prefix(instance_name: str) -> str:
    if is_configured_name(instance_name):
        return instance_name
    p = parse_address_name(instance_name)
    if p is None:
        raise NameError_(f'{instance_name!r} is not an instance name')
    ip, port = p
    if ip.version == 4:
        return instance_name.replace('.', '_').replace(':', '_')
    groups = [ip.packed[i:i + 2].hex() for i in range(0, 16, 2)]   # IPv4-mapped too: eight hex groups
    return '_'.join(groups) + f'_{port}'


def tool_part(tool_name: str) -> str:
    return _TOOL_PART_RE.sub('_', tool_name or '')


def qualified_name(net: str, instance_name: str, tool_name: str) -> str:
    if not is_net_name(net):
        raise NameError_(f'invalid net name {net!r}')
    q = f'{net}__{safe_prefix(instance_name)}__{tool_part(tool_name)}'
    if len(q) > MAX_QUALIFIED:
        raise NameError_(f'qualified name longer than {MAX_QUALIFIED} characters: {q[:40]}...')
    return q


def split_qualified(name: str) -> Optional[Tuple[str, str, str]]:
    """``(net, safe prefix, tool part)`` split at the first two ``__``; None for a plain name."""
    if not isinstance(name, str):
        return None
    i = name.find('__')
    if i <= 0:
        return None
    j = name.find('__', i + 2)
    if j < 0:
        return None
    net, prefix, part = name[:i], name[i + 2:j], name[j + 2:]
    if not is_net_name(net) or not prefix or prefix.startswith('_') or prefix.endswith('_') or not part:
        return None
    return net, prefix, part


# ── vendors and published tool names (§5.5) ─────────────────────────

def is_vendor(name) -> bool:
    """A vendor: lowercase letter first, then lowercase letters, digits and ``_``; at most 24
    characters; never ``__`` and not ending with ``_`` (the syntax of a safe federation prefix)."""
    return isinstance(name, str) and bool(VENDOR_RE.match(name))


def vendor_or_error(name: Optional[str], what: str = 'vendor') -> str:
    v = str(name or '').strip()
    if not is_vendor(v):
        raise NameError_(f'{what} {name!r} is not a vendor name: a lowercase letter, then lowercase letters, digits '
                         f'and "_", at most 24 characters, never "__" and not ending with "_"')
    return v


def is_published_name(name) -> bool:
    return isinstance(name, str) and bool(PUBLISHED_NAME_RE.match(name))


def published_name(local: str, vendor: str = '', namespaced: bool = False,
                   rename: Optional[dict] = None) -> str:
    """The name a participant offers its tool ``local`` under (§5.5): its ``rename`` entry when it has
    one, else ``<vendor>__<local>`` for a namespaced participant (unchanged when ``local`` already
    starts with ``<vendor>__``), else ``local``."""
    if rename and local in rename and rename[local]:
        return str(rename[local])
    if namespaced and vendor:
        head = vendor + VENDOR_SEPARATOR
        return local if local.startswith(head) else head + local
    return local


def max_tool_part(net: str, instance_name: str) -> int:
    """The longest tool part a tool of ``instance_name`` in ``net`` may have (MAX_QUALIFIED)."""
    return MAX_QUALIFIED - len(net) - len(safe_prefix(instance_name)) - 4


def net_user(user_name: str, instance_name: str) -> str:
    return f'{user_name}@{instance_name}'
