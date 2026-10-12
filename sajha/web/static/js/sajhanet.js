/*
 * SAJHA MCP Server — the SAJHA Net console (design §17.1): the topology map of the Net overview and the
 * admission panel (open mode's remembered first-use keys, manual mode's pins, the SAJHA Net CA's tokens,
 * certificates and revocations) of the overview and SAJHA Net admin pages.
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
 *
 * The map is plain SVG drawn from GET /api/sajhanet/topology?net= ({nets: [{name, nodes, edges}]}): one
 * node per instance (this server centred), edges for tools offered, re-exported and called. Colours come
 * from CSS classes on the theme tokens, so it follows all four themes; every state is also written in
 * words, and a table beside the map says the same for screen readers. Every change asks first (confirm)
 * and says what it does; nothing here decides anything the server does not decide again.
 */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';

  function esc(t) { var d = document.createElement('div'); d.textContent = t == null ? '' : String(t); return d.innerHTML; }
  function api(method, url, body) {
    return fetch(url, {method: method, credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': (document.querySelector('[data-sn-csrf]') || {getAttribute: function () { return ''; }}).getAttribute('data-sn-csrf')},
                       body: body ? JSON.stringify(body) : undefined})
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return {ok: r.ok, status: r.status, d: d}; }); });
  }
  function el(name, attrs, parent) {
    var e = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(e);
    return e;
  }
  function enc(s) { return encodeURIComponent(s); }
  function count(v) { return Array.isArray(v) ? v.length : (Number(v) || 0); }

  // ── the topology map ───────────────────────────────────────────────

  function layout(nodes, w, h) {
    var me = nodes.filter(function (n) { return n.self; })[0] || nodes[0];
    var others = nodes.filter(function (n) { return n !== me; });
    var pos = {};
    var cx = w / 2, cy = h / 2;
    if (me) pos[me.name] = {x: cx, y: cy};
    var r = Math.max(60, Math.min(w / 2 - 75, h / 2 - 50));     // room for the labels at the sides
    others.forEach(function (n, i) {
      var a = -Math.PI / 2 + 2 * Math.PI * i / Math.max(1, others.length);
      pos[n.name] = {x: cx + r * Math.cos(a), y: cy + r * Math.sin(a)};
    });
    return pos;
  }

  function drawMap(box, net, base) {
    var svg = box.querySelector('svg[data-role=map]');
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var w = Math.max(300, Math.round(box.clientWidth || 600)), h = Math.max(320, Math.min(460, Math.round(w * 0.62)));
    svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
    svg.setAttribute('height', h);
    var title = el('title', {id: box.id + '-t'}, svg);
    var nodes = net.nodes || [], edges = net.edges || [];
    title.textContent = _t('Topology of %(net)s: %(nodes)s instances, %(edges)s links', {net: net.name, nodes: nodes.length, edges: edges.length});
    var defs = el('defs', {}, svg);
    var mk = el('marker', {id: box.id + '-arrow', viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '9',
                           markerHeight: '9', markerUnits: 'userSpaceOnUse', orient: 'auto-start-reverse'}, defs);
    el('path', {d: 'M0,0 L10,5 L0,10 z', 'class': 'tp-arrow'}, mk);
    var pos = layout(nodes, w, h);
    var gE = el('g', {'class': 'tp-edges'}, svg), gN = el('g', {'class': 'tp-nodes'}, svg);
    var pairs = {};
    edges.forEach(function (e) {
      var a = pos[e.from], b = pos[e.to];
      if (!a || !b || e.from === e.to) return;
      var pk = [e.from, e.to].sort().join('|');
      var bend = (pairs[pk] = (pairs[pk] || 0) + 1) - 1;
      var dx = b.x - a.x, dy = b.y - a.y, len = Math.sqrt(dx * dx + dy * dy) || 1;
      var off = 18 + bend * 14, sx = a.x + dx / len * 20, sy = a.y + dy / len * 20, ex = b.x - dx / len * 22, ey = b.y - dy / len * 22;
      var mx = (sx + ex) / 2 - dy / len * off * (bend ? 1 : 0.3), my = (sy + ey) / 2 + dx / len * off * (bend ? 1 : 0.3);
      var calls = Number(e.calls) || 0;
      var p = el('path', {d: 'M' + sx + ',' + sy + ' Q' + mx + ',' + my + ' ' + ex + ',' + ey,
                          'class': 'tp-edge tp-' + (e.kind || 'offers'), 'marker-end': 'url(#' + box.id + '-arrow)',
                          'stroke-width': e.kind === 'calls' ? String(Math.min(7, 1.5 + Math.log2(calls + 1))) : '1.5'}, gE);
      var tt = el('title', {}, p);
      tt.textContent = e.from + ' → ' + e.to + ': ' + (e.kind || 'offers') + ' (' + _t('%(n)s tools', {n: count(e.tools)}) +
        (e.kind === 'calls' ? ', ' + _t('%(n)s calls', {n: calls}) : '') + ')';
    });
    nodes.forEach(function (n) {
      var q = pos[n.name];
      if (!q) return;
      var a = el('a', {href: base + enc(net.name) + '/' + enc(n.name), 'class': 'tp-link'}, gN);
      var st = String(n.state || 'unknown').replace(/[^a-z_-]/gi, '');
      el('circle', {cx: q.x, cy: q.y, r: n.self ? 18 : 14, 'class': 'tp-node st-' + st + (n.self ? ' tp-self' : '')}, a);
      var rad = n.self ? 18 : 14, up = !n.self && q.y < h / 2 - 1;     // labels away from the centre
      var t = el('text', {x: q.x, y: up ? q.y - rad - (n.region ? 22 : 8) : q.y + rad + 16, 'text-anchor': 'middle', 'class': 'tp-label'}, a);
      t.textContent = n.name + (st === 'alive' ? '' : ' (' + st + ')');
      if (n.region) {
        var r = el('text', {x: q.x, y: up ? q.y - rad - 8 : q.y + rad + 30, 'text-anchor': 'middle', 'class': 'tp-sub'}, a);
        r.textContent = n.region;
      }
      var words = n.name + (n.self ? ' ' + _t('(this server)') : '') + ': ' + st + ', ' + (n.kind || 'sajha') +
        (n.region ? ', ' + n.region : '') + '. ' + _t('Open its tools.');
      a.setAttribute('aria-label', words);
      el('title', {}, a).textContent = words;
    });
    if (!nodes.length) {
      var t = el('text', {x: w / 2, y: h / 2, 'text-anchor': 'middle', 'class': 'tp-sub'}, svg);
      t.textContent = _t('No instances to draw.');
    }
  }

  function fillTable(tbody, net) {
    var rows = [];
    (net.nodes || []).forEach(function (n) {
      rows.push('<tr><td><code>' + esc(n.name) + '</code>' + (n.self ? ' ' + esc(_t('(this server)')) : '') + '</td><td>' + esc(_t('instance')) + '</td><td>' +
        esc(n.state) + '</td><td>' + esc([n.kind, n.region].filter(Boolean).join(', ')) + '</td></tr>');
    });
    (net.edges || []).forEach(function (e) {
      rows.push('<tr><td><code>' + esc(e.from) + '</code> → <code>' + esc(e.to) + '</code></td><td>' + esc(e.kind) +
        '</td><td>' + esc(_t('%(n)s tools', {n: count(e.tools)})) + (e.calls != null ? ', ' + esc(_t('%(n)s calls', {n: e.calls})) : '') + '</td><td>' +
        esc(Array.isArray(e.tools) ? e.tools.slice(0, 8).join(', ') + (e.tools.length > 8 ? '…' : '') : '') + '</td></tr>');
    });
    tbody.innerHTML = rows.join('') || '<tr><td colspan="4">' + esc(_t('Nothing to show.')) + '</td></tr>';
  }

  function topology(box) {
    var net = box.dataset.net, base = box.dataset.base || '/net/instances/';
    var status = box.querySelector('[data-role=status]'), tbody = box.querySelector('tbody');
    var fallback = null;
    try { fallback = JSON.parse(box.querySelector('script[type="application/json"]').textContent); } catch (e) { fallback = null; }
    var last = null, timer = null, paused = false;
    function render(n) { last = n; drawMap(box, n, base); fillTable(tbody, n); }
    function load() {
      api('GET', '/api/sajhanet/topology?net=' + enc(net)).then(function (x) {
        var n = x.ok && x.d && Array.isArray(x.d.nets) ? x.d.nets.filter(function (v) { return v.name === net; })[0] : null;
        if (n) { render(n); status.textContent = _t('Updated %(time)s.', {time: new Date().toLocaleTimeString()}); return; }
        if (fallback) render(fallback);
        status.textContent = x.status === 404 || x.status === 405
          ? _t('The topology endpoint is not on this server; members only, without links.')
          : _t('Topology not available: %(error)s. Members only, without links.', {error: (x.d && x.d.error) || ('HTTP ' + x.status)});
      }).catch(function (e) { if (fallback) render(fallback); status.textContent = _t('Topology not available: %(error)s', {error: e}); });
    }
    var btn = box.querySelector('[data-role=pause]');
    function schedule() { clearInterval(timer); if (!paused) timer = setInterval(function () { if (!document.hidden) load(); }, 30000); }
    if (btn) btn.addEventListener('click', function () {
      paused = !paused; btn.setAttribute('aria-pressed', paused ? 'true' : 'false');
      btn.textContent = paused ? _t('Resume live view') : _t('Pause live view');
      schedule();
    });
    var rt = null;
    window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(function () { if (last) drawMap(box, last, base); }, 150); });
    load(); schedule();
  }

  // ── admission: first-use keys, pins, the CA ──────────────────────────

  function say(box, text) { var o = box.querySelector('[data-role=out]'); if (o) o.textContent = text; }

  function openMode(box, net) {
    var tb = box.querySelector('[data-role=first-use]');
    if (!tb) return;
    api('GET', '/api/sajhanet/nets/' + enc(net) + '/first-use').then(function (x) {
      if (!x.ok) { tb.innerHTML = '<tr><td colspan="3">' + esc(x.d.error || _t('not available')) + '</td></tr>'; return; }
      var ks = Object.keys(x.d.keys || {}).sort();
      tb.innerHTML = ks.map(function (k) {
        return '<tr><td><code>' + esc(k) + '</code></td><td class="sn-hash">' + esc(x.d.keys[k]) + '</td><td>' +
          '<button class="btn btn-sm btn-outline-danger" type="button" data-forget="' + esc(k) + '">' + esc(_t('Forget')) + '</button></td></tr>';
      }).join('') || '<tr><td colspan="3">' + esc(_t('No key remembered yet: no other instance has been seen in %(net)s.', {net: net})) + '</td></tr>';
      tb.querySelectorAll('[data-forget]').forEach(function (b) {
        b.addEventListener('click', function () {
          var who = b.getAttribute('data-forget');
          if (!confirm(_t('Forget the key remembered for %(who)s in %(net)s?', {who: who, net: net}) + '\n\n' +
                       _t('The next server that presents the name %(who)s is accepted on first use and its key remembered instead. Do this only when %(who)s replaced its key on purpose.', {who: who}))) return;
          api('DELETE', '/api/sajhanet/nets/' + enc(net) + '/first-use/' + enc(who)).then(function (y) {
            say(box, y.ok ? _t('Forgot the key of %(who)s.', {who: who}) : _t('Not forgotten: %(error)s', {error: y.d.error || _t('error')}));
            openMode(box, net);
          });
        });
      });
    });
  }

  function manualMode(box, net) {
    var tb = box.querySelector('[data-role=pins]');
    if (!tb) return;
    api('GET', '/api/sajhanet/nets/' + enc(net) + '/pins').then(function (x) {
      if (!x.ok) { tb.innerHTML = '<tr><td colspan="3">' + esc(x.d.error || _t('not available')) + '</td></tr>'; return; }
      var rows = (x.d.configured || []).map(function (p) {
        return '<tr><td class="sn-hash">' + esc(p) + '</td><td>' + esc(_t('configuration')) + '</td><td>—</td></tr>';
      }).concat((x.d.runtime || []).map(function (p) {
        return '<tr><td class="sn-hash">' + esc(p) + '</td><td>' + esc(_t('added here')) + '</td><td><button class="btn btn-sm btn-outline-danger" ' +
          'type="button" data-unpin="' + esc(p) + '">' + esc(_t('Remove')) + '</button></td></tr>';
      }));
      tb.innerHTML = rows.join('') || '<tr><td colspan="3">' + esc(_t('No thumbprint pinned: no peer is trusted yet.')) + '</td></tr>';
      tb.querySelectorAll('[data-unpin]').forEach(function (b) {
        b.addEventListener('click', function () {
          var tp = b.getAttribute('data-unpin');
          if (!confirm(_t('Remove the pin %(tp)s from %(net)s?', {tp: tp, net: net}) + '\n\n' +
                       _t('The peer with this certificate is no longer trusted on its next request.'))) return;
          api('DELETE', '/api/sajhanet/nets/' + enc(net) + '/pins', {thumbprint: tp}).then(function (y) {
            say(box, y.ok ? _t('Pin removed.') : _t('Not removed: %(error)s', {error: y.d.error || _t('error')})); manualMode(box, net);
          });
        });
      });
    });
    var f = box.querySelector('form[data-role=pin-form]');
    if (f && !f.dataset.bound) {
      f.dataset.bound = '1';
      f.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var tp = f.thumbprint.value.trim();
        if (!tp || !confirm(_t('Pin %(tp)s in %(net)s?', {tp: tp, net: net}) + '\n\n' + _t('The peer holding this certificate is trusted from its next request.'))) return;
        api('POST', '/api/sajhanet/nets/' + enc(net) + '/pins', {thumbprint: tp}).then(function (y) {
          say(box, y.ok ? _t('Pinned.') : _t('Not pinned: %(error)s', {error: y.d.error || _t('error')})); if (y.ok) f.reset(); manualMode(box, net);
        });
      });
    }
  }

  function caMode(box, net) {
    var area = box.querySelector('[data-role=ca]');
    if (!area) return;
    api('GET', '/api/sajhanet/nets/' + enc(net) + '/ca').then(function (x) {
      var issued = area.querySelector('[data-role=issued]'), pending = area.querySelector('[data-role=pending]');
      var forms = area.querySelector('[data-role=ca-forms]'), note = area.querySelector('[data-role=ca-note]');
      if (!x.ok) {
        forms.hidden = true; issued.innerHTML = ''; pending.innerHTML = '';
        note.textContent = (x.d.error || _t('The CA is not available')) + '.';
        return;
      }
      forms.hidden = false;
      var rl = x.d.revocation_list || {}, revoked = {};
      (rl.revoked || []).forEach(function (r) { if (r.serial) revoked[r.serial] = 1; if (r.instance) revoked['i:' + r.instance] = 1; });
      note.textContent = _t('This server is the CA instance of %(net)s (thumbprint %(tp)s); revocation list version %(version)s, %(n)s revoked.',
        {net: net, tp: x.d.thumbprint, version: rl.version || 0, n: (rl.revoked || []).length});
      issued.innerHTML = (x.d.issued || []).map(function (c) {
        var gone = revoked[c.serial] || revoked['i:' + c.instance];
        return '<tr><td><code>' + esc(c.instance) + '</code></td><td class="sn-hash">' + esc(c.serial) + '</td><td>' +
          esc(c.not_after) + '</td><td>' + esc(gone ? _t('revoked') : _t('valid')) + '</td><td>' + (gone ? '—' :
          '<button class="btn btn-sm btn-outline-danger" type="button" data-revoke="' + esc(c.serial) + '" data-inst="' + esc(c.instance) +
          '">' + esc(_t('Revoke')) + '</button>') + '</td></tr>';
      }).join('') || '<tr><td colspan="5">' + esc(_t('No certificate issued yet.')) + '</td></tr>';
      pending.innerHTML = (x.d.pending_tokens || []).map(function (t) {
        return '<tr><td><code>' + esc(t.instance) + '</code></td><td>' + esc(t.host || '—') + '</td><td>' +
          esc(t.created_by || '') + '</td><td>' + esc(t.expires ? new Date(t.expires * 1000).toISOString().replace('.000', '') : '') + '</td></tr>';
      }).join('') || '<tr><td colspan="4">' + esc(_t('No enrollment token waiting.')) + '</td></tr>';
      issued.querySelectorAll('[data-revoke]').forEach(function (b) {
        b.addEventListener('click', function () {
          var inst = b.getAttribute('data-inst'), serial = b.getAttribute('data-revoke');
          var reason = prompt(_t('Revoke the certificate of %(inst)s (serial %(serial)s) in %(net)s.', {inst: inst, serial: serial, net: net}) + '\n\n' +
            _t('Every member refuses it once the revocation list reaches them, and %(inst)s leaves the net until it enrolls again. Reason (required):', {inst: inst}));
          if (!reason) return;
          api('POST', '/api/sajhanet/nets/' + enc(net) + '/ca/revoke', {serial: serial, reason: reason}).then(function (y) {
            say(box, y.ok ? _t('Revoked; revocation list version %(version)s.', {version: y.d.version}) : _t('Not revoked: %(error)s', {error: y.d.error || _t('error')}));
            caMode(box, net);
          });
        });
      });
    });
    var f = area.querySelector('form[data-role=token-form]');
    if (f && !f.dataset.bound) {
      f.dataset.bound = '1';
      f.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var inst = f.instance.value.trim();
        if (!inst || !confirm(_t('Create a single-use enrollment token for %(inst)s in %(net)s?', {inst: inst, net: net}) + '\n\n' +
                              _t('Whoever holds it can obtain the certificate for the name %(inst)s until it expires.', {inst: inst}))) return;
        api('POST', '/api/sajhanet/nets/' + enc(net) + '/ca/tokens', {instance: inst, host: f.host.value.trim()}).then(function (y) {
          var out = area.querySelector('[data-role=token-out]');
          if (y.ok) {
            out.hidden = false;
            out.querySelector('code').textContent = y.d.token;
            out.querySelector('[data-role=token-meta]').textContent = _t('For %(inst)s, until %(expires)s. Shown once: give it to the administrator of %(inst)s with the CA URL %(url)s.',
              {inst: y.d.instance, expires: y.d.expires_at, url: y.d.ca_url || ''});
            f.reset();
          } else {
            say(box, _t('No token: %(error)s', {error: y.d.error || _t('error')}));
          }
          caMode(box, net);
        });
      });
    }
    var init = area.querySelector('[data-role=ca-init]');
    if (init && !init.dataset.bound) {
      init.dataset.bound = '1';
      init.addEventListener('click', function () {
        if (!confirm(_t('Initialise the SAJHA Net CA of %(net)s on this server?', {net: net}) + '\n\n' +
                     _t('This creates the CA key; back it up at once, it is the only copy.'))) return;
        api('POST', '/api/sajhanet/nets/' + enc(net) + '/ca/init', {}).then(function (y) {
          say(box, y.ok ? (_t('CA initialised (thumbprint %(tp)s).', {tp: y.d.thumbprint}) + ' ' + y.d.backup) : _t('Not initialised: %(error)s', {error: y.d.error || _t('error')}));
          caMode(box, net);
        });
      });
    }
  }

  function admission(box) {
    var net = box.dataset.net, mode = box.dataset.mode;
    if (mode === 'open') openMode(box, net);
    else if (mode === 'manual') manualMode(box, net);
    else if (mode === 'builtin_ca') caMode(box, net);
  }

  // ── small actions: approve a held tool, remove a runtime seed ───────

  function bindActions(root) {
    root.querySelectorAll('button[data-approve]').forEach(function (b) {
      b.addEventListener('click', function () {
        var d = b.dataset;
        if (!confirm(_t('Approve %(tool)s from %(peer)s in %(net)s?', {tool: d.tool, peer: d.peer, net: d.net}) + '\n\n' +
                     _t('Its proxy is listed for the users this server imports it for, from the next tools/list.'))) return;
        api('POST', '/api/sajhanet/nets/' + enc(d.net) + '/peers/' + enc(d.peer) + '/tools/' + enc(d.tool) + '/approve').then(function (y) {
          var o = document.getElementById(d.out);
          if (o) o.textContent = y.ok ? _t('Approved %(tool)s.', {tool: d.tool}) : _t('Not approved: %(error)s', {error: y.d.error || _t('error')});
          if (y.ok) b.disabled = true;
        });
      });
    });
    root.querySelectorAll('button[data-unseed]').forEach(function (b) {
      b.addEventListener('click', function () {
        var d = b.dataset;
        if (!confirm(_t('Remove the runtime seed %(seed)s from %(net)s?', {seed: d.unseed, net: d.net}) + '\n\n' +
                     _t('The server stays joined; the address is no longer tried at the next start.'))) return;
        api('DELETE', '/api/sajhanet/nets/' + enc(d.net) + '/seeds', {url: d.unseed}).then(function (y) {
          var o = document.getElementById(d.out);
          if (o) o.textContent = y.ok ? _t('Runtime seed removed.') : _t('Not removed: %(error)s', {error: (y.d && y.d.error) || _t('not found')});
          if (y.ok) { var li = b.closest('li'); if (li) li.remove(); }
        });
      });
    });
  }

  window.SajhaNet = {topology: topology, admission: admission, bindActions: bindActions, api: api, esc: esc};
  document.querySelectorAll('[data-sn-topology]').forEach(topology);
  document.querySelectorAll('[data-sn-admission]').forEach(admission);
  bindActions(document);
})();
