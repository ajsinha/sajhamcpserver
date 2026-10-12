# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Phase 8.1 broken-tool fixes (Roadmap L22, part 2): the shared SDMX client and the ECB, Banque de
France and IMF tools on it; the FRED key rule (no invented data); PBoC and BoJ series; UN SDG data;
EDGAR, CoinGecko, Wikipedia, FRED, World Bank and FBI fixes; and every changed tool's description
example validating against its schema. All network access is faked."""

import importlib
import io
import json
import re
import urllib.parse
from pathlib import Path
from unittest import mock

import pytest

from sajha.core import outbound
from sajha.tools.impl import sdmx_client
from tests.tool_config_files import read_tool, tool_file

ROOT = Path(__file__).resolve().parent.parent


# ── fakes ────────────────────────────────────────────────────────────────────

class _Http:
    """Stands in for outbound.request; records (url, params, headers) and answers from a function."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, method, url, params=None, headers=None, timeout=None, max_bytes=None, **_):
        self.calls.append({'url': url, 'params': dict(params or []), 'headers': headers or {}})
        status, body, ctype = self.answer(url, dict(params or []))
        return outbound.Response(status, 'OK' if status < 400 else 'ERR', {'content-type': ctype},
                                 body.encode('utf-8'), url)


ECB_CSV = (
    'KEY,FREQ,REF_AREA,ADJUSTMENT,ICP_ITEM,STS_INSTITUTION,ICP_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS,TITLE,UNIT,UNIT_MULT\n'
    'HICP.M.U2.N.000000.4D0.ANR,M,U2,N,000000,4D0,ANR,2026-08,3.2,A,"HICP, annual rate",PCCH,0\n'
    'HICP.M.U2.N.000000.4D0.ANR,M,U2,N,000000,4D0,ANR,2026-09,3.8,A,"HICP, annual rate",PCCH,0\n')

IMF_CSV = (
    'DATAFLOW,COUNTRY,INDICATOR,FREQUENCY,TIME_PERIOD,OBS_VALUE,SCALE,SERIES_NAME,LATEST_ACTUAL_ANNUAL_DATA\n'
    'IMF.RES:WEO(9.0.0),USA,NGDP_RPCH,A,2025,2.1,0,"GDP, constant prices, percent change",2025\n'
    'IMF.RES:WEO(9.0.0),USA,NGDP_RPCH,A,2024,2.8,0,"GDP, constant prices, percent change",2025\n'
    'IMF.RES:WEO(9.0.0),DEU,NGDP_RPCH,A,2025,0.2,0,"GDP, constant prices, percent change",2025\n')


def _csv(body):
    return lambda url, params: (200, body, 'text/csv')


@pytest.fixture(autouse=True)
def _fresh_structure_cache():
    sdmx_client.clear_cache()
    yield
    sdmx_client.clear_cache()


# ── the SDMX client ──────────────────────────────────────────────────────────

def test_sdmx_csv_parsing_ecb_and_imf_flavours():
    ecb = sdmx_client.parse_sdmx_csv(ECB_CSV)
    assert len(ecb) == 1 and ecb[0]['key'] == 'M.U2.N.000000.4D0.ANR'
    assert ecb[0]['attributes']['UNIT'] == 'PCCH'
    assert [o['value'] for o in ecb[0]['observations']] == [3.2, 3.8]
    imf = sdmx_client.parse_sdmx_csv(IMF_CSV)
    assert [s['key'] for s in imf] == ['USA.NGDP_RPCH.A', 'DEU.NGDP_RPCH.A']
    assert [o['period'] for o in imf[0]['observations']] == ['2024', '2025']      # sorted oldest first
    # the IMF answers an empty selection with one blank row; monthly periods are normalised
    blank = 'DATAFLOW,COUNTRY,INDICATOR,FREQUENCY,TIME_PERIOD,OBS_VALUE\n,,,,,\n'
    assert sdmx_client.parse_sdmx_csv(blank) == []
    monthly = 'DATAFLOW,COUNTRY,FREQUENCY,TIME_PERIOD,OBS_VALUE\nX,CHN,M,2026-M08,0.8\nX,CHN,M,2026-M07,NaN\n'
    assert sdmx_client.parse_sdmx_csv(monthly)[0]['observations'] == [
        {'period': '2026-07', 'value': None}, {'period': '2026-08', 'value': 0.8}]


