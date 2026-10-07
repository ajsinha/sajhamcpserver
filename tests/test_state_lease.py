"""
The renewing state-store lease (sajha/core/state/base.py lease_*, sajha/core/state/lease.py)
against every backend available here: memory, fakeredis (when installed), a real Redis at
SAJHA_TEST_REDIS_URL (skipped when none answers) and the database (SQLite).

Design: docs/architecture/Scaling and State.md (Leases).
"""

import tempfile
import threading
import time

import pytest

from tests.test_state_store import BACKENDS, _make


@pytest.fixture(params=BACKENDS)
def store(request):
    with tempfile.TemporaryDirectory() as tmp:
        s = _make(request.param, tmp)
        yield s
        try:
            s.delete_prefix("")
        finally:
            s.close()


def test_claim_is_exclusive_and_reentrant(store):
    assert store.lease_claim("lease:a", "w1", ttl=5) is True
    assert store.lease_holder("lease:a") == "w1"
    assert store.lease_claim("lease:a", "w2", ttl=5) is False
    assert store.lease_claim("lease:a", "w1", ttl=5) is True        # the holder renews
    assert store.lease_holder("lease:a") == "w1"


def test_renew_only_by_holder_and_extends(store):
    assert store.lease_claim("lease:b", "w1", ttl=1.0)
    assert store.lease_renew("lease:b", "w2", 5) is False
    time.sleep(0.6)
    assert store.lease_renew("lease:b", "w1", 1.0) is True           # pushed past the first expiry
    time.sleep(0.6)
    assert store.lease_holder("lease:b") == "w1"
    assert store.lease_renew("lease:b", "w1") is True                 # default: the lease's own ttl
    v = store.get("lease:b")
    assert v["holder"] == "w1" and v["ttl"] == 1.0 and v["renewed"] >= v["claimed"]


def test_expired_lease_cannot_be_renewed_and_can_be_claimed(store):
    assert store.lease_claim("lease:c", "w1", ttl=0.3)
    time.sleep(0.5)
    assert store.lease_holder("lease:c") is None
    assert store.lease_renew("lease:c", "w1", 1) is False
    assert store.lease_claim("lease:c", "w2", ttl=5) is True
    assert store.lease_renew("lease:c", "w1", 1) is False


def test_release_only_by_holder(store):
    assert store.lease_claim("lease:d", "w1", ttl=5)
    assert store.lease_release("lease:d", "w2") is False
    assert store.lease_holder("lease:d") == "w1"
    assert store.lease_release("lease:d", "w1") is True
    assert store.lease_holder("lease:d") is None
    assert store.lease_release("lease:d", "w1") is False
    assert store.lease_claim("lease:d", "w2", ttl=5) is True


def test_one_slot_claims_still_work_and_report_their_holder(store):
    # workflow cron and quality probes: add(worker id, ttl), never renewed
    assert store.add("wf:cron:x:t:2026", "worker-1", ttl=5) is True
    assert store.add("wf:cron:x:t:2026", "worker-2", ttl=5) is False
    assert store.lease_holder("wf:cron:x:t:2026") == "worker-1"
    assert store.lease_renew("wf:cron:x:t:2026", "worker-1", 5) is False   # not a lease: nothing to renew


def test_concurrent_claims_have_one_winner(store):
    wins = []
    barrier = threading.Barrier(6)

    def go(i):
        barrier.wait()
        if store.lease_claim("lease:race", f"w{i}", ttl=5):
            wins.append(i)
    threads = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1 and store.lease_holder("lease:race") == f"w{wins[0]}"


def test_lease_keeper_renews_releases_and_reports_loss(store):
    from sajha.core.state.lease import Lease, LeaseUnavailable
    lost = []
    a = Lease("lease:k", ttl=0.6, holder="A", store=store, renew_every=0.1, on_lost=lost.append)
    assert a.try_acquire() and a.held
    time.sleep(1.0)                                     # beyond the TTL: kept alive by renewal
    assert store.lease_holder("lease:k") == "A"
    b = Lease("lease:k", ttl=0.6, holder="B", store=store)
    assert b.try_acquire() is False
    with pytest.raises(LeaseUnavailable):
        with b:
            pass
    # someone forcibly takes it (an operator, or the lease expired during a pause)
    store.set("lease:k", {"holder": "C", "claimed": 0, "renewed": 0, "ttl": 5}, ttl=5)
    deadline = time.time() + 2
    while a.held and time.time() < deadline:
        time.sleep(0.05)
    assert a.held is False and lost == [a]
    assert a.release() is False                         # not ours any more; C's lease untouched
    assert store.lease_holder("lease:k") == "C"
    store.delete("lease:k")
    with Lease("lease:k", ttl=5, holder="B", store=store) as held:
        assert held.held and store.lease_holder("lease:k") == "B"
    assert store.lease_holder("lease:k") is None
