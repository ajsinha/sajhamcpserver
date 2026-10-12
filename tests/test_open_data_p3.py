# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Open data P3 (Open Data Tools §4, L36 to L39): the hazards, research, gdelt and us_spending tool folders.

The tools are played back from responses recorded live (tests/fixtures/open_data/<tool>[__case].json); no
test calls a live service. hazards_active_fires needs a NASA FIRMS MAP_KEY, which the recording had not, so
its parser is tested on a CSV in FIRMS's documented column layout."""

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
FOLDERS = ('hazards', 'research', 'gdelt', 'us_spending')
PREFIX = {'hazards': 'hazards', 'research': 'research', 'gdelt': 'gdelt', 'usaspending': 'us_spending',
          'datagov': 'us_spending'}
NO_FIXTURE = {'hazards_active_fires'}       # needs FIRMS_MAP_KEY to record


def _configs(folder):
    return [json.loads(p.read_text(encoding='utf-8')) for p in sorted((TOOLS / folder).glob('*.json'))]


def _tool(name):
    cfg = json.loads((TOOLS / PREFIX[name.split('_')[0]] / f'{name}.json').read_text(encoding='utf-8'))
    module, cls = cfg['implementation'].rsplit('.', 1)
    return getattr(importlib.import_module(module), cls)(cfg), cfg


class _Replay:
    """Stands in for outbound.request: answers each call with the next recorded response for that URL
    (and, for a POST, that JSON body)."""

    def __init__(self, calls):
        self.queue = list(calls)
        self.seen = []

    def __call__(self, method, url, params=None, headers=None, json=None, **_):
        self.seen.append({'method': method, 'url': url, 'params': dict(outbound._param_items(params)),
                          'json': json, 'headers': dict(headers or {})})
        for i, call in enumerate(self.queue):
            if call['url'] == url and call.get('method', 'GET') == method and call.get('json') == json:
                self.queue.pop(i)
                hdrs = dict(call.get('headers') or {}, **{'content-type': call['content_type'] or ''})
                return outbound.Response(call['status'], 'OK', hdrs, call['body'].encode('utf-8'), url)
        raise AssertionError(f'no recorded response for {method} {url}')


class _Store:
    """A state store with only the sliding window the throttles use."""

    def __init__(self, allow=True):
        self.allow, self.hits, self.keys = allow, 0, []

    def window_add(self, key, window, limit=None):
        self.hits += 1
        self.keys.append((key, window, limit))
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
    assert ann['readOnlyHint'] is True and ann['idempotentHint'] is True and ann['openWorldHint'] is True
    assert ann['destructiveHint'] is False
    example = json.loads(re.search(r'\nExample: (\{.*\})\s*$', cfg['description']).group(1))
    assert cfg['inputSchema']['examples'][0] == example
    jsonschema.validate(example, cfg['inputSchema'])
    domain = (TOOLS / folder / 'domain.txt').read_text(encoding='utf-8').strip()
    assert len(domain) <= 600
    assert len(cfg['description']) + 2 + len(domain) <= 1024
    for prop in cfg['inputSchema'].get('required', []):
        assert 'default' not in cfg['inputSchema']['properties'][prop]
    assert cfg['cache_ttl'] > 0                                   # every P3 source is cached
    assert 'source' in cfg['outputSchema']['properties']          # attribution on every result
    assert cfg['name'].split('_')[0] in PREFIX


def test_every_tool_has_a_recorded_fixture_and_a_probe_case():
    for folder in FOLDERS:
        for cfg in _configs(folder):
            name = cfg['name']
            case = ROOT / 'config' / 'tool_tests' / f'{name}.yaml'
            if name in NO_FIXTURE:
                assert not case.exists()
                continue
            assert (FIXTURES / f'{name}.json').exists(), name
            assert case.exists(), name
            assert any((ROOT / 'config' / 'tool_tests' / 'cassettes' / name).glob('*.json')), name


def test_dropped_sources_ship_no_tool():
    """GDACS (no licence; off until legal approves), weather (Open-Meteo non-commercial), GDELT GEO 2.0
    (404) and GDELT TV 2.0 (no data since October 2024)."""
    names = {c['name'] for f in FOLDERS for c in _configs(f)}
    assert not any(w in n for n in names for w in ('disaster_alert', 'weather', 'gdelt_geo', 'gdelt_tv'))


# ── hazards ──────────────────────────────────────────────────────────────────