def test_sdmx_json_parsing():
    msg = {'dataSets': [{'series': {'0:1': {'attributes': [0], 'observations': {'0': [1.5], '1': [2.5]}}}}],
           'structure': {'dimensions': {
               'series': [{'id': 'FREQ', 'values': [{'id': 'M'}]}, {'id': 'REF_AREA', 'values': [{'id': 'X'}, {'id': 'FR'}]}],
               'observation': [{'id': 'TIME_PERIOD', 'values': [{'id': '2026-01'}, {'id': '2026-02'}]}]},
               'attributes': {'series': [{'id': 'TITLE', 'values': [{'name': 'A title'}]}]}}}
    s = sdmx_client.parse_sdmx_json(msg)
    assert s == [{'key': 'M.FR', 'dimensions': {'FREQ': 'M', 'REF_AREA': 'FR'}, 'attributes': {'TITLE': 'A title'},
                  'observations': [{'period': '2026-01', 'value': 1.5}, {'period': '2026-02', 'value': 2.5}]}]


def test_sdmx_fetch_host_profiles_go_through_the_outbound_guard():
    http = _Http(_csv(ECB_CSV))
    with mock.patch.object(outbound, 'request', http):
        out = sdmx_client.fetch('ecb', 'HICP', 'M.U2.N.000000.4D0.ANR', last_n=2)
    call = http.calls[0]
    assert call['url'] == 'https://data-api.ecb.europa.eu/service/data/HICP/M.U2.N.000000.4D0.ANR'
    assert call['params'] == {'lastNObservations': '2', 'format': 'csvdata'}
    assert out['series'][0]['observations'][-1]['value'] == 3.8 and 'ECB' in out['source']

    http = _Http(_csv(IMF_CSV))
    with mock.patch.object(outbound, 'request', http):
        sdmx_client.fetch('imf', 'WEO', 'USA.NGDP_RPCH.A', agency='IMF.RES', start='2024', end='2025')
    call = http.calls[0]
    assert call['url'] == 'https://api.imf.org/external/sdmx/2.1/data/IMF.RES,WEO/USA.NGDP_RPCH.A'
    assert call['params'] == {'startPeriod': '2024', 'endPeriod': '2025'}
    assert call['headers']['Accept'].startswith('application/vnd.sdmx.data+csv')


def test_sdmx_no_records_is_empty_and_errors_are_sdmx_errors():
    with mock.patch.object(outbound, 'request', _Http(lambda u, p: (404, 'NoRecordsFound', 'text/plain'))):
        assert sdmx_client.fetch('ecb', 'FM', 'D.U2.EUR.4F.KR.EON.LEV')['series'] == []
    with mock.patch.object(outbound, 'request', _Http(lambda u, p: (500, '<h1>boom</h1>', 'text/html'))):
        with pytest.raises(sdmx_client.SdmxError, match='HTTP 500'):
            sdmx_client.fetch('ecb', 'FM', 'X')

    def refuse(*a, **k):
        raise outbound.Refused('blocked')
    with mock.patch.object(outbound, 'request', refuse):
        with pytest.raises(sdmx_client.SdmxError, match='could not reach'):
            sdmx_client.fetch('imf', 'CPI', 'X')
    with pytest.raises(sdmx_client.SdmxError, match='Unknown SDMX host'):
        sdmx_client.fetch('nowhere', 'X', 'Y')


def test_sdmx_fetch_series_flat_shape():
    with mock.patch.object(outbound, 'request', _Http(_csv(ECB_CSV))):
        out = sdmx_client.fetch_series('ecb', 'HICP', 'M.U2.N.000000.4D0.ANR', last_n=2)
    assert out['series_code'] == 'HICP.M.U2.N.000000.4D0.ANR'
    assert out['label'] == 'HICP, annual rate' and out['unit'] == 'PCCH' and out['frequency'] == 'Monthly'
    assert out['observations'] == [{'date': '2026-08', 'value': 3.2}, {'date': '2026-09', 'value': 3.8}]


def test_country_codes():
    from sajha.tools.impl.country_codes import name, to_alpha3, to_m49
    assert to_alpha3('us') == 'USA' and to_alpha3('IND') == 'IND' and to_alpha3('356') == 'IND'
    assert to_m49('USA') == '840' and to_m49('in') == '356' and to_m49('1') == '1'
    assert to_alpha3('XYZ') is None and to_m49('XYZ') is None and name('FR') == 'France'


# ── Banque de France and ECB on the SDMX client ──────────────────────────────

