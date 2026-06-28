"""
SAJHA MCP Server v4.5.0 — Operations, Tenancy, Versioning & Plugins Routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""
import json, logging
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sajha.auth import AuthContext, require_auth, require_admin
from sajha.app import render

logger = logging.getLogger(__name__)
router = APIRouter(tags=['ops'])

# ── Health Probes ─────────────────────────────────────────────

@router.get('/health')
async def health_liveness():
    from sajha.observability import get_health
    h = get_health()
    return JSONResponse(h.liveness() if h else {'status': 'ok'})

@router.get('/ready')
async def health_readiness():
    from sajha.observability import get_health
    h = get_health()
    return JSONResponse(h.readiness() if h else {'status': 'ok'})

# ── Metrics ───────────────────────────────────────────────────

@router.get('/api/metrics')
async def api_metrics(auth: AuthContext = Depends(require_auth)):
    from sajha.observability import get_collector
    c = get_collector()
    if not c: return JSONResponse({'error': 'Metrics not initialized'})
    return JSONResponse(c.get_summary())

@router.get('/api/metrics/tools')
async def api_metrics_tools(auth: AuthContext = Depends(require_auth)):
    from sajha.observability import get_collector
    c = get_collector()
    if not c: return JSONResponse({'tools': []})
    return JSONResponse({'tools': c.get_all_metrics()})

@router.get('/api/metrics/tools/{tool_name}')
async def api_metrics_tool(tool_name: str, auth: AuthContext = Depends(require_auth)):
    from sajha.observability import get_collector
    c = get_collector()
    if not c: return JSONResponse({'error': 'Not found'}, 404)
    m = c.get_tool_metrics(tool_name)
    return JSONResponse(m if m else {'error': 'No metrics for tool'})

# ── Tool Versioning ───────────────────────────────────────────

@router.get('/api/tool-versions')
async def api_list_versions(auth: AuthContext = Depends(require_auth)):
    from sajha.core.tool_versioning import ToolVersionManager
    # For now return from in-memory; later from DB
    return JSONResponse({'versions': []})

@router.post('/api/tool-versions/{tool_name}/deprecate')
async def api_deprecate_tool(tool_name: str, request: Request, auth: AuthContext = Depends(require_admin)):
    data = await request.json()
    from sajha.core.tool_versioning import ToolVersionManager
    return JSONResponse({'success': True, 'tool_name': tool_name})

# ── Contract Testing ──────────────────────────────────────────

@router.post('/api/contract-test/{tool_name}')
async def api_test_tool(tool_name: str, request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.core.tool_versioning import ContractTestRunner
    from sajha.app import tools_registry
    runner = ContractTestRunner(tools_registry)
    data = await request.json() if request.headers.get('content-length', '0') != '0' else {}
    result = runner.test_tool(tool_name, data.get('arguments'))
    return JSONResponse(result.to_dict())

@router.post('/api/contract-test')
async def api_test_all(auth: AuthContext = Depends(require_admin)):
    from sajha.core.tool_versioning import ContractTestRunner
    from sajha.app import tools_registry
    runner = ContractTestRunner(tools_registry)
    results = runner.test_all()
    passed = sum(1 for r in results if r.passed)
    return JSONResponse({
        'total': len(results), 'passed': passed, 'failed': len(results) - passed,
        'results': [r.to_dict() for r in results],
    })

# ── Multi-Tenancy ─────────────────────────────────────────────

@router.get('/api/tenants')
async def api_list_tenants(auth: AuthContext = Depends(require_admin)):
    from sajha.core.tenancy import get_tenant_manager
    tm = get_tenant_manager()
    return JSONResponse({'tenants': tm.list_tenants() if tm else []})

@router.post('/api/tenants')
async def api_create_tenant(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.core.tenancy import get_tenant_manager
    data = await request.json()
    tm = get_tenant_manager()
    if not tm: return JSONResponse({'error': 'Tenancy not initialized'}, 503)
    try:
        t = tm.create_tenant(data['id'], data['name'],
            tool_patterns=data.get('tool_patterns', ['*']),
            blocked_tools=data.get('blocked_tools', []))
        if 'quota' in data:
            from sajha.core.tenancy import TenantQuota
            t.quota = TenantQuota(**data['quota'])
        return JSONResponse({'success': True, 'tenant': t.to_dict()})
    except ValueError as e:
        return JSONResponse({'error': str(e)}, 409)

@router.get('/api/tenants/{tenant_id}')
async def api_get_tenant(tenant_id: str, auth: AuthContext = Depends(require_admin)):
    from sajha.core.tenancy import get_tenant_manager
    tm = get_tenant_manager()
    t = tm.get_tenant(tenant_id) if tm else None
    if not t: return JSONResponse({'error': 'Not found'}, 404)
    return JSONResponse(t.to_dict())

@router.put('/api/tenants/{tenant_id}')
async def api_update_tenant(tenant_id: str, request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.core.tenancy import get_tenant_manager
    data = await request.json()
    tm = get_tenant_manager()
    t = tm.update_tenant(tenant_id, **data) if tm else None
    if not t: return JSONResponse({'error': 'Not found'}, 404)
    return JSONResponse({'success': True})

@router.delete('/api/tenants/{tenant_id}')
async def api_delete_tenant(tenant_id: str, auth: AuthContext = Depends(require_admin)):
    from sajha.core.tenancy import get_tenant_manager
    tm = get_tenant_manager()
    if tm and tm.delete_tenant(tenant_id):
        return JSONResponse({'success': True})
    return JSONResponse({'error': 'Not found or cannot delete default'}, 404)

# ── Plugins ───────────────────────────────────────────────────

@router.get('/api/plugins')
async def api_list_plugins(auth: AuthContext = Depends(require_admin)):
    from sajha.core.plugins import get_plugin_manager
    pm = get_plugin_manager()
    if not pm: return JSONResponse({'plugins': []})
    return JSONResponse({
        'plugins': pm.list_plugins(),
        'status': pm.get_status(),
    })

@router.post('/api/plugins/{name}/load')
async def api_load_plugin(name: str, auth: AuthContext = Depends(require_admin)):
    from sajha.core.plugins import get_plugin_manager
    pm = get_plugin_manager()
    if not pm: return JSONResponse({'error': 'Plugin manager not initialized'}, 503)
    status = pm.load_plugin(name)
    return JSONResponse(status.to_dict())

@router.post('/api/plugins/{name}/unload')
async def api_unload_plugin(name: str, auth: AuthContext = Depends(require_admin)):
    from sajha.core.plugins import get_plugin_manager
    pm = get_plugin_manager()
    if pm and pm.unload_plugin(name):
        return JSONResponse({'success': True})
    return JSONResponse({'error': 'Not found'}, 404)

@router.post('/api/plugins/discover')
async def api_discover_plugins(auth: AuthContext = Depends(require_admin)):
    from sajha.core.plugins import get_plugin_manager
    pm = get_plugin_manager()
    if not pm: return JSONResponse({'plugins': []})
    manifests = pm.discover()
    return JSONResponse({'plugins': [m.to_dict() for m in manifests]})


# ── Entropy Guard API ────────────────────────────────────────────

@router.get('/api/entropy/tool/{tool_name}')
async def api_tool_entropy(tool_name: str, auth: AuthContext = Depends(require_auth)):
    """Get confidence score and entropy for a single tool."""
    from sajha.core.composition import get_tool_confidence, confidence_to_entropy
    confidence = get_tool_confidence(tool_name)
    entropy = confidence_to_entropy(confidence)
    return JSONResponse({
        'tool': tool_name,
        'confidence': round(confidence, 4),
        'entropy_bits': round(entropy, 3),
        'category': 'deterministic' if confidence >= 1.0 else 'stochastic',
    })


@router.post('/api/entropy/pipeline')
async def api_pipeline_entropy(request: Request, auth: AuthContext = Depends(require_auth)):
    """
    Pre-execution entropy analysis for a pipeline of tools.
    Body: {"tools": ["yahoo_quote", "calc_risk", "fmp_profile"], "threshold": 2.0}
    """
    from sajha.core.composition import EntropyGuard, get_tool_confidence
    body = await request.json()
    tools = body.get('tools', [])
    threshold = body.get('threshold', 3.0)

    guard = EntropyGuard(max_entropy_bits=threshold)
    for tool_name in tools:
        confidence = get_tool_confidence(tool_name)
        guard.record_step(tool_name, confidence)

    return JSONResponse(guard.check_safe('pipeline'))


# ═══════════════════════════════════════════════════════════════════
# v5.2.0 Operations APIs — Cache, Circuit Breakers, Health, Replay, Webhooks
# ═══════════════════════════════════════════════════════════════════

@router.get('/api/cache/stats')
async def cache_stats(auth: AuthContext = Depends(require_auth)):
    """Tool cache statistics."""
    from sajha.core.cache import get_tool_cache
    return get_tool_cache().stats()


@router.post('/api/cache/invalidate')
async def cache_invalidate(request: Request, auth: AuthContext = Depends(require_admin)):
    """Invalidate cache. Optional: {"tool_name": "yahoo_quote"} for specific tool."""
    from sajha.core.cache import get_tool_cache
    try:
        body = await request.json()
        tool_name = body.get('tool_name')
    except Exception:
        tool_name = None
    get_tool_cache().invalidate(tool_name)
    return {'invalidated': True, 'tool_name': tool_name or 'all'}


@router.get('/api/circuits')
async def circuit_breaker_status(auth: AuthContext = Depends(require_auth)):
    """Circuit breaker status for all providers."""
    from sajha.core.circuit_breaker import get_circuit_registry
    return {'circuits': get_circuit_registry().all_status()}


@router.get('/api/providers/health')
async def provider_health(auth: AuthContext = Depends(require_auth)):
    """Provider health status with dependency graph."""
    from sajha.core.tool_health import get_provider_health
    from sajha.app import tools_registry
    return {'providers': get_provider_health(tools_registry)}


@router.get('/api/providers/graph')
async def provider_dependency_graph(auth: AuthContext = Depends(require_auth)):
    """Tool dependency graph — tools → providers → APIs."""
    from sajha.core.tool_health import build_dependency_graph
    from sajha.app import tools_registry
    return {'graph': build_dependency_graph(tools_registry)}


@router.get('/api/replay/recent')
async def replay_recent(auth: AuthContext = Depends(require_auth)):
    """Recent tool executions across all tools."""
    from sajha.core.tool_health import get_replay_store
    return {'executions': get_replay_store().get_recent(50)}


@router.get('/api/replay/tool/{tool_name}')
async def replay_tool_history(tool_name: str, auth: AuthContext = Depends(require_auth)):
    """Execution history for a specific tool."""
    from sajha.core.tool_health import get_replay_store
    return {'tool': tool_name, 'executions': get_replay_store().get_history(tool_name)}


@router.get('/api/replay/stats')
async def replay_stats(auth: AuthContext = Depends(require_auth)):
    """Execution replay statistics."""
    from sajha.core.tool_health import get_replay_store
    return get_replay_store().stats()


@router.get('/api/webhooks')
async def webhook_subscriptions(auth: AuthContext = Depends(require_admin)):
    """List all webhook subscriptions."""
    from sajha.core.webhooks import get_webhook_manager
    mgr = get_webhook_manager()
    return {'subscriptions': mgr.list_subscriptions(), 'stats': mgr.delivery_stats()}


@router.post('/api/webhooks/subscribe')
async def webhook_subscribe(request: Request, auth: AuthContext = Depends(require_admin)):
    """Subscribe to webhook events. Body: {"event": "tool.completed", "url": "https://..."}"""
    from sajha.core.webhooks import get_webhook_manager
    body = await request.json()
    event = body.get('event', '')
    url = body.get('url', '')
    if not event or not url:
        return JSONResponse({'error': 'event and url required'}, status_code=400)
    get_webhook_manager().subscribe(event, url)
    return {'subscribed': True, 'event': event, 'url': url}


@router.delete('/api/webhooks/unsubscribe')
async def webhook_unsubscribe(request: Request, auth: AuthContext = Depends(require_admin)):
    """Unsubscribe from webhook events."""
    from sajha.core.webhooks import get_webhook_manager
    body = await request.json()
    get_webhook_manager().unsubscribe(body.get('event', ''), body.get('url', ''))
    return {'unsubscribed': True}


@router.get('/api/audit')
async def audit_log(request: Request, auth: AuthContext = Depends(require_admin)):
    """Query audit log. Params: action, user_id, from, to, limit."""
    from sajha.db.engine import get_db_session
    from sajha.db.models import AuditLog
    db = get_db_session()
    try:
        query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
        action = request.query_params.get('action')
        user_id = request.query_params.get('user_id')
        limit = int(request.query_params.get('limit', 100))
        if action:
            query = query.filter(AuditLog.action == action)
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        rows = query.limit(min(limit, 500)).all()
        return {'entries': [{
            'id': r.id, 'action': r.action, 'user_id': r.user_id,
            'resource_type': r.resource_type, 'resource_id': r.resource_id,
            'details': r.details, 'ip_address': r.ip_address,
            'created_at': str(r.created_at),
        } for r in rows]}
    except Exception as e:
        logger.error(f"Audit query error: {e}", exc_info=True)
        return {'entries': [], 'error': str(e)}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# ASYNC TOOL EXECUTION (v5.2.0)
# ═══════════════════════════════════════════════════════════════════

@router.post('/api/tools/{tool_name}/execute-async')
async def execute_tool_async(tool_name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    """Submit a tool for async background execution with delivery routing."""
    import queue as queue_mod
    from sajha.core.async_executor import get_async_executor
    body = await request.json()

    # Extract async delivery config
    async_config = body.pop('async', body.pop('delivery', {}))
    delivery_type = async_config.get('delivery', async_config.get('type', 'webhook'))
    destination = async_config.get('destination', '')
    if not destination:
        return JSONResponse({'error': 'async.destination required (URL, topic, or path)'}, status_code=400)
    if delivery_type not in ('webhook', 'kafka', 'file'):
        return JSONResponse({'error': 'delivery must be webhook, kafka, or file'}, status_code=400)

    try:
        executor = get_async_executor()
        task = executor.submit(
            tool_name=tool_name,
            arguments=body,
            delivery_type=delivery_type,
            delivery_destination=destination,
            delivery_config=async_config,
            user_id=auth.user_id,
        )
        return {
            'task_id': task.task_id,
            'status': 'queued',
            'tool_name': tool_name,
            'delivery': delivery_type,
            'destination': destination,
            'poll_url': f'/api/async/tasks/{task.task_id}',
        }
    except queue_mod.Full:
        return JSONResponse({'error': 'Queue full — try again later', 'queue_size': executor._queue.maxsize}, status_code=503)
    except Exception as e:
        logger.error(f"Async submit error: {e}", exc_info=True)
        return JSONResponse({'error': str(e)}, status_code=500)


@router.get('/api/async/tasks')
async def list_async_tasks(request: Request, auth: AuthContext = Depends(require_auth)):
    """List async tasks. Optional filter: ?status=queued|running|completed|failed"""
    from sajha.core.async_executor import get_async_executor
    status = request.query_params.get('status')
    limit = int(request.query_params.get('limit', 100))
    executor = get_async_executor()
    return {'tasks': executor.list_tasks(status=status, limit=limit), 'stats': executor.stats()}


@router.get('/api/async/tasks/{task_id}')
async def get_async_task(task_id: str, auth: AuthContext = Depends(require_auth)):
    """Get async task status and result."""
    from sajha.core.async_executor import get_async_executor
    task = get_async_executor().get_task(task_id)
    if not task:
        return JSONResponse({'error': 'Task not found'}, status_code=404)
    return task.to_full_dict()


@router.post('/api/async/tasks/{task_id}/cancel')
async def cancel_async_task(task_id: str, auth: AuthContext = Depends(require_auth)):
    """Cancel a queued async task."""
    from sajha.core.async_executor import get_async_executor
    if get_async_executor().cancel_task(task_id):
        return {'cancelled': True, 'task_id': task_id}
    return JSONResponse({'error': 'Task not found or not cancellable'}, status_code=400)


@router.post('/api/async/tasks/{task_id}/retry')
async def retry_async_task(task_id: str, auth: AuthContext = Depends(require_auth)):
    """Retry a failed async task."""
    from sajha.core.async_executor import get_async_executor
    task = get_async_executor().retry_task(task_id)
    if task:
        return {'task_id': task.task_id, 'status': 'queued', 'retried_from': task_id}
    return JSONResponse({'error': 'Task not found or not retryable'}, status_code=400)


@router.get('/api/async/stats')
async def async_executor_stats(auth: AuthContext = Depends(require_auth)):
    """Async executor statistics."""
    from sajha.core.async_executor import get_async_executor
    return get_async_executor().stats()


@router.get('/admin/async-tasks')
async def admin_async_tasks_page(request: Request, auth: AuthContext = Depends(require_admin)):
    """Async tasks management page."""
    return render(request, 'admin/async_tasks.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
    })


# ═══════════════════════════════════════════════════════════════════
# SHELL EXECUTION — Sandboxed Python & Bash (v5.2.0)
# ═══════════════════════════════════════════════════════════════════

@router.post('/api/shell/python')
async def shell_execute_python(request: Request, auth: AuthContext = Depends(require_auth)):
    """Execute Python code in sandbox. Requires shell.enabled=true in config."""
    from sajha.core.shell_executor import get_shell_executor
    executor = get_shell_executor()
    if not executor.python_enabled:
        return JSONResponse({'error': 'Python execution is disabled. Set shell.enabled=true in config.'}, status_code=403)
    body = await request.json()
    code = body.get('code', '')
    if not code:
        return JSONResponse({'error': 'code is required'}, status_code=400)
    result = executor.execute_python(code, user_id=auth.user_id)
    return result.to_dict()


@router.post('/api/shell/bash')
async def shell_execute_bash(request: Request, auth: AuthContext = Depends(require_auth)):
    """Execute bash command in sandbox. Requires shell.enabled=true AND shell.bash.enabled=true."""
    from sajha.core.shell_executor import get_shell_executor
    executor = get_shell_executor()
    if not executor.bash_enabled:
        return JSONResponse({'error': 'Bash execution is disabled. Set shell.enabled=true and shell.bash.enabled=true.'}, status_code=403)
    body = await request.json()
    command = body.get('command', '')
    if not command:
        return JSONResponse({'error': 'command is required'}, status_code=400)
    result = executor.execute_bash(command, user_id=auth.user_id)
    return result.to_dict()


@router.get('/api/shell/capabilities')
async def shell_capabilities(auth: AuthContext = Depends(require_auth)):
    """Get shell execution capabilities and security policies."""
    from sajha.core.shell_executor import get_shell_executor
    return get_shell_executor().get_capabilities()


@router.get('/api/shell/history')
async def shell_history(auth: AuthContext = Depends(require_admin)):
    """Get recent shell execution history (admin only)."""
    from sajha.core.shell_executor import get_shell_executor
    limit = 50
    return {'executions': get_shell_executor().get_history(limit)}


@router.get('/api/admin/system-monitor')
async def admin_system_monitor_api(auth: AuthContext = Depends(require_admin)):
    """System monitor API — returns CPU, memory, disk, network, process data."""
    import os, sys, time, platform, socket

    data = {
        'python_version': platform.python_version(),
        'platform': f"{platform.system()} {platform.release()} ({platform.machine()})",
        'hostname': socket.gethostname(),
        'mcp_protocol_version': '2025-11-25',
        'sajha_version': '5.2.0',
        'db_type': 'unknown',
        'tools_loaded': 0,
    }
    try:
        from sajha.core.config import get_settings
        _s = get_settings()
        data['sajha_version'] = _s.app_version
        data['db_type'] = _s.db_type
    except Exception:
        pass
    try:
        from sajha.app import tools_registry
        data['tools_loaded'] = len(tools_registry.tools) if tools_registry else 0
    except Exception:
        pass

    try:
        import psutil
        cpu_pct = psutil.cpu_percent(interval=0.5)
        load = os.getloadavg() if hasattr(os, 'getloadavg') else [0, 0, 0]
        cpu_stats = psutil.cpu_stats()
        cpu_model = platform.processor() or 'Unknown'
        try:
            with open('/proc/cpuinfo') as f:
                for line in f:
                    if 'model name' in line:
                        cpu_model = line.split(':')[1].strip(); break
        except Exception: pass
        data['cpu'] = {'percent': cpu_pct, 'physical_cores': psutil.cpu_count(logical=False) or 0, 'logical_cores': psutil.cpu_count(logical=True) or 0, 'architecture': platform.machine(), 'model': cpu_model[:60], 'load_avg': list(load), 'ctx_switches': cpu_stats.ctx_switches if cpu_stats else 0, 'interrupts': cpu_stats.interrupts if cpu_stats else 0}
        mem = psutil.virtual_memory(); swap = psutil.swap_memory()
        data['memory'] = {'total': mem.total, 'used': mem.used, 'available': mem.available, 'percent': mem.percent, 'cached': getattr(mem, 'cached', 0), 'buffers': getattr(mem, 'buffers', 0), 'swap_total': swap.total, 'swap_used': swap.used}
        disk = psutil.disk_usage('/')
        data['disk'] = {'total': disk.total, 'used': disk.used, 'free': disk.free, 'percent': disk.percent, 'mount_point': '/', 'filesystem': '', 'db_file_size': 0}
        net = psutil.net_io_counters()
        data['network'] = {'bytes_sent': net.bytes_sent, 'bytes_recv': net.bytes_recv, 'packets_sent': net.packets_sent, 'packets_recv': net.packets_recv, 'errin': net.errin, 'errout': net.errout, 'connections': len(psutil.net_connections(kind='inet'))}
        boot = psutil.boot_time()
        data['uptime_seconds'] = time.time() - boot
        data['boot_time'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(boot))
        proc = psutil.Process(os.getpid()); mem_info = proc.memory_info()
        data['process'] = {'pid': proc.pid, 'cpu_percent': proc.cpu_percent(interval=0.1), 'memory_percent': proc.memory_percent(), 'rss': mem_info.rss, 'vms': mem_info.vms, 'threads': proc.num_threads(), 'open_fds': proc.num_fds() if hasattr(proc, 'num_fds') else 0}
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent', 'memory_info', 'status', 'cmdline']):
            try:
                info = p.info
                procs.append({'pid': info['pid'], 'user': info.get('username', ''), 'cpu': info.get('cpu_percent', 0) or 0, 'mem': info.get('memory_percent', 0) or 0, 'rss': info['memory_info'].rss if info.get('memory_info') else 0, 'status': info.get('status', ''), 'cmd': ' '.join(info.get('cmdline') or [info.get('name', '')])[:120]})
            except (psutil.NoSuchProcess, psutil.AccessDenied): pass
        procs.sort(key=lambda x: x['cpu'], reverse=True)
        data['top_processes'] = procs[:15]
        data['total_processes'] = len(procs)
    except ImportError:
        data['cpu'] = {'percent': 0, 'physical_cores': os.cpu_count() or 0, 'logical_cores': os.cpu_count() or 0, 'architecture': platform.machine(), 'model': 'Unknown', 'load_avg': list(os.getloadavg()) if hasattr(os, 'getloadavg') else [0,0,0], 'ctx_switches': 0, 'interrupts': 0}
        data['memory'] = {'total': 0, 'used': 0, 'available': 0, 'percent': 0, 'cached': 0, 'buffers': 0, 'swap_total': 0, 'swap_used': 0}
        data['disk'] = {'total': 0, 'used': 0, 'free': 0, 'percent': 0, 'mount_point': '/', 'filesystem': '', 'db_file_size': 0}
        data['network'] = {'bytes_sent': 0, 'bytes_recv': 0, 'packets_sent': 0, 'packets_recv': 0, 'errin': 0, 'errout': 0, 'connections': 0}
        data['process'] = {'pid': os.getpid(), 'cpu_percent': 0, 'memory_percent': 0, 'rss': 0, 'vms': 0, 'threads': 0, 'open_fds': 0}
        data['uptime_seconds'] = 0; data['boot_time'] = '—'
        data['top_processes'] = []; data['total_processes'] = 0
    return data
