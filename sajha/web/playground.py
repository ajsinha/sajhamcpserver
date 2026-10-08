"""
Python Playground: settings, asset location and the security headers of /playground.

The playground runs Python in the visitor's browser with Pyodide (CPython compiled to
WebAssembly) inside a Web Worker. Nothing here executes user code: the server only serves
the page, the worker script, the ``sajha`` bridge module's source, and Pyodide's files.

Configuration (read live through ``sajha.core.config._get``, so ``SAJHA_PLAYGROUND_*``
environment variables override the YAML):

  playground.enabled           true | false            (default true)
  playground.assets            vendored | cdn          (default vendored)
  playground.pyodide_version   e.g. 314.0.7            (default DEFAULT_PYODIDE_VERSION)
  playground.allow_pypi        true | false            (default true): micropip may fetch
                               pure-Python wheels from PyPI (pypi.org, files.pythonhosted.org)

Headers (only on the playground's page and worker; every other route keeps the site-wide
self-only policy from sajha/security.py):

  * the worker's Content-Security-Policy adds 'wasm-unsafe-eval' (compile WebAssembly; plain
    'unsafe-eval' is not needed, checked with every vendored package), the CDN origin when
    ``assets: cdn``, and the PyPI origins when ``allow_pypi`` is on. The page itself runs no
    WebAssembly; its policy only gains worker-src 'self'.
  * Cross-Origin-Opener-Policy: same-origin and Cross-Origin-Embedder-Policy: require-corp
    make the page cross-origin isolated, so it can share a SharedArrayBuffer with the
    worker: Pyodide's interrupt buffer, which is what makes Stop raise KeyboardInterrupt.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

#: The Pyodide release scripts/fetch_pyodide.py vendors by default (checked: GitHub release
#: 314.0.7, Python 3.14). Change both together with playground.pyodide_version.
DEFAULT_PYODIDE_VERSION = '314.0.7'
CDN_ORIGIN = 'https://cdn.jsdelivr.net'
PYPI_ORIGINS = ('https://pypi.org', 'https://files.pythonhosted.org')
ASSET_MODES = ('vendored', 'cdn')
VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')

_WEB_DIR = Path(__file__).resolve().parent
VENDOR_DIR = _WEB_DIR / 'static' / 'vendor' / 'pyodide'
ASSET_DIR = _WEB_DIR / 'playground_assets'

# Starlette serves /static by file extension; make sure the two Pyodide needs are right on
# every platform (a module script must be JavaScript; streaming compile wants application/wasm).
mimetypes.add_type('application/wasm', '.wasm')
mimetypes.add_type('text/javascript', '.mjs')


@dataclass
class PlaygroundSettings:
    enabled: bool = True
    assets: str = 'vendored'
    pyodide_version: str = DEFAULT_PYODIDE_VERSION
    allow_pypi: bool = True
    errors: List[str] = field(default_factory=list)

    @property
    def index_url(self) -> str:
        """Where the worker loads pyodide.mjs and the packages from (ends with '/')."""
        if self.assets == 'cdn':
            return f'{CDN_ORIGIN}/pyodide/v{self.pyodide_version}/full/'
        return f'/static/vendor/pyodide/{self.pyodide_version}/'


def load_settings() -> PlaygroundSettings:
    """The playground settings, validated. A bad value falls back to its default and is
    reported in ``errors`` (shown to administrators on the page and logged)."""
    from sajha.core.config import _get, parse_bool
    s = PlaygroundSettings()
    errors: List[str] = []

    raw = str(_get('playground.enabled', 'true')).strip()
    s.enabled = parse_bool(raw, True) if raw else True

    assets = str(_get('playground.assets', 'vendored') or 'vendored').strip().lower()
    if assets in ASSET_MODES:
        s.assets = assets
    else:
        errors.append(f"playground.assets is {assets!r}; expected one of {', '.join(ASSET_MODES)}. "
                      "Using 'vendored'.")

    version = str(_get('playground.pyodide_version', DEFAULT_PYODIDE_VERSION) or '').strip()
    version = version.lstrip('v') if version else DEFAULT_PYODIDE_VERSION
    if VERSION_RE.match(version):
        s.pyodide_version = version
    else:
        errors.append(f'playground.pyodide_version is {version!r}; expected a release number such as '
                      f'{DEFAULT_PYODIDE_VERSION}. Using {DEFAULT_PYODIDE_VERSION}.')

    raw = str(_get('playground.allow_pypi', 'true')).strip()
    s.allow_pypi = parse_bool(raw, True) if raw else True
    s.errors = errors
    return s


def vendored_manifest(version: str) -> Optional[dict]:
    """sajha-manifest.json of a vendored release, or None when it is not (fully) there."""
    d = VENDOR_DIR / version
    try:
        if not (d / 'pyodide.mjs').is_file() or not (d / 'pyodide.asm.wasm').is_file():
            return None
        m = json.loads((d / 'sajha-manifest.json').read_text())
        return m if isinstance(m, dict) else None
    except (OSError, ValueError):
        return None


def asset_status(s: PlaygroundSettings) -> dict:
    """{'ok': bool, 'packages': [...] or None, 'hint': str}: can the worker load Pyodide?"""
    if s.assets == 'cdn':
        return {'ok': True, 'packages': None, 'hint': ''}
    m = vendored_manifest(s.pyodide_version)
    if m is None:
        return {'ok': False, 'packages': None,
                'hint': (f'Pyodide {s.pyodide_version} is not in sajha/web/static/vendor/pyodide/. '
                         'Run "python scripts/fetch_pyodide.py" on the server, or set '
                         'playground.assets: cdn to load it from cdn.jsdelivr.net.')}
    return {'ok': True, 'packages': list(m.get('packages') or []), 'hint': ''}


# ── Headers ────────────────────────────────────────────────────────────────

def isolation_headers() -> dict:
    """COOP + COEP: cross-origin isolation, so SharedArrayBuffer (the Stop button) works."""
    return {'Cross-Origin-Opener-Policy': 'same-origin',
            'Cross-Origin-Embedder-Policy': 'require-corp',
            'Cross-Origin-Resource-Policy': 'same-origin'}


def page_csp(s: PlaygroundSettings) -> str:
    """The page's policy: the site's self-only policy; workers only from this origin."""
    from sajha.security import console_csp
    return console_csp(img_src="'self' data: blob:", extra="worker-src 'self'")


def worker_csp(s: PlaygroundSettings) -> str:
    """The worker's policy: where Python runs, so the only one that allows WebAssembly."""
    script = ["'self'", "'wasm-unsafe-eval'"]
    connect = ["'self'"]
    if s.assets == 'cdn':
        script.append(CDN_ORIGIN)
        connect.append(CDN_ORIGIN)
    if s.allow_pypi:
        connect.extend(PYPI_ORIGINS)
    return (f"default-src 'self'; script-src {' '.join(script)}; "
            f"connect-src {' '.join(connect)}; img-src 'self' data: blob:")


