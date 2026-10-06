// SAJHA Python Playground: the Web Worker that runs Python (Pyodide) off the page's thread.
// Served at /api/playground/worker.js with the playground's own CSP and COOP/COEP headers
// (sajha/web/playground.py); the page (static/js/playground.js) talks to it by messages:
//
//   page → worker  {type:'init', indexURL, interruptBuffer}   load Pyodide + the sajha module
//                  {type:'run', id, code}                     run one cell
//   worker → page  {type:'status', phase, text}               loading progress / ready / error
//                  {type:'packages', names}                   what is loaded now
//                  {type:'out', id, kind, text}               stdout, stderr, text/plain, text/html, image/png
//                  {type:'done', id, ok, ms}                  the cell finished
//
// Nothing here talks to the server except to fetch Pyodide's files and, from Python, the
// sajha bridge's same-origin API calls with the user's own session.

let pyodide = null;
let runtime = null;
let currentId = null;

const post = (m) => self.postMessage(m);
const status = (phase, text) => post({type: 'status', phase, text});

// Coalesce stdout/stderr: post every 40 ms or 4 KB, so a print loop does not flood the page.
// (While Python runs, this worker's event loop is blocked, so no timers: flush on write.)
const streams = {stdout: '', stderr: ''};
let lastFlush = 0;
function flush(force) {
  const now = performance.now();
  if (!force && now - lastFlush < 40 && streams.stdout.length + streams.stderr.length < 4096) return;
  lastFlush = now;
  for (const k of ['stdout', 'stderr']) {
    if (streams[k]) { post({type: 'out', id: currentId, kind: k, text: streams[k]}); streams[k] = ''; }
  }
}
const writer = (k) => ({batched: (s) => { streams[k] += s + '\n'; flush(false); }});

function loaded() {
  post({type: 'packages', names: Object.keys(pyodide.loadedPackages || {}).sort()});
}

async function init(msg) {
  const indexURL = msg.indexURL;
  status('loading', 'Downloading the Python runtime…');
  let mod;
  try {
    mod = await import(indexURL + 'pyodide.mjs');
  } catch (e) {
    status('error', `Could not load ${indexURL}pyodide.mjs (${e && e.message || e}).`);
    return;
  }
  try {
    pyodide = await mod.loadPyodide({indexURL, fullStdLib: false});
  } catch (e) {
    status('error', `Pyodide failed to start: ${e && e.message || e}`);
    return;
  }
  status('loading', 'Starting Python…');
  pyodide.setStdout(writer('stdout'));
  pyodide.setStderr(writer('stderr'));
  if (msg.interruptBuffer) pyodide.setInterruptBuffer(msg.interruptBuffer);
  pyodide.registerJsModule('_pg_js', {
    emit: (kind, text) => { flush(true); post({type: 'out', id: currentId, kind, text}); },
  });
  try {
    const [bridge, rt] = await Promise.all([
      fetch('/api/playground/sajha.py', {credentials: 'same-origin'}).then((r) => { if (!r.ok) throw new Error('sajha.py: HTTP ' + r.status); return r.text(); }),
      fetch('/api/playground/runtime.py', {credentials: 'same-origin'}).then((r) => { if (!r.ok) throw new Error('runtime.py: HTTP ' + r.status); return r.text(); }),
    ]);
    pyodide.FS.mkdirTree('/home/pyodide/sajha');
    pyodide.FS.writeFile('/home/pyodide/sajha/__init__.py', bridge);
    pyodide.FS.writeFile('/home/pyodide/pg_runtime.py', rt);
    pyodide.runPython("import sys\nif '/home/pyodide' not in sys.path: sys.path.insert(0, '/home/pyodide')");
    runtime = pyodide.pyimport('pg_runtime');
  } catch (e) {
    status('error', `Could not install the sajha module: ${e && e.message || e}`);
    return;
  }
  loaded();
  status('ready', `Python ${pyodide.runPython('import sys; sys.version.split()[0]')} ready (Pyodide ${pyodide.version})`);
}

async function run(msg) {
  currentId = msg.id;
  const t0 = performance.now();
  let ok = false;
  try {
    // Fetch only the packages this cell imports (numpy, pandas, ...): first load stays small.
    const before = new Set(Object.keys(pyodide.loadedPackages || {}));
    await pyodide.loadPackagesFromImports(msg.code, {
      messageCallback: (m) => { if (/^Loading|^Loaded/.test(m)) status('packages', m); },
      errorCallback: (m) => { streams.stderr += m + '\n'; },
    });
    if (Object.keys(pyodide.loadedPackages || {}).some((n) => !before.has(n))) loaded();
    ok = await runtime.run_cell(msg.code);
  } catch (e) {
    streams.stderr += String(e && e.message || e) + '\n';
  } finally {
    flush(true);
    status('ready', 'Ready');
    post({type: 'done', id: msg.id, ok: !!ok, ms: Math.round(performance.now() - t0)});
    currentId = null;
  }
}

// Runs are queued, so "Run all" and quick re-runs execute one cell at a time, in order.
let chain = Promise.resolve();
self.onmessage = (ev) => {
  const msg = ev.data || {};
  if (msg.type === 'init') chain = chain.then(() => init(msg));
  else if (msg.type === 'run') chain = chain.then(() => (runtime ? run(msg) : post({type: 'done', id: msg.id, ok: false, ms: 0})));
};
