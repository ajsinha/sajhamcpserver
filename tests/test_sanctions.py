# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Sanctions screening (sajha/sanctions/, config/tools/sanctions/; docs/architecture/Open Data
Tools.md and docs/tools/public-data/Sanctions Tool Reference Guide.md): the parsers on small
recorded list files, name matching, the refresh and its change diff, the four read tools, the
UN list refused, downloads through the outbound guard, the shipped policy that keeps sanctions_*
from Ask SAJHA and LLM tools, and the shipped refresh workflow. No live calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from sajha.sanctions import match, parse, refresh, service, sources, store

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / 'tests' / 'fixtures' / 'sanctions'
TOOLS = ROOT / 'config' / 'tools' / 'sanctions'


def _bytes(name):
    return (FIX / name).read_bytes()


def fake_fetch(files):
    """A fetch serving fixture files by URL (the OFAC exports, the EU feed and file, the UK file)."""
    seen = []

    def fetch(url):
        seen.append(url)
        for key, name in files.items():
            if key in url:
                if isinstance(name, Exception):
                    raise name
                return _bytes(name)
        raise AssertionError(f'unexpected URL {url}')
    fetch.seen = seen
    return fetch


V1 = {'SDN.XML': 'ofac_sdn.xml', 'CONSOLIDATED.XML': 'ofac_sdn.xml', '/rss': 'eu_rss.xml',
      'xmlFullSanctionsList_1_1': 'eu.xml', 'UK-Sanctions-List': 'uk.xml'}


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv('SAJHA_SANCTIONS_DATA_DIR', str(tmp_path / 'sanctions'))
    store.CACHE.clear()
    yield tmp_path / 'sanctions'
    store.CACHE.clear()


@pytest.fixture
def loaded(data):
    out = refresh.refresh(fetch=fake_fetch(V1))
    assert out['ok'], out
    return data


def _tool(name):
    import importlib
    cfg = json.loads((TOOLS / f'{name}.json').read_text())
    mod, cls = cfg['implementation'].rsplit('.', 1)
    return getattr(importlib.import_module(mod), cls)(cfg), cfg


# ── parsers ─────────────────────────────────────────────────────────────

def test_ofac_parser():
    pub, e = parse.parse_ofac(_bytes('ofac_sdn.xml'), 'ofac_sdn')
    assert pub == '2026-10-09' and set(e) == {'306', '2674', '7777', '4243'}
    bnc = e['306']
    assert bnc['type'] == 'entity' and bnc['programmes'] == ['CUBA'] and bnc['countries'] == ['CH']
    assert [a['name'] for a in bnc['aliases']] == ['BNC', 'NATIONAL BANK OF CUBA']
    assert bnc['aliases'][0]['strength'] == 'weak'
    assert e['2674']['name'] == 'Abu ABBAS' and e['2674']['dates_of_birth'] == ['1948-12-10']
    assert e['7777']['countries'] == ['LY'] and e['7777']['dates_of_birth'] == ['1942']
    assert e['4243']['type'] == 'vessel' and e['4243']['countries'] == ['PA']


def test_eu_parser():
    pub, e = parse.parse_eu(_bytes('eu.xml'))
    assert pub == '2026-09-22' and set(e) == {'13', '120000', '130000'}
    s = e['13']
    assert s['name'] == 'Saddam Hussein Al-Tikriti' and s['reference'] == 'EU.27.28'
    assert s['type'] == 'individual' and s['dates_of_birth'] == ['1937-04-28'] and s['countries'] == ['IQ']
    assert s['programmes'] == ['IRQ'] and s['listed_on'] == '2003-07-07'
    assert e['130000']['type'] == 'entity' and e['130000']['countries'] == ['RU']


def test_uk_parser():
    pub, e = parse.parse_uk(_bytes('uk.xml'))
    assert pub == '2026-10-08' and set(e) == {'AFG0006', 'RUS1800'}
    a = e['AFG0006']
    assert a['name'] == 'MOHAMMAD HASSAN AKHUND' and a['dates_of_birth'] == ['1945', '1946']
    assert a['countries'] == ['AF'] and a['listed_on'] == '2001-01-25' and a['reference'] == 'TAi.002'
    assert len(a['identifiers']) == 1                                      # duplicates collapse
    assert {x['kind'] for x in a['aliases']} == {'alias', 'non_latin'}
    assert e['RUS1800']['type'] == 'vessel' and e['RUS1800']['countries'] == ['KM']


