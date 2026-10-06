/*
 * SAJHA constellation: the tool catalog drawn as a night sky, one star per tool, clustered by
 * provider group, with a chain of links from the question to each tool it calls.
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
 *
 * Shared by the landing page (static/js/landing.js: scripted demo questions) and Ask SAJHA
 * (static/js/ask.js: driven by the live /api/ai/ask event stream). This file draws; the
 * callers decide what is lit and when.
 *
 *   var C = window.SajhaConstellation;
 *   C.reduce                      prefers-reduced-motion at load (callers draw final frames)
 *   C.tok('--sajha-ink')          a design token's current value
 *   C.onTheme(fn)                 fn() whenever the theme (data-theme or the system scheme) changes
 *   C.whenVisible(el, fn)         fn(isVisible) as el scrolls in and out of view
 *   C.groupOf('calc_npv')         'calc' (GLOSSARY: Tool group)
 *   var sky = C.sky(canvas, groups)   groups: [[name, count, [tool names]?], ...]
 *     sky.readTokens()            (re)read colours: sky.T, sky.colors[group]
 *     sky.resize()                fit the canvas backing store to its CSS box; false if 0×0
 *     sky.place()                 lay the stars out (deterministic: the same sky every time)
 *     sky.stars                   [{g, n (tool name or undefined), x, y, r, tw}]
 *     sky.starOf(name)            the star a tool name stands for (its own when names were given)
 *     sky.clear(); sky.drawStars(now, lit)   lit(star) -> 0..1 brightness boost
 *     sky.sweep(x, y, p); sky.link(x0, y0, x1, y1, p, dashed, alpha); sky.node(x, y, alpha)
 *     sky.lane(name, x, y, alpha) the name chip above a point; sky.result(text, x, y, alpha, tone)
 *     sky.labelBox(name, x, y)    the box lane() + result() cover, for collision checks
 *     sky.nearest(x, y, r); sky.ring(star, pinned)   hit-testing and the hover highlight
 *   var tip = C.tips(sky, host, {info, redraw})   hover / tap tooltips (see tips() below)
 */
