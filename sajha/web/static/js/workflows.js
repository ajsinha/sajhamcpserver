/*
 * SAJHA Workflows page: list, edit (form, JSON, YAML), graph, run, run history and step timeline.
 * The definition object `cur` is the single model; every view renders from it and writes back to it.
 * Design: docs/architecture/Workflows.md
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
 */
(function () {
  'use strict';
  var TOOLS = window.WF_TOOLS || [];
  var cur = null;          // the definition being edited
  var loaded = null;       // the saved workflow record (null for a new one)
  var tab = 'form';
  var pollTimer = null;
  var openRun = null;

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function fmtTime(t) { if (!t) return '—'; var d = new Date(t * 1000); return d.toLocaleString(); }
  function fmtDur(ms) { if (ms == null) return '—'; if (ms < 1000) return Math.round(ms) + ' ms'; if (ms < 60000) return (ms / 1000).toFixed(1) + ' s'; return (ms / 60000).toFixed(1) + ' min'; }
  function pill(s) { return '<span class="wf-pill s-' + esc(s) + '">' + esc(s) + '</span>'; }
  function alertMsg(kind, text) {
    $('wfAlert').innerHTML = text ? '<div class="alert alert-' + kind + ' alert-dismissible" role="alert">' + esc(text) +
      '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button></div>' : '';
  }
  function api(method, url, body, raw) {
    var opts = {method: method, headers: {'Accept': 'application/json'}, credentials: 'same-origin'};
    if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    return fetch(url, opts).then(function (r) {
      if (raw) return r;
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { var e = new Error(j.error || ('HTTP ' + r.status)); e.status = r.status; throw e; }
        return j;
      });
    });
  }

  function blank() {
    return {name: '', description: '', steps: [{id: 'step1', kind: 'tool', tool: TOOLS[0] || '', params: {}}], triggers: []};
  }

  // ── form <-> model ─────────────────────────────────────────────
  var FORM_KEYS = {
    tool: ['id', 'kind', 'tool', 'params', 'depends_on', 'retry', 'timeout_seconds'],
    composite: ['id', 'kind', 'tool', 'params', 'depends_on', 'retry', 'timeout_seconds'],
    ask: ['id', 'kind', 'question', 'depends_on', 'retry', 'timeout_seconds'],
    condition: ['id', 'kind', 'if', 'then', 'else', 'depends_on'],
    foreach: ['id', 'kind', 'items', 'do', 'max_items', 'parallel', 'depends_on'],
    wait: ['id', 'kind', 'seconds', 'depends_on'],
    approval: ['id', 'kind', 'reason', 'depends_on']
  };
  function extraOf(step) {
    var keep = FORM_KEYS[step.kind] || [], out = {};
    Object.keys(step).forEach(function (k) {
      if (keep.indexOf(k) < 0 && !(k === 'join' && step[k] === 'all_success') && !(k === 'on_error' && step[k] === 'fail')) out[k] = step[k];
    });
    return out;
  }
  function toolOptions(sel) {
    var has = TOOLS.indexOf(sel) >= 0;
    return (has || !sel ? '' : '<option selected>' + esc(sel) + '</option>') + TOOLS.map(function (t) {
      return '<option' + (t === sel ? ' selected' : '') + '>' + esc(t) + '</option>';
    }).join('');
  }
  function field(label, html, cls) { return '<div class="' + (cls || 'col-md-6') + '"><label class="form-label small fw-bold mb-0">' + label + '</label>' + html + '</div>'; }
  function json(v) { return v === undefined ? '' : JSON.stringify(v); }

  function renderSteps() {
    var box = $('wfSteps');
    box.innerHTML = (cur.steps || []).map(function (s, i) {
      var k = s.kind, h = '<div class="wf-step" data-i="' + i + '"><div class="d-flex justify-content-between align-items-center mb-1">' +
        '<strong>' + (i + 1) + '. <span class="text-muted small">' + esc(k) + '</span></strong>' +
        '<span><button type="button" class="btn btn-sm btn-link p-1" data-act="up" aria-label="Move step up"><i class="bi bi-arrow-up" aria-hidden="true"></i></button>' +
        '<button type="button" class="btn btn-sm btn-link p-1 text-danger" data-act="del" aria-label="Remove step ' + esc(s.id) + '"><i class="bi bi-x-lg" aria-hidden="true"></i></button></span></div><div class="row g-2">';
      h += field('Id', '<input class="form-control form-control-sm" data-f="id" value="' + esc(s.id) + '">', 'col-6 col-md-4');
      h += field('Depends on', '<input class="form-control form-control-sm" data-f="depends_on" placeholder="ids, comma separated" value="' + esc((s.depends_on || []).join(', ')) + '">', 'col-6 col-md-8');
      if (k === 'tool' || k === 'composite') {
        h += field('Tool', '<select class="form-select form-select-sm" data-f="tool">' + toolOptions(s.tool) + '</select>', 'col-md-5');
        h += field('Params <small class="text-muted">(JSON; "$input.x", "$steps.id.field")</small>', '<textarea class="form-control form-control-sm" rows="2" data-f="params" data-json="1">' + esc(json(s.params || {})) + '</textarea>', 'col-md-7');
      } else if (k === 'ask') {
        h += field('Question <small class="text-muted">({{$steps.id}} inserts a value)</small>', '<textarea class="form-control form-control-sm" rows="2" data-f="question">' + esc(s.question || '') + '</textarea>', 'col-12');
      } else if (k === 'condition') {
        h += field('If', '<input class="form-control form-control-sm" data-f="if" data-maybejson="1" placeholder="$steps.a.count > 0" value="' + esc(typeof s['if'] === 'string' ? s['if'] : json(s['if'])) + '">', 'col-md-6');
        h += field('Then (ids)', '<input class="form-control form-control-sm" data-f="then" value="' + esc((s.then || []).join(', ')) + '">', 'col-6 col-md-3');
        h += field('Else (ids)', '<input class="form-control form-control-sm" data-f="else" value="' + esc((s['else'] || []).join(', ')) + '">', 'col-6 col-md-3');
      } else if (k === 'foreach') {
        h += field('Items', '<input class="form-control form-control-sm" data-f="items" placeholder="$steps.list.rows" value="' + esc(typeof s.items === 'string' ? s.items : json(s.items)) + '">', 'col-md-4');
        h += field('Max items', '<input class="form-control form-control-sm" type="number" min="1" data-f="max_items" data-num="1" value="' + esc(s.max_items || '') + '">', 'col-6 col-md-2');
        h += field('Parallel', '<input class="form-control form-control-sm" type="number" min="1" data-f="parallel" data-num="1" value="' + esc(s.parallel || 1) + '">', 'col-6 col-md-2');
        h += field('Do <small class="text-muted">(JSON: {"tool": ..., "params": {"x": "$item.x"}})</small>', '<textarea class="form-control form-control-sm" rows="2" data-f="do" data-json="1">' + esc(json(s['do'] || {kind: 'tool', tool: TOOLS[0] || '', params: {}})) + '</textarea>', 'col-md-4');
      } else if (k === 'wait') {
        h += field('Seconds', '<input class="form-control form-control-sm" data-f="seconds" data-num="1" value="' + esc(s.seconds == null ? '' : s.seconds) + '">', 'col-6 col-md-4');
      } else if (k === 'approval') {
        h += field('Reason shown to the approver', '<input class="form-control form-control-sm" data-f="reason" value="' + esc(s.reason || '') + '">', 'col-12');
      }
      if (['tool', 'composite', 'ask'].indexOf(k) >= 0) {
        var r = s.retry || {};
        h += field('Attempts', '<input class="form-control form-control-sm" type="number" min="1" max="20" data-f="retry.max_attempts" data-num="1" value="' + esc(r.max_attempts || 1) + '">', 'col-4 col-md-2');
        h += field('Backoff (s)', '<input class="form-control form-control-sm" type="number" min="0" step="any" data-f="retry.backoff_seconds" data-num="1" value="' + esc(r.backoff_seconds == null ? 1 : r.backoff_seconds) + '">', 'col-4 col-md-2');
        h += field('Timeout (s)', '<input class="form-control form-control-sm" type="number" min="0" step="any" data-f="timeout_seconds" data-num="1" value="' + esc(s.timeout_seconds || '') + '">', 'col-4 col-md-2');
      }
      var extra = extraOf(s);
      h += field('More <small class="text-muted">(JSON: join, on_error, when, idempotent, ...)</small>', '<input class="form-control form-control-sm" data-f="_extra" data-json="1" value="' + esc(Object.keys(extra).length ? json(extra) : '') + '">', 'col-md-6');
      return h + '</div></div>';
    }).join('') || '<p class="text-muted small">No steps yet.</p>';
  }

  function splitIds(v) { return String(v || '').split(',').map(function (x) { return x.trim(); }).filter(Boolean); }

  function readSteps() {
    var steps = [];
    var problems = [];
    document.querySelectorAll('#wfSteps .wf-step').forEach(function (el) {
      var i = +el.getAttribute('data-i'), old = cur.steps[i] || {}, s = {kind: old.kind};
      el.querySelectorAll('[data-f]').forEach(function (inp) {
        var f = inp.getAttribute('data-f'), v = inp.value;
        if (f === 'depends_on' || f === 'then' || f === 'else') { s[f] = splitIds(v); return; }
        if (inp.hasAttribute('data-json')) {
          if (!v.trim()) { if (f !== '_extra') s[f] = {}; return; }
          try { var parsed = JSON.parse(v); if (f === '_extra') Object.assign(s, parsed); else s[f] = parsed; }
          catch (e) { problems.push('step ' + (old.id || i + 1) + ': ' + f + ' is not valid JSON'); s[f] = old[f]; }
          return;
        }
        if (inp.hasAttribute('data-maybejson')) { try { s[f] = JSON.parse(v); } catch (e) { s[f] = v; } return; }
        if (inp.hasAttribute('data-num')) {
          if (v === '') return;
          var n = Number(v); var val = isNaN(n) ? v : n;
          if (f.indexOf('retry.') === 0) { s.retry = s.retry || {}; s.retry[f.slice(6)] = val; } else { s[f] = val; }
          return;
        }
        s[f] = v;
      });
      if (s.retry) {
        var r = Object.assign({}, old.retry || {}, s.retry);
        if (!old.retry && r.max_attempts === 1 && (r.backoff_seconds == null || r.backoff_seconds === 1)) delete s.retry; else s.retry = r;
      }
      if (!s.depends_on || !s.depends_on.length) delete s.depends_on;
      steps.push(s);
    });
    cur.steps = steps;
    return problems;
  }

  function readHeader() {
    cur.name = $('wfName').value.trim();
    cur.description = $('wfDesc').value;
    ['concurrency:wfConc', 'max_parallel:wfPar', 'timeout_seconds:wfTimeout'].forEach(function (p) {
      var k = p.split(':')[0], v = $(p.split(':')[1]).value;
      if (v === '') delete cur[k]; else cur[k] = Number(v);
    });
    if ($('wfPublish').checked) cur.publish = Object.assign({}, cur.publish || {}, {enabled: true});
    else if (cur.publish) cur.publish.enabled = false;
    var dt = $('wfDelType').value;
    if (dt) cur.delivery = Object.assign({}, cur.delivery || {}, {type: dt, destination: $('wfDelDest').value.trim()});
    else delete cur.delivery;
  }
  function renderHeader() {
    $('wfName').value = cur.name || '';
    $('wfName').disabled = !!loaded;
    $('wfDesc').value = cur.description || '';
    $('wfConc').value = cur.concurrency || '';
    $('wfPar').value = cur.max_parallel || '';
    $('wfTimeout').value = cur.timeout_seconds || '';
    $('wfPublish').checked = !!(cur.publish && cur.publish.enabled);
    $('wfDelType').value = (cur.delivery && cur.delivery.type) || '';
    $('wfDelDest').value = (cur.delivery && cur.delivery.destination) || '';
  }

  // ── triggers ───────────────────────────────────────────────────
  function renderTriggers() {
    var base = location.origin;
    $('wfTriggers').innerHTML = (cur.triggers || []).map(function (t, i) {
      var h = '<div class="wf-step" data-t="' + i + '"><div class="d-flex justify-content-between align-items-center mb-1"><strong>' + esc(t.type) + '</strong>' +
        '<button type="button" class="btn btn-sm btn-link p-1 text-danger" data-tact="del" aria-label="Remove trigger ' + esc(t.id || '') + '"><i class="bi bi-x-lg" aria-hidden="true"></i></button></div><div class="row g-2">';
      h += field('Id', '<input class="form-control form-control-sm" data-tf="id" value="' + esc(t.id || '') + '">', 'col-6 col-md-3');
      h += field('Enabled', '<select class="form-select form-select-sm" data-tf="enabled"><option value="true"' + (t.enabled !== false ? ' selected' : '') + '>yes</option><option value="false"' + (t.enabled === false ? ' selected' : '') + '>no</option></select>', 'col-6 col-md-2');
      if (t.type === 'cron') {
        h += field('Cron <small class="text-muted">(min hour day month weekday)</small>', '<input class="form-control form-control-sm" data-tf="cron" placeholder="0 6 * * 1-5" value="' + esc(t.cron || '') + '">', 'col-md-4');
        h += field('Timezone', '<input class="form-control form-control-sm" data-tf="timezone" placeholder="UTC" value="' + esc(t.timezone || '') + '">', 'col-md-3');
      } else if (t.type === 'webhook') {
        h += field('Secret', '<input class="form-control form-control-sm" data-tf="secret" autocomplete="off" placeholder="generated on save" value="' + esc(t.secret || '') + '">', 'col-md-3');
        h += '<div class="col-12 small text-muted">POST ' + esc(base) + '/api/workflows/' + esc(cur.name || '{name}') + '/hooks/' + esc(t.id || '{id}') + ' with headers X-Sajha-Timestamp and X-Sajha-Signature: sha256=HMAC(secret, timestamp + "." + body)</div>';
      } else if (t.type === 'file') {
        h += field('Prefix', '<input class="form-control form-control-sm" data-tf="prefix" placeholder="data/inbox" value="' + esc(t.prefix || '') + '">', 'col-md-3');
        h += field('Pattern', '<input class="form-control form-control-sm" data-tf="pattern" placeholder="*.csv" value="' + esc(t.pattern || '*') + '">', 'col-6 col-md-2');
        h += field('Every (s)', '<input class="form-control form-control-sm" type="number" min="1" data-tf="interval_seconds" data-num="1" value="' + esc(t.interval_seconds || 30) + '">', 'col-6 col-md-2');
      } else if (t.type === 'event') {
        h += field('Kinds', '<input class="form-control form-control-sm" data-tf="kinds" placeholder="tools, prompts" value="' + esc((t.kinds || ['tools']).join(', ')) + '">', 'col-md-4');
        h += field('Resource URI', '<input class="form-control form-control-sm" data-tf="uri" value="' + esc(t.uri || '') + '">', 'col-md-3');
      }
      h += field('Input <small class="text-muted">(JSON)</small>', '<input class="form-control form-control-sm" data-tf="input" data-json="1" value="' + esc(t.input ? json(t.input) : '') + '">', 'col-12');
      return h + '</div></div>';
    }).join('') || '<p class="text-muted small">No triggers: run it by hand.</p>';
  }
  function readTriggers() {
    var out = [], problems = [];
    document.querySelectorAll('#wfTriggers [data-t]').forEach(function (el) {
      var old = cur.triggers[+el.getAttribute('data-t')] || {}, t = Object.assign({}, old);
      el.querySelectorAll('[data-tf]').forEach(function (inp) {
        var f = inp.getAttribute('data-tf'), v = inp.value;
        if (f === 'enabled') t.enabled = v === 'true';
        else if (f === 'kinds') t.kinds = splitIds(v);
        else if (inp.hasAttribute('data-json')) { if (!v.trim()) delete t[f]; else { try { t[f] = JSON.parse(v); } catch (e) { problems.push('trigger ' + (t.id || '') + ': input is not valid JSON'); } } }
        else if (inp.hasAttribute('data-num')) t[f] = Number(v);
        else if (v === '') delete t[f]; else t[f] = v;
      });
      out.push(t);
    });
    cur.triggers = out;
    return problems;
  }

  // ── the graph ──────────────────────────────────────────────────
  function drawDag(statuses) {
    var svg = $('wfDag'), steps = (cur && cur.steps) || [];
    var ids = steps.map(function (s) { return s.id; });
    var deps = {}, branch = {};
    steps.forEach(function (s) {
      deps[s.id] = (s.depends_on || []).slice();
      [].concat(s.then || [], s['else'] || []).forEach(function (b) { (branch[b] = branch[b] || []).push(s.id); if (deps[b] && deps[b].indexOf(s.id) < 0) deps[b].push(s.id); });
      var text = JSON.stringify([s.params, s.question, s.items, s['do'], s.when, s['if']]);
      (text.match(/\$steps\.([A-Za-z][A-Za-z0-9_]*)/g) || []).forEach(function (m) { var d = m.slice(7); if (d !== s.id && deps[s.id].indexOf(d) < 0 && ids.indexOf(d) >= 0) deps[s.id].push(d); });
    });
    steps.forEach(function (s) { (branch[s.id] || []).forEach(function (c) { if (deps[s.id].indexOf(c) < 0) deps[s.id].push(c); }); });
    var level = {}, guard = 0;
    function lv(id, seen) { if (level[id] != null) return level[id]; if (seen[id] || ++guard > 5000) return 0; seen[id] = 1; var m = 0; (deps[id] || []).forEach(function (d) { if (ids.indexOf(d) >= 0) m = Math.max(m, lv(d, seen) + 1); }); level[id] = m; return m; }
    ids.forEach(function (id) { lv(id, {}); });
    var cols = {}; ids.forEach(function (id) { (cols[level[id]] = cols[level[id]] || []).push(id); });
    var W = 160, H = 48, GX = 50, GY = 18, pos = {}, maxRows = 1, nCols = 0;
    Object.keys(cols).forEach(function (c) { cols[c].forEach(function (id, r) { pos[id] = {x: 10 + c * (W + GX), y: 10 + r * (H + GY)}; }); maxRows = Math.max(maxRows, cols[c].length); nCols = Math.max(nCols, +c + 1); });
    var width = Math.max(300, 20 + nCols * (W + GX) - GX), height = Math.max(64, 20 + maxRows * (H + GY) - GY);
    svg.setAttribute('width', width); svg.setAttribute('height', height); svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    var parts = ['<defs><marker id="wfArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>'];
    ids.forEach(function (id) {
      (deps[id] || []).forEach(function (d) {
        if (!pos[d]) return;
        var a = pos[d], b = pos[id], x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2, mx = (x1 + x2) / 2;
        var isBranch = (branch[id] || []).indexOf(d) >= 0;
        parts.push('<path class="wf-edge' + (isBranch ? ' branch' : '') + '" marker-end="url(#wfArrow)" d="M' + x1 + ',' + y1 + ' C' + mx + ',' + y1 + ' ' + mx + ',' + y2 + ' ' + x2 + ',' + y2 + '"/>');
      });
    });
    steps.forEach(function (s) {
      var p = pos[s.id]; if (!p) return;
      var st = statuses && statuses[s.id] ? ' st-' + statuses[s.id] : '';
      var label = s.id.length > 18 ? s.id.slice(0, 17) + '…' : s.id;
      var sub = s.kind + (s.tool ? ': ' + s.tool : '');
      if (sub.length > 21) sub = sub.slice(0, 20) + '…';
      parts.push('<g class="wf-node' + st + '"><title>' + esc(s.id + ' (' + s.kind + ')' + (statuses && statuses[s.id] ? ': ' + statuses[s.id] : '')) + '</title><rect x="' + p.x + '" y="' + p.y + '" rx="8" width="' + W + '" height="' + H + '"/>' +
        '<text x="' + (p.x + 8) + '" y="' + (p.y + 18) + '">' + esc(label) + '</text><text class="wf-kind" x="' + (p.x + 8) + '" y="' + (p.y + 37) + '">' + esc(sub) + '</text></g>');
    });
    svg.innerHTML = parts.join('');
    svg.style.color = getComputedStyle(document.documentElement).getPropertyValue('--sajha-slate') || '#6B7480';
  }

  // ── tabs ───────────────────────────────────────────────────────
  function collect() {
    var problems = [];
    if (tab === 'form' || tab === 'triggers') { readHeader(); problems = problems.concat(readSteps(), readTriggers()); }
    else if (tab === 'json') { try { cur = JSON.parse($('wfJson').value); } catch (e) { problems.push('the JSON does not parse: ' + e.message); } }
    return problems;
  }
  function showTab(name) {
    var problems = collect();
    if (problems.length) { alertMsg('danger', problems.join('; ')); return Promise.resolve(); }
    var go = Promise.resolve();
    if (tab === 'yaml' && name !== 'yaml') {
      go = api('POST', '/api/workflows/validate', {text: $('wfYaml').value}).then(function (j) { cur = mergeSecrets(j.definition); })
        .catch(function (e) { alertMsg('danger', 'YAML: ' + e.message); throw e; });
    }
    return go.then(function () {
      tab = name;
      document.querySelectorAll('[data-wf-tab]').forEach(function (b) { var on = b.getAttribute('data-wf-tab') === name; b.classList.toggle('active', on); b.setAttribute('aria-selected', on); });
      document.querySelectorAll('[data-wf-pane]').forEach(function (p) { p.hidden = p.getAttribute('data-wf-pane') !== name; });
      renderAll();
      if (name === 'yaml') {
        $('wfYaml').value = '# loading...';
        api('POST', '/api/workflows/validate', cur).then(function (j) { $('wfYaml').value = j.yaml; })
          .catch(function (e) { $('wfYaml').value = '# ' + e.message + '\n' + JSON.stringify(cur, null, 2); });
      }
    }).catch(function () {});
  }
  function mergeSecrets(defn) {
    // the server masks secrets; keep what we had so a round trip does not lose them
    var old = {}; (cur.triggers || []).forEach(function (t) { old[t.id] = t.secret; });
    (defn.triggers || []).forEach(function (t) { if (t.secret === '********' && old[t.id]) t.secret = old[t.id]; });
    return defn;
  }
  function renderAll() {
    if (tab === 'form' || tab === 'triggers') { renderHeader(); renderSteps(); renderTriggers(); }
    if (tab === 'json') $('wfJson').value = JSON.stringify(cur, null, 2);
    drawDag(openRun && openRun.workflow === cur.name ? stepStatuses(openRun) : null);
  }

  // ── list, load, save ───────────────────────────────────────────
  function loadList(select) {
    return api('GET', '/api/workflows').then(function (j) {
      var rows = j.workflows || [];
      $('wfList').innerHTML = rows.map(function (w) {
        var trig = (w.triggers || []).map(function (t) { return t.type; }).join(', ') || 'manual';
        return '<button type="button" class="list-group-item list-group-item-action' + (loaded && loaded.name === w.name ? ' active' : '') + '" data-name="' + esc(w.name) + '">' +
          '<div class="d-flex justify-content-between gap-2"><strong>' + esc(w.name) + '</strong>' + (w.enabled ? '' : pill('disabled')) + (w.published ? ' <span class="wf-pill">tool</span>' : '') + '</div>' +
          '<div class="wf-meta">' + esc(w.steps) + ' steps · ' + esc(trig) + ' · v' + esc(w.version) + ' · owner ' + esc(w.owner) + '</div></button>';
      }).join('') || '<div class="p-3 text-muted small">No workflows yet. Use New workflow.</div>';
      if (select) open(select);
    }).catch(function (e) { $('wfList').innerHTML = '<div class="p-3 wf-err">' + esc(e.message) + '</div>'; });
  }
  function open(name) {
    return api('GET', '/api/workflows/' + encodeURIComponent(name)).then(function (w) {
      loaded = w; cur = w.definition; openRun = null; $('wfRunCard').hidden = true;
      $('wfTitle').textContent = w.name;
      $('wfInfo').textContent = 'v' + w.version + ' · owner ' + w.owner + ' · ' + (w.enabled ? 'enabled' : 'disabled');
      ['wfRun', 'wfDelete', 'wfToggle'].forEach(function (id) { $(id).disabled = false; });
      $('wfToggle').textContent = w.enabled ? 'Disable' : 'Enable';
      $('wfRunInputWrap').hidden = false;
      document.querySelectorAll('#wfList [data-name]').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-name') === name); });
      renderAll(); loadRuns();
    }).catch(function (e) { alertMsg('danger', e.message); });
  }
  function newWf() {
    loaded = null; cur = blank(); openRun = null;
    $('wfTitle').textContent = 'New workflow'; $('wfInfo').textContent = '';
    ['wfRun', 'wfDelete', 'wfToggle'].forEach(function (id) { $(id).disabled = true; });
    $('wfRunInputWrap').hidden = true; $('wfRunCard').hidden = true;
    $('wfRuns').innerHTML = '<tr><td colspan="5" class="text-muted small">Save the workflow to run it.</td></tr>';
    renderAll();
  }
  function payload() {
    if (tab === 'yaml') return {text: $('wfYaml').value};
    var problems = collect();
    if (problems.length) throw new Error(problems.join('; '));
    return cur;
  }
  function save() {
    var body;
    try { body = payload(); } catch (e) { alertMsg('danger', e.message); return; }
    var name = loaded ? loaded.name : null;
    api(name ? 'PUT' : 'POST', name ? '/api/workflows/' + encodeURIComponent(name) : '/api/workflows', body).then(function (j) {
      alertMsg('success', 'Saved ' + j.workflow.name + ' (version ' + j.workflow.version + ').');
      loadList(j.workflow.name);
    }).catch(function (e) { alertMsg('danger', e.message); });
  }
  function validate() {
    var body;
    try { body = payload(); } catch (e) { alertMsg('danger', e.message); return; }
    api('POST', '/api/workflows/validate', body).then(function (j) {
      alertMsg('success', 'Valid. Order: ' + j.order.join(' → '));
    }).catch(function (e) { alertMsg('danger', e.message); });
  }

  // ── runs ───────────────────────────────────────────────────────
  function loadRuns() {
    if (!loaded) return;
    api('GET', '/api/workflows/' + encodeURIComponent(loaded.name) + '/runs?limit=30').then(function (j) {
      var rows = j.runs || [];
      $('wfRuns').innerHTML = rows.map(function (r) {
        var dur = r.finished_at && r.started_at ? (r.finished_at - r.started_at) * 1000 : null;
        var active = ['queued', 'running', 'waiting'].indexOf(r.status) >= 0;
        return '<tr><td>' + esc(fmtTime(r.created_at)) + '</td><td>' + esc(r.trigger_type) + (r.trigger_id ? '<div class="wf-meta">' + esc(r.trigger_id) + '</div>' : '') + '</td><td>' + pill(r.status) + '</td><td>' + esc(fmtDur(dur)) + '</td>' +
          '<td class="text-nowrap"><button type="button" class="btn btn-sm btn-outline-primary" data-run="' + esc(r.id) + '" aria-label="Show run ' + esc(r.id) + '">Steps</button> ' +
          (active ? '<button type="button" class="btn btn-sm btn-outline-danger" data-cancel="' + esc(r.id) + '">Cancel</button>' :
            (r.status !== 'succeeded' ? '<button type="button" class="btn btn-sm btn-outline-secondary" data-rerun="' + esc(r.id) + '">Re-run</button>' : '')) + '</td></tr>';
      }).join('') || '<tr><td colspan="5" class="text-muted small">No runs yet.</td></tr>';
      if (rows.some(function (r) { return ['queued', 'running', 'waiting'].indexOf(r.status) >= 0; })) schedulePoll();
    }).catch(function (e) { $('wfRuns').innerHTML = '<tr><td colspan="5" class="wf-err">' + esc(e.message) + '</td></tr>'; });
  }
  function schedulePoll() {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(function () { loadRuns(); if (openRun) showRun(openRun.id, true); }, 2500);
  }
  function stepStatuses(run) { var m = {}; (run.steps || []).forEach(function (s) { m[s.step_id] = s.status; }); return m; }
  function showRun(id, quiet) {
    api('GET', '/api/workflows/runs/' + encodeURIComponent(id)).then(function (j) {
      var r = j.run; openRun = r;
      $('wfRunCard').hidden = false;
      $('wfRunId').textContent = r.id;
      $('wfRunStatus').innerHTML = pill(r.status);
      $('wfRunMeta').textContent = 'trigger ' + r.trigger_type + (r.trigger_id ? ' (' + r.trigger_id + ')' : '') + ' · run as ' + r.run_as +
        (r.started_by ? ' · started by ' + r.started_by : '') + ' · version ' + r.version + (r.parent_run_id ? ' · re-run of ' + r.parent_run_id : '') +
        (r.delivery_status ? ' · delivery ' + r.delivery_status : '');
      $('wfRunErr').textContent = r.error || '';
      $('wfRunOut').textContent = r.output == null ? '' : JSON.stringify(r.output, null, 2);
      var t0 = r.started_at || r.created_at, t1 = r.finished_at || Date.now() / 1000;
      (r.steps || []).forEach(function (s) { if (s.started_at) t0 = Math.min(t0, s.started_at); if (s.finished_at) t1 = Math.max(t1, s.finished_at); });
      var span = Math.max(0.001, t1 - t0);
      $('wfTimeline').innerHTML = (r.steps || []).map(function (s) {
        var left = s.started_at ? ((s.started_at - t0) / span) * 100 : 0;
        var end = s.finished_at || (s.status === 'running' || s.status === 'waiting' ? Date.now() / 1000 : s.started_at);
        var width = s.started_at ? Math.max(0.5, ((end - s.started_at) / span) * 100) : 0;
        var io = '';
        if (s.input != null) io += '<details><summary class="small">input</summary><pre class="wf-io">' + esc(JSON.stringify(s.input, null, 2)) + '</pre></details>';
        if (s.output != null) io += '<details><summary class="small">output</summary><pre class="wf-io">' + esc(JSON.stringify(s.output, null, 2)) + '</pre></details>';
        if (s.status === 'waiting' && s.detail && s.detail.approval_id) io += '<div class="wf-meta">waiting for approval <code>' + esc(s.detail.approval_id) + '</code> (Admin › Approvals)</div>';
        if (s.status === 'waiting' && s.detail && s.detail.wake_at) io += '<div class="wf-meta">wakes at ' + esc(fmtTime(s.detail.wake_at)) + '</div>';
        return '<div class="wf-tl-row"><div><strong>' + esc(s.step_id) + '</strong> <span class="wf-meta">' + esc(s.kind) + '</span><div>' + pill(s.status) +
          ' <span class="wf-meta">' + esc(fmtDur(s.duration_ms)) + (s.attempts > 1 ? ' · ' + s.attempts + ' attempts' : '') + '</span></div></div>' +
          '<div><div class="wf-tl-track" aria-hidden="true"><div class="wf-tl-bar s-' + esc(s.status) + '" style="left:' + left.toFixed(2) + '%;width:' + Math.min(100 - left, width).toFixed(2) + '%"></div></div>' +
          (s.error ? '<div class="wf-err">' + esc(s.error) + '</div>' : '') + io + '</div></div>';
      }).join('') || '<p class="text-muted small">No steps recorded yet.</p>';
      if (cur && cur.name === r.workflow) drawDag(stepStatuses(r));
      if (['queued', 'running', 'waiting'].indexOf(r.status) >= 0) schedulePoll();
      if (!quiet) $('wfRunCard').scrollIntoView({behavior: 'smooth', block: 'nearest'});
    }).catch(function (e) { alertMsg('danger', e.message); });
  }
  function runNow() {
    var input;
    try { input = JSON.parse($('wfRunInput').value || '{}'); } catch (e) { alertMsg('danger', 'Run input is not valid JSON'); return; }
    api('POST', '/api/workflows/' + encodeURIComponent(loaded.name) + '/runs', {input: input}).then(function (j) {
      alertMsg('info', 'Run ' + j.run.id + ' is ' + j.run.status + '.'); loadRuns(); showRun(j.run.id);
    }).catch(function (e) { alertMsg('danger', e.message); });
  }

  // ── events ─────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    newWf(); loadList();
    $('wfNew').addEventListener('click', function () { tab = 'form'; showTab('form').then(newWf); });
    $('wfRefresh').addEventListener('click', function () { loadList(); });
    $('wfRunsRefresh').addEventListener('click', loadRuns);
    $('wfSave').addEventListener('click', save);
    $('wfValidate').addEventListener('click', validate);
    $('wfRun').addEventListener('click', runNow);
    $('wfDelete').addEventListener('click', function () {
      if (!loaded || !confirm('Delete workflow ' + loaded.name + ' and its run history?')) return;
      api('DELETE', '/api/workflows/' + encodeURIComponent(loaded.name)).then(function () { alertMsg('success', 'Deleted.'); newWf(); loadList(); })
        .catch(function (e) { alertMsg('danger', e.message); });
    });
    $('wfToggle').addEventListener('click', function () {
      api('POST', '/api/workflows/' + encodeURIComponent(loaded.name) + (loaded.enabled ? '/disable' : '/enable')).then(function (j) { loadList(j.workflow.name); })
        .catch(function (e) { alertMsg('danger', e.message); });
    });
    document.querySelectorAll('[data-wf-tab]').forEach(function (b) { b.addEventListener('click', function () { showTab(b.getAttribute('data-wf-tab')); }); });
    $('wfList').addEventListener('click', function (ev) { var b = ev.target.closest('[data-name]'); if (b) { tab = 'form'; showTab('form').then(function () { open(b.getAttribute('data-name')); }); } });
    $('wfAddStep').addEventListener('click', function () {
      collect();
      var kind = $('wfAddKind').value, n = (cur.steps || []).length + 1, id = 'step' + n;
      while ((cur.steps || []).some(function (s) { return s.id === id; })) id = 'step' + (++n);
      var s = {id: id, kind: kind};
      var prev = cur.steps.length ? cur.steps[cur.steps.length - 1].id : null;
      if (prev) s.depends_on = [prev];
      if (kind === 'tool' || kind === 'composite') { s.tool = TOOLS[0] || ''; s.params = {}; }
      if (kind === 'ask') s.question = 'Summarise {{$steps.' + (prev || 'step1') + '}}';
      if (kind === 'condition') { s['if'] = 'exists $steps.' + (prev || 'step1'); s.then = []; s['else'] = []; }
      if (kind === 'foreach') { s.items = '$steps.' + (prev || 'step1') + '.rows'; s['do'] = {kind: 'tool', tool: TOOLS[0] || '', params: {}}; s.max_items = 20; }
      if (kind === 'wait') s.seconds = 60;
      if (kind === 'approval') s.reason = 'Check before continuing';
      cur.steps.push(s); renderAll();
    });
    $('wfSteps').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-act]'); if (!b) return;
      collect();
      var i = +b.closest('.wf-step').getAttribute('data-i');
      if (b.getAttribute('data-act') === 'del') cur.steps.splice(i, 1);
      else if (i > 0) { var t = cur.steps[i - 1]; cur.steps[i - 1] = cur.steps[i]; cur.steps[i] = t; }
      renderAll();
    });
    $('wfSteps').addEventListener('change', function () { collect(); drawDag(); });
    $('wfAddTrigBtn').addEventListener('click', function () {
      collect();
      var type = $('wfAddTrig').value, n = (cur.triggers || []).length + 1, t = {id: type + n, type: type};
      if (type === 'cron') { t.cron = '0 6 * * 1-5'; t.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; }
      if (type === 'file') { t.prefix = 'data/inbox'; t.pattern = '*'; t.interval_seconds = 30; }
      if (type === 'event') t.kinds = ['tools'];
      cur.triggers = (cur.triggers || []).concat([t]); renderAll();
    });
    $('wfTriggers').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-tact]'); if (!b) return;
      collect();
      cur.triggers.splice(+b.closest('[data-t]').getAttribute('data-t'), 1); renderAll();
    });
    $('wfRuns').addEventListener('click', function (ev) {
      var b = ev.target.closest('button'); if (!b) return;
      if (b.dataset.run) showRun(b.dataset.run);
      if (b.dataset.cancel) api('POST', '/api/workflows/runs/' + b.dataset.cancel + '/cancel').then(loadRuns).catch(function (e) { alertMsg('danger', e.message); });
      if (b.dataset.rerun) api('POST', '/api/workflows/runs/' + b.dataset.rerun + '/rerun', {}).then(function (j) { loadRuns(); showRun(j.run.id); }).catch(function (e) { alertMsg('danger', e.message); });
    });
  });
})();
