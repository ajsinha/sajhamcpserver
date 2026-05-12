"""
SAJHA MCP Server — Composition Framework
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Implements practical patterns from Category Theory for tool composition:

  Pillar 1 (Kleisli): StepResult envelope — unified type for all tool outputs.
                       Error short-circuits, traces accumulate, duration tracks.
  Pillar 3 (Lenses):  ParamLens — surgical projection of parent output into child input.
  Pillar 4 (Giry):    EntropyGuard — cumulative confidence tracking with threshold.

Usage in CompositeToolEngine:
    guard = EntropyGuard(max_entropy_bits=2.0)
    pipeline = Pipeline([step1, step2, step3])
    result = pipeline.execute(args, guard=guard)
    # result.confidence = 0.72, result.entropy_bits = 1.3
"""

from __future__ import annotations
import math
import time
import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# PILLAR 1: Kleisli — Unified Result Envelope
# ═══════════════════════════════════════════════════════════════

@dataclass
class StepResult:
    """
    The monadic result envelope. Every tool execution — deterministic or
    stochastic — returns one of these. This is our M[A].

    Carries: value, error, trace, duration, confidence.
    Bind semantics: if error is set, downstream steps short-circuit.
    """
    value: Any = None
    error: Optional[str] = None
    trace: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    confidence: float = 1.0  # 1.0 = deterministic, 0.0 = no confidence
    step_name: str = ""

    @property
    def is_success(self) -> bool:
        return self.error is None

    @staticmethod
    def pure(value: Any, step_name: str = "") -> StepResult:
        """η (unit): Lift a plain value into the envelope. Deterministic = confidence 1.0."""
        return StepResult(value=value, confidence=1.0, step_name=step_name)

    @staticmethod
    def fail(error: str, step_name: str = "") -> StepResult:
        """Lift an error into the envelope."""
        return StepResult(error=error, confidence=0.0, step_name=step_name)

    def bind(self, f: Callable[[Any], StepResult]) -> StepResult:
        """
        >>= (flatMap): Chain a function onto this result.
        Short-circuits on error. Accumulates trace and compounds confidence.
        """
        if not self.is_success:
            return self  # Error propagation (monadic short-circuit)

        next_result = f(self.value)

        # Accumulate trace
        combined_trace = self.trace + next_result.trace

        # Compound confidence (Giry bind: probabilities multiply)
        combined_confidence = self.confidence * next_result.confidence

        # Accumulate duration
        combined_duration = self.duration_ms + next_result.duration_ms

        return StepResult(
            value=next_result.value,
            error=next_result.error,
            trace=combined_trace,
            duration_ms=combined_duration,
            confidence=combined_confidence,
            step_name=next_result.step_name,
        )


