/*
 * SAJHA MCP Server — the credential files pages (admin/credential_file.html):
 * config/apikeys.json ("keys") and config/users.json ("users"). JSON API in
 * sajha/routes/credential_files_routes.py. Copyright All rights Reserved 2025-2030, Ashutosh Sinha.
 */
(function () {
  'use strict';
  var root = document.getElementById('credFile');
  if (!root) return;
  var kind = root.dataset.kind, csrf = root.dataset.csrf || '';
  var api = kind === 'keys' ? '/api/admin/apikeys/file' : '/api/admin/users/file';
  var idOf = function (r) { return kind === 'keys' ? r.id : r.user_id; };
  var $ = function (id) { return document.getElementById(id); };
  var rows = [], editing = null;

  var FIELDS = kind === 'keys' ? [
    ['name', 'Name', 'text'], ['owner', 'Owner (user ID)', 'text'], ['roles', 'Roles (comma-separated)', 'text'],
    ['tool_access_mode', 'Tool access', 'select', ['all', 'allowlist', 'denylist', 'regex']],
    ['tool_access_list', 'Tools (comma-separated)', 'text'], ['expires_at', 'Expires (ISO, empty = never)', 'text'],
    ['key', 'Key (empty: generate / keep)', 'text'], ['enabled', 'Enabled', 'check'], ['test_admin', 'Test admin', 'check']
  ] : [
    ['user_id', 'User ID', 'text'], ['user_name', 'Name', 'text'], ['email', 'Email', 'text'],
    ['roles', 'Roles (comma-separated: ' + (root.dataset.roles || '') + ')', 'text'],
    ['password', 'Password (empty: keep)', 'password'], ['enabled', 'Enabled', 'check'], ['test_admin', 'Test admin', 'check']
  ];

  function status(msg, bad) {
    var s = $('cfStatus'); s.hidden = !msg; s.textContent = msg || '';
    s.className = 'alert ' + (bad ? 'alert-danger' : 'alert-success'); if (msg) s.focus();
  }
  function call(method, url, body) {
    return fetch(url, { method: method, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || r.statusText); return j; }); });
  }
  function cell(text) { var td = document.createElement('td'); td.textContent = text == null ? '' : String(text); return td; }
  function btn(label, cls, fn) {
    var b = document.createElement('button'); b.type = 'button'; b.className = 'btn btn-sm ' + cls; b.textContent = label;
    b.addEventListener('click', fn); return b;
  }
  function list(v) { return Array.isArray(v) ? v.join(', ') : (v || ''); }

  function render() {
    var head = kind === 'keys' ? ['Name', 'Key', 'Owner', 'Roles', 'Tools', 'State', ''] : ['User ID', 'Name', 'Roles', 'State', ''];
    var tr = document.createElement('tr');
    head.forEach(function (h) { var th = document.createElement('th'); th.scope = 'col'; th.textContent = h; tr.appendChild(th); });
    $('cfHead').replaceChildren(tr);
    var body = $('cfRows'); body.replaceChildren();
    if (!rows.length) { var e = document.createElement('tr'); e.appendChild(cell('The file has no entries yet.')); body.appendChild(e); return; }
    rows.forEach(function (r) {
      var row = document.createElement('tr');
      var state = (r.enabled ? 'enabled' : 'disabled') + (r.test_admin ? ' · test admin' : '');
      if (kind === 'keys') {
        [r.name, r.masked, r.owner, list(r.roles), r.tool_access_mode + (r.tool_access_list && r.tool_access_list.length ? ': ' + list(r.tool_access_list) : ''), state]
          .forEach(function (v) { row.appendChild(cell(v)); });
      } else {
        [r.user_id, r.user_name, list(r.roles), state].forEach(function (v) { row.appendChild(cell(v)); });
      }
      var act = document.createElement('td'); act.className = 'text-nowrap';
      if (kind === 'keys' && r.form === 'raw') act.appendChild(btn('Reveal', 'btn-outline-secondary me-1', function () {
        call('GET', api + '/' + encodeURIComponent(r.id) + '/reveal').then(function (j) {
          $('cfOnce').hidden = false; $('cfOnceH').textContent = 'Key for ' + (r.name || r.id); $('cfOnceValue').textContent = j.key;
        }).catch(function (e) { status(e.message, true); });
      }));
      act.appendChild(btn('Edit', 'btn-outline-primary me-1', function () { openForm(r); }));
      act.appendChild(btn('Delete', 'btn-outline-danger', function () {
        if (window.confirm && !window.confirm('Delete ' + idOf(r) + ' from the file?')) return;
        call('DELETE', api + '/' + encodeURIComponent(idOf(r))).then(function () { status('Deleted ' + idOf(r) + '.'); load(); })
          .catch(function (e) { status(e.message, true); });
      }));
      row.appendChild(act); body.appendChild(row);
    });
  }

  function openForm(r) {
    editing = r; var f = $('cfFields'); f.replaceChildren();
    $('cfFormTitle').textContent = r ? 'Edit ' + idOf(r) : (kind === 'keys' ? 'New key' : 'New user');
    FIELDS.forEach(function (d) {
      var col = document.createElement('div'); col.className = d[2] === 'check' ? 'col-6 col-md-3' : 'col-12 col-md-6';
      var id = 'cf_' + d[0], lab = document.createElement('label'); lab.htmlFor = id; lab.textContent = d[1];
      var inp;
      if (d[2] === 'select') { inp = document.createElement('select'); inp.className = 'form-select form-select-sm';
        d[3].forEach(function (o) { var op = document.createElement('option'); op.value = o; op.textContent = o; inp.appendChild(op); }); }
      else { inp = document.createElement('input'); inp.type = d[2] === 'check' ? 'checkbox' : (d[2] === 'password' ? 'password' : 'text');
        inp.className = d[2] === 'check' ? 'form-check-input me-2' : 'form-control form-control-sm'; }
      inp.id = id; inp.name = d[0];
      var v = r ? r[d[0]] : (d[0] === 'enabled');
      if (d[2] === 'check') inp.checked = !!v; else if (d[0] !== 'password' && d[0] !== 'key') inp.value = Array.isArray(v) ? v.join(', ') : (v == null ? '' : v);
      if (r && kind === 'users' && d[0] === 'user_id') inp.readOnly = true;
      if (d[2] === 'check') { col.className += ' form-check'; col.appendChild(inp); col.appendChild(lab); }
      else { lab.className = 'form-label small'; col.appendChild(lab); col.appendChild(inp); }
      f.appendChild(col);
    });
    $('cfForm').hidden = false; $('cf_' + FIELDS[0][0]).focus();
  }

  $('cfForm').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var body = {};
    FIELDS.forEach(function (d) {
      var el = $('cf_' + d[0]); if (!el) return;
      if (d[2] === 'check') body[d[0]] = el.checked;
      else if (el.value !== '' || (d[0] !== 'password' && d[0] !== 'key')) body[d[0]] = el.value;
    });
    if (body.expires_at === '') body.expires_at = null;
    var p = editing ? call('PUT', api + '/' + encodeURIComponent(idOf(editing)), body) : call('POST', api, body);
    p.then(function (j) {
      $('cfForm').hidden = true;
      if (j.raw) { $('cfOnce').hidden = false; $('cfOnceH').textContent = 'Copy the new key now'; $('cfOnceValue').textContent = j.raw; }
      status('Saved.' + (j.problems && j.problems.length ? ' Not applied: ' + j.problems.join('; ') : '')); load();
    }).catch(function (e) { status(e.message, true); });
  });
  $('cfCancel').addEventListener('click', function () { $('cfForm').hidden = true; });
  $('cfNew').addEventListener('click', function () { openForm(null); });

  function load() {
    call('GET', api).then(function (j) { rows = (kind === 'keys' ? j.keys : j.users) || []; render(); })
      .catch(function (e) { status(e.message, true); });
  }
  load();
})();
