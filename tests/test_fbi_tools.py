# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""FBI Crime Data Explorer tools: request shape, parsing and error mapping.

All HTTP is mocked. The fixtures in tests/fixtures/fbi/ are real CDE API responses
(recorded October 2026) for:

    agency_VT                 /agency/byStateAbbr/VT
    sum_nat_V                 /summarized/national/V?from=01-2022&to=12-2022
    sum_state_CA_V            /summarized/state/CA/V?from=01-2022&to=12-2022
    sum_agency_VT0040100_V    /summarized/agency/VT0040100/V?from=01-2022&to=12-2022
    sum_agency_bad            /summarized/agency/ZZ9999999/V?...   (unknown ORI: US series only)
    sum_nat_HOM_2020_2022     /summarized/national/HOM?from=01-2020&to=12-2022
    pe_VT_ori                 /pe/VT/VT0040100?from=2022&to=2022
    nibrs_nat_13A_counts      /nibrs/national/13A?type=counts&from=01-2022&to=12-2022
    nibrs_nat_13A_totals      /nibrs/national/13A?type=totals&from=01-2022&to=12-2022
    bad_date.txt              HTTP 400 body for a malformed from/to
"""
import io
import json
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

import jsonschema
import pytest

from sajha.tools.impl import fbi_tool_refactored as fbi

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / 'tests' / 'fixtures' / 'fbi'
BASE = 'https://api.usa.gov/crime/fbi/cde/'


def fixture(name):
    return json.loads((FIX / f'{name}.json').read_text())


def config(name):
    return json.loads((ROOT / 'config' / 'tools' / f'{name}.json').read_text())


class _Resp(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def info(self):
        return self.headers

    def getheader(self, *_a, **_k):
        return None


class Api:
    """Stands in for urllib.request.urlopen; routes by path to fixtures."""

    def __init__(self, routes):
        self.routes = routes  # {path: fixture-name | dict | Exception}
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append((req, timeout))
        parts = urllib.parse.urlsplit(req.full_url)
        path = urllib.parse.unquote(parts.path).split('/crime/fbi/cde/', 1)[1]
        answer = self.routes[path]
        if isinstance(answer, Exception):
            raise answer
        payload = fixture(answer) if isinstance(answer, str) else answer
        return _Resp(json.dumps(payload).encode())

    def query(self, i=0):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.requests[i][0].full_url).query))

    def path(self, i=0):
        return urllib.parse.unquote(urllib.parse.urlsplit(self.requests[i][0].full_url).path)


def run(tool_cls, name, args, routes, **cfg):
    """Build the tool from its shipped config, run it, validate the output schema."""
    tool = tool_cls(dict(config(name), api_key='test-key', **cfg))
    api = Api(routes)
    with mock.patch('urllib.request.urlopen', api):
        result = tool.execute(args)
    jsonschema.validate(result, config(name)['outputSchema'])
    return result, api


def http_error(code, body):
    return urllib.error.HTTPError(BASE + 'x', code, 'err', {}, io.BytesIO(body.encode()))


# ── request shape ────────────────────────────────────────────────────────────

def test_requests_carry_key_header_and_month_window():
    result, api = run(fbi.FBIGetNationalStatisticsTool, 'fbi_get_national_statistics',
                      {'offense_type': 'violent_crime', 'year': 2022},
                      {'summarized/national/V': 'sum_nat_V'}, timeout=12)
    req, timeout = api.requests[0]
    assert req.full_url.startswith(BASE + 'summarized/national/V?')
    assert api.query() == {'from': '01-2022', 'to': '12-2022'}
    assert req.get_header('X-api-key') == 'test-key'
    assert 'test-key' not in req.full_url
    assert timeout == 12


def test_key_resolution(monkeypatch):
    monkeypatch.delenv('FBI_API_KEY', raising=False)
    monkeypatch.delenv('DATA_GOV_API_KEY', raising=False)
    assert fbi.FBIGetNationalStatisticsTool({'api_key': '${fbi.api.key:}'}).api_key == 'DEMO_KEY'
    monkeypatch.setenv('DATA_GOV_API_KEY', 'gov-key')
    assert fbi.FBIGetNationalStatisticsTool({'api_key': ''}).api_key == 'gov-key'
    monkeypatch.setenv('FBI_API_KEY', 'env-key')
    assert fbi.FBIGetNationalStatisticsTool({'api_key': ''}).api_key == 'env-key'
    assert fbi.FBIGetNationalStatisticsTool({'api_key': 'cfg'}).api_key == 'cfg'


def test_configs_point_at_this_module_and_share_the_key():
    for name, cls in fbi.FBI_TOOLS.items():
        cfg = config(name)
        assert cfg['implementation'] == f'sajha.tools.impl.fbi_tool_refactored.{cls.__name__}'
        assert cfg['api_key'] == '${fbi.api.key:}'
        props = cfg['inputSchema']['properties']
        if 'offense_type' in props:
            table = fbi.NIBRS_OFFENSES if name == 'fbi_get_offense_data' else fbi.SUMMARIZED_OFFENSES
            assert set(props['offense_type']['enum']) == set(table), name


# ── parsing real responses ───────────────────────────────────────────────────

def test_national_statistics_parses_summarized_response():
    result, _ = run(fbi.FBIGetNationalStatisticsTool, 'fbi_get_national_statistics',
                    {'offense_type': 'violent_crime', 'year': 2022, 'include_monthly': True},
                    {'summarized/national/V': 'sum_nat_V'})
    nd = result['national_data']
    assert nd['total_incidents'] == 1271206
    assert nd['rate_per_100k'] == 398.17          # sum of the 12 monthly rates
    assert nd['population'] == 336746447
    assert nd['months_reported'] == 12
    assert 90 < nd['population_coverage_pct'] < 100
    assert 0 < nd['clearance_rate_pct'] < 100
    assert result['monthly'][0] == {'month': '2022-01', 'incidents': 96191, 'rate_per_100k': 30.51}
    assert result['metadata']['endpoint'] == 'summarized/national/V'


def test_state_statistics_compares_with_national():
    result, api = run(fbi.FBIGetStateStatisticsTool, 'fbi_get_state_statistics',
                      {'state': 'ca', 'offense_type': 'violent_crime', 'year': 2022},
                      {'summarized/state/CA/V': 'sum_state_CA_V'})
    assert api.path() == '/crime/fbi/cde/summarized/state/CA/V'
    assert len(api.requests) == 1                  # the national rate comes in the same response
    assert result['state_name'] == 'California'
    assert result['state_data']['total_incidents'] > 100000
    comp = result['comparison']
    assert comp['national_rate_per_100k'] == 398.17
    assert comp['percent_of_national'] == round(result['state_data']['rate_per_100k'] / 398.17 * 100, 2)


def test_agency_statistics_reads_agency_name_from_series():
    result, api = run(fbi.FBIGetAgencyStatisticsTool, 'fbi_get_agency_statistics',
                      {'ori': 'VT0040100', 'offense_type': 'violent_crime', 'year': 2022},
                      {'summarized/agency/VT0040100/V': 'sum_agency_VT0040100_V'})
    assert result['agency_name'] == 'Burlington Police Department'
    assert result['agency_data']['population'] == 44689
    assert result['agency_data']['total_incidents'] > 0
    assert result['comparison']['state_rate_per_100k'] is not None
    assert result['comparison']['national_rate_per_100k'] == 398.17


def test_agency_statistics_unknown_ori_is_a_clear_error():
    tool = fbi.FBIGetAgencyStatisticsTool({'api_key': 'k'})
    with mock.patch('urllib.request.urlopen', Api({'summarized/agency/ZZ9999999/V': 'sum_agency_bad'})):
        with pytest.raises(fbi.FBIAPIError, match='fbi_search_agencies'):
            tool.execute({'ori': 'ZZ9999999', 'offense_type': 'violent_crime', 'year': 2022})


def test_search_agencies_filters_state_list():
    result, api = run(fbi.FBISearchAgenciesTool, 'fbi_search_agencies',
                      {'state': 'VT', 'agency_name': 'burlington', 'limit': 5},
                      {'agency/byStateAbbr/VT': 'agency_VT'})
    assert api.path() == '/crime/fbi/cde/agency/byStateAbbr/VT'
    oris = {a['ori'] for a in result['agencies']}
    assert {'VT0040100', 'VT0040300'} <= oris
    assert result['agencies'][0]['county'] == 'CHITTENDEN'

    result, _ = run(fbi.FBISearchAgenciesTool, 'fbi_search_agencies',
                    {'state': 'VT', 'agency_type': 'county', 'limit': 500},
                    {'agency/byStateAbbr/VT': 'agency_VT'})
    assert result['total_results'] > 0
    assert {a['agency_type'] for a in result['agencies']} == {'County'}


def test_agency_details_joins_directory_and_police_employees():
    result, api = run(fbi.FBIGetAgencyDetailsTool, 'fbi_get_agency_details',
                      {'ori': 'VT0040100', 'year': 2022},
                      {'agency/byStateAbbr/VT': 'agency_VT', 'pe/VT/VT0040100': 'pe_VT_ori'})
    assert api.query(1) == {'from': '2022', 'to': '2022'}
    assert result['agency_name'] == 'Burlington Police Department'
    assert result['agency_type'] == 'City'
    assert result['reporting_status'] == {'is_nibrs': True, 'nibrs_start_date': '2003-01-01'}
    p = result['personnel']
    assert (p['total_officers'], p['total_civilians'], p['total_employees']) == (62, 24, 86)
    assert p['employees_per_1000'] == 1.92


def test_agency_details_unknown_ori():
    tool = fbi.FBIGetAgencyDetailsTool({'api_key': 'k'})
    with mock.patch('urllib.request.urlopen', Api({'agency/byStateAbbr/VT': 'agency_VT'})):
        with pytest.raises(fbi.FBIAPIError, match='not in the FBI agency list'):
            tool.execute({'ori': 'VT9999999'})


def test_offense_data_uses_nibrs_counts_and_totals():
    calls = []

    def answer(req, timeout=None):
        calls.append(req.full_url)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(req.full_url).query))
        name = 'nibrs_nat_13A_counts' if q['type'] == 'counts' else 'nibrs_nat_13A_totals'
        return _Resp(json.dumps(fixture(name)).encode())

    tool = fbi.FBIGetOffenseDataTool(dict(config('fbi_get_offense_data'), api_key='k'))
    with mock.patch('urllib.request.urlopen', answer):
        result = tool.execute({'offense_type': 'aggravated_assault', 'year': 2022, 'top_n': 3})
    jsonschema.validate(result, config('fbi_get_offense_data')['outputSchema'])
    assert all('/nibrs/national/13A?' in u for u in calls) and len(calls) == 2
    assert result['nibrs_offense_code'] == '13A'
    assert result['total_offenses'] == sum(fixture('nibrs_nat_13A_counts')['offenses']['actuals']
                                           ['United States Offenses'].values())
    sex = result['breakdown']['victim']['sex']
    assert list(sex) == ['Male', 'Female', 'Unknown']          # sorted, zeros dropped
    assert len(result['breakdown']['victim']['location']) == 3   # top_n


def test_offense_data_rejects_aggregates():
    with pytest.raises(ValueError, match='Unsupported offense_type'):
        fbi.FBIGetOffenseDataTool({'api_key': 'k'}).execute({'offense_type': 'violent_crime'})


def test_participation_rate_from_population_coverage():
    result, _ = run(fbi.FBIGetParticipationRateTool, 'fbi_get_participation_rate',
                    {'year': 2022}, {'summarized/national/V': 'sum_nat_V'})
    pd = result['participation_data']
    assert pd['total_population'] == 336746447
    assert pd['months_reported'] == 12
    assert result['monthly'][0] == {'month': '2022-01', 'population_coverage_pct': 93.61,
                                    'participated_population': 315231910}


def test_crime_trend_one_request_grouped_by_year():
    result, api = run(fbi.FBIGetCrimeTrendTool, 'fbi_get_crime_trend',
                      {'offense_type': 'homicide', 'start_year': 2020, 'end_year': 2022},
                      {'summarized/national/HOM': 'sum_nat_HOM_2020_2022'})
    assert len(api.requests) == 1
    assert api.query() == {'from': '01-2020', 'to': '12-2022'}
    years = [p['year'] for p in result['time_series']]
    assert years == [2020, 2021, 2022]
    assert all(p['months_reported'] == 12 for p in result['time_series'])
    assert result['time_series'][0]['percent_change'] is None
    assert result['trend_analysis']['direction'] in ('increasing', 'decreasing', 'stable')


def test_compare_states_ranks_and_references_national():
    result, api = run(fbi.FBICompareStatesTool, 'fbi_compare_states',
                      {'states': ['VT', 'CA'], 'offense_type': 'violent_crime', 'year': 2022},
                      # VT's own state series as it appears in a summarized response
                      {'summarized/state/CA/V': 'sum_state_CA_V',
                       'summarized/state/VT/V': 'sum_agency_VT0040100_V'})
    assert [r['state'] for r in result['states_compared']] == ['CA', 'VT']   # CA rate is higher
    assert result['states_compared'][0]['rank'] == 1
    assert result['national_reference'] == {'rate_per_100k': 398.17}
    assert result['comparison_summary']['highest_state'] == 'CA'


# ── errors ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('error, key, match', [
    (http_error(403, '{"error":{"code":"API_KEY_MISSING","message":"No api_key was supplied."}}'),
     'k', 'fbi.api.key'),
    (http_error(403, '{"error":{"code":"API_KEY_INVALID","message":"An invalid api_key was supplied."}}'),
     'k', 'FBI_API_KEY'),
    (http_error(429, '{"error":{"code":"OVER_RATE_LIMIT","message":"You have exceeded your rate limit."}}'),
     'DEMO_KEY', 'DEMO_KEY.*FBI_API_KEY'),
    (http_error(400, (FIX / 'bad_date.txt').read_text()), 'k', 'expected format MM-YYYY'),
    (http_error(404, '<html>Not Found</html>'), 'k', 'no resource'),
    (urllib.error.URLError('timed out'), 'k', 'unreachable'),
    (TimeoutError(), 'k', 'did not answer within 30s'),
])
def test_error_mapping(error, key, match):
    tool = fbi.FBIGetNationalStatisticsTool({'api_key': key})
    with mock.patch('urllib.request.urlopen', Api({'summarized/national/V': error})):
        with pytest.raises(fbi.FBIAPIError, match=match):
            tool.execute({'offense_type': 'violent_crime', 'year': 2022})


def test_input_validation():
    tool = fbi.FBIGetStateStatisticsTool({'api_key': 'k'})
    with pytest.raises(ValueError, match='Invalid state'):
        tool.execute({'state': 'XX', 'offense_type': 'robbery'})
    with pytest.raises(ValueError, match='year must be between'):
        tool.execute({'state': 'CA', 'offense_type': 'robbery', 'year': 1900})
    with pytest.raises(ValueError, match='Invalid ORI'):
        fbi.FBIGetAgencyDetailsTool({'api_key': 'k'}).execute({'ori': 'bad'})
    with pytest.raises(ValueError, match='start_year'):
        fbi.FBIGetCrimeTrendTool({'api_key': 'k'}).execute(
            {'offense_type': 'robbery', 'start_year': 2022, 'end_year': 2020})
