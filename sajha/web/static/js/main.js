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
             style="background: rgba(0,0,0,0.5); z-index: 9999;">
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
