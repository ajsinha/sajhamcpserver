# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The local lab's status names the models the instances actually use (deployment/local-lab/lab.py):
it said "LLM: Ollama" even when the mock provider served every alias."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    'sajha_local_lab', Path(__file__).resolve().parents[1] / 'deployment' / 'local-lab' / 'lab.py')
lab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lab)


def test_the_mock_provider_is_reported_as_the_mock():
    line = lab.llm_line({'mock_active': True, 'resolved_aliases': {'default': 'mock/mock-planner'}})
    assert line.startswith('LLM: the mock provider') and 'Ollama at' in line     # and what the lab configured


def test_a_real_model_is_named_as_resolved():
    line = lab.llm_line({'mock_active': False, 'resolved_aliases': {
        'default': 'ollama/qwen3:8b', 'fast': 'ollama/qwen2.5:3b', 'embedding': 'ollama/nomic-embed-text',
        'reasoning': 'ollama/qwen3:8b'}})
    assert line == 'LLM: ollama/qwen3:8b (default), ollama/qwen2.5:3b (fast), ollama/nomic-embed-text (embedding)'


def test_without_a_running_instance_it_says_what_is_configured():
    assert 'as configured' in lab.llm_line(None) and 'mock' not in lab.llm_line(None)
