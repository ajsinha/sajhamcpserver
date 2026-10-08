# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA Net residency (design §12 and §13; protocol §15.4 step 12, §17 ``-32012``; conformance CALL-07 and
the ``residency_result`` part of FB-01): data classes, residency rules on arguments and results,
field-level redaction both ways, residency-aware shortlists, memory handling of remote results, audit.

The end-to-end test runs three instances in one process (as tests/net/test_net_three_instances.py):
risk-eu (the home, EU, entity acme-eu), cust-eu (EU, acme-eu) and cust-na (US, acme-us).
"""

import json
import textwrap

import pytest

from sajha.net import EXTENSION_ID
from sajha.net import residency as R
from sajha.net.integration import residency as NR
from sajha.net.integration import set_service
from sajha.policy.engine import Call, PolicyEngine, set_engine
from sajha.policy.loader import PolicySet
from sajha.policy.model import PolicyParseError, parse_text
from sajha.tools.base_mcp_tool import BaseMCPTool
from tests.net.test_net_three_instances import isolate  # noqa: F401  (the fixture)

NET = 'acme-net'

RULES = """
rules:
  - id: eu-personal-stays-in-eu
    match: {data_classes: [eu-personal], flow: arguments, destination: {labels.jurisdiction: {ne: EU}}}
    effect: deny
    reason: EU personal data stays in the EU
  - id: internal-fields-stay-in-the-entity
    match: {data_classes: [internal], flow: arguments, destination: {differs_from_here: [labels.entity]}}
    redact: {data_classes: [internal]}
  - id: confidential-results-stay-in-the-entity
    match: {data_classes: [confidential], flow: results, destination: {differs_from_here: [labels.entity]}}
    effect: deny
  - id: eu-personal-results-masked-outside-eu
    match: {data_classes: [eu-personal], flow: results, destination: {labels.jurisdiction: {ne: EU}}}
    redact: {data_classes: [eu-personal]}
  - id: staff-names-not-kept-here
    match: {data_classes: [staff], flow: results, destination: {here: true}}
    redact: {data_classes: [staff]}
