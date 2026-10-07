"""
Every number the deck shows, derived when the deck is built.

CLAUDE.md's first documentation rule is "derive, never restate": a number written into
a slide is a promise to update it forever. So the deck writes none. This module reads
each figure from the code, the configuration, the CI workflow or the compliance report
that owns it, and runs the worked examples (an Ask SAJHA question on the offline mock
model, a policy decision, a tampered audit chain, a composite's confidence) against the
code as it stands. Each slide's notes name the source of what it shows.

Nothing here writes to the repository: the worked examples use the shipped tool configs
and policies read-only, a temporary SQLite file for the audit chain, and no SAJHA
database. If a source moves or changes shape, the build fails here rather than printing
a stale number.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import functools
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(1, str(ROOT))

COMPLIANCE_2026 = ROOT / "docs" / "protocol" / "MCP 2026-07-28 Compliance.md"
COMPLIANCE_2025 = ROOT / "docs" / "protocol" / "MCP 2025-11-25 Compliance.md"
SECURITY_MODEL = ROOT / "docs" / "security" / "Security Model.md"
WORKFLOW = ROOT / ".github" / "workflows" / "mcp-conformance.yml"

ASK_QUESTION = "What is the percentage change from 80 to 100?"


class SourceChanged(Exception):
    """A source no longer has the shape the deck reads; fix the reader, not the slide."""


def _need(cond: Any, what: str) -> None:
    if not cond:
        raise SourceChanged(what)


# ── version, catalog, protocol ──────────────────────────────────────────


def version() -> str:
    import yaml

    with open(ROOT / "config" / "application.yml", encoding="utf-8") as f:
        return str(yaml.safe_load(f)["app"]["version"])


@functools.lru_cache(maxsize=1)
def registry() -> Any:
    """The tools registry, loaded from config/tools exactly as the server loads it."""
    from sajha.tools.tools_registry import ToolsRegistry

    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        reg = ToolsRegistry(str(ROOT / "config" / "tools"))
    finally:
        os.chdir(cwd)
    reg.stop_monitoring()
    return reg


def catalog() -> dict[str, Any]:
    from sajha.web.help_catalog import live_tool_groups

    live = live_tool_groups(registry(), with_names=True)
    _need(live["total_tools"] > 0, "the tools registry loaded no tools")
    return {
        "tools": live["total_tools"],
        "groups": live["total_groups"],
        "top": [(g["name"], g["tool_count"], g["tools"][0]) for g in live["groups"]],
        "errors": len(registry().tool_errors),
    }


def eras() -> dict[str, list[str]]:
    from sajha.core.mcp_modern import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS

    return {"modern": list(MODERN_PROTOCOL_VERSIONS), "handshake": list(HANDSHAKE_PROTOCOL_VERSIONS)}


def ci() -> dict[str, Any]:
    """The conformance matrix the CI workflow runs, and the branches it runs on."""
    import yaml

    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = doc.get("on", doc.get(True))  # YAML 1.1 reads a bare `on:` as True
    job = doc["jobs"]["conformance"]
    matrix = [(str(m["spec"]), m["suite"].split("@")[-1]) for m in job["strategy"]["matrix"]["include"]]
    _need(matrix, "the conformance workflow has no matrix")
    return {"matrix": matrix, "branches": list(on["push"]["branches"])}


def conformance() -> dict[str, Any]:
    """The recorded results: the table in section 5 of the 2026-07-28 compliance report,
    and the result line of the 2025-11-25 report."""
    text = COMPLIANCE_2026.read_text(encoding="utf-8")
    rows = []
    for m in re.finditer(
        r"^\|\s*(.+?)\s*\|\s*(\d+)/(\d+)\s*\|\s*\*\*(\d+) passed, (\d+) failed\*\*", text, re.M
    ):
        label = re.sub(r"`", "", m.group(1))
        rows.append(
            {
                "suite": label,
                "scenarios": f"{m.group(2)}/{m.group(3)}",
                "passed": int(m.group(4)),
                "failed": int(m.group(5)),
            }
        )
    _need(len(rows) >= 3, f"no conformance table in {COMPLIANCE_2026.name}")
    legacy = re.search(
        r"(\d+)/(\d+) scenarios pass, with (\d+) checks passed and (\d+) failed",
        COMPLIANCE_2025.read_text(encoding="utf-8"),
    )
    _need(legacy, f"no result line in {COMPLIANCE_2025.name}")
    return {
        "rows": rows,
        "passed": sum(r["passed"] for r in rows),
        "failed": sum(r["failed"] for r in rows),
        "legacy": {"scenarios": f"{legacy.group(1)}/{legacy.group(2)}", "passed": int(legacy.group(3))},
    }


def tests() -> int:
    """How many tests the suite has, by collecting it (nothing runs)."""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:randomly", "tests", "clientsdk/tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    ).stdout
    m = re.search(r"(\d+) tests? collected", out)
    _need(m, "pytest collected no tests:\n" + out[-800:])
    return int(m.group(1))


# ── governance ──────────────────────────────────────────────────────────


def security_fixes() -> list[str]:
    """The rows of 'Fixes since ...' in the Security Model: one issue each."""
    text = SECURITY_MODEL.read_text(encoding="utf-8")
    m = re.search(r"^## \d+\. Fixes since[^\n]*\n(.*?)^## ", text, re.M | re.S)
    _need(m, "no 'Fixes since' section in the Security Model")
    rows = [ln for ln in m.group(1).splitlines() if ln.startswith("| ") and not ln.startswith("| Issue")]
    issues = [r.split("|")[1].strip() for r in rows]
    _need(len(issues) >= 5, "the Security Model's fixes table is empty")
    return issues


def limitations() -> list[str]:
    """The bold heads of the Security Model's 'Known limitations'."""
    text = SECURITY_MODEL.read_text(encoding="utf-8")
    m = re.search(r"^## \d+\. Known limitations\n(.*?)(?:^## |\Z)", text, re.M | re.S)
    _need(m, "no 'Known limitations' section in the Security Model")
    out = []
    for head, rest in re.findall(r"^- \*\*(.+?)\*\*(.*)$", m.group(1), re.M):
        text = head if head.rstrip().endswith(".") else (head + rest).split(". ")[0]
        text = text.split(" (")[0].split("; ")[0]
        out.append(re.sub(r"[`*]", "", text).strip().rstrip("."))
    return out


