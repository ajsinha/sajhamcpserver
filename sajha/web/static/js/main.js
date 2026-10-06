/*
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
 * Main JavaScript for SAJHA MCP Server
 */

// Initialize Socket.IO connection
let socket = null;
let isAuthenticated = false;

// Initialize on document ready
$(document).ready(function() {
    // Initialize tooltips
    $('[data-bs-toggle="tooltip"]').tooltip();
    
    // Initialize popovers
    $('[data-bs-toggle="popover"]').popover();
    
    // Auto-hide alerts after 5 seconds
    $('.alert-dismissible').delay(5000).fadeOut('slow');
    
    // Initialize WebSocket connection if authenticated
    const token = getSessionToken();
    if (token) {
        initializeWebSocket(token);
    }
    
    // Handle form validation
    $('.needs-validation').on('submit', function(event) {
        if (this.checkValidity() === false) {
            event.preventDefault();
            event.stopPropagation();
        }
        $(this).addClass('was-validated');
    });
});

// Initialize WebSocket connection
function initializeWebSocket(token) {
    socket = io({
        transports: ['websocket'],
        upgrade: false
    });
    
    socket.on('connect', function() {
        console.log('Connected to WebSocket server');
        
        // Authenticate
        socket.emit('authenticate', { token: token });
    });
    
    socket.on('authenticated', function(data) {
        if (data.success) {
            isAuthenticated = true;
            console.log('WebSocket authenticated:', data.user);
        } else {
            console.error('WebSocket authentication failed');
            socket.disconnect();
        }
    });
    
    socket.on('disconnect', function() {
        console.log('Disconnected from WebSocket server');
        isAuthenticated = false;
    });
    
    socket.on('tool_update', function(data) {
        // Handle real-time tool updates
        showNotification('Tool Update', data.message, 'info');
    });
    
    socket.on('mcp_response', function(data) {
        // Handle MCP responses
        console.log('MCP Response:', data);
    });
}

// Execute tool via WebSocket
function executeToolWebSocket(toolName, arguments) {
    if (!socket || !isAuthenticated) {
        console.error('WebSocket not connected or not authenticated');
        return;
    }
    
    socket.emit('tool_execute', {
        token: getSessionToken(),
        tool: toolName,
        arguments: arguments
    });
    
    socket.on('tool_result', function(data) {
        if (data.success) {
            console.log('Tool executed successfully:', data.result);
        } else {
            console.error('Tool execution failed:', data.error);
        }
    });
}

// Get session token from cookie or session storage
function getSessionToken() {
    // Try to get from session storage first
    let token = sessionStorage.getItem('mcp_token');
    
    // If not found, try cookies
    if (!token) {
        const cookie = document.cookie.split('; ')
            .find(row => row.startsWith('mcp_token='));
        if (cookie) {
            token = cookie.split('=')[1];
        }
    }
    
    return token;
}

