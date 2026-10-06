"""
SAJHA MCP Server — Slack tools that act as the caller (connected account ``slack``, a user token).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Web API ``chat.postMessage`` (https://api.slack.com/methods/chat.postMessage).  Slack
answers HTTP 200 with ``ok: false`` on errors; an ``invalid_auth``, ``token_revoked`` or
``token_expired`` error is treated as a rejected token (refresh once, then reconnect).
"""

from __future__ import annotations

from typing import Any, Dict

from sajha.accounts.tools.base import ConnectedAccountTool, ProviderAPIError

API = 'https://slack.com/api'
_AUTH_ERRORS = {'invalid_auth', 'not_authed', 'token_revoked', 'token_expired', 'account_inactive'}


class SlackPostMessageTool(ConnectedAccountTool):
    default_provider = 'slack'
    default_scopes = ('chat:write',)

    def is_auth_failure(self, response) -> bool:
        if response.status_code == 401:
            return True
        try:
            body = response.json()
        except ValueError:
            return False
        return isinstance(body, dict) and body.get('ok') is False and body.get('error') in _AUTH_ERRORS

    def run(self, a: Dict[str, Any]) -> Any:
        payload: Dict[str, Any] = {'channel': a['channel'], 'text': a['text']}
        if a.get('thread_ts'):
            payload['thread_ts'] = a['thread_ts']
        resp = self.api('POST', f'{API}/chat.postMessage', json_body=payload,
                        headers={'Content-Type': 'application/json; charset=utf-8'})
        body = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not body.get('ok'):
            raise ProviderAPIError('Slack', resp.status_code, str(body.get('error') or 'request failed'))
        msg = body.get('message') or {}
        return {'ok': True, 'channel': body.get('channel'), 'ts': body.get('ts'), 'text': msg.get('text', a['text'])}
