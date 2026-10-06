"""SAJHA MCP Server v3 — Test Configuration"""
import os, sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))


import pytest


@pytest.fixture(scope='session')
def web():
    """(TestClient, admin cookies) on one started app, shared by the help tests.

    The client's own cookie jar is cleared after signing in, so a plain ``c.get`` is an
    anonymous request and ``c.get(url, cookies=admin)`` a signed-in one."""
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        r = c.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
        admin = dict(r.cookies)
        c.cookies.clear()
        yield c, admin
