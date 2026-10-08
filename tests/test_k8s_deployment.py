# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Kubernetes deployment artefacts: Helm chart, Kustomize manifests, Dockerfile.

Static checks that need no cluster. `helm lint` / `helm template` and a real install are
described in docs/getting-started/Kubernetes Deployment.md; render.py --check runs here
when the helm binary is on PATH.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / 'charts' / 'sajha'
K8S = ROOT / 'deployment' / 'k8s'


def _app_version() -> str:
    return str(yaml.safe_load((ROOT / 'config' / 'application.yml').read_text())['app']['version'])


def test_chart_app_version_matches_app_version():
    chart = yaml.safe_load((CHART / 'Chart.yaml').read_text())
    assert chart['appVersion'] == _app_version(), \
        'charts/sajha/Chart.yaml appVersion must equal app.version (then run deployment/k8s/render.py)'


@pytest.mark.parametrize('values', [CHART / 'values.yaml', K8S / 'values-dev.yaml', K8S / 'values-prod.yaml'],
                         ids=lambda p: p.name)
def test_values_files_match_schema(values):
    jsonschema = pytest.importorskip('jsonschema')
    schema = json.loads((CHART / 'values.schema.json').read_text())
    jsonschema.validate(yaml.safe_load(values.read_text()), schema)


def test_schema_rejects_unknown_top_level_key():
    jsonschema = pytest.importorskip('jsonschema')
    schema = json.loads((CHART / 'values.schema.json').read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'replicas': 3}, schema)


def test_rendered_manifests_use_the_app_version_image():
    version = _app_version()
    for path in (K8S / 'overlays').glob('*/sajha-*.yaml'):
        images = [c['image'] for d in yaml.safe_load_all(path.read_text()) if d and d['kind'] == 'Deployment'
                  for c in d['spec']['template']['spec']['containers']]
        assert images and all(i.endswith(':' + version) for i in images if 'sajhamcpserver' in i), (path, images)


@pytest.mark.skipif(not shutil.which('helm'), reason='helm not installed')
def test_kustomize_manifests_are_rendered_from_the_chart():
    r = subprocess.run([sys.executable, str(K8S / 'render.py'), '--check'], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def _seed_module():
    spec = importlib.util.spec_from_file_location('sajha_seed', CHART / 'files' / 'seed.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_merge_merges_maps_and_replaces_lists():
    seed = _seed_module()
    base = {'mcp': {'auth': {'mode': 'off', 'scopes': 'a'}}, 'ai': {'providers': [1, 2]}}
    out = seed.merge(base, {'mcp': {'auth': {'mode': 'required'}}, 'ai': {'providers': [3]}})
    assert out == {'mcp': {'auth': {'mode': 'required', 'scopes': 'a'}}, 'ai': {'providers': [3]}}


def test_seed_copy_keeps_volume_edits_unless_overwrite(tmp_path, monkeypatch):
    seed = _seed_module()
    src, dst = tmp_path / 'src', tmp_path / 'dst'
    (src / 'tools').mkdir(parents=True)
    (src / 'tools' / 'a.json').write_text('image')
    (src / '__pycache__').mkdir()
    (src / '__pycache__' / 'x.pyc').write_text('x')
    (dst / 'tools').mkdir(parents=True)
    (dst / 'tools' / 'a.json').write_text('edited')
    assert seed.copy_tree(src, dst) == 0
    assert (dst / 'tools' / 'a.json').read_text() == 'edited'
    assert not (dst / '__pycache__').exists()
    monkeypatch.setattr(seed, 'MODE', 'overwrite')
    assert seed.copy_tree(src, dst) == 1
    assert (dst / 'tools' / 'a.json').read_text() == 'image'


def test_dockerfile_runs_unprivileged_with_a_healthcheck():
    text = (ROOT / 'Dockerfile').read_text()
    assert 'USER 10001:10001' in text
    assert 'HEALTHCHECK' in text and '/health' in text
    assert 'EXPOSE 3002' in text
    ignore = (ROOT / '.dockerignore').read_text().splitlines()
    for secret_path in ('.env', 'data/'):
        assert secret_path in ignore
