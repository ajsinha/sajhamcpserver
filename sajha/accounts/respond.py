"""
SAJHA MCP Server — connected accounts: answering "connect your account" on each front end.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

* MCP 2026-07-28 (stateless): when the client declared URL-mode elicitation
  (``capabilities.elicitation.url``), an MRTR ``InputRequiredResult`` whose input request
  is ``elicitation/create`` with ``mode: "url"`` pointing at the connect page.  The
  client opens it, the user links the account, the client retries with the
  ``inputResponses``; the retry finds the token and runs the tool.  A retry that still
  finds no link answers with a tool error rather than asking again.
* MCP 2025-11-25 (sessions): with the same capability, a JSON-RPC error
  ``-32042 URLElicitationRequiredError`` whose ``data.elicitations`` holds the URL
  elicitation; the client shows it and calls the tool again.
* Clients without URL elicitation (and every case the user cannot fix by visiting a
  page, such as an API-key caller): a CallToolResult with ``isError: true`` whose text
  names the connect URL, plus ``_meta["sajha/connected_account"]`` for hosts that render it.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Mapping, Optional

from sajha.accounts.errors import ConnectedAccountRequired
from sajha.core.mcp_mrtr import InputRequired

URL_ELICITATION_REQUIRED = -32042
META_KEY = 'sajha/connected_account'


def url_elicitation_supported(capabilities: Optional[Mapping[str, Any]]) -> bool:
    e = (capabilities or {}).get('elicitation')
    return isinstance(e, dict) and isinstance(e.get('url'), dict)


def _fixable(exc: ConnectedAccountRequired) -> bool:
    return bool(exc.connect_url) and exc.reason in ('not_connected', 'insufficient_scope', 'reauth_required')


def url_elicitation(exc: ConnectedAccountRequired) -> Dict[str, Any]:
    return {'mode': 'url', 'elicitationId': f'connect-{exc.provider}-{uuid.uuid4().hex[:12]}',
            'url': exc.connect_url, 'message': exc.message}


def tool_error(exc: ConnectedAccountRequired, extra: str = '') -> Dict[str, Any]:
    info = {k: v for k, v in exc.to_dict().items() if k != 'error'}
    return {'content': [{'type': 'text', 'text': (extra + ' ' if extra else '') + exc.message}],
            'isError': True, '_meta': {META_KEY: info}}


def mcp_response(exc: ConnectedAccountRequired, era: str, session: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A CallToolResult for ``exc``, or raise the era's way of asking the client to open a URL."""
    if era == 'modern':
        from sajha.core.mcp_tool_context import current_context
        ctx = current_context()
        caps = getattr(ctx, 'client_capabilities', None) or {}
        if _fixable(exc) and url_elicitation_supported(caps):
            answer = (getattr(ctx, 'input_responses', None) or {}).get(exc.elicitation_key)
            if answer is None:
                raise InputRequired({exc.elicitation_key: {'method': 'elicitation/create',
                                                           'params': url_elicitation(exc)}})
            action = answer.get('action') if isinstance(answer, dict) else None
            if action == 'accept':
                return tool_error(exc, f'{exc.provider_title} is still not linked.')
            return tool_error(exc, f'Linking {exc.provider_title} was {action or "not completed"}.')
        return tool_error(exc)
    caps = (session or {}).get('client_capabilities') or {}
    if _fixable(exc) and url_elicitation_supported(caps):
        from sajha.core.mcp_2025_11_25 import MCPError
        raise MCPError(URL_ELICITATION_REQUIRED, exc.message, {'elicitations': [url_elicitation(exc)]})
    return tool_error(exc)


def rest_response(exc: ConnectedAccountRequired):
    """HTTP 428 Precondition Required: the call needs a linked account first."""
    from fastapi.responses import JSONResponse
    return JSONResponse({'success': False, **exc.to_dict()}, status_code=428)
