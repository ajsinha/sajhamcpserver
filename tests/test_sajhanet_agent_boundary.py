# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The SAJHA Net agent boundary (SAJHA Net design §5.4, phase 8).

The SAJHA Net agent (``sajhanet_agent/``), the reference library (``sajha/net/library.py``) and the
conformance runner (``sajha/net/conformance/``) are built from the protocol core alone: they never
import the SAJHA server (its app, web framework, database, configuration, tools, auth, federation or
SAJHA Net's own integration). Checked twice: by the import statements in their source, and by what a
fresh interpreter has loaded after importing every agent module.
"""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / 'sajhanet_agent'
FILES = sorted(p for p in AGENT.rglob('*.py') if 'tests' not in p.parts) + \
    [ROOT / 'sajha' / 'net' / 'library.py'] + sorted((ROOT / 'sajha' / 'net' / 'conformance').glob('*.py'))

FORBIDDEN_PREFIXES = ('sajha.core', 'sajha.db', 'sajha.app', 'sajha.auth', 'sajha.tools', 'sajha.routes',
                      'sajha.web', 'sajha.federation', 'sajha.net.integration', 'sajha.ai', 'sajha.policy',
                      'sajha.observability', 'sajha.notices', 'fastapi', 'starlette', 'sqlalchemy', 'flask', 'uvicorn')


def _forbidden(name: str) -> bool:
    return any(name == p or name.startswith(p + '.') for p in FORBIDDEN_PREFIXES)


@pytest.mark.parametrize('path', FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_imports_only_the_protocol_core(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if _forbidden(a.name) or
                    (a.name.startswith('sajha') and not a.name.startswith('sajha.net') and a.name != 'sajha')]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            m = node.module
            if _forbidden(m) or (m.startswith('sajha') and not m.startswith('sajha.net') and not m.startswith('sajhanet')):
                bad.append(m)
    assert not bad, f'{path.relative_to(ROOT)} imports {bad}'


def test_a_fresh_interpreter_loads_no_part_of_the_server():
    code = ('import sys, json\n'
            'import sajhanet_agent, sajhanet_agent.agent, sajhanet_agent.server, sajhanet_agent.mcp_client\n'
            'import sajhanet_agent.__main__, sajha.net.library, sajha.net.conformance, sajha.net.conformance.__main__\n'
            'print(json.dumps(sorted(sys.modules)))')
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=str(ROOT), timeout=120,
                         env=dict(os.environ, PYTHONPATH=str(ROOT)))
    assert out.returncode == 0, out.stderr
    loaded = json.loads(out.stdout.strip().splitlines()[-1])
    bad = [m for m in loaded if _forbidden(m)]
    assert not bad, f'importing the agent loaded {bad}'
    sajha = [m for m in loaded if m == 'sajha' or m.startswith('sajha.')]
    assert all(m == 'sajha' or m.startswith('sajha.net') for m in sajha), sajha
