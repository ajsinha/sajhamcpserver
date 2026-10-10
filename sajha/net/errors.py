"""
Error model (protocol §7.4, §7.5, §17): refusal reasons, their HTTP status on ``/sajhanet/``,
their JSON-RPC code on the MCP endpoint, and the RFC 9457 problem body.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sajha.net import SUPPORTED_VERSIONS

#: §7.4: reason -> HTTP status on /sajhanet/
REASON_STATUS: Dict[str, int] = {
    'invalid_request': 400, 'unsupported_version': 400, 'unknown_member': 400,
    'signature_missing': 401, 'signature_invalid': 401, 'signature_incomplete': 401,
    'signature_expired': 401, 'replay': 401, 'digest_mismatch': 401, 'certificate_invalid': 401,
    'from_mismatch': 401, 'assertion_invalid': 401, 'token_invalid': 401,
    'certificate_revoked': 403, 'instance_revoked': 403, 'net_mismatch': 403, 'blocked': 403,
    'enrollment_refused': 403, 'not_home': 403,
    'name_conflict': 409,
    'too_large': 413,
    'recipient_mismatch': 421,
    'rate_limited': 429,
    'unavailable': 503, 'draining': 503,
}

TITLES: Dict[str, str] = {
    'invalid_request': 'Invalid request', 'unsupported_version': 'Unsupported protocol version',
    'unknown_member': 'Unknown member', 'signature_missing': 'Signature missing',
    'signature_invalid': 'Signature invalid', 'signature_incomplete': 'Signature incomplete',
    'signature_expired': 'Signature too old', 'replay': 'Replayed request', 'digest_mismatch': 'Digest mismatch',
    'certificate_invalid': 'Certificate invalid', 'from_mismatch': 'Sender mismatch',
    'certificate_revoked': 'Certificate revoked', 'instance_revoked': 'Instance revoked',
    'net_mismatch': 'Wrong net', 'blocked': 'Blocked', 'enrollment_refused': 'Enrollment refused',
    'not_home': 'Not the home instance', 'name_conflict': 'Name conflict', 'too_large': 'Too large',
    'recipient_mismatch': 'Wrong recipient', 'rate_limited': 'Rate limited', 'unavailable': 'Unavailable',
    'draining': 'Draining', 'assertion_invalid': 'User assertion invalid', 'token_invalid': 'Token invalid',
}

#: §17: home-side refusals of a streamed response (§8.9, §15.10); never an HTTP status (they are found while
#: reading a stream), always ``side: home`` and ``executed`` null on the MCP endpoint (-32019)
STREAM_REASONS = ('event_invalid', 'event_order', 'stream_truncated', 'stream_limit', 'stream_idle')
TITLES.update({'event_invalid': 'Stream event invalid', 'event_order': 'Stream events out of order',
               'stream_truncated': 'Stream truncated', 'stream_limit': 'Stream too large',
               'stream_idle': 'Stream idle'})

#: §17.1: JSON-RPC codes of net refusals on the MCP endpoint
RPC_AUTHORIZATION = -32011
RPC_RESIDENCY = -32012
RPC_IDENTITY = -32013
RPC_PEER = -32014
RPC_BLOCKED = -32015
RPC_HOP = -32016
RPC_VERSION = -32017
RPC_IMPORT = -32018
RPC_UNAVAILABLE = -32019

#: reasons of the 401/403 peer refusals that map to -32014 on the MCP endpoint
PEER_REASONS = frozenset(r for r, s in REASON_STATUS.items() if s in (401, 403)) - {'blocked', 'enrollment_refused',
                                                                                   'not_home'}


class NetError(Exception):
    """A protocol refusal. ``reason`` is a §7.4/§17 reason; ``extra`` goes into the problem body."""

    def __init__(self, reason: str, detail: str = '', status: Optional[int] = None, **extra: Any):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail or TITLES.get(reason, reason)
        self.status = status or REASON_STATUS.get(reason, 400)
        self.extra = extra


def problem(reason: str, detail: str = '', status: Optional[int] = None, **extra: Any) -> Dict[str, Any]:
    """An ``application/problem+json`` body (§7.5); ``detail`` must be safe to show the other side."""
    st = status or REASON_STATUS.get(reason, 400)
    body: Dict[str, Any] = {'type': f'urn:sajha:net:error:{reason}', 'title': TITLES.get(reason, reason),
                            'status': st, 'reason': reason}
    if detail:
        body['detail'] = detail[:1024]
    if reason == 'unsupported_version':
        body['supported_versions'] = list(SUPPORTED_VERSIONS)
    for k, v in extra.items():
        if v is not None:
            body[k] = v
    return body


def problem_from(err: NetError) -> Dict[str, Any]:
    return problem(err.reason, err.detail, err.status, **err.extra)