def test_bdf_series_keys_and_recent_periods():
    from sajha.tools.impl import france_central_bank as bdf
    seen = []

    def fake(host, flow, key, start=None, end=None, last_n=None, **_):
        seen.append((host, flow, key, start, end, last_n))
        return {'flow': flow, 'key': key, 'observations': [], 'observation_count': 0}
    with mock.patch.object(sdmx_client, 'fetch_series', fake):
        bdf.BdFGetOATYieldTool({'name': 'bdf_get_oat_yield'}).execute({})
        bdf.BdFGetEurozoneIndicatorTool({'name': 'x'}).execute({'indicator': 'm3', 'start_date': '2025-01'})
        bdf.BdFGetFrenchEconomicIndicatorTool({'name': 'x'}).execute({'indicator': 'fr_cpi', 'recent_periods': 3})
    assert seen[0] == ('ecb', 'IRS', 'M.FR.L.L40.CI.0000.EUR.N.Z', None, None, 10)    # default recent_periods
    assert seen[1] == ('ecb', 'BSI', 'M.U2.Y.V.M30.X.I.U2.2300.Z01.A', '2025-01', None, None)
    assert seen[2] == ('ecb', 'HICP', 'M.FR.N.000000.4D0.ANR', None, None, 3)
    # one series per label: OAT has only the term the ECB publishes
    assert bdf.BdFGetOATYieldTool({'name': 'x'}).get_input_schema()['properties']['bond_term']['enum'] == ['10y']
    keys = [k for _, k in bdf.SERIES.values()]
    assert len(keys) == len(set(keys))
    with pytest.raises(ValueError, match='Invalid bond_term'):
        bdf.BdFGetOATYieldTool({'name': 'x'}).execute({'bond_term': '30y'})


def test_ecb_latest_and_common_indicators_ask_for_the_last_observation():
    from sajha.tools.impl import european_central_bank_tool_refactored as ecb
    calls = []

    def fake(host, flow, key, start=None, end=None, last_n=None, **_):
        calls.append((flow, key, last_n))
        return {'flow': flow, 'key': key, 'label': 't', 'observations': [{'date': '2026-Q2', 'value': 1.0}],
                'observation_count': 1}
    with mock.patch.object(sdmx_client, 'fetch_series', fake):
        out = ecb.ECBGetLatestTool(read_tool('ecb_get_latest')).execute({'indicator': 'gdp'})
        assert out['date'] == '2026-Q2'
        dash = ecb.ECBGetCommonIndicatorsTool(read_tool('ecb_get_common_indicators')).execute({})
    assert calls[0] == ('MNA', 'Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.N', 1)
    assert all(c[2] == 1 for c in calls) and len(calls) == 1 + len(dash['indicators'])
    assert 'eonia' not in ecb.ECBGetSeriesTool({'name': 'x'}).common_series
    assert 'eonia' not in json.dumps(read_tool('ecb_get_interest_rate')['inputSchema'])


# ── IMF on the SDMX client ───────────────────────────────────────────────────

def test_imf_weo_ifs_and_compare_keys():
    from sajha.tools.impl import imf_tool_refactored as imf
    http = _Http(_csv(IMF_CSV))
    with mock.patch.object(outbound, 'request', http):
        out = imf.IMFGetWEODataTool(read_tool('imf_get_weo_data')).execute(
            {'country_code': 'US', 'indicator': 'gdp_growth', 'start_year': 2024})
        assert out['key'] == 'USA.NGDP_RPCH.A' and out['latest_actual_year'] == '2025'
        assert http.calls[-1]['url'].endswith('/data/IMF.RES,WEO/USA.NGDP_RPCH.A')
        cmp_ = imf.IMFCompareCountriesTool(read_tool('imf_compare_countries')).execute(
            {'country_codes': ['US', 'DEU'], 'indicator': 'gdp_growth'})
        assert http.calls[-1]['url'].endswith('/data/IMF.RES,WEO/USA+DEU.NGDP_RPCH.A')
        assert [c['count'] for c in cmp_['countries']] == [2, 1]
        imf.IMFGetIFSDataTool(read_tool('imf_get_ifs_data')).execute({'country_code': 'IN', 'indicator': 'cpi_inflation'})
        assert http.calls[-1]['url'].endswith('/data/IMF.STA,CPI/IND.CPI._T.YOY_PCH_PA_PT.M')


def test_imf_get_data_needs_a_key_for_other_layouts():
    from sajha.tools.impl import imf_tool_refactored as imf
    structure = {'flow': 'IMF.STA,CPI', 'name': 'CPI', 'dimensions': [
        {'id': d, 'position': i, 'codelist': None, 'codes': []}
        for i, d in enumerate(['COUNTRY', 'INDEX_TYPE', 'COICOP_1999', 'TYPE_OF_TRANSFORMATION', 'FREQUENCY'])]}
    with mock.patch.object(sdmx_client, 'flow_structure', return_value=structure):
        with pytest.raises(ValueError, match='pass the full key'):
            imf.IMFGetDataTool(read_tool('imf_get_data')).execute(
                {'database': 'CPI', 'country_code': 'USA', 'indicator_code': 'CPI'})