@dataclass
class PipelineResult:
    """
    The final result of a composite pipeline execution.
    Includes the merged output dict plus composition metadata.
    """
    value: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    trace: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    confidence: float = 1.0
    entropy_bits: float = 0.0
    step_results: List[StepResult] = field(default_factory=list)
    guard_passed: bool = True
    guard_message: str = ""

    @property
    def is_success(self) -> bool:
        return self.error is None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for MCP response."""
        d = dict(self.value) if self.value else {}
        d['_composition'] = {
            'confidence': round(self.confidence, 4),
            'entropy_bits': round(self.entropy_bits, 3),
            'duration_ms': round(self.duration_ms, 1),
            'steps_executed': len(self.step_results),
            'steps_succeeded': sum(1 for s in self.step_results if s.is_success),
            'trace': self.trace,
            'guard_passed': self.guard_passed,
        }
        if self.error:
            d['error'] = self.error
        if self.guard_message:
            d['_composition']['guard_message'] = self.guard_message
        return d


# ═══════════════════════════════════════════════════════════════
# PILLAR 3: Lenses — Surgical Param Projection
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ParamLens:
    """
    A Lens that projects fields from a parent output into child input params.

    view: parent_output → child_params (extract what the child needs)
    set:  parent_output × child_result → merged_output (merge child result back)

    Satisfies lens laws:
      GetPut: view(set(w, p)) == p
      PutGet: set(w, view(w)) == w
      PutPut: set(set(w, p1), p2) == set(w, p2)
    """
    mapping: Dict[str, str]       # target_key → source_expr ("$.ticker", "$input.symbol", static)
    static_params: Dict[str, Any] = field(default_factory=dict)
    output_key: str = ""

    def view(self, parent_output: Dict, master_input: Dict = None, record: Dict = None) -> Dict:
        """
        Extract child params from parent context.
        This is the 'get' half of the lens — projects only what the child needs.
        """
        params = dict(self.static_params)
        for target_key, source_expr in self.mapping.items():
            if isinstance(source_expr, str) and source_expr.startswith('$.'):
                field_name = source_expr[2:]
                if field_name.startswith('input.'):
                    params[target_key] = (master_input or {}).get(field_name[6:], '')
                else:
                    params[target_key] = (record or {}).get(field_name, '')
            else:
                params[target_key] = source_expr
        return params

    def set(self, whole: Dict, child_result: Any) -> Dict:
        """
        Merge child result back into the whole output under output_key.
        This is the 'set' half of the lens.
        """
        updated = dict(whole)
        updated[self.output_key] = child_result
        return updated

    @staticmethod
    def from_step_definition(step: Dict) -> ParamLens:
        """Build a ParamLens from a composite step DB definition."""
        return ParamLens(
            mapping=step.get('param_mapping') or {},
            static_params=step.get('static_params') or {},
            output_key=step.get('output_key', 'result'),
        )


# ═══════════════════════════════════════════════════════════════
# PILLAR 4: Giry — Entropy Guard
# ═══════════════════════════════════════════════════════════════

def confidence_to_entropy(confidence: float) -> float:
    """
    Convert a confidence score (0.0-1.0) to Shannon entropy in bits.
    A deterministic step (confidence=1.0) has entropy 0.
    Binary uncertainty (confidence=0.5) has entropy 1.0 bit.
    """
    if confidence >= 1.0:
        return 0.0
    if confidence <= 0.0:
        return float('inf')
    p = confidence
    q = 1.0 - p
    entropy = -(p * math.log2(p) + q * math.log2(q))
    return entropy


def entropy_to_confidence_floor(entropy_bits: float) -> float:
    """
    From the article's Corollary: the most-likely output has
    probability >= 2^(-entropy). This is the confidence floor.
    """
    if entropy_bits <= 0:
        return 1.0
    return 2.0 ** (-entropy_bits)


@dataclass
class EntropyGuard:
    """
    Pre-execution and post-execution entropy analysis.

    Tracks cumulative confidence through a composite pipeline.
    Can refuse execution if predicted entropy exceeds threshold.
    Can insert deterministic checkpoints (Dirac injection) to reset entropy.

    Usage:
        guard = EntropyGuard(max_entropy_bits=2.0)
        guard.record_step("yahoo_quote", confidence=0.95)
        guard.record_step("calc_risk", confidence=0.85)
        guard.check()  # Raises if cumulative entropy > 2.0 bits
    """
    max_entropy_bits: float = 3.0   # Default: ~12.5% minimum confidence floor
    cumulative_confidence: float = 1.0
    _parallel_group: List[float] = field(default_factory=list)
    _in_parallel: bool = False
    step_entropies: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def cumulative_entropy(self) -> float:
        return confidence_to_entropy(self.cumulative_confidence)

    @property
    def confidence_floor(self) -> float:
        """Minimum probability of the most-likely output (Corollary from article)."""
        return entropy_to_confidence_floor(self.cumulative_entropy)

    def begin_parallel(self):
        """Begin a parallel group. Steps recorded until end_parallel() use min() instead of multiply."""
        self._in_parallel = True
        self._parallel_group = []

    def end_parallel(self):
        """
        Close a parallel group. Applies weakest-link (min) for the group,
        then multiplies into the cumulative chain.

        Math:
          Sequential (Giry bind): conf_chain = conf_A × conf_B × conf_C
          Parallel (independent):  conf_group = min(conf_A, conf_B, conf_C)
          Mixed: conf = conf_sequential × min(conf_parallel_group)
        """
        if self._parallel_group:
            group_confidence = min(self._parallel_group)
            self.cumulative_confidence *= group_confidence
            self.step_entropies.append({
                'step': f'parallel_group({len(self._parallel_group)} steps)',
                'confidence': round(group_confidence, 4),
                'entropy_bits': round(confidence_to_entropy(group_confidence), 3),
                'model': 'weakest_link',
                'individual': [round(c, 4) for c in self._parallel_group],
                'cumulative_confidence': round(self.cumulative_confidence, 4),
                'cumulative_entropy': round(self.cumulative_entropy, 3),
            })
        self._parallel_group = []
        self._in_parallel = False

    def record_step(self, step_name: str, confidence: float = 1.0):
        """
        Record a step's confidence.

        If inside a parallel group (begin_parallel/end_parallel), collects
        confidences for weakest-link aggregation.

        If sequential, multiplies directly into cumulative
        (Giry bind: probabilities compound through the chain).
        """
        if self._in_parallel:
            self._parallel_group.append(confidence)
            self.step_entropies.append({
                'step': step_name,
                'confidence': round(confidence, 4),
                'entropy_bits': round(confidence_to_entropy(confidence), 3),
                'mode': 'parallel',
            })
        else:
            self.cumulative_confidence *= confidence
            step_entropy = confidence_to_entropy(confidence)
            self.step_entropies.append({
                'step': step_name,
                'confidence': round(confidence, 4),
                'entropy_bits': round(step_entropy, 3),
                'mode': 'sequential',
                'cumulative_confidence': round(self.cumulative_confidence, 4),
                'cumulative_entropy': round(self.cumulative_entropy, 3),
            })

    def record_deterministic(self, step_name: str):
        """
        Record a deterministic step (Dirac injection).
        Entropy resets toward zero — this is the "entropy firebreak" pattern.
        """
        self.record_step(step_name, confidence=1.0)

    def check(self, pipeline_name: str = "pipeline") -> bool:
        """
        Check if cumulative entropy is within bounds.
        Returns True if OK. Raises ValueError if exceeded.
        """
        h = self.cumulative_entropy
        if h > self.max_entropy_bits:
            raise ValueError(
                f"ENTROPY GUARD: Pipeline '{pipeline_name}' has entropy "
                f"{h:.3f} bits (threshold: {self.max_entropy_bits:.3f}). "
                f"Confidence floor: {self.confidence_floor:.1%}. "
                f"Consider inserting a deterministic validation step."
            )
        return True

    def check_safe(self, pipeline_name: str = "pipeline") -> Dict[str, Any]:
        """Non-raising version. Returns status dict."""
        h = self.cumulative_entropy
        passed = h <= self.max_entropy_bits
        return {
            'passed': passed,
            'entropy_bits': round(h, 3),
            'max_entropy_bits': self.max_entropy_bits,
            'cumulative_confidence': round(self.cumulative_confidence, 4),
            'confidence_floor': round(self.confidence_floor, 4),
            'steps': self.step_entropies,
            'message': '' if passed else (
                f"Entropy {h:.3f} exceeds threshold {self.max_entropy_bits:.3f}. "
                f"Insert a deterministic checkpoint to reduce uncertainty."
            ),
        }

    def reset(self):
        """Reset the guard for a new pipeline execution."""
        self.cumulative_confidence = 1.0
        self._parallel_group = []
        self._in_parallel = False
        self.step_entropies = []


# ═══════════════════════════════════════════════════════════════
# TOOL CONFIDENCE REGISTRY
# ═══════════════════════════════════════════════════════════════

# Default confidence scores for tool categories.
# Deterministic tools (DB queries, calculators) = 1.0
# API tools (market data) = 0.95 (API might return stale/missing data)
# LLM tools (AI inference) = 0.80 (stochastic by nature)
# User-defined tools = 0.90 (unknown reliability)

TOOL_CONFIDENCE = {
    # Deterministic
    'calc_': 1.0,
    'olap_': 1.0,
    'duckdb_': 1.0,

    # High-reliability APIs
    'fred_': 0.95,
    'fmp_': 0.93,
    'yahoo_': 0.92,
    'alpha_': 0.91,
    'ecb_': 0.95,

    # Search / Crawl (external, variable)
    'tavily_': 0.85,
    'google_': 0.85,
    'wikipedia_': 0.90,
    'web_': 0.80,

    # Enterprise (internal, reliable)
    'powerbi_': 0.95,
    'sharepoint_': 0.90,
    'livelink_': 0.90,

    # Crypto (volatile data)
    'coingecko_': 0.88,

    # Default
    '_default': 0.90,
}


def get_tool_confidence(tool_name: str) -> float:
    """Get the confidence score for a tool based on its name prefix."""
    for prefix, confidence in TOOL_CONFIDENCE.items():
        if prefix != '_default' and tool_name.startswith(prefix):
            return confidence
    return TOOL_CONFIDENCE['_default']


# ═══════════════════════════════════════════════════════════════
# STEP EXECUTOR — Wraps tool.execute() in StepResult envelope
# ═══════════════════════════════════════════════════════════════

def execute_step(tool, arguments: Dict, step_name: str = "") -> StepResult:
    """
    Execute a single tool and wrap the result in a StepResult envelope.
    This is the Kleisli arrow: Dict → StepResult (our M[Dict]).
    """
    name = step_name or getattr(tool, 'name', 'unknown')
    confidence = get_tool_confidence(name)

    start = time.time()
    try:
        result = tool.execute(arguments)
        duration = (time.time() - start) * 1000

        # Check if tool returned an error dict
        if isinstance(result, dict) and 'error' in result and len(result) == 1:
            return StepResult(
                error=result['error'],
                trace=[f"✗ {name}: {result['error']}"],
                duration_ms=duration,
                confidence=0.0,
                step_name=name,
            )

        return StepResult(
            value=result,
            trace=[f"✓ {name}: {duration:.0f}ms"],
            duration_ms=duration,
            confidence=confidence,
            step_name=name,
        )
    except Exception as e:
        duration = (time.time() - start) * 1000
        return StepResult(
            error=str(e),
            trace=[f"✗ {name}: {e}"],
            duration_ms=duration,
            confidence=0.0,
            step_name=name,
        )
