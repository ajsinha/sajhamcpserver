# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Static guard: an ``async def`` route never holds a database connection across an ``await``.

A session checks a pool connection out at its first query and keeps it until it is closed. An
async route that queried the database (through its ``get_db`` session, a session it opened, or
``AuthContext._db``) and then awaited something kept that connection while it waited;
enough such requests in flight emptied the pool, and every other request on the worker stalled
(docs/architecture/Scaling and State.md §7, "Database connections and concurrent calls").

The check, per async route function in ``sajha/routes/``:

* database names: parameters whose default is ``Depends(get_db)``, and locals assigned from
  ``get_db_session()`` or ``SessionLocal()``;
* a database use: a call that passes a database name (``UserDAO(db)``) or an AuthContext's session
  (``UserDAO(auth._db)``), or a method call on one (``db.query``, ``db.commit``).
  ``AuthContext.has_permission`` is not one: it reads the roles' permissions that ``release_db``
  loaded, in memory;
* a release: ``release_session(db)``, ``db.close()``, ``<x>.release_db()``, ``<x>.to_legacy_session()``,
  or the end of a ``with session_scope()`` block;
* an await that does not count: one whose callee is ``run_in_threadpool``, ``to_thread.run_sync`` or
  ``authorize_mcp`` (each runs the database part in the thread pool and releases it).

Any other ``await`` after a database use, with no release in between (by source order), fails the
test. ``ALLOWLIST`` names the routes that are known to be fine, each with the reason.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROUTES = Path(__file__).resolve().parents[1] / 'sajha' / 'routes'

#: awaits that hand the database part to the thread pool (and release there)
OFFLOAD = {'run_in_threadpool', 'run_sync', 'authorize_mcp'}
RELEASE_FUNCS = {'release_session'}
RELEASE_METHODS = {'close', 'release_db', 'to_legacy_session'}
SESSION_FACTORIES = {'get_db_session', 'SessionLocal', '_SessionLocal'}

#: "<module>.<function>": why holding the session across an await there is acceptable
ALLOWLIST: Dict[str, str] = {
}


