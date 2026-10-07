"""
SAJHA Intelligence Layer — shared HTTP plumbing for the native providers.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Plain httpx: one client per provider built from its config (base URL, headers, proxy, TLS,
timeouts), JSON calls with vendor errors mapped onto the SAJHA taxonomy, and parsers for
Server-Sent Events and NDJSON streams. Every helper has an async twin (``build_async_client``,
``apost_json``, ``astream_post``, ``aiter_sse``, ``aiter_ndjson``) used by the native async
path of the HTTP providers.
"""

from __future__ import annotations

import email.utils
import json
import logging
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Callable, Dict, Iterator, Optional, Tuple

import httpx

from sajha.ai.llm.errors import (AuthenticationFailed, ContentFiltered, ContextTooLong, InvalidRequest,
                                 LLMError, ProviderUnavailable, RateLimited, UnsupportedFeature)

logger = logging.getLogger(__name__)

CONTEXT_MARKERS = ("context length", "context_length", "context window", "too long", "maximum context",
                   "prompt is too long", "token limit", "too many tokens", "input is too long",
                   "reduce the length", "exceeds the maximum")
FILTER_MARKERS = ("content_filter", "content filter", "content management policy", "responsible ai",
                  "safety", "blocked", "guardrail")


def _client_kwargs(config, base_url: str, headers: Optional[Dict[str, str]], transport: Any) -> Dict[str, Any]:
    verify: Any = config.verify_tls
    if config.verify_tls and config.ca_bundle:
        verify = config.ca_bundle
    timeout = httpx.Timeout(config.read_timeout_s, connect=config.connect_timeout_s)
    hdrs = {"user-agent": "sajha-intelligence/1"}
    hdrs.update(headers or {})
    hdrs.update(config.extra_headers or {})
    from sajha.observability.tracing import httpx_hooks
    kwargs: Dict[str, Any] = dict(base_url=base_url, headers=hdrs, timeout=timeout,
                                  verify=verify, follow_redirects=True,
                                  event_hooks=httpx_hooks())     # W3C traceparent on every request
    if transport is not None:
        kwargs["transport"] = transport
    elif config.proxy:
        kwargs["proxy"] = config.proxy
    return kwargs


def build_client(config, *, base_url: str = "", headers: Optional[Dict[str, str]] = None,
                 transport: Optional[httpx.BaseTransport] = None) -> httpx.Client:
    return httpx.Client(**_client_kwargs(config, base_url, headers, transport))


def build_async_client(config, *, base_url: str = "", headers: Optional[Dict[str, str]] = None,
                       transport: Any = None) -> httpx.AsyncClient:
    kw = _client_kwargs(config, base_url, headers, transport)
    from sajha.observability.tracing import httpx_hooks
    kw["event_hooks"] = httpx_hooks(asynchronous=True)
    if transport is not None and not hasattr(transport, "handle_async_request"):
        kw.pop("transport")
    return httpx.AsyncClient(**kw)


def parse_retry_after(headers) -> Optional[float]:
    if headers is None:
        return None
    ms = headers.get("retry-after-ms")
    if ms:
        try:
            return float(ms) / 1000.0
        except ValueError:
            pass
    ra = headers.get("retry-after")
    if not ra:
        return None
    try:
        return float(ra)
    except ValueError:
        try:
            dt = email.utils.parsedate_to_datetime(ra)
            return max(0.0, dt.timestamp() - time.time())
        except Exception:
            return None


def error_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except Exception:
        return (resp.text or "")[:500]
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            parts = [str(err.get(k)) for k in ("type", "code", "status", "message") if err.get(k)]
            return " ".join(parts)[:500] or json.dumps(body)[:500]
        if isinstance(err, str):
            return (err + " " + str(body.get("message", "")))[:500]
        if isinstance(body.get("message"), str):
            return body["message"][:500]
    return json.dumps(body)[:500]


def map_http_error(resp: httpx.Response, provider: str, model: str = "") -> LLMError:
    status = resp.status_code
    text = error_text(resp)
    low = text.lower()
    kw = dict(provider=provider, model=model, status=status)
    msg = f"{provider} HTTP {status}: {text}"
    if status == 429 or (status in (400, 403) and ("rate limit" in low or "quota" in low)):
        return RateLimited(msg, retry_after=parse_retry_after(resp.headers), **kw)
    if status in (401, 403):
        return AuthenticationFailed(msg, **kw)
    if status == 404:
        return UnsupportedFeature(msg, **kw)          # unknown model / deployment -> next candidate
    if status == 413 or (400 <= status < 500 and any(m in low for m in CONTEXT_MARKERS)):
        return ContextTooLong(msg, **kw)
    if 400 <= status < 500 and any(m in low for m in FILTER_MARKERS):
        return ContentFiltered(msg, **kw)
    if status >= 500 or status in (408, 409):
        return ProviderUnavailable(msg, **kw)
    return InvalidRequest(msg, **kw)


def _transport_error(e: Exception, provider: str, model: str) -> LLMError:
    if isinstance(e, httpx.TimeoutException):
        return ProviderUnavailable(f"{provider}: timeout ({e.__class__.__name__})", provider=provider, model=model)
    return ProviderUnavailable(f"{provider}: connection failed ({e.__class__.__name__}: {e})",
                               provider=provider, model=model)


