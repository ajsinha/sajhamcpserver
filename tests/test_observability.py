# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Observability: Prometheus exposition and /metrics protection, the instrumentation points
(HTTP, both MCP eras, tools, LLM, ask, auth, sandbox, federation), the usage ledger and
its dashboard API, alert rules and their SSRF-guarded webhook, OpenTelemetry spans
(when the SDK is installed), the multi-worker merge, and the docs naming every key.

Design: docs/architecture/Observability.md.
"""

import os
import re
import time
from datetime import datetime, timezone

import pytest
import yaml

from sajha.observability import alerts as A
from sajha.observability import metrics as M
from sajha.observability import usage as U

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _value(text: str, name: str, **labels) -> float:
    """The value of one sample in exposition text (0 when absent)."""
    for line in text.splitlines():
        if not line.startswith(name + '{') and not line.startswith(name + ' '):
            continue
        m = re.match(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{(.*)\})? (.+)$', line)
        if not m or m.group(1) != name:
            continue
        got = dict(re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', m.group(3) or ''))
        if all(got.get(k) == str(v) for k, v in labels.items()):
            return float(m.group(4))
    return 0.0


# ── the registry and the text format ─────────────────────────────────

def test_exposition_format():
    reg = M.Registry()
    c = M.Counter(reg, 't_total', 'A "help"\nline', ('a',))
    h = M.Histogram(reg, 't_seconds', 'Latency.', ('a',), buckets=(0.1, 1.0))
    c.inc(('x"y\\z\n',), 2)
    h.observe(('q',), 0.05)
    h.observe(('q',), 0.5)
    h.observe(('q',), 5)
    text = M.render(reg.collect())
    assert '# HELP t_total A "help"\\nline' in text
    assert '# TYPE t_total counter' in text
    assert 't_total{a="x\\"y\\\\z\\n"} 2' in text
    assert '# TYPE t_seconds histogram' in text
    assert 't_seconds_bucket{a="q",le="0.1"} 1' in text
    assert 't_seconds_bucket{a="q",le="1"} 2' in text            # cumulative
    assert 't_seconds_bucket{a="q",le="+Inf"} 3' in text
    assert 't_seconds_count{a="q"} 3' in text
    assert 't_seconds_sum{a="q"} 5.55' in text
    # one HELP/TYPE per family
    assert text.count('# TYPE t_total') == 1


def test_series_cap_folds_into_other(monkeypatch):
    monkeypatch.setenv('SAJHA_OBSERVABILITY_METRICS_MAX_SERIES', '10')
    reg = M.Registry()
    c = M.Counter(reg, 'cap_total', 'x', ('tool',))
    for i in range(25):
        c.inc((f't{i}',))
    text = M.render(reg.collect())
    assert _value(text, 'cap_total', tool='_other') == 15
    assert _value(text, 'sajha_metrics_series_dropped_total', family='cap_total') == 15


def test_tool_label_modes(monkeypatch):
    monkeypatch.setenv('SAJHA_OBSERVABILITY_METRICS_TOOL_LABEL', 'group')
    assert M._tool_labels('fred_get_series') == ('fred', 'fred')
    monkeypatch.setenv('SAJHA_OBSERVABILITY_METRICS_TOOL_LABEL', 'none')
    assert M._tool_labels('fred_get_series') == ('_all', 'fred')
    monkeypatch.setenv('SAJHA_OBSERVABILITY_METRICS_TOOL_LABEL', 'name')
    assert M._tool_labels('fred_get_series') == ('fred_get_series', 'fred')


# ── /metrics protection ───────────────────────────────────────────────

def test_metrics_requires_admin_by_default(web):
    c, admin = web
    r = c.get('/metrics')
    assert r.status_code == 401 and 'Bearer' in r.headers.get('www-authenticate', '')
    r = c.get('/metrics', cookies=admin)
    assert r.status_code == 200
    assert r.headers['content-type'].startswith('text/plain; version=0.0.4')
    assert '# TYPE sajha_http_requests_total counter' in r.text
    assert 'process_resident_memory_bytes' in r.text and 'sajha_info{version=' in r.text


def test_metrics_token_and_none_modes(web, monkeypatch):
    c, _ = web
    monkeypatch.setenv('SAJHA_OBSERVABILITY_METRICS_AUTH', 'token')
    monkeypatch.setenv('SAJHA_OBSERVABILITY_METRICS_TOKEN', 's3cret-token')
    assert c.get('/metrics', headers={'Authorization': 'Bearer wrong'}).status_code == 403
    assert c.get('/metrics', headers={'Authorization': 'Bearer s3cret-token'}).status_code == 200
    monkeypatch.setenv('SAJHA_OBSERVABILITY_METRICS_AUTH', 'none')
    assert c.get('/metrics').status_code == 200
    monkeypatch.setenv('SAJHA_OBSERVABILITY_METRICS_ENABLED', 'false')
    assert c.get('/metrics').status_code == 404


# ── instrumentation points ────────────────────────────────────────────

def _metrics(c, admin):
    return c.get('/metrics', cookies=admin).text


def _legacy_call(c, cookies, name, arguments):
    init = c.post('/mcp', cookies=cookies, json={
        'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
        'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}})
    sid = init.headers.get('mcp-session-id')
    h = {'Mcp-Session-Id': sid, 'MCP-Protocol-Version': '2025-11-25'} if sid else {}
    return c.post('/mcp', cookies=cookies, headers=h, json={
        'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}})


def test_tool_and_legacy_mcp_metrics_and_ledger(web):
    c, admin = web
    before = _metrics(c, admin)
    r = _legacy_call(c, admin, 'calc_future_value', {'present_value': 100, 'rate': 5, 'years': 2})
    assert r.status_code == 200 and 'result' in r.json(), r.text
    after = _metrics(c, admin)
    key = dict(tool='calc_future_value', group='calc')
    assert _value(after, 'sajha_tool_calls_total', outcome='ok', **key) == \
        _value(before, 'sajha_tool_calls_total', outcome='ok', **key) + 1
    assert _value(after, 'sajha_mcp_requests_total', era='legacy', method='tools/call', outcome='ok') >= 1
    assert _value(after, 'sajha_tool_call_duration_seconds_count', **key) >= 1
    assert _value(after, 'sajha_http_requests_total', method='POST', route='/mcp', status='200') >= 2
    # the usage ledger attributes the call to the signed-in admin
    rep = c.get(f'/api/observability/usage?since={TODAY}&until={TODAY}&tool=calc_future_value',
                cookies=admin).json()
    assert rep['totals']['tool_calls'] >= 1
    assert any(u['key'] == 'admin' for u in rep['by_user'])
    assert any(t['key'] == 'calc_future_value' for t in rep['by_tool'])
    # and the legacy JSON collector is fed now
    assert c.get('/api/metrics/tools/calc_future_value', cookies=admin).status_code == 200


def test_unknown_mcp_methods_do_not_become_labels(web):
    c, admin = web
    _legacy_call(c, admin, 'calc_future_value', {'present_value': 1, 'rate': 1, 'years': 1})
    c.post('/mcp', cookies=admin, json={'jsonrpc': '2.0', 'id': 9, 'method': 'no/such-method-xyz'})
    text = _metrics(c, admin)
    assert 'no/such-method-xyz' not in text


def test_modern_mcp_metrics(web):
    c, admin = web
    body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list',
            'params': {'_meta': {'io.modelcontextprotocol/protocolVersion': '2026-07-28',
                                 'io.modelcontextprotocol/clientCapabilities': {},
                                 'io.modelcontextprotocol/clientInfo': {'name': 't', 'version': '1'}}}}
    r = c.post('/mcp', json=body, cookies=admin, headers={'MCP-Protocol-Version': '2026-07-28',
                                                          'Mcp-Method': 'tools/list',
                                                          'Accept': 'application/json, text/event-stream'})
    assert r.status_code == 200, r.text
    assert _value(_metrics(c, admin), 'sajha_mcp_requests_total', era='modern', method='tools/list',
                  outcome='ok') >= 1


def test_auth_failures_and_lockouts_are_counted(web):
    c, admin = web
    before = _value(_metrics(c, admin), 'sajha_auth_failures_total', method='password')
    c.post('/login', data={'user_id': 'no-such-user-obs', 'password': 'x'}, follow_redirects=False)
    c.cookies.clear()
    c.get('/api/metrics', headers={'X-API-Key': 'sja_not_a_real_key'})
    text = _metrics(c, admin)
    assert _value(text, 'sajha_auth_failures_total', method='password') == before + 1
    assert _value(text, 'sajha_auth_failures_total', method='apikey') >= 1
    assert '# TYPE sajha_auth_lockouts_total counter' in text


def test_ask_and_llm_metrics(web):
    c, admin = web
    r = c.post('/api/ai/ask', json={'question': 'what is the future value of 100 at 5% for 2 years?'},
               cookies=admin)
    if r.status_code != 200:
        pytest.skip(f'ask unavailable here: {r.status_code}')
    text = _metrics(c, admin)
    assert sum(float(l.rsplit(' ', 1)[1]) for l in text.splitlines()
               if l.startswith('sajha_ask_runs_total{')) >= 1
    assert sum(float(l.rsplit(' ', 1)[1]) for l in text.splitlines()
               if l.startswith('sajha_llm_calls_total{')) >= 1
    rep = c.get(f'/api/observability/usage?since={TODAY}&until={TODAY}', cookies=admin).json()
    assert rep['totals']['llm_calls'] >= 1 and rep['by_model']


def test_sandbox_runs_are_counted():
    from sajha.sandbox.backends import SandboxResult
    before = M.SANDBOX_RUNS.value(('subprocess', 'timeout'))
    M.record_sandbox_run(SandboxResult(backend='subprocess', exit_code=-9, timed_out=True, duration_ms=1500))
    M.record_sandbox_run(SandboxResult(backend='subprocess', exit_code=0, duration_ms=10))
    assert M.SANDBOX_RUNS.value(('subprocess', 'timeout')) == before + 1
    assert M.SANDBOX_RUNS.value(('subprocess', 'ok')) >= 1


def test_federation_health_is_collected_when_present(monkeypatch):
    import sajha.federation.manager as fm

    class Fake:
        def status(self):
            return [{'id': 'units', 'state': 'connected', 'calls': 4, 'failures': 1, 'enabled': True},
                    {'id': 'wx', 'state': 'error', 'calls': 0, 'failures': 3, 'enabled': True}]
    monkeypatch.setattr(fm, 'get_federation', lambda: Fake())
    text = M.render(M._federation_families())
    assert _value(text, 'sajha_federation_upstream_up', upstream='units', state='connected') == 1
    assert _value(text, 'sajha_federation_upstream_up', upstream='wx', state='error') == 0
    assert _value(text, 'sajha_federation_upstream_failures_total', upstream='wx') == 3
    rule = A.parse_rule({'name': 'fed', 'metric': 'federation_upstreams_down', 'op': '>=', 'threshold': 1})
    assert A.AlertManager([rule]).value(rule, time.time())[0] == 1
    monkeypatch.setattr(fm, 'get_federation', lambda: None)
    assert list(M._federation_families()) == []


# ── several workers ───────────────────────────────────────────────────

def test_multiworker_snapshots_merge_with_a_worker_label(monkeypatch):
    from sajha.core.state.memory import MemoryStateStore
    store = MemoryStateStore('obs-test:')
    store.shared = True
    monkeypatch.setattr(M, '_shared_store', lambda: store)
    store.set('obs:metrics:otherhost:42:abc', {'at': time.time(), 'families': [
        ['sajha_tool_calls_total', 'counter', 'Tool calls.',
         [['sajha_tool_calls_total', {'tool': 'x_y', 'group': 'x', 'outcome': 'ok'}, 7]]]]})
    text = M.exposition()
    assert _value(text, 'sajha_tool_calls_total', tool='x_y', worker='otherhost:42:abc') == 7
    assert 'worker="' + M._worker_id() + '"' in text
    assert text.count('# TYPE sajha_tool_calls_total counter') == 1
    assert store.get('obs:metrics:' + M._worker_id()) is not None      # this worker published too


# ── the dashboard and its API ─────────────────────────────────────────

def test_usage_page_and_csv(web):
    c, admin = web
    page = c.get('/monitoring/usage', cookies=admin)
    assert page.status_code == 200 and 'Usage &amp; cost' in page.text and 'chart.umd.js' in page.text
    assert c.get('/monitoring/usage', follow_redirects=False).status_code in (302, 401)
    r = c.get(f'/api/observability/usage.csv?dimension=tool&since={TODAY}&until={TODAY}', cookies=admin)
    assert r.status_code == 200 and r.headers['content-type'].startswith('text/csv')
    assert r.text.splitlines()[0].startswith('tool,tool_calls,tool_errors,error_rate,p50_ms')
    assert c.get('/api/observability/usage.csv?dimension=bogus', cookies=admin).status_code == 400
    st = c.get('/api/observability/status', cookies=admin).json()
    assert st['metrics']['auth'] in ('admin', 'token', 'none') and 'detail' in st['otel']


def test_non_admins_see_only_their_own_calls():
    from sajha.auth import AuthContext
    from sajha.routes.observability_routes import _filters
    user = AuthContext(authenticated=True, user_id='alice', roles=['user'])
    f = _filters(user, user='bob', api_key='k', role='', provider='', model='', tool='')
    assert f == {'user': 'alice'}
    admin = AuthContext(authenticated=True, user_id='root', roles=['admin'], is_admin=True)
    assert _filters(admin, 'bob', '', '', 'mock', '', '') == {'user': 'bob', 'provider': 'mock'}


def test_report_aggregates_and_percentiles(monkeypatch):
    from sajha.observability.caller import Caller
    rows = []
    monkeypatch.setattr(U, '_rows', lambda s, u, f, limit: rows)
    who = Caller('apikey:ci', 'ci', ('api_consumer',), 'apikey')
    for i, ms in enumerate([10, 20, 30, 40, 1000]):
        rows.append({'kind': 'tool', 'day': TODAY, 'user_id': who.user_id, 'api_key': 'ci', 'roles': ',api_consumer,',
                     'tool': 'calc_irr', 'provider': None, 'model': None, 'latency_ms': ms,
                     'outcome': 'error' if i == 4 else 'ok', 'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0})
    rows.append({'kind': 'llm', 'day': TODAY, 'user_id': who.user_id, 'api_key': 'ci', 'roles': ',api_consumer,',
                 'tool': None, 'provider': 'mock', 'model': 'mock-planner', 'latency_ms': 5, 'outcome': 'ok',
                 'input_tokens': 100, 'output_tokens': 50, 'cost_usd': 0.0123})
    rep = U.report(TODAY, TODAY)
    t = rep['totals']
    assert (t['tool_calls'], t['tool_errors'], t['llm_calls'], t['tokens']) == (5, 1, 1, 150)
    assert t['error_rate'] == 0.2 and t['p50_ms'] == 30.0 and t['cost_usd'] == 0.0123
    assert rep['by_api_key'][0]['key'] == 'ci' and rep['by_role'][0]['key'] == 'api_consumer'
    assert rep['by_model'][0]['key'] == 'mock/mock-planner'
    assert rep['cost_by_provider']['series']['mock'][-1] == 0.0123
    assert list(U.csv_rows(rep, 'api_key'))[1][0] == 'ci'


# ── alerts ────────────────────────────────────────────────────────────

def test_alert_rule_parsing():
    ok = A.parse_rule({'name': 'e', 'metric': 'tool_error_rate', 'op': '>', 'threshold': 0.5, 'window': '2m',
                       'cooldown': '1h', 'channel': {'type': 'log'}})
    assert not ok.error and ok.window_s == 120 and ok.cooldown_s == 3600
    assert 'unknown metric' in A.parse_rule({'metric': 'nope', 'threshold': 1}).error
    assert A.parse_rule({'metric': 'tool_calls', 'threshold': 'x'}).error
    assert 'allowed_urls' in A.parse_rule({'metric': 'tool_calls', 'threshold': 1,
                                           'channel': {'type': 'webhook', 'url': 'https://hooks.example.com/x'}}).error


def test_alert_fires_once_per_cooldown():
    rule = A.parse_rule({'name': 'errs', 'metric': 'tool_error_rate', 'op': '>=', 'threshold': 0.5,
                         'window': '1m', 'min_events': 4, 'cooldown': '10m'})
    am = A.AlertManager([rule])
    now = time.time()
    for i in range(3):
        am.window.add('tool', {'tool': 't_a', 'outcome': 'error', 'ms': 5}, at=now)
    assert am.evaluate(now) == []                 # below min_events
    am.window.add('tool', {'tool': 't_a', 'outcome': 'ok', 'ms': 5}, at=now)
    fired = am.evaluate(now)
    assert len(fired) == 1 and fired[0]['value'] == 0.75 and rule.firing
    assert am.evaluate(now + 1) == []             # cooldown
    assert am.evaluate(now + 3600) == []          # the window moved on: nothing to judge
    assert M.ALERTS_FIRED.value(('errs',)) >= 1


def test_alert_webhook_allowlist_and_ssrf_guard(monkeypatch):
    monkeypatch.setenv('SAJHA_OBSERVABILITY_ALERTS_WEBHOOK_ALLOWED_URLS', 'http://127.0.0.1:9/hook,https://hooks.example.com/sajha')
    with pytest.raises(A.AlertDeliveryError):
        A.check_webhook_url('https://evil.example.com/sajha')
    with pytest.raises(A.AlertDeliveryError):
        A.check_webhook_url('https://user:pw@hooks.example.com/sajha')
    assert A.check_webhook_url('https://hooks.example.com/sajha/x').hostname == 'hooks.example.com'
    # allow-listed but loopback: refused by the SSRF guard unless private networks are allowed
    with pytest.raises(A.AlertDeliveryError):
        A._resolve_pinned('127.0.0.1', 9)
    assert A.send_webhook('http://127.0.0.1:9/hook', {'x': 1}) is False
    monkeypatch.setenv('SAJHA_OBSERVABILITY_ALERTS_WEBHOOK_ALLOW_PRIVATE_NETWORKS', 'true')
    assert A._resolve_pinned('127.0.0.1', 9) == '127.0.0.1'


def test_alert_rules_from_environment(monkeypatch):
    monkeypatch.setenv('SAJHA_OBSERVABILITY_ALERTS', '[{"name": "c", "metric": "llm_cost_usd", "op": ">", '
                                                     '"threshold": 1, "window": "1h"}]')
    rules = A.load_rules()
    assert [r.name for r in rules] == ['c'] and not rules[0].error


# ── OpenTelemetry ─────────────────────────────────────────────────────

def test_spans_nest_and_continue_meta_traceparent(web):
    sdk = pytest.importorskip('opentelemetry.sdk.trace')
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from sajha.observability import tracing
    c, admin = web
    exporter = InMemorySpanExporter()
    tp = sdk.TracerProvider()
    tp.add_span_processor(SimpleSpanProcessor(exporter))
    tracing.install(tp)
    try:
        tid = '4bf92f3577b34da6a3ce929d0e0e4736'
        body = {'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call',
                'params': {'name': 'calc_future_value', 'arguments': {'present_value': 1, 'rate': 1, 'years': 1},
                           '_meta': {'io.modelcontextprotocol/protocolVersion': '2026-07-28',
                                     'io.modelcontextprotocol/clientCapabilities': {},
                                     'io.modelcontextprotocol/clientInfo': {'name': 't', 'version': '1'},
                                     'traceparent': f'00-{tid}-00f067aa0ba902b7-01'}}}
        r = c.post('/mcp', json=body, cookies=admin, headers={'MCP-Protocol-Version': '2026-07-28',
                                                              'Mcp-Method': 'tools/call',
                                                              'Mcp-Name': 'calc_future_value',
                                                              'Accept': 'application/json'})
        assert r.status_code == 200, r.text
        spans = {s.name: s for s in exporter.get_finished_spans()}
        mcp, tool = spans['mcp tools/call'], spans['tool calc_future_value']
        assert format(mcp.context.trace_id, '032x') == tid                 # continued from _meta
        assert tool.parent.span_id == mcp.context.span_id                  # tool under MCP
        assert tool.attributes['sajha.tool.outcome'] == 'ok'
        assert any(n.startswith('POST /mcp') for n in spans)               # the HTTP server span
    finally:
        tracing.install(None)


def test_otel_off_by_default_and_reports_why():
    from sajha.observability import tracing
    assert tracing.wanted() is False
    assert tracing.status()['enabled'] is False


# ── docs ──────────────────────────────────────────────────────────────

def _flat(d, prefix=''):
    for k, v in d.items():
        key = f'{prefix}.{k}' if prefix else k
        if isinstance(v, dict):
            yield from _flat(v, key)
        else:
            yield key


def test_every_observability_key_is_documented():
    cfg = yaml.safe_load(open(os.path.join(ROOT, 'config/application.yml'), encoding='utf-8'))
    ref = open(os.path.join(ROOT, 'docs/getting-started/Configuration Reference.md'), encoding='utf-8').read()
    missing = [k for k in _flat(cfg['observability'], 'observability') if f'`{k}`' not in ref]
    assert not missing, missing


def test_example_deployment_files_name_real_metrics():
    """The shipped Prometheus rules and Grafana dashboard query only families SAJHA exposes."""
    import json
    base = os.path.join(ROOT, 'deployment/observability')
    src = open(os.path.join(ROOT, 'sajha/observability/metrics.py'), encoding='utf-8').read()
    rules = yaml.safe_load(open(os.path.join(base, 'sajha-alerts.yml'), encoding='utf-8'))
    exprs = [r['expr'] for g in rules['groups'] for r in g['rules']]
    dash = json.load(open(os.path.join(base, 'grafana-sajha-dashboard.json'), encoding='utf-8'))
    exprs += [t['expr'] for p in dash['panels'] for t in p.get('targets', [])]
    names = {re.sub(r'_(bucket|sum|count)$', '', n) for e in exprs for n in re.findall(r'\b((?:sajha|process)_[a-z_]+)', e)}
    assert names and not [n for n in names if f"'{n}'" not in src], names
    prom = yaml.safe_load(open(os.path.join(base, 'prometheus.yml'), encoding='utf-8'))
    assert prom['scrape_configs'][0]['metrics_path'] == '/metrics'
    assert 'sajha-alerts.yml' in prom['rule_files']
