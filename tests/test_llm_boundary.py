"""The LLM package boundary (Implementation Plan wave 3, phase 3.2 D; LLM Tools §13).

Every LLM is reached through ``sajha.ai.llm``: provider and model specifics live only inside
``sajha/ai/llm/``. Outside it, code may import the public API (``sajha.ai.llm`` and its public
submodules ``canonical``, ``errors``, ``settings``, ``secrets``), never a vendor SDK, a provider
module or another private module, never construct a provider or model class itself, and never
use the pre-canonical types. Extension examples (custom providers and models) may also use the
provider SPI, ``sajha.ai.llm.spi``. A second set of tests checks the contract: every registered
provider implements the abstract LLMProvider and its models the abstract LLMModel.
"""

import ast
import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAJHA = ROOT / "sajha"
PACKAGE = SAJHA / "ai" / "llm"

PUBLIC_MODULES = {"sajha.ai.llm", "sajha.ai.llm.canonical", "sajha.ai.llm.errors", "sajha.ai.llm.settings",
                  "sajha.ai.llm.secrets"}
SPI = "sajha.ai.llm.spi"
EXTENSION_DIRS = (SAJHA / "examples" / "intelligence",)       # custom providers/models: may use the SPI

VENDOR_SDKS = ("openai", "anthropic", "google.genai", "google.generativeai", "google.ai.generativelanguage",
               "vertexai", "cohere", "mistralai", "ollama", "litellm", "langchain", "langchain_core",
               "langchain_openai", "langchain_anthropic", "llama_index", "groq", "together", "fireworks")
VENDOR_CLIENT_STRINGS = ("bedrock-runtime", "bedrock-agent-runtime", "bedrock")

OLD_TYPES = {"ChatRequest", "ChatResponse", "ToolSpec", "ToolCallPart", "ToolResultPart", "TextPart", "ImagePart",
             "TextDelta", "ToolCallDelta", "UsageEvent", "StreamEvent", "Done", "EmbeddingResult", "Part",
             "LLMResponse", "LegacyModelInfo"}


def _outside_files():
    for p in sorted(SAJHA.rglob("*.py")):
        if PACKAGE in p.parents:
            continue
        yield p


def _is_extension(p: Path) -> bool:
    return any(d in p.parents for d in EXTENSION_DIRS)


def _in_llm(mod: str) -> bool:
    return mod == "sajha.ai.llm" or mod.startswith("sajha.ai.llm.")


def _vendor(mod: str) -> bool:
    return any(mod == v or mod.startswith(v + ".") for v in VENDOR_SDKS)


def _llm_module_allowed(mod: str, extension: bool) -> bool:
    if mod in PUBLIC_MODULES:
        return True
    return extension and (mod == SPI)


def _resolve_from(node: ast.ImportFrom, p: Path) -> str:
    if not node.level:
        return node.module or ""
    pkg = list(p.relative_to(ROOT).with_suffix("").parts[:-1])
    base = pkg[:len(pkg) - node.level + 1]
    return ".".join(base + ([node.module] if node.module else []))


def _llm_class_names():
    """Names of every provider and model class defined in the package (and the factory/proxy)."""
    import sajha.ai.llm  # noqa: F401
    from sajha.ai.llm import registry
    from sajha.ai.llm.base import LLMModel, LLMProvider
    from sajha.ai.llm.legacy import LegacyLLMProvider
    registry.ensure_builtins()
    import sajha.ai.llm.spi  # noqa: F401  (adapter, legacy, openai_compat)

    names = set()

    def walk(cls):
        for sub in cls.__subclasses__():
            if _in_llm(sub.__module__):
                names.add(sub.__name__)
            walk(sub)
    for root in (LLMModel, LLMProvider, LegacyLLMProvider):
        walk(root)
    return names | {"LLMFactory", "Governor"}


