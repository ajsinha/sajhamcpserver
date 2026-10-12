# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Wave 16, open data P2 (Open Data Tools §4, Roadmap L33 and L34): the eurostat, oecd and abs tool
folders, all host profiles on the shared SDMX client. Each tool replays the responses recorded from
the live service on 2026-10-12 (tests/fixtures/open_data/<tool>.json; the two catalogue lists are
trimmed); no test calls a live service."""

import importlib
import json
import re
from pathlib import Path

import jsonschema
import pytest
import yaml

from sajha.core import outbound
from sajha.tools.impl import abs_tools, eurostat_tools, oecd_tools, sdmx_client
from tests.tool_config_files import read_tool

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / 'config' / 'tools'
FIXTURES = ROOT / 'tests' / 'fixtures' / 'open_data'
QUALITY = ROOT / 'config' / 'tool_tests'
FOLDERS = ('eurostat', 'oecd', 'abs')
TOOLS = sorted(p.stem for f in FOLDERS for p in (TOOLS_DIR / f).glob('*.json'))


def _tool(name):
    cfg = read_tool(name)
    module, cls = cfg['implementation'].rsplit('.', 1)
    return getattr(importlib.import_module(module), cls)(cfg), cfg


class _Replay:
    """Stands in for outbound.request: answers from recorded calls, matched on URL and parameters."""

    def __init__(self, calls):
        self.calls = list(calls)
        self.seen = []

    def __call__(self, method, url, params=None, headers=None, **_):
        params = [list(p) for p in outbound._param_items(params)]
        self.seen.append({'url': url, 'params': params, 'headers': headers or {}})
        for i, c in enumerate(self.calls):
            if c['url'] == url and c['params'] == params:
                self.calls.pop(i)
                return outbound.Response(c['status'], 'OK' if c['status'] < 400 else 'ERR',
                                         {'content-type': c['content_type']}, c['body'].encode('utf-8'), url)
        raise AssertionError(f'unrecorded request {url} {params}')


class _Store:
    """A state store with only the sliding window the OECD throttle uses."""

    def __init__(self, allow=True):
        self.allow, self.calls = allow, []

    def window_add(self, key, window, limit=None):
        self.calls.append((key, window, limit))
        return self.allow, len(self.calls)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """No cached structure, catalogue or dataflow list leaks between tests; a fake state store."""
    sdmx_client.clear_cache()
    eurostat_tools._dims_cache.clear()
    eurostat_tools._toc.update(at=0.0, rows=[])
    oecd_tools._flows.update(at=0.0, rows=[])
    store = _Store()
    import sajha.core.state as state
    monkeypatch.setattr(state, 'get_state_store', lambda: store)
    return store


def _replay(name, monkeypatch, arguments=None):
    data = json.loads((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))
    fake = _Replay(data['calls'])
    monkeypatch.setattr(outbound, 'request', fake)
    tool, cfg = _tool(data['tool'])
    args = data['arguments'] if arguments is None else arguments
    tool.validate_arguments(args)
    out = tool.execute(args)
    jsonschema.validate(out, cfg['outputSchema'])
    assert not fake.calls, 'every recorded response is used'
    return out, fake


# ── the configs ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name', TOOLS)
def test_configs_follow_the_open_data_rules(name):
    cfg = read_tool(name)
    folder = name.split('_')[0]
    assert cfg['annotations'] == {'readOnlyHint': True, 'idempotentHint': True, 'openWorldHint': True}
    example = json.loads(re.search(r'\nExample: (\{.*\})\s*$', cfg['description']).group(1))
    assert cfg['inputSchema']['examples'][0] == example
    jsonschema.validate(example, cfg['inputSchema'])
    assert cfg['inputSchema']['additionalProperties'] is False
    for prop in cfg['inputSchema'].get('required', []):
        assert 'default' not in cfg['inputSchema']['properties'][prop]
    domain = (TOOLS_DIR / folder / 'domain.txt').read_text(encoding='utf-8').strip()
    assert len(domain) <= 600 and domain.startswith('Source: ')
    assert len(cfg['description']) + 2 + len(domain) <= 1024
    assert cfg['cache_ttl'] > 0 and 'api_key' not in cfg            # all three sources are keyless
    assert 'source' in cfg['outputSchema']['required']


@pytest.mark.parametrize('name', TOOLS)
def test_every_tool_has_a_fixture_a_probe_and_a_cassette(name):
    assert (FIXTURES / f'{name}.json').exists()
    spec = yaml.safe_load((QUALITY / f'{name}.yaml').read_text(encoding='utf-8'))
    assert spec['tool'] == name and spec['probe']['case'] == spec['cases'][0]['name']
    slug = spec['cases'][0]['name'].replace(' ', '_')
    assert (QUALITY / 'cassettes' / name / f'{slug}.json').exists()
    assert not re.search(r'last \d+', json.dumps(spec['cases'][0]['arguments'])), 'fixed periods replay'


@pytest.mark.parametrize('name', TOOLS)
def test_every_recorded_run_replays_and_matches_its_output_schema(name, monkeypatch):
    out, _ = _replay(name, monkeypatch)
    assert out['source'].startswith('Source: ')


# ── Eurostat ─────────────────────────────────────────────────────────────────

def test_eurostat_codes():
    g = eurostat_tools.geo_code
    assert [g(x) for x in ('DE', 'DEU', 'Germany', 'GR', 'GB', 'XM', 'euro area', 'EU', 'EA20', 'EU27_2020')] == \
        ['DE', 'DE', 'DE', 'EL', 'UK', 'EA21', 'EA21', 'EU27_2020', 'EA20', 'EU27_2020']
    with pytest.raises(ValueError, match='Unknown country'):
        g('Narnia')


def test_eurostat_series_shape(monkeypatch):
    out, fake = _replay('eurostat_hicp', monkeypatch)
    assert fake.seen[0]['url'].endswith('/data/prc_hicp_minr/M.RCH_A.TOTAL.DE+FR+EA21')
    assert ['format', 'SDMX-CSV'] in fake.seen[0]['params']
    de = out['series'][0]
    assert de['key'] == 'M.RCH_A.TOTAL.DE' and 'LAST UPDATE' not in de['dimensions']
    assert de['unit'] == 'Annual rate of change, percent' and re.fullmatch(r'\d{4}-\d{2}-\d{2}', de['last_update'])
    assert [o['date'] for o in de['observations']] == [f'2026-0{m}' for m in range(1, 7)]
    assert 'reuse_note' not in out


def test_eurostat_marks_data_that_is_not_its_own(monkeypatch):
    out, _ = _replay('eurostat_unemployment', monkeypatch)
    assert {s['country'] for s in out['series']} == {'ES', 'EA21', 'US'}
    assert 'commercially' in out['reuse_note']


def test_eurostat_get_series_builds_the_key_from_the_structure(monkeypatch):
    out, fake = _replay('eurostat_get_series', monkeypatch)
    assert '/datastructure/ESTAT/PRC_HICP_MINR/' in fake.seen[0]['url']
    assert fake.seen[1]['url'].endswith('/data/prc_hicp_minr/M.RCH_A.TOTAL+NRG.DE+FR')
    assert out['series_count'] == 4
    eurostat_tools._dims_cache['PRC_HICP_MINR'] = (1e18, ['freq', 'unit', 'coicop18', 'geo'])
    with pytest.raises(ValueError, match='no dimension .*sector'):
        eurostat_tools.build_key('prc_hicp_minr', {'sector': 'S13'})
    assert eurostat_tools.build_key('prc_hicp_minr', {'GEO': 'Greece'}) == '...EL'


def test_eurostat_search(monkeypatch):
    out, fake = _replay('eurostat_search', monkeypatch)
    assert fake.seen[0]['params'] == [['lang', 'en']]
    codes = [d['code'] for d in out['datasets']]
    assert 'prc_hpi_q' in codes and len(codes) == len(set(codes))
    assert out['datasets'][0]['type'] == 'dataset'
    q = next(d for d in out['datasets'] if d['code'] == 'prc_hpi_q')
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', q['last_update'])
    tool, _ = _tool('eurostat_search')          # cached for a day: no second request
    monkeypatch.setattr(outbound, 'request', lambda *a, **k: pytest.fail('the catalogue is cached'))
    assert tool.execute({'text': 'house price'})['count'] >= 1


def test_eurostat_refusal_is_passed_on(monkeypatch):
    fault = ('<?xml version="1.0"?><S:Fault xmlns:S="x"><faultcode>150</faultcode><faultstring>'
             'INVALID_QUERY_DIMENSION_VALUE: GEO=EA.</faultstring></S:Fault>')
    monkeypatch.setattr(outbound, 'request', lambda *a, **k: outbound.Response(400, 'ERR', {}, fault.encode(), a[1]))
    tool, _ = _tool('eurostat_gdp')
    with pytest.raises(ValueError, match='INVALID_QUERY_DIMENSION_VALUE'):
        tool.execute({'countries': ['DE'], 'period': '2025'})


# ── OECD ─────────────────────────────────────────────────────────────────────

def test_oecd_area_codes():
    r = oecd_tools.ref_area
    assert [r(x) for x in ('USA', 'US', 'Germany', 'GB', 'OECD', 'g20', 'XM', 'euro area', 'EA20')] == \
        ['USA', 'USA', 'DEU', 'GBR', 'OECD', 'G20', 'EA20', 'EA20', 'EA20']
    with pytest.raises(ValueError):
        r('Narnia')


def test_oecd_takes_a_slot_in_the_shared_hourly_budget(monkeypatch, fresh):
    out, fake = _replay('oecd_leading_indicators', monkeypatch)
    assert fake.seen[0]['url'].endswith(',DSD_STES@DF_CLI/USA+DEU+G20.M.LI.IX._Z.AA.IX._Z.H')
    assert fresh.calls == [(oecd_tools.THROTTLE_KEY, 3600.0, oecd_tools.THROTTLE_LIMIT)]
    assert out['series_count'] == 3 and all(s['unit'] == 'Index' for s in out['series'])


def test_oecd_budget_used_up_sends_nothing(monkeypatch):
    full = _Store(allow=False)
    import sajha.core.state as state
    monkeypatch.setattr(state, 'get_state_store', lambda: full)
    monkeypatch.setattr(oecd_tools, 'THROTTLE_WAIT', 0)
    monkeypatch.setattr(outbound, 'request', lambda *a, **k: pytest.fail('no request past the budget'))
    tool, _ = _tool('oecd_get_series')
    with pytest.raises(ValueError, match='budget'):
        tool.execute({'dataflow': 'OECD.SDD.STES,DSD_STES@DF_CLI', 'key': 'USA.M.LI.IX._Z.AA.IX._Z.H'})


def test_oecd_main_indicators_keep_only_what_was_asked(monkeypatch):
    out, _ = _replay('oecd_main_economic_indicators', monkeypatch)
    wanted = {('CP', 'GR', '_Z', '_Z', 'GY'), ('UNEMP', 'PT_LF', '_T', 'Y', '_Z'), ('IRLT', 'PA', '_Z', '_Z', '_Z')}
    dims = ('MEASURE', 'UNIT_MEASURE', 'ACTIVITY', 'ADJUSTMENT', 'TRANSFORMATION')
    assert all(tuple(s['dimensions'][d] for d in dims) in wanted for s in out['series'])
    assert {s['indicator'] for s in out['series']} == {'cpi_inflation', 'unemployment_rate', 'long_term_rate'}


def test_oecd_economic_outlook_marks_projections(monkeypatch):
    out, _ = _replay('oecd_economic_outlook', monkeypatch)
    assert {s['indicator'] for s in out['series']} <= {'gdp_growth', 'inflation'}
    obs = out['series'][0]['observations']
    assert obs[0]['date'] == '2023' and obs[0]['projection'] is False
    assert any(o['projection'] for o in obs) and 'projections' in out['note']


def test_oecd_search_and_a_bare_dataflow_id(monkeypatch):
    out, _ = _replay('oecd_search', monkeypatch)
    refs = [f['dataflow'] for f in out['dataflows']]
    assert 'OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL' in refs
    monkeypatch.setattr(outbound, 'request', lambda *a, **k: pytest.fail('the dataflow list is cached'))
    assert oecd_tools.flow_ref('DF_PRICES_ALL') == 'OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL'
    assert oecd_tools.flow_ref('OECD.SDD.STES,DSD_STES@DF_CLI') == 'OECD.SDD.STES,DSD_STES@DF_CLI'
    with pytest.raises(ValueError, match='unknown'):
        oecd_tools.flow_ref('DF_NOTHING_LIKE_IT')
    with pytest.raises(ValueError, match='must look like'):
        oecd_tools.flow_ref('../etc')


# ── ABS ──────────────────────────────────────────────────────────────────────

def test_abs_cpi_cities_and_units(monkeypatch):
    out, fake = _replay('abs_cpi', monkeypatch)
    assert fake.seen[0]['url'].endswith('/data/ABS,CPI/3.10001.10.50+1.M')
    assert fake.seen[0]['headers']['Accept'].startswith('application/vnd.sdmx.data+csv')
    assert {s['region'] for s in out['series']} == {'australia', 'sydney'}
    assert all(s['unit'] == 'Percent' and s['adjustment'] == 'original' for s in out['series'])
    with pytest.raises(ValueError, match='unknown region'):
        _tool('abs_cpi')[0].execute({'regions': ['Auckland']})


def test_abs_labour_force_and_gdp(monkeypatch):
    lf, _ = _replay('abs_labour_force', monkeypatch)
    by = {s['measure']: s for s in lf['series']}
    assert by['unemployment_rate']['unit'] == 'Percent'
    assert by['employed']['unit'] == 'Number' and by['employed']['unit_multiplier'] == 'thousands'
    gdp, _ = _replay('abs_gdp', monkeypatch)
    by = {s['measure']: s for s in gdp['series']}
    assert by['volume']['unit'] == 'Australian dollars' and by['volume']['unit_multiplier'] == 'millions'
    assert re.fullmatch(r'\d{4}-Q[1-4]', by['growth_qoq']['observations'][0]['date'])


def test_abs_no_records_is_no_data(monkeypatch):
    monkeypatch.setattr(outbound, 'request',
                        lambda *a, **k: outbound.Response(404, 'ERR', {}, b'NoRecordsFound', a[1]))
    out = _tool('abs_get_series')[0].execute({'dataflow': 'WPI', 'key': '3.THRPEB.7.TOT.20.AUS.Q', 'period': '1990'})
    assert out['series'] == [] and 'NoRecordsFound' in out['note']


def test_eurostat_keeps_each_observations_flag(monkeypatch):
    out, _ = _replay('eurostat_gdp', monkeypatch)
    de = next(s for s in out['series'] if s['country'] == 'DE')
    assert any(o.get('flag') == 'p' for o in de['observations'])
    assert out['flags']['p'] == 'provisional'