def test_earthquakes(monkeypatch, store):
    r, replay = _run('hazards_earthquakes', '', monkeypatch)
    assert r['count'] >= 1 and r['source'].startswith('U.S. Geological Survey')
    assert all(q['magnitude'] >= 5 for q in r['earthquakes'])
    assert all(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', q['time']) for q in r['earthquakes'])
    p = replay.seen[0]['params']
    assert p['starttime'] == '2026-10-01' and p['endtime'] == '2026-10-08'      # 'to' is inclusive
    times = [q['time'] for q in r['earthquakes']]
    assert times == sorted(times, reverse=True)


def test_earthquakes_around_a_point(monkeypatch, store):
    r, replay = _run('hazards_earthquakes', 'point', monkeypatch)
    p = replay.seen[0]['params']
    assert p['latitude'] == '35.68' and p['maxradiuskm'] == '300' and p['orderby'] == 'magnitude'
    mags = [q['magnitude'] for q in r['earthquakes']]
    assert mags == sorted(mags, reverse=True)


def test_earthquake_arguments():
    tool, _ = _tool('hazards_earthquakes')
    with pytest.raises(ValueError, match='both latitude and longitude'):
        tool.execute({'latitude': 10})
    with pytest.raises(ValueError, match='from is after to'):
        tool.execute({'from': '2026-10-02', 'to': '2026-10-01'})
    with pytest.raises(ValueError, match='out of range'):
        tool.execute({'bbox': [0, 10, 5, 5]})


def test_significant_earthquakes(monkeypatch, store):
    r, replay = _run('hazards_significant_earthquakes', '', monkeypatch)
    assert replay.seen[0]['url'].endswith('/significant_month.geojson')
    assert r['window'] == 'month' and r['count'] == len(r['earthquakes']) >= 1


FIRMS_CSV = ('latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,'
             'bright_ti5,frp,daynight\n'
             '36.5,-119.2,330.1,0.4,0.6,2026-10-10,912,N20,VIIRS,n,2.0NRT,290.2,5.3,N\n'
             '36.6,-119.3,345.7,0.4,0.6,2026-10-10,2045,N20,VIIRS,h,2.0NRT,300.1,12.9,D\n'
             '36.7,-119.4,301.0,0.4,0.6,2026-10-11,15,N20,VIIRS,l,2.0NRT,280.0,0.9,N\n')


def test_active_fires_needs_a_map_key(monkeypatch, store):
    from sajha.quality.check import _NEEDS_KEY
    monkeypatch.delenv('FIRMS_MAP_KEY', raising=False)
    tool, _ = _tool('hazards_active_fires')
    monkeypatch.setattr(outbound, 'request', lambda *a, **k: pytest.fail('no request without a key'))
    with pytest.raises(ValueError) as e:
        tool.execute({})
    assert _NEEDS_KEY.search(str(e.value))                       # the live check reports not_configured


def test_active_fires_parse(monkeypatch, store):
    from sajha.tools.impl import hazards_tools
    monkeypatch.setenv('FIRMS_MAP_KEY', 'k-firms')
    url = f'{hazards_tools.FIRMS}/k-firms/VIIRS_NOAA20_NRT/-125,32,-114,42/2'
    replay = _Replay([{'url': url, 'status': 200, 'content_type': 'text/csv', 'body': FIRMS_CSV}])
    monkeypatch.setattr(outbound, 'request', replay)
    tool, cfg = _tool('hazards_active_fires')
    args = {'bbox': [-125, 32, -114, 42], 'days': 2, 'min_confidence': 'nominal', 'source': 'VIIRS_NOAA20_NRT', 'limit': 1}
    r = tool.execute(args)
    jsonschema.validate(r, cfg['outputSchema'])
    assert r['total'] == 2 and r['count'] == 1 and r['truncated'] is True
    f = r['fires'][0]
    assert f['acquired'] == '2026-10-10T09:12Z' and f['confidence'] == 'nominal' and f['day_night'] == 'night'
    assert f['frp_mw'] == 5.3 and f['brightness_k'] == 330.1
    assert ('opendata:firms:requests', 600.0, 5000) in store.keys
    bad = _Replay([{'url': url, 'status': 200, 'content_type': 'text/plain', 'body': 'Invalid MAP_KEY.'}])
    monkeypatch.setattr(outbound, 'request', bad)
    with pytest.raises(ValueError, match='refused the MAP_KEY'):
        tool.execute(dict(args))


# ── research ─────────────────────────────────────────────────────────────────

def test_openalex_search_is_a_filter_by_default(monkeypatch, store):
    r, replay = _run('research_search_works', '', monkeypatch)
    p = replay.seen[0]['params']
    assert p['filter'].startswith('title_and_abstract.search:counterparty credit risk')
    assert 'publication_year:>2019' in p['filter'] and 'search' not in p
    assert p['sort'] == 'cited_by_count:desc'
    assert r['mode'] == 'filter' and r['count'] == 5 and r['budget']['remaining_usd'] is not None
    counts = [w['cited_by_count'] for w in r['works']]
    assert counts == sorted(counts, reverse=True)


def test_openalex_key_is_sent(monkeypatch, store):
    from sajha.tools.impl import research_tools
    monkeypatch.setenv('OPENALEX_API_KEY', 'k-oa')
    replay = _Replay([{'url': f'{research_tools.OPENALEX}/works', 'status': 200, 'content_type': 'application/json',
                       'body': '{"meta": {"count": 0}, "results": []}'}])
    monkeypatch.setattr(outbound, 'request', replay)
    tool, _ = _tool('research_search_works')
    r = tool.execute({'query': 'x y', 'full_text_search': True})
    assert replay.seen[0]['params']['api_key'] == 'k-oa' and replay.seen[0]['params']['search'] == 'x y'
    assert r['mode'] == 'search' and r['budget']['keyed'] is True


def test_openalex_work(monkeypatch, store):
    r, replay = _run('research_get_work', '', monkeypatch)
    assert replay.seen[0]['url'].endswith('/works/doi:10.1016/j.jbankfin.2006.07.013')
    assert r['work']['id'].startswith('W') and r['work']['doi'] == '10.1016/j.jbankfin.2006.07.013'
    tool, _ = _tool('research_get_work')
    with pytest.raises(ValueError, match='DOI'):
        tool.execute({'id': 'not an id'})


def test_abstract_from_inverted_index():
    from sajha.tools.impl.research_tools import _abstract
    assert _abstract({'risk': [1], 'Credit': [0], 'matters': [2]}) == 'Credit risk matters'


def test_crossref(monkeypatch, store):
    r, replay = _run('research_crossref_works', '', monkeypatch)
    assert replay.seen[0]['params']['filter'] == 'from-pub-date:2018'
    assert r['count'] == 5 and all(w['doi'] for w in r['works'])
    assert ('opendata:crossref:requests', 1.0, 3) in store.keys
    d, _ = _run('research_crossref_doi', '', monkeypatch)
    assert d['work']['venue'] == 'Journal of Banking & Finance'          # entities unescaped
    assert d['work']['issn'] == ['0378-4266']


def test_crossref_mailto(monkeypatch, store):
    from sajha.tools.impl import research_tools
    monkeypatch.setenv('CROSSREF_MAILTO', 'ops@example.com')
    replay = _Replay([{'url': f'{research_tools.CROSSREF}/works', 'status': 200, 'content_type': 'application/json',
                       'body': '{"message": {"items": [], "total-results": 0}}'}])
    monkeypatch.setattr(outbound, 'request', replay)
    _tool('research_crossref_works')[0].execute({'query': 'var'})
    assert replay.seen[0]['params']['mailto'] == 'ops@example.com'


def test_arxiv(monkeypatch, store):
    if not (FIXTURES / 'research_arxiv_search.json').exists():
        pytest.skip('arXiv not recorded')
    r, replay = _run('research_arxiv_search', '', monkeypatch)
    assert replay.seen[0]['params']['search_query'] == '(all:credit AND all:valuation AND all:adjustment) AND cat:q-fin.RM'
    assert ('opendata:arxiv:requests', 3.0, 1) in store.keys          # one request every 3 seconds
    assert r['count'] >= 1
    assert all(p['abs_url'].startswith('https://arxiv.org/abs/') for p in r['papers'])


def test_arxiv_needs_something(store):
    tool, _ = _tool('research_arxiv_search')
    with pytest.raises(ValueError, match='query, a category'):
        tool.execute({})


# ── gdelt ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name', ['gdelt_articles', 'gdelt_coverage_timeline', 'gdelt_context'])
def test_gdelt(name, monkeypatch, store):
    if not (FIXTURES / f'{name}.json').exists():
        pytest.skip(f'{name} not recorded')
    r, replay = _run(name, '', monkeypatch)
    assert r['source'].startswith('The GDELT Project') and 'gdeltproject.org' in r['source']
    assert replay.seen[0]['params']['format'] == 'json'
    assert ('opendata:gdelt:requests', 5.0, 1) in store.keys          # one request every 5 seconds, shared
    assert r['count'] >= 1


def test_gdelt_retries_one_429_and_reports_query_errors(monkeypatch, store):
    from sajha.tools.impl import gdelt_tools
    url = f'{gdelt_tools.BASE}/context/context'
    replay = _Replay([{'url': url, 'status': 429, 'content_type': 'text/plain', 'body': 'Please limit requests'},
                      {'url': url, 'status': 200, 'content_type': 'application/json', 'body': '{"articles": []}'}])
    monkeypatch.setattr(outbound, 'request', replay)
    r = _tool('gdelt_context')[0].execute({'query': 'banks'})
    assert r['count'] == 0 and len(replay.seen) == 2
    bad = _Replay([{'url': url, 'status': 200, 'content_type': 'text/html', 'body': 'Your query was too short.'}])
    monkeypatch.setattr(outbound, 'request', bad)
    with pytest.raises(ValueError, match='refused the query'):
        _tool('gdelt_context')[0].execute({'query': 'ab'})


def test_gdelt_throttle_gives_up(monkeypatch):
    import sajha.core.state as state
    from sajha.tools.impl import open_data_common
    monkeypatch.setattr(state, 'get_state_store', lambda: _Store(allow=False))
    monkeypatch.setattr(outbound, 'request', lambda *a, **k: pytest.fail('no request past the budget'))
    with pytest.raises(ValueError, match='budget'):
        open_data_common.take_slot('opendata:gdelt:requests', 1, 5.0, 0, 'GDELT')


def test_gdelt_range():
    tool, _ = _tool('gdelt_articles')
    with pytest.raises(ValueError, match='at most 92 days'):
        tool.execute({'query': 'x y', 'from': '2026-01-01', 'to': '2026-09-01'})


# ── us_spending ──────────────────────────────────────────────────────────────

def test_usaspending_awards(monkeypatch, store):
    r, replay = _run('usaspending_awards', '', monkeypatch)
    body = replay.seen[0]['json']
    assert replay.seen[0]['method'] == 'POST'
    assert body['filters']['award_type_codes'] == ['A', 'B', 'C', 'D']
    assert body['filters']['agencies'][0]['name'] == 'Department of Defense'
    assert r['count'] == 10 and all(a['url'].startswith('https://www.usaspending.gov/award/') for a in r['awards'])
    amounts = [a['amount'] for a in r['awards']]
    assert amounts == sorted(amounts, reverse=True)
    loans, replay = _run('usaspending_awards', 'loans', monkeypatch)
    assert 'Loan Value' in replay.seen[0]['json']['fields'] and loans['awards'][0]['amount'] > 0


def test_usaspending_rules():
    tool, _ = _tool('usaspending_awards')
    with pytest.raises(ValueError, match='one award group'):
        tool.execute({'award_types': ['contracts', 'grants']})
    with pytest.raises(ValueError, match='2007-10-01'):
        tool.execute({'from': '2001-01-01', 'to': '2002-01-01'})


def test_usaspending_category_time_recipient(monkeypatch, store):
    c, replay = _run('usaspending_by_category', '', monkeypatch)
    assert replay.seen[0]['url'].endswith('/search/spending_by_category/recipient/') and c['count'] == 5
    t, _ = _run('usaspending_over_time', '', monkeypatch)
    assert [p['period'] for p in t['points']] == ['2023', '2024', '2025', '2026']
    s, _ = _run('usaspending_recipient', '', monkeypatch)
    assert s['matches'][0]['level'] == 'parent' and s['total'] >= s['count']
    p, replay = _run('usaspending_recipient', 'profile', monkeypatch)
    assert replay.seen[0]['params'] == {'year': 'latest'}
    assert p['recipient']['uei'] and p['recipient']['parent_name']
    with pytest.raises(ValueError, match='recipient id'):
        _tool('usaspending_recipient')[0].execute({'id': 'nope'})


def test_datagov_contract(monkeypatch, store):
    """The new catalogue API (OpenAPI 'Datagov Catalog' 0.1.0) is undocumented: pin the shape we read."""
    s, replay = _run('datagov_search', '', monkeypatch)
    assert replay.seen[0]['url'] == 'https://catalog.data.gov/search'
    assert replay.seen[0]['params'] == {'q': 'consumer complaints', 'org_slug': 'cfpb', 'per_page': '5'}
    raw = json.loads(json.loads((FIXTURES / 'datagov_search.json').read_text())['calls'][0]['body'])
    assert {'results', 'sort'} <= set(raw) and {'slug', 'title', 'organization', 'dcat'} <= set(raw['results'][0])
    assert s['datasets'][0]['id'] == 'consumer-complaint-database'
    d, replay = _run('datagov_dataset', '', monkeypatch)
    assert replay.seen[0]['url'] == 'https://catalog.data.gov/api/dataset/consumer-complaint-database'
    assert d['dataset']['distributions'] and d['dataset']['contact_email'] == 'devops@cfpb.gov'
    with pytest.raises(ValueError, match='slug'):
        _tool('datagov_dataset')[0].execute({'id': '../etc'})