"""


def use(*docs) -> PolicyEngine:
    ps = PolicySet()
    ps.set_policies([parse_text(textwrap.dedent(d), f'p{i}', f'p{i}.yaml') for i, d in enumerate(docs)])
    eng = PolicyEngine(ps)
    set_engine(eng)
    return eng


@pytest.fixture(autouse=True)
def _clean():
    yield
    set_engine(None)
    NR.set_settings(None)


# ── the core: marks and field redaction ─────────────────────────────

SCHEMA = {'type': 'object', 'required': ['customer_id'], 'properties': {
    'customer_id': {'type': 'string', 'x-sajha-data-class': 'eu-personal'},
    'note': {'type': 'string', 'x-sajha-data-class': ['internal', 'confidential']},
    'rows': {'type': 'array', 'items': {'type': 'object', 'properties': {
        'email': {'type': 'string', 'x-sajha-data-class': 'eu-personal'}, 'n': {'type': 'integer'}}}}}}


def test_schema_marks_presence_and_necessary_classes():
    marks = R.schema_marks(SCHEMA)
    assert marks == {'customer_id': ['eu-personal'], 'note': ['internal', 'confidential'],
                     'rows.[].email': ['eu-personal']}
    assert R.classes_present({'customer_id': 'x'}, marks) == ['eu-personal']
    assert sorted(R.classes_present({'note': 'n', 'rows': [{'n': 1}]}, marks)) == ['confidential', 'internal']
    assert R.classes_present({'rows': [{'email': 'a@b.eu'}]}, marks) == ['eu-personal']
    # every call sends the required field's class; an optional field's class only when sent
    assert R.necessary_classes(SCHEMA) == ['eu-personal']
    assert R.necessary_classes({'type': 'object', 'properties': {'q': {'type': 'string'}}}, ['public']) == ['public']


def test_field_redaction_of_arguments_and_results():
    marks = R.schema_marks(SCHEMA)
    red, touched, removed = R.redact_fields({'customer_id': 'C-991', 'rows': [{'email': 'ana@x.eu', 'n': 2}]},
                                            marks, ['eu-*'])
    assert red == {'customer_id': '[REDACTED:eu-personal]', 'rows': [{'email': '[REDACTED:eu-personal]', 'n': 2}]}
    assert touched == ['customer_id', 'rows.[].email'] and set(removed) == {'C-991', 'ana@x.eu'}
    # a result: structured content, the JSON text block and a value quoted in prose are all redacted
    result = {'content': [{'type': 'text', 'text': '{"customer_id": "C-991", "rows": []}'},
                          {'type': 'text', 'text': 'Customer C-991 is retail.'}],
              'structuredContent': {'customer_id': 'C-991', 'rows': []}}
    out, touched = R.redact_result(result, marks, ['eu-personal'])
    assert touched == ['customer_id']
    assert out['structuredContent']['customer_id'] == '[REDACTED:eu-personal]'
    assert 'C-991' not in str(out['content'])
    assert result['structuredContent']['customer_id'] == 'C-991'          # the original is untouched
    # a whole-tool class cannot be removed field by field: the caller is told (and SAJHA refuses)
    _, touched, _ = R.redact_fields({'a': 1}, {'*': ['confidential']}, ['confidential'])
    assert touched == ['*']


# ── the policy language: new conditions ─────────────────────────────

def test_policy_conditions_parse_strictly():
    p = parse_text(RULES, 'residency')
    m = p.rules[0].match
    assert m.residency and m.data_classes == ['eu-personal'] and m.flow == ['arguments']
    assert p.rules[1].match.differs_from_here == ['labels.entity']
    assert p.rules[1].redact.data_classes == ('internal',) and not p.rules[1].redact.empty()
    for bad in ('rules: [{match: {flow: sideways}}]',
                'rules: [{match: {destination: {country: US}}}]',
                'rules: [{match: {destination: {labels: EU}}}]',
                'rules: [{match: {destination: [EU]}}]',
                'rules: [{redact: {data_classes: [x], colour: red}}]'):
        with pytest.raises(PolicyParseError):
            parse_text(bad, 'bad')


def _call(classes, flow, dest_labels, here_labels=None, tool='t'):
    from types import SimpleNamespace
    who = SimpleNamespace(user_id='alice', roles=('user',), api_key='', auth_type='sajhanet')
    return Call(tool, {}, who, 'sajhanet', data_classes=classes, flow=flow,
                destination={'net': NET, 'instance': 'x', 'region': '', 'labels': dest_labels, 'here': False},
                here={'net': NET, 'instance': 'me', 'labels': here_labels or {'entity': 'acme-eu'}, 'here': True})


def test_engine_residency_decisions(monkeypatch):
    eng = use(RULES)
    assert eng.residency(_call(['eu-personal'], 'arguments', {'jurisdiction': 'US'})).effect == 'deny'
    assert eng.residency(_call(['eu-personal'], 'arguments', {'jurisdiction': 'EU'})).effect == 'allow'
    assert eng.residency(_call(['eu-personal'], 'arguments', {})).effect == 'deny'      # unlabelled: not EU
    d = eng.residency(_call(['internal'], 'arguments', {'entity': 'acme-us'}))
    assert d.effect == 'allow' and d.redact.data_classes == ('internal',)
    assert eng.residency(_call(['internal'], 'arguments', {'entity': 'acme-eu'})).redact is None
    assert eng.residency(_call(['confidential'], 'results', {'entity': 'acme-us'})).effect == 'deny'
    assert eng.residency(_call(['public'], 'results', {'entity': 'acme-us'})).effect == 'allow'
    # an ordinary call (no flow, no destination) never matches a residency rule
    assert eng.evaluate(Call('t', {}, _call([], None, {}).caller, 'mcp', data_classes=['eu-personal'])).effect == 'allow'
    # default_effect deny: classified data needs an allow rule
    from sajha.policy import engine as E
    monkeypatch.setattr(E, '_cfg', lambda k, d='': 'deny' if k == 'sajhanet.residency.default_effect' else d)
    assert eng.residency(_call(['public'], 'results', {'entity': 'acme-eu'})).kind == 'default_deny'
    assert eng.residency(_call([], 'results', {'entity': 'acme-eu'})).effect == 'allow'


def test_local_call_field_redaction_by_class():
    """A rule with only data classes also governs this server's own calls (output fields by class)."""
    use("""
    rules:
      - id: no-staff-names
        match: {data_classes: [staff], tools: [desk_report]}
        redact: {data_classes: [staff]}
    """)
    t = Typed('desk_report', props={'desk': {'type': 'string', 'x-sajha-data-class': 'staff'}},
              out={'desk': {'type': 'string'}, 'trader': {'type': 'string', 'x-sajha-data-class': 'staff'}},
              result=lambda a: {'desk': 'rates', 'trader': 'J. Smith'})
    assert t.execute_with_tracking({'desk': 'rates'}) == {'desk': 'rates', 'trader': '[REDACTED:staff]'}


