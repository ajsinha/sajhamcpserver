#!/usr/bin/env python3
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA local test lab: three SAJHA instances in one SAJHA Net on one laptop, with a local Ollama as
their LLM.

    python deployment/local-lab/lab.py start      # generate what is missing, start the three, wait until healthy
    python deployment/local-lab/lab.py status     # PIDs, health, net members, the URLs and credentials
    python deployment/local-lab/lab.py stop       # stop the three (and the MCP server risk-eu proxies)
    python deployment/local-lab/lab.py kill cust-na    # a crash (SIGKILL): the others notice by gossip
    python deployment/local-lab/lab.py reset      # stop, then delete the instances' folders: the next start is a new net
    python deployment/local-lab/lab.py stop cust-na    # one instance (every command takes names)

Each instance has its own generated configuration, database, data folder, tools folder, policies
folder, keys files and log under deployment/local-lab/run/<instance>/ (git-ignored). The instances
run from this checkout with the Python that runs this script, through run_sajha_web.py.

This is a lab: plain HTTP on 127.0.0.1, open admission, the test admin key and a known password.
The walkthrough is docs/tutorials/TUTORIAL_29_local_test_lab.md.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RUN = Path(os.environ.get('SAJHA_LAB_DIR') or HERE / 'run')
NET = 'lab-net'
TEST_ADMIN_KEY = 'sja_test_admin_dev_key_0001'          # config/apikeys.json.example
TEST_ADMIN_USER, TEST_ADMIN_PASSWORD = 'testadmin', 'testadmin-dev-1'   # config/users.json.example
OLLAMA = os.environ.get('SAJHA_LAB_OLLAMA', 'http://127.0.0.1:11434')
CHAT_MODEL = os.environ.get('SAJHA_LAB_MODEL', 'qwen3:8b')
FAST_MODEL = os.environ.get('SAJHA_LAB_FAST_MODEL', 'qwen2.5:3b')
EMBED_MODEL = os.environ.get('SAJHA_LAB_EMBED_MODEL', 'nomic-embed-text')
PORT = int(os.environ.get('SAJHA_LAB_PORT', '3002'))     # risk-eu; cust-na and treasury-eu take the next two
# One loopback address per instance, so a browser keeps a separate sign-in for each (cookies ignore the
# port). Linux answers on all of 127.0.0.0/8; elsewhere set SAJHA_LAB_ONE_HOST=1 (then use one browser
# profile or private window per instance).
ONE_HOST = os.environ.get('SAJHA_LAB_ONE_HOST', '').lower() in ('1', 'true', 'yes')
HOSTS = ['127.0.0.1'] * 3 if ONE_HOST else ['127.0.0.1', '127.0.0.2', '127.0.0.3']

# The lab's layout. "remove": tools left out of this instance's copy of config/tools, so a call for
# them here must cross the net (a disabled tool would still hold the name locally). "llm_tools":
# example LLM tools (shipped disabled) the lab enables here.
INSTANCES = [
    {'name': 'risk-eu', 'host': HOSTS[0], 'port': PORT, 'region': 'eu', 'seeds': [],
     'labels': {'site': 'laptop', 'team': 'risk'},
     'proxied': True, 'rag': True, 'llm_tools': ['llm_summarise', 'llm_docs_qa'],
     'remove': ['calc_loan_amortization', 'calc_retirement']},
    {'name': 'cust-na', 'host': HOSTS[1], 'port': PORT + 1, 'region': 'na', 'seeds': [f'http://{HOSTS[0]}:{PORT}'],
     'labels': {'site': 'laptop', 'team': 'customers'},
     'proxied': False, 'rag': False, 'llm_tools': ['llm_triage_ticket'],
     'remove': ['calc_retirement']},
    {'name': 'treasury-eu', 'host': HOSTS[2], 'port': PORT + 2, 'region': 'eu', 'seeds': [f'http://{HOSTS[0]}:{PORT}'],
     'labels': {'site': 'laptop', 'team': 'treasury'},
     'proxied': False, 'rag': False, 'llm_tools': [],
     'remove': []},
]
# What each instance offers the others, and what it takes from them.
EXPORT = [{'tools': ['calc_*', 'llm_*', 'units__*']}]
IMPORT = [{'tools': ['*']}]


