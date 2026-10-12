# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Wave 16, open data P2 (Open Data Tools §4, L35): the bls, bea and eia tool folders.

The BLS tools replay responses recorded live on 2026-10-12 (tests/fixtures/open_data/<tool>.json, made from
the tools' cassettes). No BEA UserID or EIA key was available (EIA's DEMO_KEY allowance ran out while the routes
were being verified), so their fixtures are hand-written with the field names and shapes of the BEA API user
guide and of EIA's live answers, with illustrative values; each says so in ``recorded``. The refused-key answer
(``bea_datasets__invalid_key``) is a live recording. No test calls a live service."""

import importlib
import json
import re
from pathlib import Path

import jsonschema
import pytest

from sajha.core import outbound
from sajha.tools.impl import bea_tools, bls_tools, eia_tools
from tests.tool_config_files import read_tool

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / 'config' / 'tools'
FIXTURES = ROOT / 'tests' / 'fixtures' / 'open_data'
FOLDERS = ('bls', 'bea', 'eia')
SECRET = {'api_key', 'userid', 'registrationkey'}
KEY_ENVS = ('BLS_API_KEY', 'BEA_API_KEY', 'EIA_API_KEY')


def _configs(folder):
    return [json.loads(p.read_text(encoding='utf-8')) for p in sorted((TOOLS / folder).glob('*.json'))]


def _tool(name):
    cfg = read_tool(name)
    module, cls = cfg['implementation'].rsplit('.', 1)
    return getattr(importlib.import_module(module), cls)(cfg), cfg


def _redact(params):
    return [[k, 'REDACTED' if str(k).lower() in SECRET else str(v)] for k, v in outbound._param_items(params)]


class _Replay:
    """Stands in for outbound.request: answers from recorded calls, matched on method, URL and parameters
    (secret parameters compared redacted)."""

    def __init__(self, calls):
        self.calls = list(calls)
        self.seen = []

    def __call__(self, method, url, params=None, headers=None, json=None, **_):
        params = _redact(params)
        self.seen.append({'method': method, 'url': url, 'params': params, 'json': json, 'headers': headers or {}})
        for i, c in enumerate(self.calls):
            if c['url'] == url and c['params'] == params and c.get('method', 'GET') == method:
                self.calls.pop(i)
                return outbound.Response(c['status'], 'OK' if c['status'] < 400 else 'ERR',
                                         {'content-type': c['content_type']}, c['body'].encode('utf-8'), url)
        raise AssertionError(f'unrecorded request {method} {url} {params}')


class _Store:
    """A state store with only the sliding window the throttles use."""

    def __init__(self, allow=True):
        self.allow, self.keys = allow, []

    def window_add(self, key, window, limit=None):
        self.keys.append((key, limit, window))
        return self.allow, len(self.keys)


@pytest.fixture(autouse=True)
def store(monkeypatch):
    s = _Store()
    import sajha.core.state as state
    monkeypatch.setattr(state, 'get_state_store', lambda: s)
    for env in KEY_ENVS:
        monkeypatch.delenv(env, raising=False)
    return s


def _run(name, case='', monkeypatch=None):
    data = json.loads((FIXTURES / f'{name}{"__" + case if case else ""}.json').read_text(encoding='utf-8'))
    tool, cfg = _tool(name)
    from sajha.tools.schema_defaults import apply_schema_defaults
    args, _ = apply_schema_defaults(cfg['inputSchema'], dict(data['arguments']))
    tool.validate_arguments(args)
    fake = _Replay(data['calls'])
    monkeypatch.setattr(outbound, 'request', fake)
    out = tool.execute(args)
    jsonschema.validate(out, cfg['outputSchema'])
    assert not fake.calls, 'every recorded response is used'
    return out, fake


# ── the configs ──────────────────────────────────────────────────────────────

ALL = [(f, c) for f in FOLDERS for c in _configs(f)]


def test_the_folders_hold_the_planned_tools():
    names = {c['name'] for _, c in ALL}
    assert names == {
        'bls_series', 'bls_cpi', 'bls_payrolls', 'bls_unemployment_rate', 'bls_ppi', 'bls_employment_cost_index',
        'bls_job_openings', 'bea_datasets', 'bea_nipa_table', 'bea_gdp_by_industry', 'bea_international_transactions',
        'bea_regional', 'eia_browse', 'eia_series', 'eia_petroleum_spot_prices', 'eia_petroleum_stocks',
        'eia_natural_gas_storage', 'eia_electricity_retail_sales', 'eia_short_term_outlook'}


@pytest.mark.parametrize('folder,cfg', ALL, ids=[c['name'] for _, c in ALL])
def test_configs_follow_the_open_data_rules(folder, cfg):
    ann = cfg['annotations']
    assert ann == {'readOnlyHint': True, 'idempotentHint': True, 'openWorldHint': True}
    example = json.loads(re.search(r'\nExample: (\{.*\})\s*$', cfg['description']).group(1))
    assert cfg['inputSchema']['examples'][0] == example
    jsonschema.validate(example, cfg['inputSchema'])
    assert cfg['inputSchema']['additionalProperties'] is False
    domain = (TOOLS / folder / 'domain.txt').read_text(encoding='utf-8').strip()
    assert len(domain) <= 600 and 'Source: U.S.' in domain
    assert len(cfg['description']) + 2 + len(domain) <= 1024
    for prop in cfg['inputSchema'].get('required', []):
        assert 'default' not in cfg['inputSchema']['properties'][prop]
    assert cfg['cache_ttl'] > 0
    assert cfg['api_key'] == '${%s_API_KEY:}' % folder.upper()       # the key comes from the environment only
    assert 'source' in cfg['outputSchema']['required']


def test_every_tool_has_a_fixture_and_a_test_case():
    for _, cfg in ALL:
        assert (FIXTURES / f'{cfg["name"]}.json').exists(), cfg['name']
        assert (ROOT / 'config' / 'tool_tests' / f'{cfg["name"]}.yaml').exists(), cfg['name']


def test_fixtures_hold_no_key():
    for p in FIXTURES.glob('*.json'):
        if p.stem.split('_')[0] in FOLDERS:
            data = json.loads(p.read_text(encoding='utf-8'))
            for call in data['calls']:
                for k, v in call['params']:
                    if k.lower() in SECRET:
                        assert v == 'REDACTED', p.name


# ── BLS ──────────────────────────────────────────────────────────────────────

def test_bls_series_keyless_v1(monkeypatch, store):
    out, fake = _run('bls_series', monkeypatch=monkeypatch)
    assert fake.seen[0]['url'] == bls_tools.URL['v1'] and fake.seen[0]['method'] == 'POST'
    assert 'registrationkey' not in fake.seen[0]['json']
    assert fake.seen[0]['json'] == {'seriesid': ['CUUR0000SA0', 'LNS14000000'], 'startyear': '2025', 'endyear': '2025'}
    assert out['api_version'] == 'v1 (keyless)' and 'BLS_API_KEY' in out['note']
    assert out['disclaimer'] == bls_tools.DISCLAIMER and re.fullmatch(r'\d{4}-\d{2}-\d{2}', out['retrieved'])
    cpi = out['series'][0]
    assert cpi['series_id'] == 'CUUR0000SA0' and cpi['frequency'] == 'Monthly'
    assert [o['date'] for o in cpi['observations']][:2] == ['2025-01', '2025-02']       # oldest first
    assert ('opendata:bls:v1:daily', 25, 86400.0) in store.keys and ('opendata:bls:burst', 50, 10.0) in store.keys


def test_bls_curated_tools(monkeypatch):
    cpi, fake = _run('bls_cpi', monkeypatch=monkeypatch)
    assert fake.seen[0]['json']['startyear'] == '2024'               # one year back for the 12-month change
    assert [s['series_id'] for s in cpi['series']] == ['CUSR0000SA0', 'CUSR0000SA0L1E']
    jan = cpi['series'][0]['observations'][0]
    assert jan['date'] == '2025-01' and isinstance(jan['change_12m_percent'], float)
    assert all(o['date'].startswith('2025') for s in cpi['series'] for o in s['observations'])
    ppi, _ = _run('bls_ppi', monkeypatch=monkeypatch)
    assert ppi['series'][1]['series_id'] == 'WPSFD49116'
    pay, _ = _run('bls_payrolls', monkeypatch=monkeypatch)
    nfp = pay['series'][0]['observations']
    assert nfp[1]['change'] == pytest.approx(nfp[1]['value'] - nfp[0]['value'])
    assert 'change_12m_percent' in pay['series'][1]['observations'][0]           # hourly earnings
    ur, _ = _run('bls_unemployment_rate', monkeypatch=monkeypatch)
    assert {s['unit'] for s in ur['series']} == {'percent'}
    assert all('change' not in o for s in ur['series'] for o in s['observations'])
    eci, _ = _run('bls_employment_cost_index', monkeypatch=monkeypatch)
    assert [o['date'] for o in eci['series'][0]['observations']] == \
        ['2024-Q1', '2024-Q2', '2024-Q3', '2024-Q4', '2025-Q1', '2025-Q2', '2025-Q3', '2025-Q4']
    assert eci['series'][0]['series_id'] == 'CIU1010000000000A' and eci['series'][0]['seasonally_adjusted'] is False
    jolts, _ = _run('bls_job_openings', monkeypatch=monkeypatch)
    assert [s['measure'] for s in jolts['series']] == ['openings', 'hires', 'quits', 'layoffs', 'openings_rate']
    assert jolts['messages'] == []                                    # v1's "no catalog" messages are dropped


def test_bls_with_a_key_uses_v2(monkeypatch, store):
    monkeypatch.setenv('BLS_API_KEY', 'k-123')
    body = json.dumps({'status': 'REQUEST_SUCCEEDED', 'message': [], 'Results': {'series': [
        {'seriesID': 'LNS14000000', 'catalog': {'series_title': '(Seas) Unemployment Rate'},
         'data': [{'year': '2025', 'period': 'M13', 'value': '4.2', 'footnotes': [{}]},
                  {'year': '2025', 'period': 'M12', 'value': '4.4', 'footnotes': [{}]}]}]}})
    fake = _Replay([{'method': 'POST', 'url': bls_tools.URL['v2'], 'params': [], 'status': 200,
                     'content_type': 'application/json', 'body': body}])
    monkeypatch.setattr(outbound, 'request', fake)
    tool, _ = _tool('bls_series')
    out = tool.execute({'series': ['LNS14000000'], 'from_year': 2006, 'to_year': 2025})        # 20 years: v2 only
    assert fake.seen[0]['json']['registrationkey'] == 'k-123' and fake.seen[0]['json']['catalog'] is True
    assert out['api_version'] == 'v2' and 'note' not in out
    assert out['series'][0]['label'] == '(Seas) Unemployment Rate'
    assert [o['date'] for o in out['series'][0]['observations']] == ['2025-12']          # M13 annual average dropped
    assert ('opendata:bls:v2:daily', 500, 86400.0) in store.keys


def test_bls_limits_and_errors(monkeypatch, store):
    tool, _ = _tool('bls_series')
    monkeypatch.setattr(outbound, 'request', lambda *a, **k: pytest.fail('no request'))
    with pytest.raises(ValueError, match='10 years'):
        tool.execute({'series': ['CUUR0000SA0'], 'from_year': 2006, 'to_year': 2025})
    with pytest.raises(ValueError, match='at most 25 series'):
        tool.execute({'series': [f'CUUR0000SA{i:02d}' for i in range(26)], 'from_year': 2025, 'to_year': 2025})
    store.allow = False
    with pytest.raises(ValueError, match='budget'):
        tool.execute({'series': ['CUUR0000SA0'], 'from_year': 2025, 'to_year': 2025})
    store.allow = True
    body = json.dumps({'status': 'REQUEST_NOT_PROCESSED', 'message': [
        'The daily threshold for total number of requests allocated to the user has been reached.']})
    monkeypatch.setattr(outbound, 'request', lambda *a, **k: outbound.Response(
        200, 'OK', {'content-type': 'application/json'}, body.encode(), a[1]))
    with pytest.raises(ValueError, match='rate limit'):
        tool.execute({'series': ['CUUR0000SA0'], 'from_year': 2025, 'to_year': 2025})


def test_bls_period_helpers():
    from datetime import date
    assert [bls_tools._date_of('2025', p) for p in ('M07', 'M13', 'Q03', 'Q05', 'S01', 'A01')] == \
        ['2025-07', None, '2025-Q3', None, '2025-S1', '2025']
    assert bls_tools._lag_key('2025-01', 12) == '2024-01' and bls_tools._lag_key('2025-Q1', 4) == '2024-Q1'
    assert bls_tools._lag_key('2025-01', 1) == '2024-12'
    start, end = date(2025, 2, 15), date(2025, 6, 30)
    assert [bls_tools._in_range(d, start, end) for d in ('2025-01', '2025-02', '2025-06', '2025-07')] == \
        [False, True, True, False]
    assert bls_tools._in_range('2025-Q1', start, end) and not bls_tools._in_range('2025-Q3', start, end)


# ── EIA ──────────────────────────────────────────────────────────────────────

def test_eia_browse_and_series(monkeypatch):
    browse, fake = _run('eia_browse', monkeypatch=monkeypatch)
    assert fake.seen[0]['url'] == f'{eia_tools.BASE}/petroleum/pri/spt/'
    assert ['api_key', 'REDACTED'] in fake.seen[0]['params'] and 'EIA_API_KEY' in browse['note']
    assert 'series' in {f['id'] for f in browse['facets']} and browse['data_columns'][0]['id'] == 'value'
    rows, fake = _run('eia_series', monkeypatch=monkeypatch)
    params = dict(fake.seen[0]['params'])
    assert params['facets[series][]'] == 'RWTC' and params['start'] == '2025-01' and params['end'] == '2025-12'
    assert params['length'] == '500' and params['offset'] == '0'
    assert rows['returned'] == 12 and rows['rows'][0]['period'] == '2025-01'          # oldest first
    assert all(isinstance(r['value'], float) for r in rows['rows'])


def test_eia_curated_tools(monkeypatch):
    spot, fake = _run('eia_petroleum_spot_prices', monkeypatch=monkeypatch)
    assert dict(fake.seen[0]['params'])['start'] == '2026-09-01'
    assert [s['name'] for s in spot['series']] == ['wti', 'brent'] and spot['series'][0]['unit'] == '$/BBL'
    dates = [o['date'] for o in spot['series'][0]['observations']]
    assert dates == sorted(dates) and all(d.startswith('2026-09') for d in dates)
    stocks, _ = _run('eia_petroleum_stocks', monkeypatch=monkeypatch)
    assert stocks['series'][0]['series_id'] == 'WCESTUS1' and stocks['series'][0]['unit'] == 'MBBL'
    gas, _ = _run('eia_natural_gas_storage', monkeypatch=monkeypatch)
    obs = gas['series'][0]['observations']
    assert obs[0]['change'] is None and obs[1]['change'] == obs[1]['value'] - obs[0]['value']
    power, _ = _run('eia_electricity_retail_sales', monkeypatch=monkeypatch)
    assert [s['series_id'] for s in power['series']] == ['TX.RES.price', 'TX.RES.sales', 'US.RES.price', 'US.RES.sales']
    assert power['series'][0]['unit'] == 'cents per kilowatt-hour'
    steo, _ = _run('eia_short_term_outlook', monkeypatch=monkeypatch)
    assert [s['series_id'] for s in steo['series']] == ['BREPUUS', 'NGHHUUS']
    assert steo['series'][0]['observation_count'] == 24 and 'forecast' in steo['note_forecast']


def test_eia_key_pages_and_errors(monkeypatch, store):
    monkeypatch.setenv('EIA_API_KEY', 'k-eia')
    seen = []

    def fake(method, url, params=None, **_):
        p = dict(outbound._param_items(params))
        seen.append(p)
        n = int(p['length']) if int(p['offset']) < 7000 else 0
        n = min(n, 7000 - int(p['offset']))
        body = {'response': {'total': '7000', 'data': [{'period': f'r{int(p["offset"]) + i}', 'value': '1.5'}
                                                       for i in range(n)]}}
        return outbound.Response(200, 'OK', {'content-type': 'application/json'}, json.dumps(body).encode(), url)

    monkeypatch.setattr(outbound, 'request', fake)
    tool, _ = _tool('eia_series')
    out = tool.execute({'route': 'petroleum/pri/spt', 'max_rows': 6000})
    assert [(s['offset'], s['length']) for s in seen] == [('0', '5000'), ('5000', '1000')]
    assert seen[0]['api_key'] == 'k-eia' and 'note' not in out
    assert out['returned'] == 6000 and out['truncated'] is True
    assert ('opendata:eia:second', 5, 1.0) in store.keys and ('opendata:eia:hour', 9000, 3600.0) in store.keys
    monkeypatch.delenv('EIA_API_KEY')
    for status, body, match in ((429, {'error': {'code': 'OVER_RATE_LIMIT'}}, 'rate limit'),
                                (403, {'error': {'code': 'API_KEY_INVALID', 'message': 'bad key'}}, 'EIA_API_KEY'),
                                (400, {'error': 'Invalid facet'}, 'HTTP 400')):
        monkeypatch.setattr(outbound, 'request', lambda *a, _s=status, _b=body, **k: outbound.Response(
            _s, 'ERR', {'content-type': 'application/json'}, json.dumps(_b).encode(), a[1]))
        with pytest.raises(ValueError, match=match):
            tool.execute({'route': 'petroleum/pri/spt'})
    with pytest.raises(ValueError, match='not an EIA route'):
        tool.execute({'route': '../etc'})
    assert ('opendata:eia:demo:day', 10, 86400.0) in store.keys


# ── BEA ──────────────────────────────────────────────────────────────────────

def test_bea_without_a_key_is_not_configured(monkeypatch):
    from sajha.quality import check
    monkeypatch.setattr(outbound, 'request', lambda *a, **k: pytest.fail('no request without a key'))
    tool, cfg = _tool('bea_datasets')
    with pytest.raises(ValueError, match='not configured') as e:
        tool.execute({})
    assert check.classify(tool, error=e.value)[0] == 'not_configured'
    assert check.missing_key(tool) == 'api_key'               # the unresolved ${BEA_API_KEY:} in the config
    assert check.missing_key(_tool('bls_cpi')[0]) == ''           # keyless v1 tier: the check calls it
    assert check.missing_key(_tool('eia_browse')[0]) == 'api_key'  # the DEMO_KEY is too small for the check


def test_bea_refused_key_recorded_live(monkeypatch):
    monkeypatch.setenv('BEA_API_KEY', 'not-a-real-userid')
    with pytest.raises(ValueError, match='refused the API key.*BEA_API_KEY'):
        _run('bea_datasets', 'invalid_key', monkeypatch)


def test_bea_tools_on_documented_responses(monkeypatch):
    monkeypatch.setenv('BEA_API_KEY', 'k-bea')
    sets, fake = _run('bea_datasets', monkeypatch=monkeypatch)
    assert ['UserID', 'REDACTED'] == fake.seen[0]['params'][0]
    assert 'not endorsed or certified by BEA' in sets['source'] and sets['dataset_count'] == 4
    nipa, _ = _run('bea_nipa_table', monkeypatch=monkeypatch)
    assert [s['line'] for s in nipa['series']] == [1, 2] and nipa['title'].startswith('Table 1.1.1')
    assert nipa['series'][0]['observations'] == [{'date': '2025-Q1', 'value': -0.5}, {'date': '2025-Q2', 'value': 3.8}]
    gdp, _ = _run('bea_gdp_by_industry', monkeypatch=monkeypatch)
    assert [s['industry'] for s in gdp['series']] == ['52', '51']
    assert gdp['series'][0]['observations'][0] == {'date': '2025-Q1', 'value': 2450.1}
    ita, _ = _run('bea_international_transactions', monkeypatch=monkeypatch)
    assert ita['series'][0]['unit_multiplier'] == 'millions' and ita['series'][0]['observation_count'] == 3
    reg, _ = _run('bea_regional', monkeypatch=monkeypatch)
    assert reg['series_count'] == 3 and reg['series'][1]['geo_name'] == 'Alabama'


def test_bea_throttle_and_rate_limit(monkeypatch, store):
    monkeypatch.setenv('BEA_API_KEY', 'k-bea')
    tool, _ = _tool('bea_datasets')
    monkeypatch.setattr(outbound, 'request', lambda *a, **k: outbound.Response(
        429, 'ERR', {'content-type': 'application/json', 'retry-after': '42'}, b'{}', a[1]))
    with pytest.raises(ValueError, match='rate limit.*42'):
        tool.execute({})
    assert store.keys == [('opendata:bea:requests', 100, 60.0)]
    store.allow = False
    monkeypatch.setattr(bea_tools, 'THROTTLE', ('opendata:bea:requests', 100, 60.0, 0))
    monkeypatch.setattr(outbound, 'request', lambda *a, **k: pytest.fail('no request past the budget'))
    with pytest.raises(ValueError, match='budget'):
        tool.execute({})
