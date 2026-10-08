# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""LLM-tool resource safety (sajha/ai/llm_tools/runtime.py; docs/architecture/LLM Tools.md §10.3–10.4): the
memory guard's states with a simulated resident memory and cgroup-style limits, admission (concurrency,
bounded queue, busy), the working-set budget and spill to the per-run spool, the spool caps and janitor,
the caches shed under pressure, System Notices, and a soak test that drives the process to its soft and
hard limits under concurrent calls without a crash."""

import json
import os
import threading
import time

import pytest

from sajha.ai.intelligence import IntelligenceService
from sajha.ai.llm import RequestContext
from sajha.ai.llm.settings import AskSettings
from sajha.ai.llm_tools import LLMTool, LLMToolSettings, set_settings
from sajha.ai.llm_tools.config import GuardSettings, RuntimeSettings, SpoolSettings, WorkingSetSettings
from sajha.ai.llm_tools.runtime import (Busy, MemoryGuard, Run, Runtime, get_runtime, observe_result, set_runtime,
                                        CURRENT)
from tests.ai.conftest import FakeTool, ToolBox, make_gateway

MB = 1 << 20
ADMIN = RequestContext(user_id="", roles=["admin"], is_admin=True)


class Rss:
    """A simulated resident-memory reading."""

    def __init__(self, mb=100):
        self.mb = mb

    def __call__(self):
        return int(self.mb * MB)


@pytest.fixture(autouse=True)
def notices():
    from sajha import notices as N
    from sajha.core.state.memory import MemoryStateStore
    svc = N.NoticeService(MemoryStateStore("llmt:"), forward=[])
    N.set_service(svc)
    yield svc
    N.set_service(None)


def install(tmp_path, rss, **kw):
    s = LLMToolSettings(spool=SpoolSettings(dir=str(tmp_path / "spool"), **kw.pop("spool", {})),
                        guard=GuardSettings(interval_s=0.05, **kw.pop("guard", {})),
                        runtime=RuntimeSettings(**kw.pop("runtime", {})),
                        working_set=WorkingSetSettings(**kw.pop("working_set", {})))
    set_settings(s)
    rt = Runtime(s, MemoryGuard(rss_reader=rss, limit_reader=lambda: 1000 * MB))
    set_runtime(rt)
    return rt


@pytest.fixture(autouse=True)
def cleanup():
    yield
    set_runtime(None)
    set_settings(None)


def test_the_guard_moves_through_its_states_and_raises_notices(tmp_path, notices):
    rss = Rss(100)
    rt = install(tmp_path, rss)                       # limit 1000 MB: soft 700, hard 850
    assert rt.guard.thresholds() == (700 * MB, 850 * MB)
    assert rt.guard.sample() == "ok"
    rss.mb = 720
    assert rt.guard.sample() == "soft"
    assert notices.get("llm_tools.memory")["severity"] == "warning"
    rss.mb = 900
    assert rt.guard.sample() == "hard"
    assert notices.get("llm_tools.memory")["severity"] == "error"
    rss.mb = 100
    assert rt.guard.sample() == "ok"
    assert notices.get("llm_tools.memory")["state"] == "cleared"
    from sajha.observability import metrics as M
    assert M.LLM_TOOL_GUARD.samples()[0][2] == 0


def test_absolute_limits_and_the_real_readers():
    g = MemoryGuard(cfg=GuardSettings(soft_mb=10, hard_mb=20), rss_reader=lambda: 15 * MB)
    assert g.thresholds() == (10 * MB, 20 * MB) and g.sample() == "soft"
    from sajha.ai.llm_tools.runtime import read_limit_bytes, read_rss_bytes
    assert read_rss_bytes() > 0 and read_limit_bytes() > 0


def test_admission_queues_then_refuses(tmp_path, notices):
    rt = install(tmp_path, Rss(), runtime={"max_concurrent_runs": 1, "max_queued": 1, "queue_timeout_s": 0.2})
    rt.admission.acquire()
    errors = []

    def second():
        try:
            rt.admission.acquire()
            rt.admission.release()
        except Busy as e:
            errors.append(e.reason)
    th = threading.Thread(target=second)
    th.start()
    time.sleep(0.05)
    with pytest.raises(Busy) as e:                    # one running, one waiting: the queue is full
        rt.admission.acquire()
    assert e.value.reason == "queue_full" and e.value.stopped_by == "busy"
    th.join()
    assert errors == ["queue_timeout"]
    rt.admission.release()
    assert notices.get("llm_tools.busy") is not None


def test_hard_pressure_refuses_new_runs(tmp_path):
    rss = Rss(900)
    rt = install(tmp_path, rss)
    with pytest.raises(Busy) as e:
        rt.begin("t", "complete", 10, 1.0)
    assert e.value.reason == "memory"
    rss.mb = 100
    rt.guard.sample()
    run = rt.begin("t", "complete", 10, 1.0)
    rt.end(run)


def test_working_set_spills_to_the_spool_and_reads_back(tmp_path):
    rt = install(tmp_path, Rss(), working_set={"spill_threshold_kb": 1, "working_set_max_kb": 4})
    run = rt.begin("t", "answer", 10, 1.0)
    token = CURRENT.set(run)
    try:
        small = observe_result("calc", "c1", {"v": 1})
        assert small == {"v": 1} and run.spilled == 0
        big = {"rows": ["x" * 100] * 50}                 # ~5 KB: spilled at once, a preview kept
        kept = observe_result("data", "c2", big)
        assert isinstance(kept, str) and run.spilled == 1
        folder = tmp_path / "spool" / run.id
        assert folder.is_dir() and len(list(folder.iterdir())) == 1
        assert run.full("data-c2") == big
        for i in range(6):                               # the total passes 4 KB: the oldest spill next
            observe_result("calc", f"m{i}", {"pad": "y" * 900})
        assert run.bytes <= 4 * 1024 and run.spilled >= 3
    finally:
        CURRENT.reset(token)
        rt.end(run)
    assert not (tmp_path / "spool" / run.id).exists()     # the run's folder goes when the run ends
    assert rt.spool.bytes_in_use == 0


def test_a_full_spool_truncates_and_raises_a_notice(tmp_path, notices):
    rt = install(tmp_path, Rss(), spool={"per_run_mb": 0.001}, working_set={"spill_threshold_kb": 1})
    run = rt.begin("t", "answer", 10, 1.0)
    token = CURRENT.set(run)
    try:
        observe_result("data", "c1", "z" * 5000)
        assert run.items[0].ref.truncated
        assert notices.get("llm_tools.spool_full")["state"] == "active"
    finally:
        CURRENT.reset(token)
        rt.end(run)


def test_the_janitor_removes_orphaned_run_folders(tmp_path):
    rt = install(tmp_path, Rss(), spool={"orphan_minutes": 1})
    old = tmp_path / "spool" / "crashed"
    old.mkdir(parents=True)
    (old / "x.json").write_text("{}")
    past = time.time() - 3600
    os.utime(old, (past, past))
    live = tmp_path / "spool" / "live"
    live.mkdir()
    os.utime(live, (past, past))
    assert rt.spool.sweep_orphans(active={"live"}) == 1
    assert not old.exists() and live.exists()


def test_soft_pressure_sheds_the_caches_and_spills(tmp_path):
    rss = Rss(100)
    rt = install(tmp_path, rss, working_set={"spill_threshold_kb": 64})
    rt.results.put("k", {"text": "cached"})
    rt.hot.enabled = True
    rt.hot.put("c|u|row|t", {"id": "c"})
    assert rt.results.get("k") and rt.hot.get("c|u|row|t")
    run = rt.begin("t", "answer", 10, 1.0)
    token = CURRENT.set(run)
    try:
        observe_result("calc", "c1", {"v": 1})
        rss.mb = 720
        rt.guard.sample()
        assert rt.results.get("k") is None and rt.hot.get("c|u|row|t") is None
        assert run.spilled == 1                              # every spillable item went to the spool
        rt.results.put("k2", {"x": 1})                       # nothing is cached under pressure
        assert rt.results.get("k2") is None
    finally:
        CURRENT.reset(token)
        rt.end(run)


def test_hard_pressure_ends_a_running_answer_at_its_next_step(tmp_path):
    rss = Rss(100)
    install(tmp_path, rss)
    box = ToolBox(with_calc=False)

    def squeeze(args):
        rss.mb = 900                         # the process crosses the hard limit while the tool runs
        get_runtime().guard.sample()
        return {"value": 1}
    box.add(FakeTool("calc_squeeze", "Squeeze calculation of a value", output=squeeze))
    gw = make_gateway({"aliases": {a: ["mock/mock-scripted"] for a in ("default", "reasoning")},
                       "cache": {"enabled": False}})
    gw.providers["mock"].set_script([{"tool_calls": [{"name": "calc_squeeze", "arguments": {}}]}], loop=True)
    svc = IntelligenceService(gw, box, settings=AskSettings(synthesize=False), audit=lambda e: None)
    t = LLMTool({"name": "pressure_tool", "description": "x", "implementation": "sajha.ai.llm_tools.LLMTool",
                 "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}},
                 "outputSchema": {"type": "object", "properties": {"answer": {"type": "string"}}},
                 "llm": {"mode": "answer", "tools": {"allow": ["calc_*"]}}})
    t.registry, t.service, t.gateway = box, svc, gw
    info = t.run({"question": "squeeze"}, ctx=ADMIN, audit=False)
    assert info.stopped_by == "memory_pressure" and info.result.is_error
    assert len(info.steps) == 1                               # ended at the next step, not mid-step
    assert get_runtime().admission.running == 0


def test_soak_through_soft_and_hard_limits_without_a_crash(tmp_path, notices):
    """Many concurrent calls while resident memory climbs through soft and hard and falls back:
    every call ends with a result (answer, busy or memory_pressure), nothing raises, no slot leaks."""
    rss = Rss(100)
    rt = install(tmp_path, rss, runtime={"max_concurrent_runs": 4, "max_queued": 8, "queue_timeout_s": 0.5},
                 working_set={"spill_threshold_kb": 1})
    gw = make_gateway({"aliases": {a: ["mock/mock-scripted"] for a in ("default", "fast")},
                       "cache": {"enabled": False}})
    gw.providers["mock"].set_script([{"sleep_ms": 5, "text": "ok " * 200}], loop=True)
    box = ToolBox(with_calc=False)
    t = LLMTool({"name": "soak_tool", "description": "x", "implementation": "sajha.ai.llm_tools.LLMTool",
                 "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
                 "outputSchema": {"type": "object", "properties": {"text": {"type": "string"},
                                                                   "stopped_by": {"type": "string"}}},
                 "llm": {"mode": "complete", "template": "Echo {{input.text}}"}})
    t.registry, t.gateway = box, gw
    t.service = IntelligenceService(gw, box, settings=AskSettings(), audit=lambda e: None)
    outcomes, crashes = [], []
    lock = threading.Lock()

    def worker(n):
        for i in range(15):
            try:
                info = t.run({"text": f"{n}-{i} " + "p" * 3000}, ctx=ADMIN, audit=False)
                with lock:
                    outcomes.append(info.stopped_by)
            except Exception as e:                       # a crash is a failure of the guard
                with lock:
                    crashes.append(repr(e))

    def pressure():
        for mb in (300, 720, 760, 900, 950, 880, 720, 300, 100):
            rss.mb = mb
            rt.guard.sample()
            time.sleep(0.04)
    threads = [threading.Thread(target=worker, args=(n,)) for n in range(10)] + [threading.Thread(target=pressure)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=60)
    assert not crashes, crashes[:3]
    assert set(outcomes) <= {"answer", "busy", "memory_pressure"}
    assert "answer" in outcomes and "busy" in outcomes
    assert rt.admission.running == 0 and rt.admission.queued == 0
    assert rt.guard.state == "ok" and rt.spool.bytes_in_use == 0
    assert not any((tmp_path / "spool").iterdir()) if (tmp_path / "spool").exists() else True
