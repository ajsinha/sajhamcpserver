/*
 * SAJHA MCP Server — the SAJHA Net management pages (design §17.1): every change asks first, in a dialog
 * that names its effect, shows its blast radius (who loses access to what, from
 * GET /api/sajhanet/nets/{net}/blast-radius) and requires a reason; then it is sent with the page's CSRF
 * token (data-sn-csrf) and lands in the net's change history, from which it can be undone.
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
 *
 * Markup:
 *   <button data-sn-action data-method="DELETE" data-url="/api/..." data-body='{"x":1}' data-net="acme"
 *           data-kind="block_remove" data-blast='{"level":"instance","target_instance":"risk-eu"}'
 *           data-effect="Words" data-final="1">            (data-final: cannot be undone)
 *   <form data-sn-form data-method="POST" data-url="/api/.../{field}" data-net="acme" data-kind="block_add"
 *         data-effect="Words" data-blast-form>               (fields become the body; {field} fills the URL)
 * The page's status line is [data-sn-status]. No inline handlers (the console's CSP).
 */
(function () {
  'use strict';

  function csrf() { var e = document.querySelector('[data-sn-csrf]'); return e ? e.getAttribute('data-sn-csrf') : ''; }
  function api(method, url, body) {
    return fetch(url, {method: method, credentials: 'same-origin',
                       headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf(), 'Accept': 'application/json'},
                       body: body ? JSON.stringify(body) : undefined})
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) { return {ok: r.ok, status: r.status, d: d}; });
      });
  }
  function status(text, bad) {
    var s = document.querySelector('[data-sn-status]');
    if (!s) return;
    s.textContent = text;
    s.classList.toggle('sn-bad', !!bad);
  }
  function parse(json, dflt) { try { return json ? JSON.parse(json) : dflt; } catch (e) { return dflt; } }
  function qs(o) {
    return Object.keys(o).filter(function (k) { return o[k] !== '' && o[k] != null; })
      .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(o[k]); }).join('&');
  }

  var dlg, pending = null;

  function ask(spec) {
    dlg = dlg || document.getElementById('sn-dialog');
    if (!dlg) return;
    pending = spec;
    dlg.querySelector('[data-role=effect]').textContent = spec.effect || '';
    var blast = dlg.querySelector('[data-role=blast]');
    blast.textContent = spec.blast ? _t('Working out who is affected…') : '';
    dlg.querySelector('[data-role=final]').hidden = !spec.final;
    dlg.querySelector('[data-role=undo]').hidden = !!spec.final;
    var reason = dlg.querySelector('textarea');
    reason.value = '';
    dlg.querySelector('[data-role=out]').textContent = '';
    if (typeof dlg.showModal === 'function') dlg.showModal(); else dlg.setAttribute('open', '');
    reason.focus();
    if (spec.blast && spec.net) {
      var params = Object.assign({kind: spec.kind || ''}, spec.blast);
      api('GET', '/api/sajhanet/nets/' + encodeURIComponent(spec.net) + '/blast-radius?' + qs(params))
        .then(function (x) { blast.textContent = x.ok ? (x.d.words || '') : ''; });
    }
  }

  function close() {
    if (!dlg) return;
    if (typeof dlg.close === 'function') dlg.close(); else dlg.removeAttribute('open');
    pending = null;
  }

  function send() {
    if (!pending) return;
    var reason = dlg.querySelector('textarea').value.trim();
    var out = dlg.querySelector('[data-role=out]');
    if (!reason) { out.textContent = _t('Give a reason: it is kept in the change history.'); return; }
    var spec = pending, body = Object.assign({}, spec.body || {}, {reason: reason});
    out.textContent = _t('Sending…');
    if (spec.bulk) {                                          // one reason for every selected item, in turn
      var done = 0, failed = [];
      spec.bulk.reduce(function (p, url) {
        return p.then(function () {
          return api(spec.method, url, body).then(function (x) { if (x.ok) done++; else failed.push(x.d.error || x.status); });
        });
      }, Promise.resolve()).then(function () {
        close();
        status(_t('%(done)s of %(all)s done.', {done: done, all: spec.bulk.length}) +
               (failed.length ? ' ' + _t('Not done: %(error)s', {error: failed.join('; ')}) : ''), failed.length > 0);
        if (done) setTimeout(function () { location.reload(); }, 1200);
      });
      return;
    }
    api(spec.method, spec.url, spec.method === 'GET' ? null : body).then(function (x) {
      if (!x.ok) { out.textContent = _t('Not done: %(error)s', {error: x.d.error || x.status}); return; }
      close();
      if (x.d && x.d.token) {
        status(_t('Done. The token, shown once: %(token)s (expires %(expires)s)', {token: x.d.token, expires: x.d.expires_at || ''}));
        return;
      }
      status((x.d && x.d.effect) ? x.d.effect : _t('Done; it is in the change history.'));
      setTimeout(function () { location.reload(); }, 900);
    }).catch(function (e) { out.textContent = _t('Not done: %(error)s', {error: String(e)}); });
  }

  function formBody(f) {
    var body = {};
    Array.prototype.forEach.call(f.elements, function (el) {
      if (!el.name || el.disabled) return;
      if (el.type === 'checkbox') body[el.name] = el.checked;
      else if (el.type === 'number') { if (el.value !== '') body[el.name] = Number(el.value); }
      else if (el.value.trim() !== '') body[el.name] = el.value.trim();
    });
    return body;
  }

  document.addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-sn-action]');
    if (b) {
      ev.preventDefault();
      ask({method: b.getAttribute('data-method') || 'POST', url: b.getAttribute('data-url'),
           body: parse(b.getAttribute('data-body'), {}), net: b.getAttribute('data-net'),
           kind: b.getAttribute('data-kind'), blast: parse(b.getAttribute('data-blast'), null),
           effect: b.getAttribute('data-effect'), final: b.hasAttribute('data-final')});
      return;
    }
    var bulk = ev.target.closest('[data-sn-bulk]');
    if (bulk) {
      ev.preventDefault();
      var urls = Array.prototype.map.call(document.querySelectorAll(bulk.getAttribute('data-sn-bulk') + ':checked'),
                                          function (c) { return c.value; });
      if (!urls.length) { status(_t('Select at least one item first.'), true); return; }
      ask({method: bulk.getAttribute('data-method') || 'POST', bulk: urls, net: bulk.getAttribute('data-net'),
           effect: _t('%(n)s selected: %(what)s', {n: urls.length, what: bulk.getAttribute('data-effect') || ''})});
      return;
    }
    if (ev.target.closest('[data-sn-cancel]')) { ev.preventDefault(); close(); }
    if (ev.target.closest('[data-sn-confirm]')) { ev.preventDefault(); send(); }
  });

  document.addEventListener('submit', function (ev) {
    var f = ev.target.closest('[data-sn-form]');
    if (!f) return;
    ev.preventDefault();
    var body = formBody(f), url = f.getAttribute('data-url');
    url = url.replace(/\{(\w+)\}/g, function (m, k) { var v = body[k]; delete body[k]; return encodeURIComponent(v == null ? '' : v); });
    if (body.map_text !== undefined) {                       // a role map typed as "remote: local1, local2" lines
      var map = {};
      String(body.map_text).split(/\n|;/).forEach(function (line) {
        var i = line.indexOf(':');
        if (i > 0) map[line.slice(0, i).trim()] = line.slice(i + 1).split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      });
      delete body.map_text;
      body.map = map;
    }
    ask({method: f.getAttribute('data-method') || 'POST', url: url, body: body, net: f.getAttribute('data-net'),
         kind: f.getAttribute('data-kind'), blast: f.hasAttribute('data-blast-form') ? body : null,
         effect: f.getAttribute('data-effect'), final: f.hasAttribute('data-final')});
  });

  // client-side filters: <input data-sn-filter="#table-id"> hides rows whose text lacks the query
  document.addEventListener('input', function (ev) {
    var q = ev.target.closest('[data-sn-filter]');
    if (!q) return;
    var s = q.value.trim().toLowerCase();
    document.querySelectorAll(q.getAttribute('data-sn-filter')).forEach(function (row) {
      row.hidden = !!s && row.textContent.toLowerCase().indexOf(s) < 0;
    });
  });

  window.SajhaNet = {api: api, status: status, ask: ask};
})();
