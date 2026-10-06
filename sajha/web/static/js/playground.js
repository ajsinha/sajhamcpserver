/*
 * SAJHA Python Playground (/playground): the page side of a small notebook.
 * Python runs in a Web Worker (/api/playground/worker.js, Pyodide); this file owns the cells,
 * the editors (vendor/codemirror), the outputs, Stop/Reset, examples, and saving.
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha
 */
(function () {
  'use strict';

  var DATA = {};
  try { DATA = JSON.parse(document.getElementById('pgData').textContent || '{}'); } catch (e) { DATA = {}; }
  var KEY_SAVED = 'sajha.playground.saved.v1';
  var KEY_DRAFT = 'sajha.playground.draft.v1';
  var KEY_IMPORT = 'sajha.playground.import';    // set by MCP Studio's "Open in playground"
  var MAX_OUT = 1000000;                          // characters of text output kept per cell

  var $ = function (id) { return document.getElementById(id); };
  var cellsEl = $('pgCells'), tpl = $('pgCellTpl');
  var statusEl = $('pgStatus'), dotEl = $('pgDot');
  var btnRunAll = $('pgRunAll'), btnStop = $('pgStop'), btnReset = $('pgReset');

  var cells = [];          // {id, el, editor, out, countEl, chars}
  var nextId = 1, execCount = 0;
  var worker = null, ready = false, interrupt = null;
  var queue = [], running = null;

  // ── storage (any of these may throw: private mode, blocked storage) ───────
  function store(key, value) { try { localStorage.setItem(key, value); return true; } catch (e) { return false; } }
  function load(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function drop(key) { try { localStorage.removeItem(key); } catch (e) { /* ignore */ } }

  // ── status ─────────────────────────────────────────────────────────────────
  function setStatus(phase, text) {
    statusEl.textContent = text;
    dotEl.className = 'pg-dot pg-dot-' + phase;
  }
  function setBusy() {
    var busy = !!running;
    btnStop.disabled = !busy;
    btnRunAll.disabled = !ready;
    btnReset.disabled = !worker;
    cells.forEach(function (c) { c.el.classList.toggle('pg-running', running === c); });
  }

  // ── the worker ─────────────────────────────────────────────────────────────
  function startWorker() {
    if (!DATA.assetsOk) {
      setStatus('error', 'Python runtime not installed on this server');
      return;
    }
    if (typeof Worker === 'undefined') { setStatus('error', 'This browser has no Web Workers'); return; }
    ready = false;
    interrupt = null;
    if (window.crossOriginIsolated && typeof SharedArrayBuffer !== 'undefined') {
      interrupt = new Int32Array(new SharedArrayBuffer(4));
    }
    try {
      worker = new Worker('/api/playground/worker.js', {type: 'module', name: 'sajha-python'});
    } catch (e) {
      setStatus('error', 'Could not start the Python worker: ' + e.message);
      return;
    }
    worker.onmessage = onWorkerMessage;
    worker.onerror = function (e) {
      setStatus('error', 'Python worker error: ' + (e.message || 'see the browser console'));
      finishRun(false);
    };
    setStatus('loading', 'Starting…');
    worker.postMessage({type: 'init', indexURL: DATA.indexURL, interruptBuffer: interrupt});
    setBusy();
  }

  function stopWorker() {
    if (worker) { worker.terminate(); worker = null; }
    ready = false;
  }

  function onWorkerMessage(ev) {
    var m = ev.data || {};
    if (m.type === 'status') {
      if (m.phase === 'ready') {
        ready = true;
        if (m.text !== 'Ready') readyText = m.text;
        setStatus(running ? 'busy' : 'ready', running ? 'Running…' : readyText);
        pump();
      } else if (m.phase === 'packages') {
        setStatus('loading', m.text);
      } else {
        setStatus(m.phase, m.text);
        if (m.phase === 'error') { ready = false; queue = []; }
      }
      setBusy();
    } else if (m.type === 'packages') {
      showPackages(m.names || []);
    } else if (m.type === 'out') {
      var c = byId(m.id);
      if (c) appendOutput(c, m.kind, m.text);
    } else if (m.type === 'done') {
      finishRun(m.ok, m.ms);
    }
  }
  var readyText = 'Ready';

  function showPackages(names) {
    var el = $('pgPackageList');
    var shown = names.filter(function (n) { return n !== 'sajha'; });
    if (!shown.length) return;
    el.className = '';
    el.textContent = '';
    shown.forEach(function (n) {
      var s = document.createElement('span');
      s.className = 'pg-chip';
      s.textContent = n;
      el.appendChild(s);
      el.appendChild(document.createTextNode(' '));
    });
  }

  // ── running cells ──────────────────────────────────────────────────────────
  function byId(id) { for (var i = 0; i < cells.length; i++) if (cells[i].id === id) return cells[i]; return null; }

  function enqueue(c) {
    if (!worker) startWorker();
    if (queue.indexOf(c) < 0 && running !== c) queue.push(c);
    c.el.classList.add('pg-queued');
    c.countEl.textContent = '[*]';
    pump();
  }

  function pump() {
    if (running || !ready || !queue.length) return;
    var c = queue.shift();
    if (cells.indexOf(c) < 0) { pump(); return; }
    running = c;
    c.el.classList.remove('pg-queued');
    clearOutput(c);
    if (interrupt) Atomics.store(interrupt, 0, 0);
    setStatus('busy', 'Running…');
    setBusy();
    worker.postMessage({type: 'run', id: c.id, code: c.editor.getValue()});
  }

  function finishRun(ok, ms) {
    var c = running;
    running = null;
    if (c) {
      execCount += 1;
      c.countEl.textContent = '[' + execCount + ']';
      c.el.classList.toggle('pg-failed', !ok);
      if (typeof ms === 'number') c.countEl.title = 'Ran in ' + ms + ' ms';
      if (!ok) { queue.forEach(function (q) { q.el.classList.remove('pg-queued'); q.countEl.textContent = '[ ]'; }); queue = []; }
    }
    if (ready) setStatus('ready', readyText);
    setBusy();
    pump();
  }

  function stop() {
    queue.forEach(function (q) { q.el.classList.remove('pg-queued'); q.countEl.textContent = '[ ]'; });
    queue = [];
    if (!running) return;
    if (interrupt) {
      Atomics.store(interrupt, 0, 2);       // SIGINT: Python raises KeyboardInterrupt
      setStatus('busy', 'Stopping…');
    } else {
      // Not cross-origin isolated: the only way to stop is to restart Python.
      var c = running;
      appendOutput(c, 'stderr', 'Stopped by restarting Python (variables were lost).\n');
      stopWorker();
      running = null;
      c.countEl.textContent = '[!]';
      startWorker();
    }
  }

  function reset() {
    queue = [];
    running = null;
    stopWorker();
    execCount = 0;
    cells.forEach(function (c) { clearOutput(c); c.countEl.textContent = '[ ]'; c.el.classList.remove('pg-failed', 'pg-queued'); });
    $('pgPackageList').className = 'text-muted';
    $('pgPackageList').textContent = 'none loaded yet — imports load on first run';
    startWorker();
  }

  // ── output ─────────────────────────────────────────────────────────────────
  function clearOutput(c) { c.out.textContent = ''; c.chars = 0; c.el.classList.remove('pg-failed'); }

  function appendOutput(c, kind, text) {
    var out = c.out;
    if (kind === 'stdout' || kind === 'stderr') {
      if (c.chars > MAX_OUT) return;
      c.chars += text.length;
      if (c.chars > MAX_OUT) text = text.slice(0, Math.max(0, text.length - (c.chars - MAX_OUT))) + '\n… output truncated\n';
      var last = out.lastElementChild;
      if (!last || last.getAttribute('data-kind') !== kind) {
        last = document.createElement('pre');
        last.className = kind === 'stderr' ? 'pg-out pg-err' : 'pg-out';
        last.setAttribute('data-kind', kind);
        out.appendChild(last);
      }
      last.textContent += text;
    } else if (kind === 'text/plain') {
      var pre = document.createElement('pre');
      pre.className = 'pg-out pg-repr';
      pre.textContent = text;
      out.appendChild(pre);
    } else if (kind === 'text/html') {
      var div = document.createElement('div');
      div.className = 'pg-html';
      div.appendChild(sanitize(text));
      out.appendChild(div);
    } else if (kind === 'image/png') {
      var img = document.createElement('img');
      img.className = 'pg-img';
      img.alt = 'Figure';
      img.src = 'data:image/png;base64,' + text;
      out.appendChild(img);
    }
  }

  // Rich HTML (pandas tables) comes from the user's own code, but it is still parsed into an
  // inert document and rebuilt from an allowlist: no scripts, no event handlers, no URLs.
  var TAGS = {TABLE: 1, THEAD: 1, TBODY: 1, TFOOT: 1, TR: 1, TH: 1, TD: 1, CAPTION: 1, COLGROUP: 1, COL: 1,
              DIV: 1, SPAN: 1, P: 1, B: 1, I: 1, STRONG: 1, EM: 1, BR: 1, CODE: 1, PRE: 1, SMALL: 1,
              SUB: 1, SUP: 1, UL: 1, OL: 1, LI: 1, H1: 1, H2: 1, H3: 1, H4: 1, HR: 1};
  var ATTRS = {colspan: 1, rowspan: 1, align: 1, title: 1, 'class': 1};
  function sanitize(html) {
    var doc = new DOMParser().parseFromString('<body>' + html + '</body>', 'text/html');
    var frag = document.createDocumentFragment();
    function copy(src, dst) {
      src.childNodes.forEach(function (n) {
        if (n.nodeType === 3) { dst.appendChild(document.createTextNode(n.nodeValue)); return; }
        if (n.nodeType !== 1) return;
        if (!TAGS[n.tagName]) {
          if (n.tagName !== 'STYLE' && n.tagName !== 'SCRIPT') copy(n, dst);   // keep the text, drop the tag
          return;
        }
        var el = document.createElement(n.tagName.toLowerCase());
        for (var i = 0; i < n.attributes.length; i++) {
          var a = n.attributes[i];
          if (ATTRS[a.name.toLowerCase()]) el.setAttribute(a.name, a.value);
        }
        copy(n, el);
        dst.appendChild(el);
      });
    }
    copy(doc.body, frag);
    return frag;
  }

  // ── cells ──────────────────────────────────────────────────────────────────
  var draftTimer = null;
  function saveDraftSoon() {
    clearTimeout(draftTimer);
    draftTimer = setTimeout(function () { store(KEY_DRAFT, JSON.stringify(sources())); }, 600);
  }

  function addCell(code, after) {
    var node = tpl.content.firstElementChild.cloneNode(true);
    var c = {id: 'c' + (nextId++), el: node, out: node.querySelector('.pg-output'),
             countEl: node.querySelector('.pg-cell-count'), chars: 0};
    var idx = after ? cells.indexOf(after) + 1 : cells.length;
    if (idx <= 0 || idx >= cells.length) cellsEl.appendChild(node);
    else cellsEl.insertBefore(node, cells[idx].el);
    cells.splice(idx > 0 ? idx : cells.length, 0, c);
    c.editor = window.SajhaEditor.create(node.querySelector('.pg-editor'), code || '', {
      onRun: function (shift) {
        enqueue(c);
        if (shift) {
          var i = cells.indexOf(c);
          (cells[i + 1] || addCell('', c)).editor.focus();
        }
      },
      onChange: saveDraftSoon,
      label: 'Python code, cell',
    });
    node.querySelector('.pg-cell-run').addEventListener('click', function () { enqueue(c); });
    node.querySelector('.pg-cell-del').addEventListener('click', function () { deleteCell(c); });
    node.querySelector('.pg-cell-up').addEventListener('click', function () { moveCell(c, -1); });
    node.querySelector('.pg-cell-down').addEventListener('click', function () { moveCell(c, 1); });
    saveDraftSoon();
    return c;
  }

  function deleteCell(c) {
    if (running === c) return;
    var i = cells.indexOf(c);
    if (i < 0) return;
    queue = queue.filter(function (q) { return q !== c; });
    c.editor.destroy();
    c.el.remove();
    cells.splice(i, 1);
    if (!cells.length) addCell('');
    saveDraftSoon();
  }

  function moveCell(c, d) {
    var i = cells.indexOf(c), j = i + d;
    if (j < 0 || j >= cells.length) return;
    cells.splice(i, 1);
    cells.splice(j, 0, c);
    if (d < 0) cellsEl.insertBefore(c.el, cells[j + 1].el);
    else cellsEl.insertBefore(c.el, cells[j].el.nextSibling);
    saveDraftSoon();
  }

  function sources() { return cells.map(function (c) { return c.editor.getValue(); }); }

  function setNotebook(list) {
    cells.slice().forEach(function (c) { c.editor.destroy(); c.el.remove(); });
    cells = []; queue = [];
    (list && list.length ? list : ['']).forEach(function (s) { addCell(String(s)); });
  }

  function isBlank() { return sources().every(function (s) { return !s.trim(); }); }

  // ── files ──────────────────────────────────────────────────────────────────
  function toPy(list) {
    return '# SAJHA Python Playground notebook\n' +
           list.map(function (s) { return '# %%\n' + s.replace(/\s+$/, '') + '\n'; }).join('\n');
  }

  function fromPy(text) {
    var parts = text.split(/^# ?%%.*$/m).map(function (s) { return s.replace(/^\n+|\s+$/g, ''); });
    if (parts.length > 1 && /^# SAJHA Python Playground notebook\s*$/.test(parts[0])) parts.shift();
    parts = parts.filter(function (s) { return s.length; });
    return parts.length ? parts : [text];
  }

  function fromIpynb(text) {
    var nb = JSON.parse(text);
    var out = (nb.cells || []).filter(function (c) { return c.cell_type === 'code'; }).map(function (c) {
      return Array.isArray(c.source) ? c.source.join('') : String(c.source || '');
    });
    if (!out.length) throw new Error('the notebook has no code cells');
    return out;
  }

  function download() {
    var blob = new Blob([toPy(sources())], {type: 'text/x-python'});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'playground.py';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  }

  function upload(file) {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { flash('That file is larger than 2 MB.'); return; }
    var r = new FileReader();
    r.onload = function () {
      try {
        var list = /\.ipynb$/i.test(file.name) ? fromIpynb(String(r.result)) : fromPy(String(r.result));
        if (!isBlank() && !window.confirm('Replace the current cells with ' + file.name + '?')) return;
        setNotebook(list);
        flash('Opened ' + file.name + ' (' + list.length + ' cell' + (list.length === 1 ? '' : 's') + ').');
      } catch (e) { flash('Could not open ' + file.name + ': ' + e.message); }
    };
    r.readAsText(file);
  }

  function flash(text) { setStatus(ready ? 'ready' : (worker ? 'loading' : 'idle'), text); }

  // ── MCP Studio hand-off ────────────────────────────────────────────────────
  function sampleArg(type) {
    type = (type || '').trim();
    if (/^int\b/.test(type)) return '1';
    if (/^float\b/.test(type)) return '1.0';
    if (/^bool\b/.test(type)) return 'True';
    if (/^str\b/.test(type)) return '"text"';
    if (/^(list|List)\b/.test(type)) return '[]';
    if (/^(dict|Dict)\b/.test(type)) return '{}';
    return 'None';
  }

  function testCall(code) {
    var m = /@sajhamcptool[\s\S]*?def\s+([A-Za-z_]\w*)\s*\(([\s\S]*?)\)\s*(->[^:]*)?:/.exec(code) ||
            /def\s+([A-Za-z_]\w*)\s*\(([\s\S]*?)\)\s*(->[^:]*)?:/.exec(code);
    if (!m) return '# Call your function here to try it.';
    var args = [];
    m[2].split(',').forEach(function (p) {
      p = p.trim();
      if (!p || p === 'self' || p.charAt(0) === '*' || p.indexOf('=') >= 0) return;   // keep defaults
      var name = p.split(':')[0].trim(), type = p.indexOf(':') >= 0 ? p.split(':')[1] : '';
      args.push(name + '=' + sampleArg(type));
    });
    return '# Try the tool function here (edit the arguments), as the server would call it.\n' +
           m[1] + '(' + args.join(', ') + ')';
  }

  function takeImport() {
    var raw = load(KEY_IMPORT);
    if (!raw) return null;
    drop(KEY_IMPORT);
    try {
      var d = JSON.parse(raw);
      if (!d || typeof d.code !== 'string' || !d.code.trim()) return null;
      if (d.at && Date.now() - d.at > 10 * 60 * 1000) return null;       // stale hand-off
      return [d.code, testCall(d.code)];
    } catch (e) { return null; }
  }

  // ── wiring ─────────────────────────────────────────────────────────────────
  function example(id) {
    var ex = (DATA.examples || []).filter(function (e) { return e.id === id; })[0];
    if (!ex) return;
    if (!isBlank() && !window.confirm('Replace the current cells with the "' + ex.title + '" example?')) return;
    setNotebook(ex.cells);
    cells[0].editor.focus();
  }

  btnRunAll.addEventListener('click', function () { cells.forEach(enqueue); });
  btnStop.addEventListener('click', stop);
  btnReset.addEventListener('click', reset);
  $('pgAddCell').addEventListener('click', function () { addCell('').editor.focus(); });
  $('pgExamples').addEventListener('change', function () { example(this.value); this.value = ''; });
  $('pgSave').addEventListener('click', function () {
    flash(store(KEY_SAVED, JSON.stringify(sources())) ? 'Saved in this browser.' : 'This browser does not allow saving here.');
  });
  $('pgLoad').addEventListener('click', function () {
    var raw = load(KEY_SAVED), list = null;
    try { list = raw ? JSON.parse(raw) : null; } catch (e) { list = null; }
    if (!Array.isArray(list)) { flash('Nothing saved in this browser yet.'); return; }
    if (!isBlank() && !window.confirm('Replace the current cells with the saved notebook?')) return;
    setNotebook(list);
    flash('Loaded the saved notebook.');
  });
  $('pgDownload').addEventListener('click', download);
  $('pgUpload').addEventListener('change', function () { upload(this.files && this.files[0]); this.value = ''; });

  // First content: a hand-off from MCP Studio, else the last draft, else the first example.
  var initial = takeImport(), draft = null;
  if (!initial) {
    try { draft = JSON.parse(load(KEY_DRAFT) || 'null'); } catch (e) { draft = null; }
    if (Array.isArray(draft) && draft.some(function (s) { return String(s).trim(); })) initial = draft;
  }
  if (!initial) {
    var first = (DATA.examples || [])[0];
    initial = first ? first.cells : ['print("Hello from Python in your browser")'];
  }
  if (!window.SajhaEditor) { setStatus('error', 'The editor did not load'); return; }
  setNotebook(initial);
  startWorker();
  setBusy();

  // Exposed for the browser checks in tests (no secrets here).
  window.SajhaPlayground = {
    run: function (i) { enqueue(cells[i || 0]); }, runAll: function () { cells.forEach(enqueue); },
    stop: stop, reset: reset, cells: function () { return cells; }, setNotebook: setNotebook,
    isolated: function () { return !!interrupt; }, ready: function () { return ready; },
    busy: function () { return !!running || queue.length > 0; },
  };
})();
