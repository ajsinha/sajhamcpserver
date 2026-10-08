/*
 * SAJHA console: event handlers without inline script (Content-Security-Policy).
 *
 * The console's CSP refuses inline event handler attributes (onclick="..."), so pages write
 * them as data-onclick / data-onchange / data-onsubmit / ... instead, and this file runs them.
 * It does not evaluate script: a handler is a short program in a small language, interpreted
 * here, so an attribute injected into a page cannot run arbitrary code.
 *
 *   program    statement (";" statement)*
 *   statement  "return" value  |  call
 *   value      call | literal
 *   call       name "(" [argument ("," argument)*] ")"
 *   argument   literal | this | event | this.<property> | event.<property>
 *   literal    'string' | "string" | number | true | false | null | undefined
 *
 * A name is a function the page itself declares (a global function that is not built into the
 * browser), or confirm. A "return" whose value is false cancels the event's default action, as an
 * inline handler's "return false" does. "this" is the element carrying the attribute.
 *
 * docs/security/Security Model.md "Security headers and CSP"
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha
 */
(function () {
    'use strict';

    var EVENTS = ['click', 'dblclick', 'change', 'input', 'submit', 'keydown', 'keyup'];
    var NATIVE = /\{\s*\[native code\]\s*\}\s*$/;
    var cache = Object.create(null);

    function tokenize(src) {
        var out = [], i = 0, n = src.length;
        while (i < n) {
            var c = src[i];
            if (/\s/.test(c)) { i++; continue; }
            if ('();,.'.indexOf(c) >= 0) { out.push({t: 'p', v: c}); i++; continue; }
            if (c === "'" || c === '"') {
                var q = c, s = '';
                i++;
                while (i < n && src[i] !== q) {
                    if (src[i] === '\\' && i + 1 < n) {
                        var e = src[i + 1];
                        s += e === 'n' ? '\n' : e === 't' ? '\t' : e;
                        i += 2;
                    } else { s += src[i++]; }
                }
                if (i >= n) throw new Error('unterminated string');
                i++;
                out.push({t: 's', v: s});
                continue;
            }
            var m = /^-?\d+(\.\d+)?/.exec(src.slice(i));
            if (m) { out.push({t: 'n', v: Number(m[0])}); i += m[0].length; continue; }
            m = /^[A-Za-z_$][\w$]*/.exec(src.slice(i));
            if (m) { out.push({t: 'i', v: m[0]}); i += m[0].length; continue; }
            throw new Error('unexpected character ' + c);
        }
        return out;
    }

    function parse(src) {
        var toks = tokenize(src), pos = 0;
        function peek(v) { var t = toks[pos]; return t && (v === undefined || t.v === v) ? t : null; }
        function take(v) {
            var t = toks[pos];
            if (!t || (v !== undefined && t.v !== v)) throw new Error('expected ' + (v || 'a value'));
            pos++;
            return t;
        }
        function argument() {
            var t = take();
            if (t.t === 's' || t.t === 'n') return {k: 'lit', v: t.v};
            if (t.t !== 'i') throw new Error('bad argument');
            if (t.v === 'true') return {k: 'lit', v: true};
            if (t.v === 'false') return {k: 'lit', v: false};
            if (t.v === 'null') return {k: 'lit', v: null};
            if (t.v === 'undefined') return {k: 'lit', v: undefined};
            if (t.v === 'this' || t.v === 'event') {
                var prop = null;
                if (peek('.')) { take('.'); prop = take().v; }
                if (prop !== null && !/^[A-Za-z_]\w*$/.test(prop)) throw new Error('bad property');
                return {k: t.v, p: prop};
            }
            throw new Error('unknown name ' + t.v);
        }
        function call(name) {
            take('(');
            var args = [];
            if (!peek(')')) {
                args.push(argument());
                while (peek(',')) { take(','); args.push(argument()); }
            }
            take(')');
            return {k: 'call', f: name, a: args};
        }
        function value() {
            var t = take();
            if (t.t === 'i' && peek('(')) return call(t.v);
            pos--;
            return argument();
        }
        var prog = [];
        while (pos < toks.length) {
            if (peek(';')) { take(';'); continue; }
            var t = take();
            if (t.t === 'i' && t.v === 'return') prog.push({k: 'return', e: value()});
            else if (t.t === 'i' && peek('(')) prog.push(call(t.v));
            else throw new Error('expected a call');
            if (pos < toks.length) take(';');
        }
        return prog;
    }

    function resolve(name) {
        if (name === 'confirm') return window.confirm.bind(window);
        var fn = window[name];
        if (typeof fn !== 'function') throw new Error(name + ' is not a function of this page');
        if (NATIVE.test(Function.prototype.toString.call(fn))) throw new Error(name + ' is not allowed');
        return fn;
    }

    function evaluate(node, el, ev) {
        if (node.k === 'lit') return node.v;
        if (node.k === 'this') return node.p === null ? el : el[node.p];
        if (node.k === 'event') return node.p === null ? ev : ev[node.p];
        if (node.k === 'call') {
            var fn = resolve(node.f);
            return fn.apply(el, node.a.map(function (a) { return evaluate(a, el, ev); }));
        }
        throw new Error('bad node');
    }

    function run(el, type, ev) {
        var src = el.getAttribute('data-on' + type);
        if (!src) return;
        var prog = cache[src];
        try {
            if (!prog) prog = cache[src] = parse(src);
            for (var i = 0; i < prog.length; i++) {
                var st = prog[i];
                if (st.k === 'return') {
                    if (evaluate(st.e, el, ev) === false) ev.preventDefault();
                    return;
                }
                evaluate(st, el, ev);
            }
        } catch (err) {
            console.error('data-on' + type + ' handler failed: ' + src, err);
        }
    }

    function dispatch(ev) {
        var type = ev.type;
        var node = ev.target && ev.target.nodeType === 1 ? ev.target : (ev.target && ev.target.parentElement);
        while (node && node !== document) {
            if (node.nodeType === 1 && node.hasAttribute('data-on' + type)) {
                run(node, type, ev);
                if (ev.cancelBubble) return;
            }
            node = node.parentNode;
        }
    }

    EVENTS.forEach(function (t) { document.addEventListener(t, dispatch); });

    // Exposed for tests and for pages that build handlers in script
    window.SajhaActions = {parse: parse};
})();

// Small helpers for handlers that used to be one-line DOM statements.
function sajhaClick(id) { var el = document.getElementById(id); if (el) el.click(); }
function sajhaBack() { window.history.back(); }
function sajhaDisplay(id, value) { var el = document.getElementById(id); if (el) el.style.display = value; }
function sajhaHideClosest(el, selector) { var c = el.closest(selector); if (c) c.classList.add('d-none'); }
function sajhaRemoveClosest(el, selector) { var c = el.closest(selector); if (c) c.remove(); }
function sajhaRemoveParent(el) { if (el.parentElement) el.parentElement.remove(); }
