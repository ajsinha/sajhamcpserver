# SAJHA MCP Server — Composition Framework

**Version 4.5.0** · Inspired by "On the Composability of Intelligence: A Category Theory Framework"

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.

---

## Overview

SAJHA's Composition Framework brings mathematical guarantees from Category Theory into practical tool orchestration. When tools are chained together — whether in parallel (sibling) or sequentially (parent-child) — the framework automatically tracks confidence, isolates parameters, and guards against runaway uncertainty.

No other MCP server tells you how confident a composite answer is. SAJHA does.

---

## The Problem

When you chain `stock_screener → stock_profile → risk_calculator`, three things go wrong without a composition framework:

1. **Errors vanish** — if `stock_profile` fails for one ticker, the pipeline continues with missing data. The final result looks complete but is silently wrong.

2. **Uncertainty compounds** — the screener returns stocks with a relevance score (stochastic). The profile lookup treats that score as certain. The risk calculator treats the profile as certain. Nobody tracks the cumulative confidence. An enterprise user gets "Low Risk" that's actually only 40% confident.

3. **Coupling creeps in** — child steps accidentally depend on parent output fields that change in a future version. A rename of `ticker` to `symbol` in the master tool breaks all children.

---

## The Four Pillars

### Pillar 1: Kleisli Composition (StepResult Envelope)

**Concept:** Every tool execution — deterministic or stochastic — returns a `StepResult` envelope. This is our monadic type `M[A]`.

**File:** `sajha/core/composition.py`

```python
@dataclass
class StepResult:
    value: Any              # The tool's output
    error: Optional[str]    # None = success, set = short-circuits pipeline
    trace: List[str]        # Accumulates: ["✓ yahoo_quote: 230ms", "✗ calc_risk: timeout"]
    duration_ms: float      # Per-step timing
    confidence: float       # 1.0 = deterministic, 0.0 = failed
    step_name: str          # Which tool produced this
```

**Key operations:**

`pure(value)` — Lift a plain value into the envelope. Confidence = 1.0 (deterministic).

`fail(error)` — Lift an error. Confidence = 0.0. All downstream steps short-circuit.

`bind(f)` — Chain a function. If this result is an error, skip `f` entirely (monadic short-circuit). If success, run `f`, compound confidence (`self.confidence × next.confidence`), accumulate traces.

**Why this matters:** Without the envelope, a composite tool that runs 5 steps must wrap each in try/catch, manually accumulate timing, manually track which steps succeeded. With `StepResult`, the `execute_step()` function handles all of this uniformly for any tool.

```python
def execute_step(tool, arguments, step_name) -> StepResult:
    """Wraps any tool's .execute() in a StepResult envelope."""
    confidence = get_tool_confidence(step_name)
    start = time.time()
    try:
        result = tool.execute(arguments)
        return StepResult(value=result, confidence=confidence, ...)
    except Exception as e:
        return StepResult(error=str(e), confidence=0.0, ...)
```

### Pillar 2: Coalgebras (Transport Equivalence)

**Concept:** An agent's behavior is defined by its transition function: `step(input) → (output, new_state)`. If two implementations produce the same outputs for the same inputs, they are **bisimilar** — behaviorally equivalent.

**File:** `clientsdk/sajhaclient/mcp_client.py`

This pillar applies to the Client SDK, not the server. SAJHA has three transport clients (HTTP, SSE, WebSocket) that should behave identically for the same MCP operations. The `TransportCoalgebra` abstract class enforces this:

```python
class TransportCoalgebra:
    def step(self, method: str, params: dict) -> (result, new_state):
        """α: S → (Input → (Output × S))"""

class HTTPTransport(TransportCoalgebra): ...
class SSETransport(TransportCoalgebra): ...
class WSTransport(TransportCoalgebra): ...
```

**Bisimulation test:**

```python
result = bisimilar(
    HTTPTransport(config, auth),
    WSTransport(config, auth),
    test_sequence=[
        ('initialize', None),
        ('tools/list', None),
        ('tools/call', {'name': 'yahoo_quote', 'arguments': {'symbol': 'AAPL'}})
    ]
)
assert result['passed']  # Same structure = safe to hot-swap
```

**Why this matters:** If a WebSocket connection drops, the client can fall back to HTTP POST without behavior changes. The bisimulation test proves this is safe.

### Pillar 3: Lenses (Parameter Isolation)

**Concept:** A lens is a pair of functions — `view` (extract a subset) and `set` (merge back) — that provide surgical access to a larger structure. Child tools receive ONLY the fields their lens projects.

**File:** `sajha/core/composition.py`

```python
@dataclass
class ParamLens:
    mapping: Dict[str, str]       # {"symbol": "$.ticker", "period": "$input.timeframe"}
    static_params: Dict[str, Any] # {"limit": 5}
    output_key: str               # Where to merge result back

    def view(self, parent_output, master_input, record) -> Dict:
        """Extract child params from parent context. Child can't see other fields."""

    def set(self, whole, child_result) -> Dict:
        """Merge child result back into the composite output."""
```

**Mapping syntax:**

| Expression | Meaning | Source |
|-----------|---------|--------|
| `$.ticker` | Field from parent record | Used in parent-child per-record |
| `$input.symbol` | Field from original pipeline input | Passed through from user |
| `5` (literal) | Static value | Hardcoded in step definition |

**Why this matters:** Without lenses, the child tool receives the entire parent output dict. If the parent adds a field called `limit` in a future version, and the child also has a `limit` parameter, the child silently gets the wrong value. With `ParamLens`, the child sees exactly `{"symbol": "AAPL"}` — nothing else leaks through.

### Pillar 4: Giry Monad (Entropy Guard)