# ── memory of remote results ────────────────────────────────────────

class Step:
    def __init__(self, net, ok=True):
        self.net, self.ok, self.name = net, ok, 'remote_tool'


def test_memory_modes_by_class():
    NR.set_settings(NR.ResidencySettings(memory_default='store',
                                         memory_by_class={'confidential': 'none', 'eu-*': 'summary'}))
    assert NR.memory_mode([]) == 'store'
    assert NR.memory_mode(['eu-personal']) == 'summary'
    assert NR.memory_mode(['eu-personal', 'confidential']) == 'none'          # the strictest wins
    answer = 'VaR is 1,843,200.50 EUR (99%) for Ana.'
    assert NR.memory_answer(answer, [Step(None)]) == (answer, 'store')        # no remote result
    assert NR.memory_answer(answer, [Step({'instance': 'cust-na'})]) == (answer, 'store')
    text, mode = NR.memory_answer(answer, [Step({'instance': 'cust-eu', 'data_classes': ['eu-personal']})])
    assert mode == 'summary' and '1,843,200.50' not in text and '99%' not in text and 'EUR' in text
    text, mode = NR.memory_answer(answer, [Step({'instance': 'cust-na', 'data_classes': ['confidential']})])
    assert mode == 'none' and 'not stored' in text and 'EUR' not in text
    NR.set_settings(NR.ResidencySettings(memory_default='none'))
    assert NR.memory_answer(answer, [Step({'instance': 'cust-na'})])[1] == 'none'


def test_memory_store_keeps_what_residency_allows(tmp_path):
    from sqlalchemy import create_engine
    from sajha.ai.intelligence import AskResult, _net_of
    from sajha.ai.memory import ConversationMemory, ConversationStore, MemoryContext
    from sajha.ai.llm.types import RequestContext
    NR.set_settings(NR.ResidencySettings(memory_by_class={'confidential': 'none'}))
    store = ConversationStore(create_engine(f'sqlite:///{tmp_path / "m.db"}'))
    mem = ConversationMemory(None, store=store)
    out = {'content': [], '_meta': {EXTENSION_ID: {'net': NET, 'instance': 'cust-na',
                                                   'data_classes': {'results': ['confidential']}}}}
    net = _net_of(out)
    assert net['data_classes'] == ['confidential']
    res = AskResult(question='q', answer='The balance is 1843200.5 EUR.')
    res.steps.append(Step(net))
    mc = MemoryContext(conversation_id='c' * 32, is_new=True)
    ctx = RequestContext(user_id='alice')
    assert mem.record(mc, ctx, 'q', res) == 1
    assert '1843200' not in store.turns('c' * 32, 'alice')[0]['answer']


# ── end to end: three instances ─────────────────────────────────────

class Typed(BaseMCPTool):
    """A tool with marked schemas that returns ``result(arguments)`` and records what it received."""

    def __init__(self, name, props, out=None, required=(), result=None, owner=''):
        cfg = {'name': name, 'description': f'{name} on {owner}', 'version': '1.0.0', 'enabled': True,
               'inputSchema': {'type': 'object', 'properties': props, 'required': list(required)},
               'annotations': {'readOnlyHint': True}}
        if out:
            cfg['outputSchema'] = {'type': 'object', 'properties': out}
        super().__init__(cfg)
        self.result = result or (lambda a: {'echo': a, 'host': owner})
        self.received = []

    def get_input_schema(self):
        return self._input_schema

    def get_output_schema(self):
        return self._output_schema or {}

    def execute(self, arguments):
        self.received.append(dict(arguments))
        return self.result(arguments)