def _violations():
    classes = _llm_class_names()
    out = []
    for p in _outside_files():
        rel = p.relative_to(ROOT)
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), str(p))
        except SyntaxError as e:          # pragma: no cover
            out.append(f"{rel}: does not parse ({e})")
            continue
        ext = _is_extension(p)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if _vendor(a.name):
                        out.append(f"{rel}:{node.lineno}: imports the vendor SDK '{a.name}'")
                    elif _in_llm(a.name) and not _llm_module_allowed(a.name, ext):
                        out.append(f"{rel}:{node.lineno}: imports the private module '{a.name}'")
                    elif a.name in ("sajha.ai.gateway", "sajha.ai.providers"):
                        out.append(f"{rel}:{node.lineno}: imports the retired module '{a.name}'")
            elif isinstance(node, ast.ImportFrom):
                mod = _resolve_from(node, p)
                if _vendor(mod):
                    out.append(f"{rel}:{node.lineno}: imports from the vendor SDK '{mod}'")
                    continue
                if mod in ("sajha.ai.gateway", "sajha.ai.providers") or (
                        mod == "sajha.ai" and any(a.name in ("gateway", "providers") for a in node.names)):
                    out.append(f"{rel}:{node.lineno}: imports a retired module ({mod})")
                    continue
                if _in_llm(mod):
                    if not _llm_module_allowed(mod, ext):
                        out.append(f"{rel}:{node.lineno}: imports from the private module '{mod}'")
                    if mod == "sajha.ai.llm":
                        for a in node.names:
                            sub = f"sajha.ai.llm.{a.name}"
                            if a.name not in __import__("sajha.ai.llm", fromlist=["__all__"]).__all__ \
                                    and not _llm_module_allowed(sub, ext):
                                out.append(f"{rel}:{node.lineno}: imports '{a.name}', which is not in the public "
                                           f"API of sajha.ai.llm")
                    for a in node.names:
                        if a.name in OLD_TYPES:
                            out.append(f"{rel}:{node.lineno}: uses the pre-canonical type '{a.name}'")
            elif isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                if name in classes:
                    out.append(f"{rel}:{node.lineno}: constructs '{name}' directly (use llm_factory().model())")
                if name in ("import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str):
                    m = node.args[0].value
                    if _vendor(m) or (_in_llm(m) and not _llm_module_allowed(m, ext)):
                        out.append(f"{rel}:{node.lineno}: imports '{m}' dynamically")
                if name == "client" and node.args and isinstance(node.args[0], ast.Constant) \
                        and node.args[0].value in VENDOR_CLIENT_STRINGS:
                    out.append(f"{rel}:{node.lineno}: opens a '{node.args[0].value}' client (LLM vendor API)")
    return out


def test_nothing_outside_the_package_reaches_past_the_public_llm_api():
    v = _violations()
    assert not v, "LLM package boundary violations:\n  " + "\n  ".join(v)


def test_the_retired_modules_are_gone():
    assert not (SAJHA / "ai" / "gateway.py").exists()
    assert not (SAJHA / "ai" / "providers").exists()


def test_the_public_api_is_the_factory_the_abstract_classes_the_canonical_types_and_the_errors():
    import sajha.ai.llm as llm
    exported = set(llm.__all__)
    for name in ("llm_factory", "LLMFactory", "GovernedModel", "LLMModel", "LLMProvider", "ChatMessage",
                 "ChatCompletionRequest", "ChatCompletion", "ChatCompletionChunk", "ToolDefinition", "ToolCall",
                 "EmbeddingsRequest", "EmbeddingsResponse", "SajhaRequest", "ResponseSajha", "RequestContext",
                 "LLMError", "NoModelAvailable", "BudgetExceeded", "PolicyDenied", "UnsupportedFeature"):
        assert name in exported, name
    assert not exported & OLD_TYPES
    assert not exported & {"registry", "register_provider", "register_model", "ChatModel", "EmbeddingModel",
                           "ProviderBase", "AISettings"}
    for name in exported:
        assert hasattr(llm, name), name


# ── the contract: providers implement LLMProvider, their models LLMModel ──

def _providers():
    from sajha.ai.llm import registry
    return sorted(registry.registered_providers().items())


@pytest.mark.parametrize("name,cls", _providers(), ids=[n for n, _ in _providers()])
def test_every_registered_provider_implements_the_abstract_classes(name, cls):
    from sajha.ai.llm.base import LLMModel, LLMProvider
    assert issubclass(cls, LLMProvider) and not inspect.isabstract(cls), name
    for attr in ("chat_model_class", "embedding_model_class"):
        mc = getattr(cls, attr, None)
        if mc is not None:
            assert issubclass(mc, LLMModel) and not inspect.isabstract(mc), f"{name}.{attr}"


def test_models_handed_out_are_llm_models_and_the_proxy_hides_the_provider():
    from sajha.ai.llm import ChatMessage, GovernedModel, LLMModel, build_llm_factory
    f = build_llm_factory({"gateway": {"load_entry_points": False, "use_db_providers": False}}, environ={})
    p = f.provider("mock")
    assert isinstance(p.chat_model(), LLMModel) and isinstance(p.embedding_model(), LLMModel)
    m = f.model("default")
    assert isinstance(m, GovernedModel) and isinstance(m, LLMModel) and not inspect.isabstract(GovernedModel)
    c = m.chat_completions_create(messages=[ChatMessage.user("hello")])
    assert c.sajha.provider == "mock" and c.text
    e = f.model("embedding").embeddings_create(input=["a", "b"])
    assert len(e.vectors) == 2
    assert f.model("embedding").info().kind == "embedding"
    with pytest.raises(Exception):
        p.embedding_model().chat_completions_create(messages=[ChatMessage.user("x")])
    with pytest.raises(Exception):
        p.chat_model().embeddings_create(input=["x"])


def test_a_provider_that_skips_the_abstract_methods_is_refused():
    from sajha.ai.llm import ConfigurationError, LLMProvider
    from sajha.ai.llm.spi import register_provider

    from pydantic import BaseModel

    class Half(LLMProvider):
        name = "half"
        config_model = BaseModel

    with pytest.raises(ConfigurationError, match="abstract"):
        register_provider(Half)