**Concept:** When stochastic steps compose, uncertainty compounds. The Giry monad tracks probability distributions through a pipeline. SAJHA simplifies this to a scalar confidence score with entropy calculation.

**File:** `sajha/core/composition.py`

```python
@dataclass
class EntropyGuard:
    max_entropy_bits: float = 3.0    # Threshold (3.0 bits ≈ 12.5% confidence floor)
    cumulative_confidence: float = 1.0

    def record_step(self, step_name, confidence):
        """Sequential: multiply. Parallel: collect for min()."""

    def begin_parallel(self):
        """Start parallel group — uses weakest-link model."""

    def end_parallel(self):
        """Close group: min(confidences), then multiply into chain."""

    def check_safe(self, pipeline_name) -> Dict:
        """Returns {passed, entropy_bits, confidence_floor, steps}."""
```

---

## Parallel vs Sequential Confidence

This is the key design decision. The article's Giry bind multiplies probabilities through a chain, which is correct for sequential composition but over-penalizes parallel steps.

### Sequential (Parent-Child)

```
master(0.95) → step_1(0.92) → step_2(0.85)
Confidence = 0.95 × 0.92 × 0.85 = 0.742
```

Correct: each step processes the previous step's output. If master returns wrong data, ALL downstream steps are wrong.

### Parallel (Sibling)

```
master(0.95) → ┌ step_1(0.92) → result_a
               ├ step_2(0.85) → result_b
               └ step_3(0.90) → result_c
```

Wrong (multiply): 0.95 × 0.92 × 0.85 × 0.90 = 0.669 (66.9%)
Correct (weakest link): 0.95 × min(0.92, 0.85, 0.90) = 0.95 × 0.85 = 0.808 (80.8%)

The parallel steps are INDEPENDENT — step_2's output doesn't depend on step_1. The composite is as reliable as its least reliable component.

### Parent-Child with Multiple Children Per Record

```
master → [record_1, record_2, ...] → for each record:
                                       ├ child_a(0.93)
                                       └ child_b(0.88)
```

Per-record children are parallel (independent of each other). The record loop is sequential (each record depends on master). So:

```
confidence = master_conf × min(child_a_conf, child_b_conf)
           = 0.95 × min(0.93, 0.88)
           = 0.95 × 0.88
           = 0.836
```

---

## Tool Confidence Registry

Every tool is pre-classified by reliability:

| Category | Prefix | Confidence | Rationale |
|----------|--------|:----------:|-----------|
| Calculators | `calc_` | 1.00 | Pure math, no external dependency |
| OLAP | `olap_`, `duckdb_` | 1.00 | Local DB query, deterministic |
| Central Banks | `fred_`, `ecb_` | 0.95 | Stable government APIs |
| Financial Data | `fmp_` | 0.93 | Reliable commercial API |
| Market Data | `yahoo_`, `alpha_` | 0.91-0.92 | Free APIs, occasional gaps |
| Enterprise | `powerbi_`, `sharepoint_` | 0.90-0.95 | Internal, usually reliable |
| Crypto | `coingecko_` | 0.88 | Volatile data, rate limits |
| Search | `tavily_`, `google_` | 0.85 | Web results vary |
| Web Crawl | `web_` | 0.80 | External sites, unpredictable |
| User-defined | (default) | 0.90 | Unknown reliability |

These defaults can be overridden per-tool in the tool's JSON config.

---

## Composite Result Format

Every composite tool execution returns a `_composition` metadata block:

```json
{
  "master": { "...tool output..." },
  "step_0": { "...tool output..." },
  "_composition": {
    "confidence": 0.808,
    "entropy_bits": 0.707,
    "confidence_floor": 0.613,
    "duration_ms": 1230.5,
    "steps_executed": 4,
    "steps_succeeded": 4,
    "trace": [
      "✓ fmp_stock_screener: 450ms",
      "✓ yahoo_quote: 230ms",
      "✓ fred_vix: 180ms",
      "✓ calc_risk: 5ms"
    ],
    "guard_passed": true,
    "guard_message": ""
  }
}
```

If `guard_passed` is `false`, the entropy threshold was exceeded. The `guard_message` explains what to do: "Insert a deterministic checkpoint to reduce uncertainty."

---

## Client-Side Pipelines

The Client SDK provides `ClientPipeline` for composing tools without server-side definitions:

```python
from sajhaclient import SajhaClient, SajhaConfig, ApiKeyAuth, ClientPipeline

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002"), auth=ApiKeyAuth("key"))

pipeline = ClientPipeline(client)
pipeline.add_step("yahoo_quote", param_map={"symbol": "$input.ticker"})
pipeline.add_step("calc_sharpe", param_map={"returns": "$.history"})
pipeline.add_step("tavily_search", param_map={"query": "$.companyName"})

result = pipeline.execute({"ticker": "AAPL"}, max_entropy_bits=2.0)
# result['_composition']['confidence'] = 0.72
# result['_composition']['guard_passed'] = True
```

Client pipelines use the same `$input.` / `$.` syntax as server composites, and the same entropy tracking.

---

## Files

| File | Lines | Purpose |
|------|------:|---------|
| `sajha/core/composition.py` | 430 | StepResult, PipelineResult, ParamLens, EntropyGuard, execute_step, TOOL_CONFIDENCE |
| `sajha/tools/composite_tool.py` | 372 | CompositeTool (uses composition framework), CompositeToolEngine |
| `clientsdk/sajhaclient/mcp_client.py` | 817 | TransportCoalgebra, HTTPTransport, SSETransport, WSTransport, bisimilar, ClientPipeline |

---

*SAJHA MCP Server v5.0.0 — Composition Framework*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