def tools_for(owner):
    lookup = Typed('customer_lookup', {'customer_id': {'type': 'string', 'x-sajha-data-class': 'eu-personal'}},
                   out={'name': {'type': 'string', 'x-sajha-data-class': 'eu-personal'},
                        'segment': {'type': 'string'}, 'host': {'type': 'string'}},
                   required=['customer_id'], owner=owner,
                   result=lambda a, o=owner: {'name': 'Ana Silva', 'segment': 'retail', 'host': o})
    notes = Typed('note_search', {'q': {'type': 'string'},
                                  'email': {'type': 'string', 'x-sajha-data-class': 'eu-personal'},
                                  'desk': {'type': 'string', 'x-sajha-data-class': 'internal'}}, owner=owner,
                  result=lambda a, o=owner: f'{o}:{a}')
    out = [lookup, notes]
    if owner == 'cust-na':
        out.append(Typed('account_balance', {'account': {'type': 'string'}},
                         out={'balance': {'type': 'number', 'x-sajha-data-class': 'confidential'},
                              'currency': {'type': 'string'}}, owner=owner,
                         result=lambda a: {'balance': 1843200.5, 'currency': 'EUR'}))
        out.append(Typed('us_kyc', {'passport': {'type': 'string', 'x-sajha-data-class': 'eu-personal'}},
                         required=['passport'], owner=owner))
    if owner == 'cust-eu':
        out.append(Typed('desk_report', {'desk': {'type': 'string'}}, owner=owner,
                         out={'desk': {'type': 'string'}, 'trader': {'type': 'string', 'x-sajha-data-class': 'staff'}},
                         result=lambda a: {'desk': a.get('desk'), 'trader': 'J. Smith'}))
    return out


LABELS = {'risk-eu': ('eu-west', {'jurisdiction': 'EU', 'entity': 'acme-eu'}),
          'cust-eu': ('eu-central', {'jurisdiction': 'EU', 'entity': 'acme-eu'}),
          'cust-na': ('us-east', {'jurisdiction': 'US', 'entity': 'acme-us'})}
TOOLS = 'customer_lookup,note_search,account_balance,us_kyc,desk_report'


def label(i):
    region, labels = LABELS[i.name]
    i.node.cfg.region, i.node.cfg.labels = region, dict(labels)
    i.node.refresh_record()


