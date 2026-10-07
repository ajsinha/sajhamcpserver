"""
SAJHA MCP Server — OpenTelemetry: the OTLP exporter, spans, and W3C trace context.

Off unless ``observability.otel.enabled`` (or the standard ``OTEL_SDK_DISABLED=false``
with an ``OTEL_EXPORTER_OTLP_ENDPOINT``) and the SDK is installed
(``pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http``, or ``-grpc``).
The standard ``OTEL_*`` variables win over the YAML keys. When off, :func:`span` yields
``None`` and costs one check, so instrumented code needs no guards.

Spans: HTTP (middleware) → MCP (parent: ``_meta.traceparent`` when the client sent one)
→ tool (``execute_with_tracking``) → LLM (the gateway's ``llm.chat``). Outbound calls carry
the context on (:func:`inject`, :func:`httpx_hooks`), with or without the SDK.
Design: docs/architecture/Observability.md, section 3.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import contextvars
import logging
import os
import re
import secrets
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple

from sajha.observability import settings as S

logger = logging.getLogger(__name__)

_state: Dict[str, Any] = {'initialised': False, 'tracer': None, 'meter': None, 'instruments': {},
                          'tracer_provider': None, 'meter_provider': None, 'reason': 'not initialised'}
_lock = threading.Lock()


def _env(name: str) -> Optional[str]:
    v = os.environ.get(name)
    return v if v not in (None, '') else None


def wanted() -> bool:
    """Is OpenTelemetry export asked for (YAML key or the standard environment)?"""
    if (_env('OTEL_SDK_DISABLED') or '').lower() == 'true':
        return False
    if S.get_bool('observability.otel.enabled', False):
        return True
    return (_env('OTEL_SDK_DISABLED') or '').lower() == 'false' and bool(_env('OTEL_EXPORTER_OTLP_ENDPOINT'))


def _headers() -> Optional[Dict[str, str]]:
    if _env('OTEL_EXPORTER_OTLP_HEADERS'):
        return None                       # the exporter reads the environment itself
    raw = S.get_str('observability.otel.headers', '')
    out = {}
    for part in raw.split(','):
        if '=' in part:
            k, v = part.split('=', 1)
            out[k.strip()] = v.strip()
    return out or None


def _endpoint(signal: str, protocol: str) -> Optional[str]:
    if _env(f'OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT') or _env('OTEL_EXPORTER_OTLP_ENDPOINT'):
        return None                       # the exporter reads (and completes) the environment itself
    ep = S.get_str('observability.otel.endpoint', '').strip()
    if not ep:
        return None
    if protocol.startswith('http'):
        return ep.rstrip('/') + f'/v1/{signal}'
    return ep


def service_name() -> str:
    if _env('OTEL_SERVICE_NAME'):
        return _env('OTEL_SERVICE_NAME')
    for part in (_env('OTEL_RESOURCE_ATTRIBUTES') or '').split(','):
        k, _, v = part.partition('=')
        if k.strip() == 'service.name' and v.strip():
            return v.strip()
    return S.get_str('observability.otel.service_name', 'sajha-mcp-server') or 'sajha-mcp-server'


def init_tracing(force: bool = False) -> bool:
    """Install the tracer and meter providers with OTLP exporters; True when tracing is live."""
    with _lock:
        if _state['initialised'] and not force:
            return _state['tracer'] is not None
        _state['initialised'] = True
        if not wanted():
            _state['reason'] = 'off (observability.otel.enabled is false)'
            return False
        try:
            from opentelemetry import metrics as otel_metrics
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
        except ImportError:
            _state['reason'] = 'the OpenTelemetry SDK is not installed (pip install opentelemetry-sdk)'
            logger.warning(f'OpenTelemetry: {_state["reason"]}; running without tracing')
            return False
        from sajha.core.config import get_settings
        protocol = (_env('OTEL_EXPORTER_OTLP_PROTOCOL')
                    or S.get_str('observability.otel.protocol', 'http/protobuf')).strip().lower()
        resource = Resource.create({'service.name': service_name(),
                                    'service.version': get_settings().app_version})
        try:
            ratio = float(_env('OTEL_TRACES_SAMPLER_ARG') or S.get_float('observability.otel.sample_ratio', 1.0))
        except ValueError:
            ratio = 1.0
        traces_on = S.get_bool('observability.otel.traces', True) and (_env('OTEL_TRACES_EXPORTER') or '') != 'none'
        metrics_on = S.get_bool('observability.otel.metrics', True) and (_env('OTEL_METRICS_EXPORTER') or '') != 'none'
        try:
            if traces_on:
                if protocol == 'grpc':
                    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                else:
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                kw = {k: v for k, v in (('endpoint', _endpoint('traces', protocol)), ('headers', _headers()))
                      if v is not None}
                tp = TracerProvider(resource=resource, sampler=ParentBased(TraceIdRatioBased(max(0.0, min(1.0, ratio)))))
                tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**kw)))
                trace.set_tracer_provider(tp)
                _state['tracer_provider'] = tp
                _state['tracer'] = trace.get_tracer('sajha')
            if metrics_on:
                from opentelemetry.sdk.metrics import MeterProvider
                from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
                if protocol == 'grpc':
                    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
                else:
                    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
                kw = {k: v for k, v in (('endpoint', _endpoint('metrics', protocol)), ('headers', _headers()))
                      if v is not None}
                mp = MeterProvider(resource=resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(**kw))])
                otel_metrics.set_meter_provider(mp)
                _state['meter_provider'] = mp
                _state['meter'] = otel_metrics.get_meter('sajha')
        except ImportError as e:
            _state['reason'] = f'the OTLP exporter is not installed ({e.name}); pip install opentelemetry-exporter-otlp'
            logger.warning(f'OpenTelemetry: {_state["reason"]}')
            return _state['tracer'] is not None
        _state['reason'] = f'exporting via OTLP ({protocol}) as {service_name()}'
        logger.info(f'  OpenTelemetry: {_state["reason"]} (traces {"on" if traces_on else "off"}, '
                    f'metrics {"on" if metrics_on else "off"})')
        return _state['tracer'] is not None


def install(tracer_provider=None, meter_provider=None) -> None:
    """Use the given SDK providers (tests: an in-memory exporter)."""
    with _lock:
        _state['initialised'] = True
        _state['tracer_provider'] = tracer_provider
        _state['tracer'] = tracer_provider.get_tracer('sajha') if tracer_provider is not None else None
        _state['meter_provider'] = meter_provider
        _state['meter'] = meter_provider.get_meter('sajha') if meter_provider is not None else None
        _state['instruments'] = {}
        _state['reason'] = 'installed'


def shutdown() -> None:
    for key in ('tracer_provider', 'meter_provider'):
        p = _state.get(key)
        if p is not None:
            try:
                p.shutdown()
            except Exception:
                pass


def tracer():
    return _state['tracer']


def status() -> Dict[str, Any]:
    return {'enabled': _state['tracer'] is not None or _state['meter'] is not None, 'detail': _state['reason']}


def _parent_context(traceparent: Optional[str], tracestate: Optional[str] = None,
                    carrier: Optional[Mapping[str, str]] = None):
    try:
        from opentelemetry.propagate import extract
    except ImportError:
        return None
    if traceparent:
        c = {'traceparent': traceparent}
        if tracestate:
            c['tracestate'] = tracestate
        return extract(c)
    if carrier is not None:
        return extract({k.lower(): v for k, v in carrier.items()})
    return None


# ── W3C trace context without the SDK ───────────────────────────────
#
# With OpenTelemetry off, SAJHA still continues an inbound ``traceparent`` (HTTP header or
# MCP ``_meta.traceparent``), starts one for a request that has none, and sends it on its
# own outbound calls (:func:`inject`), so a trace id reaches the audit record and the
# services SAJHA calls either way. With OpenTelemetry on, the live span's context wins.

_TP = re.compile(r'^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$')
# (trace id, our span id, flags, tracestate) of the current request, when OTel is off
_w3c: contextvars.ContextVar[Optional[Tuple[str, str, str, str]]] = contextvars.ContextVar('sajha_w3c', default=None)


def parse_traceparent(value: Any) -> Optional[Tuple[str, str, str]]:
    """(trace id, parent id, flags) of a valid version-00 ``traceparent``, else None."""
    if not isinstance(value, str):
        return None
    m = _TP.match(value.strip().lower())
    if not m or m.group(1) == 'ff' or m.group(2) == '0' * 32 or m.group(3) == '0' * 16:
        return None
    return m.group(2), m.group(3), m.group(4)


def _new_id(n: int) -> str:
    return secrets.token_hex(n)


def _carrier_get(carrier: Optional[Mapping[str, str]], name: str) -> Optional[str]:
    if not carrier:
        return None
    for k, v in carrier.items():
        if str(k).lower() == name:
            return v
    return None


def current_traceparent() -> Optional[str]:
    """The ``traceparent`` to send on an outbound call made now; None outside any request."""
    try:
        if _state['tracer'] is not None:
            from opentelemetry import trace
            sc = trace.get_current_span().get_span_context()
            if sc is not None and sc.is_valid:
                return f'00-{sc.trace_id:032x}-{sc.span_id:016x}-{int(sc.trace_flags):02x}'
    except Exception:
        pass
    ctx = _w3c.get()
    return f'00-{ctx[0]}-{ctx[1]}-{ctx[2]}' if ctx else None


def current_trace_id() -> str:
    """The current trace id (32 hex), or '' outside any request."""
    tp = current_traceparent()
    return tp[3:35] if tp else ''


def current_tracestate() -> Optional[str]:
    try:
        if _state['tracer'] is not None:
            from opentelemetry import trace
            sc = trace.get_current_span().get_span_context()
            if sc is not None and sc.is_valid:
                ts = sc.trace_state.to_header() if sc.trace_state else ''
                return ts or None
    except Exception:
        pass
    ctx = _w3c.get()
    return (ctx[3] or None) if ctx else None


def inject(headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Add the current ``traceparent`` (and ``tracestate``) to ``headers`` (created when None)
    unless the caller already set one; returns the dict. A no-op outside any request."""
    h = headers if headers is not None else {}
    if any(str(k).lower() == 'traceparent' for k in h):
        return h
    tp = current_traceparent()
    if tp:
        h['traceparent'] = tp
        ts = current_tracestate()
        if ts:
            h['tracestate'] = ts
    return h


