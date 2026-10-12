"""
SAJHA MCP Server — plumbing shared by the open data tools of P2 and P3 (Open Data Tools §1, §4).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Three rules of Open Data Tools §1 live here so that each source module stays small:

* **Keys** come from an environment variable only (:func:`env_key`); a tool config may carry
  ``"api_key": "${NAME_API_KEY:}"`` so the live tool check can see that it is empty.
* **Rate limits** are shared by every worker: :func:`take_slot` takes a slot in a sliding window
  kept in the state store (``state.backend``), so all workers behind the organisation's one egress
  IP spend one budget. Results are cached by each tool's ``cache_ttl``.
* **Outbound**: :func:`get` and :func:`fetch` send every request through the outbound fetch guard
  and HTTP proxy (``sajha/core/outbound.py``) and turn transport failures into one-line
  ``ValueError`` messages; :func:`fetch` (with :func:`get_json` and :func:`post_json`) also turns an
  HTTP error status into one, where :func:`get` leaves the status to the caller.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Mapping, Optional

from sajha.core import outbound
from sajha.tools.base_mcp_tool import BaseMCPTool

USER_AGENT = 'SAJHA-MCP-Server (open data tools; https://github.com/ajsinha/sajhamcpserver)'
_PLACEHOLDERS = {'', 'demo', 'demo_key', 'none', 'changeme'}


def env_key(env: str, config: Optional[Mapping[str, Any]] = None, field: str = 'api_key') -> Optional[str]:
    """The key from the tool config's ``field`` (already resolved from the environment by the
    registry) or the environment variable ``env``; None when neither holds a real value."""
    for candidate in ((config or {}).get(field), os.environ.get(env)):
        if isinstance(candidate, str):
            value = candidate.strip()
            if value and not value.startswith('${') and value.lower() not in _PLACEHOLDERS:
                return value
    return None


def take_slot(key: str, limit: int, window: float, wait: float, label: str) -> None:
    """Wait up to ``wait`` seconds for a slot in the shared window ``key`` (``limit`` requests per
    ``window`` seconds across every worker); raise when the budget stays used up."""
    from sajha.core.state import get_state_store
    store = get_state_store()
    deadline = time.monotonic() + wait
    while True:
        recorded, _ = store.window_add(key, window, limit)
        if recorded:
            return
        if time.monotonic() >= deadline:
            raise ValueError(f'{label} request budget ({limit} per {window:g} s, shared by every worker) is '
                             f'used up; try again later')
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())) or 0.05)


def get(url: str, label: str, *, params: Any = None, headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0, max_bytes: int = 20 * 1024 * 1024, method: str = 'GET',
        json: Any = None) -> outbound.Response:
    """One guarded request; a transport failure becomes ``ValueError('<label>: ...')``.
    The HTTP status is left to the caller."""
    send = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
    send.update(headers or {})
    try:
        return outbound.request(method, url, params=params, headers=send, timeout=timeout,
                                max_bytes=max_bytes, json=json)
    except outbound.FetchTimeout:
        raise ValueError(f'{label} did not answer within {timeout:g} seconds')
    except (outbound.Refused, outbound.FetchError) as e:
        raise ValueError(f'{label}: request failed: {e}')


def fetch(label: str, method: str, url: str, *, params: Optional[Dict[str, Any]] = None,
          json: Any = None, headers: Optional[Dict[str, str]] = None, timeout: float = 30.0,
          accept: str = 'application/json') -> outbound.Response:
    """One guarded request. Raises ValueError with a readable message on a refusal, timeout or HTTP error."""
    send = {'User-Agent': USER_AGENT, 'Accept': accept}
    send.update(headers or {})
    if params:
        params = {k: v for k, v in params.items() if v not in (None, '')}
    try:
        r = outbound.request(method, url, params=params, json=json, headers=send, timeout=timeout)
    except outbound.FetchTimeout:
        raise ValueError(f'{label} did not answer within {timeout:g} seconds')
    except (outbound.Refused, outbound.FetchError) as e:
        raise ValueError(f'{label} request failed: {e}')
    if r.status_code == 429:
        raise ValueError(f'{label} answered HTTP 429 (rate limit): {r.text[:200].strip()}')
    if r.status_code >= 400:
        detail = ''
        try:
            body = r.json()
            if isinstance(body, dict):
                detail = body.get('message') or body.get('detail') or body.get('error') or ''
                if not isinstance(detail, str):
                    detail = str(detail)
        except Exception:
            detail = r.text[:200].strip()
        raise ValueError(f'{label} answered HTTP {r.status_code}{": " + detail[:300] if detail else ""}')
    return r


def get_json(label: str, url: str, **kw) -> Any:
    r = fetch(label, 'GET', url, **kw)
    try:
        return r.json()
    except ValueError:
        raise ValueError(f'{label} did not answer with JSON: {r.text[:200].strip()}')


def post_json(label: str, url: str, body: Dict[str, Any], **kw) -> Any:
    r = fetch(label, 'POST', url, json=body, **kw)
    try:
        return r.json()
    except ValueError:
        raise ValueError(f'{label} did not answer with JSON: {r.text[:200].strip()}')


def number(value: Any) -> Optional[float]:
    """A float from an upstream value, None for blanks and markers (``.``, ``NA``, ``(NA)``, ``-``)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(',', '')
    if not s or s.lower() in ('.', '-', '--', 'na', 'n/a', '(na)', '(d)', 'nan', 'null', 'x', '..', '...'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


class OpenDataTool(BaseMCPTool):
    """Base for the open data tools: the schemas come from the JSON config."""

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {'type': 'object', 'properties': {}})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {'type': 'object'})
