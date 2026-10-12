# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""tools/bench/bench_federation.py picks free ports: an upstream port another process held passed for the
upstream (the check only asked whether something listened there), and scenario ports were never checked."""

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def benches():
    sys.path.insert(0, str(ROOT / 'tools' / 'bench'))
    try:
        import bench
        import bench_federation
        yield bench, bench_federation
    finally:
        sys.path.remove(str(ROOT / 'tools' / 'bench'))


def test_a_busy_port_is_skipped_and_never_taken_for_the_upstream(benches, tmp_path):
    bench, fed = benches
    with socket.socket() as held:
        held.bind(('127.0.0.1', 0))
        held.listen(1)
        busy = held.getsockname()[1]
        got = bench.free_port(busy)
        assert got != busy and bench.port_free(got)
        assert bench.free_port(got, avoid=(got,)) != got
        with pytest.raises(RuntimeError, match='in use'):
            fed.start_upstream(busy, tmp_path / 'upstream.log')
