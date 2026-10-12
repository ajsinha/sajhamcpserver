# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Phase 8.3, P1 (Open Data Tools §4, §5): the gleif and bis folders and the Wikidata tools in the
wikipedia folder. Each tool replays the responses recorded from the live service on 2026-10-11
(tests/fixtures/open_data/<tool>[__case].json); no test calls a live service."""

import importlib
import json
import re
from datetime import date
from pathlib import Path
from unittest import mock

import jsonschema
import pytest

from sajha.core import outbound
from sajha.tools.impl import bis_tools, gleif_tools, sdmx_client, wikidata_tools
from tests.tool_config_files import read_tool

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / 'tests' / 'fixtures' / 'open_data'
PREFIXES = ('gleif_', 'bis_', 'wikidata_')
TOOLS = sorted(p.stem for f in ('gleif', 'bis') for p in (ROOT / 'config' / 'tools' / f).glob('*.json')) + \
    sorted(p.stem for p in (ROOT / 'config' / 'tools' / 'wikipedia').glob('wikidata_*.json'))
RECORDED = sorted(p for p in FIXTURES.glob('*.json') if p.stem.startswith(PREFIXES))


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
        params = [list(p) for p in (params or [])]
        self.seen.append({'url': url, 'params': params, 'headers': headers or {}})
        for i, c in enumerate(self.calls):
            if c['url'] == url and c['params'] == params:
                self.calls.pop(i)
                return outbound.Response(c['status'], 'OK' if c['status'] < 400 else 'ERR',
                                         {'content-type': c['content_type']}, c['body'].encode('utf-8'), url)
        raise AssertionError(f'unrecorded request {url} {params}')


def _replay(fixture):
    data = json.loads(fixture.read_text(encoding='utf-8'))
    tool, cfg = _tool(data['tool'])
    fake = _Replay(data['calls'])
    with mock.patch.object(outbound, 'request', fake):
        out = tool.execute(data['arguments'])
    return out, cfg, fake


@pytest.fixture(autouse=True)
def _fresh_cache():
    sdmx_client.clear_cache()
    yield


def test_every_tool_has_a_recording():
    assert len(TOOLS) == 16
    recorded = {json.loads(p.read_text())['tool'] for p in RECORDED}
    assert recorded == set(TOOLS)


@pytest.mark.parametrize('fixture', RECORDED, ids=lambda p: p.stem)
def test_recorded_response_replays_and_matches_the_output_schema(fixture):
    out, cfg, fake = _replay(fixture)
    jsonschema.validate(out, cfg['outputSchema'])
    assert out['source'].startswith('Source: ')
    assert not fake.calls, 'recorded calls left unused'
    for call in fake.seen:
        assert call['headers'].get('User-Agent', '').startswith('SAJHA-MCP-Server')


# ── GLEIF ────────────────────────────────────────────────────────────────────

def test_gleif_lookup_by_lei_and_isin():
    out, _, _ = _replay(FIXTURES / 'gleif_lookup.json')
    assert out['legal_name'] == 'Apple Inc.' and out['headquarters_address']['city'] == 'Cupertino'
    out, _, fake = _replay(FIXTURES / 'gleif_lookup__isin.json')
    assert out['lei'] == 'HWUPKR0MPOU8FGXBT394' and out['isin'] == 'US0378331005'
    assert fake.seen[0]['params'] == [['filter[isin]', 'US0378331005']]
    tool, _ = _tool('gleif_lookup')
    with pytest.raises(ValueError, match='not an LEI'):
        tool.execute({'lei': 'ABC'})


def test_gleif_parents_reported_exception_and_not_applicable():
    out, _, _ = _replay(FIXTURES / 'gleif_parents.json')
    assert out['direct_parent']['status'] == 'reported'
    assert out['direct_parent']['parent']['lei'] == '7LTWFZYICNSX8D621K86'
    out, _, _ = _replay(FIXTURES / 'gleif_parents__top.json')
    assert out['ultimate_parent'] == {'status': 'reporting_exception', 'exception': {
        'category': 'ULTIMATE_ACCOUNTING_CONSOLIDATION_PARENT', 'reason': 'NO_KNOWN_PERSON', 'reference': None}}
    # a 404 on both the parent and the exception: not applicable, not an error
    record = json.dumps({'data': {'id': '7LTWFZYICNSX8D621K86', 'attributes': {'lei': '7LTWFZYICNSX8D621K86'},
                                  'relationships': {}}})

    def answer(method, url, **_):
        status, body = (200, record) if url.endswith('K86') else (404, '{"errors": []}')
        return outbound.Response(status, '', {'content-type': 'application/json'}, body.encode(), url)
    tool, _ = _tool('gleif_parents')
    with mock.patch.object(outbound, 'request', answer):
        out = tool.execute({'lei': '7LTWFZYICNSX8D621K86'})
    assert out['direct_parent'] == {'status': 'not_applicable'} == out['ultimate_parent']


def test_gleif_unknown_lei_and_upstream_errors():
    tool, _ = _tool('gleif_lookup')
    html = lambda status: (lambda m, url, **_: outbound.Response(status, '', {'content-type': 'text/html'},
                                                                  b'<html/>', url))
    with mock.patch.object(outbound, 'request', html(404)):
        with pytest.raises(ValueError, match='No LEI record'):
            tool.execute({'lei': 'AAAAAAAAAAAAAAAAAA00'})
    with mock.patch.object(outbound, 'request', html(503)):
        with pytest.raises(ValueError, match='HTTP 503'):
            tool.execute({'lei': 'AAAAAAAAAAAAAAAAAA00'})


def test_gleif_search_filters_and_fuzzy_fallback():
    out, _, fake = _replay(FIXTURES / 'gleif_search.json')
    params = dict(map(tuple, fake.seen[0]['params']))
    assert params['filter[entity.names]'] == 'Deutsche Bank'
    assert params['filter[entity.legalAddress.country]'] == 'DE' and params['filter[entity.status]'] == 'ACTIVE'
    assert out['matched_by'] == 'name' and any(r['lei'] == '7LTWFZYICNSX8D621K86' for r in out['results'])
    out, _, fake = _replay(FIXTURES / 'gleif_search__fuzzy.json')
    assert fake.seen[1]['url'].endswith('/fuzzycompletions') and out['results'] == [] and out['note']
    assert [dict(map(tuple, c['params']))['field'] for c in fake.seen[1:]] == ['fulltext', 'entity.legalName']


def test_gleif_children_and_isins_page():
    out, _, _ = _replay(FIXTURES / 'gleif_children.json')
    assert out['total'] == out['result_count'] > 0 and out['more'] is False
    out, _, _ = _replay(FIXTURES / 'gleif_isins.json')
    assert out['result_count'] == 20 and out['more'] is True and all(len(i) == 12 for i in out['isins'])


# ── BIS ──────────────────────────────────────────────────────────────────────

def test_bis_host_profile_goes_through_the_shared_client():
    h = sdmx_client.host('bis')
    assert h.base_url == 'https://stats.bis.org/api/v1' and h.csv_accept.startswith('application/vnd.sdmx.data+csv')
    out, _, fake = _replay(FIXTURES / 'bis_policy_rates.json')
    assert fake.seen[0]['url'] == 'https://stats.bis.org/api/v1/data/WS_CBPOL/M.US+GB+XM'
    assert fake.seen[0]['headers']['Accept'].startswith('application/vnd.sdmx.data+csv')
    assert {s['country'] for s in out['series']} == {'US', 'GB', 'XM'}
    assert all(s['unit'] == 'Per cent per year' for s in out['series'])


@pytest.mark.parametrize('fixture', [p for p in RECORDED if p.stem.startswith('bis_')], ids=lambda p: p.stem)
def test_bis_cites_the_bis_on_every_output(fixture):
    out, _, _ = _replay(fixture)
    assert 'Source: BIS' in out['source'] and out['series']


def test_bis_units_and_keys():
    out, _, _ = _replay(FIXTURES / 'bis_credit_gap.json')
    assert out['key'] == 'Q.US+CN.P.A.C' and out['series'][0]['unit'] == 'Percentage points of GDP'
    out, _, _ = _replay(FIXTURES / 'bis_total_credit.json')
    assert {s['unit'] for s in out['series']} == {'Percentage of GDP'}
    out, _, _ = _replay(FIXTURES / 'bis_property_prices.json')
    assert out['key'] == 'Q.US+DE.R.771'
    out, _, _ = _replay(FIXTURES / 'bis_effective_exchange_rates.json')
    assert out['key'] == 'M.R.B.US+JP' and out['series'][0]['unit'] == 'Index, 2020 = 100'
    tool, _ = _tool('bis_effective_exchange_rates')
    with pytest.raises(ValueError, match='monthly only'):
        tool.execute({'countries': ['US'], 'real': True, 'frequency': 'daily'})


def test_bis_countries_and_periods():
    assert [bis_tools.area_code(c) for c in ('us', 'GBR', 'Euro area', 'Japan', 'XM')] == ['US', 'GB', 'XM', 'JP', 'XM']
    with pytest.raises(ValueError, match='Unknown country'):
        bis_tools.area_code('Atlantis')
    today = date(2026, 10, 11)
    assert bis_tools.period_params('latest') == {'last_n': 1}
    assert bis_tools.period_params('last 12 months', today) == {'start': '2025-10'}
    assert bis_tools.period_params('last 4 quarters', today) == {'start': '2025-Q4'}
    assert bis_tools.period_params('last 5 years', today) == {'start': '2021'}
    assert bis_tools.period_params('last 10 days', today) == {'start': '2026-10-01'}
    assert bis_tools.period_params('2025-Q3') == {'start': '2025-Q3', 'end': '2025-Q3'}
    assert bis_tools.period_params('2020-Q1/2025-Q4') == {'start': '2020-Q1', 'end': '2025-Q4'}
    assert bis_tools.period_params('2024-01 to 2024-06') == {'start': '2024-01', 'end': '2024-06'}
    with pytest.raises(ValueError, match='Unreadable period'):
        bis_tools.period_params('yesterday')


def test_bis_no_data_is_a_note_and_errors_are_errors():
    tool, _ = _tool('bis_get_series')
    nodata = lambda m, url, **_: outbound.Response(404, '', {'content-type': 'application/xml'}, b'NoRecordsFound', url)
    with mock.patch.object(outbound, 'request', nodata):
        out = tool.execute({'dataflow': 'WS_EER', 'key': 'D.R.B.US', 'period': 'latest'})
    assert out['series'] == [] and 'no data' in out['note'] and 'Source: BIS' in out['source']
    boom = lambda m, url, **_: outbound.Response(500, '', {'content-type': 'text/html'}, b'<h1>x</h1>', url)
    with mock.patch.object(outbound, 'request', boom):
        with pytest.raises(ValueError, match='BIS: .*HTTP 500'):
            tool.execute({'dataflow': 'WS_EER', 'key': 'M.R.B.US'})


# ── Wikidata ─────────────────────────────────────────────────────────────────

def test_wikidata_entity_and_company_identifiers():
    out, _, _ = _replay(FIXTURES / 'wikidata_entity.json')
    assert out['properties']['P1278']['values'] == ['7LTWFZYICNSX8D621K86']
    assert out['properties']['P159']['values'][0]['label'] == 'Frankfurt'
    out, _, _ = _replay(FIXTURES / 'wikidata_company_identifiers.json')
    assert out['lei'] == '7LTWFZYICNSX8D621K86' and out['isins'] == ['DE0005140008']
    assert {'ticker': 'DB', 'exchange_qid': 'Q13677', 'exchange': 'New York Stock Exchange'} in out['tickers']


def test_wikidata_sparql_is_read_only_and_capped():
    check = wikidata_tools.check_read_only
    assert check('PREFIX wd: <http://www.wikidata.org/entity/> SELECT ?x WHERE { ?x ?p wd:Q1 }')
    assert check('# ask\nASK { wd:Q1 ?p ?o }')
    for bad in ('INSERT DATA { <a> <b> <c> }', 'DESCRIBE wd:Q1',
                'SELECT * WHERE { ?s ?p ?o } ; DELETE WHERE { ?s ?p ?o }'):
        with pytest.raises(ValueError):
            check(bad)
    assert check('SELECT ?x WHERE { ?x rdfs:label "delete me" }')     # words inside literals are fine
    out, _, fake = _replay(FIXTURES / 'wikidata_sparql.json')
    assert fake.seen[0]['url'] == 'https://query.wikidata.org/sparql'
    assert dict(map(tuple, fake.seen[0]['params']))['query'].endswith('LIMIT 101')
    assert out['rows'] == [{'item': 'http://www.wikidata.org/entity/Q66048', 'itemLabel': 'Deutsche Bank'}]
    out, _, _ = _replay(FIXTURES / 'wikidata_sparql__ask.json')
    assert out['boolean'] is True
    tool, _ = _tool('wikidata_sparql')
    body = json.dumps({'head': {'vars': ['n']}, 'results': {'bindings': [
        {'n': {'type': 'literal', 'value': str(i), 'datatype': 'http://www.w3.org/2001/XMLSchema#integer'}}
        for i in range(5)]}})
    seen = []

    def answer(method, url, params=None, **_):
        seen.append(url)
        return outbound.Response(200, '', {'content-type': 'application/json'}, body.encode(), url)
    with mock.patch.object(outbound, 'request', answer):
        out = tool.execute({'query': 'SELECT ?n WHERE { } LIMIT 5', 'max_rows': 2, 'graph': 'scholarly'})
    assert seen == ['https://query-scholarly.wikidata.org/sparql']
    assert out['rows'] == [{'n': 0}, {'n': 1}] and out['truncated'] is True


# ── configs ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name', TOOLS)
def test_config_rules(name):
    tool, cfg = _tool(name)
    assert cfg['annotations'] == {'readOnlyHint': True, 'idempotentHint': True, 'openWorldHint': True}
    desc = cfg['description']
    m = re.search(r'Example: (\{.*\})$', desc, re.S)
    assert m and json.loads(m.group(1)) == cfg['inputSchema']['examples'][0]
    tool.validate_arguments(cfg['inputSchema']['examples'][0])
    folder = 'wikipedia' if name.startswith('wikidata_') else name.split('_')[0]
    dom = ROOT / 'config' / 'tools' / folder / 'domain.txt'
    domain = dom.read_text(encoding='utf-8').strip() if dom.exists() else ''
    assert len(domain) <= 600
    assert len(desc) + (len(domain) + 2 if domain else 0) <= 1024