def httpx_hooks(asynchronous: bool = False) -> Dict[str, list]:
    """``event_hooks`` for an httpx client that adds the trace context to every request it
    sends. The context is read when the request is sent, so a long-lived client is fine."""
    def _on_request(request):
        if 'traceparent' not in request.headers:
            for k, v in inject({}).items():
                request.headers[k] = v
    if not asynchronous:
        return {'request': [_on_request]}

    async def _on_request_async(request):
        _on_request(request)
    return {'request': [_on_request_async]}


@contextmanager
def _w3c_scope(traceparent: Optional[str], tracestate: Optional[str], carrier: Optional[Mapping[str, str]],
               start: bool) -> Iterator[None]:
    """OTel off: continue an inbound context (or start one for a server span), as our own span."""
    parsed = parse_traceparent(traceparent if traceparent else _carrier_get(carrier, 'traceparent'))
    token = None
    if parsed is not None:
        ts = tracestate if traceparent else _carrier_get(carrier, 'tracestate')
        token = _w3c.set((parsed[0], _new_id(8), parsed[2], (ts or '')[:512]))
    elif start and _w3c.get() is None:
        token = _w3c.set((_new_id(16), _new_id(8), '01', ''))
    try:
        yield
    finally:
        if token is not None:
            try:
                _w3c.reset(token)
            except (ValueError, RuntimeError):
                pass