def test_parsers_refuse_the_wrong_file():
    with pytest.raises(ValueError, match='not an OFAC'):
        parse.parse_ofac(_bytes('uk.xml'), 'ofac_sdn')
    with pytest.raises(ValueError, match='not an EU'):
        parse.parse_eu(_bytes('uk.xml'))


def test_dates_and_countries():
    assert parse.norm_date('10 Dec 1948') == '1948-12-10'
    assert parse.norm_date('Feb 1960') == '1960-02'
    assert parse.norm_date('circa 1960') == '1960'
    assert parse.norm_date('dd/mm/1945') == '1945' and parse.norm_date('dd/05/1945') == '1945-05'
    assert parse.norm_date('07/10/1952') == '1952-10-07' and parse.norm_date('') is None
    assert parse.country_code('Russia') == 'RU' and parse.country_code('IRN') == 'IR'
    assert parse.country_code('gb') == 'GB' and parse.country_code('Region: Gaza') == 'PS'
    assert parse.country_code('Atlantis') is None


# ── matching ────────────────────────────────────────────────────────────

def test_normalisation():
    assert match.tokens('Dr. José  MÜLLER-Lüdenscheidt') == ['jose', 'muller', 'ludenscheidt']
    assert match.tokens("Sheikh Abd al-Qadir O'Brien") == ['abd', 'al', 'qadir', 'obrien']
    assert match.tokens('Владимир Путин') == ['vladimir', 'putin']
    assert match.tokens('Müller Trading GmbH', organisation=True) == ['muller', 'trading']
    assert match.tokens('Mr') == ['mr']                                     # never empty


def test_scores():
    s, _ = match.score(match.tokens('Putin Vladimir'), match.tokens('Vladimir Vladimirovich PUTIN'))
    assert s >= 90                                                          # word order, extra word
    assert match.score(match.tokens('Putin Vladimir'), match.tokens('PUTIN Vladimir'))[0] == 100.0
    s, sound = match.score(match.tokens('Muammar Gaddafi'), match.tokens('Muammar QADHAFI'))
    assert sound and s >= 85                                                # phonetic key agrees
    assert match.phonetic('kaddafi') == match.phonetic('qadhafi') == match.phonetic('gaddafi')
    s, _ = match.score(['ali'], match.tokens('Abu Ali Mustafa Hassan'))
    assert s < 85                                                           # one word is not a match
    s, _ = match.score(match.tokens('John Smith'), match.tokens('Maria Gonzalez'))
    assert s < 50
    s, _ = match.score(match.tokens('Vladimir Putin'), match.tokens('Marija Vladimirovna PUTINA'))
    assert s < 85                                                           # a relative is not the person
    s, _ = match.score(match.tokens('Mohammed Ali'), match.tokens('Mohammed Bishr Al-Sabban'))
    assert s < 85                                                           # 'al' is not 'ali'


# ── refresh and the index ───────────────────────────────────────────────

def test_refresh_builds_the_index_and_status(loaded):
    st = store.read_status()
    assert set(st) == {'ofac_sdn', 'ofac_consolidated', 'eu', 'uk'}            # never un
    assert st['ofac_sdn']['publication_date'] == '2026-10-09' and st['ofac_sdn']['entry_count'] == 4
    assert st['eu']['source_published'] == '2026-09-22T18:10:17Z'
    assert (loaded / 'ofac_sdn.json.gz').exists() and (loaded / 'changes.jsonl').exists()
    out = service.lists_status()
    rows = {r['list']: r for r in out['lists']}
    assert rows['uk']['loaded'] and rows['uk']['entry_count'] == 2 and rows['uk']['age_hours'] is not None
    assert rows['un']['enabled'] is False and not rows['un']['loaded'] and 'legal' in rows['un']['disabled_reason']
    assert out['notice'].startswith('Screening aid, not a determination')


def test_refresh_diff_and_changes(loaded):
    v2 = dict(V1, **{'SDN.XML': 'ofac_sdn_v2.xml'})
    out = refresh.refresh(['ofac_sdn', 'eu'], fetch=fake_fetch(v2))
    by = {r['list']: r for r in out['lists']}
    assert by['ofac_sdn']['status'] == 'updated'
    assert (by['ofac_sdn']['added'], by['ofac_sdn']['changed'], by['ofac_sdn']['removed']) == (1, 1, 1)
    assert by['eu']['status'] == 'unchanged'                                # the feed shows no new file
    ch = service.changes('2000-01-01', 'ofac_sdn')
    assert [r['initial'] for r in ch['refreshes']] == [True, False]
    assert [x['entry_id'] for x in ch['added']] == ['9001'] and ch['added'][0]['name'] == 'Ivan PETROV'
    assert [x['entry_id'] for x in ch['changed']] == ['4243']
    assert [x['entry_id'] for x in ch['removed']] == ['2674']
    assert ch['notice'].startswith('Screening aid') and ch['source']
    assert service.changes('2999-01-01')['refreshes'] == []
    with pytest.raises(ValueError, match='YYYY-MM-DD'):
        service.changes('last week')


