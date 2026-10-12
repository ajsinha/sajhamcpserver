# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""inputSchema defaults applied before a call (sajha/tools/schema_defaults.py; Tool Quality §12.1):
the helper's rules, the one choke point every transport shares, the composite step executor, the
quality harness, the audit record, the off switch and the proxy opt-out, and the lint rules."""

import pytest

from sajha.tools.base_mcp_tool import BaseMCPTool, ToolArgumentError
from sajha.tools.schema_defaults import apply_schema_defaults, build_plan

SCHEMA = {
    'type': 'object',
    'properties': {
        'symbol': {'type': 'string', 'default': 'IBM'},           # required: never filled
        'limit': {'type': 'integer', 'default': 30},
        'tags': {'type': 'array', 'items': {'type': 'string'}, 'default': ['a']},
        'opts': {'type': 'object', 'properties': {'depth': {'type': 'integer', 'default': 2},
                                                  'mode': {'type': 'string'}}},
        'cfg': {'type': 'object', 'default': {'x': 1}, 'properties': {'x': {'type': 'integer'}}},
        'pick': {'oneOf': [{'type': 'string', 'default': 'b'}, {'type': 'integer'}]},
        'ref': {'$ref': '#/$defs/r'},
        'bad': {'type': 'integer', 'default': 'not-a-number'},
        'nothing': {'type': 'string'},
    },
    'required': ['symbol'],
    '$defs': {'r': {'type': 'string', 'default': 'z'}},
}


def test_fills_only_absent_keys_and_never_required():
    out, filled = apply_schema_defaults(SCHEMA, {'symbol': 'AAPL'})
    assert out['limit'] == 30 and out['tags'] == ['a'] and out['cfg'] == {'x': 1}
    assert out['symbol'] == 'AAPL' and sorted(filled) == ['cfg', 'limit', 'tags']
    out, filled = apply_schema_defaults(SCHEMA, {})
    assert 'symbol' not in out                                   # required: validation reports it


def test_present_keys_win_even_when_null():
    out, filled = apply_schema_defaults(SCHEMA, {'symbol': 'A', 'limit': None})
    assert out['limit'] is None and 'limit' not in filled


def test_nested_objects_only_when_supplied():
    out, _ = apply_schema_defaults(SCHEMA, {'symbol': 'A'})
    assert 'opts' not in out                                     # never created just to hold defaults
    out, filled = apply_schema_defaults(SCHEMA, {'symbol': 'A', 'opts': {'mode': 'm'}})
    assert out['opts'] == {'mode': 'm', 'depth': 2} and 'opts.depth' in filled


def test_no_defaults_through_branches_refs_or_items():
    out, _ = apply_schema_defaults(SCHEMA, {'symbol': 'A'})
    assert 'pick' not in out and 'ref' not in out


def test_a_default_that_fails_its_own_schema_is_not_applied():
    out, _ = apply_schema_defaults(SCHEMA, {'symbol': 'A'})
    assert 'bad' not in out


def test_copies_never_share_and_the_caller_dict_is_untouched():
    args = {'symbol': 'A', 'opts': {'mode': 'm'}}
    out, _ = apply_schema_defaults(SCHEMA, args)
    out['tags'].append('mutated')
    out['opts']['mode'] = 'changed'
    assert args == {'symbol': 'A', 'opts': {'mode': 'm'}}
    again, _ = apply_schema_defaults(SCHEMA, {'symbol': 'A'})
    assert again['tags'] == ['a'] and SCHEMA['properties']['tags']['default'] == ['a']


def test_nothing_to_fill_returns_the_same_object():
    args = {'symbol': 'A', 'limit': 1, 'tags': [], 'cfg': {}}
    out, filled = apply_schema_defaults(SCHEMA, args)
    assert out is args and filled == []
    assert build_plan({'type': 'object', 'properties': {'a': {'type': 'string'}}}) is None
    assert apply_schema_defaults(SCHEMA, ['not', 'a', 'dict']) == (['not', 'a', 'dict'], [])


# ── the call path ───────────────────────────────────────────────────────────

class Echo(BaseMCPTool):
    def __init__(self, schema=None, **extra):
        super().__init__({'name': 'echo_defaults', 'description': 'Echo the arguments it ran with.',
                          'inputSchema': schema or {'type': 'object', 'properties': {
                              'q': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'default': 30}},
                              'required': ['q']}, **extra})
        self.seen = []

    def get_input_schema(self):
        return self._input_schema

    def get_output_schema(self):
        return {}

    def execute(self, arguments):
        self.seen.append(dict(arguments))
        return {'args': dict(arguments)}


class PythonSchema(Echo):
    """A tool whose schema comes from code (get_input_schema), not from its config."""

    def __init__(self):
        BaseMCPTool.__init__(self, {'name': 'py_schema_tool', 'description': 'A tool with a schema in code.'})
        self.seen = []

    def get_input_schema(self):
        return {'type': 'object', 'properties': {'n': {'type': 'integer', 'default': 7}}}


def test_execute_with_tracking_applies_defaults_once_for_every_transport():
    t = Echo()
    assert t.execute_with_tracking({'q': 'x'}) == {'args': {'q': 'x', 'limit': 30}}
    assert t.execute_with_tracking({'q': 'x', 'limit': 5})['args']['limit'] == 5


def test_schemas_defined_in_python_are_included():
    t = PythonSchema()
    assert t.execute_with_tracking({}) == {'args': {'n': 7}}


def test_a_required_property_is_still_reported_missing():
    with pytest.raises(ToolArgumentError, match='Missing required parameter: q'):
        Echo().execute_with_tracking({})


def test_the_removed_switch_no_longer_turns_it_off(monkeypatch):
    """tools.apply_schema_defaults was removed in 8.14.0: schema defaults always apply."""
    monkeypatch.setenv('SAJHA_TOOLS_APPLY_SCHEMA_DEFAULTS', 'false')
    assert Echo().execute_with_tracking({'q': 'x'}) == {'args': {'q': 'x', 'limit': 30}}
    from sajha.tools import schema_defaults
    assert not hasattr(schema_defaults, 'enabled')


def test_proxies_of_other_servers_opt_out():
    from sajha.federation.tool import FederatedTool
    from sajha.net.integration.catalogs import NetProxyTool
    assert FederatedTool.apply_schema_defaults is False and NetProxyTool.apply_schema_defaults is False
    t = Echo()
    t.apply_schema_defaults = False
    assert t.execute_with_tracking({'q': 'x'}) == {'args': {'q': 'x'}}


def test_the_audit_record_names_the_filled_keys(monkeypatch):
    seen = {}

    def fake_record(tool, arguments, outcome, elapsed, error='', defaults_applied=None):
        seen.update(arguments=arguments, defaults_applied=defaults_applied, outcome=outcome)
    monkeypatch.setattr('sajha.audit.tool_calls.record_call', fake_record)
    Echo().execute_with_tracking({'q': 'x'})
    assert seen == {'arguments': {'q': 'x', 'limit': 30}, 'defaults_applied': ['limit'], 'outcome': 'ok'}


def test_the_audit_details_carry_defaults_applied(monkeypatch):
    from sajha.audit import tool_calls as TC
    captured = {}
    monkeypatch.setattr('sajha.audit.record', lambda *a, **kw: captured.update(kw))
    monkeypatch.setattr(TC, 'settings', lambda: TC.Settings())
    TC.record_call(Echo(), {'q': 'x', 'limit': 30}, 'ok', 0.01, defaults_applied=['limit'])
    assert captured['details']['defaults_applied'] == ['limit']


def test_the_result_cache_keys_on_the_filled_arguments(monkeypatch):
    from sajha.core import cache as C
    t = Echo(cache_ttl=60)
    monkeypatch.setattr(C, 'get_tool_ttl', lambda name, cfg=None: 60)
    import uuid
    q = f'cache-key-{uuid.uuid4().hex}'
    t.execute_with_tracking({'q': q})
    t.execute_with_tracking({'q': q, 'limit': 30})
    assert len(t.seen) == 1                                      # {} and an explicit default share an entry


def test_composite_steps_apply_defaults():
    from sajha.core.composition import execute_step
    t = Echo()
    r = execute_step(t, {'q': 'x'})
    assert r.value == {'args': {'q': 'x', 'limit': 30}}


def test_the_quality_harness_applies_defaults():
    from sajha.quality.cases import TestCase
    from sajha.quality.runner import run_case
    t = Echo()
    r = run_case(t, TestCase(tool='echo_defaults', name='d', arguments={'q': 'x'},
                             expect=[{'path': '$.args.limit', 'equals': 30}]), mode='live')
    assert r.status == 'pass', r.message


# ── lint ────────────────────────────────────────────────────────────────────

def test_lint_reports_required_and_unapplied_defaults():
    from sajha.quality.lint import lint_tool
    cfg = {'description': 'A tool to lint for its defaults; returns nothing at all, only for the test.',
           'inputSchema': SCHEMA}
    found = {(f.level, f.rule) for f in lint_tool('t', cfg)}
    assert ('warning', 'required-default') in found and ('info', 'unapplied-default') in found
