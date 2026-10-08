# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Third-party SAJHA Net plug-ins (design §5.3): modules named in ``sajhanet.plugins.modules`` and the
entry-point group ``sajha.net.plugins`` are loaded at start, contract-checked, and failures are reported
as System Notices; the example plug-in ``region_first`` (sajha/examples/sajhanet/region_first.py)."""

import sys
import textwrap

import pytest

from sajha.net import plugins
from sajha.net.plugins import HostOption


@pytest.fixture
def clean():
    before = {k: dict(v) for k, v in plugins._REGISTRY.items()}
    errors = list(plugins.LOAD_ERRORS)
    mods = set(sys.modules)
    yield
    for k in plugins._REGISTRY:
        plugins._REGISTRY[k] = before[k]
    plugins.LOAD_ERRORS[:] = errors
    for m in set(sys.modules) - mods:
        if m.startswith(('sajha.examples.sajhanet', 'thirdparty_')):
            sys.modules.pop(m, None)
    from sajha import notices
    for n in notices.list_notices(state='all'):
        if str(n.get('id', '')).startswith('sajhanet.plugin'):
            notices.clear_notice(n['id'])


def test_the_example_plugin_loads_and_routes_by_region(clean):
    sys.modules.pop('sajha.examples.sajhanet.region_first', None)
    rows = plugins.load_plugins(['sajha.examples.sajhanet.region_first'])
    assert {'source': 'module sajha.examples.sajhanet.region_first', 'kind': 'routing', 'name': 'region_first',
            'error': ''} in rows
    strat = plugins.create('routing', 'region_first')
    strat.region = 'eu-west'
    hosts = [HostOption('b-us', attrs={'region': 'us-east'}, latency_ms=1),
             HostOption('c-eu', attrs={'region': 'eu-west'}, latency_ms=9),
             HostOption('a-eu', attrs={'region': 'eu-west'})]
    assert [h.instance for h in strat.order('t', hosts)] == ['c-eu', 'a-eu', 'b-us']
    assert [h.instance for h in strat.order('t', hosts, ['b-us'])][0] == 'b-us'


def test_failures_are_reported_and_a_failing_plugin_is_not_selectable(clean, tmp_path, monkeypatch):
    (tmp_path / 'thirdparty_bad.py').write_text(textwrap.dedent('''
        from sajha.net import plugins

        @plugins.register('routing')
        class IgnoresPreferences(plugins.RoutingStrategy):
            name = 'ignores_preferences'

            def order(self, tool, hosts, preferred=None):
                return sorted(hosts, key=lambda h: h.instance, reverse=True)
    '''))
    (tmp_path / 'thirdparty_empty.py').write_text('X = 1\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    rows = plugins.load_plugins(['thirdparty_bad', 'thirdparty_empty', 'thirdparty_missing'])
    by = {r['name']: r['error'] for r in rows}
    assert 'contract check' in by['ignores_preferences']
    assert 'registers no SAJHA Net plug-in' in by['thirdparty_empty']
    assert 'cannot be imported' in by['thirdparty_missing']
    assert 'ignores_preferences' not in plugins.registered('routing')
    with pytest.raises(ValueError):
        plugins.create('routing', 'ignores_preferences')
    assert any(e['name'] == 'thirdparty_missing' for e in plugins.LOAD_ERRORS)


def test_the_service_raises_a_notice_per_failure(clean, tmp_path):
    from sajha import notices
    from sajha.core.state.memory import MemoryStateStore
    from sajha.net.integration import SajhaNetService
    from sajha.net.integration.config import Shared
    svc = SajhaNetService(Shared(enabled=True, data_dir=str(tmp_path), plugin_modules=['thirdparty_nowhere']), [], {},
                          store=MemoryStateStore())
    svc.start(run_agents=False)
    ids = {n['id']: n for n in notices.list_notices(state='all')}
    nid = 'sajhanet.plugin:module thirdparty_nowhere:thirdparty_nowhere'
    assert nid in ids and ids[nid]['severity'] == 'error'
    assert svc.status()['plugins'][-1]['name'] == 'thirdparty_nowhere'
    svc.stop()


def test_modules_from_configuration(monkeypatch):
    from sajha.net.integration import config
    monkeypatch.setenv('SAJHA_SAJHANET_PLUGINS_MODULES', 'a.b, c.d')
    assert config.shared().plugin_modules == ['a.b', 'c.d']
