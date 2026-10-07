/*
 * API keys pages (/account/apikeys, /admin/apikeys, /admin/apikeys/create, /admin/apikeys/{id}/view).
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
 *
 * Buttons carry data-key-action="post" (or "delete"), data-url, optional data-body (JSON) and
 * data-confirm. A form with data-key-create posts its fields as JSON. Every request sends the
 * page's CSRF token (data-csrf on [data-apikeys]). A response with "key" shows it once in
 * #keyOnce; anything else reloads the page.
 */
(function () {
  'use strict';
  var root = document.querySelector('[data-apikeys]');
  if (!root) { return; }
  var csrf = root.getAttribute('data-csrf') || '';
  var once = document.getElementById('keyOnce');
  var onceValue = document.getElementById('keyOnceValue');
  var status = document.getElementById('keyStatus');

  function say(msg, bad) {
    if (!status) { if (bad) { alert(msg); } return; }
    status.textContent = msg;
    status.className = 'alert ' + (bad ? 'alert-danger' : 'alert-success');
    status.hidden = false;
    status.focus();
  }

  function send(method, url, body) {
    return fetch(url, {
      method: method, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'Accept': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) { throw new Error(data.error || ('HTTP ' + r.status)); }
        return data;
      });
    });
  }

  function showOnce(data) {
    if (!once || !onceValue) { alert(data.key); location.reload(); return; }
    onceValue.textContent = data.key;
    var name = document.getElementById('keyOnceName');
    if (name && data.apikey) { name.textContent = data.apikey.name; }
    once.hidden = false;
    once.scrollIntoView({ block: 'center' });
    var copy = document.getElementById('keyOnceCopy');
    if (copy) { copy.focus(); }
  }

  function done(data) {
    if (data && data.key) { showOnce(data); } else { location.reload(); }
  }

  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest('[data-key-action]');
    if (!btn) { return; }
    ev.preventDefault();
    var question = btn.getAttribute('data-confirm');
    if (question && !confirm(question)) { return; }
    var body;
    var raw = btn.getAttribute('data-body');
    if (raw) { try { body = JSON.parse(raw); } catch (e) { body = {}; } }
    var from = btn.getAttribute('data-body-from');
    if (from) {
      var el = document.getElementById(from);
      body = body || {};
      body[el.name] = el.value;
    }
    var method = btn.getAttribute('data-key-action') === 'delete' ? 'DELETE' : 'POST';
    btn.disabled = true;
    send(method, btn.getAttribute('data-url'), body === undefined ? {} : body)
      .then(done)
      .catch(function (e) { say(e.message, true); })
      .then(function () { btn.disabled = false; });
  });

  var copyBtn = document.getElementById('keyOnceCopy');
  if (copyBtn) {
    copyBtn.addEventListener('click', function () {
      var text = onceValue ? onceValue.textContent : '';
      var ok = function () { copyBtn.textContent = 'Copied'; };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(ok, function () { window.prompt('Copy the key', text); });
      } else { window.prompt('Copy the key', text); }
    });
  }
  var closeBtn = document.getElementById('keyOnceDone');
  if (closeBtn) {
    closeBtn.addEventListener('click', function () {
      if (onceValue) { onceValue.textContent = ''; }
      var back = closeBtn.getAttribute('data-return');
      if (back) { location.href = back; } else { location.reload(); }
    });
  }

  function syncMode(form) {
    var mode = form.querySelector('[name="tool_access_mode"]:checked') || form.querySelector('select[name="tool_access_mode"]');
    var box = form.querySelector('[data-patterns]');
    if (box && mode) { box.hidden = mode.value === 'all'; }
  }

  document.querySelectorAll('form[data-key-create]').forEach(function (form) {
    syncMode(form);
    form.addEventListener('change', function () { syncMode(form); });
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var data = {};
      new FormData(form).forEach(function (v, k) { data[k] = v; });
      data.persistent = !!(form.querySelector('[name="persistent"]') || {}).checked;
      data.tool_list = (data.tool_list || '').split(/[\n,]/).map(function (s) { return s.trim(); }).filter(Boolean);
      if (data.tool_access_mode === 'all') { data.tool_list = []; }
      var submit = form.querySelector('[type="submit"]');
      if (submit) { submit.disabled = true; }
      send('POST', form.getAttribute('data-url'), data)
        .then(function (res) { form.reset(); syncMode(form); showOnce(res); })
        .catch(function (e) { say(e.message, true); })
        .then(function () { if (submit) { submit.disabled = false; } });
    });
  });
})();
