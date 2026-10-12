"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Web crawler: JavaScript rendering (Playwright, optional) and non-HTML documents (PDF, text).

JavaScript rendering is off unless ``tools.webcrawler.javascript.enabled`` is true and Playwright
with its Chromium is installed (``pip install playwright`` then ``python -m playwright install
chromium``); a call then asks for it with ``render_js: true``. The browser never connects to anything
itself:

* every request the page makes (the navigation, each redirect target, scripts, styles, XHR/fetch,
  frames, popups) is intercepted by a context route and **fetched by SAJHA** through the outbound fetch
  guard (sajha/core/outbound.py: blocked addresses refused, the connection pinned to the vetted
  address, ``tools.outbound.proxy`` honoured), then handed to the browser with ``route.fulfill``;
  a refused destination is aborted and listed in ``blocked``;
* Chromium is pointed at a proxy that does not exist (loopback not bypassed) and runs with
  ``--host-resolver-rules=MAP * ~NOTFOUND``, so a request that escaped the route could reach nothing;
  service workers are blocked; WebSockets are closed;
* images, media and fonts are not fetched (``block_resource_types``); at most ``max_requests``
  requests and ``max_bytes`` bytes per page, ``timeout_seconds`` for the whole render, and at most
  ``max_concurrent`` renders at once per process. ``crawl_url`` renders at most ``max_pages`` pages
  per call.

Non-HTML answers are turned into text the crawler's HTML parsing reads: a PDF (``pypdf``) becomes a
small HTML document with the PDF's title, the text of its first ``pdf_max_pages`` pages and its link
annotations as anchors; ``text/plain``, ``text/markdown`` and ``text/csv`` are returned as they are.

Docs: docs/tools/search/Web Crawler Tool Reference Guide.md
"""

import html
import io
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sajha.core import outbound

logger = logging.getLogger(__name__)

TEXT_TYPES = ('text/plain', 'text/markdown', 'text/csv', 'text/x-markdown')
PDF_MAX_PAGES = 50
PDF_MAX_CHARS = 200_000
#: request headers the browser sends that SAJHA passes on (never Host, lengths, or hop-by-hop ones)
FORWARD_REQUEST_HEADERS = ('user-agent', 'accept', 'accept-language', 'content-type', 'referer', 'cookie',
                           'x-requested-with', 'origin')
DEAD_PROXY = 'http://127.0.0.1:9'        # the discard port: nothing listens, nothing is proxied
DROP_RESPONSE_HEADERS = ('content-encoding', 'content-length', 'transfer-encoding', 'connection',
                         'keep-alive', 'strict-transport-security', 'alt-svc')


class RenderUnavailable(RuntimeError):
    """JavaScript rendering is switched off, or Playwright / its browser is not installed."""


@dataclass
class RenderSettings:
    enabled: bool = False
    timeout_seconds: float = 20.0
    max_requests: int = 100
    max_bytes: int = 20 * 1024 * 1024
    max_pages: int = 10
    max_concurrent: int = 2
    block_resource_types: List[str] = field(default_factory=lambda: ['image', 'media', 'font'])
    pdf_max_pages: int = PDF_MAX_PAGES


def settings() -> RenderSettings:
    from sajha.core.config import _get, parse_bool, parse_list

    def num(key, default, cast=int):
        try:
            return cast(_get(f'tools.webcrawler.javascript.{key}', default))
        except (TypeError, ValueError):
            return default
    blocked = _get('tools.webcrawler.javascript.block_resource_types', None)
    return RenderSettings(
        enabled=parse_bool(_get('tools.webcrawler.javascript.enabled', False), False),
        timeout_seconds=max(1.0, num('timeout_seconds', 20.0, float)),
        max_requests=max(1, num('max_requests', 100)),
        max_bytes=max(1024, num('max_bytes', 20 * 1024 * 1024)),
        max_pages=max(1, num('max_pages', 10)),
        max_concurrent=max(1, num('max_concurrent', 2)),
        block_resource_types=(['image', 'media', 'font'] if blocked is None
                              else [str(x) for x in (blocked if isinstance(blocked, list) else parse_list(blocked))]),
        pdf_max_pages=max(1, num('pdf_max_pages', PDF_MAX_PAGES)))


# ── non-HTML documents ──────────────────────────────────────────────

def media_type(content_type: str) -> str:
    return (content_type or '').split(';', 1)[0].strip().lower()


def is_pdf(content: bytes, content_type: str) -> bool:
    return media_type(content_type) == 'application/pdf' or (content or b'')[:5] == b'%PDF-'


def pdf_to_html(content: bytes, max_pages: int = PDF_MAX_PAGES) -> str:
    """A PDF as a small HTML document: title, each page's text in a <pre>, link annotations as anchors."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ValueError('this URL is a PDF and pypdf is not installed (pip install pypdf)')
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as e:
        raise ValueError(f'the PDF could not be read: {e}')
    title = ''
    try:
        title = str((reader.metadata or {}).get('/Title') or '')
    except Exception:
        pass
    parts, links, chars = [], [], 0
    for i, page in enumerate(reader.pages):
        if i >= max_pages or chars >= PDF_MAX_CHARS:
            parts.append(f'<p>[{len(reader.pages) - i} more page(s) not read]</p>')
            break
        try:
            text = page.extract_text() or ''
        except Exception:
            text = ''
        text = text[:PDF_MAX_CHARS - chars]
        chars += len(text)
        parts.append(f'<pre>{html.escape(text, quote=False)}</pre>')
        try:
            for annot in page.get('/Annots') or []:
                obj = annot.get_object()
                uri = ((obj.get('/A') or {}).get('/URI')) if obj.get('/Subtype') == '/Link' else None
                if uri:
                    links.append(str(uri))
        except Exception:
            pass
    anchors = ''.join(f'<a href="{html.escape(u)}">{html.escape(u)}</a>' for u in dict.fromkeys(links))
    return (f'<html><head><title>{html.escape(title)}</title></head><body>'
            f'{"".join(parts)}{anchors}</body></html>')