def test_a_failed_download_keeps_the_previous_index(loaded):
    bad = dict(V1, **{'UK-Sanctions-List': OSError('connection reset')})
    out = refresh.refresh(['uk'], fetch=fake_fetch(bad))
    assert not out['ok'] and 'connection reset' in out['lists'][0]['error']
    st = store.read_status()['uk']
    assert st['entry_count'] == 2 and 'connection reset' in st['last_error']
    assert service.entry('uk', 'AFG0006')['entry']['name'] == 'MOHAMMAD HASSAN AKHUND'


def test_one_refresh_at_a_time(data):
    with refresh._lock(str(data)):
        with pytest.raises(refresh.RefreshBusy):
            refresh.refresh(['uk'], fetch=fake_fetch(V1))


def test_downloads_go_through_the_outbound_guard(monkeypatch):
    from sajha.core import outbound
    calls = []

    class R:
        content = b'x'

        def raise_for_status(self):
            pass

    def fake_request(method, url, **kw):
        calls.append((method, url, kw.get('max_bytes')))
        return R()
    monkeypatch.setattr(outbound, 'request', fake_request)
    assert refresh._fetch(sources.UK_XML) == b'x'
    assert calls == [('GET', sources.UK_XML, refresh.MAX_BYTES)]


def test_the_un_list_is_refused_everywhere(loaded):
    with pytest.raises(ValueError, match='legal approves'):
        service.screen('Abu Ali', lists=['un'])
    with pytest.raises(ValueError, match='legal approves'):
        service.entry('un', '1')
    with pytest.raises(ValueError, match='legal approves'):
        service.changes('2026-01-01', 'un')
    with pytest.raises(ValueError, match='legal approves'):
        refresh.refresh(['un'], fetch=fake_fetch(V1))


# ── screening ───────────────────────────────────────────────────────────

def test_screen_finds_aliases_across_lists(loaded):
    r = service.screen('National Bank of Cuba')
    top = r['matches'][0]
    assert top['list'] in ('ofac_sdn', 'ofac_consolidated') and top['entry_id'] == '306'
    assert top['matched_alias'] == 'NATIONAL BANK OF CUBA' and top['score'] == 100.0
    assert top['programmes'] == ['CUBA'] and top['name'] == 'BANCO NACIONAL DE CUBA'
    assert r['notice'].startswith('Screening aid, not a determination')
    assert {s['list'] for s in r['lists_searched']} == {'ofac_sdn', 'ofac_consolidated', 'eu', 'uk'}
    assert all(s['publication_date'] and s['last_refresh'] for s in r['lists_searched'])
    assert len(r['source']) == 4 and r['lists_missing'] == []


def test_screen_spelling_order_script_and_honorifics(loaded):
    r = service.screen('Colonel Moammar Gaddafi', lists=['ofac_sdn'])
    assert r['matches'] and r['matches'][0]['entry_id'] == '7777' and r['matches'][0]['phonetic_match']
    r = service.screen('PUTIN, Vladimir', lists=['eu'])
    assert r['matches'][0]['entry_id'] == '120000' and r['matches'][0]['score'] >= 90
    r = service.screen('Мохаммад Хассан Ахунд', lists=['uk'])                # Cyrillic spelling
    assert r['matches'] and r['matches'][0]['entry_id'] == 'AFG0006'
    r = service.screen('Muller Trading', lists=['eu'])
    assert r['matches'][0]['entry_id'] == '130000'


def test_screen_filters(loaded):
    assert service.screen('Muammar Qadhafi', date_of_birth='1942-06-07', lists=['ofac_sdn'])['matches'][0]['dob_match']
    assert service.screen('Muammar Qadhafi', date_of_birth='1950', lists=['ofac_sdn'])['matches'] == []
    assert service.screen('Ebano', type='vessel', lists=['ofac_sdn'])['matches']
    assert service.screen('Ebano', type='individual', lists=['ofac_sdn'])['matches'] == []
    r = service.screen('Banco Nacional de Cuba', country='Switzerland', lists=['ofac_sdn'])
    assert r['matches'][0]['country_match'] is True and r['query']['country'] == 'CH'
    assert service.screen('Banco Nacional de Venezuela', threshold=99, lists=['ofac_sdn'])['matches'] == []
    with pytest.raises(ValueError, match='unknown country'):
        service.screen('x', country='Atlantis')


