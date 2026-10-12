# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Publisher signatures for plugins (sajha/core/plugin_signing.py; Roadmap L12): signing,
verification, every way a package fails it, the trusted-key configuration, the load-time gate in
PluginManager with plugins.allow_unsigned, and the publisher command line."""
import json
import os
from types import SimpleNamespace

import pytest

pytest.importorskip('cryptography', reason='publisher signatures need the cryptography package')

from sajha.core import plugin_signing as S  # noqa: E402


def make_plugin(root, name='demo', version='1.0.0', tool='echo'):
    (root / 'tools').mkdir(parents=True, exist_ok=True)
    (root / 'plugin.json').write_text(json.dumps({'name': name, 'version': version, 'author': 'Desk',
                                                  'min_sajha_version': '1.0.0'}))
    (root / 'tools' / f'{tool}.json').write_text(json.dumps({
        'name': f'zz_{name.replace("-", "_")}_{tool}', 'description': 'Echo.',
        'implementation': 'sajha.tools.impl.does_not_matter.Echo', 'enabled': True}))
    return root


@pytest.fixture
def keys(tmp_path):
    priv, pub = S.generate_keypair()
    other_priv, other_pub = S.generate_keypair()
    return SimpleNamespace(priv=priv, pub=pub, other_priv=other_priv, other_pub=other_pub,
                           trusted=S.trusted_keys([f'acme={pub}'], keys_dir=''))


@pytest.fixture(autouse=True)
def _quiet_notices(monkeypatch):
    raised, cleared = [], []
    from sajha import notices
    monkeypatch.setattr(notices, 'raise_notice', lambda nid, **kw: raised.append((nid, kw)))
    monkeypatch.setattr(notices, 'clear_notice', lambda nid, **kw: cleared.append(nid))
    return SimpleNamespace(raised=raised, cleared=cleared)


def test_sign_and_verify(tmp_path, keys):
    p = make_plugin(tmp_path / 'demo')
    sig = S.sign(p, keys.priv, 'acme')
    assert (p / 'plugin.sig').is_file()
    assert set(sig['files']) == {'plugin.json', 'tools/echo.json'}
    assert sig['key_id'] == S.key_id(S.load_public_key(keys.pub))
    v = S.verify(p, keys.trusted)
    assert v.status == 'trusted' and v.publisher == 'acme' and len(v.package_hash) == 64
    # bytecode written by loading is not part of the package
    (p / 'tools' / '__pycache__').mkdir()
    (p / 'tools' / '__pycache__' / 'x.cpython-314.pyc').write_bytes(b'\0')
    assert S.verify(p, keys.trusted).status == 'trusted'


def test_raw_base64_key_is_accepted(tmp_path, keys):
    import base64
    raw = S._raw_public(S.load_public_key(keys.pub))
    trusted = S.trusted_keys([f'acme={base64.b64encode(raw).decode()}'], keys_dir='')
    p = make_plugin(tmp_path / 'demo')
    S.sign(p, keys.priv, 'acme')
    assert S.verify(p, trusted).status == 'trusted'


def test_unsigned(tmp_path, keys):
    assert S.verify(make_plugin(tmp_path / 'demo'), keys.trusted).status == 'unsigned'


@pytest.mark.parametrize('tamper', ['change', 'add', 'remove', 'manifest_version', 'signature', 'publisher_claim'])
def test_tampering_is_invalid(tmp_path, keys, tamper):
    p = make_plugin(tmp_path / 'demo')
    S.sign(p, keys.priv, 'acme')
    if tamper == 'change':
        (p / 'tools' / 'echo.json').write_text('{"name": "evil"}')
    elif tamper == 'add':
        (p / 'tools' / 'backdoor.py').write_text('import os')
    elif tamper == 'remove':
        (p / 'tools' / 'echo.json').unlink()
    elif tamper == 'manifest_version':
        m = json.loads((p / 'plugin.json').read_text())
        m['version'] = '9.9.9'
        (p / 'plugin.json').write_text(json.dumps(m))
        sig = json.loads((p / 'plugin.sig').read_text())       # re-digest so only the version differs
        sig['files']['plugin.json'] = S.file_digests(p)['plugin.json']
        (p / 'plugin.sig').write_text(json.dumps(sig))
    elif tamper == 'signature':
        sig = json.loads((p / 'plugin.sig').read_text())
        sig['files']['tools/echo.json'] = 'sha256:' + '0' * 64
        (p / 'tools' / 'echo.json').write_text('{"name": "evil"}')
        sig['files']['tools/echo.json'] = S.file_digests(p)['tools/echo.json']   # digests match, signature does not
        (p / 'plugin.sig').write_text(json.dumps(sig))
    elif tamper == 'publisher_claim':
        sig = json.loads((p / 'plugin.sig').read_text())
        sig['publisher'] = 'mallory'
        (p / 'plugin.sig').write_text(json.dumps(sig))
    v = S.verify(p, keys.trusted)
    assert v.status == 'invalid', v


def test_untrusted_key(tmp_path, keys):
    p = make_plugin(tmp_path / 'demo')
    S.sign(p, keys.other_priv, 'acme')
    v = S.verify(p, keys.trusted)
    assert v.status == 'untrusted' and 'not a configured trusted key' in v.detail


def test_malformed_signature_file(tmp_path, keys):
    p = make_plugin(tmp_path / 'demo')
    (p / 'plugin.sig').write_text('not json')
    assert S.verify(p, keys.trusted).status == 'invalid'
    (p / 'plugin.sig').write_text('{"format": "sajha-plugin-signature/1"}')
    assert S.verify(p, keys.trusted).status == 'invalid'


def test_symlink_in_package_is_invalid(tmp_path, keys):
    p = make_plugin(tmp_path / 'demo')
    S.sign(p, keys.priv, 'acme')
    os.symlink('/etc/hostname', p / 'tools' / 'link.txt')
    assert S.verify(p, keys.trusted).status == 'invalid'


def test_trusted_keys_from_config_and_folder(tmp_path, keys, monkeypatch):
    d = tmp_path / 'keys'
    d.mkdir()
    (d / 'globex.pub').write_text(keys.other_pub)
    (d / 'broken.pub').write_text('nope')
    monkeypatch.setenv('SAJHA_PLUGINS_TRUSTED_KEYS', json.dumps([f'acme={keys.pub}', 'no-equals-sign']))
    monkeypatch.setenv('SAJHA_PLUGINS_TRUSTED_KEYS_DIR', str(d))
    got = {k.publisher for k in S.trusted_keys().values()}
    assert got == {'acme', 'globex'}


def test_gate_and_allow_unsigned(tmp_path, keys, monkeypatch, _quiet_notices):
    p = make_plugin(tmp_path / 'demo')
    monkeypatch.setattr(S, 'trusted_keys', lambda *a, **k: keys.trusted)
    monkeypatch.setenv('SAJHA_PLUGINS_ALLOW_UNSIGNED', 'true')
    errors, v = S.gate(p, 'demo')
    assert errors == [] and v.status == 'unsigned'
    assert ('plugins.unsigned:demo', 'warning') in [(n, kw['severity']) for n, kw in _quiet_notices.raised]
    monkeypatch.setenv('SAJHA_PLUGINS_ALLOW_UNSIGNED', 'false')
    errors, v = S.gate(p, 'demo')
    assert errors and 'allow_unsigned' in errors[0]
    S.sign(p, keys.priv, 'acme')
    errors, v = S.gate(p, 'demo')
    assert errors == [] and v.trusted
    assert 'plugins.unsigned:demo' in _quiet_notices.cleared
    (p / 'tools' / 'echo.json').write_text('{}')
    monkeypatch.setenv('SAJHA_PLUGINS_ALLOW_UNSIGNED', 'true')
    errors, v = S.gate(p, 'demo')                 # tampering is refused whatever allow_unsigned says
    assert errors and 'invalid' in errors[0]


class _Registry:
    def __init__(self):
        self.tools = {}

    def register_tool_from_dict(self, config, source=''):
        self.tools[config['name']] = config

    def register_tool(self, tool):
        self.tools[tool.name] = tool

    def unregister_tool(self, name):
        self.tools.pop(name, None)


def test_plugin_manager_refuses_by_signature(tmp_path, keys, monkeypatch):
    from sajha.core.plugins import PluginManager
    if 'plugin_signing' not in open('sajha/core/plugins.py', encoding='utf-8').read():
        pytest.skip('PluginManager does not check signatures yet (pending edit)')
    root = tmp_path / 'plugins'
    make_plugin(root / 'demo')
    monkeypatch.setattr(S, 'trusted_keys', lambda *a, **k: keys.trusted)
    pm = PluginManager(_Registry())
    pm.PLUGINS_DIR = str(root)
    pm.discover()
    monkeypatch.setenv('SAJHA_PLUGINS_ALLOW_UNSIGNED', 'false')
    st = pm.load_plugin('demo')
    assert not st.enabled and 'allow_unsigned' in st.error
    monkeypatch.setenv('SAJHA_PLUGINS_ALLOW_UNSIGNED', 'true')
    st = pm.load_plugin('demo')
    assert st.enabled and st.tools_registered == 1
    pm.unload_plugin('demo')
    S.sign(root / 'demo', keys.priv, 'acme')
    (root / 'demo' / 'tools' / 'extra.json').write_text(json.dumps({'name': 'zz_extra'}))
    st = pm.load_plugin('demo')
    assert not st.enabled and 'signature invalid' in st.error


def test_command_line(tmp_path, capsys):
    out = tmp_path / 'keys'
    assert S.main(['keygen', '--publisher', 'acme', '--out', str(out)]) == 0
    assert oct(os.stat(out / 'acme.key').st_mode & 0o777) == '0o600'
    p = make_plugin(tmp_path / 'demo')
    assert S.main(['sign', str(p), '--key', str(out / 'acme.key'), '--publisher', 'acme']) == 0
    assert S.main(['verify', str(p), '--trusted', str(out / 'acme.pub')]) == 0
    assert 'trusted' in capsys.readouterr().out
    zipped = tmp_path / 'dist'
    assert S.main(['pack', str(p), '--out', str(zipped)]) == 0
    import zipfile
    names = zipfile.ZipFile(zipped / 'demo-1.0.0.zip').namelist()
    assert set(names) == {'plugin.json', 'tools/echo.json', 'plugin.sig'}
    (p / 'tools' / 'echo.json').write_text('{}')
    assert S.main(['verify', str(p), '--trusted', str(out / 'acme.pub')]) == 1
