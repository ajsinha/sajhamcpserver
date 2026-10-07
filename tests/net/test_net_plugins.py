"""SAJHA Net plug-in points (design §5.3, §5.4): registry, selection and every contract suite."""

import ast
import os
import types

import pytest

from sajha.net import contract, plugins

CASES = [(kind, name) for kind in sorted(plugins.INTERFACES) for name in sorted(plugins.registered(kind))]


def test_every_kind_has_a_shipped_implementation():
    assert {k for k, _ in CASES} == set(plugins.INTERFACES)


@pytest.mark.parametrize('kind, name', CASES)
def test_contract(kind, name):
    contract.check(kind, lambda: plugins.create(kind, name))


def test_selection_by_class_path_and_errors():
    cls = plugins.plugin_class('routing', 'sajha.net.plugins:LocalFirst')
    assert cls is plugins.LocalFirst
    with pytest.raises(ValueError):
        plugins.plugin_class('routing', 'nope')
    with pytest.raises(ValueError):
        plugins.plugin_class('routing', 'sajha.net.plugins:StaticMembership')
    with pytest.raises(ValueError):
        plugins.plugin_class('nope', 'x')


def test_third_party_registration_and_entry_points(monkeypatch):
    class Mine(plugins.RoutingStrategy):
        name = 'alphabetical'

        def order(self, tool, hosts, preferred=None):
            return sorted(hosts, key=lambda h: h.instance)
    plugins.register('routing')(Mine)
    try:
        contract.check('routing', lambda: plugins.create('routing', 'alphabetical'))
    except AssertionError as e:
        assert 'preferred' in str(e)          # this strategy ignores preferences: the contract says so
    with pytest.raises(TypeError):
        plugins.register('routing')(object)

    class EP:
        name = 'membership.from-ep'

        def load(self):
            class FromEP(plugins.MembershipProvider):
                gossip = True
            return FromEP
    import importlib.metadata as md
    monkeypatch.setattr(md, 'entry_points', lambda group=None: [EP()] if group == plugins.ENTRY_POINT_GROUP else [])
    monkeypatch.setattr(plugins, '_entry_points_loaded', False)
    assert 'from-ep' in plugins.registered('membership')
    contract.check('membership', lambda: plugins.create('membership', 'from-ep'))


CORE = ['__init__', 'names', 'jcs', 'sfv', 'crypto', 'httpsig', 'errors', 'schemas', 'models', 'plugins', 'trust',
        'membership', 'ca', 'node', 'contract']


@pytest.mark.parametrize('module', CORE)
def test_the_core_imports_nothing_from_the_rest_of_sajha(module):
    """Design §5.4: the protocol core can be built into the agent and the library on its own."""
    path = os.path.join(os.path.dirname(plugins.__file__), f'{module}.py')
    tree = ast.parse(open(path, encoding='utf-8').read())
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name.startswith('sajha') and not a.name.startswith('sajha.net')]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == 'sajha' or (node.module.startswith('sajha.') and not node.module.startswith('sajha.net')):
                bad.append(node.module)
            if node.module.startswith('sajha.net.integration'):
                bad.append(node.module)
    assert not bad, f'sajha/net/{module}.py imports {bad}'