# ── FRED key: a configuration error, never invented values ───────────────────

def test_fred_key_rules(monkeypatch):
    from sajha.tools.impl.fred_key import configured_key, fred_api_key
    monkeypatch.delenv('FRED_API_KEY', raising=False)
    for placeholder in ('${fred.api.key}', '', 'demo', 'DEMO_KEY', None):
        assert configured_key({'api_key': placeholder}) is None
    with pytest.raises(ValueError, match='FRED_API_KEY'):
        fred_api_key({})
    monkeypatch.setenv('FRED_API_KEY', 'env-key')
    assert fred_api_key({'api_key': '${fred.api.key}'}) == 'env-key'
    assert fred_api_key({'api_key': 'cfg-key'}) == 'cfg-key'


@pytest.mark.parametrize('cls, args', [
    ('FedGetSeriesTool', {'indicator': 'gdp'}),
    ('FedGetLatestTool', {'series_id': 'DGS10'}),
    ('FedSearchSeriesTool', {'query': 'gdp'}),
    ('FedGetCommonIndicatorsTool', {}),
])
def test_fed_tools_without_a_key_fail_and_never_invent_data(cls, args, monkeypatch):
    monkeypatch.delenv('FRED_API_KEY', raising=False)
    mod = importlib.import_module('sajha.tools.impl.fed_reserve_tool_refactored')
    tool = getattr(mod, cls)({'name': 'x', 'api_key': '${fred.api.key}'})
    with mock.patch('sajha.core.outbound.urlopen', side_effect=AssertionError('no request without a key')):
        with pytest.raises(ValueError, match='FRED_API_KEY'):
            tool.execute(args)
    assert not hasattr(mod.FedReserveBaseTool, '_get_demo_series')


def test_fred_preset_tools_without_series_id_and_schema_limit(monkeypatch):
    from sajha.tools.impl.fred_tools import FREDCustomSeriesTool, FREDUnemploymentTool
    monkeypatch.setenv('FRED_API_KEY', 'k')
    urls = []

    class R(io.BytesIO):
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def info(self): return self.headers

    def urlopen(req, timeout=None):
        urls.append(urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query))
        return R(b'{"observations": []}')
    with mock.patch('sajha.core.outbound.urlopen', urlopen):
        out = FREDCustomSeriesTool(read_tool('fred_5yr_treasury')).execute({})
        assert out['series'] == 'DGS5' and urls[-1]['limit'] == ['20']
        FREDUnemploymentTool(read_tool('fred_unemployment')).execute({})
        assert urls[-1]['limit'] == ['30'] and urls[-1]['series_id'] == ['UNRATE']
        with pytest.raises(ValueError, match='series_id is required'):
            FREDCustomSeriesTool(read_tool('fred_custom_series')).execute({})
    assert read_tool('fred_leading_index')['inputSchema']['properties']['series_id']['default'] == 'USALOLITOAASTSAM'


# ── PBoC and BoJ ─────────────────────────────────────────────────────────────

def test_pboc_and_boj_series_are_distinct_and_labelled():
    from sajha.tools.impl.china_central_bank import PBOC_SERIES
    from sajha.tools.impl.japan_central_bank import BOJ_SERIES
    for table in (PBOC_SERIES, BOJ_SERIES):
        codes = [spec[1] + (spec[2] if spec[0] == 'imf' else '') for spec in table.values()]
        assert len(codes) == len(set(codes)), 'two labels read the same series'
    assert BOJ_SERIES['trade_balance'][1] == 'XTNTVA01JPM664S'          # a balance, not exports
    assert 'prime_rate' not in PBOC_SERIES and 'eur_cny' not in PBOC_SERIES
    assert PBOC_SERIES['cpi'][0] == 'imf'


def test_boj_default_recent_periods_is_the_schema_default(monkeypatch):
    from sajha.tools.impl.japan_central_bank import BoJGetJGBYieldTool
    seen = {}

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def info(self): return {}

    def urlopen(req, timeout=None):
        seen.update(urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query))
        return R(b'{"observations": []}')
    with mock.patch('sajha.core.outbound.urlopen', urlopen):
        BoJGetJGBYieldTool({'name': 'x', 'api_key': 'k'}).execute({})
    assert seen['limit'] == ['10'] and seen['sort_order'] == ['desc'] and seen['series_id'] == ['IRLTLT01JPM156N']


