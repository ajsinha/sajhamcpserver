/**
 * SAJHA MCP Server v4.0.0 — Universal Table Enhancement
 * Copyright All rights Reserved 2025-2030, Ashutosh Sinha
 *
 * Auto-adds search, pagination, and rows-per-page to any table.
 *
 * Usage: Add data-enhance="true" to any <table>:
 *   <table class="table" data-enhance="true" data-page-sizes="10,25,50,100">
 *
 * Or call manually:
 *   enhanceTable(document.getElementById('myTable'));
 */

(function() {
    'use strict';

    function enhanceTable(table) {
        if (!table || table.dataset.enhanced === 'true') return;
        table.dataset.enhanced = 'true';

        const tbody = table.querySelector('tbody');
        if (!tbody) return;

        const allRows = Array.from(tbody.querySelectorAll('tr'));
        if (allRows.length < 5) return; // skip tiny tables

        let filteredRows = [...allRows];
        let currentPage = 1;
        const sizes = (table.dataset.pageSizes || '10,25,50,100').split(',').map(Number);
        let rowsPerPage = sizes[1] || 25;

        // ── Create controls container ──
        const controls = document.createElement('div');
        controls.className = 'd-flex flex-wrap align-items-center gap-3 mb-3';
        controls.innerHTML = `
            <div class="flex-grow-1">
                <div class="input-group input-group-sm" style="max-width:350px">
                    <span class="input-group-text"><i class="bi bi-search"></i></span>
                    <input type="text" class="form-control" placeholder="Search in table..." data-role="table-search">
                    <button class="btn btn-outline-secondary" type="button" data-role="table-clear" title="Clear"><i class="bi bi-x-lg"></i></button>
                </div>
            </div>
            <div class="d-flex align-items-center gap-2">
                <label class="form-label mb-0 small text-muted">Show</label>
                <select class="form-select form-select-sm" style="width:auto" data-role="table-pagesize">
                    ${sizes.map(s => `<option value="${s}" ${s===rowsPerPage?'selected':''}>${s}</option>`).join('')}
                    <option value="0">All</option>
                </select>
                <span class="small text-muted" data-role="table-count"></span>
            </div>
        `;

        // ── Create pagination container ──
        const paginationWrap = document.createElement('div');
        paginationWrap.className = 'd-flex justify-content-between align-items-center mt-2';
        paginationWrap.innerHTML = `
            <span class="small text-muted" data-role="table-info"></span>
            <nav><ul class="pagination pagination-sm mb-0" data-role="table-pagination"></ul></nav>
        `;

        // Insert controls before table, pagination after
        table.parentNode.insertBefore(controls, table);
        table.parentNode.insertBefore(paginationWrap, table.nextSibling);

        const searchInput = controls.querySelector('[data-role="table-search"]');
        const clearBtn = controls.querySelector('[data-role="table-clear"]');
        const pageSizeSelect = controls.querySelector('[data-role="table-pagesize"]');
        const countSpan = controls.querySelector('[data-role="table-count"]');
        const infoSpan = paginationWrap.querySelector('[data-role="table-info"]');
        const paginationUl = paginationWrap.querySelector('[data-role="table-pagination"]');

        function applyFilter() {
            const q = searchInput.value.toLowerCase().trim();
            filteredRows = allRows.filter(row => {
                if (!q) return true;
                return row.textContent.toLowerCase().includes(q);
            });
            currentPage = 1;
            render();
        }

        function render() {
            const total = filteredRows.length;
            const rpp = rowsPerPage || total;
            const totalPages = Math.max(1, Math.ceil(total / rpp));
            if (currentPage > totalPages) currentPage = totalPages;

            const start = (currentPage - 1) * rpp;
            const end = rowsPerPage ? start + rpp : total;

            // Hide all, show page
            allRows.forEach(r => r.style.display = 'none');
            filteredRows.slice(start, end).forEach(r => r.style.display = '');

            // Update count
            countSpan.textContent = `${total} of ${allRows.length}`;
            infoSpan.textContent = total > 0 ? `Showing ${start+1}–${Math.min(end, total)} of ${total}` : 'No results';

            // Pagination
            paginationUl.innerHTML = '';
            if (totalPages <= 1) return;

            const addPage = (label, page, disabled, active) => {
                const li = document.createElement('li');
                li.className = `page-item ${disabled?'disabled':''} ${active?'active':''}`;
                const a = document.createElement('a');
                a.className = 'page-link'; a.href = '#'; a.innerHTML = label;
                a.onclick = (e) => { e.preventDefault(); if (!disabled && page >= 1 && page <= totalPages) { currentPage = page; render(); } };
                li.appendChild(a);
                paginationUl.appendChild(li);
            };

            addPage('&laquo;', currentPage - 1, currentPage === 1);
            let s = Math.max(1, currentPage - 2), e = Math.min(totalPages, currentPage + 2);
            if (s > 1) { addPage('1', 1); if (s > 2) addPage('...', 0, true); }
            for (let i = s; i <= e; i++) addPage(i, i, false, i === currentPage);
            if (e < totalPages) { if (e < totalPages - 1) addPage('...', 0, true); addPage(totalPages, totalPages); }
            addPage('&raquo;', currentPage + 1, currentPage === totalPages);
        }

        // ── Event listeners ──
        searchInput.addEventListener('input', applyFilter);
        clearBtn.addEventListener('click', () => { searchInput.value = ''; applyFilter(); });
        pageSizeSelect.addEventListener('change', (e) => {
            rowsPerPage = parseInt(e.target.value) || 0;
            currentPage = 1;
            render();
        });

        // Initial render
        render();
    }

    // ── Auto-enhance on DOM load ──
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('table[data-enhance="true"]').forEach(enhanceTable);
    });

    // Expose globally
    window.enhanceTable = enhanceTable;
})();
