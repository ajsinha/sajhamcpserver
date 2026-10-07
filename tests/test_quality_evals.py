"""Evals for Ask SAJHA, offline on the mock provider: set parsing, scoring (tool selection, answer
checks, limits), per model x planner runs, comparison, saved runs, the CLI and JUnit."""

import json
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from sajha.ai.intelligence import IntelligenceService
from sajha.ai.llm.settings import AskSettings
from sajha.ai.llm.types import Usage
from sajha.quality import evals as E
from sajha.quality.store import RunStore, set_run_store
from tests.ai.conftest import ToolBox, make_gateway

SET = {
    'name': 'calc', 'models': ['mock/mock-planner'], 'planners': ['react'], 'tools': ['calc_*'],
    'defaults': {'max_steps': 3},
    'questions': [
        {'id': 'pct', 'question': 'What is the percentage change from 80 to 100?',
         'expect_tools': ['calc_percentage_change'], 'answer': [{'number': 25, 'tolerance': 0.01}]},
        {'id': 'npv', 'question': 'What is the net present value NPV of cash flows -100, 50, 60 at discount rate 10',
         'expect_tools': ['calc_npv'], 'forbid_tools': ['calc_irr'], 'answer': [{'regex': r'-?4\.96'}]},
    ],
}


@pytest.fixture
def service():
    return IntelligenceService(make_gateway(), ToolBox(), settings=AskSettings(audit=False), audit=lambda e: None)


def test_parse_and_validate():
    es = E.parse_set(SET, 'x.yaml')
    assert [q.id for q in es.questions] == ['pct', 'npv'] and es.questions[0].max_steps == 3
    for bad in ({'name': 'x', 'questions': []}, {'name': 'x', 'questions': [{'id': 'a'}]},
                {'name': 'x', 'questions': [{'question': 'q', 'answer': [{'regex': '('}]}]},
                {'name': 'x', 'questions': [{'question': 'q', 'answer': [{'smells_like': 'x'}]}]},
                {'name': 'x', 'questions': [{'id': 'a', 'question': 'q'}, {'id': 'a', 'question': 'r'}]}):
        with pytest.raises(E.EvalError):
            E.parse_set(bad)


@pytest.mark.parametrize('check,answer,ok', [
    ({'contains': 'Paris'}, 'the capital is paris', True),
    ({'not_contains': 'error'}, 'all good', True),
    ({'regex': r'\d+%'}, 'up 25%', True),
    ({'number': 25, 'tolerance': 0.1}, 'It rose 25.04 percent', True),
    ({'number': 1647.01}, 'about 1,647.01 dollars', True),
    ({'number': 25}, 'It rose 26 percent', False),
    ({'equals': 'yes'}, ' Yes ', True),
])
def test_answer_checks(check, answer, ok):
    assert (E.check_answer(check, answer) is None) is ok


def _result(steps, answer='25%', stopped='answer', tokens=100, cost=0.0, ms=10):
    return SimpleNamespace(steps=[SimpleNamespace(name=s) for s in steps], answer=answer, stopped_by=stopped,
                           usage=Usage(tokens, 0, 0, cost), duration_ms=ms, error='', models=['m'], planner='react')


def test_scoring():
    q = E.parse_set(SET).questions[1]
    good = E.score(q, _result(['calc_npv'], answer='NPV is -4.96'))
    assert good['passed'] and good['tool_recall'] == 1.0 and good['tool_precision'] == 1.0
    wrong = E.score(q, _result(['calc_irr', 'calc_npv'], answer='-4.96'))
    assert not wrong['passed'] and not wrong['tool_ok'] and wrong['tool_precision'] == 0.5
    assert any('forbidden' in r for r in wrong['reasons'])
    long = E.score(q, _result(['calc_npv'] * 4, answer='-4.96'))
    assert long['tool_ok'] and not long['limits_ok'] and any('steps' in r for r in long['reasons'])
    stopped = E.score(q, _result(['calc_npv'], answer='-4.96', stopped='budget'))
    assert not stopped['passed']


