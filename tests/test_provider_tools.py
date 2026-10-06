"""Provider tool regressions: PBoC / BoJ (FRED), FBI (api.data.gov key), UN Comtrade,
duckdb_sql, and the OLAP pivot / time-series tools. All HTTP is mocked."""
import io
import json
import urllib.parse
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _config(name: str) -> dict:
    return json.loads((ROOT / 'config' / 'tools' / f'{name}.json').read_text())


class _Resp(io.BytesIO):
    """Minimal stand-in for an HTTPResponse usable as a context manager."""
    headers = {}

    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def info(self):
        return self.headers

    def getheader(self, *_a, **_k):
        return None


class _Recorder:
    """Patches urllib.request.urlopen; records each Request and answers via ``responder``."""

    def __init__(self, responder):
        self.responder = responder
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        return _Resp(self.responder(req))


def _query(req) -> dict:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(req.full_url).query))


FRED_PAYLOAD = {'observations': [{'date': '2024-01-01', 'value': '1.5'},
                                 {'date': '2024-02-01', 'value': '.'},
                                 {'date': '2024-03-01', 'value': '1.7'}]}


# ── PBoC / BoJ (FRED) ────────────────────────────────────────────────────────

@pytest.mark.parametrize('module, cls, args, series', [
    ('china_central_bank', 'PBoCGetCGBYieldTool', {'bond_term': '10y'}, 'IRLTLT01CNM156N'),
    ('japan_central_bank', 'BoJGetJGBYieldTool', {'bond_term': '10y'}, 'IRLTLT01JPM156N'),
    ('japan_central_bank', 'BoJGetPolicyRateTool', {'rate_type': 'policy_rate'}, 'IRSTCI01JPM156N'),
    ('japan_central_bank', 'BoJGetInflationTool', {'index_type': 'core_cpi'}, 'JPNCPICORMINMEI'),
])
def test_fred_backed_central_bank_tools_use_configured_key(module, cls, args, series, monkeypatch):
    import importlib
    monkeypatch.delenv('FRED_API_KEY', raising=False)
    tool_cls = getattr(importlib.import_module(f'sajha.tools.impl.{module}'), cls)
    tool = tool_cls({'api_key': 'fred-test-key'})
    rec = _Recorder(lambda req: FRED_PAYLOAD)
    with mock.patch('urllib.request.urlopen', rec):
        result = tool.execute(args)
    q = _query(rec.requests[0])
    assert q['api_key'] == 'fred-test-key'
    assert q['series_id'] == series
    assert [o['value'] for o in result['observations']] == [1.5, 1.7]


def test_fred_key_falls_back_to_env_and_rejects_unresolved_placeholder(monkeypatch):
    from sajha.tools.impl.china_central_bank import PBoCGetMoneySupplyTool
    monkeypatch.setenv('FRED_API_KEY', 'from-env')
    tool = PBoCGetMoneySupplyTool({'api_key': '${fred.api.key}'})
    assert tool._get_api_key() == 'from-env'

    monkeypatch.delenv('FRED_API_KEY')
    tool = PBoCGetMoneySupplyTool({'api_key': '${fred.api.key}'})
    with pytest.raises(ValueError, match='FRED API key not configured'):
        tool._get_api_key()


def test_boj_eur_jpy_is_a_cross_rate(monkeypatch):
    from sajha.tools.impl.japan_central_bank import BoJGetExchangeRateTool

    def responder(req):
        sid = _query(req)['series_id']
        if sid == 'DEXJPUS':
            return {'observations': [{'date': '2024-01-02', 'value': '150'}, {'date': '2024-01-03', 'value': '151'}]}
        return {'observations': [{'date': '2024-01-02', 'value': '1.1'}]}

    rec = _Recorder(responder)
    with mock.patch('urllib.request.urlopen', rec):
        result = BoJGetExchangeRateTool({'api_key': 'k'}).execute({'currency_pair': 'eur_jpy'})
    assert result['observations'] == [{'date': '2024-01-02', 'value': 165.0}]


def test_boj_configs_match_implementation():
    """Every enum value the BoJ configs advertise must be accepted by the implementation."""
    from sajha.tools.impl import japan_central_bank as m
    cases = {
        'boj_get_jgb_yield': (m.BoJGetJGBYieldTool, 'bond_term'),
        'boj_get_policy_rate': (m.BoJGetPolicyRateTool, 'rate_type'),
        'boj_get_exchange_rate': (m.BoJGetExchangeRateTool, 'currency_pair'),
        'boj_get_money_supply': (m.BoJGetMoneySupplyTool, 'aggregate'),
        'boj_get_inflation': (m.BoJGetInflationTool, 'index_type'),
    }
    for name, (cls, param) in cases.items():
        cfg = _config(name)
        assert cfg['api_key'] == '${fred.api.key}'
        tool = cls(dict(cfg, api_key='k'))
        for value in cfg['inputSchema']['properties'][param]['enum']:
            rec = _Recorder(lambda req: FRED_PAYLOAD)
            with mock.patch('urllib.request.urlopen', rec):
                result = tool.execute({param: value})
            assert 'error' not in result, (name, value, result)
            assert rec.requests, (name, value)