def test_screen_with_no_index_says_how_to_refresh(data):
    with pytest.raises(ValueError, match='python -m sajha.sanctions refresh'):
        service.screen('anyone')


def test_entry(loaded):
    r = service.entry('ofac_sdn', '306')
    assert r['entry']['name'] == 'BANCO NACIONAL DE CUBA' and r['index']['publication_date'] == '2026-10-09'
    assert r['notice'].startswith('Screening aid') and 'OFAC' in r['source']
    with pytest.raises(ValueError, match='no entry'):
        service.entry('ofac_sdn', '999999')


# ── the tools ───────────────────────────────────────────────────────────

READ_TOOLS = ('sanctions_screen', 'sanctions_entry', 'sanctions_changes', 'sanctions_lists_status')


@pytest.mark.parametrize('name', READ_TOOLS + ('sanctions_refresh',))
def test_tool_configs(name):
    tool, cfg = _tool(name)
    ann = cfg['annotations']
    if name in READ_TOOLS:
        assert ann['readOnlyHint'] is True and ann['openWorldHint'] is False
    else:
        assert ann['readOnlyHint'] is False and ann['openWorldHint'] is True
    assert 'Example:' in cfg['description'] and cfg['outputSchema']['type'] == 'object'
    for ex in cfg['inputSchema']['examples']:
        jsonschema.validate(ex, cfg['inputSchema'])
    domain = (TOOLS / 'domain.txt').read_text().strip()
    assert len(cfg['description']) + 2 + len(domain) <= 1024


def test_tools_return_their_output_schema(loaded):
    for name, args in (('sanctions_screen', {'name': 'Banco Nacional de Cuba', 'lists': ['ofac_sdn']}),
                       ('sanctions_entry', {'list': 'ofac_sdn', 'entry_id': '306'}),
                       ('sanctions_changes', {'since': '2000-01-01'}),
                       ('sanctions_lists_status', {})):
        tool, cfg = _tool(name)
        out = tool.execute(args)
        jsonschema.validate(out, cfg['outputSchema'])


def test_refresh_tool_is_for_administrators(data, monkeypatch):
    from sajha.observability.caller import Caller, reset, set_caller
    tool, _ = _tool('sanctions_refresh')
    t = set_caller(Caller('alice', '', ('user',), 'session'))
    try:
        with pytest.raises(PermissionError, match='administrators'):
            tool.execute({})
    finally:
        reset(t)
    monkeypatch.setattr(refresh, '_fetch', fake_fetch(V1))
    t = set_caller(Caller('admin', '', ('admin',), 'session', is_admin=True))
    try:
        out = tool.execute({'lists': ['uk']})
        assert out['ok'] and out['lists'][0]['status'] == 'initial'
        monkeypatch.setattr(refresh, '_fetch', fake_fetch({'UK-Sanctions-List': OSError('down')}))
        with pytest.raises(ValueError, match='uk: OSError: down'):
            tool.execute({'lists': ['uk']})
    finally:
        reset(t)


# ── the shipped policy: no sanctions results for a model ───────────────

@pytest.fixture
def shipped_policy():
    from sajha.core.state import set_state_store
    from sajha.core.state.memory import MemoryStateStore
    from sajha.policy.engine import PolicyEngine, set_engine
    from sajha.policy.loader import PolicySet
    set_state_store(MemoryStateStore())
    eng = PolicyEngine(PolicySet(str(ROOT / 'config' / 'policies')))
    set_engine(eng)
    yield eng
    set_engine(None)
    set_state_store(None)


def test_shipped_policy_blocks_sanctions_for_ask_and_llm_tools(loaded, shipped_policy):
    from sajha.policy import context
    from sajha.policy.errors import PolicyDenied
    tool, _ = _tool('sanctions_screen')
    args = {'name': 'Banco Nacional de Cuba', 'lists': ['ofac_sdn']}
    for src in ('ask', 'openai_api'):
        with context.using_source(src, override=True):
            with pytest.raises(PolicyDenied, match='not given to a model'):
                tool.execute_with_tracking(dict(args))
    for src in ('mcp', 'rest', 'workflow'):                                  # people use the tools directly
        with context.using_source(src, override=True):
            assert tool.execute_with_tracking(dict(args))['matches']
    with context.using_source('ask', override=True):                        # other tools are untouched
        from sajha.policy.engine import Call
        from sajha.observability.caller import current
        assert shipped_policy.evaluate(Call('calc_npv', {}, current(), 'ask')).effect != 'deny'