def test_run_set_offline_on_the_mock(service):
    es = E.parse_set(SET)
    run = E.run_set(service, es, 'mock/mock-planner', 'react')
    s = run['summary']
    assert s['questions'] == 2 and s['passed'] == 2, run['questions']
    assert s['tool_selection_accuracy'] == 1.0 and s['answer_accuracy'] == 1.0 and s['total_tokens'] > 0
    assert run['questions'][0]['tools_called'] == ['calc_percentage_change']


def test_tools_restrict_what_is_offered(service):
    es = E.parse_set({**SET, 'tools': ['calc_npv']})
    run = E.run_set(service, es, 'mock/mock-planner', 'react')
    assert run['questions'][0]['tools_called'] in ([], ['calc_npv'])      # percentage change is not offered
    assert not run['questions'][0]['passed']


def test_plan_execute_planner_runs_too(service):
    run = E.run_set(service, E.parse_set(SET), 'mock/mock-planner', 'plan_execute')
    assert run['planner'] == 'plan_execute' and run['summary']['tool_selection_accuracy'] == 1.0


def test_combos():
    es = E.parse_set(SET)
    assert E.combos(es) == [('mock/mock-planner', 'react')]
    assert E.combos(es, ['a', 'b'], ['p', 'q']) == [('a', 'p'), ('a', 'q'), ('b', 'p'), ('b', 'q')]


def test_compare_finds_regressions():
    a = {'set': 's', 'model': 'm1', 'planner': 'p', 'summary': {'pass_rate': 1.0, 'mean_tokens': 100},
         'questions': [{'id': 'x', 'question': 'X', 'passed': True, 'tools_called': ['t']},
                       {'id': 'y', 'question': 'Y', 'passed': False, 'tools_called': []}]}
    b = {'set': 's', 'model': 'm2', 'planner': 'p', 'summary': {'pass_rate': 0.5, 'mean_tokens': 80},
         'questions': [{'id': 'x', 'question': 'X', 'passed': False, 'reasons': ['missing tools: t'], 'tools_called': []},
                       {'id': 'y', 'question': 'Y', 'passed': True, 'tools_called': ['u']}]}
    c = E.compare(a, b)
    m = {r['metric']: r for r in c['metrics']}
    assert m['pass_rate']['direction'] == 'worse' and m['mean_tokens']['direction'] == 'better'
    assert [q['id'] for q in c['regressed']] == ['x'] and [q['id'] for q in c['improved']] == ['y']
    assert len(c['changed_tools']) == 2
    assert 'Regressed' in E.render_compare(c)


def test_saved_runs_and_background(service, tmp_path):
    store = RunStore(create_engine(f'sqlite:///{tmp_path / "q.db"}'))
    set_run_store(store)
    try:
        es = E.parse_set(SET)
        rid = E.start_background(service, es, 'mock/mock-planner', 'react', 'tester')
        import time
        for _ in range(100):
            row = store.get(rid)
            if row['status'] != 'running':
                break
            time.sleep(0.05)
        assert row['status'] == 'done' and row['summary']['passed'] == 2 and row['created_by'] == 'tester'
        run = E.saved_run(rid)
        assert run['set'] == 'calc' and len(run['questions']) == 2
        assert [r['id'] for r in store.list('eval')] == [rid] and store.list('test') == []
        assert store.delete(rid) and store.get(rid) is None
    finally:
        set_run_store(None)


def test_junit():
    run = {'set': 's', 'model': 'm', 'planner': 'p', 'duration_s': 1,
           'questions': [{'id': 'a', 'passed': True, 'latency_ms': 5, 'reasons': []},
                         {'id': 'b', 'passed': False, 'latency_ms': 5, 'reasons': ['missing tools: t']}]}
    root = ET.fromstring(E.render_junit([run]))
    assert root.get('tests') == '2' and root.get('failures') == '1'


def test_shipped_set_and_cli(tmp_path, monkeypatch):
    """config/evals/calculators.yaml passes offline; eval --json then compare the file with itself."""
    from sajha.quality.__main__ import main
    out = tmp_path / 'run.json'
    assert main(['eval', 'calculators', '--no-save', '--json', str(out), '--junit', str(tmp_path / 'e.xml')]) == 0
    data = json.loads(out.read_text())
    assert data['summary']['pass_rate'] == 1.0
    assert main(['compare', str(out), str(out)]) == 0
    assert main(['eval', 'no-such-set', '--no-save']) == 2