# ── Bank of Canada ───────────────────────────────────────────────────────────

BOC_VERIFIED = {   # checked against the live Valet API
    'policy_rate': 'V39079', 'overnight_rate': 'AVG.INTWO', 'prime_rate': 'V80691311',
    'bond_2y': 'BD.CDN.2YR.DQ.YLD', 'bond_5y': 'BD.CDN.5YR.DQ.YLD', 'bond_10y': 'BD.CDN.10YR.DQ.YLD',
    'bond_30y': 'BD.CDN.LONG.DQ.YLD', 'cpi': 'V41690973', 'core_cpi': 'CPI_TRIM',
}


def test_boc_shorthands_use_verified_valet_series():
    from sajha.tools.impl import bank_of_canada_tool_refactored as boc
    series = boc.BoCGetLatestTool(read_tool('boc_get_latest')).common_series
    for key, sid in BOC_VERIFIED.items():
        assert series[key] == sid, key
    assert 'gdp' not in series
    assert not {'POLICY_RATE', 'CORRA', 'V122530', 'V122531', 'V122533', 'V122539', 'V122546',
                'V41690914', 'V65201210'} & set(series.values())
    for f in sorted((ROOT / 'config' / 'tools' / 'bank_of_canada').glob('*.json')):
        text = f.read_text()
        assert '"gdp"' not in text and 'POLICY_RATE' not in text and 'V122539' not in text, f.name
    src = (ROOT / 'sajha' / 'tools' / 'impl' / 'bank_of_canada_tool_refactored.py').read_text()
    assert "'gdp'" not in src and '"gdp"' not in src and 'POLICY_RATE' not in src


def test_boc_recent_observations_are_oldest_first():
    from sajha.tools.impl.bank_of_canada_tool_refactored import BoCGetSeriesTool
    body = json.dumps({'seriesDetail': {'V39079': {'label': 'Target'}}, 'observations': [
        {'d': '2026-10-08', 'V39079': {'v': '2.25'}}, {'d': '2026-10-07', 'V39079': {'v': '2.50'}}]})

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def info(self): return {}

    with mock.patch('sajha.core.outbound.urlopen', lambda req, timeout=None: R(body.encode())):
        out = BoCGetSeriesTool(read_tool('boc_get_series')).execute({'indicator': 'policy_rate', 'recent_periods': 2})
    assert [o['date'] for o in out['observations']] == ['2026-10-07', '2026-10-08']


# ── UN SDG data ──────────────────────────────────────────────────────────────

def test_un_sdg_data_converts_iso_to_m49_and_reads_pages():
    from sajha.tools.impl.united_nations_tool_refactored import UNGetSDGDataTool
    tool = UNGetSDGDataTool(read_tool('un_get_sdg_data'))
    urls = []

    def get(url, headers=None):
        urls.append(url)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        page = int(q['page'][0])
        row = {'series': 'SH_DYN_IMRT', 'seriesDescription': 'Infant mortality rate', 'geoAreaCode': '356',
               'geoAreaName': 'India', 'timePeriodStart': 2014.0 + page, 'value': '36.3',
               'dimensions': {'Sex': 'BOTHSEX'}, 'attributes': {'Units': 'PER_1000_LIVE_BIRTHS'}}
        return {'totalElements': 2, 'totalPages': 2, 'data': [row]}
    with mock.patch.object(tool, '_http_get_json', get):
        out = tool.execute({'indicator_code': '3.2.1', 'country_code': 'IND', 'start_year': 2015, 'end_year': 2016})
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(urls[0]).query)
    assert q['areaCode'] == ['356'] and q['timePeriod'] == ['2015', '2016']
    assert out['count'] == 2 and out['data'][0] == {
        'year': 2015, 'value': 36.3, 'unit': 'PER_1000_LIVE_BIRTHS', 'series': 'SH_DYN_IMRT',
        'series_description': 'Infant mortality rate', 'dimensions': {'Sex': 'BOTHSEX'}}
    with pytest.raises(ValueError, match='Unknown country code'):
        tool.execute({'indicator_code': '3.2.1', 'country_code': 'ZZZ'})


# ── EDGAR ────────────────────────────────────────────────────────────────────

def _edgar(cls_name, cfg_name):
    mod = importlib.import_module('sajha.tools.impl.enhanced_edgar_tool')
    return getattr(mod, cls_name)(read_tool(cfg_name))