def policy_example() -> list[dict[str, Any]]:
    """The shipped example-guardrails policy, evaluated (not enforced) on three calls."""
    from sajha.observability.caller import Caller
    from sajha.policy.engine import Call, PolicyEngine
    from sajha.policy.loader import PolicySet, load_dir

    pols = load_dir(str(ROOT / "config" / "policies"))
    ps = PolicySet()
    ps.set_policies(pols)
    eng = PolicyEngine(ps)
    alice = Caller("alice", "", ("user",), "session")
    anon = Caller()
    calls = [
        ("duckdb_sql", {"sql": "SELECT region, SUM(amount) FROM orders GROUP BY region"}, alice, {}),
        ("duckdb_sql", {"sql": "SELECT 1; DROP TABLE orders"}, alice, {}),
        ("github_create_issue", {"repo": "acme/app", "title": "x"}, anon, {"destructiveHint": True}),
        ("github_create_issue", {"repo": "acme/app", "title": "x"}, alice, {"destructiveHint": True}),
    ]
    out = []
    for tool, args, who, ann in calls:
        d = eng.evaluate(Call(tool=tool, arguments=args, caller=who, annotations=ann), include_disabled=True)
        out.append(
            {
                "tool": tool,
                "args": args,
                "caller": who.user_id,
                "effect": d.effect,
                "rule": d.rule.split(":")[-1] if d.rule else "",
                "reason": d.reason,
                "obligations": [k for k in ("redact", "screen") if getattr(d, k)]
                + (["rate limit"] if any(t == "rate" for _r, _l, t in d.limits) else []),
            }
        )
    _need(out[1]["effect"] == "deny" and out[2]["effect"] == "deny", "the example guardrails no longer deny")
    return out