def document_text(content: bytes, content_type: str, pdf_max_pages: int = PDF_MAX_PAGES) -> str:
    """The text the crawler parses for a response body: HTML as is, a PDF converted, text as is."""
    if is_pdf(content, content_type):
        return pdf_to_html(content, pdf_max_pages)
    return content.decode('utf-8', errors='ignore')


# ── JavaScript rendering ────────────────────────────────────────────

@dataclass
class Rendered:
    html: str
    status_code: int
    content_type: str
    final_url: str
    requests: int = 0
    blocked: List[str] = field(default_factory=list)
    truncated: bool = False


_slots_lock = threading.Lock()
_slots: Optional[threading.BoundedSemaphore] = None


def _semaphore(n: int) -> threading.BoundedSemaphore:
    global _slots
    with _slots_lock:
        if _slots is None or getattr(_slots, '_sajha_n', None) != n:
            _slots = threading.BoundedSemaphore(n)
            _slots._sajha_n = n
        return _slots


def available() -> Optional[str]:
    """None when rendering can run, else why not."""
    if not settings().enabled:
        return 'JavaScript rendering is off (tools.webcrawler.javascript.enabled)'
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return 'JavaScript rendering needs Playwright (pip install playwright; python -m playwright install chromium)'
    return None


def render(url: str, user_agent: str, timeout: Optional[float] = None, cfg: Optional[RenderSettings] = None) -> Rendered:
    """Load ``url`` in headless Chromium with every request fetched through the outbound guard."""
    cfg = cfg or settings()
    if not cfg.enabled:
        raise RenderUnavailable('JavaScript rendering is off (tools.webcrawler.javascript.enabled)')
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        raise RenderUnavailable('JavaScript rendering needs Playwright (pip install playwright; '
                                'python -m playwright install chromium)')
    outbound.vet(url)                         # the start URL is refused before a browser starts
    budget = min(float(timeout or cfg.timeout_seconds), cfg.timeout_seconds)
    slots = _semaphore(cfg.max_concurrent)
    if not slots.acquire(timeout=budget):
        raise RuntimeError('too many pages are being rendered; try again')
    try:
        box: Dict[str, Any] = {}
        # Playwright's sync API refuses to run on a thread with an asyncio loop: use a thread of our own
        t = threading.Thread(target=_render_thread, args=(url, user_agent, budget, cfg, box),
                             name='sajha-crawler-render', daemon=True)
        t.start()
        t.join(budget + 15)
        if t.is_alive():
            raise RuntimeError(f'rendering {outbound.safe_url(url)} did not finish')
        if 'error' in box:
            raise box['error']
        return box['result']
    finally:
        slots.release()


def _render_thread(url, user_agent, budget, cfg, box) -> None:
    try:
        box['result'] = _render(url, user_agent, budget, cfg)
    except BaseException as e:               # handed to the caller's thread
        box['error'] = e


