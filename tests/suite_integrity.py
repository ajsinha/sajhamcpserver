# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Suite integrity checks (docs/architecture/Adversarial QA Plan.md §3.13), loaded by tests/conftest.py.

* **Required modules.** ``REQUIRED`` lists the test modules whose area must run: a test in one of them
  skipped because an import is missing fails the session (the deck tests were once skipped for weeks
  this way). ``SAJHA_TEST_ALLOW_MISSING`` relaxes it: ``1`` (or ``all``) allows every module, else a
  comma-separated list of module paths (or of the keys below) is allowed.
* **The developer's files.** Every file under ``data/`` and ``config/`` is fingerprinted when the
  session starts and compared when it ends; a test that leaves one added, changed or deleted fails the
  session. ``SAJHA_TEST_ALLOW_REPO_WRITES=1`` turns the failure into a warning (for example while a
  development server writes ``data/`` beside the run).
* **Shifted clock.** ``SAJHA_TEST_CLOCK_SHIFT_DAYS=N`` runs the session with the clock moved ``N`` days
  ahead (time-machine, ticking), so expiry, key, certificate, schedule and SAJHA Net clock code is
  exercised at a future date (CI: the ``shifted-clock`` job of .github/workflows/tests.yml).

Random order: pytest-randomly (requirements-dev.txt) shuffles every run and prints its seed in the
header; ``--randomly-seed=N`` repeats an order and ``-p no:randomly`` turns shuffling off.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: The one list of test modules that must never be skipped for a missing dependency (module path ->
#: what provides it). Add a module here when its area is part of the gate.
REQUIRED = {
    'tests/test_deck_geometry.py': 'python-pptx (requirements-dev.txt)',
    'tests/ai/test_openai_api.py': 'openai (requirements.txt)',
    'tests/tools/test_qlrisk_tools.py': 'qlrisk (requirements-qlrisk.txt)',
    'tests/test_federation.py': 'mcp, the official MCP SDK (requirements.txt)',
    'tests/test_federation_mcp_servers.py': 'mcp (requirements.txt)',
    'tests/test_connected_accounts.py': 'mcp (requirements.txt)',
    'tests/test_stdio_transport.py': 'mcp (requirements.txt)',
    'tests/test_cli.py': 'mcp (requirements.txt)',
    'tests/net/test_net_streaming.py': 'mcp and uvicorn (requirements.txt)',
    'clientsdk/tests/test_standard_client.py': 'mcp (requirements.txt)',
    'tests/test_olap_sql_injection.py': 'duckdb (requirements.txt)',
    'tests/unit/test_pivot_totals.py': 'duckdb (requirements.txt)',
    'tests/test_connectors.py': 'duckdb, httpx (requirements.txt), sqlglot (requirements-dev.txt)',
    'tests/test_state_multiworker.py': 'httpx (requirements.txt)',
    'tests/test_state_store.py': 'fakeredis[lua] (requirements-dev.txt)',
    'tests/test_k8s_deployment.py': 'jsonschema (requirements.txt)',
    'tests/test_sajhanet_groundwork.py': 'jsonschema (requirements.txt)',
}

_IMPORT_SKIP_MARKERS = ('could not import', 'no module named', 'not installed')

#: Watched for writes by tests (relative to the repository root).
WATCHED = ('data', 'config')


# ── shifted clock ────────────────────────────────────────────────────

def start_shifted_clock():
    """Start the shifted clock when SAJHA_TEST_CLOCK_SHIFT_DAYS asks for one (returns the traveller)."""
    days = os.environ.get('SAJHA_TEST_CLOCK_SHIFT_DAYS', '').strip()
    if not days or days == '0':
        return None
    import time_machine
    trav = time_machine.travel(datetime.now(timezone.utc) + timedelta(days=float(days)), tick=True)
    trav.start()
    return trav


# ── required modules ─────────────────────────────────────────────────

def _allowed_missing() -> set:
    raw = os.environ.get('SAJHA_TEST_ALLOW_MISSING', '').strip()
    if raw.lower() in ('1', 'true', 'all', '*'):
        return set(REQUIRED)
    return {p.strip() for p in raw.split(',') if p.strip()}


def _skip_reason(report) -> str:
    lr = report.longrepr
    if isinstance(lr, tuple) and len(lr) == 3:
        return str(lr[2])
    return str(lr or '')


def _module_of(nodeid: str) -> str:
    return nodeid.split('::', 1)[0].replace('\\', '/')


class _Integrity:
    def __init__(self):
        self.missing = {}            # module -> first skip reason
        self.before = None

    # skips
    def note(self, report):
        if not report.skipped or hasattr(report, 'wasxfail'):
            return
        mod = _module_of(report.nodeid)
        if mod not in REQUIRED:
            return
        reason = _skip_reason(report)
        if any(m in reason.lower() for m in _IMPORT_SKIP_MARKERS):
            self.missing.setdefault(mod, reason)

    # the developer's files
    @staticmethod
    def fingerprint() -> dict:
        out = {}
        for top in WATCHED:
            base = ROOT / top
            if not base.is_dir():
                continue
            for p in base.rglob('*'):
                if '__pycache__' in p.parts or not p.is_file() or p.is_symlink():
                    continue
                try:
                    h = hashlib.sha1()
                    with open(p, 'rb') as f:
                        for chunk in iter(lambda: f.read(1 << 20), b''):
                            h.update(chunk)
                    out[str(p.relative_to(ROOT))] = h.hexdigest()
                except OSError:
                    continue
        return out


_state = _Integrity()


def pytest_sessionstart(session):
    if not hasattr(session.config, 'workerinput'):
        _state.before = _Integrity.fingerprint()


def pytest_collectreport(report):
    _state.note(report)


def pytest_runtest_logreport(report):
    _state.note(report)


def pytest_sessionfinish(session, exitstatus):
    problems = []
    allowed = _allowed_missing()
    for mod, reason in sorted(_state.missing.items()):
        if mod in allowed:
            continue
        problems.append(f'required test module {mod} was skipped for a missing dependency '
                        f'({REQUIRED[mod]}): {reason.strip()[:200]}; install it or set '
                        f'SAJHA_TEST_ALLOW_MISSING={mod}')
    if _state.before is not None:
        after = _Integrity.fingerprint()
        changed = sorted(p for p in set(_state.before) | set(after) if _state.before.get(p) != after.get(p))
        if changed:
            what = ', '.join(changed[:20]) + (' ...' if len(changed) > 20 else '')
            msg = f'tests changed the developer\'s files under data/ or config/: {what}'
            if os.environ.get('SAJHA_TEST_ALLOW_REPO_WRITES', '').strip().lower() in ('1', 'true', 'yes'):
                print(f'\nWARNING (SAJHA_TEST_ALLOW_REPO_WRITES): {msg}')
            else:
                problems.append(msg)
    if problems:
        tr = session.config.pluginmanager.get_plugin('terminalreporter')
        for p in problems:
            if tr is not None:
                tr.write_line(f'SUITE INTEGRITY: {p}', red=True, bold=True)
            else:
                print(f'SUITE INTEGRITY: {p}')
        if session.exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