def audit_example() -> dict[str, Any]:
    """Write a short signed chain, verify it, change one stored outcome, verify again."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from sqlalchemy import create_engine, text

    from sajha.audit.chain import ChainWriter, Signer
    from sajha.audit.verify import verify

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    signer = Signer(pem, "deck")
    with tempfile.TemporaryDirectory() as tmp:
        eng = create_engine(f"sqlite:///{tmp}/audit.db")
        w = ChainWriter(engine=eng, chain_id="deck", anchor_every=5, anchor_interval=0, signer=signer, store=True)
        for i in range(12):
            denied = i == 7
            w.append(
                "policy.deny" if denied else "tool.call",
                actor={"user": "alice", "roles": ["user"]},
                resource={"type": "tool", "id": "duckdb_sql"},
                outcome="deny" if denied else "ok",
                details={"i": i},
            )
        w.close()
        keys = {signer.kid: signer.public_key()}
        before = verify(eng, keys=keys)
        with eng.begin() as conn:
            seq = conn.execute(text("SELECT seq FROM audit_chain WHERE outcome='deny'")).scalar()
            conn.execute(text("UPDATE audit_chain SET outcome='ok' WHERE seq=:s"), {"s": seq})
        after = verify(eng, keys=keys)
        eng.dispose()
    c0, c1 = before["chains"][0], after["chains"][0]
    _need(before["ok"] and not after["ok"], "the audit verifier did not catch the edit")
    return {
        "records": c0["records"],
        "anchors": c0["anchors"],
        "ok_before": before["ok"],
        "ok_after": after["ok"],
        "seq": seq,
        "problems": c1["problems"],
    }


def siem() -> dict[str, list[str]]:
    from sajha.audit import formats, sinks

    return {"types": list(sinks.TYPES), "flavors": list(sinks.FLAVORS), "formats": list(formats.FORMATS)}


def sandbox_backends() -> list[str]:
    from sajha.sandbox.backends import BACKENDS

    return list(BACKENDS)


def account_templates() -> list[str]:
    from sajha.accounts.providers import TEMPLATES

    return list(TEMPLATES)


# ── tools, composition, intelligence ───────────────────────────────────


def connector_kinds() -> dict[str, list[str]]:
    from sajha.connectors.model import KINDS, PER_USER_KINDS

    return {
        "per_user": list(PER_USER_KINDS),
        "sql": [k for k, f in KINDS.items() if f == "sql"],
        "search": [k for k, f in KINDS.items() if f == "search"],
    }


def studio_creators() -> list[str]:
    names = sorted(p.stem.replace("_tool_generator", "") for p in (ROOT / "sajha" / "studio").glob("*_tool_generator.py"))
    _need(names, "no Studio generators found")
    return names


def workflow_model() -> dict[str, list[str]]:
    from sajha.workflows import model

    return {"steps": list(model.STEP_KINDS), "triggers": [t for t in model.TRIGGER_TYPES if t != "manual"]}


def composition_example() -> dict[str, Any]:
    """Confidence through a three-step composite: the EntropyGuard, as composites use it."""
    from sajha.core.composition import EntropyGuard, get_tool_confidence

    steps = ["fred_series_observations", "fmp_company_profile", "calc_percentage_change"]
    g = EntropyGuard()
    rows = []
    for s in steps:
        c = get_tool_confidence(s)
        g.record_step(s, confidence=c)
        rows.append((s, c, g.cumulative_confidence, g.cumulative_entropy))
    return {"rows": rows, "max_bits": g.max_entropy_bits}


def providers() -> list[str]:
    from sajha.ai.llm import registry as r

    r.ensure_builtins()
    names = sorted(r.registered_providers())
    _need("mock" in names, "no mock provider")
    return names


def planners() -> list[str]:
    from sajha.ai.planners import registered_planners

    return list(registered_planners())


@functools.lru_cache(maxsize=1)
def service() -> Any:
    """Ask SAJHA over the whole catalog, on the offline mock model only (no keys, no
    network for the model, no audit written)."""
    from sajha.ai import tool_resolver
    from sajha.ai.gateway import build_gateway
    from sajha.ai.intelligence import IntelligenceService
    from sajha.ai.llm.settings import AskSettings

    gw = build_gateway(
        {
            "gateway": {"load_entry_points": False, "use_db_providers": False},
            "providers": [{"name": "mock", "config": {"enabled": True, "scripts_dir": ""}}],
        },
        environ={},
    )
    res = tool_resolver.ToolResolver(None, registry(), persist=False)
    return IntelligenceService(gw, registry(), resolver=res, settings=AskSettings(audit=False), audit=lambda e: None)


def ask_run() -> dict[str, Any]:
    """One question through Ask SAJHA on the mock: the events the chat page animates,
    captured as they are emitted."""
    from sajha.ai.llm import RequestContext
    from sajha.ai.llm.settings import AskSettings

    svc = service()
    events = [e for e in svc.stream_ask(ASK_QUESTION, RequestContext(user_id="deck")) if e["type"] != "answer_delta"]
    done = next(e for e in events if e["type"] == "done")["result"]
    short = next(e for e in events if e["type"] == "shortlist")["tools"]
    if hasattr(done, "to_dict"):
        done = done.to_dict()
    steps = done["steps"]
    _need(done["stopped_by"] == "answer" and steps and all(s["ok"] for s in steps), "the mock ask failed")
    return {
        "question": ASK_QUESTION,
        "shortlist": [(t["name"], t["score"]) for t in short],
        "steps": [(s["name"], s["arguments"], s["summary"], s["latency_ms"], s["confidence"]) for s in steps],
        "answer": done["answer"],
        "confidence": done["confidence"],
        "citations": done["citations"],
        "model": done["models"][0] if done["models"] else "",
        "tokens": done["usage"]["total_tokens"],
        "planner": done["planner"],
        "events": [e["type"] for e in events],
        "duration_ms": done["duration_ms"],
        "shortlist_setting": AskSettings().shortlist,
    }


def confidence_rules() -> dict[str, float]:
    """The per-group confidences and the discounts Ask SAJHA applies, from the code."""
    import inspect

    from sajha.ai import intelligence
    from sajha.core.composition import get_tool_confidence

    src = inspect.getsource(intelligence.IntelligenceService._confidence)
    failed = re.search(r':failed", (0\.\d+)\)', src)
    incomplete = re.search(r'incomplete:\{res\.stopped_by\}", (0\.\d+)\)', src)
    _need(failed and incomplete, "IntelligenceService._confidence no longer has its two discounts")
    return {
        "calc": get_tool_confidence("calc_x"),
        "fred": get_tool_confidence("fred_x"),
        "web": get_tool_confidence("web_x"),
        "default": get_tool_confidence("zz_x"),
        "failed": float(failed.group(1)),
        "incomplete": float(incomplete.group(1)),
        "unverified": intelligence.UNVERIFIED_CONFIDENCE,
    }


def eval_runs() -> dict[str, Any]:
    """The shipped eval set, run offline on the mock with two planners."""
    import yaml

    from sajha.quality import evals as E

    path = ROOT / "config" / "evals" / "calculators.yaml"
    es = E.parse_set(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
    runs = {pl: E.run_set(service(), es, "mock/mock-planner", pl)["summary"] for pl in ("react", "plan_execute")}
    return {"set": es.name, "questions": len(es.questions), "runs": runs}


# ── how it runs, and how it compares ───────────────────────────────────


def storage_backends() -> list[str]:
    from sajha.core import storage

    names = [
        c.__name__.replace("StorageBackend", "")
        for c in vars(storage).values()
        if isinstance(c, type) and issubclass(c, storage.StorageBackend) and not c.__name__.startswith("_")
        and c is not storage.StorageBackend
    ]
    return names


def state_backends() -> list[str]:
    from sajha.core.state import BACKENDS

    return list(BACKENDS)


def schema_dialects() -> list[str]:
    return sorted(p.name for p in (ROOT / "db" / "scripts").iterdir() if (p / "schema.sql").exists())


def helm_templates() -> list[str]:
    return sorted(p.stem for p in (ROOT / "charts" / "sajha" / "templates").glob("*.yaml"))


def recipes() -> list[str]:
    return sorted(p.name for p in (ROOT / "deployment").iterdir() if p.is_dir())


def competition() -> dict[str, Any]:
    from sajha.web import competitive as c

    dims = c.DIMENSION_IDS
    sajha_cells = {d: c.SAJHA["cells"][d] for d in dims}
    products = [("SAJHA", "Server", c.tally(sajha_cells), sajha_cells)]
    for comp in c.COMPETITORS:
        products.append((comp["name"], comp["kind"], c.tally(comp["cells"]), comp["cells"]))
    return {
        "as_of": c.AS_OF,
        "dims": [(d, c._label(d)) for d in dims],
        "products": products,
        "competitors": c.COMPETITORS,
        "sajha_best_for": c.SAJHA["best_for"],
        "short": c.SHORT_VERSION,
        "not_yes": [(c._label(d), v["verdict"], v["note"]) for d, v in sajha_cells.items() if v["verdict"] != "Yes"],
    }


@functools.lru_cache(maxsize=1)
def facts() -> dict[str, Any]:
    """Everything, once per build."""
    logging.disable(logging.CRITICAL)
    try:
        return {
            "version": version(),
            "catalog": catalog(),
            "eras": eras(),
            "ci": ci(),
            "conformance": conformance(),
            "tests": tests(),
            "fixes": security_fixes(),
            "limitations": limitations(),
            "policy": policy_example(),
            "audit": audit_example(),
            "siem": siem(),
            "sandbox": sandbox_backends(),
            "accounts": account_templates(),
            "connectors": connector_kinds(),
            "studio": studio_creators(),
            "workflows": workflow_model(),
            "composition": composition_example(),
            "providers": providers(),
            "planners": planners(),
            "ask": ask_run(),
            "evals": eval_runs(),
            "confidence": confidence_rules(),
            "storage": storage_backends(),
            "state": state_backends(),
            "schemas": schema_dialects(),
            "helm": helm_templates(),
            "recipes": recipes(),
            "competition": competition(),
        }
    finally:
        logging.disable(logging.NOTSET)


if __name__ == "__main__":
    import pprint

    pprint.pprint(facts(), width=120, compact=True)
