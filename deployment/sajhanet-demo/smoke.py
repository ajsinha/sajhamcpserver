#!/usr/bin/env python3
"""
Smoke test of the three-instance SAJHA Net demo (deployment/sajhanet-demo/docker-compose.yml).

Initialises the CA on risk-eu, enrolls cust-na and treasury-na with enrollment tokens (they join
through risk-eu, their seed), waits until every instance sees the other two alive and risk-eu has
imported cust-na's tools, then calls one of cust-na's tools on risk-eu by its qualified name.
Idempotent: a second run skips what is done. Exit status 0 when everything passed.

    python3 deployment/sajhanet-demo/smoke.py [--key sja_test_admin_dev_key_0001] [--timeout 120]

It signs in with the test admin key of config/apikeys.json.example (a lab only).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

NET = 'demo-net'
INSTANCES = {'risk-eu': 'http://127.0.0.1:3201', 'cust-na': 'http://127.0.0.1:3202',
             'treasury-na': 'http://127.0.0.1:3203'}
INSIDE = {name: f'http://sajha-{name}:3002' for name in INSTANCES}     # the URLs the containers use
TOOL = 'calc_percentage_change'


def call(base, method, path, key, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={'X-API-Key': key, 'Content-Type': 'application/json',
                                          'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except ValueError:
            return e.code, {}


def wait_for(what, fn, timeout):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = fn()
            if last:
                return last
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            last = e
        time.sleep(2)
    raise SystemExit(f'FAIL: {what} (last: {last})')


def net_status(base, key):
    s, st = call(base, 'GET', '/api/sajhanet/status', key)
    if s != 200:
        return None
    return next((n for n in st.get('nets') or [] if n['net'] == NET), None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--key', default='sja_test_admin_dev_key_0001')
    ap.add_argument('--timeout', type=float, default=120)
    a = ap.parse_args()
    k = a.key

    for name, base in INSTANCES.items():
        wait_for(f'{name} answers /health', lambda b=base: urllib.request.urlopen(b + '/health', timeout=5).status == 200,
                 a.timeout)
    print('ok   the three instances are up')

    ca = INSTANCES['risk-eu']
    st = net_status(ca, k)
    if st is None:
        raise SystemExit('FAIL: risk-eu does not show demo-net (is the test admin key accepted?)')
    if not (st.get('ca') or {}).get('initialised'):
        s, r = call(ca, 'POST', f'/api/sajhanet/nets/{NET}/ca/init', k, {})
        if s != 200:
            raise SystemExit(f'FAIL: CA init on risk-eu: {s} {r}')
        print('ok   CA of demo-net initialised on risk-eu')
    for name in ('cust-na', 'treasury-na'):
        base = INSTANCES[name]
        st = net_status(base, k)
        if st and st.get('certificate'):
            continue
        s, tok = call(ca, 'POST', f'/api/sajhanet/nets/{NET}/ca/tokens', k, {'instance': name})
        if s != 200:
            raise SystemExit(f'FAIL: enrollment token for {name}: {s} {tok}')
        s, r = call(base, 'POST', f'/api/sajhanet/nets/{NET}/enroll', k,
                    {'ca_url': INSIDE['risk-eu'], 'token': tok['token']}, timeout=60)
        if s != 200:
            raise SystemExit(f'FAIL: enrollment of {name}: {s} {r}')
        print(f'ok   {name} enrolled (certificate {r["certificate"].get("serial")})')

    def all_alive():
        for name, base in INSTANCES.items():
            st = net_status(base, k)
            if not st or not st.get('joined'):
                return False
            seen = {m['name']: m['state'] for m in st.get('members') or []}
            if any(seen.get(o) != 'alive' for o in INSTANCES if o != name):
                return False
        return True
    wait_for('every instance sees the other two alive', all_alive, a.timeout)
    print('ok   the three see each other alive')

    qn = f'{NET}__cust-na__{TOOL}'

    def imported():
        s, t = call(ca, 'GET', f'/api/sajhanet/tools?net={NET}', k)
        return s == 200 and any(r['qualified_name'] == qn and r['state'] == 'active' for r in t.get('rows') or [])
    wait_for(f'risk-eu imports {qn}', imported, a.timeout)
    print(f'ok   risk-eu lists {qn}')

    def remote_call():                       # the proxy reaches every worker's registry within a gossip round
        s, r = call(ca, 'POST', '/api/tools/execute', k, {'tool': qn, 'arguments': {'old_value': 100, 'new_value': 125}},
                    timeout=60)
        return None if s == 404 else (s, r)
    s, r = wait_for(f'{qn} is callable on risk-eu', remote_call, a.timeout)
    text = json.dumps(r)
    if s != 200 or not r.get('success') or '25' not in text:
        raise SystemExit(f'FAIL: remote call of {qn}: {s} {text[:600]}')
    print(f'ok   a remote call of {qn} on risk-eu ran on cust-na')

    s, v = call(ca, 'GET', '/api/sajhanet/instances', k)
    names = sorted(i['name'] for n in v.get('nets') or [] for i in n['instances'])
    if names != sorted(INSTANCES):
        raise SystemExit(f'FAIL: the Instances view on risk-eu lists {names}')
    print('ok   the Instances page on risk-eu lists all three')
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
