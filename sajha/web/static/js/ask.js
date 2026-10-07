/*
 * Ask SAJHA: the chat page over POST /api/ai/ask.
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
 *
 * The answer arrives as a Server-Sent Events stream (docs/architecture/Intelligence Layer.md,
 * "POST /api/ai/ask"): shortlist, model, plan, tool_call, tool_result, needs_confirmation, needs_connection,
 * answer_delta, answer, confidence, error, done. A planner that plans ahead (plan_execute, recipes)
 * sends a plan event, shown as a collapsible list whose steps tick off as their calls return. EventSource cannot POST, so the stream is
 * read with fetch + ReadableStream. The events are played through a short queue so each step
 * is visible (the mock planner answers in milliseconds); the conversation bubble and the sky
 * (static/js/constellation.js) change together. With prefers-reduced-motion nothing moves: each
 * event is applied at once and the sky shows the chain's final state.
 *
 * The conversation is a server-side conversation (conversation memory): the first question sends
 * conversation_id "new", later ones the id the server returned, so follow-ups are answered with
 * the earlier turns as context. New chat starts a new conversation. The bubbles are kept for the
 * tab in sessionStorage; Stop aborts the fetch, which ends the server's stream.
 */
(function () {
  'use strict';

  /* The "Servers and tools" log under the sky: one line per tool call, server — tool, newest last.
     The server comes from the tool's name: a plain name runs here; "upstream__tool" on a federated
     upstream; "net__host__tool" on a SAJHA Net host. It scrolls itself unless the reader scrolled up. */
  var callLog = (function () {
    var log = document.getElementById('askCallsLog'), count = document.getElementById('askCallsCount');
    var data = {}; try { data = JSON.parse(document.getElementById('askData').textContent) || {}; } catch (e) {}
    var here = data.server_name || 'this server', rows = {}, total = 0, lastTurn = null, MAX = 300;
    function serverOf(name) {
      var parts = String(name).split('__');
      if (parts.length >= 3) return { server: parts[0] + ' / ' + parts[1], kind: 'net', tool: parts.slice(2).join('__') };
      if (parts.length === 2) return { server: parts[0], kind: 'federated', tool: parts[1] };
      return { server: here, kind: 'local', tool: name };
    }
    function stamp() { var d = new Date(); return d.toTimeString().slice(0, 8); }
    function nearBottom() { return !log || log.scrollHeight - log.scrollTop - log.clientHeight < 28; }
    function add(li) {
      var stick = nearBottom();
      log.appendChild(li);
      while (log.children.length > MAX) log.removeChild(log.firstChild);
      if (stick) log.scrollTop = log.scrollHeight;
    }
    function span(cls, text) { var s = document.createElement('span'); s.className = cls; s.textContent = text; return s; }
    return {
      start: function (turn, id, name) {
        if (!log) return;
        if (turn !== lastTurn) {
          lastTurn = turn;
          var sep = document.createElement('li'); sep.className = 'ask-call-turn';
          sep.textContent = turn && turn.q ? turn.q : 'New question';
          add(sep);
        }
        var s = serverOf(name), li = document.createElement('li');
        li.className = 'ask-call is-running is-' + s.kind;
        li.appendChild(span('ask-call-time', stamp()));
        li.appendChild(span('ask-call-server', s.server));
        li.appendChild(span('ask-call-sep', '—'));
        var code = document.createElement('code'); code.className = 'ask-call-tool'; code.textContent = s.tool; li.appendChild(code);
        li.appendChild(span('ask-call-state', 'running'));
        rows[id] = li; total += 1; add(li);
        count.textContent = total + (total === 1 ? ' call' : ' calls');
      },
      end: function (id, ok, ms) {
        var li = rows[id]; if (!li) return;
        li.classList.remove('is-running');
        var st = li.querySelector('.ask-call-state');
        if (ok === null) { li.classList.add('is-waiting'); st.textContent = 'waiting for you'; return; }
        li.classList.add(ok ? 'is-ok' : 'is-error');
        st.textContent = (ok ? 'done' : 'failed') + (ms != null ? ' · ' + ms + ' ms' : '');
      }
    };
  })();
  var C = window.SajhaConstellation;
  var reduce = C.reduce;
  var D = {};
  try { D = JSON.parse(document.getElementById('askData').textContent) || {}; } catch (e) { /* no data */ }
  var $ = function (id) { return document.getElementById(id); };
  var logEl = $('askLog'), emptyEl = $('askEmpty'), liveEl = $('askLive'), form = $('askForm'), input = $('askInput'),
      sendBtn = $('askSend'), stopBtn = $('askStop'), newBtn = $('askNew'), modelSel = $('askModel'),
      mockPill = $('askMock'), statusText = $('askSkyStatusText'), statusBox = $('askSkyStatus');

  /* ── storage (per tab; every access may throw in a private window) ───────────────────── */
  var KEY = 'sajha.ask.v1.' + (D.user || ''), MKEY = 'sajha.ask.model', CKEY = 'sajha.ask.conv.' + (D.user || '');
  function sget(k) { try { return window.sessionStorage.getItem(k); } catch (e) { return null; } }
  function sset(k, v) { try { window.sessionStorage.setItem(k, v); } catch (e) { /* storage off */ } }
  function sdel(k) { try { window.sessionStorage.removeItem(k); } catch (e) { /* storage off */ } }
  var turns = [];
  try { turns = JSON.parse(sget(KEY) || '[]') || []; } catch (e) { turns = []; }
  function save() { sset(KEY, JSON.stringify(turns.slice(-30))); }

  /* ── small helpers ────────────────────────────────────────────────────────────────────── */
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function icon(name) { var i = el('i', 'bi bi-' + name); i.setAttribute('aria-hidden', 'true'); return i; }
  function pretty(v) {
    if (typeof v === 'string') { try { return JSON.stringify(JSON.parse(v), null, 2); } catch (e) { return v; } }
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v); }
  }
  function clip(s, n) { s = String(s || ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; }
  function tone(v) { return v >= 0.8 ? 'ok' : v >= 0.5 ? 'warn' : 'bad'; }
  function say(text) { liveEl.textContent = ''; setTimeout(function () { liveEl.textContent = text; }, 30); }
  function nearBottom() { return logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 80; }
  function toBottom(force) { if (force || nearBottom()) logEl.scrollTop = logEl.scrollHeight; }

  /* ── the sky ──────────────────────────────────────────────────────────────────────────── */
  var GROUPS = (D.groups || []).filter(function (g) { return g[1] > 0; });
  var skyEl = $('askSky'), cv = $('askSkyCanvas'), S = C.sky(cv, GROUPS);
  $('askSkyStats').textContent = (D.total || 0) + ' tools · ' + GROUPS.length + ' provider groups';
  var ease = function (x) { return 1 - Math.pow(1 - Math.min(Math.max(x, 0), 1), 3); };
  // what the sky shows: the shortlist (lit stars), the chain (links + labels), the phase
  var sk = { short: {}, shortG: {}, litT: 0, chain: [], phase: 'idle' };
  var raf = 0, onScreen = true;

  function skyReset() { sk = { short: {}, shortG: {}, litT: 0, chain: [], phase: 'idle' }; kick(); }
  function skyShortlist(tools, now) {
    sk.short = {}; sk.shortG = {};
    (tools || []).forEach(function (t) { sk.short[t.name] = 1; sk.shortG[C.groupOf(t.name)] = 1; });
    sk.litT = now || performance.now(); sk.phase = 'shortlist';
    kick();
  }
  function origin() { return { x: S.W / 2, y: statusBox.offsetTop + statusBox.offsetHeight + 4 }; }
  // a label's anchor: on its star unless that collides with an earlier label, then nudged
  function anchorFor(name, star) {
    var top = origin().y + 6, tries = [0, -46, 46, -92, 92, -138, 138], best = null, bestCost = 1e9;
    for (var i = 0; i < tries.length; i++) {
      var y = star.y + tries[i];
      var b = S.labelBox(name, star.x, y), cost = 0;
      if (b.t < top || b.b > S.H - 4) cost += 1e6;
      sk.chain.forEach(function (c) {
        if (!c.box) return;
        cost += Math.max(0, Math.min(b.r, c.box.r) - Math.max(b.l, c.box.l)) * Math.max(0, Math.min(b.b, c.box.b) - Math.max(b.t, c.box.t));
      });
      cost += Math.abs(tries[i]) * 0.5;
      if (cost < bestCost) { bestCost = cost; best = { y: y, box: b }; }
      if (cost === Math.abs(tries[i]) * 0.5) break;
    }
    return best;
  }
  function placeChain() {
    sk.chain.forEach(function (c) { c.box = null; });
    sk.chain.forEach(function (c) {
      c.star = S.starOf(c.name);
      if (!c.star) return;
      var a = anchorFor(c.name, c.star);
      c.ay = a.y; c.box = a.box;
    });
  }
  function skyCall(id, name, now) {
    var c = { id: id, name: name, t0: now || performance.now(), res: null };
    sk.chain.push(c); placeChain(); sk.phase = 'call'; kick();
  }
  function skyResult(id, ok, summary, now) {          // ok: true, false, or null (waiting for the user)
    sk.chain.forEach(function (c) { if (c.id === id) c.res = { ok: ok, text: summary, t: now || performance.now() }; });
    kick();
  }
  function draw(now) {
    if (!S.W) return;
    S.clear();
    var litP = sk.litT ? (reduce ? 1 : ease((now - sk.litT) / 700)) : 0;
    // the regex filter: a match is lifted, a miss dimmed hard; a shortlisted or chained star
    // keeps full strength whatever the filter says (the ask's own steps are never hidden)
    var fon = flt.re !== null;
    S.drawStars(now, function (st) {
      var on = 0;
      if (litP) on = st.n && sk.short[st.n] ? litP : sk.shortG[st.g] ? 0.32 * litP : 0;
      return fon && st.m ? Math.max(on, 0.6) : on;
    }, reduce, fon ? function (st) { return st.m || inAsk(st) ? 1 : 0.16; } : null);
    var cx = S.ctx, T = S.T;
    if (litP) {                                                   // a ring on every shortlisted star
      cx.strokeStyle = T.accent; cx.lineWidth = 1.2;
      S.stars.forEach(function (st) {
        if (!(st.n && sk.short[st.n])) return;
        cx.globalAlpha = 0.6 * litP; cx.beginPath(); cx.arc(st.x, st.y, 5.5, 0, 6.283); cx.stroke();
      });
      cx.globalAlpha = 1;
    }
    S.ring(tip.star, tip.pinned);
    var o = origin();
    if (!reduce && sk.litT && now - sk.litT < 900) S.sweep(o.x, o.y, ease((now - sk.litT) / 900));
    var px = o.x, py = o.y;
    sk.chain.forEach(function (c, i) {
      if (!c.star) return;
      var p = reduce ? 1 : ease((now - c.t0) / 520);
      S.link(px, py, c.star.x, c.star.y, p, i === 0, 1);
      if (p > 0.95) S.node(c.star.x, c.star.y, 1, c.res && c.res.ok === false ? T.bad : T.accent);
      px = c.star.x; py = c.star.y;
    });
    sk.chain.forEach(function (c) {
      if (!c.star) return;
      var p = reduce ? 1 : ease((now - c.t0) / 520);
      if (p <= 0.95) return;
      if (Math.abs(c.ay - c.star.y) > 1) {                                    // a leader from the star to its nudged label
        cx.strokeStyle = T.border; cx.lineWidth = 1; cx.globalAlpha = 0.9;
        cx.beginPath(); cx.moveTo(c.star.x, c.star.y); cx.lineTo(c.star.x, c.ay + (c.ay < c.star.y ? 28 : -10)); cx.stroke();
        cx.globalAlpha = 1;
      }
      S.lane(c.name, c.star.x, c.ay, 1);
      if (c.res) {
        var rp = reduce ? 1 : ease((now - c.res.t) / 400), wait = c.res.ok === null;
        S.result((wait ? '' : c.res.ok ? '✓ ' : '✕ ') + clip(c.res.text, S.W < 520 ? 30 : 46), c.star.x, c.ay, rp,
                 wait ? undefined : c.res.ok ? 'ok' : 'bad');
      } else {
        S.result('running…', c.star.x, c.ay, reduce ? 1 : 0.55 + 0.35 * Math.sin(now / 160));
      }
    });
  }
  function running() { return !reduce && onScreen && !document.hidden; }
  function loop(now) { raf = 0; draw(now); if (running()) raf = requestAnimationFrame(loop); }
  function kick() {
    if (running()) { if (!raf) raf = requestAnimationFrame(loop); }
    else draw(performance.now());
  }
  function layout() {
    if (!S.resize()) return;
    tip.forget();
    S.place({ cy: 0.57, ry: 0.35, rx: 0.43, scale: Math.max(0.5, Math.min(1.25, S.H / 520)) });
    markMatches(); placeChain(); kick();
  }
  function inAsk(st) {
    if (!st.n) return false;
    if (sk.short[st.n]) return true;
    for (var i = 0; i < sk.chain.length; i++) if (sk.chain[i].star === st) return true;
    return false;
  }

  /* ── hover tooltips: a star's tool, its group and its one-line description ────────────── */
  var DESC = D.descriptions || {};
  var tip = C.tips(S, skyEl, {
    info: function (st) { return st.n ? { name: st.n, group: st.g, desc: DESC[st.n] || '' } : null; },
    redraw: function () { kick(); }
  });

  /* ── the regex filter (cosmetic: it changes what the sky shows, never which tools an ask uses) */
  var FKEY = 'sajha.ask.filter', fIn = $('askFilter'), fMsg = $('askFilterMsg'), fClear = $('askFilterClear'), fErr = $('askFilterErr'),
      flt = { re: null }, fTimer = 0;
  function parseFilter(v) {          // '' -> null; /pattern/flags as written; else case-insensitive
    if (!v) return null;
    var m = /^\/(.+)\/([a-z]*)$/.exec(v);
    return m ? new RegExp(m[1], m[2].replace(/[gy]/g, '')) : new RegExp(v, 'i');
  }
  function markMatches() {
    var n = 0;
    S.stars.forEach(function (st) {
      var re = flt.re, hay = st.n ? st.n + ' ' + st.g + ' ' + (DESC[st.n] || '') : st.g;
      st.m = !!(re && re.test(hay));
      if (st.m) n++;
    });
    return n;
  }
  function applyFilter(store) {
    var v = fIn.value.trim(), err = null;
    try { flt.re = parseFilter(v); } catch (e) { flt.re = null; err = e; }
    if (store) sset(FKEY, fIn.value);
    fClear.hidden = !fIn.value;
    fIn.closest('.ask-filter').classList.toggle('is-bad', !!err);
    var n = markMatches();
    if (err) {
      fIn.setAttribute('aria-invalid', 'true');
      fMsg.textContent = 'no filter';
      fErr.textContent = 'Not a valid regular expression: ' + String(err.message || err).replace(/^Invalid regular expression: /, '');
    } else {
      fIn.removeAttribute('aria-invalid');
      fErr.textContent = '';
      fMsg.textContent = flt.re ? n + ' of ' + S.stars.length + ' match' : '';
    }
    kick();
  }
  fIn.value = sget(FKEY) || '';
  fIn.addEventListener('input', function () { clearTimeout(fTimer); fTimer = setTimeout(function () { applyFilter(true); }, 120); });
  fIn.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && fIn.value) { e.stopPropagation(); fIn.value = ''; applyFilter(true); }
  });
  fClear.addEventListener('click', function () { fIn.value = ''; applyFilter(true); fIn.focus(); });
  function setStatus(text, state) {
    statusText.textContent = text;
    statusBox.setAttribute('data-state', state || 'idle');
  }
  // wide screens: the chat and the sky fill the viewport below the page header, so the
  // composer is always on screen; narrow screens stack them and let the page scroll
  var pageEl = document.querySelector('.ask-page'), gridEl = document.querySelector('.ask-grid'),
      capEl = document.querySelector('.ask-sky-cap'), narrow = window.matchMedia('(max-width: 991.98px)');
  function fit() {
    if (narrow.matches) { pageEl.style.removeProperty('--ask-h'); pageEl.style.removeProperty('--ask-sky-h'); return; }
    var top = gridEl.getBoundingClientRect().top + window.scrollY;
    var h = Math.max(480, window.innerHeight - top - 16);
    pageEl.style.setProperty('--ask-h', h + 'px');
    var fEl = document.querySelector('.ask-filter');
    pageEl.style.setProperty('--ask-sky-h', Math.max(320, h - (capEl ? capEl.offsetHeight + 12 : 0) -
                                                        (fEl ? fEl.offsetHeight + 8 : 0)) + 'px');
  }
  fit();
  window.addEventListener('resize', fit);
  C.onTheme(function () { S.readTokens(); kick(); });
  document.addEventListener('visibilitychange', kick);
  C.whenVisible(skyEl, function (v) { onScreen = v; kick(); });
  if ('ResizeObserver' in window) new ResizeObserver(layout).observe(skyEl);
  else window.addEventListener('resize', layout);
  S.readTokens(); layout(); applyFilter(false);

  /* ── rendering a turn ─────────────────────────────────────────────────────────────────── */
  function newTurn(q, extra) {
    return { id: 't' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), q: q,
             note: (extra && extra.note) || '', confirm: (extra && extra.confirm) || [],
             model: (extra && extra.model) || '', status: 'running', models: [], shortlist: [], steps: [],
             answer: '', confidence: null, citations: [], caveats: [], pending: [], connections: [], decisions: {}, error: null,
             plan: null,
             stopped_by: '', duration_ms: null, open: {} };
  }

  function turnEl(t) {
    var art = document.getElementById(t.id);
    if (art) return art;
    art = el('article', 'ask-turn'); art.id = t.id;
    var qRow = el('div', 'ask-row ask-row-user');
    var qb = el('div', 'ask-bubble ask-bubble-user');
    if (t.note) qb.appendChild(el('div', 'ask-note', t.note));
    qb.appendChild(el('div', 'ask-q-text', t.q));
    qRow.appendChild(qb);
    var aRow = el('div', 'ask-row ask-row-sajha');
    var av = el('div', 'ask-avatar'); av.setAttribute('aria-hidden', 'true'); av.appendChild(icon('stars'));
    var ab = el('div', 'ask-bubble ask-bubble-sajha');
    ab.setAttribute('aria-label', 'SAJHA’s answer');
    ['head', 'short', 'plan', 'chain', 'confirm', 'answer', 'cites', 'foot'].forEach(function (k) {
      var part = el('div', 'ask-part ask-' + k); part.setAttribute('data-part', k); ab.appendChild(part);
    });
    aRow.appendChild(av); aRow.appendChild(ab);
    art.appendChild(qRow); art.appendChild(aRow);
    logEl.appendChild(art);
    emptyEl.hidden = true;
    return art;
  }
  function part(t, k) { return turnEl(t).querySelector('[data-part="' + k + '"]'); }

  function paintHead(t) {
    var h = part(t, 'head'); h.textContent = '';
    h.appendChild(el('span', 'ask-who', 'SAJHA'));
    if (t.models.length) h.appendChild(el('span', 'ask-model-tag', t.models.join(', ')));
    if (t.confidence != null && !t.pending.length && !(t.connections || []).length) {      // a paused ask has no answer to score
      var b = el('span', 'ask-conf ask-conf-' + tone(t.confidence));
      b.title = 'Confidence comes from the tool results the answer rests on (the composition framework), not from the model.';
      b.appendChild(el('span', 'ask-conf-l', 'confidence '));
      var v = el('span', 'ask-conf-v', t.confidence.toFixed(2)); v.setAttribute('data-v', t.confidence);
      b.appendChild(v);
      h.appendChild(b);
    } else if (t.status === 'running') {
      var th = el('span', 'ask-thinking'); th.appendChild(el('span', '', 'working'));
      var dots = el('span', 'ask-dots'); dots.setAttribute('aria-hidden', 'true');
      dots.appendChild(el('i')); dots.appendChild(el('i')); dots.appendChild(el('i'));
      th.appendChild(dots); h.appendChild(th);
    }
  }
  function countUp(t) {
    var v = part(t, 'head').querySelector('.ask-conf-v');
    if (!v || reduce) return;
    var target = t.confidence, t0 = performance.now();
    (function step(now) {
      var p = ease((now - t0) / 900);
      v.textContent = (target * p).toFixed(2);
      if (p < 1) requestAnimationFrame(step);
    })(t0);
  }
  function paintShort(t) {
    var s = part(t, 'short'); s.textContent = '';
    if (!t.shortlist.length) return;
    var d = el('details', 'ask-shortlist');
    if (t.open.short) d.open = true;
    d.addEventListener('toggle', function () { t.open.short = d.open; save(); });
    var sum = el('summary');
    sum.appendChild(icon('funnel'));
    sum.appendChild(document.createTextNode(' Considered ' + t.shortlist.length + ' tool' + (t.shortlist.length === 1 ? '' : 's')));
    d.appendChild(sum);
    var ul = el('ul', 'ask-short-list');
    t.shortlist.forEach(function (x) {
      var li = el('li');
      li.appendChild(el('code', '', x.name));
      li.appendChild(el('span', 'ask-score', (x.score != null ? Number(x.score).toFixed(2) : '')));
      if (x.description) li.title = x.description;
      ul.appendChild(li);
    });
    d.appendChild(ul);
    s.appendChild(d);
  }
  function paintPlan(t) {
    var p = part(t, 'plan'); p.textContent = '';
    if (!t.plan || !(t.plan.steps || []).length) return;
    var d = el('details', 'ask-shortlist ask-plan');
    if (t.open.plan) d.open = true;
    d.addEventListener('toggle', function () { t.open.plan = d.open; save(); });
    var sum = el('summary');
    sum.appendChild(icon('list-check'));
    var n = t.plan.steps.length;
    sum.appendChild(document.createTextNode(' Plan: ' + n + ' step' + (n === 1 ? '' : 's') +
      (t.plan.planner ? ' (' + t.plan.planner + (t.plan.revision ? ', revised' : '') + ')' : '')));
    d.appendChild(sum);
    var ol = el('ol', 'ask-plan-list');
    ol.style.margin = '.35rem 0 0'; ol.style.paddingLeft = '1.4rem'; ol.style.fontSize = '.8rem';
    t.plan.steps.forEach(function (ps) {
      var run = t.steps.filter(function (st) { return st.id === ps.call_id; })[0];
      var state = run ? (!run.done ? 'running' : run.ok ? 'done' : (run.status || 'failed').replace(/_/g, ' ')) : (ps.status || 'pending');
      var li = el('li');
      li.appendChild(el('code', '', ps.tool));
      if (ps.depends_on && ps.depends_on.length) li.appendChild(document.createTextNode(' after ' + ps.depends_on.join(', ')));
      if (ps.why) li.appendChild(document.createTextNode(' · ' + ps.why));
      li.appendChild(el('span', 'ask-score', ' ' + state));
      li.title = ps.id + ' ' + pretty(ps.arguments || {});
      ol.appendChild(li);
    });
    d.appendChild(ol);
    p.appendChild(d);
  }
  function stepState(st) {
    if (!st.done) return 'run';
    if (st.status === 'needs_confirmation' || st.status === 'needs_connection') return 'wait';
    return st.ok ? 'ok' : 'bad';
  }
  function paintChain(t) {
    var c = part(t, 'chain'); c.textContent = '';
    if (!t.steps.length) return;
    var ol = el('ol', 'ask-steps'); ol.setAttribute('aria-label', 'Tool calls');
    t.steps.forEach(function (st, i) {
      var li = el('li', 'ask-step is-' + stepState(st));
      var cited = t.citations.indexOf(st.id);
      var btn = el('button', 'ask-step-btn'); btn.type = 'button';
      var open = !!t.open[st.id];
      btn.setAttribute('aria-expanded', String(open));
      var rawId = t.id + '-raw-' + i; btn.setAttribute('aria-controls', rawId);
      var stIcon = { ok: 'check-circle-fill', bad: 'x-circle-fill', run: 'hourglass-split', wait: 'pause-circle-fill' }[stepState(st)];
      btn.appendChild(icon(stIcon));
      btn.appendChild(el('code', 'ask-step-name', st.name));
      var meta = st.done ? (st.status === 'needs_confirmation' ? 'waiting for you'
                            : st.status === 'needs_connection' ? 'needs your account'
                            : (st.latency_ms != null ? st.latency_ms + ' ms' : ''))
                         : 'running';
      if (meta) btn.appendChild(el('span', 'ask-step-meta', meta));
      if (cited >= 0) btn.appendChild(el('span', 'ask-cite-no', '[' + (cited + 1) + ']'));
      btn.appendChild(icon(open ? 'chevron-up' : 'chevron-down'));
      var sr = el('span', 'visually-hidden', open ? ' (hide arguments and result)' : ' (show arguments and result)');
      btn.appendChild(sr);
      btn.addEventListener('click', function () {
        t.open[st.id] = !t.open[st.id]; save(); paintChain(t);
        var again = part(t, 'chain').querySelectorAll('.ask-step-btn')[i]; if (again) again.focus();
      });
      li.appendChild(btn);
      if (st.done && st.summary) li.appendChild(el('div', 'ask-step-sum', clip(st.summary, 200)));
      var raw = el('div', 'ask-step-raw'); raw.id = rawId; raw.hidden = !open;
      raw.appendChild(el('div', 'ask-raw-h', 'Arguments'));
      raw.appendChild(el('pre', '', pretty(st.arguments || {})));
      raw.appendChild(el('div', 'ask-raw-h', 'Result' + (st.status && st.status !== 'ok' ? ' (' + st.status + ')' : '')));
      raw.appendChild(el('pre', '', st.done ? pretty(st.summary || '') : '…'));
      li.appendChild(raw);
      ol.appendChild(li);
    });
    c.appendChild(ol);
  }
  function paintConfirm(t) {
    var c = part(t, 'confirm'); c.textContent = '';
    t.pending.forEach(function (p) {
      var card = el('div', 'ask-confirm-card'); card.setAttribute('role', 'group');
      card.setAttribute('aria-label', 'Confirm ' + p.name);
      var h = el('div', 'ask-confirm-h'); h.appendChild(icon('shield-exclamation'));
      h.appendChild(document.createTextNode(' Run '));
      h.appendChild(el('code', '', p.name));
      h.appendChild(document.createTextNode('?'));
      card.appendChild(h);
      card.appendChild(el('p', 'ask-confirm-why', 'This tool is marked destructive (it can change or delete data), so SAJHA has not run it. ' +
        'Confirm to ask again with permission to run exactly this call.'));
      card.appendChild(el('pre', 'ask-confirm-args', pretty(p.arguments || {})));
      var dec = t.decisions[p.fingerprint];
      if (dec) {
        card.appendChild(el('div', 'ask-confirm-done', dec === 'confirmed' ? 'Confirmed: the answer follows below.' : 'Cancelled: not run.'));
      } else {
        var bar = el('div', 'ask-confirm-bar');
        var yes = el('button', 'btn btn-sm btn-primary', 'Confirm and run'); yes.type = 'button';
        var no = el('button', 'btn btn-sm btn-outline-secondary', 'Cancel'); no.type = 'button';
        yes.addEventListener('click', function () {
          if (busy) return;
          t.decisions[p.fingerprint] = 'confirmed'; save(); paintConfirm(t);
          ask(t.q, { confirm: [p.fingerprint], note: 'Confirmed: run ' + p.name });
        });
        no.addEventListener('click', function () {
          t.decisions[p.fingerprint] = 'cancelled'; save(); paintConfirm(t);
          say('Cancelled. ' + p.name + ' was not run.'); input.focus();
        });
        bar.appendChild(yes); bar.appendChild(no); card.appendChild(bar);
      }
      c.appendChild(card);
    });
    (t.connections || []).forEach(function (p) {
      // a connected-accounts tool and no usable link: send the user to link it, then ask again
      var card = el('div', 'ask-confirm-card ask-connect-card'); card.setAttribute('role', 'group');
      card.setAttribute('aria-label', 'Connect ' + p.provider_title);
      var h = el('div', 'ask-confirm-h'); h.appendChild(icon('link-45deg'));
      h.appendChild(document.createTextNode(' Connect ' + p.provider_title));
      card.appendChild(h);
      card.appendChild(el('p', 'ask-confirm-why', (p.reason === 'reauth_required'
        ? p.provider_title + ' no longer accepts your linked account. '
        : p.reason === 'insufficient_scope' ? 'Your linked ' + p.provider_title + ' account does not grant what ' + p.name + ' needs. '
        : p.reason === 'sign_in_required' ? 'Connected accounts belong to signed-in users. '
        : 'Your ' + p.provider_title + ' account is not linked yet. ') +
        p.name + ' acts as you in ' + p.provider_title + '. Link it (it opens in a new tab), then ask again.'));
      var bar = el('div', 'ask-confirm-bar');
      if (p.reason !== 'sign_in_required') {
        var go = el('a', 'btn btn-sm btn-primary', 'Connect ' + p.provider_title);
        go.href = p.connect_url; go.target = '_blank'; go.rel = 'noopener';
        bar.appendChild(go);
      }
      var again = el('button', 'btn btn-sm btn-outline-secondary', 'I have connected it: ask again'); again.type = 'button';
      again.addEventListener('click', function () {
        if (busy) return;
        ask(t.q, { note: 'Connected ' + p.provider_title + ': asking again' });
      });
      bar.appendChild(again); card.appendChild(bar);
      c.appendChild(card);
    });
  }
  function paintAnswer(t) {
    var a = part(t, 'answer'); a.textContent = '';
    if (t.answer) a.appendChild(el('p', 'ask-answer-text', t.answer));
    if (t.status === 'running' && t.answering) a.lastChild && a.lastChild.appendChild(el('span', 'ask-caret'));
    if (t.error) {
      var e = el('div', 'ask-error'); e.setAttribute('role', 'alert');
      e.appendChild(icon('exclamation-octagon'));
      var txt = el('span'); txt.textContent = ' ' + t.error.message;
      e.appendChild(txt);
      if (t.error.login) {
        var link = el('a', '', 'Sign in again'); link.href = '/login';
        e.appendChild(document.createTextNode(' ')); e.appendChild(link);
      }
      a.appendChild(e);
    }
    if (t.status === 'stopped') a.appendChild(el('div', 'ask-stopped', 'Stopped. The rest of this answer was not fetched.'));
  }
  function paintCites(t) {
    var c = part(t, 'cites'); c.textContent = '';
    if (t.status === 'running') return;
    var cited = t.citations.map(function (id, i) {
      var st = t.steps.filter(function (s) { return s.id === id; })[0];
      return st ? [i + 1, st.name] : null;
    }).filter(Boolean);
    if (cited.length) {
      var p = el('div', 'ask-sources'); p.appendChild(el('span', 'ask-sources-h', 'Sources'));
      cited.forEach(function (x) {
        var s = el('span', 'ask-source'); s.appendChild(el('span', 'ask-cite-no', '[' + x[0] + ']'));
        s.appendChild(el('code', '', x[1])); p.appendChild(s);
      });
      c.appendChild(p);
    }
    if (t.caveats.length) {
      var ul = el('ul', 'ask-caveats'); ul.setAttribute('aria-label', 'Caveats');
      t.caveats.forEach(function (cv) { var li = el('li'); li.appendChild(icon('info-circle')); li.appendChild(document.createTextNode(' ' + cv)); ul.appendChild(li); });
      c.appendChild(ul);
    }
  }
  function paintFoot(t) {
    var f = part(t, 'foot'); f.textContent = '';
    if (t.status === 'running') return;
    var bits = [];
    if (t.duration_ms != null) bits.push((t.duration_ms / 1000).toFixed(2) + ' s');
    if (t.usage && t.usage.total_tokens) bits.push(t.usage.total_tokens + ' tokens');
    if (t.stopped_by && t.stopped_by !== 'answer') bits.push('stopped by ' + t.stopped_by.replace(/_/g, ' '));
    if (bits.length) f.appendChild(el('span', '', bits.join(' · ')));
  }
  function paint(t, parts) {
    (parts || ['head', 'short', 'plan', 'chain', 'confirm', 'answer', 'cites', 'foot']).forEach(function (k) {
      ({ head: paintHead, short: paintShort, plan: paintPlan, chain: paintChain, confirm: paintConfirm, answer: paintAnswer,
         cites: paintCites, foot: paintFoot })[k](t);
    });
  }

  /* ── applying one event (to the turn, the bubble and the sky) ─────────────────────────── */
  // how long each event holds the stage before the next is played (ms)
  var HOLD = { shortlist: 900, model: 250, plan: 700, tool_call: 650, tool_result: 600, needs_confirmation: 300, needs_connection: 300,
               answer_delta: 45, answer: 0, confidence: 900, error: 0, done: 0 };

  function apply(t, ev) {
    var now = performance.now();
    switch (ev.type) {
      case 'shortlist':
        t.shortlist = (ev.tools || []).map(function (x) { return { name: x.name, score: x.score, description: x.description }; });
        paint(t, ['short']);
        skyShortlist(ev.tools, now);
        setStatus(t.shortlist.length ? 'Considering ' + t.shortlist.length + ' tools' : 'No tools to offer', 'busy');
        break;
      case 'model':
        if (t.models.indexOf(ev.model) < 0) t.models.push(ev.model);
        if (/^mock\//.test(ev.model || '')) mockPill.hidden = false;
        paint(t, ['head']);
        setStatus('Planning with ' + ev.model, 'busy');
        break;
      case 'plan':
        t.plan = { planner: ev.planner || '', revision: ev.revision || 0, steps: ev.steps || [] };
        paint(t, ['plan']);
        setStatus('Planned ' + t.plan.steps.length + ' step' + (t.plan.steps.length === 1 ? '' : 's'), 'busy');
        break;
      case 'tool_call':
        callLog.start(t, ev.id, ev.name);
        t.steps.push({ id: ev.id, name: ev.name, arguments: ev.arguments, done: false });
        paint(t, ['chain']);
        skyCall(ev.id, ev.name, now);
        setStatus('Calling ' + ev.name, 'busy');
        say('Calling ' + ev.name);
        break;
      case 'tool_result':
        t.steps.forEach(function (st) {
          if (st.id !== ev.id) return;
          st.done = true; st.ok = !!ev.ok; st.summary = ev.summary; st.latency_ms = ev.latency_ms;
          if (!st.status) st.status = ev.ok ? 'ok' : 'error';
        });
        paint(t, ['chain', 'plan']);
        var waiting = t.steps.some(function (st) { return st.id === ev.id && (st.status === 'needs_confirmation' || st.status === 'needs_connection'); });
        skyResult(ev.id, waiting ? null : !!ev.ok, waiting ? 'waiting for you' : ev.summary, now);
        callLog.end(ev.id, waiting ? null : !!ev.ok, ev.latency_ms);
        if (!waiting) setStatus(ev.name + (ev.ok ? ' answered' : ' failed'), ev.ok ? 'busy' : 'bad');
        break;
      case 'needs_confirmation':
        t.pending.push({ id: ev.id, name: ev.name, arguments: ev.arguments, fingerprint: ev.fingerprint, reason: ev.reason });
        t.steps.forEach(function (st) { if (st.id === ev.id) st.status = 'needs_confirmation'; });
        paint(t, ['confirm']);
        setStatus(ev.name + ' needs your confirmation', 'wait');
        break;
      case 'needs_connection':
        t.connections = t.connections || [];
        if (!t.connections.some(function (c) { return c.provider === ev.provider; }))
          t.connections.push({ id: ev.id, name: ev.name, provider: ev.provider, provider_title: ev.provider_title,
                               connect_url: ev.connect_url, reason: ev.reason });
        t.steps.forEach(function (st) { if (st.id === ev.id) st.status = 'needs_connection'; });
        paint(t, ['confirm']);
        setStatus(ev.name + ' needs your ' + ev.provider_title + ' account', 'wait');
        break;
      case 'answer_delta':
        t.answer += ev.text || ''; t.answering = true;
        paint(t, ['answer']);
        setStatus('Answering', 'busy');
        break;
      case 'answer':
        t.answer = ev.text || ''; t.answering = false;
        paint(t, ['answer']);
        break;
      case 'confidence':
        t.confidence = Number(ev.value) || 0; t.basis = ev.basis;
        paint(t, ['head']); countUp(t);
        break;
      case 'error':
        t.error = { code: ev.code, message: ev.message || 'The question could not be answered.', login: !!ev.login };
        paint(t, ['answer']);
        setStatus('Error', 'bad');
        break;
      case 'done':
        finishWith(t, ev.result);
        break;
    }
    toBottom();
    return reduce ? 0 : (HOLD[ev.type] || 0);
  }

  function finishWith(t, r) {
    if (r) {
      t.citations = r.citations || []; t.caveats = r.caveats || []; t.stopped_by = r.stopped_by || '';
      t.duration_ms = r.duration_ms; t.usage = r.usage; t.models = r.models && r.models.length ? r.models : t.models;
      if (r.answer && !t.answer) t.answer = r.answer;
      if (r.confidence != null && t.confidence == null) t.confidence = r.confidence;
      (r.steps || []).forEach(function (rs) {
        t.steps.forEach(function (st) {
          if (st.id === rs.id) { st.status = rs.status; st.ok = rs.ok; st.summary = rs.summary; st.latency_ms = rs.latency_ms; st.done = true; }
        });
      });
      if (r.error && !t.error && r.stopped_by === 'error') t.error = { code: 'error', message: r.error };
      if (r.plan && r.plan.length) t.plan = { planner: r.planner || (t.plan && t.plan.planner) || '', revision: t.plan ? t.plan.revision : 0, steps: r.plan };
      if (r.conversation_id) sset(CKEY, r.conversation_id);    // later questions continue this conversation
    }
    if (t.status === 'running') t.status = t.error ? 'error' : 'done';
    t.answering = false;
    paint(t);
    sk.phase = 'done';
    if ((t.connections || []).length && !t.error) setStatus('Waiting for you to connect ' + t.connections.map(function (c) { return c.provider_title; }).join(', '), 'wait');
    else if (t.pending.length && !t.error) setStatus('Waiting for your confirmation', 'wait');
    else if (t.error) setStatus('Error', 'bad');
    else setStatus('Answered' + (t.confidence != null ? ' · confidence ' + t.confidence.toFixed(2) : ''), 'done');
    var msg = t.error ? 'Error: ' + t.error.message
      : t.pending.length ? 'SAJHA needs your confirmation to run ' + t.pending.map(function (p) { return p.name; }).join(', ') + '.'
      : 'Answer: ' + t.answer + (t.confidence != null ? ' Confidence ' + t.confidence.toFixed(2) + '.' : '');
    say(msg);
    save();
    kick();
  }

  /* ── the event queue ──────────────────────────────────────────────────────────────────── */
  var queue = [], playing = false, timer = 0, current = null, busy = false, ctrl = null, gen = 0;
  function enqueue(ev) { queue.push(ev); pump(); }
  function pump() {
    while (!playing && queue.length) {
      var ev = queue.shift(), wait = apply(current, ev);
      if (ev.type === 'done') { endBusy(); return; }
      if (wait > 0) {
        playing = true;
        timer = setTimeout(function () { playing = false; timer = 0; pump(); }, wait);
      }
    }
  }
  function startBusy() {
    busy = true; sendBtn.disabled = true; stopBtn.hidden = false;
    Array.prototype.forEach.call(document.querySelectorAll('.ask-chip'), function (b) { b.disabled = true; });
  }
  function endBusy() {
    busy = false; sendBtn.disabled = false; stopBtn.hidden = true; ctrl = null;
    Array.prototype.forEach.call(document.querySelectorAll('.ask-chip'), function (b) { b.disabled = false; });
    if (document.activeElement === stopBtn || document.activeElement === document.body) input.focus();
  }

  /* ── asking ───────────────────────────────────────────────────────────────────────────── */
  function parseSSE(block) {
    var data = [];
    block.split('\n').forEach(function (line) {
      if (line.indexOf('data:') === 0) data.push(line.slice(5).replace(/^ /, ''));
    });
    if (!data.length) return null;
    try { return JSON.parse(data.join('\n')); } catch (e) { return null; }
  }
  function fail(t, message, extra) {
    enqueue({ type: 'error', code: 'client', message: message, login: !!(extra && extra.login) });
    enqueue({ type: 'done', result: null });
  }

  function ask(q, opts) {
    q = (q || '').trim();
    if (!q || busy) return;
    opts = opts || {};
    var model = modelSel.value || '';
    var t = newTurn(q, { note: opts.note, confirm: opts.confirm, model: model });
    turns.push(t); save();
    current = t; queue = []; gen++;
    var myGen = gen;
    paint(t);
    toBottom(true);
    if (narrow.matches) turnEl(t).scrollIntoView({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' });
    skyReset(); setStatus('Finding tools for your question', 'busy');
    startBusy();
    var body = { question: q, conversation_id: sget(CKEY) || 'new' };
    if (model) body.model = model;
    if (opts.confirm && opts.confirm.length) body.confirm = opts.confirm;
    ctrl = window.AbortController ? new AbortController() : null;
    var gotDone = false;
    fetch('/api/ai/ask', {
      method: 'POST', credentials: 'same-origin', signal: ctrl ? ctrl.signal : undefined,
      headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (myGen !== gen) return;
      if (r.status === 401) { gotDone = true; return fail(t, 'Your session has ended.', { login: true }); }
      var ct = r.headers.get('content-type') || '';
      if (!r.ok || ct.indexOf('text/event-stream') < 0) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (myGen !== gen) return;
          if (r.ok && j && j.question !== undefined) {           // a JSON AskResult: replay it as events
            enqueue({ type: 'shortlist', tools: (j.shortlist || []).map(function (n) { return { name: n }; }) });
            (j.steps || []).forEach(function (s) {
              enqueue({ type: 'tool_call', id: s.id, name: s.name, arguments: s.arguments });
              enqueue({ type: 'tool_result', id: s.id, name: s.name, ok: s.ok, summary: s.summary, latency_ms: s.latency_ms });
            });
            enqueue({ type: 'answer', text: j.answer }); enqueue({ type: 'confidence', value: j.confidence });
            gotDone = true; enqueue({ type: 'done', result: j });
            return;
          }
          if (r.status === 404 && j && j.error === 'conversation not found') {
            sdel(CKEY);               // expired or deleted: the next question starts a new conversation
            return fail(t, 'This conversation is no longer kept on the server. Ask again to start a new one.');
          }
          fail(t, (j && j.error) || ('The server answered ' + r.status + '.'));
          gotDone = true;
        });
      }
      var reader = r.body.getReader(), dec = new TextDecoder(), buf = '';
      function read() {
        return reader.read().then(function (x) {
          if (myGen !== gen) { try { reader.cancel(); } catch (e) { /* gone */ } return; }
          if (x.done) {
            if (buf.trim()) { var last = parseSSE(buf.replace(/\r\n?/g, '\n')); if (last) { if (last.type === 'done') gotDone = true; enqueue(last); } }
            if (!gotDone) fail(t, 'The connection closed before the answer was complete.');
            return;
          }
          buf += dec.decode(x.value, { stream: true }).replace(/\r\n?/g, '\n');
          var i;
          while ((i = buf.indexOf('\n\n')) >= 0) {
            var ev = parseSSE(buf.slice(0, i)); buf = buf.slice(i + 2);
            if (ev && ev.type) { if (ev.type === 'done') gotDone = true; enqueue(ev); }
          }
          return read();
        });
      }
      return read();
    }).catch(function (e) {
      if (myGen !== gen) return;
      if (e && e.name === 'AbortError') return;
      fail(t, 'Could not reach the server (' + (e && e.message ? e.message : 'network error') + ').');
    });
  }

  function stop() {
    if (!busy || !current) return;
    gen++;
    if (ctrl) { try { ctrl.abort(); } catch (e) { /* already done */ } }
    if (timer) { clearTimeout(timer); timer = 0; }
    queue = []; playing = false;
    var t = current;
    t.status = 'stopped'; t.answering = false;
    t.steps.forEach(function (st) { if (!st.done) { st.done = true; st.ok = false; st.status = 'stopped'; st.summary = 'stopped before a result arrived'; } });
    paint(t); save();
    sk.phase = 'done'; setStatus('Stopped', 'idle'); kick();
    say('Stopped.');
    endBusy(); input.focus();
  }

  /* ── wiring ───────────────────────────────────────────────────────────────────────────── */
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var q = input.value;
    if (!q.trim() || busy) return;
    input.value = '';
    ask(q);
  });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { cancelable: true })); }
  });
  stopBtn.addEventListener('click', stop);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && busy) stop(); });
  Array.prototype.forEach.call(document.querySelectorAll('.ask-chip'), function (b) {
    b.addEventListener('click', function () { if (!busy) ask(b.getAttribute('data-q')); });
  });
  newBtn.addEventListener('click', function () {
    if (busy) stop();
    turns = []; sdel(KEY); sdel(CKEY);           // the next question starts a new conversation
    Array.prototype.forEach.call(logEl.querySelectorAll('.ask-turn'), function (a) { a.remove(); });
    emptyEl.hidden = false;
    skyReset(); setStatus('Waiting for a question', 'idle');
    say('New chat.'); input.focus();
  });

  // the model picker: aliases from the gateway (admins), or the enabled tool-capable models
  var savedModel = sget(MKEY) || '';
  modelSel.addEventListener('change', function () { sset(MKEY, modelSel.value); });
  function addOption(value, label) {
    if (modelSel.querySelector('option[value="' + value.replace(/"/g, '') + '"]')) return;
    var o = el('option', '', label); o.value = value; modelSel.appendChild(o);
  }
  function pickSaved() { if (savedModel && modelSel.querySelector('option[value="' + savedModel.replace(/"/g, '') + '"]')) modelSel.value = savedModel; }
  if (D.is_admin) {
    fetch('/api/ai/config', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
      if (!j) return;
      var al = j.resolved_aliases || {};
      modelSel.options[0].textContent = 'default' + (al['default'] ? ' · ' + al['default'] : '');
      Object.keys(al).forEach(function (k) { if (k !== 'default' && k !== 'embedding') addOption(k, k + ' · ' + al[k]); });
      mockPill.hidden = !j.mock_active;
      pickSaved();
    }).catch(function () { /* the picker keeps "default" */ });
  } else {
    fetch('/api/ai/models', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
      ((j && j.models) || []).forEach(function (m) {
        if (m.enabled && m.supports_tools) addOption(m.provider_type + '/' + m.model_id, m.provider_type + '/' + m.model_id);
      });
      pickSaved();
    }).catch(function () { /* the picker keeps "default" */ });
  }

  // restore this tab's conversation, still; the sky shows the last answer's chain
  turns.forEach(function (t) {
    if (t.status === 'running') { t.status = 'stopped'; }
    paint(t);
    if (t.models.some(function (m) { return /^mock\//.test(m); })) mockPill.hidden = false;
  });
  if (turns.length) {
    var lt = turns[turns.length - 1], past = performance.now() - 5000;
    skyShortlist(lt.shortlist, past);
    lt.steps.forEach(function (st) {
      skyCall(st.id, st.name, past);
      var held = st.status === 'needs_confirmation' || st.status === 'needs_connection';
      if (st.done) skyResult(st.id, held ? null : !!st.ok, held ? 'waiting for you' : st.summary || '', past);
    });
    setStatus(lt.status === 'done' ? 'Answered' + (lt.confidence != null ? ' · confidence ' + lt.confidence.toFixed(2) : '') : 'Waiting for a question',
              lt.status === 'done' ? 'done' : 'idle');
    toBottom(true);
  }
})();