def say(msg: str) -> None:
    print(msg, flush=True)


def inst_dir(i: dict) -> Path:
    return RUN / i['name']


def url(i: dict) -> str:
    return f'http://{i["host"]}:{i["port"]}'


def pid_file(i: dict) -> Path:
    return inst_dir(i) / 'server.pid'


# ── configuration ───────────────────────────────────────────────────

def _merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def _ai_section(base_ai: dict) -> dict:
    ai = copy.deepcopy(base_ai or {})
    providers = []
    for p in ai.get('providers') or []:
        p = copy.deepcopy(p)
        if p.get('name') == 'ollama':
            p['config'] = {'enabled': True, 'base_url': OLLAMA,
                           'think': False,           # no thinking: qwen3 answers short prompts in about a second on a CPU
                           'num_ctx': 8192,          # room for the tool definitions Ask SAJHA sends (Ollama's default is 4096)
                           'keep_alive': '30m'}      # keep the models loaded between questions
        providers.append(p)
    ai['providers'] = providers
    ai['aliases'] = {'default': [f'ollama/{CHAT_MODEL}'], 'fast': [f'ollama/{FAST_MODEL}'],
                     'reasoning': [f'ollama/{CHAT_MODEL}'], 'embedding': [f'ollama/{EMBED_MODEL}'],
                     'toolsmith': [f'ollama/{CHAT_MODEL}']}
    ai.setdefault('policy', {})['roles'] = {'viewer': {'allowed': ['mock/*', 'ollama/*'], 'tools': False}}
    # A CPU reads a prompt at a few dozen tokens a second, and every offered tool is part of the prompt:
    # offer fewer tools and allow minutes, not seconds.
    ai.setdefault('ask', {}).update({'timeout_s': 600, 'shortlist': 6})
    ai.setdefault('llm_tools', {}).setdefault('limits', {})['timeout_s'] = 600
    ai.setdefault('openai_api', {})['enabled'] = True
    return ai