def test_ask_sajha_refuses_a_sanctions_call(loaded, shipped_policy):
    """Ask SAJHA (and an LLM tool's planner loop, which runs through it) gets a refusal, not results."""
    from sajha.ai.intelligence import IntelligenceService
    from sajha.ai.llm.canonical import ToolCall
    from sajha.ai.llm.settings import AskSettings
    from tests.ai.conftest import ToolBox, make_gateway
    tool, _ = _tool('sanctions_screen')
    svc = IntelligenceService(make_gateway(), ToolBox(with_calc=False), settings=AskSettings(audit=False),
                              audit=lambda e: None)
    step, msg, _extra = svc._run_call(ToolCall.of('c1', 'sanctions_screen', {'name': 'Banco Nacional de Cuba'}),
                                      {'sanctions_screen': tool}, set())
    assert step.status == 'refused' and 'not given to a model' in step.summary
    assert 'BANCO NACIONAL' not in str(msg)


def test_sanctions_tools_are_not_offered_to_a_model(shipped_policy):
    """Not only refused at call time: Ask SAJHA's shortlist (and an LLM tool's allowed set, which is
    ranked through it) never contains a sanctions tool, while the policy leaves them to people."""
    from sajha.ai.intelligence import IntelligenceService
    from sajha.ai.llm import RequestContext
    from sajha.ai.llm.settings import AskSettings
    from sajha.policy import offered
    from tests.ai.conftest import ToolBox, make_gateway
    box = ToolBox(with_calc=True)
    for name in ('sanctions_screen', 'sanctions_entry', 'sanctions_lists_status'):
        box.add(_tool(name)[0])
    svc = IntelligenceService(make_gateway(), box, settings=AskSettings(audit=False, shortlist=50),
                              audit=lambda e: None)
    ctx = RequestContext(user_id='alice')
    names = [t['name'] for t in svc.shortlist('screen Banco Nacional de Cuba against sanctions lists', ctx)]
    assert names and not any(n.startswith('sanctions_') for n in names)
    among = [t['name'] for t in svc.shortlist('sanctions screen', ctx, among=['sanctions_screen', 'calc_npv'])]
    assert among == ['calc_npv']
    tool = box.get_tool('sanctions_screen')
    assert not offered(tool, 'ask') and not offered(tool, 'openai_api')
    assert all(offered(tool, src) for src in ('mcp', 'rest', 'workflow'))


# ── the shipped refresh workflow ────────────────────────────────────────

def test_shipped_workflow_definition_and_install(monkeypatch):
    import yaml
    from sajha.workflows import identity, model, shipped
    defn = model.normalize(yaml.safe_load((ROOT / 'config' / 'workflows' / 'sanctions_refresh.yaml').read_text()))
    assert defn['steps'][0]['tool'] == 'sanctions_refresh'
    assert defn['triggers'][0]['type'] == 'cron'

    class Store:
        def __init__(self):
            self.saved = {}

        def get_workflow(self, name):
            return self.saved.get(name)

    class Svc:
        def __init__(self):
            self.store = Store()

        def validate(self, raw):
            return model.normalize(yaml.safe_load(raw))

        def save(self, d, user_id, is_admin=False):
            self.store.saved[d['name']] = {'owner': user_id, 'definition': d}

    identity.set_resolver(lambda owner: identity.RunIdentity(owner, ['admin'], True))
    try:
        svc = Svc()
        assert 'sanctions_refresh' in shipped.install_shipped(svc)              # with the other shipped ones
        assert svc.store.saved['sanctions_refresh']['owner'] == 'admin'
        assert shipped.install_shipped(svc) == []                           # never overwritten
    finally:
        identity.set_resolver(None)

    def missing(owner):
        raise identity.OwnerUnavailable('no such user')
    identity.set_resolver(missing)
    try:
        assert shipped.install_shipped(Svc()) == []
    finally:
        identity.set_resolver(None)


def test_cli_status(data, capsys):
    from sajha.sanctions.__main__ import main
    assert main(['status']) == 0
    out = json.loads(capsys.readouterr().out)
    assert {r['list'] for r in out['lists']} == set(sources.LISTS)