def _name(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ''


def _is_route(fn: ast.AsyncFunctionDef) -> bool:
    for d in fn.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                and target.value.id in ('router', 'app') \
                and target.attr in ('get', 'post', 'put', 'patch', 'delete', 'api_route', 'websocket'):
            return True
    return False


def _db_params(fn: ast.AsyncFunctionDef) -> Set[str]:
    out: Set[str] = set()
    args = fn.args.args + fn.args.kwonlyargs
    defaults = [None] * (len(fn.args.args) - len(fn.args.defaults)) + list(fn.args.defaults) \
        + list(fn.args.kw_defaults)
    for a, d in zip(args, defaults):
        if isinstance(d, ast.Call) and _name(d.func) == 'Depends' and d.args and _name(d.args[0]) == 'get_db':
            out.add(a.arg)
    return out


def _walk_no_nested(node):
    """ast.walk without descending into nested function definitions or lambdas."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield n
        stack.extend(ast.iter_child_nodes(n))


def _events(fn: ast.AsyncFunctionDef) -> List[Tuple[int, int, str, str]]:
    """(line, col, kind, text) for every database use, release and counted await, in source order."""
    db_names = _db_params(fn)
    for n in _walk_no_nested(fn):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and _name(n.value.func) in SESSION_FACTORIES:
            for t in n.targets:
                if isinstance(t, ast.Name):
                    db_names.add(t.id)
    ev: List[Tuple[int, int, str, str]] = []
    offloaded = set()       # nodes inside an offload await: they run in the thread pool
    for n in _walk_no_nested(fn):
        if isinstance(n, ast.Await):
            callee = n.value.func if isinstance(n.value, ast.Call) else n.value
            if _name(callee) in OFFLOAD:
                offloaded.update(id(x) for x in ast.walk(n.value))
    for n in _walk_no_nested(fn):
        if id(n) in offloaded:
            continue
        if isinstance(n, ast.With) or isinstance(n, ast.AsyncWith):
            for item in n.items:
                if isinstance(item.context_expr, ast.Call) and _name(item.context_expr.func) == 'session_scope':
                    last = max(getattr(x, 'end_lineno', n.lineno) for x in n.body)
                    ev.append((last, 10_000, 'release', 'end of session_scope'))
        if isinstance(n, ast.Await):
            callee = n.value.func if isinstance(n.value, ast.Call) else n.value
            if _name(callee) not in OFFLOAD:
                ev.append((n.lineno, n.col_offset, 'await', ast.unparse(n)[:80]))
            continue
        if not isinstance(n, ast.Call):
            continue
        fname = _name(n.func)
        if fname in RELEASE_FUNCS and n.args and _name(n.args[0]) in db_names | {'db'}:
            ev.append((n.lineno, n.col_offset, 'release', ast.unparse(n)[:80]))
            continue
        if isinstance(n.func, ast.Attribute) and fname in RELEASE_METHODS:
            owner = n.func.value
            if fname != 'close' or (isinstance(owner, ast.Name) and owner.id in db_names):
                ev.append((n.lineno, n.col_offset, 'release', ast.unparse(n)[:80]))
                continue
        if isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id in db_names:
            ev.append((n.lineno, n.col_offset, 'use', ast.unparse(n)[:80]))
            continue
        if any((isinstance(a, ast.Name) and a.id in db_names) or (isinstance(a, ast.Attribute) and a.attr == '_db')
               for a in list(n.args) + [k.value for k in n.keywords]):
            if fname not in OFFLOAD:
                ev.append((n.lineno, n.col_offset, 'use', ast.unparse(n)[:80]))
    ev.sort()
    return ev


def find_holds() -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {}
    for path in sorted(ROUTES.glob('*.py')):
        tree = ast.parse(path.read_text(), filename=str(path))
        for fn in ast.walk(tree):
            if not (isinstance(fn, ast.AsyncFunctionDef) and _is_route(fn)):
                continue
            held, problems = None, []
            for line, _col, kind, text in _events(fn):
                if kind == 'use':
                    held = held or (line, text)
                elif kind == 'release':
                    held = None
                elif kind == 'await' and held is not None:
                    problems.append(f'line {line}: `{text}` after the database use at line {held[0]} '
                                    f'(`{held[1]}`) with no release in between')
            if problems:
                found[f'{path.stem}.{fn.name}'] = problems
    return found


def test_no_async_route_holds_a_db_session_across_an_await():
    found = {k: v for k, v in find_holds().items() if k not in ALLOWLIST}
    msg = '\n'.join(f'{k}:\n  ' + '\n  '.join(v) for k, v in sorted(found.items()))
    assert not found, ('async routes that keep a database connection across an await; release it first '
                       '(release_session(db) / auth.release_db()) or run the database part in the thread '
                       'pool (run_in_threadpool), see docs/architecture/Scaling and State.md §7:\n' + msg)


def test_allowlist_has_no_stale_entries():
    found = find_holds()
    stale = [k for k in ALLOWLIST if k not in found]
    assert not stale, f'ALLOWLIST entries that no longer hold a session across an await: {stale}'


def test_the_check_catches_a_hold(tmp_path):
    src = '''
from fastapi import Depends
from sajha.db.engine import get_db, release_session

@router.post('/bad')
async def bad(request, db = Depends(get_db)):
    user = UserDAO(db).get(1)
    await slow_call()

@router.post('/good')
async def good(request, db = Depends(get_db)):
    user = UserDAO(db).get(1)
    release_session(db)
    await slow_call()

@router.post('/offloaded')
async def offloaded(request, db = Depends(get_db)):
    user = await run_in_threadpool(UserDAO(db).get, 1)
    await slow_call()

@router.post('/authdb')
async def authdb(request, auth = Depends(get_current_user)):
    user = UserDAO(auth._db).get(1)
    await slow_call()

@router.post('/perm')
async def perm(request, auth = Depends(get_current_user)):
    if not auth.has_permission('tool', 'x', 'execute'):
        return None
    await slow_call()
'''
    (tmp_path / 'fake_routes.py').write_text(src)
    globals()['ROUTES'], old = tmp_path, ROUTES
    try:
        found = find_holds()
    finally:
        globals()['ROUTES'] = old
    assert set(found) == {'fake_routes.bad', 'fake_routes.authdb'}, found
