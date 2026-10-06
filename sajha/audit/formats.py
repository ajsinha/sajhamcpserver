"""
SAJHA MCP Server — renderings of an audit record for SIEM sinks.

* ``json``: the record itself (with its ``hash``), canonical JSON;
* ``cef``: ArcSight Common Event Format, one line;
* ``ocsf``: an OCSF-style object (API Activity, Authentication or Account Change), with
  ``metadata.uid`` the record's hash and ``metadata.sequence`` its sequence number.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
from typing import Any, Dict, Tuple

from sajha.audit.chain import canonical, parse_ts

FORMATS = ('json', 'cef', 'ocsf')

#: event -> severity 0..10 (CEF); unknown events are 3 (low)
_SEVERITY = {
    'policy.deny': 6, 'policy.rate_limited': 5, 'policy.output_flagged': 7, 'policy.approval_required': 4,
    'policy.redacted': 3, 'approval.deny': 4, 'approval.approve': 4, 'login_failed': 5, 'account_locked': 7,
    'permission_change': 6, 'apikey_create': 5, 'apikey_revoke': 5, 'user_create': 5, 'user_delete': 6,
    'config_change': 5, 'chain.open': 1, 'chain.close': 1, 'audit.anchor': 1,
}


def severity(event: str) -> int:
    return _SEVERITY.get(event, 3)


def syslog_severity(event: str) -> int:
    """RFC 5424 severity: 4 warning, 5 notice, 6 informational."""
    s = severity(event)
    return 4 if s >= 6 else 5 if s >= 4 else 6


def _version() -> str:
    try:
        from sajha.core.config import get_settings
        return str(get_settings().app_version)
    except Exception:
        return ''


def _cef_header(v: Any) -> str:
    return str(v if v is not None else '').replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ')


def _cef_ext(v: Any) -> str:
    return (str(v if v is not None else '').replace('\\', '\\\\').replace('=', '\\=')
            .replace('\r', '\\r').replace('\n', '\\n'))


def to_cef(rec: Dict[str, Any]) -> str:
    event = rec.get('event', '')
    actor = rec.get('actor') or {}
    res = rec.get('resource') or {}
    ext = {
        'rt': int(parse_ts(rec['ts']).timestamp() * 1000) if rec.get('ts') else '',
        'suser': actor.get('user'), 'src': actor.get('ip'), 'act': event, 'outcome': rec.get('outcome'),
        'cs1Label': 'chain', 'cs1': rec.get('chain'), 'cs2Label': 'hash', 'cs2': rec.get('hash'),
        'cs3Label': 'resource', 'cs3': f"{res.get('type', '')}:{res.get('id', '')}" if res else None,
        'cs4Label': 'roles', 'cs4': ','.join(actor.get('roles') or []) or None,
        'cn1Label': 'seq', 'cn1': rec.get('seq'),
        'msg': canonical(rec.get('details')) if rec.get('details') is not None else None,
    }
    parts = ' '.join(f'{k}={_cef_ext(v)}' for k, v in ext.items() if v not in (None, ''))
    return '|'.join(['CEF:0', 'SAJHA', 'SAJHA MCP Server', _cef_header(_version()), _cef_header(event),
                     _cef_header(event.replace('.', ' ').replace('_', ' ')), str(severity(event))]) + '|' + parts


def _ocsf_class(event: str) -> Tuple[int, str, int, str, int]:
    """(class_uid, class_name, category_uid, category_name, activity_id)."""
    if event in ('login_success', 'login_failed', 'logout', 'account_locked'):
        act = {'login_success': 1, 'login_failed': 1, 'logout': 2, 'account_locked': 99}[event]
        return 3002, 'Authentication', 3, 'Identity & Access Management', act
    if event.startswith(('user_', 'apikey_', 'permission_')):
        act = 1 if event.endswith('create') else 6 if event.endswith(('delete', 'revoke')) else 99
        return 3001, 'Account Change', 3, 'Identity & Access Management', act
    return 6003, 'API Activity', 6, 'Application Activity', 99


def to_ocsf(rec: Dict[str, Any]) -> Dict[str, Any]:
    event = rec.get('event', '')
    actor = rec.get('actor') or {}
    res = rec.get('resource') or {}
    cls, cls_name, cat, cat_name, act = _ocsf_class(event)
    outcome = (rec.get('outcome') or '').lower()
    failed = outcome in ('deny', 'denied', 'constraint', 'default_deny', 'rate', 'quota', 'block', 'error',
                         'failed', 'not_confirmed') or event in ('login_failed', 'policy.deny', 'policy.rate_limited')
    sev = severity(event)
    return {
        'class_uid': cls, 'class_name': cls_name, 'category_uid': cat, 'category_name': cat_name,
        'activity_id': act, 'type_uid': cls * 100 + act,
        'time': int(parse_ts(rec['ts']).timestamp() * 1000) if rec.get('ts') else None,
        'severity_id': 1 if sev <= 2 else 2 if sev <= 4 else 3 if sev <= 6 else 4,
        'status': 'Failure' if failed else 'Success', 'status_id': 2 if failed else 1,
        'message': event,
        'actor': {'user': {'name': actor.get('user'), 'uid': actor.get('user'),
                           'groups': [{'name': r} for r in actor.get('roles') or []]},
                  **({'session': {'credential_uid': actor.get('api_key')}} if actor.get('api_key') else {})},
        'src_endpoint': {'ip': actor.get('ip')} if actor.get('ip') else None,
        'api': {'operation': event, 'service': {'name': 'sajha'}},
        'resources': [{'type': res.get('type'), 'uid': res.get('id')}] if res else [],
        'metadata': {'version': '1.1.0', 'uid': rec.get('hash'), 'sequence': rec.get('seq'),
                     'correlation_uid': rec.get('chain'),
                     'product': {'name': 'SAJHA MCP Server', 'vendor_name': 'SAJHA', 'version': _version()}},
        'unmapped': {'outcome': rec.get('outcome'), 'details': rec.get('details'), 'prev': rec.get('prev')},
    }


def render(rec: Dict[str, Any], fmt: str = 'json') -> str:
    """One line of text for ``rec`` in ``fmt``."""
    if fmt == 'cef':
        return to_cef(rec)
    if fmt == 'ocsf':
        return json.dumps(to_ocsf(rec), separators=(',', ':'), ensure_ascii=False, default=str)
    return canonical(rec)


def as_object(rec: Dict[str, Any], fmt: str = 'json') -> Any:
    """The JSON value to embed in an HTTP payload (CEF stays a string)."""
    if fmt == 'cef':
        return to_cef(rec)
    if fmt == 'ocsf':
        return to_ocsf(rec)
    return rec