@contextmanager
def span(name: str, attributes: Optional[Dict[str, Any]] = None, *, traceparent: Optional[str] = None,
         tracestate: Optional[str] = None, carrier: Optional[Mapping[str, str]] = None,
         kind: str = 'internal', ensure_trace: bool = False) -> Iterator[Any]:
    """A span when tracing is live, else None. ``traceparent``/``carrier`` set the parent.
    With tracing off, the W3C context still follows the request (:func:`current_traceparent`);
    a server span, or one with ``ensure_trace``, starts a trace when there is none yet."""
    t = _state['tracer']
    if t is None:
        start = kind == 'server' or ensure_trace
        if traceparent is None and carrier is None and not (start and _w3c.get() is None):
            yield None
            return
        with _w3c_scope(traceparent, tracestate, carrier, start):
            yield None
        return
    from opentelemetry.trace import SpanKind
    ctx = _parent_context(traceparent, tracestate, carrier)
    attrs = {k: v for k, v in (attributes or {}).items() if v is not None}
    sk = {'server': SpanKind.SERVER, 'client': SpanKind.CLIENT}.get(kind, SpanKind.INTERNAL)
    with t.start_as_current_span(name, context=ctx, kind=sk, attributes=attrs) as sp:
        yield sp


def set_attrs(sp: Any, **attrs: Any) -> None:
    if sp is None:
        return
    try:
        for k, v in attrs.items():
            if v is not None:
                sp.set_attribute(k.replace('__', '.'), v)
    except Exception:
        pass


def set_error(sp: Any, message: str) -> None:
    if sp is None:
        return
    try:
        from opentelemetry.trace import StatusCode
        sp.set_status(StatusCode.ERROR, (message or '')[:200])
    except Exception:
        pass


def record_metric(name: str, kind: str, value: float, attrs: Dict[str, Any]) -> None:
    """Mirror an instrumentation point into OTel metrics (counter or histogram)."""
    meter = _state['meter']
    if meter is None:
        return
    inst = _state['instruments'].get(name)
    if inst is None:
        inst = meter.create_histogram(name) if kind == 'histogram' else meter.create_counter(name)
        _state['instruments'][name] = inst
    clean = {k: v for k, v in attrs.items() if v is not None}
    if kind == 'histogram':
        inst.record(value, clean)
    elif value:
        inst.add(value, clean)