(function () {
  'use strict';
  var root = document.documentElement;
  var mm = function (q) { return window.matchMedia ? window.matchMedia(q) : { matches: false }; };
  var MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

  // one theme signal for every figure: the menu sets data-theme on <html>; no data-theme
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
  function groupOf(name) { return name.indexOf('_') >= 0 ? name.split('_')[0] : name; }

  function sky(cv, groups) {
    var cx = cv.getContext('2d');
    var S = { canvas: cv, ctx: cx, groups: groups, stars: [], W: 0, H: 0, T: {}, colors: {} };
    var seed = 7;
    var rnd = function () { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
    var byName = {};

    S.readTokens = function () {
      var T = S.T = { ink: tok('--sajha-ink'), slate: tok('--sajha-slate'), accent: tok('--sajha-crimson'),
        indigo: tok('--sajha-indigo'), ok: tok('--sajha-ok'), warn: tok('--sajha-warn'), bad: tok('--sajha-bad'),
        surface: tok('--sajha-surface'), border: tok('--sajha-border'),
        font: getComputedStyle(document.body).fontFamily, mono: MONO };
      var pal = [T.accent, T.indigo, T.ok, T.warn, T.slate];
      groups.forEach(function (g, i) { S.colors[g[0]] = pal[i % pal.length]; });
    };

    S.resize = function () {
      var dpr = Math.min(window.devicePixelRatio || 1, 2), r = cv.getBoundingClientRect();
      S.W = r.width; S.H = r.height;
      if (!S.W || !S.H) return false;
      cv.width = Math.round(S.W * dpr); cv.height = Math.round(S.H * dpr); cx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return true;
    };

    // each provider group is a loose cluster on a golden-angle spiral; the biggest sit nearest the middle
    S.place = function (o) {
      o = o || {};
      var W = S.W, H = S.H;
      seed = 7; S.stars = []; byName = {};
      var k = Math.max(0.55, Math.min(1, W / 1000)) * (o.scale || 1), cxm = W / 2, cym = H * (o.cy || 0.55),
          rx = W * (o.rx || 0.44), ry = H * (o.ry || 0.35);
      groups.forEach(function (g, i) {
        var t = i * 2.399963, ring = Math.sqrt((i + 1.5) / (groups.length + 1));
        var gx = cxm + Math.cos(t) * rx * ring, gy = cym + Math.sin(t) * ry * ring;
        var spread = (20 + Math.sqrt(g[1]) * 9) * k, names = g[2] || [];
        for (var n = 0; n < g[1]; n++) {
          var a = rnd() * Math.PI * 2, d = Math.sqrt(rnd()) * spread;
          var s = { g: g[0], n: names[n], x: gx + Math.cos(a) * d, y: gy + Math.sin(a) * d * 0.8, r: 1 + rnd() * 1.5, tw: rnd() * 6.28 };
          S.stars.push(s);
          if (s.n) byName[s.n] = s;
        }
      });
      return S.stars;
    };

    // a tool's own star when names were given, else a fixed member of its group (by name hash)
    S.starOf = function (name) {
      if (byName[name]) return byName[name];
      var all = S.stars.filter(function (s) { return s.g === groupOf(name); }), h = 0;
      if (!all.length) return null;
      for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
      return all[h % all.length];
    };

    S.clear = function () { cx.clearRect(0, 0, S.W, S.H); };

    // dim(star) -> 0..1 alpha multiplier (Ask SAJHA's regex filter); omitted: 1
    S.drawStars = function (now, lit, still, dim) {
      for (var i = 0; i < S.stars.length; i++) {
        var st = S.stars[i], tw = still ? 0.8 : 0.55 + 0.45 * Math.sin(now / 900 + st.tw), on = lit ? lit(st) : 0;
        cx.globalAlpha = ((0.30 + 0.25 * tw) * (1 - on) + (0.55 + 0.45 * tw) * on) * (dim ? dim(st) : 1);
        cx.fillStyle = S.colors[st.g];
        cx.beginPath(); cx.arc(st.x, st.y, st.r + on * 0.6, 0, 6.283); cx.fill();
      }
      cx.globalAlpha = 1;
    };

    S.sweep = function (x, y, p) {
      cx.strokeStyle = S.T.accent; cx.globalAlpha = 0.35 * (1 - p); cx.lineWidth = 2;
      cx.beginPath(); cx.arc(x, y, Math.hypot(S.W, S.H) * 0.6 * p, 0, 6.283); cx.stroke(); cx.globalAlpha = 1;
    };

    S.link = function (x0, y0, x1, y1, p, dashed, alpha) {
      cx.strokeStyle = S.T.accent; cx.lineWidth = 1.8; cx.globalAlpha = 0.85 * alpha;
      cx.setLineDash(dashed ? [4, 5] : []);
      cx.beginPath(); cx.moveTo(x0, y0); cx.lineTo(x0 + (x1 - x0) * p, y0 + (y1 - y0) * p); cx.stroke();
      cx.setLineDash([]); cx.globalAlpha = 1;
    };

    S.node = function (x, y, alpha, color) {
      cx.fillStyle = color || S.T.accent;
      cx.globalAlpha = 0.18 * alpha;
      cx.beginPath(); cx.arc(x, y, 14, 0, 6.283); cx.fill();
      cx.globalAlpha = alpha;
      cx.beginPath(); cx.arc(x, y, 4.2, 0, 6.283); cx.fill();
      cx.globalAlpha = 1;
    };

    function pill(x, y, w, h) {
      cx.beginPath();
      if (cx.roundRect) cx.roundRect(x, y, w, h, 6); else cx.rect(x, y, w, h);
    }
    S.lane = function (name, x, y, alpha) {
      var W = S.W, T = S.T;
      cx.globalAlpha = alpha; cx.font = '600 12px ' + T.mono;
      var w = cx.measureText(name).width + 14, left = Math.min(Math.max(x - w / 2, 6), W - w - 6), top = y - 30;
      cx.fillStyle = T.surface; cx.strokeStyle = T.border; cx.lineWidth = 1;
      pill(left, top, w, 20); cx.fill(); cx.stroke();
      cx.fillStyle = T.ink; cx.fillText(name, left + 7, top + 14); cx.globalAlpha = 1;
    };
    // tone: undefined (muted), 'ok' or 'bad'; a toned result is outlined in its colour
    S.result = function (text, x, y, alpha, tone) {
      if (alpha <= 0) return;
      var W = S.W, T = S.T, col = tone === 'ok' ? T.ok : tone === 'bad' ? T.bad : T.slate;
      cx.globalAlpha = alpha; cx.font = '12px ' + T.font;
      var w = cx.measureText(text).width + 10, left = Math.min(Math.max(x - w / 2, 6), W - w - 6);
      cx.fillStyle = T.surface; pill(left, y + 10, w, 18); cx.fill();
      if (tone) { cx.strokeStyle = col; cx.lineWidth = 1; cx.stroke(); }
      cx.fillStyle = col; cx.fillText(text, left + 5, y + 23); cx.globalAlpha = 1;
    };
    S.labelBox = function (name, x, y) {
      var w = name.length * 7.4 + 22, l = Math.min(Math.max(x - w / 2, 6), S.W - w - 6);
      return { l: l, r: l + w, t: y - 34, b: y + 32 };
    };
    // the star nearest (x, y) in CSS px within r px, or null; ~500 stars, a plain loop is enough
    S.nearest = function (x, y, r) {
      var best = null, bd = r * r;
      for (var i = 0; i < S.stars.length; i++) {
        var st = S.stars[i], dx = st.x - x, dy = st.y - y, d = dx * dx + dy * dy;
        if (d <= bd) { bd = d; best = st; }
      }
      return best;
    };
    // the hover highlight: a soft halo and a ring in the ink colour (pinned: solid, else lighter)
    S.ring = function (st, pinned) {
      if (!st) return;
      cx.fillStyle = S.colors[st.g] || S.T.accent; cx.globalAlpha = 0.22;
      cx.beginPath(); cx.arc(st.x, st.y, 9, 0, 6.283); cx.fill();
      cx.globalAlpha = 1; cx.beginPath(); cx.arc(st.x, st.y, st.r + 0.8, 0, 6.283); cx.fill();
      cx.strokeStyle = S.T.ink; cx.lineWidth = pinned ? 1.6 : 1.2; cx.globalAlpha = pinned ? 0.95 : 0.7;
      cx.beginPath(); cx.arc(st.x, st.y, 7, 0, 6.283); cx.stroke(); cx.globalAlpha = 1;
    };
    S.measure = function (text, mono) {
      cx.font = mono ? '600 12px ' + S.T.mono : '12px ' + S.T.font;
      return cx.measureText(text).width;
    };
    return S;
  }

  /* ── star tooltips ──────────────────────────────────────────────────────────────────────
   * var tip = C.tips(S, host, { info: fn(star) -> {name, group, desc?} | null, redraw: fn() })
   *   host: the positioned box around the canvas (the tooltip and a polite live region go in it)
   *   tip.star / tip.pinned        what is highlighted now (the caller's draw calls S.ring(tip.star, tip.pinned))
   *   tip.hide()                   drop the hover and the pin
   * A mouse hover shows the tooltip of the nearest star within 8px (12px for a pen, 18px for a
   * touch); a click or a tap pins it, a click on empty sky, Escape or a click outside unpins.
   * The live region speaks a pinned star at once and a hovered one after a short dwell. */
  function tips(S, host, opts) {
    var cv = S.canvas, info = opts.info, redraw = opts.redraw || function () {};
    var box = document.createElement('div');
    box.className = 'sky-tip'; box.setAttribute('role', 'tooltip'); box.hidden = true;
    box.id = (cv.id || 'sky') + 'Tip';
    var nm = document.createElement('div'); nm.className = 'sky-tip-name';
    var gp = document.createElement('div'); gp.className = 'sky-tip-group';
    var dot = document.createElement('span'); dot.className = 'sky-tip-dot'; dot.setAttribute('aria-hidden', 'true');
    var gt = document.createElement('span'); gp.appendChild(dot); gp.appendChild(gt);
    var ds = document.createElement('div'); ds.className = 'sky-tip-desc';
    box.appendChild(nm); box.appendChild(gp); box.appendChild(ds);
    var live = document.createElement('div');
    live.className = 'visually-hidden'; live.setAttribute('aria-live', 'polite'); live.setAttribute('aria-atomic', 'true');
    host.appendChild(box); host.appendChild(live);

    var T = { star: null, pinned: false }, raf = 0, pending = null, dwell = 0, spoken = '';
    function speak(text, wait) {
      clearTimeout(dwell);
      if (!text || text === spoken) return;
      dwell = setTimeout(function () { spoken = text; live.textContent = text; }, wait);
    }
    function sentence(i) { return i.name + ', ' + i.group + ' provider group' + (i.desc ? '. ' + i.desc : ''); }
    function place(st) {
      var i = st && info(st);
      if (!i) { box.hidden = true; return null; }
      nm.textContent = i.name;
      gt.textContent = i.group + ' provider group';
      dot.style.background = S.colors[st.g] || '';
      ds.textContent = i.desc || ''; ds.hidden = !i.desc;
      box.hidden = false;
      // the canvas's box inside the host, then the star in host coordinates
      var ox = cv.offsetLeft, oy = cv.offsetTop, hw = host.clientWidth, hh = host.clientHeight;
      var w = box.offsetWidth, h = box.offsetHeight, x = ox + st.x, y = oy + st.y, gap = 12;
      var left = x + gap + w <= hw - 6 ? x + gap : x - gap - w;          // right of the star, else left
      var top = y - gap - h >= 6 ? y - gap - h : y + gap;                // above, else below
      box.style.left = Math.max(6, Math.min(left, hw - w - 6)) + 'px';
      box.style.top = Math.max(6, Math.min(top, hh - h - 6)) + 'px';
      return i;
    }
    function set(st, pinned) {
      var changed = st !== T.star || pinned !== T.pinned;
      T.star = st; T.pinned = !!(st && pinned);
      var i = place(st);
      cv.style.cursor = st ? 'pointer' : '';
      if (i) speak(sentence(i) + (T.pinned ? ' (pinned; Escape to close)' : ''), T.pinned ? 30 : 900);
      else clearTimeout(dwell);
      if (changed) redraw();
    }
    function at(e, slop) {
      var r = cv.getBoundingClientRect();
      if (!r.width || !S.W) return null;
      var k = S.W / r.width;                       // CSS box vs the layout's own width (zoom, transforms)
      return S.nearest((e.clientX - r.left) * k, (e.clientY - r.top) * k, slop * k);
    }
    function slopOf(e) { return e.pointerType === 'touch' ? 18 : e.pointerType === 'pen' ? 12 : 8; }
    cv.addEventListener('pointermove', function (e) {
      if (T.pinned || e.pointerType === 'touch') return;
      pending = e;
      if (!raf) raf = requestAnimationFrame(function () { raf = 0; if (pending && !T.pinned) set(at(pending, slopOf(pending)), false); });
    });
    cv.addEventListener('pointerleave', function () { if (!T.pinned) { pending = null; set(null, false); } });
    cv.addEventListener('click', function (e) {
      var st = at(e, slopOf(e.pointerType ? e : { pointerType: lastType }));
      if (st && !(T.pinned && st === T.star)) set(st, true); else set(null, false);
    });
    var lastType = 'mouse';
    cv.addEventListener('pointerdown', function (e) { lastType = e.pointerType || 'mouse'; });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && T.star) set(null, false); });
    document.addEventListener('pointerdown', function (e) { if (T.pinned && e.target !== cv && !box.contains(e.target)) set(null, false); });
    T.hide = function () { set(null, false); };
    T.refresh = function () { if (T.star) place(T.star); };     // after a re-layout (the star may have moved)
    T.forget = function () { T.star = null; T.pinned = false; box.hidden = true; };
    return T;
  }

  window.SajhaConstellation = {
    reduce: mm('(prefers-reduced-motion: reduce)').matches,
    tok: tok, onTheme: function (fn) { themeFns.push(fn); }, whenVisible: whenVisible,
    groupOf: groupOf, sky: sky, tips: tips, MONO: MONO
  };
})();
