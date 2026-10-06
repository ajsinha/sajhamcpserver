/*
 * SAJHA landing page: the constellation (hero) and the wire (how it works).
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
 *
 * The catalog (provider groups and their tool counts) comes from the live registry through
 * #lpData. Canvas colours are --sajha-* tokens, read with getComputedStyle and read again
 * whenever the theme changes. With prefers-reduced-motion both figures stand still on their
 * final frame.
 */
(function () {
  'use strict';
  var root = document.documentElement;
  var mm = function (q) { return window.matchMedia ? window.matchMedia(q) : { matches: false }; };
  var reduce = mm('(prefers-reduced-motion: reduce)').matches;
  var data = {};
  try { data = JSON.parse(document.getElementById('lpData').textContent) || {}; } catch (e) { /* no data */ }

  // one theme signal for both figures: the menu sets data-theme on <html>; no data-theme
  // follows the system, so a system light/dark switch counts too
  var themeFns = [];
  var themeChanged = function () { themeFns.forEach(function (f) { f(); }); };
  new MutationObserver(themeChanged).observe(root, { attributes: true, attributeFilter: ['data-theme', 'data-bs-theme'] });
  var scheme = mm('(prefers-color-scheme: dark)');
  if (scheme.addEventListener) scheme.addEventListener('change', themeChanged);
  else if (scheme.addListener) scheme.addListener(themeChanged);

  function tok(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
  function whenVisible(el, fn) {
    if (!('IntersectionObserver' in window)) { fn(true); return; }
    new IntersectionObserver(function (es) { fn(es[es.length - 1].isIntersecting); }, { threshold: 0.15 }).observe(el);
  }

  /* ── 1. The constellation ─────────────────────────────────────────────────────────────── */
  (function constellation() {
    var sky = document.getElementById('lpSky');
    if (!sky) return;
    // The questions are illustrative; every tool name is a real SAJHA tool (config/tools).
    var RAW = [
      { q: "Is Apple's dividend safe if rates keep rising?",
        steps: [['yf_dividends', '$1.00 / yr, +4.3% CAGR'], ['fred_10yr_treasury', '10Y at 4.31%'],
                ['calc_percentage_change', 'payout ratio 15%'], ['calc_sharpe_ratio', 'Sharpe 1.12']],
        conf: 0.86, a: 'Yes. The payout is about 15% of earnings, so a 50bp rise in the 10-year barely touches it.' },
      { q: 'Who inside Nvidia has been buying or selling its stock?',
        steps: [['edgar_insider_transactions', '42 Form 4 filings, 90d'], ['yf_insider_purchases', 'net −$310M'],
                ['tavily_news_search', '3 articles on plans']],
        conf: 0.91, a: 'Mostly scheduled 10b5-1 sales by two executives; no open-market buying in 90 days.' },
      { q: 'Is the US yield curve still inverted?',
        steps: [['fred_2yr_treasury', '2Y at 3.92%'], ['fred_10yr_treasury', '10Y at 4.31%'],
                ['fred_yield_spread', '10Y−2Y +39bp'], ['calc_percentage_change', '+81bp in 12 months']],
        conf: 0.94, a: 'No. The 10Y−2Y spread is +39bp, after twelve months of steepening.' }
    ];
    var GROUPS = (data.groups || []).filter(function (g) { return g[1] > 0; });
    var have = {};
    GROUPS.forEach(function (g) { have[g[0]] = 1; });
    var grp = function (name) { return name.indexOf('_') >= 0 ? name.split('_')[0] : name; };
    var SCENES = RAW.map(function (s) {
      return { q: s.q, conf: s.conf, a: s.a, steps: s.steps.filter(function (st) { return have[grp(st[0])]; }) };
    }).filter(function (s) { return s.steps.length; });
    if (!SCENES.length) { sky.closest('.lp2-sky-wrap').hidden = true; return; }

    var cv = document.getElementById('lpSkyCanvas'), cx = cv.getContext('2d');
    var $ = function (id) { return document.getElementById(id); };
    var qEl = $('lpSkyQ'), ans = $('lpSkyAns'), confEl = $('lpSkyConf'), ansText = $('lpSkyAnsText'),
        ansChain = $('lpSkyChain'), sceneNo = $('lpSkyScene'), srDesc = $('lpSkyDesc'),
        pauseBtn = $('lpSkyPause'), nextBtn = $('lpSkyNext');
    var total = data.total || GROUPS.reduce(function (a, g) { return a + g[1]; }, 0);
    $('lpSkyStats').textContent = total + ' tools · ' + GROUPS.length + ' provider groups';

    var T = {}, colors = {};
    function readTokens() {
      var font = getComputedStyle(document.body).fontFamily;
      T = { ink: tok('--sajha-ink'), slate: tok('--sajha-slate'), accent: tok('--sajha-crimson'),
            indigo: tok('--sajha-indigo'), ok: tok('--sajha-ok'), warn: tok('--sajha-warn'),
            surface: tok('--sajha-surface'), border: tok('--sajha-border'), font: font,
            mono: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace' };
      var pal = [T.accent, T.indigo, T.ok, T.warn, T.slate];
      GROUPS.forEach(function (g, i) { colors[g[0]] = pal[i % pal.length]; });
    }

    var W = 0, H = 0, stars = [], chains = [], seed = 7;
    var rnd = function () { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
    function rectIn(el, base) {
      var r = el.getBoundingClientRect();
      return { l: r.left - base.left - 12, t: r.top - base.top - 12, r: r.right - base.left + 12, b: r.bottom - base.top + 12 };
    }
    function layout() {
      var dpr = Math.min(window.devicePixelRatio || 1, 2), r = cv.getBoundingClientRect();
      W = r.width; H = r.height;
      if (!W || !H) return;
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed = 7; stars = [];
      // each provider group is a loose cluster on a golden-angle spiral; the biggest sit nearest the middle
      var k = Math.max(0.55, Math.min(1, W / 1000)), cxm = W / 2, cym = H * 0.55, rx = W * 0.44, ry = H * 0.35;
      GROUPS.forEach(function (g, i) {
        var t = i * 2.399963, ring = Math.sqrt((i + 1.5) / (GROUPS.length + 1));
        var gx = cxm + Math.cos(t) * rx * ring, gy = cym + Math.sin(t) * ry * ring;
        var spread = (20 + Math.sqrt(g[1]) * 9) * k;
        for (var n = 0; n < g[1]; n++) {
          var a = rnd() * Math.PI * 2, d = Math.sqrt(rnd()) * spread;
          stars.push({ g: g[0], x: gx + Math.cos(a) * d, y: gy + Math.sin(a) * d * 0.8, r: 1 + rnd() * 1.5, tw: rnd() * 6.28 });
        }
      });
      // the star a named tool stands for: a fixed member of its group, kept clear of the
      // prompt and the answer card, and away from the chain's earlier stars so labels part
      // the answer card sits right, or left when the chain needs the stars it would cover
      var base = cv.getBoundingClientRect(), pr = rectIn(qEl.parentNode, base), side = { R: [pr], L: [pr] };
      if (getComputedStyle(ans).position === 'absolute') {
        var ar = rectIn(ans, base), mir = { l: W - ar.r, r: W - ar.l, t: ar.t, b: ar.b };
        var left = sky.classList.contains('is-ans-left');
        side.R.push(left ? mir : ar); side.L.push(left ? ar : mir);
      }
      var freeIn = function (blocks) {
        return function (s) {
          return s.y > 44 && s.y < H - 34 && !blocks.some(function (b) { return s.x > b.l && s.x < b.r && s.y > b.t && s.y < b.b; });
        };
      };
      var fits = function (sc, f) {
        return sc.steps.every(function (st) { return stars.some(function (s) { return s.g === grp(st[0]) && f(s); }); });
      };
      chains = SCENES.map(function (sc) {
        var picked = [], sd = fits(sc, freeIn(side.R)) || !fits(sc, freeIn(side.L)) ? 'R' : 'L', free = freeIn(side[sd]);
        var steps = sc.steps.map(function (st) {
          var name = st[0], all = stars.filter(function (s) { return s.g === grp(name); });
          var ok = all.filter(free), members = ok.length ? ok : all, h = 0;
          for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
          // a label box: the name chip above the star, its result below
          var box = function (s) {
            var w = name.length * 7.4 + 22, l = Math.min(Math.max(s.x - w / 2, 6), W - w - 6);
            return { l: l, r: l + w, t: s.y - 34, b: s.y + 32 };
          };
          var clear = function (s) {
            var a = box(s);
            return picked.every(function (p) { return a.r < p.b.l || a.l > p.b.r || a.b < p.b.t || a.t > p.b.b; });
          };
          var gap = function (s) { return picked.reduce(function (m, p) { return Math.min(m, Math.hypot(p.s.x - s.x, p.s.y - s.y)); }, 1e9); };
          var best = null;
          for (var j = 0; j < members.length && !best; j++) {
            var c = members[(h + j) % members.length];
            if (clear(c)) best = c;
          }
          if (!best) {          // nothing clear: the least overlap, then the farthest
            var cost = function (s) {
              var a = box(s);
              return picked.reduce(function (m, p) {
                return m + Math.max(0, Math.min(a.r, p.b.r) - Math.max(a.l, p.b.l)) * Math.max(0, Math.min(a.b, p.b.b) - Math.max(a.t, p.b.t));
              }, 0) - gap(s) * 0.01;
            };
            best = members.reduce(function (a, b) { return cost(b) < cost(a) ? b : a; });
          }
          picked.push({ s: best, b: box(best) });
          return { n: name, r: st[1], s: best };
        });
        steps.left = sd === 'L';
        return steps;
      });
      shownScene = -1;
    }

    var TYPE = 1.7, DISCOVER = 0.9, STEP = 1.25, CONF = 1.0, HOLD = 3.2, FADE = 0.8;
    var dur = function (s) { return TYPE + DISCOVER + s.steps.length * STEP + CONF + HOLD + FADE; };
    var ease = function (x) { return 1 - Math.pow(1 - Math.min(Math.max(x, 0), 1), 3); };
    var scene = 0, clock = 0, last = 0, raf = 0, paused = false, onScreen = true, shownQ = null, shownScene = -1, ansOn = null;

    function pill(x, y, w, h) {
      cx.beginPath();
      if (cx.roundRect) cx.roundRect(x, y, w, h, 6); else cx.rect(x, y, w, h);
    }
    function lane(name, x, y, alpha) {
      cx.globalAlpha = alpha; cx.font = '600 12px ' + T.mono;
      var w = cx.measureText(name).width + 14, left = Math.min(Math.max(x - w / 2, 6), W - w - 6), top = y - 30;
      cx.fillStyle = T.surface; cx.strokeStyle = T.border; cx.lineWidth = 1;
      pill(left, top, w, 20); cx.fill(); cx.stroke();
      cx.fillStyle = T.ink; cx.fillText(name, left + 7, top + 14); cx.globalAlpha = 1;
    }
    function result(text, x, y, alpha) {
      if (alpha <= 0) return;
      cx.globalAlpha = alpha; cx.font = '12px ' + T.font;
      var w = cx.measureText(text).width + 10, left = Math.min(Math.max(x - w / 2, 6), W - w - 6);
      cx.fillStyle = T.surface; pill(left, y + 10, w, 18); cx.fill();
      cx.fillStyle = T.slate; cx.fillText(text, left + 5, y + 23); cx.globalAlpha = 1;
    }

    function draw(now) {
      var sc = SCENES[scene], chain = chains[scene] || [];
      var t = reduce ? dur(sc) - FADE - 0.01 : clock;
      var tStep = t - TYPE - DISCOVER, endSteps = TYPE + DISCOVER + chain.length * STEP;
      var fade = 1 - ease((t - (dur(sc) - FADE)) / FADE);

      if (shownScene !== scene) {
        shownScene = scene;
        sceneNo.textContent = 'Question ' + (scene + 1) + ' of ' + SCENES.length;
        srDesc.textContent = 'Question: ' + sc.q + ' Tools chained: ' + sc.steps.map(function (s) { return s[0]; }).join(', ') +
          '. Answer: ' + sc.a;
        ansText.textContent = sc.a;
        sky.classList.toggle('is-ans-left', !!chain.left);
        ansChain.textContent = sc.steps.map(function (s) { return s[0]; }).join(' → ');
      }
      var shown = reduce ? sc.q.length : Math.floor(sc.q.length * ease(t / TYPE)), caret = t < TYPE + DISCOVER && !reduce;
      var key = shown + (caret ? '|' : '');
      if (key !== shownQ) {
        shownQ = key; qEl.textContent = sc.q.slice(0, shown);
        if (caret) { var c = document.createElement('span'); c.className = 'lp2-caret'; qEl.appendChild(c); }
      }

      cx.clearRect(0, 0, W, H);
      var used = {};
      chain.forEach(function (c) { used[c.s.g] = 1; });
      var lit = t > TYPE ? ease((t - TYPE) / DISCOVER) * fade : 0;
      for (var i = 0; i < stars.length; i++) {
        var st = stars[i], tw = reduce ? 0.8 : 0.55 + 0.45 * Math.sin(now / 900 + st.tw), on = used[st.g] ? lit : 0;
        cx.globalAlpha = (0.30 + 0.25 * tw) * (1 - on) + (0.55 + 0.45 * tw) * on;
        cx.fillStyle = colors[st.g];
        cx.beginPath(); cx.arc(st.x, st.y, st.r + on * 0.6, 0, 6.283); cx.fill();
      }
      cx.globalAlpha = 1;

      if (!reduce && t > TYPE && t < TYPE + DISCOVER) {           // the discovery sweep
        var p = ease((t - TYPE) / DISCOVER);
        cx.strokeStyle = T.accent; cx.globalAlpha = 0.35 * (1 - p); cx.lineWidth = 2;
        cx.beginPath(); cx.arc(W / 2, 40, Math.hypot(W, H) * 0.6 * p, 0, 6.283); cx.stroke(); cx.globalAlpha = 1;
      }

      var pb = qEl.parentNode, px = W / 2, py = pb.offsetTop + pb.offsetHeight;
      chain.forEach(function (c, i) {                               // the chain, step by step
        var p = reduce ? 1 : ease((tStep - i * STEP) / (STEP * 0.6));
        if (p <= 0) return;
        cx.strokeStyle = T.accent; cx.lineWidth = 1.8; cx.globalAlpha = 0.85 * fade;
        cx.setLineDash(i === 0 ? [4, 5] : []);
        cx.beginPath(); cx.moveTo(px, py); cx.lineTo(px + (c.s.x - px) * p, py + (c.s.y - py) * p); cx.stroke();
        cx.setLineDash([]);
        if (p > 0.95) {
          cx.globalAlpha = 0.18 * fade; cx.fillStyle = T.accent;
          cx.beginPath(); cx.arc(c.s.x, c.s.y, 14, 0, 6.283); cx.fill();
          cx.globalAlpha = fade;
          cx.beginPath(); cx.arc(c.s.x, c.s.y, 4.2, 0, 6.283); cx.fill();
        }
        px = c.s.x; py = c.s.y;
      });
      chain.forEach(function (c, i) {                               // labels on top of every line
        var p = reduce ? 1 : ease((tStep - i * STEP) / (STEP * 0.6));
        if (p <= 0.95 || (W < 640 && chain[i + 1] && (reduce || tStep >= (i + 1) * STEP + STEP * 0.38))) return;
        lane(c.n, c.s.x, c.s.y, fade);
        result(c.r, c.s.x, c.s.y, (reduce ? 1 : ease((tStep - i * STEP - STEP * 0.6) / 0.4)) * fade);
      });
      cx.globalAlpha = 1;

      var show = (reduce || t > endSteps) && fade > 0.5;
      if (show) confEl.textContent = 'confidence ' + (sc.conf * (reduce ? 1 : ease((t - endSteps) / CONF))).toFixed(2);
      if (show !== ansOn) { ansOn = show; ans.classList.toggle('is-off', !show); }
    }

    function loop(now) {
      raf = 0;
      var dt = Math.min(0.05, (now - last) / 1000); last = now;
      clock += dt;
      if (clock > dur(SCENES[scene])) { scene = (scene + 1) % SCENES.length; clock = 0; }
      draw(now);
      if (running()) raf = requestAnimationFrame(loop);
    }
    function running() { return !reduce && !paused && onScreen && !document.hidden; }
    function kick() {
      if (running() && !raf) { last = performance.now(); raf = requestAnimationFrame(loop); }
      else if (!running()) draw(performance.now());
    }

    pauseBtn.hidden = reduce;
    pauseBtn.addEventListener('click', function () {
      paused = !paused;
      pauseBtn.setAttribute('aria-pressed', String(paused));
      pauseBtn.innerHTML = paused ? '<i class="bi bi-play-fill" aria-hidden="true"></i> Play'
                                  : '<i class="bi bi-pause-fill" aria-hidden="true"></i> Pause';
      kick();
    });
    nextBtn.addEventListener('click', function () {
      scene = (scene + 1) % SCENES.length; clock = 0; kick();
    });
    themeFns.push(function () { readTokens(); kick(); });
    document.addEventListener('visibilitychange', kick);
    whenVisible(sky, function (v) { onScreen = v; kick(); });
    if ('ResizeObserver' in window) new ResizeObserver(function () { layout(); kick(); }).observe(sky);
    else window.addEventListener('resize', function () { layout(); kick(); });

    readTokens(); layout(); kick();
  })();

  /* ── 2. The wire: a 2026-07-28 exchange, typed as it happens ─────────────────────────── */
  (function wire() {
    var box = document.getElementById('lpWire');
    if (!box) return;
    var log = document.getElementById('lpWireLog'), toolEl = document.getElementById('lpWireTool'),
        noteEl = document.getElementById('lpWireNote'), stateEl = document.getElementById('lpWireState'),
        acts = [].slice.call(box.querySelectorAll('[data-act]')), nodes = {}, lanes = {};
    ['agent', 'sajha', 'tool'].forEach(function (n) { nodes[n] = box.querySelector('[data-node="' + n + '"]'); });
    ['as', 'sa', 'st', 'ts'].forEach(function (n) { lanes[n] = box.querySelector('[data-lane="' + n + '"]'); });
    var dot = document.getElementById('lpWireDot');
    var srv = data.server || {};
    var V = '"io.modelcontextprotocol/protocolVersion":"2026-07-28"';
    var STATE = 'eyJtIjoidG9vbHMvY2FsbCIsInQiOi….Zk3qW…';
    // Shapes follow sajha/core/mcp_modern.py and docs/MCP_2026_07_28_Compliance.md; "…" trims.
    var ACTS = [
      { tool: 'tool registry', msgs: [
        { hops: ['as'], note: 'Agent → SAJHA: server/discover, no initialize, no session', text:
          '// 1. Discover: no initialize, no session id\n' +
          '→ POST /mcp\n  MCP-Protocol-Version: 2026-07-28\n  Mcp-Method: server/discover\n' +
          '{"jsonrpc":"2.0","id":1,"method":"server/discover",\n "params":{"_meta":{\n  ' + V + ',\n' +
          '  "io.modelcontextprotocol/clientCapabilities":{}}}}' },
        { hops: ['sa'], fast: true, note: 'SAJHA → Agent: every version it speaks, cacheable', text:
          '← 200 application/json\n{"jsonrpc":"2.0","id":1,"result":{\n' +
          ' "supportedVersions":["2026-07-28","2025-11-25",\n   "2025-06-18","2025-03-26","2024-11-05"],\n' +
          ' "capabilities":{"tools":{"listChanged":true},…},\n' +
          ' "resultType":"complete","ttlMs":300000,"cacheScope":"public",\n' +
          ' "_meta":{"io.modelcontextprotocol/serverInfo":\n   {"name":' + JSON.stringify(srv.name || 'SAJHA') +
          ',"version":' + JSON.stringify(srv.version || '') + ',…}}}}' }
      ] },
      { tool: 'calc_bond_price', msgs: [
        { hops: ['as', 'st'], note: 'Agent → SAJHA → tool: tools/call with a progressToken', text:
          '// 2. Call a tool, progress streams back over SSE\n' +
          '→ POST /mcp\n  Mcp-Method: tools/call\n  Mcp-Name: calc_bond_price\n' +
          '  Accept: application/json, text/event-stream\n' +
          '{"jsonrpc":"2.0","id":2,"method":"tools/call",\n "params":{"name":"calc_bond_price",\n' +
          '  "arguments":{"face_value":1000,"coupon_rate":5,\n   "yield_rate":4.5,"years":10},\n' +
          '  "_meta":{"progressToken":"bond-1",\n   ' + V + ',…}}}' },
        { hops: ['sa'], fast: true, note: 'SAJHA → Agent: notifications/progress, 50%', text:
          '← 200 text/event-stream\n' +
          'data: {"jsonrpc":"2.0","method":"notifications/progress",\n' +
          ' "params":{"progressToken":"bond-1","progress":50,"total":100}}' },
        { hops: ['ts', 'sa'], fast: true, note: 'tool → SAJHA → Agent: the result, text and structured', text:
          'data: {"jsonrpc":"2.0","id":2,"result":{\n' +
          ' "content":[{"type":"text","text":"{\\n  \\"face_value\\": 1000,…"}],\n' +
          ' "structuredContent":{"face_value":1000,"coupon_rate":5,\n   "yield":4.5,"price":1039.91},\n' +
          ' "resultType":"complete","_meta":{…}}}' }
      ] },
      { tool: 'duckdb_refresh_views', msgs: [
        { hops: ['as'], note: 'Agent → SAJHA: a tool marked destructiveHint', text:
          '// 3. Ask first (mcp.confirm_destructive_tools on, tool marked destructiveHint)\n' +
          '→ POST /mcp\n  Mcp-Method: tools/call\n  Mcp-Name: duckdb_refresh_views\n' +
          '{"jsonrpc":"2.0","id":3,"method":"tools/call",\n "params":{"name":"duckdb_refresh_views",\n' +
          '  "arguments":{"reload_external_files":true},\n  "_meta":{' + V + ',\n' +
          '   "io.modelcontextprotocol/clientCapabilities":\n    {"elicitation":{"form":{}}}}}}' },
        { hops: ['sa'], fast: true, note: 'SAJHA → Agent: input_required, with a signed requestState', text:
          '← 200 application/json\n{"jsonrpc":"2.0","id":3,"result":{\n "resultType":"input_required",\n' +
          ' "inputRequests":{"sajha_confirm_destructive":{\n  "method":"elicitation/create",\n' +
          '  "params":{"mode":"form",\n   "message":"\'duckdb_refresh_views\' can modify or delete data. Run it?",\n' +
          '   "requestedSchema":{…"confirm":{"type":"boolean"}…}}}},\n' +
          ' "requestState":"' + STATE + '"}}' },
        { hops: ['as', 'st'], note: 'The user said yes: the same request again, with the answer', text:
          '// the agent asks its user, then retries the same request\n' +
          '→ POST /mcp\n  Mcp-Method: tools/call\n  Mcp-Name: duckdb_refresh_views\n' +
          '{"jsonrpc":"2.0","id":4,"method":"tools/call",\n "params":{"name":"duckdb_refresh_views",\n' +
          '  "arguments":{"reload_external_files":true},\n' +
          '  "inputResponses":{"sajha_confirm_destructive":\n   {"action":"accept","content":{"confirm":true}}},\n' +
          '  "requestState":"' + STATE + '","_meta":{…}}}' },
        { hops: ['ts', 'sa'], fast: true, note: 'tool → SAJHA → Agent: done', text:
          '← 200 application/json\n{"jsonrpc":"2.0","id":4,"result":{\n' +
          ' "content":[{"type":"text","text":"…"}],\n "resultType":"complete","_meta":{…}}}' }
      ] }
    ];

    // syntax tint: comments, HTTP lines, header lines, then JSON keys / strings / literals
    var esc = function (s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); };
    function tint(text) {
      var out = [];
      text.split('\n').forEach(function (line, i) {
        if (i) out.push(['', '\n']);
        if (/^\/\//.test(line)) { out.push(['c', line]); return; }
        if (/^[→←] /.test(line)) { out.push(['k', line]); return; }
        var hm = /^(\s+[A-Za-z-]+:)( .*)$/.exec(line);
        if (hm) { out.push(['f', hm[1]], ['s', hm[2]]); return; }
        if (/^data: /.test(line)) { out.push(['k', 'data:']); line = line.slice(5); }
        var re = /("(?:[^"\\]|\\.)*")(\s*:)?|\b(-?\d+(?:\.\d+)?|true|false|null)\b/g, at = 0, m;
        while ((m = re.exec(line))) {
          if (m.index > at) out.push(['', line.slice(at, m.index)]);
          if (m[1]) { out.push([m[2] ? 'f' : 's', m[1]]); if (m[2]) out.push(['', m[2]]); }
          else out.push(['n', m[3]]);
          at = re.lastIndex;
        }
        if (at < line.length) out.push(['', line.slice(at)]);
      });
      return out;
    }
    function html(spans, n) {
      var s = '';
      for (var i = 0; i < spans.length && n > 0; i++) {
        var t = spans[i][1].slice(0, n); n -= t.length;
        s += spans[i][0] ? '<span class="' + spans[i][0] + '">' + esc(t) + '</span>' : esc(t);
      }
      return s;
    }
    ACTS.forEach(function (a) { a.msgs.forEach(function (m) { m.spans = tint(m.text); m.len = m.text.length; }); });

    var GEOM = { as: [92, 64, 92, 136], sa: [148, 136, 148, 64], st: [92, 184, 92, 256], ts: [148, 256, 148, 184] };
    function setHops(m, f) {
      Object.keys(lanes).forEach(function (k) {
        if (lanes[k].classList.contains('is-on')) lanes[k].classList.replace('is-on', 'is-done');
      });
      Object.keys(nodes).forEach(function (k) { nodes[k].classList.remove('is-on'); });
      if (!m) { dot.style.opacity = 0; return; }
      var idx = Math.min(m.hops.length - 1, Math.floor(f * m.hops.length)), lf = f * m.hops.length - idx;
      m.hops.forEach(function (h, i) { if (i <= idx) lanes[h].classList.add(i < idx ? 'is-done' : 'is-on'); });
      var h = m.hops[idx], g = GEOM[h], e = Math.min(1, lf);
      dot.setAttribute('cx', g[0] + (g[2] - g[0]) * e); dot.setAttribute('cy', g[1] + (g[3] - g[1]) * e);
      dot.style.opacity = 1;
      var to = { as: 'sajha', sa: 'agent', st: 'tool', ts: 'sajha' }[h];
      if (e > 0.85) nodes[to].classList.add('is-on');
    }
    function startAct(i) {
      log.innerHTML = '';
      Object.keys(lanes).forEach(function (k) { lanes[k].classList.remove('is-on', 'is-done'); });
      toolEl.textContent = ACTS[i].tool;
      acts.forEach(function (el, j) { el.classList.toggle('is-on', j === i); });
    }

    if (reduce) {     // the whole transcript, every hop lit
      log.innerHTML = ACTS.map(function (a) {
        return a.msgs.map(function (m) { return '<div class="lp2-wire-msg">' + html(m.spans, m.len) + '</div>'; }).join('');
      }).join('');
      Object.keys(lanes).forEach(function (k) { lanes[k].classList.add('is-done'); });
      toolEl.textContent = 'registry tool';
      dot.style.opacity = 0;
      noteEl.textContent = 'Three exchanges: discover, a streamed call, and a call that asks first.';
      return;
    }

    var act = 0, msg = 0, chars = 0, timer = 0, cur = null, hover = false, onScreen = false, started = false;
    function running() { return onScreen && !hover && !document.hidden; }
    function schedule(ms) { if (!timer && running()) timer = setTimeout(step, ms); }
    function step() {
      timer = 0;
      if (!running()) return;
      var A = ACTS[act];
      if (msg >= A.msgs.length) { act = (act + 1) % ACTS.length; msg = 0; chars = 0; startAct(act); setHops(null); return schedule(350); }
      var m = A.msgs[msg];
      if (chars === 0) {
        cur = document.createElement('div'); cur.className = 'lp2-wire-msg'; log.appendChild(cur);
        noteEl.textContent = m.note;
      }
      if (chars < m.len) {
        chars = Math.min(m.len, chars + (m.fast ? 9 : 4));
        cur.innerHTML = html(m.spans, chars) + (chars < m.len ? '<span class="lp2-wire-caret"></span>' : '');
        log.scrollTop = log.scrollHeight;
        setHops(m, chars / m.len);
        return schedule(26);
      }
      setHops(m, 1);
      msg++; chars = 0;
      schedule(msg >= A.msgs.length ? 3400 : 800);
    }
    function update() {
      stateEl.textContent = (hover && onScreen) ? 'paused' : '';
      if (running()) { if (!started) { started = true; startAct(0); } schedule(started ? 60 : 0); }
      else if (timer) { clearTimeout(timer); timer = 0; }
    }
    box.addEventListener('mouseenter', function () { hover = true; update(); });
    box.addEventListener('mouseleave', function () { hover = box.contains(document.activeElement); update(); });
    box.addEventListener('focusin', function () { hover = true; update(); });
    box.addEventListener('focusout', function (e) { if (!box.contains(e.relatedTarget)) { hover = false; update(); } });
    document.addEventListener('visibilitychange', update);
    whenVisible(box, function (v) { onScreen = v; update(); });
  })();
})();
