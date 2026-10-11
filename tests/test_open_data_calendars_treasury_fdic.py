# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Phase 8.3 open data, P1 (Open Data Tools §4): the calendars, us_treasury and fdic tool folders.

The calendars are computed offline by the holidays package. The US Treasury and FDIC tools are
played back from responses recorded live on 2026-10-11 (tests/fixtures/open_data/<tool>[__case].json);
no test calls a live service."""

import importlib
import json
import re
from pathlib import Path

import jsonschema
import pytest

from sajha.core import outbound

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / 'config' / 'tools'
FIXTURES = ROOT / 'tests' / 'fixtures' / 'open_data'
FOLDERS = ('calendars', 'us_treasury', 'fdic')


def _configs(folder):
    return [json.loads(p.read_text(encoding='utf-8')) for p in sorted((TOOLS / folder).glob('*.json'))]


def _tool(name):
    folder = {'cal': 'calendars', 'ust': 'us_treasury', 'fdic': 'fdic'}[name.split('_')[0]]
    cfg = json.loads((TOOLS / folder / f'{name}.json').read_text(encoding='utf-8'))
    module, cls = cfg['implementation'].rsplit('.', 1)
    return getattr(importlib.import_module(module), cls)(cfg), cfg


class _Replay:
    """Stands in for outbound.request: answers each call with the next recorded response for that URL."""

    def __init__(self, calls):
        self.queue = list(calls)
        self.seen = []

    def __call__(self, method, url, params=None, headers=None, **_):
        self.seen.append({'url': url, 'params': dict(outbound._param_items(params))})
        for i, call in enumerate(self.queue):
            if call['url'] == url:
                self.queue.pop(i)
                return outbound.Response(call['status'], 'OK', {'content-type': call['content_type'] or ''},
                                         call['body'].encode('utf-8'), url)
        raise AssertionError(f'no recorded response for {url}')


class _Store:
    """A state store with only the sliding window the FDIC throttle uses."""

    def __init__(self, allow=True):
        self.allow, self.hits = allow, 0

    def window_add(self, key, window, limit=None):
        self.hits += 1
        return self.allow, self.hits


@pytest.fixture
def store(monkeypatch):
    s = _Store()
    import sajha.core.state as state
    monkeypatch.setattr(state, 'get_state_store', lambda: s)
    return s


def _run(name, case, monkeypatch):
    fixture = json.loads((FIXTURES / f'{name}{"__" + case if case else ""}.json').read_text(encoding='utf-8'))
    replay = _Replay(fixture['calls'])
    monkeypatch.setattr(outbound, 'request', replay)
    tool, cfg = _tool(name)
    tool.validate_arguments(fixture['arguments'])
    result = tool.execute(fixture['arguments'])
    jsonschema.validate(result, cfg['outputSchema'])
    assert not replay.queue, 'every recorded response is used'
    return result, replay


# ── the configs ──────────────────────────────────────────────────────────────

ALL = [(f, c) for f in FOLDERS for c in _configs(f)]


@pytest.mark.parametrize('folder,cfg', ALL, ids=[c['name'] for _, c in ALL])
def test_configs_follow_the_open_data_rules(folder, cfg):
    ann = cfg['annotations']
    assert ann['readOnlyHint'] is True and ann['idempotentHint'] is True
    assert ann['openWorldHint'] is (folder != 'calendars')        # calendars are offline
    example = json.loads(re.search(r'\nExample: (\{.*\})\s*$', cfg['description']).group(1))
    assert cfg['inputSchema']['examples'][0] == example
    jsonschema.validate(example, cfg['inputSchema'])
    domain = (TOOLS / folder / 'domain.txt').read_text(encoding='utf-8').strip()
    assert len(domain) <= 600
    assert len(cfg['description']) + 2 + len(domain) <= 1024
    for prop in cfg['inputSchema'].get('required', []):
        assert 'default' not in cfg['inputSchema']['properties'][prop]
    if folder == 'calendars':
        assert cfg['requires'] == ['holidays']
    if folder == 'fdic':
        assert cfg['cache_ttl'] > 0


def test_every_networked_tool_has_a_recorded_fixture():
    for folder in ('us_treasury', 'fdic'):
        for cfg in _configs(folder):
            assert (FIXTURES / f'{cfg["name"]}.json').exists(), cfg['name']


# ── calendars ────────────────────────────────────────────────────────────────

def _cal(name, **args):
    pytest.importorskip('holidays')
    tool, cfg = _tool(name)
    tool.validate_arguments(args)
    result = tool.execute(args)
    jsonschema.validate(result, cfg['outputSchema'])
    return result


def test_market_and_country_holidays():
    nyse = _cal('cal_holidays', market='XNYS', year=2026)
    assert nyse['kind'] == 'market' and nyse['calendar'] == 'XNYS'
    names = {h['date']: h['name'] for h in nyse['holidays']}
    assert names['2026-11-26'] == 'Thanksgiving Day' and '2026-06-19' in names
    assert '2026-11-11' not in names                            # Veterans Day: the exchange is open
    on = _cal('cal_holidays', country='CA', subdivision='ON', **{'from': '2026-07-01', 'to': '2026-09-30'})
    assert on['calendar'] == 'CA-ON' and [h['date'] for h in on['holidays']] == ['2026-07-01', '2026-09-07']
    assert _cal('cal_holidays', market='NYSE', year=2026)['count'] == nyse['count']      # an alias
    assert _cal('cal_holidays', country='USA', year=2026)['calendar'] == 'US'           # alpha-3
    with pytest.raises(ValueError, match='exactly one'):
        _cal('cal_holidays', year=2026)
    with pytest.raises(ValueError, match='unknown market'):
        _cal('cal_holidays', market='ZZZZ')
    with pytest.raises(ValueError, match='no subdivision'):
        _cal('cal_holidays', country='CA', subdivision='XX')


def test_business_day_in_all_calendars():
    r = _cal('cal_is_business_day', date='2026-11-26', calendars=['XNYS', 'CA'])
    assert r['is_business_day'] is False
    assert r['calendars'] == [{'calendar': 'XNYS', 'is_business_day': False, 'reason': 'Thanksgiving Day'},
                              {'calendar': 'CA', 'is_business_day': True, 'reason': None}]
    assert (r['previous_business_day'], r['next_business_day']) == ('2026-11-25', '2026-11-27')
    sat = _cal('cal_is_business_day', date='2026-10-10', calendars=['GB'])
    assert sat['calendars'][0]['reason'] == 'weekend'


def test_counting_adding_settling_and_adjusting():
    between = _cal('cal_business_days_between', calendars=['US', 'GB'], **{'from': '2026-12-01', 'to': '2027-01-04'})
    assert between['business_days'] == 21 and between['calendar_days'] == 34
    assert [h['date'] for h in between['holidays_on_weekdays']] == ['2026-12-25', '2026-12-28', '2027-01-01']
    back = _cal('cal_business_days_between', calendars=['US'], **{'from': '2027-01-04', 'to': '2026-12-01'})
    assert back['business_days'] < 0
    assert _cal('cal_add_business_days', date='2026-12-23', days=3, calendars=['XNYS'])['result'] == '2026-12-29'
    assert _cal('cal_add_business_days', date='2026-12-24', days=-3, calendars=['US'])['result'] == '2026-12-21'
    assert _cal('cal_add_business_days', date='2026-10-10', days=0, calendars=['US'])['result'] == '2026-10-13'
    t1 = _cal('cal_settlement_date', trade_date='2026-11-25', convention='T+1', calendars=['XNYS'])
    assert t1['settlement_date'] == '2026-11-27' and t1['trade_date_is_business_day'] is True
    mf = _cal('cal_adjust_date', date='2026-10-31', rule='modified_following', calendars=['XLON'])
    assert mf['adjusted'] == '2026-10-30' and mf['changed'] is True                     # stays in October
    assert _cal('cal_adjust_date', date='2026-10-31', rule='following', calendars=['XLON'])['adjusted'] == '2026-11-02'
    assert _cal('cal_adjust_date', date='2026-10-30', rule='preceding', calendars=['XLON'])['changed'] is False
    with pytest.raises(ValueError, match='unknown calendar'):
        _cal('cal_is_business_day', date='2026-10-30', calendars=['Narnia'])


# ── US Treasury ──────────────────────────────────────────────────────────────

def test_yield_curves(monkeypatch):
    nominal, replay = _run('ust_yield_curve', '', monkeypatch)
    assert nominal['count'] == 1 and list(nominal['observations'][0]['yields']) == ['2Y', '10Y', '30Y']
    assert replay.seen[0]['params']['type'] == 'daily_treasury_yield_curve'
    bills, _ = _run('ust_yield_curve', 'bills', monkeypatch)
    obs = bills['observations'][0]
    assert obs['date'] == '2026-10-09'                          # the last curve before a Saturday
    assert set(obs['yields']) == set(obs['bank_discount']) == {'4W', '52W'}
    real, replay = _run('ust_yield_curve', 'real_range', monkeypatch)
    assert [o['date'] for o in real['observations']][:2] == ['2025-12-29', '2025-12-30']
    assert real['tenors'] == ['5Y', '7Y', '10Y', '20Y', '30Y'] and len(replay.seen) == 2     # one file per year


def test_tenor_names():
    from sajha.tools.impl.us_treasury_tools import tenor_of
    assert [tenor_of(c) for c in ('1 Mo', '1.5 Month', '10 Yr', '4 WEEKS BANK DISCOUNT', 'Date')] == \
        ['1M', '1.5M', '10Y', '4W', None]


def test_fiscal_data_tools(monkeypatch):
    debt, replay = _run('ust_debt_to_the_penny', '', monkeypatch)
    assert debt['count'] > 10 and debt['records'][0]['date'] == '2026-09-01'
    assert isinstance(debt['records'][0]['total_public_debt_outstanding'], float)
    assert 'record_date:gte:2026-09-01' in replay.seen[0]['params']['filter']
    latest, replay = _run('ust_debt_to_the_penny', 'latest', monkeypatch)
    assert latest['count'] == 1 and replay.seen[0]['params']['page[size]'] == '1'
    rates, _ = _run('ust_average_interest_rates', '', monkeypatch)
    assert rates['records'] and all('Notes' in r['security'] for r in rates['records'])
    auctions, replay = _run('ust_auctions', '', monkeypatch)
    assert 'original_security_term:eq:10-Year' in replay.seen[0]['params']['filter']
    assert all(a['tips'] is False and a['frn'] is False for a in auctions['auctions'])
    dts, replay = _run('ust_daily_treasury_statement', '', monkeypatch)
    assert len(replay.seen) == 2 and dts['units'] == 'millions of US dollars'
    assert dts['rows'] and 'table_nbr' not in dts['rows'][0]
    assert all(r['open_today_bal'] is None or isinstance(r['open_today_bal'], int) for r in dts['rows'])
    fx, replay = _run('ust_exchange_rates', '', monkeypatch)
    assert fx['rates'] and {r['currency'] for r in fx['rates']} == {'Euro'}
    assert 'country_currency_desc:eq:Euro Zone-Euro' in replay.seen[0]['params']['filter']
    korea, _ = _run('ust_exchange_rates', 'country', monkeypatch)
    assert [r['country'] for r in korea['rates']] == ['Korea']        # ISO KR to Treasury's name


def test_periods():
    from datetime import date
    from sajha.tools.impl.us_treasury_tools import parse_period
    today = date(2026, 10, 11)
    assert parse_period('2025-Q3', today) == (date(2025, 7, 1), date(2025, 9, 30))
    assert parse_period('2025-02', today) == (date(2025, 2, 1), date(2025, 2, 28))
    assert parse_period('2024', today) == (date(2024, 1, 1), date(2024, 12, 31))
    assert parse_period('last 4 quarters', today) == (date(2025, 10, 11), today)
    assert parse_period('2025-01-01:2025-03-31', today) == (date(2025, 1, 1), date(2025, 3, 31))
    with pytest.raises(ValueError, match='not understood'):
        parse_period('soon', today)


# ── FDIC ─────────────────────────────────────────────────────────────────────

def test_fdic_tools(monkeypatch, store):
    inst, replay = _run('fdic_institutions', '', monkeypatch)
    assert inst['institutions'][0]['cert'] == 24735 and inst['institutions'][0]['active'] is False
    assert replay.seen[0]['params']['search'] == 'NAME:Silicon Valley Bank'
    vt, replay = _run('fdic_institutions', 'state', monkeypatch)
    assert 'STALP:VT AND ACTIVE:1' == replay.seen[0]['params']['filters']
    fin, _ = _run('fdic_financials', '', monkeypatch)
    assert fin['units']['total_assets'].startswith('amounts in thousands')
    assert all(re.fullmatch(r'\d{4}-Q[1-4]', q['quarter']) for q in fin['quarters'])
    fail, _ = _run('fdic_failures', '', monkeypatch)
    assert 'SILICON VALLEY BANK' in {f['name'] for f in fail['failures']}
    assert all(re.fullmatch(r'\d{4}-\d{2}-\d{2}', f['failure_date']) for f in fail['failures'])
    loc, _ = _run('fdic_locations', '', monkeypatch)
    assert loc['offices'] and all(o['state'] == 'VT' for o in loc['offices'])
    hist, replay = _run('fdic_history', '', monkeypatch)
    assert 'NOT ORG_ROLE_CDE:BR' in replay.seen[0]['params']['filters']
    assert all(e['level'] == 'institution' for e in hist['events'])
    sod, _ = _run('fdic_summary_of_deposits', '', monkeypatch)
    assert sod['as_of'] == '2025-06-30' and sod['total_deposits_listed'] > 0
    assert store.hits == 7                                     # one throttle slot per request


def test_fdic_throttle_is_shared_and_gives_up(monkeypatch):
    from sajha.tools.impl import fdic_tools
    import sajha.core.state as state
    full = _Store(allow=False)
    monkeypatch.setattr(state, 'get_state_store', lambda: full)
    monkeypatch.setattr(fdic_tools, 'THROTTLE_WAIT', 0)
    monkeypatch.setattr(outbound, 'request', lambda *a, **k: pytest.fail('no request past the budget'))
    with pytest.raises(ValueError, match='budget'):
        fdic_tools.fdic('institutions', {'filters': 'CERT:628'})


def test_fdic_optional_key_and_dates(monkeypatch, store):
    from sajha.tools.impl import fdic_tools
    replay = _Replay([{'url': f'{fdic_tools.BASE}/failures', 'status': 200, 'content_type': 'application/json',
                       'body': '{"meta": {"total": 0}, "data": []}'}])
    monkeypatch.setattr(outbound, 'request', replay)
    monkeypatch.setenv('FDIC_API_KEY', 'k-123')
    fdic_tools.fdic('failures', {'limit': 1})
    assert replay.seen[0]['params']['api_key'] == 'k-123'
    assert [fdic_tools.us_date(v) for v in ('7/17/2026', '2026-09-22T00:00:00', '20260630', '12/31/9999', '')] == \
        ['2026-07-17', '2026-09-22', '2026-06-30', None, None]
