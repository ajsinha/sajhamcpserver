/*
 * System notices in the console: keeps the banner, the navbar badge and (on the dashboard)
 * the System status panel current from GET /api/notices/stream (server-sent events), with a
 * slow poll of /api/notices when the stream is unavailable. docs/architecture/System Notices.md
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
 */
(function () {
  'use strict';
  var SEV = ['critical', 'error', 'warning', 'info'];
  var WORD = { info: 'Info', warning: 'Warning', error: 'Error', critical: 'Critical' };
  var ICON = { info: 'info-circle', warning: 'exclamation-triangle', error: 'x-octagon', critical: 'exclamation-octagon-fill' };
  var state = { view: null, showCleared: false, cleared: [] };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function when(ts) {
    if (!ts) return '';
    var d = new Date(ts * 1000), s = Math.max(0, (Date.now() - d.getTime()) / 1000), rel;
    if (s < 60) rel = 'just now';
    else if (s < 3600) rel = Math.round(s / 60) + ' min ago';
    else if (s < 86400) rel = Math.round(s / 3600) + ' h ago';
    else rel = Math.round(s / 86400) + ' d ago';
    return '<time datetime="' + d.toISOString() + '" title="' + esc(d.toLocaleString()) + '">' + rel + '</time>';
  }
  function safeLink(href) {
    return (typeof href === 'string' && href.charAt(0) === '/' && href.charAt(1) !== '/') ? href : '';
  }
  function setSev(el, sev) {
    SEV.forEach(function (s) { el.classList.remove('sev-' + s); });
    if (sev) el.classList.add('sev-' + sev);
  }

  // ── banner ──
  function renderBanner(v) {
    var el = document.getElementById('sajha-notice-banner');
    if (!el) return;
    var b = v && v.banner;
    if (!b) { el.hidden = true; return; }
    setSev(el, b.severity);
    el.querySelector('.bi').className = 'bi bi-' + ICON[b.severity];
    el.querySelector('.sev-word').textContent = WORD[b.severity] + ':';
    el.querySelector('.snb-title').textContent = b.title;
    var more = el.querySelector('.snb-more');
    more.textContent = v.others ? 'and ' + v.others + ' more' : '';
    el.hidden = false;
  }

  // ── badge ──
  function renderBadge(v) {
    var el = document.getElementById('sajha-notice-badge');
    if (!el) return;
    var n = (v && v.badge) || 0;
    var top = null;
    (v && v.notices || []).some(function (x) { if (SEV.indexOf(x.severity) < 3) { top = x.severity; return true; } return false; });
    setSev(el, top);
    el.classList.toggle('d-none', !n);
    var label = n + ' system notice' + (n === 1 ? '' : 's') + ' need attention';
    el.setAttribute('aria-label', label);
    el.setAttribute('title', label);
    el.querySelector('.cnt').textContent = n > 99 ? '99+' : String(n);
    var live = document.getElementById('sajha-notice-live');
    if (live && live.dataset.n !== String(n)) { live.dataset.n = String(n); live.textContent = n ? label : ''; }
  }

  // ── panel ──
  function item(n, admin, cleared) {
    var link = safeLink(n.link);
    var stateText = '';
    if (cleared) stateText = 'Cleared ' + when(n.cleared_at) + (n.cleared_reason ? ' (' + esc(n.cleared_reason) + ')' : '');
    else if (n.state === 'acknowledged') stateText = 'Acknowledged by ' + esc(n.acknowledged_by || 'an administrator') + ' ' + when(n.acknowledged_at);
    var actions = '';
    if (link) actions += '<a class="btn btn-sm btn-outline-primary" href="' + esc(link) + '">Open<span class="visually-hidden"> ' + esc(n.title) + '</span></a>';
    if (admin && !cleared && n.state === 'active') {
      actions += '<button type="button" class="btn btn-sm btn-outline-secondary" data-ack="' + esc(n.id) + '">Acknowledge<span class="visually-hidden"> ' + esc(n.title) + '</span></button>';
    }
    return '<li class="ssp-item sev-' + esc(n.severity) + (cleared ? ' is-cleared' : '') + '">' +
      '<div class="ssp-head"><span class="sev-pill sev-' + esc(n.severity) + '">' + esc(WORD[n.severity] || n.severity) + '</span>' +
      '<span class="ssp-title">' + esc(n.title) + '</span>' + (stateText ? '<span class="ssp-state">' + stateText + '</span>' : '') + '</div>' +
      '<div class="ssp-meta">' + esc(n.source || 'sajha') + ' · since ' + when(n.since) + ' · last seen ' + when(n.last_seen) +
      (admin ? ' · <code>' + esc(n.id) + '</code>' : '') + '</div>' +
      (n.detail ? '<p class="ssp-detail">' + esc(n.detail) + '</p>' : '') +
      (actions ? '<div class="ssp-actions">' + actions + '</div>' : '') + '</li>';
  }
  function renderPanel(v) {
    var body = document.getElementById('ssp-body');
    if (!body || !v) return;
    var admin = !!v.is_admin, html = '';
    if (v.enabled === false) {
      html = '<div class="ssp-empty"><i class="bi bi-dash-circle" aria-hidden="true"></i>System notices are switched off (notices.enabled).</div>';
    } else if (!v.notices.length) {
      html = '<div class="ssp-empty"><i class="bi bi-check-circle" aria-hidden="true"></i>No notices: nothing needs attention.</div>';
    } else {
      SEV.forEach(function (s) {
        var group = v.notices.filter(function (n) { return n.severity === s; });
        if (!group.length) return;
        html += '<h3 class="ssp-group sev-' + s + '"><span class="sev-pill sev-' + s + '">' + WORD[s] + '</span> ' +
          group.length + ' notice' + (group.length === 1 ? '' : 's') + '</h3><ul class="ssp-list">' +
          group.map(function (n) { return item(n, admin, false); }).join('') + '</ul>';
      });
    }
    if (state.showCleared) {
      html += '<h3 class="ssp-group">Recently cleared</h3>' + (state.cleared.length
        ? '<ul class="ssp-list">' + state.cleared.map(function (n) { return item(n, admin, true); }).join('') + '</ul>'
        : '<p class="ssp-state">Nothing cleared recently.</p>');
    }
    body.innerHTML = html;
    var summary = document.getElementById('ssp-summary');
    if (summary) summary.textContent = v.notices.length ? v.notices.length + ' open' : 'All clear';
  }

  function apply(v) {
    state.view = v;
    if (v && v.cleared) state.cleared = v.cleared;
    renderBanner(v); renderBadge(v); renderPanel(v);
  }

  function fetchView() {
    var url = '/api/notices' + (state.showCleared ? '?cleared=1' : '');
    return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; }).then(function (v) { if (v) apply(v); })
      .catch(function () {});
  }

  var source = null, poll = null;
  function connect() {
    if (!window.EventSource) { poll = setInterval(fetchView, 60000); return; }
    if (source) source.close();
    source = new EventSource('/api/notices/stream' + (state.showCleared ? '?cleared=1' : ''));
    source.addEventListener('notices', function (e) { try { apply(JSON.parse(e.data)); } catch (err) {} });
    source.onerror = function () {
      if (source && source.readyState === EventSource.CLOSED && !poll) poll = setInterval(fetchView, 60000);
    };
  }

  function acknowledge(btn) {
    var v = state.view || {};
    btn.disabled = true;
    fetch('/api/admin/notices/' + encodeURIComponent(btn.getAttribute('data-ack')) + '/acknowledge', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRF-Token': v.csrf || '', Accept: 'application/json' }
    }).then(function (r) {
      var msg = document.getElementById('ssp-msg');
      if (msg) msg.textContent = r.ok ? 'Acknowledged.' : 'Could not acknowledge (HTTP ' + r.status + ').';
      return fetchView();
    }).catch(function () { btn.disabled = false; });
  }

  // For scripts/check_mobile.py --notices: render a given view, and stop live updates first.
  window.SajhaNotices = {
    apply: apply,
    stop: function () { if (source) source.close(); source = null; if (poll) clearInterval(poll); poll = null; }
  };

  document.addEventListener('DOMContentLoaded', function () {
    var banner = document.getElementById('sajha-notice-banner');
    if (!banner) return;                       // signed out, or notices switched off
    var initial = document.getElementById('ssp-initial');
    if (initial) { try { apply(JSON.parse(initial.textContent)); } catch (e) {} }
    var panel = document.getElementById('system-status');
    if (panel) {
      panel.addEventListener('click', function (e) {
        var b = e.target.closest('[data-ack]');
        if (b) acknowledge(b);
      });
      var toggle = document.getElementById('ssp-cleared-toggle');
      if (toggle) toggle.addEventListener('click', function () {
        state.showCleared = !state.showCleared;
        toggle.setAttribute('aria-pressed', state.showCleared ? 'true' : 'false');
        toggle.textContent = state.showCleared ? 'Hide recently cleared' : 'Show recently cleared';
        fetchView(); connect();
      });
    }
    connect();
  });
})();