// Show notification
function showNotification(title, message, type = 'info') {
    const alertClass = `alert-${type}`;
    const alertHtml = `
        <div class="alert ${alertClass} alert-dismissible fade show position-fixed top-0 end-0 m-3" 
             role="alert" style="z-index: 9999;">
            <strong>${title}</strong> ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    $('body').append(alertHtml);
    
    // Auto-hide after 5 seconds
    setTimeout(function() {
        $('.alert').last().alert('close');
    }, 5000);
}

// Format JSON for display
function formatJSON(json) {
    if (typeof json === 'string') {
        try {
            json = JSON.parse(json);
        } catch (e) {
            return json;
        }
    }
    return JSON.stringify(json, null, 2);
}

// Copy to clipboard
function copyToClipboard(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    
    showNotification('Success', 'Copied to clipboard!', 'success');
}

// Export table to CSV
function exportTableToCSV(tableId, filename) {
    const table = document.getElementById(tableId);
    if (!table) return;
    
    let csv = [];
    const rows = table.querySelectorAll('tr');
    
    for (let i = 0; i < rows.length; i++) {
        const row = [];
        const cols = rows[i].querySelectorAll('td, th');
        
        for (let j = 0; j < cols.length; j++) {
            let data = cols[j].innerText.replace(/(\r\n|\n|\r)/gm, '');
            data = data.replace(/(\s\s)/gm, ' ');
            data = data.replace(/"/g, '""');
            row.push('"' + data + '"');
        }
        
        csv.push(row.join(','));
    }
    
    const csvString = csv.join('\n');
    const link = document.createElement('a');
    link.style.display = 'none';
    link.setAttribute('target', '_blank');
    link.setAttribute('href', 'data:text/csv;charset=utf-8,' + encodeURIComponent(csvString));
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// Debounce function for search inputs
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Search/filter table
function filterTable(inputId, tableId) {
    const input = document.getElementById(inputId);
    const filter = input.value.toUpperCase();
    const table = document.getElementById(tableId);
    const tr = table.getElementsByTagName('tr');
    
    for (let i = 1; i < tr.length; i++) {
        const td = tr[i].getElementsByTagName('td');
        let txtValue = '';
        
        for (let j = 0; j < td.length; j++) {
            if (td[j]) {
                txtValue += td[j].textContent || td[j].innerText;
            }
        }
        
        if (txtValue.toUpperCase().indexOf(filter) > -1) {
            tr[i].style.display = '';
        } else {
            tr[i].style.display = 'none';
        }
    }
}

// Confirm action dialog
function confirmAction(message, callback) {
    if (confirm(message)) {
        callback();
    }
}

// Format timestamp
function formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleString();
}

// Format file size
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// Handle keyboard shortcuts
document.addEventListener('keydown', function(e) {
    // Ctrl/Cmd + K: Focus search
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.querySelector('input[type="search"]');
        if (searchInput) {
            searchInput.focus();
        }
    }
    
    // Escape: Close modals/dialogs
    if (e.key === 'Escape') {
        $('.modal').modal('hide');
    }
});

// Add loading overlay
function showLoading() {
    const overlay = `
        <div id="loadingOverlay" class="position-fixed top-0 start-0 w-100 h-100 d-flex 
             justify-content-center align-items-center" 
             style="background: color-mix(in srgb, var(--sajha-nav-to) 55%, transparent); z-index: 9999;">
            <div class="spinner-border text-light" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
        </div>
    `;
    $('body').append(overlay);
}

function hideLoading() {
    $('#loadingOverlay').remove();
}

// API helper functions
const API = {
    get: function(url) {
        return $.ajax({
            url: url,
            method: 'GET',
            headers: {
                'Authorization': 'Bearer ' + getSessionToken()
            }
        });
    },
    
    post: function(url, data) {
        return $.ajax({
            url: url,
            method: 'POST',
            data: JSON.stringify(data),
            contentType: 'application/json',
            headers: {
                'Authorization': 'Bearer ' + getSessionToken()
            }
        });
    },
    
    put: function(url, data) {
        return $.ajax({
            url: url,
            method: 'PUT',
            data: JSON.stringify(data),
            contentType: 'application/json',
            headers: {
                'Authorization': 'Bearer ' + getSessionToken()
            }
        });
    },
    
    delete: function(url) {
        return $.ajax({
            url: url,
            method: 'DELETE',
            headers: {
                'Authorization': 'Bearer ' + getSessionToken()
            }
        });
    }
};

// ── Theme-aware chart colours ──────────────────────────────────────────────
// Chart.js draws on a canvas, which cannot read CSS variables, so charts take
// their colours from the design tokens at runtime and are re-coloured when the
// theme changes. A chart opts in by setting chart.$sajhaRestyle = function () {...}.
window.SajhaChartTheme = (function () {
    function token(name) {
        return getComputedStyle(document.documentElement).getPropertyValue('--sajha-' + name).trim();
    }
    // Resolve any CSS colour (hex, rgb, color-mix) to an rgba() string with the given alpha.
    var probe;
    function color(name, alpha) {
        var raw = name.indexOf('(') >= 0 || name.charAt(0) === '#' ? name : token(name);
        if (!probe) { probe = document.createElement('canvas').getContext('2d'); }
        probe.fillStyle = '#000';
        probe.fillStyle = raw;
        var v = probe.fillStyle; // normalised to #rrggbb or rgba(...)
        var r, g, b;
        if (v.charAt(0) === '#') {
            r = parseInt(v.substr(1, 2), 16); g = parseInt(v.substr(3, 2), 16); b = parseInt(v.substr(5, 2), 16);
        } else {
            var m = v.match(/[\d.]+/g) || [0, 0, 0];
            r = +m[0]; g = +m[1]; b = +m[2];
        }
        return 'rgba(' + r + ',' + g + ',' + b + ',' + (alpha == null ? 1 : alpha) + ')';
    }
    // Series palette: accent, indigo, ok, warn, slate.
    function palette() {
        return ['crimson', 'indigo', 'ok', 'warn', 'slate'].map(function (n) { return color(n); });
    }
    function applyDefaults() {
        if (!window.Chart) { return; }
        Chart.defaults.color = color('slate');
        Chart.defaults.borderColor = color('border');
        Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    }
    function restyleAll() {
        if (!window.Chart) { return; }
        applyDefaults();
        Object.values(Chart.instances || {}).forEach(function (c) {
            if (c.options && c.options.scales) {
                Object.values(c.options.scales).forEach(function (s) {
                    if (s.grid) { s.grid.color = color('border'); }
                    if (s.ticks) { s.ticks.color = color('slate'); }
                    if (s.title) { s.title.color = color('slate'); }
                });
            }
            if (c.options && c.options.plugins && c.options.plugins.legend && c.options.plugins.legend.labels) {
                c.options.plugins.legend.labels.color = color('ink');
            }
            if (typeof c.$sajhaRestyle === 'function') { c.$sajhaRestyle(); }
            c.update('none');
        });
    }
    new MutationObserver(restyleAll).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return { token: token, color: color, palette: palette, applyDefaults: applyDefaults, restyleAll: restyleAll };
})();

/*
 * Small screens (see "Mobile" at the end of style.css):
 *  - every data table sits in a horizontal-scroll box, so a wide table scrolls on its own
 *    instead of widening the page (tables already in a scrolling/clipping box are left alone);
 *  - a table marked class="sajha-stack" turns into one card per row on phones: each cell is
 *    labelled from its column heading (data-label), which this fills in;
 *  - on touch screens a tap on an element that only explains itself through title="" shows
 *    that text, since there is no hover to reveal it.
 * Runs after table-enhance.js and sajha-table.js have placed their controls, and again for
 * tables that pages render later.
 */
(function () {
    'use strict';
    var SKIP = '.jsoneditor, .CodeMirror, .cm-editor, .pg-html, pre, .table-responsive, .sajha-xscroll, [data-no-xscroll]';

    function scrollsX(el) {
        for (var p = el.parentElement; p && p !== document.body; p = p.parentElement) {
            var o = getComputedStyle(p).overflowX;
            if (o === 'auto' || o === 'scroll') return true;  // a clipping box would hide the overflow
        }
        return false;
    }
    function label(table) {
        if (!table.classList.contains('sajha-stack')) return;
        var heads = Array.prototype.map.call(table.querySelectorAll('thead th'), function (th) {
            return th.textContent.replace(/\s+/g, ' ').trim();
        });
        table.querySelectorAll('tbody tr').forEach(function (tr) {
            Array.prototype.forEach.call(tr.children, function (td, i) {
                if (!td.hasAttribute('data-label') && heads[i]) td.setAttribute('data-label', heads[i]);
            });
        });
    }
    function wrap(root) {
        (root || document).querySelectorAll('main table, .sajha-content table').forEach(function (t) {
            label(t);
            if (t.dataset.xscroll === 'done' || t.closest(SKIP) || t.parentElement.closest('table')) return;
            t.dataset.xscroll = 'done';
            if (scrollsX(t)) return;
            var box = document.createElement('div');
            box.className = 'sajha-xscroll';
            t.parentNode.insertBefore(box, t);
            box.appendChild(t);
        });
    }
    function start() {
        wrap(document);
        var main = document.getElementById('main-content');
        if (!main || !window.MutationObserver) return;
        var pending = null;
        new MutationObserver(function () {
            if (pending) return;
            pending = setTimeout(function () { pending = null; wrap(main); }, 120);
        }).observe(main, { childList: true, subtree: true });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();

    // Tap to read a title="" on touch screens (controls keep their normal tap behaviour).
    if (window.matchMedia && window.matchMedia('(hover: none)').matches) {
        var tip = null, hideTimer = null;
        document.addEventListener('click', function (e) {
            var el = e.target.closest('[title]');
            if (tip) { tip.remove(); tip = null; clearTimeout(hideTimer); }
            if (!el || el.closest('a, button, input, select, textarea, label, summary, [role=button]')) return;
            var text = el.getAttribute('title');
            if (!text) return;
            tip = document.createElement('div');
            tip.className = 'sajha-tap-tip';
            tip.setAttribute('role', 'status');
            tip.textContent = text;
            document.body.appendChild(tip);
            var r = el.getBoundingClientRect(), w = tip.offsetWidth;
            var left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2));
            tip.style.left = left + 'px';
            tip.style.top = (window.scrollY + r.bottom + 6) + 'px';
            hideTimer = setTimeout(function () { if (tip) { tip.remove(); tip = null; } }, 4000);
        });
    }
})();