def page_headers(s: PlaygroundSettings) -> dict:
    h = isolation_headers()
    h['Content-Security-Policy'] = page_csp(s)
    return h


def worker_headers(s: PlaygroundSettings) -> dict:
    h = isolation_headers()
    h['Content-Security-Policy'] = worker_csp(s)
    h['Cache-Control'] = 'no-cache'
    return h


# ── Assets the routes serve ───────────────────────────────────────────────

def bridge_source() -> str:
    """The ``sajha`` module installed into Pyodide (sajha/web/playground_assets/sajha_bridge.py)."""
    return (ASSET_DIR / 'sajha_bridge.py').read_text(encoding='utf-8')


def runtime_source() -> str:
    """The cell runner installed into Pyodide (sajha/web/playground_assets/pg_runtime.py)."""
    return (ASSET_DIR / 'pg_runtime.py').read_text(encoding='utf-8')


def worker_source() -> str:
    return (ASSET_DIR / 'worker.mjs').read_text(encoding='utf-8')


# ── Examples (the page's dropdown) ─────────────────────────────────────────

EXAMPLES: List[dict] = [
    {'id': 'numpy', 'title': 'NumPy basics', 'cells': [
        'import numpy as np\n\n'
        'a = np.arange(12).reshape(3, 4)\n'
        'print("shape:", a.shape)\n'
        'print("column means:", a.mean(axis=0))\n'
        'a @ a.T          # the last expression is shown, like a REPL',
    ]},
    {'id': 'pandas', 'title': 'pandas: groupby and pivot', 'cells': [
        'import pandas as pd\n\n'
        'sales = pd.DataFrame({\n'
        '    "region":  ["North", "South", "North", "East", "South", "East", "North"],\n'
        '    "product": ["A", "A", "B", "A", "B", "B", "A"],\n'
        '    "units":   [10, 4, 7, 12, 3, 9, 5],\n'
        '    "price":   [2.5, 2.5, 4.0, 2.5, 4.0, 4.0, 2.5],\n'
        '})\n'
        'sales["revenue"] = sales.units * sales.price\n'
        'sales.groupby("region")[["units", "revenue"]].sum()',
        'sales.pivot_table(index="region", columns="product", values="revenue",\n'
        '                  aggfunc="sum", fill_value=0)',
    ]},
    {'id': 'matplotlib', 'title': 'matplotlib chart', 'cells': [
        'import numpy as np\n'
        'import matplotlib.pyplot as plt\n\n'
        'x = np.linspace(0, 4 * np.pi, 400)\n'
        'fig, ax = plt.subplots(figsize=(7, 3.2))\n'
        'ax.plot(x, np.sin(x), label="sin")\n'
        'ax.plot(x, np.cos(x) * np.exp(-x / 8), label="damped cos")\n'
        'ax.set_title("Figures appear below the cell")\n'
        'ax.legend()\n'
        'plt.show()',
    ]},
    {'id': 'scipy', 'title': 'SciPy statistics', 'cells': [
        'import numpy as np\n'
        'from scipy import stats\n\n'
        'rng = np.random.default_rng(7)\n'
        'a = rng.normal(100, 15, 200)\n'
        'b = rng.normal(104, 15, 200)\n'
        't, p = stats.ttest_ind(a, b)\n'
        'print(f"t = {t:.3f}, p = {p:.4f}")\n'
        'stats.describe(a)',
    ]},
    {'id': 'sklearn', 'title': 'scikit-learn regression', 'cells': [
        'import numpy as np\n'
        'from sklearn.linear_model import LinearRegression\n'
        'from sklearn.model_selection import train_test_split\n'
        'from sklearn.metrics import r2_score\n\n'
        'rng = np.random.default_rng(0)\n'
        'X = rng.uniform(0, 10, (300, 2))\n'
        'y = 3.0 * X[:, 0] - 1.5 * X[:, 1] + rng.normal(0, 1, 300)\n'
        'X_tr, X_te, y_tr, y_te = train_test_split(X, y, random_state=0)\n'
        'model = LinearRegression().fit(X_tr, y_tr)\n'
        'print("coefficients:", model.coef_.round(3), "intercept:", round(model.intercept_, 3))\n'
        'print("R² on held-out data:", round(r2_score(y_te, model.predict(X_te)), 4))',
    ]},
    {'id': 'sajha_tools', 'title': 'SAJHA: list my tools', 'cells': [
        'import sajha\n\n'
        'tools = sajha.tools()          # the tools you may call, as the server decides\n'
        'print(len(tools), "tools available to you")\n'
        '[t["name"] for t in tools][:20]',
    ]},
    {'id': 'sajha_calc', 'title': 'SAJHA: call a tool, analyse with pandas, plot', 'cells': [
        'import sajha\n'
        'import pandas as pd\n\n'
        '# Future value of 10,000 at several rates and horizons, from the server\'s\n'
        '# calc_future_value tool (offline: no API key needed).\n'
        'rows = []\n'
        'for rate in (3, 5, 7):\n'
        '    for years in (5, 10, 20, 30):\n'
        '        r = sajha.call("calc_future_value", present_value=10000, rate=rate, years=years)\n'
        '        rows.append({"rate %": rate, "years": years, "future value": r["future_value"]})\n'
        'df = pd.DataFrame(rows)\n'
        'df.pivot(index="years", columns="rate %", values="future value").round(0)',
        'import matplotlib.pyplot as plt\n\n'
        'fig, ax = plt.subplots(figsize=(7, 3.2))\n'
        'for rate, g in df.groupby("rate %"):\n'
        '    ax.plot(g["years"], g["future value"], marker="o", label=f"{rate}%")\n'
        'ax.set_xlabel("years"); ax.set_ylabel("future value"); ax.legend(title="rate")\n'
        'ax.set_title("calc_future_value, called from the browser")\n'
        'plt.show()',
    ]},
    {'id': 'sajha_quote', 'title': 'SAJHA: fetch a quote and a rate (network tools)', 'cells': [
        'import sajha\n\n'
        '# Network tools need the server to reach their provider (and sometimes an API key).\n'
        '# A failure comes back as sajha.ToolError carrying the server\'s message.\n'
        'mine = {t["name"] for t in sajha.tools()}\n'
        'for name, args in [("yahoo_get_quote", {"symbol": "AAPL"}),\n'
        '                   ("ecb_get_exchange_rate", {"indicator": "eur_usd", "recent_periods": 30})]:\n'
        '    if name not in mine:\n'
        '        print(name, "is not available to you"); continue\n'
        '    try:\n'
        '        result = sajha.call(name, **args)\n'
        '        print(name, "→", str(result)[:300])\n'
        '    except sajha.ToolError as e:\n'
        '        print(name, "failed:", e)',
    ]},
    {'id': 'sajha_ask', 'title': 'SAJHA: ask a question', 'cells': [
        'import sajha\n\n'
        'r = sajha.ask("What is the percentage change from 80 to 100?")\n'
        'print(r["answer"])\n'
        '[(s["name"], s["ok"]) for s in r["steps"]]',
    ]},
]
