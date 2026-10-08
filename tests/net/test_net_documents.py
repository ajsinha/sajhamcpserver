# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA Net's per-net list documents (``first_use.json``, ``runtime_seeds.json``, ``pins.json``) are
read-modify-written under a lock and written atomically (a temporary file renamed over the old one), so
concurrent first contacts never lose a remembered key or leave a file two writes mixed ("Extra data").
"""

import json
import threading

from sajha.core.state.memory import MemoryStateStore
from sajha.core.storage import LocalStorageBackend
from sajha.net.integration import SajhaNetService
from sajha.net.integration.config import Shared


def test_concurrent_first_use_writes_lose_nothing_and_stay_parseable(tmp_path):
    docs = LocalStorageBackend(str(tmp_path))
    svc = SajhaNetService(Shared(enabled=True, data_dir='sajhanet'), [], {}, store=MemoryStateStore(),
                          documents=docs)
    names = [f'peer-{i}' for i in range(40)]
    barrier = threading.Barrier(len(names))

    def remember(name):
        barrier.wait()
        svc._update_list_doc('lab-net', 'first_use',
                             lambda items: items + [{'instance': name, 'thumbprint': 'tp-' + name * 20}])
    threads = [threading.Thread(target=remember, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    path = tmp_path / 'sajhanet' / 'lab-net' / 'first_use.json'
    doc = json.loads(path.read_text())                  # one document, not two writes mixed
    assert sorted(x['instance'] for x in doc['items']) == sorted(names)
    assert set(svc.first_use_keys('lab-net')) == set(names)
    assert [p.name for p in path.parent.iterdir()] == ['first_use.json']     # no temporary file left


def test_local_backend_atomic_json_write_replaces_whole(tmp_path):
    docs = LocalStorageBackend(str(tmp_path))
    docs.write_json_atomic('d/x.json', {'items': ['a' * 1000]})
    docs.write_json_atomic('d/x.json', {'items': []})          # shorter than the old one: nothing left over
    assert docs.read_json('d/x.json') == {'items': []}
    assert [p.name for p in (tmp_path / 'd').iterdir()] == ['x.json']