# ── FBI ──────────────────────────────────────────────────────────────────────

def test_fbi_sends_api_key_header(monkeypatch):
    from sajha.tools.impl.fbi_tool_refactored import FBIGetNationalStatisticsTool
    monkeypatch.delenv('FBI_API_KEY', raising=False)
    monkeypatch.delenv('DATA_GOV_API_KEY', raising=False)
    tool = FBIGetNationalStatisticsTool({'api_key': 'fbi-test-key'})
    rec = _Recorder(lambda req: {'total_incidents': 1000, 'population': 100000})
    with mock.patch('urllib.request.urlopen', rec):
        result = tool.execute({'offense_type': 'robbery', 'year': 2022})
    assert rec.requests[0].get_header('X-api-key') == 'fbi-test-key'
    assert result['national_data']['rate_per_100k'] == 1000.0


def test_fbi_key_resolution(monkeypatch):
    from sajha.tools.impl.fbi_tool_refactored import FBIGetNationalStatisticsTool
    monkeypatch.delenv('FBI_API_KEY', raising=False)
    monkeypatch.delenv('DATA_GOV_API_KEY', raising=False)
    assert FBIGetNationalStatisticsTool({'api_key': '${fbi.api.key:}'}).api_key == 'DEMO_KEY'
    monkeypatch.setenv('FBI_API_KEY', 'env-key')
    assert FBIGetNationalStatisticsTool({'api_key': ''}).api_key == 'env-key'
    for name in ('fbi_get_national_statistics', 'fbi_compare_states', 'fbi_search_agencies'):
        assert _config(name)['api_key'] == '${fbi.api.key:}'


# ── UN Comtrade ──────────────────────────────────────────────────────────────

def _comtrade_rows(reporter, rows):
    return {'count': len(rows), 'error': '', 'data': [
        {'reporterCode': reporter, 'partner2Code': 0, 'customsCode': 'C00', 'motCode': 0, 'cmdCode': 'TOTAL', **r}
        for r in rows]}


def test_un_trade_balance_calls_comtrade_preview(monkeypatch):
    from sajha.tools.impl.united_nations_tool_refactored import UNGetTradeBalanceTool
    monkeypatch.delenv('COMTRADE_API_KEY', raising=False)
    rec = _Recorder(lambda req: _comtrade_rows(842, [
        {'flowCode': 'X', 'partnerCode': 156, 'primaryValue': 150.0},
        {'flowCode': 'M', 'partnerCode': 156, 'primaryValue': 500.0},
    ]))
    with mock.patch('urllib.request.urlopen', rec):
        result = UNGetTradeBalanceTool().execute({'country_code': 'USA', 'partner_code': 'CHN', 'year': 2022})
    req = rec.requests[0]
    assert req.full_url.startswith('https://comtradeapi.un.org/public/v1/preview/C/A/HS?')
    q = _query(req)
    assert (q['reporterCode'], q['partnerCode'], q['period'], q['flowCode']) == ('842', '156', '2022', 'X,M')
    assert result['data'] == {'exports': 150.0, 'imports': 500.0, 'balance': -350.0}


def test_un_trade_data_commodity_group_and_subscription_key(monkeypatch):
    from sajha.tools.impl.united_nations_tool_refactored import UNGetTradeDataTool
    monkeypatch.setenv('COMTRADE_API_KEY', 'sub-key')
    rec = _Recorder(lambda req: _comtrade_rows(276, [
        {'flowCode': 'X', 'partnerCode': 0, 'primaryValue': 10.0},
        {'flowCode': 'X', 'partnerCode': 0, 'primaryValue': 5.0},
    ]))
    with mock.patch('urllib.request.urlopen', rec):
        result = UNGetTradeDataTool().execute({'reporter_code': 'DEU', 'commodity_code': 'mineral', 'year': 2021})
    req = rec.requests[0]
    assert req.full_url.startswith('https://comtradeapi.un.org/data/v1/get/C/A/HS?')
    assert req.get_header('Ocp-apim-subscription-key') == 'sub-key'
    assert _query(req)['cmdCode'] == '25,26,27'
    assert result['total_value'] == 15.0 and result['record_count'] == 2


