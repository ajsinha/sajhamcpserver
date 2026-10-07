/*
 * SAJHA MCP Server — the SAJHA Net ring on the landing page (beside the constellation).
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
 *
 * Eight SAJHA servers on a ring play five short scenes in a loop: they find each other by
 * gossip; one question fans out to tools on other servers and the results come home; a
 * server goes down and a call falls back to another; a server offering a different contract
 * quarantines a tool until the contracts agree. Server and tool names are examples; the
 * design is docs/architecture/SAJHA Net.md. Colours come from CSS classes using the theme
 * tokens, so the ring follows all four themes. With prefers-reduced-motion the ring shows one
 * still, complete frame. The loop pauses while the ring is off screen or the tab is hidden.
 */
(function () {
  'use strict';
  var root = document.getElementById('lpNet');
  if (!root) return;
  var svg = root.querySelector('svg');
  var NS = 'http://www.w3.org/2000/svg';
  var CX = 280, CY = 312, R = 168;
  var NAMES = ['risk-eu', 'treasury-na', 'cust-na', 'research', 'quant-na', 'risk-apac', 'ops-eu', 'vendor-search'];
  var TAGS = ['home', 'rates', 'customers', 'LLM tools', 'models', 'risk', 'operations', 'sponsored'];
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var layer = {
    chords: svg.querySelector('[data-layer="chords"]'), arrows: svg.querySelector('[data-layer="arrows"]'),
    nodes: svg.querySelector('[data-layer="nodes"]'), fx: svg.querySelector('[data-layer="fx"]')
  };
  var bubbleEl = document.getElementById('lpNetBubble');
  var sceneEl = document.getElementById('lpNetScene');
  var pauseBtn = document.getElementById('lpNetPause');
  var nextBtn = document.getElementById('lpNetNext');

  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  var P = NAMES.map(function (n, i) {
    var a = -Math.PI / 2 + i * 2 * Math.PI / NAMES.length;
    return { x: CX + R * Math.cos(a), y: CY + R * Math.sin(a), a: a };
  });

  el('circle', { cx: CX, cy: CY, r: R, 'class': 'lp2-net-ring' }, layer.chords);
  for (var i = 0; i < NAMES.length; i++) {
    for (var j = i + 2; j < NAMES.length; j += 3) {
      el('line', { x1: P[i].x, y1: P[i].y, x2: P[j].x, y2: P[j].y, 'class': 'lp2-net-chord' }, layer.chords);
    }
  }
  var nodes = NAMES.map(function (name, i) {
    var g = el('g', { 'class': 'lp2-net-node' }, layer.nodes);
    el('circle', { cx: P[i].x, cy: P[i].y, r: 22, 'class': 'lp2-net-core' }, g);
    var dots = [];
    for (var k = 0; k < 4; k++) {
      var a = P[i].a + Math.PI + (k - 1.5) * 0.44;
      dots.push(el('circle', { cx: P[i].x + 33 * Math.cos(a), cy: P[i].y + 33 * Math.sin(a), r: 3.6, 'class': 'lp2-net-tool' }, g));
    }
    var s = Math.sin(P[i].a), c = Math.cos(P[i].a), tx, y, anchor;
    if (c > 0.5) { anchor = 'start'; tx = P[i].x + 30; y = P[i].y - 2; }          // right side: label outward
    else if (c < -0.5) { anchor = 'end'; tx = P[i].x - 30; y = P[i].y - 2; }      // left side
    else { anchor = 'middle'; tx = P[i].x; y = P[i].y + (s > 0 ? 40 : -38); }      // top and bottom
    el('text', { x: tx, y: y, 'class': 'lp2-net-name', 'text-anchor': anchor }, g).textContent = name;
    el('text', { x: tx, y: y + 13, 'class': 'lp2-net-tag', 'text-anchor': anchor }, g).textContent = TAGS[i];
    return { g: g, dots: dots };
  });

  function cls(i, c, on) { nodes[i].g.classList.toggle(c, on); }
  function clearFx() { layer.arrows.textContent = ''; layer.fx.textContent = ''; }
  function curve(i, j) {
    var a = P[i], b = P[j], mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    return 'M' + a.x + ' ' + a.y + ' Q' + (mx + (CX - mx) * 0.55) + ' ' + (my + (CY - my) * 0.55) + ' ' + b.x + ' ' + b.y;
  }
  function arrow(i, j, kind, label) {
    var p = el('path', { d: curve(i, j), 'class': 'lp2-net-arrow' + (kind ? ' is-' + kind : '') }, layer.arrows);
    var len = p.getTotalLength();
    if (!kind) { p.setAttribute('stroke-dasharray', (len - 24) + ' ' + len); p.setAttribute('marker-end', 'url(#lpNetHead)'); }
    if (label) {
      var m = p.getPointAtLength(len * 0.55);
      el('text', { x: m.x + 6, y: m.y - 6, 'class': 'lp2-net-label' }, layer.arrows).textContent = label;
    }
    return p;
  }
  function note(i, text, dy) {
    el('text', { x: P[i].x, y: P[i].y + dy, 'class': 'lp2-net-note' }, layer.fx).textContent = text;
  }

  var paused = false, visible = true, token = 0, scene = 0;
  function halted() { return paused || !visible || document.hidden; }
  function wait(ms) {
    return new Promise(function (res) {
      var left = ms, last = Date.now();
      (function tick() {
        var now = Date.now();
        if (!halted()) left -= now - last;
        last = now;
        if (left <= 0) res(); else setTimeout(tick, 60);
      })();
    });
  }
  function packet(path, back, ms) {
    return new Promise(function (res) {
      var len = path.getTotalLength();
      var c = el('circle', { r: 4.5, 'class': 'lp2-net-packet' + (back ? ' is-back' : '') }, layer.fx);
      var done = 0, last = performance.now();
      function step(t) {
        if (!halted()) done += t - last;
        last = t;
        var k = Math.min(1, done / ms), d = len * (back ? 1 - k : k) * 0.93 + (back ? len * 0.07 : 0);
        var pt = path.getPointAtLength(d);
        c.setAttribute('cx', pt.x); c.setAttribute('cy', pt.y);
        if (k < 1) requestAnimationFrame(step); else { c.remove(); res(); }
      }
      requestAnimationFrame(step);
    });
  }
  function bubble(who, html, kind) {
    bubbleEl.className = 'lp2-net-bubble' + (kind ? ' is-' + kind : '');
    bubbleEl.innerHTML = '<span class="lp2-net-who"></span>' + html;
    bubbleEl.firstChild.textContent = who;
    requestAnimationFrame(function () { bubbleEl.classList.add('is-on'); });
  }
  function reset(home) {
    clearFx();
    bubbleEl.classList.remove('is-on');
    nodes.forEach(function (n) {
      n.g.setAttribute('class', 'lp2-net-node' + (home ? ' is-alive' : ''));
      n.dots.forEach(function (d) { d.setAttribute('class', 'lp2-net-tool'); });
    });
    cls(0, 'is-home', true);
  }

  var SCENES = [
    ['Servers find each other', async function (tk) {
      reset(false);
      bubble('gossip', 'Who is in the net, and what does each server offer?');
      for (var r = 0; r < 12 && tk === token; r++) {
        var a = r % 8, b = (a + 1 + Math.floor(Math.random() * 6)) % 8;
        cls(a, 'is-alive', true);
        (function (p, b) { packet(p, false, 420).then(function () { p.remove(); cls(b, 'is-alive', true); }); })(
          el('path', { d: curve(a, b), 'class': 'lp2-net-arrow is-gossip' }, layer.arrows), b);
        await wait(330);
      }
      for (var k = 0; k < 8; k++) cls(k, 'is-alive', true);
      await wait(1300);
    }],
    ['One question, tools on three servers', async function (tk) {
      reset(true);
      bubble('analyst on risk-eu', 'How exposed is the EU book to the US rate forecast?');
      await wait(1400); if (tk !== token) return;
      var calls = [[1, 'fred_10yr_treasury'], [2, 'portfolio_positions'], [3, 'rate_outlook']];
      var paths = calls.map(function (c) { cls(c[0], 'is-target', true); return arrow(0, c[0], '', c[1]); });
      await Promise.all(paths.map(function (p, k) { return wait(k * 240).then(function () { return packet(p, false, 1250); }); }));
      if (tk !== token) return;
      calls.forEach(function (c) { note(c[0], 'data stays here', P[c[0]].y > CY ? 58 : -44); });
      await wait(900); if (tk !== token) return;
      await Promise.all(paths.map(function (p, k) { return wait(k * 200).then(function () { return packet(p, true, 1050); }); }));
      await wait(500);
    }],
    ['The answer comes home', async function (tk) {
      clearFx();
      for (var k = 0; k < 8; k++) cls(k, 'is-target', false);
      bubble('answer on risk-eu', 'A 100 bp move costs the EU book about 3.1%. Sources: <code>treasury-na</code>, <code>cust-na</code>, <code>research</code>.', 'good');
      note(0, 'memory stays on risk-eu', -48);
      await wait(3400);
    }],
    ['A server goes down, the call falls back', async function (tk) {
      reset(true);
      bubble('ops-eu calls var_calc', 'Preferred server: <code>quant-na</code>');
      await wait(1200); if (tk !== token) return;
      nodes[4].g.setAttribute('class', 'lp2-net-node is-down');
      await packet(arrow(6, 4, 'fail', 'var_calc'), false, 950); if (tk !== token) return;
      bubble('quant-na is down · not executed', 'Its tools leave every catalog. Fallback 1 of 3: <code>risk-apac</code>', 'bad');
      await wait(1100); if (tk !== token) return;
      var ok = arrow(6, 5, '', 'var_calc');
      await packet(ok, false, 850); cls(5, 'is-target', true);
      await packet(ok, true, 750);
      bubble('result from risk-apac', 'Done once. Nothing ran twice.', 'good');
      await wait(2100);
    }],
    ['One name, one contract', async function (tk) {
      reset(true);
      var holders = [0, 5, 4];
      bubble('quant-na rejoins', 'It offers <code>var_calc</code> with a different input schema.');
      await wait(1500); if (tk !== token) return;
      holders.forEach(function (i) { cls(i, 'is-conflict', true); nodes[i].dots[1].setAttribute('class', 'lp2-net-tool is-quarantined'); });
      bubble('every server · error', '<code>var_calc</code> quarantined: <b>quant-na</b> differs at <code>/properties/horizon/type</code>. Agreeing: risk-eu, risk-apac.', 'bad');
      await wait(3300); if (tk !== token) return;
      holders.forEach(function (i) { cls(i, 'is-conflict', false); nodes[i].dots[1].setAttribute('class', 'lp2-net-tool is-restored'); });
      bubble('quant-na fixed', 'The contracts agree again. <code>var_calc</code> is back on every server.', 'good');
      await wait(2500);
    }]
  ];

  function show(s) { sceneEl.textContent = (s + 1) + ' / ' + SCENES.length + ' · ' + SCENES[s][0]; }
  async function loop() {
    for (;;) {
      var tk = ++token;
      show(scene);
      await SCENES[scene][1](tk);
      if (tk !== token) return;
      scene = (scene + 1) % SCENES.length;
    }
  }

  if (reduce) {
    reset(true);
    [[1, 'fred_10yr_treasury'], [2, 'portfolio_positions'], [3, 'rate_outlook']].forEach(function (c) {
      cls(c[0], 'is-target', true); arrow(0, c[0], '', c[1]);
    });
    bubble('analyst on risk-eu', 'How exposed is the EU book to the US rate forecast?');
    show(1);
    if (pauseBtn) pauseBtn.hidden = true;
    if (nextBtn) nextBtn.hidden = true;
    return;
  }
  if (pauseBtn) pauseBtn.addEventListener('click', function () {
    paused = !paused;
    pauseBtn.setAttribute('aria-pressed', String(paused));
    pauseBtn.innerHTML = paused ? '<i class="bi bi-play-fill" aria-hidden="true"></i> Play' : '<i class="bi bi-pause-fill" aria-hidden="true"></i> Pause';
  });
  if (nextBtn) nextBtn.addEventListener('click', function () {
    scene = (scene + 1) % SCENES.length;
    paused = false;
    if (pauseBtn) { pauseBtn.setAttribute('aria-pressed', 'false'); pauseBtn.innerHTML = '<i class="bi bi-pause-fill" aria-hidden="true"></i> Pause'; }
    loop();
  });
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (entries) { visible = entries[0].isIntersecting; }, { threshold: 0.05 }).observe(root);
  }
  loop();
})();
