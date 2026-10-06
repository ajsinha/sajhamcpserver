"""
MCP 2026-07-28 Multi Round-Trip Requests (MRTR, SEP-2322).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A stateless server cannot hold a request open while it asks the client for
something (sampling, elicitation, roots).  Instead it answers with an
``InputRequiredResult``::

    {"resultType": "input_required",
     "inputRequests": {"<key>": {"method": "elicitation/create", "params": {...}}},
     "requestState": "<opaque>"}

and the client retries the *same* request with ``inputResponses`` (keyed like
``inputRequests``) plus the echoed ``requestState``.

SAJHA's ``requestState`` is ``base64url(payload) "." base64url(HMAC-SHA256)``.
The payload binds the state to the method, the target (tool / prompt / URI),
a digest of the arguments and the caller, carries an expiry, and accumulates
the input responses of earlier rounds — so a tool sees every answer gathered
so far on each retry without the server keeping anything.  The state is
signed, not encrypted: it only ever holds what the client itself sent.  A
state that fails verification (tampered, expired, replayed against another
tool/argument set/user) is rejected with -32602.

The signing secret comes from ``mcp.mrtr.state_secret``
(env ``SAJHA_MCP_MRTR_STATE_SECRET``); if unset it is derived from
``auth.session.secret_key`` — which, when that is not configured either, is
random per process, so states then do not survive a restart.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

# Methods that may answer with an InputRequiredResult (SEP-2322)
MRTR_METHODS = ("tools/call", "prompts/get", "resources/read")

# Input-request method -> the client capability it needs
INPUT_REQUEST_CAPABILITY = {
    "elicitation/create": "elicitation",
    "sampling/createMessage": "sampling",
    "roots/list": "roots",
}

_STATE_VERSION = 1


class InputRequired(Exception):
    """
    Raised by a tool / prompt handler that needs client input before it can
    finish.  ``requests`` maps server-chosen keys to ``{"method", "params"}``
    InputRequest objects; ``state`` is optional extra server state (JSON
    serialisable) returned to the handler on the retry via ``ctx.state``.
    """

    def __init__(self, requests: Mapping[str, Dict[str, Any]], state: Optional[Dict[str, Any]] = None):
        super().__init__(f"input required: {', '.join(requests)}")
        self.requests = dict(requests)
        self.state = dict(state or {})


class RequestStateError(ValueError):
    """requestState failed integrity / binding verification."""


# ── secret ─────────────────────────────────────────────────────────

_secret_cache: Optional[bytes] = None


def _secret() -> bytes:
    global _secret_cache
    if _secret_cache is None:
        from sajha.core.config import _get
        configured = (_get("mcp.mrtr.state_secret", "") or "").strip()
        if configured:
            _secret_cache = configured.encode("utf-8")
        else:
            base = (_get("auth.session.secret_key", "") or "").strip()
            seed = base.encode("utf-8") if base else os.urandom(32)
            _secret_cache = hmac.new(seed, b"sajha/mcp/mrtr-request-state/v1", hashlib.sha256).digest()
    return _secret_cache


def reset_secret_cache() -> None:
    """For tests / config reloads."""
    global _secret_cache
    _secret_cache = None


def _ttl_seconds() -> int:
    from sajha.core.config import _int
    return max(1, _int("mcp.mrtr.state_ttl_seconds", 900))


# ── encoding ───────────────────────────────────────────────────────

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def arguments_digest(arguments: Any) -> str:
    return hashlib.sha256(_canonical(arguments if arguments is not None else {})).hexdigest()[:32]


def sign_state(*, method: str, target: str, arguments: Any, user: Optional[str],
               responses: Dict[str, Any], state: Dict[str, Any], round_no: int) -> str:
    payload = {
        "v": _STATE_VERSION,
        "m": method,
        "t": target,
        "a": arguments_digest(arguments),
        "u": user,
        "r": responses,
        "s": state,
        "n": round_no,
        "x": int(time.time()) + _ttl_seconds(),
        "j": secrets.token_hex(6),          # makes every state distinct
    }
    body = _b64e(_canonical(payload))
    mac = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64e(mac)}"


def verify_state(token: Any, *, method: str, target: str, arguments: Any, user: Optional[str]) -> Dict[str, Any]:
    """Return the payload of a valid state, else raise RequestStateError."""
    if not isinstance(token, str) or token.count(".") != 1 or len(token) > 1_000_000:
        raise RequestStateError("requestState is malformed")
    body, mac = token.split(".")
    try:
        given = _b64d(mac)
    except (ValueError, TypeError):
        raise RequestStateError("requestState is malformed")
    expected = hmac.new(_secret(), body.encode("ascii", "replace"), hashlib.sha256).digest()
    if not hmac.compare_digest(given, expected):
        raise RequestStateError("requestState failed integrity verification")
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, TypeError):
        raise RequestStateError("requestState is malformed")
    if not isinstance(payload, dict) or payload.get("v") != _STATE_VERSION:
        raise RequestStateError("requestState version is not supported")
    if payload.get("x", 0) < time.time():
        raise RequestStateError("requestState has expired; retry the request from the start")
    if payload.get("m") != method or payload.get("t") != target:
        raise RequestStateError("requestState was issued for a different request")
    if payload.get("a") != arguments_digest(arguments):
        raise RequestStateError("requestState was issued for different arguments")
    if payload.get("u") != user:
        raise RequestStateError("requestState was issued to a different caller")
    return payload


# ── validation ─────────────────────────────────────────────────────

def validate_input_responses(value: Any) -> Dict[str, Dict[str, Any]]:
    """``inputResponses`` must be an object of objects (or absent)."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("inputResponses must be an object keyed by inputRequests keys")
    for key, response in value.items():
        if not isinstance(response, dict):
            raise ValueError(f"inputResponses[{key!r}] must be an object (an ElicitResult, "
                             f"CreateMessageResult or ListRootsResult)")
    return value


def missing_capabilities_for(requests: Mapping[str, Dict[str, Any]],
                             client_capabilities: Mapping[str, Any]) -> Dict[str, Any]:
    """Client capabilities the given input requests need but the client did not declare."""
    missing: Dict[str, Any] = {}
    for req in requests.values():
        cap = INPUT_REQUEST_CAPABILITY.get((req or {}).get("method"))
        if cap and cap not in (client_capabilities or {}):
            missing[cap] = {}
    return missing


def elicitation_form_supported(client_capabilities: Mapping[str, Any]) -> bool:
    """Form-mode elicitation: ``elicitation: {}`` (form implied) or ``elicitation: {form: {...}}``."""
    elicitation = (client_capabilities or {}).get("elicitation")
    if not isinstance(elicitation, dict):
        return False
    return not elicitation or "form" in elicitation or "url" not in elicitation


def elicitation_request(message: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    return {"method": "elicitation/create",
            "params": {"mode": "form", "message": message, "requestedSchema": schema}}


def accepted_content(response: Any) -> Optional[Dict[str, Any]]:
    """The content of an accepted ElicitResult, else None (declined / cancelled / malformed)."""
    if isinstance(response, dict) and response.get("action") == "accept":
        content = response.get("content")
        return content if isinstance(content, dict) else {}
    return None
