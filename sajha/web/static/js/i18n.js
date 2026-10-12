/*
 * Console languages for page scripts: _t('...') and _nt(singular, plural, n) look a message up in
 * window.SAJHA_I18N, which /static/i18n/<lang>.js sets (written by scripts/i18n.py compile from the
 * gettext catalog; English loads no catalog). A message with no translation shows English.
 * Messages are gettext-style: %(name)s / %(name)d take values from the args object and a literal
 * percent sign is written %%, as in the templates. scripts/i18n.py extract finds _t() and _nt()
 * in static/js and in the templates' inline scripts.
 * Guide: docs/architecture/Architecture.md §10, "Languages".
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
 */
(function () {
  'use strict';
  var cat = window.SAJHA_I18N || {};
  var msgs = cat.messages || {};
  var has = Object.prototype.hasOwnProperty;
  function fmt(s, args) {
    return String(s).replace(/%\((\w+)\)[sd]|%%/g, function (m, k) {
      if (m === '%%') return '%';
      return args && has.call(args, k) && args[k] != null ? String(args[k]) : m;
    });
  }
  function _t(msg, args) {
    var s = has.call(msgs, msg) && typeof msgs[msg] === 'string' && msgs[msg] ? msgs[msg] : msg;
    return fmt(s, args);
  }
  function _nt(singular, plural, n, args) {
    var forms = has.call(msgs, singular) ? msgs[singular] : null, s;
    if (Array.isArray(forms) && typeof cat.plural === 'function') {
      s = forms[+cat.plural(n)] || (n === 1 ? singular : plural);
    } else {
      s = n === 1 ? singular : plural;
    }
    var a = {num: n};
    if (args) for (var k in args) if (has.call(args, k)) a[k] = args[k];
    return fmt(s, a);
  }
  window._t = _t;
  window._nt = _nt;
  window.SAJHA_LANG = cat.lang || document.documentElement.lang || 'en';
})();
