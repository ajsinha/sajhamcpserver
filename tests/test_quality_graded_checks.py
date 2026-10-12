# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The model-graded answer check of evals (sajha/quality/judge.py): validation, off by default
(skipped, not failed), on through quality.evals.graded_checks or the CLI's --graded, deterministic on
the mock provider, reached only through llm_factory().model(alias), and a failing grader reported as
a failed check rather than an error.

Docs: docs/architecture/Tool Quality.md §5
"""

from types import SimpleNamespace

import pytest

from sajha.ai.llm.types import Usage
from sajha.quality import evals as E
from sajha.quality import judge
from tests.ai.conftest import make_gateway

GRADED = {'graded': 'states the percentage change of 25 percent'}


@pytest.fixture
def factory():
    from sajha.ai.llm import llm_factory, set_llm_factory
    before = llm_factory()
    gw = make_gateway()
    set_llm_factory(gw)
    yield gw
    set_llm_factory(before)


def _q(*checks):
    return E.parse_set({'name': 's', 'questions': [{'id': 'q', 'question': 'What is the change from 80 to 100?',
                                                     'answer': list(checks)}]}).questions[0]


def _result(answer):
    return SimpleNamespace(steps=[], answer=answer, stopped_by='answer', usage=Usage(1, 0, 0, 0.0), duration_ms=1,
                           error='', models=['m'], planner='react')


@pytest.mark.parametrize('check,msg', [
    ({'graded': ''}, 'criterion'),
    ({'graded': 'x', 'min_score': 9}, 'from 1 to 5'),
    ({'graded': 'x', 'model': ''}, 'model alias'),
    ({'contains': 'x', 'min_score': 3}, 'belong to a graded check'),
])
def test_bad_graded_checks_are_refused(check, msg):
    with pytest.raises(E.EvalError, match=msg):
        _q(check)


def test_off_by_default_the_check_is_skipped_not_failed(factory, monkeypatch):
    monkeypatch.delenv('SAJHA_QUALITY_EVALS_GRADED_CHECKS', raising=False)
    calls = []
    monkeypatch.setattr(judge, 'grade', lambda *a, **k: calls.append(a) or {})
    row = E.score(_q({'contains': 'percent'}, GRADED), _result('It rose 25 percent'))
    assert row['passed'] and row['skipped_checks'] == [GRADED['graded']] and calls == []


def test_on_it_grades_deterministically_on_the_mock(factory):
    with judge.forced(True):
        good = E.score(_q(GRADED), _result('The value rose by 25 percent.'))
        bad = E.score(_q(GRADED), _result('I could not find it.'))
    assert good['passed'] and good['answer_ok'] and good['skipped_checks'] == []
    assert not bad['passed'] and not bad['answer_ok']
    assert any(r.startswith('graded 3/5 < 4') for r in bad['reasons'])


def test_config_turns_it_on_and_min_score_is_honoured(factory, monkeypatch):
    monkeypatch.setenv('SAJHA_QUALITY_EVALS_GRADED_CHECKS', 'true')
    assert judge.enabled()
    lenient = E.score(_q({**GRADED, 'min_score': 3}), _result('nothing relevant'))
    assert lenient['passed']                                          # the mock's midpoint is 3


def test_the_grader_goes_through_llm_factory_model(factory, monkeypatch):
    seen = []
    real = factory.model

    def model(alias, **kw):
        seen.append(alias)
        return real(alias, **kw)
    monkeypatch.setattr(factory, 'model', model)
    g = judge.grade({**GRADED, 'model': 'default'}, 'q?', 'It changed by 25 percent')
    assert seen == ['default'] and g['passed'] and g['score'] == 5 and g['model'].startswith('mock/')


def test_no_model_is_a_failed_check_not_an_error(monkeypatch):
    from sajha.ai.llm import llm_factory, set_llm_factory
    before = llm_factory()
    set_llm_factory(None)
    try:
        with judge.forced(True):
            row = E.score(_q(GRADED), _result('25 percent'))
    finally:
        set_llm_factory(before)
    assert not row['passed'] and any('graded check could not run' in r for r in row['reasons'])


def test_score_key_keeps_content_words():
    assert judge.score_key('States the percentage change of 25 percent') == 'percentage_change_25_percent'
    assert judge.score_key('the and of') == 'criterion'


def test_cli_graded_flag(tmp_path, monkeypatch, factory, capsys):
    from sajha.quality import __main__ as cli
    (tmp_path / 's.yaml').write_text(
        'name: s\nquestions:\n  - id: q\n    question: "What is the percentage change from 80 to 100?"\n'
        '    answer:\n      - graded: "an unrelated zebra criterion"\n', encoding='utf-8')
    monkeypatch.setattr(cli, '_cli_service', lambda: SimpleNamespace(gateway=factory))

    def fake_run(svc, es, model, planner, ctx=None):
        row = E.score(es.questions[0], _result('The change is 25 percent'))
        return {'set': es.name, 'model': 'm', 'planner': 'p', 'started_at': 0, 'duration_s': 0,
                'summary': E.summarise([row]), 'questions': [row]}
    monkeypatch.setattr(E, 'run_set', fake_run)
    monkeypatch.delenv('SAJHA_QUALITY_EVALS_GRADED_CHECKS', raising=False)
    assert cli.main(['eval', '--dir', str(tmp_path), '--no-save']) == 0          # skipped: passes
    assert 'graded checks are off' in capsys.readouterr().out
    assert cli.main(['eval', '--dir', str(tmp_path), '--no-save', '--graded']) == 1   # graded: zebra not in it