def generate(i: dict) -> Path:
    """Write the instance's folder (only what is missing) and return its application.yml."""
    import yaml
    d = inst_dir(i)
    cfg_dir, data = d / 'config', d / 'data'
    for sub in (cfg_dir / 'federation', data / 'duckdb', data / 'sqlselect'):
        sub.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    # Credential files: the test admin key and the test administrator, from the shipped examples.
    for name in ('apikeys.json', 'users.json'):
        target = cfg_dir / name
        if not target.exists():
            shutil.copyfile(REPO / 'config' / f'{name}.example', target)
            os.chmod(target, 0o600)
    # Tools and policies: a copy per instance, so one instance can differ (the lab's layout, a
    # changed contract, a residency rule) without touching the others or the checkout.
    tools = cfg_dir / 'tools'
    if not tools.exists():
        shutil.copytree(REPO / 'config' / 'tools', tools)
        for name in i['remove']:
            (tools / f'{name}.json').unlink(missing_ok=True)
        for name in i['llm_tools']:
            _set_enabled(tools / f'{name}.json', True)
        if i['rag']:                    # the documentation tool answers from the lab's own source
            _patch(tools / 'llm_docs_qa.json', lambda t: t['llm'].setdefault('rag', {}).update({'sources': ['lab']}))
    policies = cfg_dir / 'policies'
    if not policies.exists():
        shutil.copytree(REPO / 'config' / 'policies', policies)
    duck = REPO / 'data' / 'duckdb'
    if duck.is_dir() and not any((data / 'duckdb').iterdir()):
        for f in duck.iterdir():
            if f.is_file() and not f.name.endswith('.wal'):
                shutil.copyfile(f, data / 'duckdb' / f.name)
    mcp_file = cfg_dir / 'mcp_servers.json'
    if i['proxied'] and mcp_file.exists():
        # keep your edits, but run the units server with this Python (the one that has the MCP SDK)
        _patch(mcp_file, lambda d: (d.get('mcpServers') or {}).get('units', {}).update({'command': sys.executable})
               if 'units' in (d.get('mcpServers') or {}) else None)
    if i['proxied'] and not mcp_file.exists():
        # An external server this instance embeds and proxies (stdio, no credentials, offline): the
        # units example server. Its tools appear here and in the net as units__<tool>.
        mcp_file.write_text(json.dumps({'mcpServers': {'units': {
            'command': sys.executable,
            'args': [str(REPO / 'sajha' / 'examples' / 'federation' / 'units_server.py'), '--stdio'],
            'vendor': 'units',
            'tools': ['celsius_to_fahrenheit', 'kilometres_to_miles']}}}, indent=2) + '\n')

    base = yaml.safe_load((REPO / 'config' / 'application.yml').read_text(encoding='utf-8')) or {}
    rel = lambda p: str(p)                                                      # noqa: E731 (absolute paths)
    over = {
        'server': {'host': i['host'], 'port': i['port']},
        'db': {'type': 'sqlite', 'path': rel(d / 'sajha.db')},
        'data': {'dir': rel(data), 'duckdb': {'dir': rel(data / 'duckdb')}, 'sqlselect': {'dir': rel(data / 'sqlselect')}},
        'config': {'tools': {'dir': rel(tools)}, 'apikeys': {'path': rel(cfg_dir / 'apikeys.json')}},
        'auth': {'users_file': {'path': rel(cfg_dir / 'users.json')},
                 'api_keys': {'db_dump_path': rel(cfg_dir / 'apikeys_db.json')}},
        'hot_reload': {'interval_seconds': 10},
        'cache': {'dir': rel(data / 'cache')},
        'async': {'delivery': {'file': {'base_dir': rel(data / 'async_results')}}},
        'shell': {'scratch_dir': rel(data / 'shell_scratch')},
        'policy': {'dir': rel(policies), 'reload_seconds': 2},
        'snapshots': {'dir': rel(data / 'snapshots')},
        'federation': {'enabled': bool(i['proxied']), 'allow_stdio': bool(i['proxied']),
                       'require_approval': False,
                       'state_path': rel(cfg_dir / 'federation' / 'federation.json'),
                       'mcp_servers_file': rel(mcp_file)},
        'ai': _ai_section(base.get('ai')),
        'sajhanet': {
            'enabled': True,
            'require_https': False,                 # a lab on one machine: plain HTTP on loopback
            'base_url': url(i),
            'region': i['region'],
            'labels': i['labels'],
            'data_dir': rel(data / 'sajhanet'),
            'refresh_interval_seconds': 30,
            'peer_keys': {},
            'nets': [{'name': NET, 'instance_name': i['name'], 'seeds': i['seeds'],
                      'export': EXPORT, 'import': IMPORT}],
        },
    }
    cfg = _merge(base, over)
    cfg['sajhanet']['peer_keys'] = {}       # drop the shipped sample (a merge would keep it)
    rag = cfg['ai'].setdefault('rag', {})
    rag.setdefault('stores', {}).setdefault('sqlite_vec', {})['path'] = rel(data / 'rag' / 'vectors.db')
    # Document search: embedding all of SAJHA's guides takes the better part of an hour on a CPU, so the
    # lab indexes only this folder's guide (on risk-eu). Set ai.rag.index_sajha_docs: true in local.yml
    # for everything.
    rag.update({'uploads_dir': rel(data / 'rag' / 'uploads'), 'index_path': rel(data / 'rag' / 'index.json'),
                'index_sajha_docs': False,
                'sources': [{'name': 'lab', 'path': 'deployment/local-lab', 'pattern': '*.md',
                             'title': 'SAJHA local test lab'}] if i['rag'] else []})
    llm_tools = cfg['ai'].setdefault('llm_tools', {})
    llm_tools.setdefault('memory', {}).setdefault('spool', {})['dir'] = rel(data / 'spool' / 'llm_tools')
    # Your own settings, merged last (a list, such as sajhanet.nets, replaces the generated one whole):
    # run/local.yml for all three, then run/<instance>/local.yml for one.
    env: dict = {}
    for local in (RUN / 'local.yml', d / 'local.yml'):
        if local.exists():
            extra = yaml.safe_load(local.read_text(encoding='utf-8')) or {}
            env.update({str(k): str(v) for k, v in (extra.pop('lab_env', None) or {}).items()})
            _merge(cfg, extra)
    # lab_env: environment variables for the instance (the lab does not pass on your shell's SAJHA_*)
    (d / 'env.json').write_text(json.dumps(env, indent=2) + '\n', encoding='utf-8')
    path = d / 'application.yml'
    header = (f'# Generated by deployment/local-lab/lab.py for {i["name"]} at every start (a lab: never use these '
              f'settings elsewhere).\n# Edits here are lost; put settings of your own in local.yml beside it '
              f'(or in {RUN.name}/local.yml for all three).\n')
    path.write_text(header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding='utf-8')
    return path