TICKERS = {'fields': ['cik', 'name', 'ticker', 'exchange'],
           'data': [[320193, 'Apple Inc.', 'AAPL', 'Nasdaq'], [19617, 'JPMORGAN CHASE & CO', 'JPM', 'NYSE'],
                    [320193, 'Apple Inc.', 'AAPL2', 'Nasdaq']]}


def test_edgar_tickers_carry_the_exchange():
    tool = _edgar('EDGARCompanyTickersByExchangeTool', 'edgar_company_tickers_by_exchange')
    with mock.patch.object(tool, '_make_request', return_value=TICKERS) as req:
        out = tool.execute({'exchange': 'NYSE'})
    assert req.call_args[0][0] == 'https://www.sec.gov/files/company_tickers_exchange.json'
    assert out['companies'] == [{'cik': '0000019617', 'ticker': 'JPM', 'title': 'JPMORGAN CHASE & CO'}]
    search = _edgar('EDGARCompanySearchTool', 'edgar_company_search')
    with mock.patch.object(search, '_make_request', return_value=TICKERS):
        assert search.execute({'query': 'AAPL'})['companies'][0]['exchange'] == 'Nasdaq'


def test_edgar_companies_by_sic_error_path_uses_the_tool_logger():
    tool = _edgar('EDGARCompaniesBySICTool', 'edgar_companies_by_sic')

    def request(url):
        if url.endswith('company_tickers_exchange.json'):
            return TICKERS
        if 'CIK0000320193' in url:
            raise ValueError('Rate limit exceeded')
        return {'sic': '6021', 'name': 'JPMORGAN CHASE & CO'}
    with mock.patch.object(tool, '_make_request', side_effect=request):
        out = tool.execute({'sic_code': '6021', 'limit': 5, 'max_scan': 10})
    assert out['errors'] == 1 and out['companies_scanned'] == 2       # Apple's second ticker is not re-read
    assert [c['cik'] for c in out['companies']] == ['0000019617']


def test_edgar_schedule_13_names_after_december_2024():
    tool = _edgar('EDGAROwnershipReportsTool', 'edgar_ownership_reports')
    subs = {'name': 'X', 'filings': {'recent': {
        'form': ['SCHEDULE 13G', '10-K', 'SC 13G', 'SC 13G/A'],
        'filingDate': ['2026-04-29', '2026-01-01', '2019-02-14', '2018-01-01'],
        'accessionNumber': ['a-1', 'b-2', 'c-3', 'd-4'], 'reportDate': ['', '', '', ''],
        'primaryDocument': ['', '', '', ''], 'primaryDocDescription': ['', '', '', '']}}}
    with mock.patch('sajha.tools.impl.enhanced_edgar_tool.EDGARBaseTool._make_request', return_value=subs):
        out = tool.execute({'cik': '320193', 'form_type': 'SC 13G'})
    assert [r['form'] for r in out['reports']] == ['SCHEDULE 13G', 'SC 13G']
    assert 'SCHEDULE 13D' in read_tool('edgar_ownership_reports')['inputSchema']['properties']['form_type']['enum']


def test_edgar_frames_fall_back_to_instant_periods():
    tool = _edgar('EDGARFrameDataTool', 'edgar_frame_data')
    urls = []

    def request(url):
        urls.append(url)
        if url.endswith('/CY2023.json'):
            raise ValueError(f'Resource not found: {url}')
        return {'tag': 'Assets', 'data': [{'val': 1}]}
    with mock.patch.object(tool, '_make_request', side_effect=request):
        out = tool.execute({'concept': 'Assets', 'year': 2023})
    assert out['frame'] == 'CY2023Q4I' and urls[-1].endswith('/us-gaap/Assets/USD/CY2023Q4I.json')
    with mock.patch.object(tool, '_make_request', side_effect=request):
        assert tool.execute({'concept': 'Assets', 'year': 2023, 'quarter': 'Q2', 'period_type': 'instant'})['frame'] == 'CY2023Q2I'