def _render(url: str, user_agent: str, budget: float, cfg: RenderSettings) -> Rendered:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RenderUnavailable('JavaScript rendering needs Playwright (pip install playwright; '
                                'python -m playwright install chromium)')
    deadline = time.monotonic() + budget
    state = {'requests': 0, 'bytes': 0, 'blocked': [], 'truncated': False, 'main': None}

    def handler(route, request):
        try:
            _handle(route, request)
        except Exception as e:               # never leave a request hanging
            logger.debug(f'crawler render: {e}')
            try:
                route.abort('failed')
            except Exception:
                pass

    def _handle(route, request):
        rurl = request.url
        if request.resource_type in cfg.block_resource_types:
            return route.abort('blockedbyclient')
        if not rurl.startswith(('http://', 'https://')):
            return route.abort('blockedbyclient')
        remaining = deadline - time.monotonic()
        if remaining <= 0.2 or state['requests'] >= cfg.max_requests or state['bytes'] >= cfg.max_bytes:
            state['truncated'] = True
            return route.abort('blockedbyclient')
        state['requests'] += 1
        headers = {k: v for k, v in (request.headers or {}).items() if k.lower() in FORWARD_REQUEST_HEADERS}
        headers.setdefault('user-agent', user_agent)
        try:
            resp = outbound.request(request.method, rurl, headers=headers, data=request.post_data_buffer,
                                    timeout=max(0.5, min(remaining, 15.0)),
                                    max_bytes=max(1, cfg.max_bytes - state['bytes']))
        except outbound.Refused:
            state['blocked'].append(outbound.safe_url(rurl))
            return route.abort('blockedbyclient')
        except outbound.FetchError as e:
            logger.debug(f'crawler render: {outbound.safe_url(rurl)}: {e}')
            return route.abort('failed')
        state['bytes'] += len(resp.content or b'')
        out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in DROP_RESPONSE_HEADERS}
        if state['main'] is None and request.is_navigation_request() and request.frame == page.main_frame:
            state['main'] = (resp.status_code, resp.headers.get('content-type', ''), resp.url, resp.content or b'')
        return route.fulfill(status=resp.status_code, headers=out_headers, body=resp.content or b'')

    with sync_playwright() as p:
        # defence in depth: a request that escaped the route meets a proxy that does not exist (loopback
        # included) and a resolver that resolves nothing
        browser = p.chromium.launch(headless=True, proxy={'server': DEAD_PROXY},
                                    args=['--host-resolver-rules=MAP * ~NOTFOUND', '--proxy-bypass-list=<-loopback>',
                                          '--disable-background-networking', '--no-first-run', '--disable-sync'])
        try:
            context = browser.new_context(user_agent=user_agent, service_workers='block', accept_downloads=False,
                                          java_script_enabled=True)
            context.route('**/*', handler)
            if hasattr(context, 'route_web_socket'):
                context.route_web_socket('**/*', lambda ws: ws.close())
            page = context.new_page()
            page.set_default_timeout(max(1000, int(budget * 1000)))
            try:
                response = page.goto(url, wait_until='load', timeout=max(1000, int((deadline - time.monotonic()) * 1000)))
            except PlaywrightError as e:
                if state['main'] is None:
                    if state['blocked']:
                        raise outbound.Refused(f'refused: {outbound.safe_url(url)} (rendering)')
                    raise RuntimeError(f'the page did not load: {str(e).splitlines()[0][:200]}')
                response = None
            idle = min(3.0, deadline - time.monotonic())
            if idle > 0.2:
                try:
                    page.wait_for_load_state('networkidle', timeout=int(idle * 1000))
                except PlaywrightError:
                    pass                    # a page that keeps polling: take the DOM as it is
            status, ctype, final, body = state['main'] or (
                (response.status, (response.headers or {}).get('content-type', ''), response.url, b'') if response
                else (200, 'text/html', url, b''))
            if body and (is_pdf(body, ctype) or media_type(ctype) in TEXT_TYPES):
                html_text = document_text(body, ctype, cfg.pdf_max_pages)    # no script ran on a document
            else:
                html_text = page.content()
            return Rendered(html=html_text, status_code=int(status), content_type=ctype or 'text/html',
                            final_url=final or url, requests=state['requests'], blocked=list(state['blocked']),
                            truncated=state['truncated'])
        finally:
            browser.close()
