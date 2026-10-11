# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The Tool Reference Guide tables are generated from the tool configs (python -m sajha.tools guides):
every marked region is current, so a changed tool config fails here until the guide is regenerated.
Design: docs/architecture/Tool Quality.md §12.5 (sajha/tools/guides.py)."""

import io
import json
from pathlib import Path

import pytest


def test_every_generated_region_is_current():
    """Run ``python -m sajha.tools guides`` when this fails: a tool config changed since the guides were
    regenerated (regions whose tools need a module that is not installed are reported, not judged)."""
    from sajha.tools.guides import run
    results = run(check=True)
    assert results, 'no generated:tools regions in docs/tools'
    bad = [f'{r.path.name} [{r.folder}]: {r.status} {r.detail}' for r in results if r.status in ('stale', 'error')]
    assert not bad, 'stale guide tables; run: python -m sajha.tools guides\n' + '\n'.join(bad)


def test_cli_check_exit_codes(tmp_path, monkeypatch):
    import sajha.tools.guides as g
    guide = tmp_path / 'X Tool Reference Guide.md'
    guide.write_text('# X\n\nProse stays.\n\n<!-- generated:tools folder=calc include=calc_percentage_change -->\n'
                     'old table\n<!-- /generated:tools -->\n\nMore prose.\n', encoding='utf-8')
    out = io.StringIO()
    monkeypatch.setattr(g, 'GUIDES_DIR', tmp_path)
    assert g.main(check=True, out=out) == 1 and 'stale' in out.getvalue()
    assert 'old table' in guide.read_text()                       # --check writes nothing
    from sajha.tools.__main__ import main as cli
    assert cli(['guides']) == 0
    text = guide.read_text()
    assert text.startswith('# X\n\nProse stays.\n') and text.endswith('\n\nMore prose.\n')
    assert '`calc_percentage_change`' in text and 'old table' not in text
    assert cli(['guides', '--check']) == 0


def test_rendering_columns_defaults_keys_and_selection(tmp_path, monkeypatch):
    import sajha.core.storage as storage
    import sajha.tools.guides as g
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(tmp_path)))
    monkeypatch.setattr(g, '_prefix', lambda: 'config/tools')
    base = tmp_path / 'config' / 'tools' / 'zeta'
    base.mkdir(parents=True)
    common = {'implementation': 'x.Y', 'metadata': {'category': 'Cat B'}}
    (base / 'zeta_one.json').write_text(json.dumps(dict(common, name='zeta_one', title='One',
        description='Does one thing (e.g. the first). Then more | pipes.', api_key='${fred.api.key}',
        annotations={'readOnlyHint': True, 'openWorldHint': True},
        inputSchema={'type': 'object', 'required': ['q'],
                     'properties': {'q': {'type': 'string'}, 'limit': {'type': 'integer', 'default': 30}}})))
    (base / 'zeta_two.json').write_text(json.dumps(dict(common, name='zeta_two', enabled=False,
        metadata={'category': 'Cat A'}, description='Two.',
        inputSchema={'type': 'object', 'properties': {'mode': {'type': 'string', 'default': 'fast'}}})))
    (base / 'domain.txt').write_text('not a config')
    body = g.render(g.parse_attrs('folder=zeta group=category'))
    assert body.index('### Cat A') < body.index('### Cat B')
    assert '| Tool | Title | Description | Required | Optional (schema default) | Annotations | Key |' in body
    assert ('| `zeta_one` | One | Does one thing (e.g. the first). | `q` | `limit` (`30`) | read-only, open-world '
            '| `FRED_API_KEY` (config `fred.api.key`) |') in body
    assert '| `zeta_two` | — | Two. | — | `mode` (`fast`) | disabled | — |' in body
    only = g.render(g.parse_attrs('folder=zeta exclude=zeta_*,!zeta_two'))
    assert 'zeta_two' in only and 'zeta_one' not in only
    with pytest.raises(ValueError):
        g.render(g.parse_attrs('folder=zeta include=nothing_*'))
    with pytest.raises(ValueError):
        g.parse_attrs('group=category')


def test_first_sentence_keeps_abbreviations():
    from sajha.tools.guides import first_sentence
    assert first_sentence("From FRED, the St. Louis Fed's database. More.") == "From FRED, the St. Louis Fed's database."
    assert first_sentence('Line one\nLine two.') == 'Line one'
    assert first_sentence('x ' * 400).endswith('…')


def test_market_data_guides_that_claim_generation_are_generated():
    root = Path(__file__).resolve().parents[1] / 'docs' / 'tools'
    for p in root.rglob('*.md'):
        text = p.read_text(encoding='utf-8')
        if 'tables below are generated' in text:
            assert '<!-- generated:tools ' in text, f'{p.name} claims generated tables but has no marked region'