def test_edgar_financial_ratios_pick_the_period_not_the_comparatives():
    tool = _edgar('EDGARFinancialRatiosTool', 'edgar_financial_ratios')

    def usd(*rows):
        return {'units': {'USD': [dict(zip(('fy', 'fp', 'form', 'start', 'end', 'val'), r)) for r in rows]}}
    facts = {'entityName': 'Co', 'facts': {'us-gaap': {
        'Revenues': usd((2024, 'FY', '10-K', '2022-10-01', '2023-09-30', 100.0),       # comparative
                        (2024, 'FY', '10-K', '2023-10-01', '2024-09-30', 200.0),
                        (2024, 'FY', '10-K', '2024-07-01', '2024-09-30', 60.0),        # a quarter inside the 10-K
                        (2023, 'FY', '10-K', '2022-10-01', '2023-09-30', 100.0)),
        'NetIncomeLoss': usd((2024, 'FY', '10-K', '2022-10-01', '2023-09-30', 10.0),
                             (2024, 'FY', '10-K', '2023-10-01', '2024-09-30', 50.0)),
        'Assets': usd((2024, 'FY', '10-K', None, '2023-09-30', 400.0), (2024, 'FY', '10-K', None, '2024-09-30', 500.0)),
    }}}
    with mock.patch.object(tool, '_make_request', return_value=facts):
        out = tool.execute({'cik': '1'})                    # no fiscal_year: the latest reported
    assert out['fiscal_year'] == 2024
    assert out['profitability_ratios']['net_margin'] == 25.0
    assert out['profitability_ratios']['return_on_assets'] == 10.0


def test_sec_financial_data_maps_friendly_names_to_tags():
    from sajha.tools.impl.sec_edgar_tool_refactored import SECGetFinancialDataTool
    tool = SECGetFinancialDataTool(read_tool('sec_get_financial_data'))
    body = json.dumps({'entityName': 'Co', 'facts': {'us-gaap': {'AssetsCurrent': {'label': 'Assets, Current', 'units': {}}}}})

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def info(self): return {}
    with mock.patch('sajha.core.outbound.urlopen', lambda req, timeout=None: R(body.encode())):
        out = tool.execute({'cik': '1', 'fact_type': 'CurrentAssets'})
        missing = tool.execute({'cik': '1', 'fact_type': 'GrossProfit'})
    assert out['data'][0]['tag'] == 'AssetsCurrent'
    assert missing['data'] == [] and 'GrossProfit' in missing['note']


def test_sec_mutual_fund_holdings_reads_nport():
    from sajha.tools.impl.sec_edgar_tool_refactored import SECGetMutualFundHoldingsTool
    body = json.dumps({'name': 'Fund', 'filings': {'recent': {
        'accessionNumber': ['1', '2'], 'filingDate': ['2026-08-28', '2026-08-14'], 'reportDate': ['', ''],
        'form': ['13F-HR', 'NPORT-P'], 'primaryDocument': ['', '']}}})

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def info(self): return {}
    with mock.patch('sajha.core.outbound.urlopen', lambda req, timeout=None: R(body.encode())):
        out = SECGetMutualFundHoldingsTool(read_tool('sec_get_mutual_fund_holdings')).execute({'cik': '36405'})
    assert [f['form'] for f in out['filings']] == ['NPORT-P']


# ── CoinGecko, Wikipedia, World Bank ─────────────────────────────────────────

def test_coingecko_movers_are_ranked_by_sajha():
    from sajha.tools.impl.coingecko_tools import CGTopGainersTool, CGTopLosersTool
    coins = [{'id': 'a', 'price_change_percentage_24h': 1.0}, {'id': 'b', 'price_change_percentage_24h': -5.0},
             {'id': 'c', 'price_change_percentage_24h': 9.0}, {'id': 'd', 'price_change_percentage_24h': None}]
    for cls, expect in ((CGTopGainersTool, ['c', 'a']), (CGTopLosersTool, ['b', 'a'])):
        tool = cls({'name': 'x'})
        with mock.patch.object(tool, '_cg_get', return_value=coins) as get:
            out = tool.execute({'limit': 2})
        assert get.call_args.kwargs['order'] == 'market_cap_desc' and get.call_args.kwargs['per_page'] == 250
        assert [c['id'] for c in out['coins']] == expect
    assert read_tool('cg_coin_markets')['inputSchema']['properties']['order']['enum'][0] == 'market_cap_desc'


def test_wikipedia_redirect_links_and_original_image():
    from sajha.tools.impl.wikipedia_tool import WikiGetPageTool, WikiGetSummaryTool
    page = WikiGetPageTool(read_tool('wiki_get_page'))
    calls = []

    def request(params, language='en'):
        calls.append(dict(params))
        if params.get('prop') == 'links|extlinks':
            return {'query': {'pages': {'1': {'links': [{'title': 'Risk'}], 'extlinks': [{'*': 'https://x'}]}}}}
        return {'query': {'pages': {'1': {'pageid': 1, 'title': 'VaR', 'extract': 'Text',
                                          'original': {'source': 'o.jpg', 'width': 1, 'height': 2}}}}}
    with mock.patch.object(page, '_make_request', side_effect=request):
        out = page.execute({'query': 'VaR', 'redirect': False})
    assert 'redirects' not in calls[0]
    assert out['links'] == {'internal': ['Risk'], 'external': ['https://x'], 'truncated': False}
    assert 'html_content' not in out and 'references' not in out
    assert 'include_references' not in read_tool('wiki_get_page')['inputSchema']['properties']
    summary = WikiGetSummaryTool(read_tool('wiki_get_summary'))
    calls.clear()
    with mock.patch.object(summary, '_make_request', side_effect=request):
        out = summary.execute({'query': 'VaR'})
    assert calls[0]['redirects'] == 1 and 'original' in calls[0]['piprop']
    assert out['original_image'] == {'url': 'o.jpg', 'width': 1, 'height': 2}


