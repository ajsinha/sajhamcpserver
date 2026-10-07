"""The schema linter: each rule, the registry walk, JUnit output and the CLI's exit status."""

import xml.etree.ElementTree as ET

import pytest

from sajha.quality.cases import TestCase
from sajha.quality.lint import lint_registry, lint_tool, render_junit, summarise

GOOD = {
    'description': 'Look up the latest quote for a ticker symbol; returns price, currency and timestamp.',
    'inputSchema': {'type': 'object',
                    'properties': {'symbol': {'type': 'string', 'description': 'Ticker', 'examples': ['AAPL'],
                                              'pattern': '^[A-Z]+$'},
                                   'limit': {'type': 'integer', 'description': 'Rows', 'default': 5, 'minimum': 1}},
                    'required': ['symbol']},
    'outputSchema': {'type': 'object', 'properties': {'price': {'type': 'number'}}},
    'annotations': {'readOnlyHint': True},
}


def rules(findings, level=None):
    return sorted({(f.level, f.rule) for f in findings if level is None or f.level == level})


def test_a_good_tool_is_clean():
    assert lint_tool('quote_get', GOOD) == []


@pytest.mark.parametrize('name,cfg,expected', [
    ('bad name!', GOOD, ('error', 'name')),
    ('x' * 129, GOOD, ('error', 'name')),
    ('t', {**GOOD, 'description': ''}, ('error', 'description')),
    ('t', {**GOOD, 'description': 'Gets it.'}, ('warning', 'description')),
    ('t', {**GOOD, 'inputSchema': {'type': 'array'}}, ('error', 'input-schema')),
    ('t', {**GOOD, 'inputSchema': {'type': 'object', 'properties': {'a': {'type': 'strng'}}}}, ('error', 'input-schema')),
    ('t', {**GOOD, 'inputSchema': {'type': 'object', 'properties': {}, 'required': ['x']}}, ('error', 'input-schema')),
    ('t', {**GOOD, 'inputSchema': {'type': 'object', 'properties': {'a': {'type': 'string'}}}}, ('warning', 'property-description')),
    ('t', {**GOOD, 'inputSchema': {'type': 'object', 'properties': {'a': {'type': 'integer', 'description': 'd', 'examples': ['x']}}}}, ('error', 'examples')),
    ('t', {**GOOD, 'inputSchema': {'type': 'object', 'properties': {'a': {'type': 'integer', 'description': 'd', 'default': 'x'}}}}, ('warning', 'default')),
    ('t', {**GOOD, 'outputSchema': {'type': 'array'}}, ('error', 'output-schema')),
    ('t', {**GOOD, 'annotations': {'readOnlyHint': 'yes'}}, ('error', 'annotations')),
    ('t', {**GOOD, 'annotations': {'readOnlyHint': True, 'destructiveHint': True}}, ('error', 'annotations')),
    ('files_delete', {**GOOD, 'annotations': {}}, ('warning', 'annotations')),
    ('records_list', {**GOOD, 'annotations': {}}, ('info', 'annotations')),
])
def test_rules(name, cfg, expected):
    assert expected in rules(lint_tool(name, cfg))


def test_destructive_hint_satisfies_the_rule():
    assert not [f for f in lint_tool('files_delete', {**GOOD, 'annotations': {'destructiveHint': True}})
                if f.rule == 'annotations']


def test_test_case_arguments_must_match_the_schema():
    bad = TestCase(tool='t', name='c', arguments={'limit': 2})          # symbol missing
    expected_error = TestCase(tool='t', name='e', arguments={}, error=True)
    fs = lint_tool('t', GOOD, cases=[bad, expected_error])
    assert [f.rule for f in fs if f.level == 'error'] == ['test-arguments'] and "'c'" in fs[0].message


def test_registry_walk_and_junit():
    from tests.ai.conftest import ToolBox
    tb = ToolBox()
    findings = lint_registry(tb, 'calc_*')
    s = summarise(findings)
    assert s['error'] == 0 and s['warning'] >= 0
    names = sorted(tb.tools)
    root = ET.fromstring(render_junit(findings + lint_tool('Bad Name', GOOD), names + ['Bad Name']))
    assert root.get('tests') == str(len(names) + 1) and root.get('failures') == '1'


def test_cli_exit_status(tmp_path):
    from sajha.quality.__main__ import main
    assert main(['lint', '--tool', 'calc_*', '--junit', str(tmp_path / 'l.xml')]) == 0
    assert (tmp_path / 'l.xml').is_file()
