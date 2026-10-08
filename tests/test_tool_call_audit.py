# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Every tool call as a ``tool.call`` record in the tamper-evident audit chain
(sajha/audit/tool_calls.py; docs/architecture/Policy and Audit.md section 13), the deferred
chain flush that keeps the database off the call path, the W3C trace context with and
without the OpenTelemetry SDK (sajha/observability/tracing.py; Observability.md), and the
per-user tool result cache key (sajha/core/cache.py).
"""

from __future__ import annotations

import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine

from sajha import audit
from sajha.audit import tool_calls as TC
from sajha.audit.chain import ChainWriter, Signer
from sajha.audit.verify import verify
from sajha.observability import tracing
from sajha.observability.caller import Caller, reset as reset_caller, set_caller
from sajha.policy import context as pctx
from sajha.tools.base_mcp_tool import BaseMCPTool

TP = '00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01'


class Tool(BaseMCPTool):
    def __init__(self, name='tca_echo', fail=False, annotations=None, extra=None):
        cfg = {'name': name, 'description': 'audit test tool', 'inputSchema': {'type': 'object', 'properties': {}}}
        if annotations:
            cfg['annotations'] = annotations
        cfg.update(extra or {})
        super().__init__(cfg)
        self.fail = fail
        self.calls = 0
        self.seen_traceparent = None

    def get_input_schema(self):
        return self._input_schema

    def get_output_schema(self):
        return {}

    def execute(self, arguments):
        self.calls += 1
        self.seen_traceparent = tracing.current_traceparent()
        if self.fail:
            raise RuntimeError('upstream exploded')
        return {'n': self.calls}


@pytest.fixture(scope='module')
def signer():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption())
    return Signer(pem, 'tca-kid')


@pytest.fixture
def records():
    """An audit writer that only records (no database); default tool-call settings."""
    from sajha.core.state import set_state_store
    from sajha.core.state.memory import MemoryStateStore
    from sajha.policy.engine import PolicyEngine, set_engine
    from sajha.policy.loader import PolicySet
    got = []
    old = (audit._writer, audit._exporter)
    audit.set_writer(ChainWriter(store=False, anchor_interval=0, anchor_every=10 ** 9, on_record=got.append))
    audit._exporter = None
    set_engine(PolicyEngine(PolicySet()))
    set_state_store(MemoryStateStore())
    TC.set_settings(TC.Settings())
    yield got
    TC.set_settings(None)
    set_engine(None)
    set_state_store(None)
    audit._writer, audit._exporter = old


def calls(got):
    return [r for r in got if r['event'] == 'tool.call']


# ── what a record holds ─────────────────────────────────────────────

def test_every_call_is_recorded_with_who_what_outcome_and_hashed_arguments(records):
    t = Tool()
    tok = set_caller(Caller('alice', 'k-1', ('user',), 'apikey'))
    src = pctx.set_source('rest')
    try:
        t.execute_with_tracking({'email': 'a@b.example', 'n': 1})
    finally:
        pctx.reset_source(src)
        reset_caller(tok)
    [r] = calls(records)
    assert r['actor'] == {'user': 'alice', 'api_key': 'k-1', 'roles': ['user'], 'auth': 'apikey'}
    assert r['resource'] == {'type': 'tool', 'id': 'tca_echo'} and r['outcome'] == 'ok'
    d = r['details']
    assert d['source'] == 'rest' and d['duration_ms'] >= 0
    assert d['arguments_sha256'] == TC.arguments_digest({'n': 1, 'email': 'a@b.example'})
    assert 'a@b.example' not in str(r) and 'arguments' not in d
    assert len(d['trace_id']) == 32                     # a trace is started when none is current


def test_failures_and_the_error_are_recorded(records):
    t = Tool(fail=True)
    with pytest.raises(RuntimeError):
        t.execute_with_tracking({})
    [r] = calls(records)
    assert r['outcome'] == 'error' and 'upstream exploded' in r['details']['error']


def test_policy_denial_is_a_tool_call_record_too(records):
    import textwrap
    from sajha.policy.engine import PolicyEngine, set_engine
    from sajha.policy.errors import PolicyDenied
    from sajha.policy.loader import PolicySet
    from sajha.policy.model import parse_text
    ps = PolicySet()
    ps.set_policies([parse_text(textwrap.dedent('''
        rules:
          - id: no
            match: {tools: [tca_*]}
            effect: deny
            reason: not today
    '''), 'p', 'p.yaml')])
    set_engine(PolicyEngine(ps))
    with pytest.raises(PolicyDenied):
        Tool().execute_with_tracking({})
    events = [r['event'] for r in records]
    assert 'policy.deny' in events and calls(records)[0]['outcome'] == 'policy_denied'


def test_mcp_era_is_recorded(records):
    tok = pctx.ensure_era('2026-07-28')
    try:
        Tool().execute_with_tracking({})
    finally:
        pctx.reset_era(tok)
    assert calls(records)[0]['details']['era'] == '2026-07-28'


def test_redacted_arguments_opt_in(records):
    TC.set_settings(TC.Settings(arguments='redacted'))
    Tool().execute_with_tracking({'to': 'bob@example.com', 'password': 'hunter2', 'q': 'plain'})
    d = calls(records)[0]['details']
    assert d['arguments']['q'] == 'plain' and d['arguments']['password'] == '[REDACTED:secret]'
    assert 'bob@example.com' not in str(d) and 'hunter2' not in str(d)
    assert 'arguments_sha256' not in d


def test_arguments_none_mode(records):
    TC.set_settings(TC.Settings(arguments='none'))
    Tool().execute_with_tracking({'x': 1})
    d = calls(records)[0]['details']
    assert 'arguments' not in d and 'arguments_sha256' not in d


# ── volume control ──────────────────────────────────────────────────

def test_decide_rules():
    s = TC.Settings(success_sample_rate=0.0, exclude_tools=['noisy_*'],
                    sample_rates=[('fred_*', 0.5), ('*', 0.0)])
    assert TC.decide(s, 'calc_add', 'ok', False)[0] is False
    assert TC.decide(s, 'calc_add', 'error', False)[0] is True          # failures always
    assert TC.decide(s, 'noisy_x', 'policy_denied', False)[0] is True  # denials always
    assert TC.decide(s, 'noisy_x', 'ok', True)[0] is True              # destructive always
    assert TC.decide(s, 'noisy_x', 'ok', False)[2] == 'excluded'
    assert TC.decide(s, 'fred_gdp', 'ok', False, rand=lambda: 0.4) == (True, 0.5, '')
    assert TC.decide(s, 'fred_gdp', 'ok', False, rand=lambda: 0.6) == (False, 0.5, 'sampled')
    assert TC.decide(TC.Settings(include_tools=['a_*']), 'b_x', 'ok', False)[2] == 'excluded'
    assert TC.decide(TC.Settings(enabled=False), 'x', 'error', True)[0] is False


def test_sampled_and_excluded_successes_are_not_written(records):
    TC.set_settings(TC.Settings(success_sample_rate=0.0))
    Tool().execute_with_tracking({})
    Tool(annotations={'destructiveHint': True}, name='tca_delete').execute_with_tracking({})
    with pytest.raises(RuntimeError):
        Tool(fail=True).execute_with_tracking({})
    got = calls(records)
    assert [(r['resource']['id'], r['outcome']) for r in got] == [('tca_delete', 'ok'), ('tca_echo', 'error')]
    assert got[0]['details']['destructive'] is True


def test_settings_from_configuration(monkeypatch):
    monkeypatch.setenv('SAJHA_AUDIT_TOOL_CALLS_SUCCESS_SAMPLE_RATE', '0.25')
    monkeypatch.setenv('SAJHA_AUDIT_TOOL_CALLS_SAMPLE_RATES', 'fred_*=0.1, calc_*=0')
    monkeypatch.setenv('SAJHA_AUDIT_TOOL_CALLS_EXCLUDE_TOOLS', 'noisy_*')
    monkeypatch.setenv('SAJHA_AUDIT_TOOL_CALLS_ARGUMENTS', 'redacted')
    s = TC.load_settings()
    assert s.success_sample_rate == 0.25 and s.sample_rates == [('fred_*', 0.1), ('calc_*', 0.0)]
    assert s.exclude_tools == ['noisy_*'] and s.arguments == 'redacted' and s.enabled is True
    monkeypatch.setenv('SAJHA_AUDIT_TOOL_CALLS_ARGUMENTS', 'everything')
    assert TC.load_settings().arguments == 'hash'


# ── the chain: deferred storage, verification, export ───────────────

def test_deferred_records_are_stored_by_the_flusher_and_the_chain_verifies(tmp_path, signer):
    eng = create_engine(f'sqlite:///{tmp_path}/a.db')
    exported = []
    w = ChainWriter(engine=eng, anchor_every=7, anchor_interval=0, signer=signer, store=True,
                    on_record=exported.append)
    w.flush_interval = 0.05
    old = (audit._writer, audit._exporter)
    audit.set_writer(w)
    TC.set_settings(TC.Settings())
    try:
        w.append('login_success', actor={'user': 'x'})           # an ordinary, synchronous record
        for i in range(20):
            Tool().execute_with_tracking({'i': i})
        assert any(r['event'] == 'tool.call' for r in exported)  # SIEM export sees every record
        deadline = time.time() + 3
        while w.status()['pending'] and time.time() < deadline:
            time.sleep(0.02)
        assert w.status()['pending'] == 0                       # stored without anyone calling flush
        w.close()
    finally:
        TC.set_settings(None)
        audit._writer, audit._exporter = old
    r = verify(eng, keys={signer.kid: signer.public_key()})
    assert r['ok'], r
    from sajha.audit.chain import recent
    assert len(recent(eng, 100, event='tool.call')) == 20


def test_audit_overhead_per_call_is_small(records):
    """The record is hashed on the calling thread and stored later; measure the difference."""
    t = Tool()
    n = 400

    def run():
        t0 = time.perf_counter()
        for i in range(n):
            t.execute_with_tracking({'i': i, 'q': 'x' * 50})
        return (time.perf_counter() - t0) / n

    TC.set_settings(TC.Settings(enabled=False))
    run()
    off = min(run() for _ in range(3))
    TC.set_settings(TC.Settings())
    on = min(run() for _ in range(3))
    # generous bound for slow CI machines; the measured figure is in the CHANGELOG
    assert on - off < 0.002, f'audit adds {(on - off) * 1e6:.0f} us per call'


# ── trace context ───────────────────────────────────────────────────

def test_parse_and_inject_without_the_sdk():
    assert tracing.parse_traceparent(TP) == ('0af7651916cd43dd8448eb211c80319c', 'b7ad6b7169203331', '01')
    for bad in ('', 'junk', '00-' + '0' * 32 + '-b7ad6b7169203331-01', 'ff-' + TP[3:], None):
        assert tracing.parse_traceparent(bad) is None
    assert tracing.current_traceparent() is None and tracing.inject({}) == {}
    with tracing.span('x', traceparent=TP, tracestate='k=v'):
        tp = tracing.current_traceparent()
        assert tp.startswith('00-0af7651916cd43dd8448eb211c80319c-') and not tp.endswith('b7ad6b7169203331-01')
        h = tracing.inject({'Accept': 'x'})
        assert h['traceparent'] == tp and h['tracestate'] == 'k=v'
        assert tracing.inject({'TraceParent': 'mine'}) == {'TraceParent': 'mine'}   # caller's own wins
    assert tracing.current_traceparent() is None


def test_tool_call_continues_the_inbound_trace(records):
    t = Tool()
    with tracing.span('mcp tools/call', traceparent=TP):
        t.execute_with_tracking({})
    assert t.seen_traceparent[3:35] == '0af7651916cd43dd8448eb211c80319c'
    assert calls(records)[0]['details']['trace_id'] == '0af7651916cd43dd8448eb211c80319c'


def test_http_middleware_continues_or_starts_a_trace():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sajha.observability.middleware import ObservabilityMiddleware
    app = FastAPI()

    @app.get('/tp')
    def tp():
        return {'tp': tracing.current_traceparent()}
    app.add_middleware(ObservabilityMiddleware)
    c = TestClient(app)
    got = c.get('/tp', headers={'traceparent': TP}).json()['tp']
    assert got[3:35] == '0af7651916cd43dd8448eb211c80319c'
    fresh = c.get('/tp').json()['tp']
    assert tracing.parse_traceparent(fresh) is not None and fresh[3:35] != '0af7651916cd43dd8448eb211c80319c'


def test_outbound_httpx_clients_send_traceparent():
    import httpx
    seen = []

    def handler(request):
        seen.append(request.headers.get('traceparent'))
        return httpx.Response(200, json={})
    # the LLM providers' client builder and the connected-accounts client carry the hook
    from types import SimpleNamespace
    from sajha.ai.llm.http import build_client
    cfg = SimpleNamespace(verify_tls=True, ca_bundle=None, read_timeout_s=5, connect_timeout_s=5,
                          extra_headers={}, proxy=None)
    client = build_client(cfg, base_url='http://llm.example', transport=httpx.MockTransport(handler))
    client.get('/v1/models')                                   # outside any request: no header
    with tracing.span('x', traceparent=TP):
        client.get('/v1/models')
    from sajha.accounts import http as acc_http
    acc_http.set_transport(httpx.MockTransport(handler))
    try:
        with tracing.span('x', traceparent=TP):
            acc_http.client().get('http://idp.example/token')
    finally:
        acc_http.set_transport(None)
    assert seen[0] is None
    assert seen[1][3:35] == seen[2][3:35] == '0af7651916cd43dd8448eb211c80319c'


def test_webhook_notifier_sends_the_notifying_requests_trace():
    from sajha.core.webhooks import WebhookManager
    captured = {}
    m = WebhookManager()
    m.subscribe('e', 'http://hook.example/x')
    m._deliver = lambda event_type, url, payload, trace_headers=None: captured.update(trace_headers or {})
    with tracing.span('x', traceparent=TP):
        m.notify('e', {})
    deadline = time.time() + 2
    while not captured and time.time() < deadline:
        time.sleep(0.01)
    assert captured['traceparent'][3:35] == '0af7651916cd43dd8448eb211c80319c'


# ── per-user cache key ──────────────────────────────────────────────

@pytest.fixture
def tool_cache(tmp_path, monkeypatch):
    from sajha.core import cache as C
    c = C.ToolCache(cache_dir=str(tmp_path / 'cache'), enabled=True)
    monkeypatch.setattr(C, '_tool_cache', c)
    return c


def test_per_user_cache_never_serves_one_users_result_to_another(records, tool_cache):
    t = Tool(name='tca_cached', extra={'cache_ttl': 60, 'cache_per_user': True})
    for who in ('alice', 'bob', 'alice', 'bob'):
        tok = set_caller(Caller(who, '', ('user',), 'session'))
        try:
            out = t.execute_with_tracking({'q': 1})
        finally:
            reset_caller(tok)
        if who == 'alice':
            assert out == {'n': 1}
        else:
            assert out == {'n': 2}
    assert t.calls == 2
    assert [r['outcome'] for r in calls(records)] == ['ok', 'ok', 'cache_hit', 'cache_hit']


def test_shared_cache_by_default_and_federated_default(records, tool_cache, monkeypatch):
    from sajha.core.cache import cache_scope, is_per_user
    t = Tool(name='tca_shared', extra={'cache_ttl': 60})
    for who in ('alice', 'bob'):
        tok = set_caller(Caller(who, '', ('user',), 'session'))
        try:
            t.execute_with_tracking({'q': 1})
        finally:
            reset_caller(tok)
    assert t.calls == 1                                      # unchanged: shared across callers
    fed = {'metadata': {'category': 'federated'}}
    assert is_per_user(fed) is True and is_per_user(dict(fed, cache_per_user=False)) is False
    monkeypatch.setenv('SAJHA_CACHE_PER_USER_FEDERATED', 'false')
    assert is_per_user(fed) is False
    assert is_per_user({'cache_per_user': 'yes'}) is True and is_per_user({}) is False
    tok = set_caller(Caller('carol', '', (), 'session'))
    try:
        assert cache_scope({'cache_per_user': True}) == 'user:carol' and cache_scope({}) == ''
    finally:
        reset_caller(tok)


def test_federation_upstream_cache_per_user_key():
    from sajha.federation.config import UpstreamConfig
    up = UpstreamConfig.from_dict({'id': 'u', 'url': 'https://mcp.example.com/mcp', 'cache_ttl': 60,
                                   'cache_per_user': False})
    assert up.cache_per_user is False and up.to_dict()['cache_per_user'] is False
    assert UpstreamConfig.from_dict({'id': 'u', 'url': 'https://mcp.example.com/mcp'}).cache_per_user is None
