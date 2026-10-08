# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""run_sajha_web.py honours ``logging.dir`` and ``logging.file`` (it used to write logs/server.log always)."""

import importlib.util
import logging
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _module():
    cwd = os.getcwd()
    spec = importlib.util.spec_from_file_location('run_sajha_web_under_test', ROOT / 'run_sajha_web.py')
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)                 # the module changes to the project root on import
    finally:
        os.chdir(cwd)
    return mod


def test_the_log_file_follows_logging_dir_and_logging_file(tmp_path):
    m = _module()
    assert m.log_file_path('./logs', '') == ''                                  # empty: stdout only
    assert m.log_file_path(str(tmp_path / 'l'), 'sajha.log') == str(tmp_path / 'l' / 'sajha.log')
    assert m.log_file_path('./logs', str(tmp_path / 'abs.log')) == str(tmp_path / 'abs.log')
    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers = []
    try:
        m.setup_logging('INFO', str(tmp_path / 'logdir'), 'mine.log')
        files = [h.baseFilename for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert files == [str(tmp_path / 'logdir' / 'mine.log')]
        for h in root.handlers:
            h.close()
        root.handlers = []
        m.setup_logging('INFO', str(tmp_path / 'logdir'), '')
        assert not [h for h in root.handlers if isinstance(h, logging.FileHandler)]
    finally:
        for h in root.handlers:
            h.close()
        root.handlers = saved