@contextmanager
def transport_errors(provider: str, model: str = ""):
    """Translate httpx transport failures into ProviderUnavailable."""
    try:
        yield
    except LLMError:
        raise
    except (httpx.TimeoutException, httpx.TransportError) as e:
        raise _transport_error(e, provider, model) from None


@asynccontextmanager
async def atransport_errors(provider: str, model: str = ""):
    try:
        yield
    except LLMError:
        raise
    except (httpx.TimeoutException, httpx.TransportError) as e:
        raise _transport_error(e, provider, model) from None


def post_json(client: httpx.Client, url: str, payload: Dict[str, Any], *, provider: str, model: str = "",
              params: Optional[Dict[str, str]] = None, headers: Optional[Dict[str, str]] = None,
              classify: Optional[Callable[[httpx.Response], Optional[LLMError]]] = None) -> Dict[str, Any]:
    with transport_errors(provider, model):
        resp = client.post(url, json=payload, params=params, headers=headers)
    if resp.status_code >= 400:
        err = classify(resp) if classify else None
        raise err or map_http_error(resp, provider, model)
    try:
        return resp.json()
    except Exception:
        raise ProviderUnavailable(f"{provider}: non-JSON response", provider=provider, model=model)


async def apost_json(client: httpx.AsyncClient, url: str, payload: Dict[str, Any], *, provider: str,
                     model: str = "", params: Optional[Dict[str, str]] = None,
                     headers: Optional[Dict[str, str]] = None,
                     classify: Optional[Callable[[httpx.Response], Optional[LLMError]]] = None) -> Dict[str, Any]:
    async with atransport_errors(provider, model):
        resp = await client.post(url, json=payload, params=params, headers=headers)
    if resp.status_code >= 400:
        err = classify(resp) if classify else None
        raise err or map_http_error(resp, provider, model)
    try:
        return resp.json()
    except Exception:
        raise ProviderUnavailable(f"{provider}: non-JSON response", provider=provider, model=model)


def get_json(client: httpx.Client, url: str, *, provider: str, timeout: Optional[float] = None,
             params: Optional[Dict[str, str]] = None) -> Any:
    with transport_errors(provider):
        resp = client.get(url, params=params, timeout=timeout) if timeout else client.get(url, params=params)
    if resp.status_code >= 400:
        raise map_http_error(resp, provider)
    return resp.json()


@contextmanager
def stream_post(client: httpx.Client, url: str, payload: Dict[str, Any], *, provider: str, model: str = "",
                params: Optional[Dict[str, str]] = None, headers: Optional[Dict[str, str]] = None,
                classify: Optional[Callable[[httpx.Response], Optional[LLMError]]] = None):
    with transport_errors(provider, model):
        with client.stream("POST", url, json=payload, params=params, headers=headers) as resp:
            if resp.status_code >= 400:
                resp.read()
                err = classify(resp) if classify else None
                raise err or map_http_error(resp, provider, model)
            yield resp


@asynccontextmanager
async def astream_post(client: httpx.AsyncClient, url: str, payload: Dict[str, Any], *, provider: str,
                       model: str = "", params: Optional[Dict[str, str]] = None,
                       headers: Optional[Dict[str, str]] = None,
                       classify: Optional[Callable[[httpx.Response], Optional[LLMError]]] = None):
    async with atransport_errors(provider, model):
        async with client.stream("POST", url, json=payload, params=params, headers=headers) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                err = classify(resp) if classify else None
                raise err or map_http_error(resp, provider, model)
            yield resp


class SSEParser:
    """Incremental Server-Sent Events parser: feed lines, get (event, data) pairs."""

    def __init__(self):
        self.event, self.data = "", []

    def feed(self, line: str) -> Optional[Tuple[str, str]]:
        if line == "":
            out = (self.event or "message", "\n".join(self.data)) if self.data else None
            self.event, self.data = "", []
            return out
        if line.startswith(":"):
            return None
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            self.event = value
        elif field == "data":
            self.data.append(value)
        return None

    def close(self) -> Optional[Tuple[str, str]]:
        return (self.event or "message", "\n".join(self.data)) if self.data else None


def iter_sse(resp: httpx.Response) -> Iterator[Tuple[str, str]]:
    """Yield (event, data) pairs from a Server-Sent Events response."""
    p = SSEParser()
    for line in resp.iter_lines():
        out = p.feed(line)
        if out:
            yield out
    out = p.close()
    if out:
        yield out


async def aiter_sse(resp: httpx.Response) -> AsyncIterator[Tuple[str, str]]:
    p = SSEParser()
    async for line in resp.aiter_lines():
        out = p.feed(line)
        if out:
            yield out
    out = p.close()
    if out:
        yield out


async def aiter_ndjson(resp: httpx.Response) -> AsyncIterator[Dict[str, Any]]:
    async for line in resp.aiter_lines():
        line = line.strip()
        if line:
            yield json.loads(line)


def iter_ndjson(resp: httpx.Response) -> Iterator[Dict[str, Any]]:
    for line in resp.iter_lines():
        line = line.strip()
        if line:
            yield json.loads(line)


def safe_json_loads(s: str) -> dict:
    if not s:
        return {}
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {"value": v}
    except Exception:
        return {"_raw": s}