def test_un_country_trade_and_compare(monkeypatch):
    from sajha.tools.impl.united_nations_tool_refactored import UNGetCountryTradeTool, UNCompareCountryTradeTool
    monkeypatch.delenv('COMTRADE_API_KEY', raising=False)
    rows = [
        {'flowCode': 'X', 'partnerCode': 0, 'primaryValue': 300.0},
        {'flowCode': 'X', 'partnerCode': 124, 'partnerDesc': 'Canada', 'primaryValue': 100.0},
        {'flowCode': 'X', 'partnerCode': 484, 'partnerDesc': 'Mexico', 'primaryValue': 120.0},
        {'flowCode': 'M', 'partnerCode': 0, 'primaryValue': 400.0},
        # partner2 breakdown rows must not be double counted
        {'flowCode': 'M', 'partnerCode': 0, 'primaryValue': 999.0, 'partner2Code': 4},
    ]

    with mock.patch('urllib.request.urlopen', _Recorder(lambda req: _comtrade_rows(842, rows))):
        result = UNGetCountryTradeTool().execute({'country_code': 'USA', 'year': 2022})
    assert result['exports']['total_value'] == 300.0
    assert result['imports']['total_value'] == 400.0
    assert result['trade_balance'] == -100.0
    assert [p['partner'] for p in result['exports']['top_partners']] == ['Mexico', 'Canada']

    def per_country(req):
        reporter = int(_query(req)['reporterCode'])
        return _comtrade_rows(reporter, [{'flowCode': 'X', 'partnerCode': 0,
                                          'primaryValue': {842: 2.0, 156: 3.0}[reporter]}])

    with mock.patch('urllib.request.urlopen', _Recorder(per_country)):
        result = UNCompareCountryTradeTool().execute({'country_codes': ['USA', 'CHN'], 'year': 2022})
    ranks = {c['country_code']: c['rank'] for c in result['countries']}
    assert ranks == {'CHN': 1, 'USA': 2}


def test_un_unknown_country_is_a_clear_error(monkeypatch):
    from sajha.tools.impl.united_nations_tool_refactored import UNGetTradeBalanceTool
    tool = UNGetTradeBalanceTool()
    with mock.patch.object(tool, '_load_reference', return_value={}):
        with pytest.raises(ValueError, match='Unknown country code'):
            tool.execute({'country_code': 'XYZ'})


# ── duckdb_sql ───────────────────────────────────────────────────────────────

def test_duckdb_sql_appends_limit(tmp_path):
    from sajha.tools.impl.duckdb_olap_advanced import DuckDBSQLTool
    (tmp_path / 'customers.csv').write_text('id,region\n1,North\n2,South\n3,North\n')
    tool = DuckDBSQLTool({'name': 'duckdb_sql', 'data_directory': str(tmp_path)})  # orders/products missing: tolerated

    r = tool.execute({'sql': 'SELECT * FROM customers ORDER BY id', 'limit': 2})
    assert r['success'], r
    assert r['row_count'] == 2 and r['sql'].endswith('LIMIT 2')

    r = tool.execute({'sql': 'SELECT * FROM customers LIMIT 3;', 'limit': 1})
    assert r['success'] and r['row_count'] == 3          # caller's own LIMIT respected

    r = tool.execute({'sql': 'DESCRIBE customers'})
    assert r['success'] and 'LIMIT' not in r['sql']      # no LIMIT on non-SELECT statements

    r = tool.execute({'sql': 'DROP TABLE customers'})
    assert not r['success']


# ── OLAP pivot / time series ─────────────────────────────────────────────────

@pytest.fixture(scope='module')
def olap_tools():
    from sajha.tools.impl.duckdb_olap_advanced import DuckDBOLAPAdvancedTool
    return {name: DuckDBOLAPAdvancedTool(_config(name)) for name in ('olap_pivot_table', 'olap_time_series')}


def test_olap_tools_advertise_their_own_schema(olap_tools):
    assert olap_tools['olap_pivot_table'].input_schema['required'] == ['dataset', 'rows', 'values']
    assert 'time_grain' in olap_tools['olap_time_series'].input_schema['properties']


def test_olap_pivot_table_examples(olap_tools):
    tool = olap_tools['olap_pivot_table']
    for example in _config('olap_pivot_table')['examples']:
        result = tool.execute(example['input'])
        assert result.get('success'), result
        assert result['data']
    json.dumps(result)  # JSON-serializable (no Decimal / date objects)


def test_olap_time_series_examples(olap_tools):
    tool = olap_tools['olap_time_series']
    for example in _config('olap_time_series')['examples']:
        result = tool.execute(example['input'])
        assert result.get('success'), result
        assert len(result['data']) >= 12
    assert 'revenue_pct_change' in result['data'][-1]
    json.dumps(result)


def test_olap_execute_inside_running_event_loop(olap_tools):
    import asyncio

    async def call():
        return olap_tools['olap_time_series'].execute(
            {'dataset': 'sales_analysis', 'time_dimension': 'date', 'time_grain': 'quarter', 'measures': ['revenue']})

    assert asyncio.run(call())['success']


def test_un_comtrade_retries_on_rate_limit(monkeypatch):
    import urllib.error
    from sajha.tools.impl import united_nations_tool_refactored as un
    monkeypatch.delenv('COMTRADE_API_KEY', raising=False)
    monkeypatch.setattr(un.time, 'sleep', lambda s: None)
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, 'Too Many Requests', {}, None)
        return _Resp(_comtrade_rows(842, [{'flowCode': 'X', 'partnerCode': 0, 'primaryValue': 7.0},
                                          {'flowCode': 'M', 'partnerCode': 0, 'primaryValue': 2.0}]))

    with mock.patch('urllib.request.urlopen', urlopen):
        result = un.UNGetTradeBalanceTool().execute({'country_code': 'USA', 'year': 2022})
    assert len(calls) == 2 and result['data']['balance'] == 5.0
