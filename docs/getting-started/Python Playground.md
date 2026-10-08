# Python Playground

The Python Playground (`/playground`, **Tools → Python Playground**) is a small notebook that
runs Python in your browser. It uses [Pyodide](https://pyodide.org), CPython compiled to
WebAssembly, inside a Web Worker, so long computations never freeze the page. numpy, pandas,
matplotlib, scipy, scikit-learn, statsmodels and sympy load when a cell first imports them,
and `import sajha` calls this server's tools and Ask SAJHA with your own permissions.

Nothing you type runs on the server. The server serves the page, the worker script, two
small Python files and Pyodide's own files; Python runs in your browser tab.

A hands-on walk-through is [Tutorial 12](../tutorials/TUTORIAL_12_python_playground.md).

## Using the notebook

| Action | How |
|---|---|
| Run a cell | ▶ beside it, or **Ctrl+Enter** (**Cmd+Enter** on a Mac) in the editor |
| Run a cell and move on | **Shift+Enter** (moves to the next cell, adding one after the last) |
| Run every cell, top to bottom | **Run all**. A failing cell stops the rest. |
| Interrupt | **Stop** raises `KeyboardInterrupt` in the running cell; your variables survive |
| Start again | **Reset** restarts Python: every variable and output is cleared |
| Add, move, delete cells | **Add cell**; the arrows and bin on each cell |
| Examples | The **Examples** menu replaces the cells (it asks first) |
| Keep your work | **Save** / **Load** keep one notebook in this browser's storage; the current cells are also kept as a draft and come back when you reopen the page |
| Files | **.py** downloads every cell as one file, separated by `# %%` markers; **Open** reads a `.py` file (split at `# %%`) or a Jupyter `.ipynb` (its code cells) |

All cells share one namespace, as in Jupyter. Below each cell:

- **stdout** in plain text and **stderr** in red; an exception shows a short traceback that
  starts at your cell;
- the value of the **last expression**, as a REPL shows it: an object with `_repr_html_`
  (a pandas DataFrame) as a table, anything else as its `repr`. End the line with `;` to
  hide it;
- **matplotlib figures**, as PNG images, when you call `plt.show()` or when the cell ends;
- anything you pass to `display(obj)` (available in every cell), straight away.

The status pill at the top right says what the runtime is doing (downloading, loading a
package, running, ready), and **Packages** lists what is loaded.

## Packages

A cell's imports are scanned before it runs (`pyodide.loadPackagesFromImports`) and the
packages it needs, with their dependencies, are fetched then. The first page load fetches
only the Python runtime itself.

- **Vendored assets** (the default): the packages available are the ones
  `scripts/fetch_pyodide.py` vendored (numpy, pandas, matplotlib, scipy, scikit-learn,
  statsmodels, sympy and micropip, with their dependencies, unless the administrator chose
  others). Importing another Pyodide package fails with a message naming it; the
  administrator can add it with `python scripts/fetch_pyodide.py --packages <name> ...`.
- **CDN assets**: every package of that Pyodide release is available.
- **micropip** installs pure-Python wheels from PyPI when `playground.allow_pypi` is true
  (the default): `import micropip` then `await micropip.install("tabulate")` in a cell
  (top-level `await` works).

## The `sajha` module

`sajha` is installed into Python when the runtime starts. Its source is served at
`/api/playground/sajha.py` (`sajha/web/playground_assets/sajha_bridge.py`).

| Call | What it does |
|---|---|
| `sajha.tools(refresh=False)` | The tools you may call, as the server decides: a list of `{name, description, category}` from `GET /api/playground/tools` |
| `sajha.schema(name)` | One tool's MCP description, including `inputSchema` (`GET /api/tools/{name}/schema`) |
| `sajha.call(name, **arguments)` | Runs the tool on the server through `POST /api/tools/execute` and returns its result as Python data. Use `sajha.call(name, {"arg": 1})` for argument names that are not Python identifiers. |
| `sajha.ask(question, model=None)` | Asks SAJHA (`POST /api/ai/ask`) and returns the answer: `answer`, `steps`, `citations`, `confidence` |
| `sajha.server()` | The origin these calls go to (the page's own) |
| `sajha.ToolError` | Raised when a call is refused or fails; `.status` is the HTTP status (401 when your session has expired, 403 for a tool you may not use, 404 for an unknown tool) |

Calls are synchronous (a blocking request is allowed in a worker), so they need no `await`.
Each request carries your session cookie and is checked by the server exactly as on the
Tools page: tool access, usage logging and auditing are the same.

```python
import sajha, pandas as pd

rows = [sajha.call("calc_future_value", present_value=10000, rate=r, years=y)
        for r in (3, 5, 7) for y in (10, 20, 30)]
pd.DataFrame(rows).pivot(index="years", columns="rate", values="future_value")
```

### From MCP Studio

The Python code tool creator on Studio home has **Open in playground**. It hands the
function in the editor to a new playground tab (through this browser's storage), followed
by a cell that calls it with sample arguments. `from sajha.studio import sajhamcptool`
works in the playground: the decorator records its metadata and returns the function
unchanged, so you can try the function before deploying it.

## Where Pyodide comes from

SAJHA's Content-Security-Policy is self-only, so by default the playground loads Pyodide
from this server (`playground.assets: vendored`):

```
python scripts/fetch_pyodide.py                 # the release in playground.pyodide_version
python scripts/fetch_pyodide.py --list          # show which packages would be fetched
python scripts/fetch_pyodide.py --packages numpy pandas   # a smaller set
```

The script downloads the release's core archive from GitHub and checks its SHA-256 against
the digest GitHub publishes for it (the default release's digest is also pinned in the
script). It then reads `pyodide-lock.json` from that verified archive and downloads each
package wheel, checking every one against the lockfile's SHA-256. Files go to
`sajha/web/static/vendor/pyodide/<version>/` with a `sajha-manifest.json`; everything there
except the folder's README is git-ignored. The script prints the total size (tens of
megabytes for the default packages).

Until those files are present, the page says so (with this command, for administrators)
instead of failing silently. The alternative is `playground.assets: cdn`, which loads the
same release from `https://cdn.jsdelivr.net/pyodide/v<version>/full/`.

The editor is CodeMirror 6, vendored as one bundle in `sajha/web/static/vendor/codemirror/`
(its README says how to rebuild it).

## Security

- **Where code runs.** In the browser tab only, in a Web Worker, inside the browser's
  WebAssembly sandbox. The server has no endpoint that runs playground code. Closing the
  tab ends the Python process.
- **What code can reach.** The same origin, with the user's session, through
  `sajha.call` and `sajha.ask` (or any same-origin request). That is no more than the user
  can already do on the Tools page, and every request is authorized server-side. Rich HTML
  output (pandas tables) is rebuilt from an allowlist of table and text tags before it is
  shown: no scripts, event handlers or links.
- **Limits.** Tool calls are ordinary `POST /api/tools/execute` requests, so the server's
  own limits apply (the request-body cap, `server.max_request_bytes`, each tool's own timeouts, and for
  `sajha.ask` the `ai.ask` step, call and time limits). The bridge gives up on a request
  after 120 seconds on the browser side. While a call is waiting for the server, **Stop**
  takes effect when it returns.
- **Headers** (`sajha/web/playground.py`; every other route keeps the site-wide policy in
  [Security Model](../security/Security%20Model.md#security-headers-and-csp)):

| Response | Header | Why |
|---|---|---|
| `/playground` | `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Embedder-Policy: require-corp` | Cross-origin isolation: the page may share a `SharedArrayBuffer` with the worker, Pyodide's interrupt buffer, which is how **Stop** interrupts running Python |
| `/playground` | the site CSP plus `worker-src 'self'` (and `blob:` images) | The page itself runs no WebAssembly |
| `/api/playground/worker.js` | CSP with `script-src 'self' 'wasm-unsafe-eval'`; COOP/COEP as above | Compiling WebAssembly needs `'wasm-unsafe-eval'`; it is granted to this worker only. `'unsafe-eval'` is not needed. |
| `/api/playground/worker.js` | `https://cdn.jsdelivr.net` in `script-src` and `connect-src` | Only when `playground.assets` is `cdn` |
| `/api/playground/worker.js` | `https://pypi.org https://files.pythonhosted.org` in `connect-src` | Only when `playground.allow_pypi` is true (micropip) |

  If a browser does not grant cross-origin isolation (for example when the page is
  embedded somewhere unusual), **Stop** falls back to restarting Python, which loses the
  variables; the cell says so.
- **Who can open it.** Signed-in users only; an anonymous visitor is sent to the landing
  page. Administrators can switch the playground off with `playground.enabled: false`.

## Configuration

`playground.enabled`, `playground.assets`, `playground.pyodide_version` and
`playground.allow_pypi`, read on every request with `SAJHA_PLAYGROUND_*` overrides. Defaults
and details: [Configuration Reference](Configuration%20Reference.md#playground).

## Troubleshooting

| You see | Do this |
|---|---|
| "The Python runtime is not installed on this server" | Run `python scripts/fetch_pyodide.py` on the server, or set `playground.assets: cdn` |
| `ModuleNotFoundError` for a package Pyodide ships | With vendored assets it was not vendored: `python scripts/fetch_pyodide.py --packages <name>`; or use `cdn` |
| `sajha.ToolError: not signed in` | Your session expired: sign in again and reload the page (Python restarts) |
| **Stop** restarts Python instead of interrupting | The page is not cross-origin isolated: check that a proxy is not stripping the COOP/COEP headers from `/playground` and `/api/playground/worker.js` |
| micropip cannot reach PyPI | `playground.allow_pypi` is false, or the browser cannot reach `pypi.org` |

## Where the code is

| Part | File |
|---|---|
| Routes | `sajha/routes/playground_routes.py` |
| Settings, headers, examples | `sajha/web/playground.py` |
| Worker, cell runner, `sajha` module | `sajha/web/playground_assets/` |
| Page | `sajha/web/templates/playground/playground.html`, `sajha/web/static/js/playground.js` |
| Asset fetcher | `scripts/fetch_pyodide.py` |
| Tests | `tests/test_playground.py` |