def test_residency_three_instances_end_to_end(tmp_path, monkeypatch, isolate):  # noqa: F811
    from tests.net.test_net_integration import ClientConnector
    from tests.net.test_net_three_instances import Instance, as_user, settle
    from sajha.net.integration import authz as az
    audits = []
    monkeypatch.setattr(az, 'linked_audit', lambda event, details, actor=None: audits.append((event, dict(details))))
    use(RULES)
    try:
        conn = ClientConnector()
        a = Instance(tmp_path, 'risk-eu', conn, [], founder=True)
        a.svc.start(run_agents=False)
        from sajha.net.integration import ServiceError
        try:
            a.svc.ca_init(NET)
        except ServiceError as ex:                      # a net of one may have created its CA at start
            assert 'already initialised' in str(ex)
        label(a)
        assert a.node.try_join()
        insts = [a]
        for name in ('cust-eu', 'cust-na'):
            i = Instance(tmp_path, name, conn, tools_for(name))
            i.svc.start(run_agents=False)
            i.svc.enroll(NET, 'https://risk-eu.test', a.svc.ca_token(NET, name)['token'], by='test')
            label(i)
            assert i.node.try_join()
            insts.append(i)
        e, n = insts[1], insts[2]
        for i in insts:
            i.user('alice', tools=TOOLS)
        kid, raw = a.key('alice')
        nkid, nraw = n.key('alice')
        settle(insts, 6)
        set_service(a.svc)
        # the extension advertises the feature; tools carry their data classes in the net metadata
        assert 'residency' in a.node.features
        row = next(r for r in a.svc.catalogs.router.rows() if r['qualified_name'] == 'acme-net__cust-na__account_balance')
        assert row['entry']['meta']['data_classes'] == {'results': ['confidential']}
        table = {r['qualified_name']: r for r in a.svc.catalogs.table()['rows']}
        assert table['acme-net__cust-na__account_balance']['data_classes'] == {'results': ['confidential']}
        assert table['acme-net__cust-eu__customer_lookup']['data_classes'] == {'arguments': ['eu-personal'],
                                                                             'results': ['eu-personal']}

        def call(name, args, who=(raw, kid), inst=a):
            set_service(inst.svc)
            try:
                return as_user('alice', who[0], who[1], lambda: inst.reg.get_tool(name).execute_with_tracking(args))
            finally:
                set_service(a.svc)

        # residency-aware shortlist: the data every customer_lookup call sends (eu-personal) may not go to
        # cust-na, so the plain name resolves to cust-eu only and cust-na's copy is not offered
        res = a.svc.catalogs.router.resolve('customer_lookup', {'user_id': 'alice', 'roles': ['user']})
        assert [c.host for c in res.candidates] == ['cust-eu']
        assert [(c.host, c.why_not) for c in res.skipped] == [('cust-na', 'residency rule')]
        from sajha.net.integration.catalogs import listed
        from sajha.observability.caller import Caller, reset, set_caller
        tok = set_caller(Caller('alice', '', ('user',), 'apikey', None, False))
        try:
            names = {t['name'] for t in listed(a.reg.get_all_tools())}
            from sajha.ai.intelligence import _residency_offered
            assert not _residency_offered('acme-net__cust-na__us_kyc') and _residency_offered('customer_lookup')
        finally:
            reset(tok)
        assert 'acme-net__cust-eu__customer_lookup' in names and 'customer_lookup' in names
        assert 'acme-net__cust-na__customer_lookup' not in names
        assert 'acme-net__cust-na__us_kyc' not in names and 'us_kyc' not in names          # nowhere to go

        # CALL-07 (arguments): by qualified name the home refuses before anything leaves; -32012, executed false
        before = len(n.reg.get_tool('customer_lookup').received)
        r = call('acme-net__cust-na__customer_lookup', {'customer_id': 'C-991'})
        ref = r['_meta'][EXTENSION_ID]['refusal']
        assert r['isError'] and ref['reason'] == 'residency_arguments' and ref['side'] == 'home'
        assert ref['executed'] is False and 'residency' in r['content'][0]['text']
        assert len(n.reg.get_tool('customer_lookup').received) == before
        assert any(ev == 'net.residency' and d['side'] == 'home' and d['flow'] == 'arguments'
                   and d['outcome'] == 'refused' and d['instance'] == 'cust-na'
                   and d['rule'].endswith('eu-personal-stays-in-eu') for ev, d in audits), audits    # refusals are audited
        # by plain name it goes to cust-eu (EU): allowed, audited
        r = call('customer_lookup', {'customer_id': 'C-991'})
        assert not r.get('isError') and r['structuredContent']['host'] == 'cust-eu', r
        assert r['_meta'][EXTENSION_ID]['data_classes'] == {'results': ['eu-personal']}
        assert any(ev == 'net.residency' and d['flow'] == 'arguments' and d['outcome'] == 'allowed'
                   and d['instance'] == 'cust-eu' for ev, d in audits)

        # an optional classified argument: refused for cust-na at the home, the plain name falls back to cust-eu
        a.svc.catalogs.settings.preferences = {'note_search': ['acme-net/cust-na', 'acme-net/cust-eu']}
        a.svc.catalogs._build_router()
        r = call('note_search', {'q': 'fx', 'email': 'ana@x.eu'})
        assert not r.get('isError') and r['content'][0]['text'].startswith('cust-eu:'), r
        assert [(x['host'], x['outcome']) for x in r['_meta'][EXTENSION_ID]['attempts']] == \
            [('cust-na', 'residency_arguments'), ('cust-eu', 'answered')]
        # without the classified field the preferred host gets the call
        r = call('note_search', {'q': 'fx'})
        assert r['content'][0]['text'].startswith('cust-na:'), r
        # field-level redaction of arguments before they leave: internal fields never reach another entity
        r = call('acme-net__cust-na__note_search', {'q': 'fx', 'desk': 'rates-desk-7'})
        assert n.reg.get_tool('note_search').received[-1] == {'q': 'fx', 'desk': '[REDACTED:internal]'}
        assert any(d.get('outcome') == 'redacted' and d.get('fields') == ['desk'] for ev, d in audits)
        r = call('acme-net__cust-eu__note_search', {'q': 'fx', 'desk': 'rates-desk-7'})
        assert e.reg.get_tool('note_search').received[-1]['desk'] == 'rates-desk-7'           # same entity

        # CALL-07 (results) and FB-01: confidential results may not leave acme-us; the host refuses after running
        r = call('acme-net__cust-na__account_balance', {'account': 'A1'})
        ref = r['_meta'][EXTENSION_ID]['refusal']
        assert r['isError'] and ref['reason'] == 'residency_result' and ref['side'] == 'host'
        assert ref['executed'] is True and '1843200' not in str(r)
        assert any(ev == 'net.residency' and d['side'] == 'host' and d['outcome'] == 'refused'
                   and d['data_classes'] == ['confidential'] for ev, d in audits)
        # a home in the same entity would receive it: cust-na calling itself is local, so check the rule instead
        # results redacted at the host: alice at cust-na (US) asks cust-eu for a customer; the name is masked
        r = call('acme-net__cust-eu__customer_lookup', {'customer_id': 'C-991'}, who=(nraw, nkid), inst=n)
        assert not r.get('isError'), r
        assert r['structuredContent']['name'] == '[REDACTED:eu-personal]' and 'Ana Silva' not in str(r)
        assert r['structuredContent']['segment'] == 'retail'
        assert r['_meta'][EXTENSION_ID]['redacted'] == ['name']

        # redaction as results arrive: the home's own rule keeps staff names out of what it receives
        r = call('acme-net__cust-eu__desk_report', {'desk': 'rates'})
        assert r['structuredContent'] == {'desk': 'rates', 'trader': '[REDACTED:staff]'}, r
        assert 'J. Smith' not in str(r)
        assert any(d.get('side') == 'home' and d.get('flow') == 'results' and d.get('outcome') == 'redacted'
                   for ev, d in audits)

        # the protocol error code of a residency refusal, seen by a caller of the endpoint
        from sajha.net.routing import CODES, RPC_RESIDENCY
        assert CODES['residency_arguments'] == CODES['residency_result'] == RPC_RESIDENCY == -32012
    finally:
        for i in locals().get('insts') or []:
            i.svc.stop()


