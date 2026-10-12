# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The LLM package is import safe: without the optional vendor libraries (boto3, google-auth, PyJWT) the
package imports, the factory builds, the mock answers, and a provider that needs a missing library is
down with a clear error instead of breaking startup. A provider module that fails to import is
skipped and the rest still register. Each case runs in a fresh interpreter so the blocked modules are
really absent.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_BLOCK = textwrap.dedent("""
    import importlib.abc, sys

    class Block(importlib.abc.MetaPathFinder):
        def __init__(self, names): self.names = names
        def find_spec(self, name, path=None, target=None):
            if name.split('.')[0] in self.names or name in self.names:
                raise ImportError(f'blocked for the test: {name}')
            return None
""")


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", _BLOCK + textwrap.dedent(code)], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def test_package_imports_and_mock_answers_without_optional_vendor_libraries():
    r = _run("""
        sys.meta_path.insert(0, Block({'boto3', 'botocore', 'google', 'jwt'}))
        from sajha.ai.llm import registry
        from sajha.ai.llm.factory import build_llm_factory
        from sajha.ai.llm.canonical import ChatMessage
        registry.ensure_builtins()
        names = set(registry.registered_providers())
        assert {'mock', 'anthropic', 'openai', 'gemini', 'ollama', 'bedrock'} <= names, names
        f = build_llm_factory({"gateway": {"load_entry_points": False, "use_db_providers": False}}, environ={})
        c = f.provider("mock").model("mock-echo").chat_completions_create(messages=[ChatMessage.user("hi")])
        assert c.text, c
        print("OK")
    """)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-2000:]


def test_bedrock_without_boto3_is_down_with_a_clear_error_not_a_startup_failure():
    r = _run("""
        sys.meta_path.insert(0, Block({'boto3', 'botocore'}))
        from sajha.ai.llm import registry
        from sajha.ai.llm.errors import LLMError
        registry.ensure_builtins()
        cls = registry.registered_providers()['bedrock']
        p = cls.from_settings('bedrock', {'enabled': True, 'region': 'us-east-1'})
        try:
            p.health()
            msg = str(p.health())
        except LLMError as e:
            msg = str(e)
        assert 'boto3' in msg, msg
        print("OK")
    """)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-2000:]


def test_a_provider_module_that_fails_to_import_is_skipped_and_the_rest_register():
    r = _run("""
        sys.meta_path.insert(0, Block({'sajha.ai.llm.providers.cohere'}))
        from sajha.ai.llm import registry, providers
        registry.ensure_builtins()
        names = set(registry.registered_providers())
        assert 'cohere' not in names and {'mock', 'anthropic', 'bedrock', 'ollama'} <= names, names
        assert 'cohere' in providers.FAILED, providers.FAILED
        print("OK")
    """)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-2000:]


def test_bedrock_async_path_without_aiobotocore_falls_back_to_the_worker_thread():
    r = _run("""
        sys.meta_path.insert(0, Block({'boto3', 'botocore', 'aiobotocore', 'aioboto3'}))
        from sajha.ai.llm import registry
        registry.ensure_builtins()
        p = registry.registered_providers()['bedrock'].from_settings('bedrock', {'enabled': True})
        assert p.async_native() is False
        print("OK")
    """)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-2000:]
