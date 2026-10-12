# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Wave 16, open data P2 (Open Data Tools §4, L32 and L34): the cftc, ons and statcan tool folders.
Each tool replays responses recorded from the live service (tests/fixtures/open_data/<tool>[__case].json;
large Statistics Canada and ONS bodies are trimmed, as each fixture says); no test calls a live service."""

import importlib
import json
import re
from pathlib import Path
from unittest import mock

import jsonschema
import pytest

from sajha.core import outbound
from sajha.tools.impl import cftc_tools, ons_tools, statcan_tools
from tests.tool_config_files import read_tool

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / 'config' / 'tools'
FIXTURES = ROOT / 'tests' / 'fixtures' / 'open_data'
FOLDERS = ('cftc', 'ons', 'statcan')
PREFIXES = ('cftc_', 'ons_', 'statcan_')
RECORDED = sorted(p for p in FIXTURES.glob('*.json') if p.stem.startswith(PREFIXES))


def _configs(folder):
    return [json.loads(p.read_text(encoding='utf-8')) for p in sorted((TOOLS / folder).glob('*.json'))]


def _tool(name):
    cfg = read_tool(name)
    module, cls = cfg['implementation'].rsplit('.', 1)
    return getattr(importlib.import_module(module), cls)(cfg), cfg


class _Replay:
    """Stands in for outbound.request: answers from recorded calls, matched on method, URL,
    parameters and JSON body."""

    def __init__(self, calls):
        self.calls = list(calls)
        self.seen = []

    def __call__(self, method, url, params=None, headers=None, json=None, **_):
        params = [list(p) for p in outbound._param_items(params)]
        self.seen.append({'method': method, 'url': url, 'params': params, 'headers': headers or {}, 'json': json})
        for i, c in enumerate(self.calls):
            if (c['url'] == url and c['params'] == params and c.get('method', 'GET') == method
                    and c.get('json') == json):
                self.calls.pop(i)
                return outbound.Response(c['status'], 'OK' if c['status'] < 400 else 'ERR',
                                         {'content-type': c['content_type']}, c['body'].encode('utf-8'), url)
        raise AssertionError(f'unrecorded request {method} {url} {params} {json}')


class _Store:
    def __init__(self, allow=True):
        self.allow, self.hits = allow, 0

    def window_add(self, key, window, limit=None):
        self.hits += 1
        return self.allow, self.hits


@pytest.fixture(autouse=True)
def store(monkeypatch):
    s = _Store()
    import sajha.core.state as state
    monkeypatch.setattr(state, 'get_state_store', lambda: s)
    statcan_tools.clear_cache()
    yield s
    statcan_tools.clear_cache()


def _replay(name, case=''):
    data = json.loads((FIXTURES / f'{name}{"__" + case if case else ""}.json').read_text(encoding='utf-8'))
    tool, cfg = _tool(data['tool'])
    statcan_tools.clear_cache()          # each recording made its own reference-data calls
    fake = _Replay(data['calls'])
    with mock.patch.object(outbound, 'request', fake):
        tool.validate_arguments(data['arguments'])
        out = tool.execute(data['arguments'])
    jsonschema.validate(out, cfg['outputSchema'])
    assert not fake.calls, 'every recorded response is used'
    return out, fake


# ── the configs ──────────────────────────────────────────────────────────────

ALL = [(f, c) for f in FOLDERS for c in _configs(f)]


@pytest.mark.parametrize('folder,cfg', ALL, ids=[c['name'] for _, c in ALL])
def test_configs_follow_the_open_data_rules(folder, cfg):
    ann = cfg['annotations']
    assert ann == {'readOnlyHint': True, 'idempotentHint': True, 'openWorldHint': True}
    example = json.loads(re.search(r'\nExample: (\{.*\})\s*$', cfg['description']).group(1))
    assert cfg['inputSchema']['examples'][0] == example
    jsonschema.validate(example, cfg['inputSchema'])
    assert cfg['inputSchema']['additionalProperties'] is False
    domain = (TOOLS / folder / 'domain.txt').read_text(encoding='utf-8').strip()
    assert len(domain) <= 600 and domain.startswith('Source: ')
    assert len(cfg['description']) + 2 + len(domain) <= 1024
    for prop in cfg['inputSchema'].get('required', []):
        assert 'default' not in cfg['inputSchema']['properties'][prop]
    assert cfg['cache_ttl'] > 0 and cfg['name'].startswith(folder + '_')
    assert 'source' in cfg['outputSchema']['required']


def test_every_tool_has_a_fixture_a_probe_and_a_cassette():
    for folder in FOLDERS:
        for cfg in _configs(folder):
            name = cfg['name']
            assert (FIXTURES / f'{name}.json').exists(), name
            case = ROOT / 'config' / 'tool_tests' / f'{name}.yaml'
            assert case.exists() and 'probe:' in case.read_text(encoding='utf-8'), name
            assert list((ROOT / 'config' / 'tool_tests' / 'cassettes' / name).glob('*.json')), name


@pytest.mark.parametrize('fixture', RECORDED, ids=[p.stem for p in RECORDED])
def test_recorded_runs_replay_and_match_the_output_schema(fixture):
    name, _, case = fixture.stem.partition('__')
    out, _ = _replay(name, case)
    assert out['source'].startswith('Source: ')


# ── CFTC ─────────────────────────────────────────────────────────────────────

def test_cftc_latest_by_code_and_by_name():
    out, fake = _replay('cftc_cot_latest')
    assert out['dataset'] == 'gpe5-46if' and out['code'] == '13874A'
    assert set(out['categories']) == {'dealers', 'asset_managers', 'leveraged_funds', 'other_reportables',
                                      'nonreportable'}
    lev = out['categories']['leveraged_funds']
    assert lev['net'] == lev['long'] - lev['short']
    assert lev['net_pct_of_open_interest'] == round(100 * lev['net'] / out['open_interest'], 2)
    params = dict(fake.seen[0]['params'])
    assert params['$order'] == 'report_date_as_yyyy_mm_dd DESC' and params['$limit'] == '1'
    gold, fake = _replay('cftc_cot_latest', 'name')
    assert gold['code'] == '088691' and len(fake.seen) == 2          # the name resolved first
    assert 'managed_money' in gold['categories']


def test_cftc_history_markets_and_net_positioning():
    hist, fake = _replay('cftc_cot_history')
    dates = [r['report_date'] for r in hist['reports']]
    assert dates == sorted(dates, reverse=True) and all('2025-09-01' <= d <= '2025-09-30' for d in dates)
    assert "report_date_as_yyyy_mm_dd >= '2025-09-01T00:00:00.000'" in dict(fake.seen[0]['params'])['$where']
    markets, _ = _replay('cftc_cot_markets')
    assert any(m['code'] == '088691' for m in markets['markets'])
    net, _ = _replay('cftc_cot_net_positioning')
    assert net['category'] == 'leveraged_funds' and net['from'] == '2025-07-01' and net['to'] == '2025-09-30'
    s = net['summary']
    assert s['min'] <= net['latest']['net_pct_of_open_interest'] <= s['max']


def test_cftc_ambiguous_name_is_refused(monkeypatch):
    rows = [{'cftc_contract_market_code': '088691', 'market_and_exchange_names': 'GOLD - COMMODITY EXCHANGE INC.',
             'latest_report': '2026-10-06T00:00:00.000'},
            {'cftc_contract_market_code': '088695', 'market_and_exchange_names': 'MICRO GOLD - COMMODITY EXCHANGE INC.',
             'latest_report': '2026-10-06T00:00:00.000'}]
    monkeypatch.setattr(cftc_tools, 'socrata', lambda *a, **k: rows)
    with pytest.raises(ValueError, match='matches 2 current markets'):
        cftc_tools.resolve_market('6dca-aqww', 'gold commodity', None)
    assert cftc_tools.resolve_market('6dca-aqww', 'GOLD', None) == '088691'           # exact name wins
    assert cftc_tools.resolve_market('6dca-aqww', '13874a', None) == '13874A'         # a code is not looked up
    tool, _ = _tool('cftc_cot_net_positioning')
    with pytest.raises(ValueError, match='not in the tff report'):
        tool.execute({'market': '13874A', 'report': 'tff', 'category': 'managed_money'})


def test_cftc_app_token_and_shared_throttle(monkeypatch, store):
    seen = {}

    def fake(method, url, params=None, headers=None, **_):
        seen.update(headers or {})
        return outbound.Response(200, 'OK', {'content-type': 'application/json'}, b'[]', url)
    monkeypatch.setattr(outbound, 'request', fake)
    monkeypatch.setenv('CFTC_APP_TOKEN', 'tok-1')
    tool, _ = _tool('cftc_cot_latest')
    out = tool.execute({'market': '13874A', 'report': 'tff', 'kind': 'futures_only'})
    assert seen['X-App-Token'] == 'tok-1' and 'note' in out and store.hits == 1
    assert tool.keyless_fallback is True
    full = _Store(allow=False)
    import sajha.core.state as state
    monkeypatch.setattr(state, 'get_state_store', lambda: full)
    monkeypatch.setattr(cftc_tools, 'THROTTLE_WAIT', 0)
    monkeypatch.setattr(outbound, 'request', lambda *a, **k: pytest.fail('no request past the budget'))
    with pytest.raises(ValueError, match='budget'):
        cftc_tools.socrata('6dca-aqww', {'$limit': '1'})


# ── ONS ──────────────────────────────────────────────────────────────────────

def test_ons_search_and_timeseries():
    found, fake = _replay('ons_search')
    assert found['series'][0]['cdid'] == 'D7G7' and dict(fake.seen[0]['params'])['content_type'] == 'timeseries'
    cpi, fake = _replay('ons_timeseries')
    assert cpi['unit'] == '%' and cpi['frequency'] == 'monthly'
    assert [o['date'] for o in cpi['observations']] == [f'2025-{m:02d}' for m in range(1, 13)]
    assert fake.seen[1]['url'] == 'https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7g7/mm23/data'
    gdp, _ = _replay('ons_timeseries', 'gdp')
    assert gdp['unit'] == '£m' and gdp['frequency'] == 'quarterly' and gdp['observation_count'] == 4
    assert gdp['other_datasets'] and gdp['dataset'] not in gdp['other_datasets']
    assert all(re.fullmatch(r'\d{4}-Q[1-4]', o['date']) for o in gdp['observations'])


def test_ons_dates_and_bad_input():
    assert [ons_tools.ons_date(x) for x in ('2026 AUG', '2026 Q2', '2026', '')] == ['2026-08', '2026-Q2', '2026', None]
    tool, _ = _tool('ons_timeseries')
    with pytest.raises(ValueError, match='four-character'):
        tool.execute({'cdid': 'CPI-ANNUAL'})


def test_ons_takes_both_windows(monkeypatch, store):
    monkeypatch.setattr(outbound, 'request', lambda m, url, **k: outbound.Response(
        200, 'OK', {'content-type': 'application/json'}, b'{"count": 0, "items": []}', url))
    ons_tools.search('nothing')
    assert store.hits == 2


# ── Statistics Canada ────────────────────────────────────────────────────────

def test_statcan_vector_and_table():
    v, fake = _replay('statcan_vector')
    assert v['table'] == '18-10-0004-01' and v['unit'] == '2002=100' and v['frequency'] == 'Monthly'
    assert v['members'] == {'Geography': 'Canada', 'Products and product groups': 'All-items'}
    assert v['source'].startswith('Source: Statistics Canada, Table 18-10-0004-01 Consumer Price Index')
    assert ', 2025-12. Reproduced and distributed on an "as is" basis' in v['source']
    assert ['vectorIds', '"41690973"'] in fake.seen[1]['params']
    t, fake = _replay('statcan_table')
    assert t['vector'] == 'v41690973' and t['observation_count'] == 6
    assert fake.seen[0]['json'] == [{'productId': 18100004, 'coordinate': '2.2.0.0.0.0.0.0.0.0'}]
    dims, _ = _replay('statcan_table', 'dimensions')
    assert dims['dimensions'][0]['name'] == 'Geography' and dims['dimensions'][0]['members'][0]['name'] == 'Canada'


def test_statcan_search_and_changed():
    found, _ = _replay('statcan_search_tables')
    assert [t['table'] for t in found['tables']] == ['18-10-0004-01', '18-10-0006-01']
    changed, _ = _replay('statcan_changed_series')
    assert changed['count'] == len(changed['tables']) > 0
    assert all(re.fullmatch(r'\d{2}-\d{2}-\d{4}-01', t['table']) for t in changed['tables'])


def test_statcan_identifiers():
    assert [statcan_tools.product_id(x) for x in ('18-10-0004-01', '18-10-0004', '1810000401', 18100004)] == [18100004] * 4
    assert statcan_tools.vector_id('v41690973') == 41690973
    assert statcan_tools.coordinate('2.2') == '2.2.0.0.0.0.0.0.0.0'
    assert [statcan_tools.ref_period('2026-04-01', f) for f in (6, 9, 12, 1)] == ['2026-04', '2026-Q2', '2026', '2026-04-01']
    with pytest.raises(ValueError, match='table number'):
        statcan_tools.product_id('CPI')
    tool, _ = _tool('statcan_vector')
    with pytest.raises(ValueError, match='not both'):
        tool.execute({'vector': 'v1', 'latest_n': 3, 'period': '2025'})


def test_statcan_failed_answer_is_an_error(monkeypatch):
    monkeypatch.setattr(outbound, 'request', lambda m, url, **k: outbound.Response(
        200, 'OK', {'content-type': 'application/json'},
        b'[{"status":"FAILED","object":"The cube product ID 99999999 does not exist."}]', url))
    tool, _ = _tool('statcan_table')
    with pytest.raises(ValueError, match='does not exist'):
        tool.execute({'table': '99-99-9999-01'})