def test_result_redaction_never_edits_inside_other_numbers():
    """A removed value that shares digits with other values (304 inside 304566, 304.5, 1304) is replaced only
    where it stands: the JSON text block is re-serialised from the redacted value, prose by whole token."""
    marks = {'age': ['eu-personal'], 'name': ['eu-personal']}
    value = {'name': 'Ana', 'age': 304, 'total_paid': 30456, 'rate': 304.5, 'count': 1304, 'note': 'Anaconda'}
    result = {'content': [{'type': 'text', 'text': json.dumps(value)},
                          {'type': 'text', 'text': '{"name": "Ana", "age": 304, "other": 304304}'},
                          {'type': 'text', 'text': 'Ana is 304; paid 30456 at 304.5 over 1304 days (Anaconda).'}],
              'structuredContent': value}
    out, touched = R.redact_result(result, marks, ['eu-personal'])
    assert touched == ['age', 'name']
    sc = out['structuredContent']
    assert sc['age'] == '[REDACTED:eu-personal]' and sc['total_paid'] == 30456 and sc['rate'] == 304.5
    assert json.loads(out['content'][0]['text']) == sc                    # the JSON of the result, re-serialised
    other = json.loads(out['content'][1]['text'])
    assert other == {'name': '[REDACTED:eu-personal]', 'age': '[REDACTED:eu-personal]', 'other': 304304}
    prose = out['content'][2]['text']
    assert prose == ('[REDACTED:eu-personal] is [REDACTED:eu-personal]; paid 30456 at 304.5 over 1304 days '
                     '(Anaconda).'), prose