def _patch(path: Path, change) -> None:
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding='utf-8'))
    change(data)
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def _set_enabled(path: Path, on: bool) -> None:
    _patch(path, lambda t: t.update({'enabled': on}))


# ── processes ───────────────────────────────────────────────────────

def _pid(i: dict) -> int | None:
    try:
        pid = int(pid_file(i).read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def _get(url: str, key: str | None = None, timeout: float = 3.0):
    req = urllib.request.Request(url, headers={'X-API-Key': key} if key else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def _healthy(i: dict) -> bool:
    try:
        return _get(f'{url(i)}/health').get('status') == 'healthy'
    except Exception:
        return False


def _port_busy(host: str, port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _check_ollama() -> None:
    try:
        tags = _get(f'{OLLAMA}/api/tags')
    except Exception:
        say(f'warning: Ollama does not answer on {OLLAMA}; start it (`ollama serve`) before asking questions')
        return
    have = {m.get('name', '').removesuffix(':latest') for m in tags.get('models') or []}
    missing = [m for m in (CHAT_MODEL, FAST_MODEL, EMBED_MODEL) if m.removesuffix(':latest') not in have]
    if missing:
        say(f'warning: Ollama lacks {", ".join(missing)}; run `ollama pull <model>` for each')


def _check_mcp_sdk() -> None:
    try:
        import mcp  # noqa: F401  (federation connects to proxied MCP servers through the official SDK)
    except ImportError:
        say('warning: the MCP SDK is not installed in this Python, so risk-eu cannot connect to its proxied '
            'server (units__ tools); install it: pip install "mcp>=2.3,<3" (it is in requirements-dev.txt)')


def start(selected: list[dict]) -> int:
    _check_ollama()
    _check_mcp_sdk()
    started = []
    for i in selected:
        if _pid(i):
            say(f'{i["name"]}: already running (pid {_pid(i)})')
            continue
        if _port_busy(i['host'], i['port']):
            say(f'{i["name"]}: {i["host"]}:{i["port"]} is in use by another process; stop it first '
                f'(lsof -i :{i["port"]}), or move the lab: SAJHA_LAB_PORT=3102 {Path(sys.argv[0]).name} start')
            return 1
        cfg = generate(i)
        log = open(inst_dir(i) / 'server.log', 'ab')
        env = {k: v for k, v in os.environ.items() if not k.startswith('SAJHA_')}
        env.update(json.loads((inst_dir(i) / 'env.json').read_text(encoding='utf-8')))
        env.update({'PYTHONUNBUFFERED': '1', 'SAJHA_CONFIG_FILE': str(cfg)})
        p = subprocess.Popen([sys.executable, str(REPO / 'run_sajha_web.py'), '--config', str(cfg)],
                             cwd=str(REPO), env=env, stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        pid_file(i).write_text(str(p.pid))
        started.append(i)
        say(f'{i["name"]}: starting on {url(i)} (pid {p.pid}, log {inst_dir(i) / "server.log"})')
        if not i['seeds']:
            _wait([i])                    # the seed first, so the others join at once
    ok = _wait(started)
    status(selected)
    return 0 if ok else 1


def _wait(items: list[dict], timeout: float = 180) -> bool:
    deadline = time.time() + timeout
    pending = list(items)
    while pending and time.time() < deadline:
        for i in list(pending):
            if _healthy(i):
                pending.remove(i)
            elif not _pid(i):
                say(f'{i["name"]}: exited during start; see {inst_dir(i) / "server.log"}')
                pending.remove(i)
                return False
        time.sleep(1)
    for i in pending:
        say(f'{i["name"]}: not healthy after {int(timeout)} s; see {inst_dir(i) / "server.log"}')
    return not pending


def stop(selected: list[dict]) -> int:
    for i in selected:
        pid = _pid(i)
        if not pid:
            say(f'{i["name"]}: not running')
            pid_file(i).unlink(missing_ok=True)
            continue
        try:
            os.killpg(pid, signal.SIGTERM)        # the server and what it started (the stdio MCP server)
        except OSError:
            os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if not _pid(i):
                break
            time.sleep(0.5)
        if _pid(i):
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        pid_file(i).unlink(missing_ok=True)
        say(f'{i["name"]}: stopped (pid {pid})')
    return 0


def kill(selected: list[dict]) -> int:
    """A crash: SIGKILL, so the instance cannot say goodbye (the others find out by gossip)."""
    for i in selected:
        pid = _pid(i)
        if not pid:
            say(f'{i["name"]}: not running')
            continue
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            os.kill(pid, signal.SIGKILL)
        pid_file(i).unlink(missing_ok=True)
        say(f'{i["name"]}: killed (pid {pid}); `start {i["name"]}` brings it back')
    return 0


def status(selected: list[dict]) -> int:
    say('')
    for i in selected:
        pid = _pid(i)
        u = url(i)
        state = 'healthy' if pid and _healthy(i) else ('starting' if pid else 'stopped')
        line = f'{i["name"]:<12} {u:<24} {state:<9} pid {pid or "-"}'
        if state == 'healthy':
            try:
                st = _get(f'{u}/api/sajhanet/status', TEST_ADMIN_KEY)
                for n in st.get('nets') or []:
                    seen = ', '.join(f'{m.get("name")} {m.get("state")}' for m in n.get('members') or [])
                    state_word = '' if n.get('joined') else ' (not joined)'
                    line += f'  {n.get("net")}{state_word}: {seen or "no one else"}'
            except urllib.error.HTTPError:
                line += '  (net members: shown with the test admin key on; see SAJHA Net > Instances)'
            except Exception as e:
                line += f'  (net status: {e.__class__.__name__})'
        say(line)
    say('')
    say(f'Sign in at any URL as {TEST_ADMIN_USER} / {TEST_ADMIN_PASSWORD} (while the test admin key is on) '
        f'or admin / admin123.')
    say(f'API key on all three: {TEST_ADMIN_KEY}   (header X-API-Key; the test admin key)')
    say(f'LLM: Ollama at {OLLAMA}: {CHAT_MODEL} (default), {FAST_MODEL} (fast), {EMBED_MODEL} (embedding)')
    say(f'Files: {RUN}')
    return 0


def reset(selected: list[dict]) -> int:
    stop(selected)
    for i in selected:
        shutil.rmtree(inst_dir(i), ignore_errors=True)
        say(f'{i["name"]}: deleted {inst_dir(i)}')
    if RUN.exists() and not any(RUN.iterdir()):
        RUN.rmdir()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='SAJHA local test lab: three instances in one SAJHA Net')
    ap.add_argument('command', choices=['start', 'stop', 'status', 'kill', 'reset'])
    ap.add_argument('instances', nargs='*', help='instance names (default: all three)')
    a = ap.parse_args(argv)
    names = {i['name'] for i in INSTANCES}
    bad = [n for n in a.instances if n not in names]
    if bad:
        ap.error(f'unknown instance {", ".join(bad)}; the lab has {", ".join(sorted(names))}')
    selected = [i for i in INSTANCES if not a.instances or i['name'] in a.instances]
    try:
        import yaml  # noqa: F401
    except ImportError:
        say('PyYAML is missing: run this script with the Python you run SAJHA with (pip install -r requirements.txt)')
        return 1
    RUN.mkdir(parents=True, exist_ok=True)
    return {'start': start, 'stop': stop, 'status': status, 'kill': kill, 'reset': reset}[a.command](selected)


if __name__ == '__main__':
    sys.exit(main())
