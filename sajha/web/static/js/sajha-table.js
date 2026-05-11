/**
 * SAJHA MCP Server — Universal Table Enhancement
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha
 *
 * Auto-adds search, pagination, and rows-per-page to any table with
 * class="table" inside a .card or .table-responsive container.
 *
 * Usage: Just include this script. It runs on DOMContentLoaded.
 *
 * Skip a table: add data-sajha-table="false"
 * Already has custom pagination (like tools_list): add data-sajha-table="false"
 */
(function() {
    'use strict';

    const MIN_ROWS_FOR_ENHANCEMENT = 5;
    const DEFAULT_ROWS_PER_PAGE = 10;
    const ROWS_OPTIONS = [5, 10, 25, 50, 100];

    document.addEventListener('DOMContentLoaded', function() {
        document.querySelectorAll('table.table').forEach(function(table, tableIndex) {
            // Skip if explicitly disabled or already enhanced
            if (table.dataset.sajhaTable === 'false') return;
            if (table.dataset.sajhaEnhanced === 'true') return;
            if (table.closest('[data-sajha-table="false"]')) return;

            const tbody = table.querySelector('tbody');
            if (!tbody) return;

            const allRows = Array.from(tbody.querySelectorAll('tr'));
            if (allRows.length < MIN_ROWS_FOR_ENHANCEMENT) return;

            table.dataset.sajhaEnhanced = 'true';
            const uid = 'st_' + tableIndex;

            // ── Create controls container ──
            const controls = document.createElement('div');
            controls.className = 'd-flex justify-content-between align-items-center mb-2 flex-wrap gap-2';
            controls.innerHTML = `
                <div class="d-flex align-items-center gap-2">
                    <div class="input-group input-group-sm" style="width:240px">
                        <span class="input-group-text"><i class="bi bi-search"></i></span>
                        <input type="text" class="form-control" id="${uid}_search" placeholder="Search in table...">
                        <button class="btn btn-outline-secondary" type="button" id="${uid}_clear" title="Clear"><i class="bi bi-x-lg"></i></button>
                    </div>
                    <span class="text-muted small" id="${uid}_count">${allRows.length} rows</span>
                </div>
                <div class="d-flex align-items-center gap-2">
                    <label class="form-label mb-0 small text-muted">Show</label>
                    <select class="form-select form-select-sm" id="${uid}_rpp" style="width:auto">
                        ${ROWS_OPTIONS.map(n => `<option value="${n}" ${n===DEFAULT_ROWS_PER_PAGE?'selected':''}>${n}</option>`).join('')}
                        <option value="all">All</option>
                    </select>
                </div>
            `;

            // Insert controls before the table (or before table-responsive wrapper)
            const wrapper = table.closest('.table-responsive') || table;
            wrapper.parentNode.insertBefore(controls, wrapper);

            // ── Create pagination container ──
            const pagDiv = document.createElement('div');
            pagDiv.className = 'd-flex justify-content-between align-items-center mt-2';
            pagDiv.innerHTML = `
                <span class="text-muted small" id="${uid}_info"></span>
                <nav><ul class="pagination pagination-sm mb-0" id="${uid}_pages"></ul></nav>
            `;
            wrapper.parentNode.insertBefore(pagDiv, wrapper.nextSibling);

            // ── State ──
            let filtered = allRows.slice();
            let page = 1;
            let rpp = DEFAULT_ROWS_PER_PAGE;

            // ── Search ──
            const searchInput = document.getElementById(uid + '_search');
            const clearBtn = document.getElementById(uid + '_clear');

            function applySearch() {
                const q = searchInput.value.toLowerCase().trim();
                filtered = allRows.filter(row => {
                    if (!q) return true;
                    return row.textContent.toLowerCase().includes(q);
                });
                page = 1;
                render();
            }

            searchInput.addEventListener('input', applySearch);
            clearBtn.addEventListener('click', function() { searchInput.value = ''; applySearch(); });

            // ── Rows per page ──
            document.getElementById(uid + '_rpp').addEventListener('change', function() {
                rpp = this.value === 'all' ? filtered.length : parseInt(this.value);
                page = 1;
                render();
            });

            // ── Render ──
            function render() {
                const total = filtered.length;
                const totalPages = rpp >= total ? 1 : Math.ceil(total / rpp);
                if (page > totalPages) page = totalPages;
                if (page < 1) page = 1;

                const start = (page - 1) * rpp;
                const end = Math.min(start + rpp, total);

                // Hide/show rows
                allRows.forEach(r => r.style.display = 'none');
                for (let i = start; i < end; i++) {
                    if (filtered[i]) filtered[i].style.display = '';
                }

                // Update count
                document.getElementById(uid + '_count').textContent =
                    filtered.length === allRows.length
                        ? `${allRows.length} rows`
                        : `${filtered.length} of ${allRows.length} rows`;

                // Update info
                document.getElementById(uid + '_info').textContent =
                    total > 0
                        ? `Showing ${start+1}-${end} of ${total}`
                        : 'No matching rows';

                // Build pagination
                const pagesEl = document.getElementById(uid + '_pages');
                pagesEl.innerHTML = '';
                if (totalPages <= 1) return;

                function addPage(label, p, disabled, active) {
                    const li = document.createElement('li');
                    li.className = 'page-item' + (disabled ? ' disabled' : '') + (active ? ' active' : '');
                    const a = document.createElement('a');
                    a.className = 'page-link';
                    a.href = '#';
                    a.innerHTML = label;
                    a.addEventListener('click', function(e) {
                        e.preventDefault();
                        if (!disabled && p >= 1 && p <= totalPages) { page = p; render(); }
                    });
                    li.appendChild(a);
                    pagesEl.appendChild(li);
                }

                addPage('&laquo;', page - 1, page === 1);
                let s = Math.max(1, page - 2), e = Math.min(totalPages, page + 2);
                if (s > 1) { addPage('1', 1); if (s > 2) addPage('...', 0, true); }
                for (let i = s; i <= e; i++) addPage(i, i, false, i === page);
                if (e < totalPages) { if (e < totalPages - 1) addPage('...', 0, true); addPage(totalPages, totalPages); }
                addPage('&raquo;', page + 1, page === totalPages);
            }

            render();
        });
    });
})();
