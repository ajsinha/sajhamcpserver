/*
 * Ask SAJHA: a figure's lineage (docs/architecture/Quantitative Planners.md §2.1).
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
 *
 * When a quantitative planner answers, the ask's stream sends a "workspace" event: the answer's
 * figures that match a quantity of the run's workspace ({start, end, text, quantity}, offsets in
 * Unicode code points) and those quantities with everything their lineage reaches
 * ({name: {value, cells, unit, as_of, source, op, args, inputs}}). This module marks each figure
 * in the answer as a button; selecting it shows the figure's lineage under the answer: the
 * operation and its inputs, recursively, down to the tool calls (tool, arguments, JSON path,
 * as-of date, unit and whether the tool's outputSchema or the model declared it).
 *
 * Built with createElement and textContent only: no markup is ever parsed from data. Each figure is a
 * <button type="button"> with an accessible name, aria-expanded and aria-controls; Escape in the
 * panel closes it and returns focus to the figure.
 *
 *   SajhaLineage.segments(text, figures)            -> [{text}, {text, fig, index}] (pure)
 *   SajhaLineage.render(container, text, figures, quantities, state, onToggle) -> the <p> it built
 *   SajhaLineage.tree(name, quantities)             -> a <ul> of the lineage
 */
(function () {
  'use strict';
  var _t = window._t || function (s, a) {
    return String(s).replace(/%\((\w+)\)[sd]|%%/g, function (m, k) { return m === '%%' ? '%' : (a && a[k] != null ? String(a[k]) : m); });
  };
  var _nt = window._nt || function (one, many, n) { return _t(n === 1 ? one : many, {num: n}); };
  var MAX_DEPTH = 14;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function num(v) {
    if (typeof v !== 'number' || !isFinite(v)) return String(v);
    var a = Math.abs(v);
    if (a !== 0 && (a >= 1e15 || a < 1e-6)) return v.toExponential(4);
    return String(Math.round(v * 1e6) / 1e6);
  }
  function shown(q) {
    if (!q) return '';
    var v = q.value, u = q.unit && q.unit !== 'unitless' ? ' ' + q.unit : '';
    if (Array.isArray(v)) {
      var n = q.cells != null ? q.cells : v.length;
      return '[' + v.slice(0, 6).map(num).join(', ') + (n > 6 ? ', …' : '') + ']' + u +
        ' (' + _nt('%(num)s value', '%(num)s values', n) + ')';
    }
    return num(v) + u;
  }
  function json(v) {
    try { return JSON.stringify(v); } catch (e) { return String(v); }
  }

  /* the answer split at the figures; offsets are code points (Python's), not UTF-16 units */
  function segments(text, figures) {
    var cps = Array.from(String(text || '')), out = [], at = 0;
    var figs = (figures || []).map(function (f, i) { return { f: f, i: i }; })
      .filter(function (x) {
        var f = x.f;
        return f && typeof f.start === 'number' && typeof f.end === 'number' && f.start >= 0 && f.end > f.start && f.end <= cps.length;
      })
      .sort(function (a, b) { return a.f.start - b.f.start; });
    figs.forEach(function (x) {
      var f = x.f;
      if (f.start < at) return;                        // overlapping: keep the first
      if (f.start > at) out.push({ text: cps.slice(at, f.start).join('') });
      out.push({ text: cps.slice(f.start, f.end).join(''), fig: f, index: x.i });
      at = f.end;
    });
    if (at < cps.length) out.push({ text: cps.slice(at).join('') });
    return out;
  }

  function sourceLine(li, q) {
    var s = q.source || {};
    if (s.kind === 'tool') {
      var d = el('div', 'ask-lin-src');
      d.appendChild(document.createTextNode(_t('Read from') + ' '));
      d.appendChild(el('code', 'ask-lin-tool', s.tool || '?'));
      if (s.call_id) d.appendChild(document.createTextNode(' (' + _t('call %(id)s', {id: s.call_id}) + ')'));
      li.appendChild(d);
      var dl = el('dl', 'ask-lin-facts');
      function fact(k, v, code) {
        if (v == null || v === '') return;
        dl.appendChild(el('dt', '', k));
        var dd = el('dd');
        if (code) dd.appendChild(el('code', '', v)); else dd.textContent = v;
        dl.appendChild(dd);
      }
      fact(_t('Arguments'), json(s.arguments || {}), true);
      fact(_t('Path'), s.path || '', true);
      fact(_t('As of'), q.as_of || _t('not stated'));
      fact(_t('Unit'), (q.unit || 'unitless') + ' · ' + (s.unit_from === 'schema'
        ? _t('declared by the tool (its output schema)') : _t('declared by the model')));
      li.appendChild(dl);
    } else if (s.kind === 'constant') {
      li.appendChild(el('div', 'ask-lin-src', s.text ? _t('A constant: %(text)s', {text: s.text}) : _t('A constant')));
    } else if (!q.op) {
      li.appendChild(el('div', 'ask-lin-src', _t('A literal value')));
    }
  }

  function node(name, label, q, quantities, depth, seen) {
    var li = el('li', 'ask-lin-node');
    var head = el('div', 'ask-lin-head');
    if (label) head.appendChild(el('code', 'ask-lin-name', label));
    head.appendChild(document.createTextNode((label ? ' = ' : '') + shown(q)));
    if (q.op) {
      head.appendChild(document.createTextNode(' · '));
      head.appendChild(el('span', 'ask-lin-op', q.op));
      var args = q.args && Object.keys(q.args).length ? ' ' + json(q.args) : '';
      if (args) head.appendChild(el('span', 'ask-lin-args', args));
    }
    if (q.as_of && (q.op || (q.source || {}).kind !== 'tool')) head.appendChild(el('span', 'ask-lin-asof', ' · ' + _t('as of %(date)s', {date: q.as_of})));
    li.appendChild(head);
    sourceLine(li, q);
    if (q.op && Array.isArray(q.inputs) && q.inputs.length) {
      if (depth >= MAX_DEPTH) {
        li.appendChild(el('div', 'ask-lin-src', _t('… (deeper steps not shown)')));
        return li;
      }
      var ul = el('ul', 'ask-lin-list');
      ul.setAttribute('aria-label', _t('Inputs of %(name)s', {name: label || q.op}));
      q.inputs.forEach(function (inp) {
        if (typeof inp === 'string') {
          var sub = quantities[inp];
          if (!sub) { ul.appendChild(el('li', 'ask-lin-node', inp)); return; }
          if (seen[inp]) { ul.appendChild(el('li', 'ask-lin-node', inp + ' ' + _t('(shown above)'))); return; }
          seen[inp] = 1;
          ul.appendChild(node(inp, inp, sub, quantities, depth + 1, seen));
        } else if (inp && typeof inp === 'object') {
          ul.appendChild(node(null, '', inp, quantities, depth + 1, seen));
        }
      });
      li.appendChild(ul);
    }
    return li;
  }

  function tree(name, quantities) {
    var ul = el('ul', 'ask-lin-list ask-lin-root');
    var q = (quantities || {})[name];
    if (!q) { ul.appendChild(el('li', 'ask-lin-node', _t('The lineage of %(name)s is not available.', {name: name}))); return ul; }
    var seen = {}; seen[name] = 1;
    ul.appendChild(node(name, name, q, quantities || {}, 0, seen));
    return ul;
  }

  /* the answer paragraph with its figures as buttons, and the lineage panel of the selected one.
     state.open: the index of the selected figure (or null); onToggle(index or null) is called on a change. */
  function render(container, text, figures, quantities, state, onToggle) {
    var p = el('p', 'ask-answer-text');
    var base = container.closest && container.closest('.ask-turn') ? container.closest('.ask-turn').id : 'ask';
    var panelId = base + '-lineage';
    var segs = segments(text, figures), buttons = [];
    segs.forEach(function (sg) {
      if (!sg.fig) { p.appendChild(document.createTextNode(sg.text)); return; }
      var b = el('button', 'ask-fig', sg.text);
      b.type = 'button';
      b.setAttribute('data-fig', String(sg.index));
      b.setAttribute('aria-label', _t('%(figure)s: show how it was computed', {figure: sg.text.trim()}));
      b.setAttribute('aria-controls', panelId);
      b.setAttribute('aria-expanded', String(state.open === sg.index));
      if (state.open === sg.index) b.classList.add('is-open');
      b.addEventListener('click', function () { onToggle(state.open === sg.index ? null : sg.index, sg.index); });
      buttons.push(b);
      p.appendChild(b);
    });
    container.appendChild(p);
    if (!buttons.length) return p;
    container.appendChild(el('div', 'ask-fig-note', _t('Underlined figures were computed by SAJHA: select one to see how it was done.')));
    var panel = el('div', 'ask-lineage');
    panel.id = panelId;
    panel.setAttribute('role', 'region');
    var f = state.open != null ? (figures || [])[state.open] : null;
    if (!f) { panel.hidden = true; container.appendChild(panel); return p; }
    panel.setAttribute('aria-label', _t('How %(figure)s was computed', {figure: String(f.text || '').trim()}));
    var h = el('div', 'ask-lineage-h');
    h.appendChild(el('span', 'ask-lineage-t', _t('How %(figure)s was computed', {figure: String(f.text || '').trim()})));
    var close = el('button', 'ask-lineage-close', _t('Close'));
    close.type = 'button';
    close.setAttribute('aria-label', _t('Close the lineage of %(figure)s', {figure: String(f.text || '').trim()}));
    close.addEventListener('click', function () { onToggle(null, state.open); });
    h.appendChild(close);
    panel.appendChild(h);
    panel.appendChild(tree(f.quantity, quantities));
    panel.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.stopPropagation(); onToggle(null, state.open); }
    });
    container.appendChild(panel);
    return p;
  }

  /* quantities from a run record's workspace ({quantities: [...]}) when no workspace event came */
  function fromWorkspace(ws, names, maxCells) {
    var all = {}, out = {}, todo = (names || []).slice(), cap = maxCells || 24;
    ((ws && ws.quantities) || []).forEach(function (q) { if (q && q.name) all[q.name] = q; });
    function clip(v) {
      if (!Array.isArray(v)) return v;
      var flat = [];
      v.forEach(function (r) { if (Array.isArray(r)) flat.push.apply(flat, r); else flat.push(r); });
      return flat.slice(0, cap);
    }
    function cells(v) {
      if (!Array.isArray(v)) return 1;
      return v.reduce(function (n, r) { return n + (Array.isArray(r) ? r.length : 1); }, 0);
    }
    while (todo.length && Object.keys(out).length < 200) {
      var n = todo.shift();
      if (out[n] || !all[n]) continue;
      var q = all[n], lin = q.lineage || null;
      var node = { value: clip(q.value), cells: cells(q.value), unit: q.unit, as_of: q.as_of, source: q.source };
      if (lin) {
        node.op = lin.op; node.args = lin.args || {};
        node.inputs = (lin.inputs || []).map(function (i) {
          if (typeof i === 'string' && all[i]) { todo.push(i); return i; }
          if (i && typeof i === 'object') return { value: clip(i.value), unit: i.unit, source: i.source };
          return { value: i };
        });
      }
      out[n] = node;
    }
    return out;
  }

  window.SajhaLineage = { segments: segments, render: render, tree: tree, fromWorkspace: fromWorkspace };
})();
