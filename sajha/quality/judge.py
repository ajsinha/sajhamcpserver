"""
SAJHA MCP Server — a model-graded answer check for evals, beside the lexical ones.

An eval question's ``answer`` list may hold a ``graded`` check::

    answer:
      - number: 25
      - graded: "states that the value rose, and by how much"
        min_score: 4          # 1-5, default 4
        model: fast           # a model alias, default quality.evals.grader_model ('default')

The grader is a model reached only through ``llm_factory().model(alias)`` (the intelligence layer's
governed model: role policy, budgets, retries, fallback, audit, usage and cost). It is asked for one
score from 1 to 5 against the criterion, with the question for context, and the check passes when
the score is at least ``min_score``. The call is marked ``metadata.sajha_llm_mode: judge``, so on the
mock provider it is deterministic (the criterion's content words found in the answer score 5,
otherwise 3) and evals still run offline.

Graded checks are **off by default**: they cost tokens and are not deterministic on a real model.
With ``quality.evals.graded_checks`` false they are skipped (listed in the row's ``skipped_checks``,
neither passed nor failed); ``python -m sajha.quality eval --graded`` turns them on for one run.

Docs: docs/architecture/Tool Quality.md §5.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import re
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

CHECK = 'graded'
KEYS = (CHECK, 'model', 'min_score')
MAX_CRITERION = 500
MAX_ANSWER_CHARS = 8000
_STOP = {'a', 'an', 'the', 'and', 'or', 'of', 'to', 'in', 'on', 'for', 'by', 'with', 'is', 'are', 'it', 'its',
         'that', 'this', 'how', 'much', 'many', 'what', 'which', 'answer', 'states', 'state', 'says', 'say',
         'mentions', 'mention', 'gives', 'give', 'includes', 'include', 'names', 'name', 'should', 'must', 'be',
         'as', 'at', 'from', 'whether', 'does', 'do', 'not', 'no'}

_forced: contextvars.ContextVar[Optional[bool]] = contextvars.ContextVar('sajha_graded_checks', default=None)


class GradeError(RuntimeError):
    """The grader could not give a score (no model, refusal, a reply that is not a score)."""


def enabled() -> bool:
    forced = _forced.get()
    if forced is not None:
        return forced
    try:
        from sajha.core.config import _get, parse_bool
        return parse_bool(_get('quality.evals.graded_checks', False), False)
    except Exception:
        return False


@contextlib.contextmanager
def forced(value: Optional[bool]) -> Iterator[None]:
    """Turn graded checks on (or off) for the code inside, whatever the configuration says."""
    token = _forced.set(value)
    try:
        yield
    finally:
        _forced.reset(token)


def default_model() -> str:
    try:
        from sajha.core.config import _get
        return str(_get('quality.evals.grader_model', 'default') or 'default')
    except Exception:
        return 'default'


def validate(check: Dict[str, Any], where: str) -> None:
    """Raise ValueError when a graded check is malformed."""
    criterion = check.get(CHECK)
    if not isinstance(criterion, str) or not criterion.strip():
        raise ValueError(f'{where}: graded needs the criterion as text')
    if len(criterion) > MAX_CRITERION:
        raise ValueError(f'{where}: graded criterion longer than {MAX_CRITERION} characters')
    if 'min_score' in check:
        try:
            ms = int(check['min_score'])
        except (TypeError, ValueError):
            raise ValueError(f'{where}: min_score must be a whole number from 1 to 5')
        if not 1 <= ms <= 5:
            raise ValueError(f'{where}: min_score must be from 1 to 5')
    if 'model' in check and (not isinstance(check['model'], str) or not check['model'].strip()):
        raise ValueError(f'{where}: model must be a model alias')


def score_key(criterion: str) -> str:
    """The criterion's content words as a property name (the schema key the grader fills)."""
    words = [w for w in re.findall(r'[a-z0-9]+', criterion.lower()) if w not in _STOP]
    key = '_'.join(words)[:60].strip('_')
    return key or 'criterion'


SYSTEM = ('You grade an answer against one criterion. Judge only whether the answer meets the criterion, '
          'using the question for context; ignore style and length. Score 1 (does not meet it at all) to 5 '
          '(fully meets it). Reply with the JSON object the schema describes and nothing else.')


def grade(check: Dict[str, Any], question: str, answer: str, ctx: Any = None) -> Dict[str, Any]:
    """{score, min_score, passed, model, reason}; raises GradeError when no score could be obtained."""
    from sajha.ai.llm import LLMError, llm_factory
    from sajha.ai.llm.canonical import ChatMessage, ResponseFormat
    factory = llm_factory()
    if factory is None:
        raise GradeError('the intelligence layer is not running (no LLM factory)')
    criterion = str(check[CHECK]).strip()
    alias = str(check.get('model') or default_model())
    min_score = int(check.get('min_score', 4))
    key = score_key(criterion)
    schema = {'type': 'object', 'title': 'sajha.eval_grade', 'additionalProperties': False,
              'required': ['scores', 'reasons'],
              'properties': {
                  'scores': {'type': 'object', 'additionalProperties': False, 'required': [key],
                             'properties': {key: {'type': 'integer', 'minimum': 1, 'maximum': 5,
                                                  'description': f'How well the answer meets: {criterion}'}}},
                  'reasons': {'type': 'object', 'additionalProperties': False, 'required': [key],
                              'properties': {key: {'type': 'string'}}}}}
    # instruction first, the answer alone after the first blank line (the part that is graded)
    user = (f'Criterion: {criterion}\nQuestion: {" ".join((question or "").split())[:2000]}\nThe answer follows.'
            f'\n\n{(answer or "")[:MAX_ANSWER_CHARS]}')
    try:
        model = factory.model(alias, context=ctx) if ctx is not None else factory.model(alias)
        comp = model.chat_completions_create(
            messages=[ChatMessage.system(SYSTEM), ChatMessage.user(user)], temperature=0.0,
            max_completion_tokens=300, response_format=ResponseFormat.of_schema(schema, name='sajha_eval_grade'),
            metadata={'sajha_llm_tool': 'quality.eval.graded', 'sajha_llm_mode': 'judge'})
    except LLMError as e:
        raise GradeError(f'the grader model ({alias}) is not available: {e}')
    if getattr(comp, 'refusal', None):
        raise GradeError(f'the grader model declined: {comp.refusal}')
    text = (comp.text or '').strip()
    try:
        data = json.loads(text[text.find('{'):text.rfind('}') + 1]) if '{' in text else {}
        value = int((data.get('scores') or {})[key])
    except (ValueError, KeyError, TypeError, AttributeError):
        raise GradeError(f'the grader did not reply with a score: {text[:200]!r}')
    if not 1 <= value <= 5:
        raise GradeError(f'the grader replied with a score outside 1-5: {value}')
    reason = str(((data.get('reasons') or {}).get(key)) or '')[:300]
    used = comp.sajha.qualified_model if getattr(comp, 'sajha', None) else getattr(comp, 'model', alias)
    return {'score': value, 'min_score': min_score, 'passed': value >= min_score, 'model': used or alias,
            'reason': reason}


def check(check_: Dict[str, Any], question: str, answer: str, ctx: Any = None) -> Optional[str]:
    """As ``evals.check_answer``: None when the graded check passes, else why not."""
    try:
        g = grade(check_, question, answer, ctx)
    except GradeError as e:
        return f'graded check could not run: {e}'
    if g['passed']:
        return None
    return (f'graded {g["score"]}/5 < {g["min_score"]} on {check_[CHECK]!r}'
            + (f' ({g["reason"]})' if g['reason'] else ''))