def test_world_bank_search_reads_every_page_and_most_recent_year():
    from sajha.tools.impl.world_bank_tool import WBCompareCountriesTool, WBSearchIndicatorsTool
    search = WBSearchIndicatorsTool(read_tool('wb_search_indicators'))
    search._catalogue.clear()
    pages = {1: [{'id': 'A', 'name': 'Carbon one', 'sourceNote': ''}],
             2: [{'id': 'B', 'name': 'Other', 'sourceNote': 'carbon note'}]}
    with mock.patch.object(search, '_make_request',
                           side_effect=lambda ep, p: [{'pages': 2}, pages[p['page']]]):
        out = search.execute({'search_term': 'carbon', 'per_page': 1, 'page': 2})
    assert out['total_results'] == 2 and [r['id'] for r in out['results']] == ['B']
    search._catalogue.clear()
    cmp_ = WBCompareCountriesTool(read_tool('wb_compare_countries'))
    seen = []

    def req(endpoint, params):
        seen.append(dict(params))
        return [{}, [{'date': '2025', 'value': 5.0, 'country': {'value': 'X'}, 'indicator': {'value': 'GDP'}}]]
    with mock.patch.object(cmp_, '_make_request', side_effect=req):
        out = cmp_.execute({'country_codes': ['US', 'CN'], 'indicator': 'gdp', 'most_recent_year': True,
                            'start_year': 2000, 'end_year': 2001})
    assert all(p.get('mrnev') == 1 and 'date' not in p for p in seen)
    assert out['indicator']['name'] == 'GDP'


def test_fbi_year_schema_has_no_fixed_maximum():
    for f in sorted((ROOT / 'config' / 'tools' / 'fbi').glob('*.json')):
        props = json.loads(f.read_text())['inputSchema']['properties']
        for k in ('year', 'start_year', 'end_year'):
            if k in props:
                assert 'maximum' not in props[k], f.name


# ── removed tools and descriptions ───────────────────────────────────────────

REMOVED = ['rbi_get_exchange_rate', 'rbi_get_forex_reserves', 'rbi_get_gsec_yield', 'rbi_get_inflation',
           'rbi_get_policy_rate', 'pboc_get_cgb_yield', 'pboc_get_money_supply', 'un_get_sdg_progress',
           'fred_gold_price', 'fred_silver_price']


def test_removed_tools_are_gone():
    for name in REMOVED:
        assert not tool_file(name).exists(), name
    assert not (ROOT / 'config' / 'tools' / 'reserve_bank_of_india').exists()
    assert not (ROOT / 'sajha' / 'tools' / 'impl' / 'india_central_bank.py').exists()


FOLDERS = ['banque_de_france', 'federal_reserve', 'peoples_bank_of_china', 'bank_of_japan', 'imf', 'ecb',
           'united_nations', 'edgar', 'coingecko', 'wikipedia', 'fred', 'worldbank', 'fbi', 'bank_of_canada']


def _tools():
    from sajha.tools.tools_registry import ToolsRegistry  # noqa: F401  (import check only)
    for folder in FOLDERS:
        for f in sorted((ROOT / 'config' / 'tools' / folder).glob('*.json')):
            yield f


@pytest.mark.parametrize('path', list(_tools()), ids=lambda p: p.stem)
def test_description_example_validates(path):
    """Every tool in these folders: description at most 1000 characters, and its Example parses
    and validates against the input schema the tool serves."""
    cfg = json.loads(path.read_text())
    desc = cfg['description']
    assert len(desc) <= 1000, len(desc)
    m = re.search(r'Example: (\{.*?\})(?: gives|\n|$)', desc, re.S)
    assert m, 'no Example: {...} in the description'
    example = json.loads(m.group(1))
    module, cls = cfg['implementation'].rsplit('.', 1)
    tool = getattr(importlib.import_module(module), cls)(cfg)
    tool.validate_arguments(example)
