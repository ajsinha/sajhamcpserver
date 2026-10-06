"""
SAJHA Intelligence Layer — the provider and model registry.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

One registry, fed three ways:

1. ``@register_provider`` on a class you ship or import at startup;
2. a class path in application.yml (``ai.providers[].class: pkg.module:Class``);
3. a pip plug-in exposing an entry point in the ``sajha.llm_providers`` group.

All three validate the class (an LLMProvider subclass that declares ``name`` and a pydantic
``config_model``) and fail at startup with a clear message. ``@register_model`` injects one
model class into an existing provider (a fine-tune, a custom route).
"""

from __future__ import annotations

import importlib
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel

from sajha.ai.llm.errors import ConfigurationError

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "sajha.llm_providers"

_lock = threading.RLock()
_providers: Dict[str, type] = {}
_models: Dict[Tuple[str, str], type] = {}
_builtins_loaded = False


def _validate_provider(cls) -> None:
    from sajha.ai.llm.provider import LLMProvider
    if not isinstance(cls, type) or not issubclass(cls, LLMProvider):
        raise ConfigurationError(f"{cls!r} is not a subclass of sajha.ai.llm.LLMProvider")
    if not getattr(cls, "name", ""):
        raise ConfigurationError(f"{cls.__name__} must declare a class attribute 'name'")
    cm = getattr(cls, "config_model", None)
    if not (isinstance(cm, type) and issubclass(cm, BaseModel)):
        raise ConfigurationError(f"{cls.__name__}.config_model must be a pydantic BaseModel subclass")


def register_provider(cls=None, *, name: Optional[str] = None, replace: bool = True):
    """Decorator (or call) registering an LLMProvider subclass under ``cls.name``."""
    def deco(c):
        _validate_provider(c)
        key = name or c.name
        with _lock:
            if key in _providers and _providers[key] is not c and not replace:
                raise ConfigurationError(f"provider '{key}' is already registered")
            _providers[key] = c
        return c
    return deco(cls) if cls is not None else deco


def unregister_provider(name: str) -> None:
    with _lock:
        _providers.pop(name, None)


def register_model(provider: str, model_id: str):
    """Decorator registering a ChatModel/EmbeddingModel subclass for one provider/model id."""
    def deco(c):
        from sajha.ai.llm.model import ChatModel, EmbeddingModel
        if not (isinstance(c, type) and issubclass(c, (ChatModel, EmbeddingModel))):
            raise ConfigurationError(f"{c!r} must subclass ChatModel or EmbeddingModel")
        with _lock:
            _models[(provider, model_id)] = c
        return c
    return deco


def unregister_model(provider: str, model_id: str) -> None:
    with _lock:
        _models.pop((provider, model_id), None)


def model_class(provider: str, model_id: str) -> Optional[type]:
    return _models.get((provider, model_id))


def registered_models_for(provider: str) -> Dict[str, type]:
    return {mid: c for (p, mid), c in _models.items() if p == provider}


def provider_class(name: str) -> Optional[type]:
    ensure_builtins()
    return _providers.get(name)


def registered_providers() -> Dict[str, type]:
    ensure_builtins()
    return dict(_providers)


def load_class(path: str) -> type:
    """'pkg.module:Class' or 'pkg.module.Class' -> the class, validated."""
    mod, sep, attr = path.partition(":")
    if not sep:
        mod, _, attr = path.rpartition(".")
    try:
        cls = getattr(importlib.import_module(mod), attr)
    except Exception as e:
        raise ConfigurationError(f"cannot load provider class '{path}': {e}") from None
    _validate_provider(cls)
    return cls


def load_entry_points(group: str = ENTRY_POINT_GROUP) -> List[str]:
    """Register every provider class exposed by installed packages in ``group``."""
    loaded = []
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group=group)
    except Exception as e:
        logger.debug(f"entry points unavailable: {e}")
        return loaded
    for ep in eps:
        try:
            cls = ep.load()
            register_provider(cls, name=ep.name if ep.name else None)
            loaded.append(ep.name or cls.name)
        except Exception as e:
            logger.error(f"LLM provider plug-in '{ep.name}' failed to load: {e}")
    return loaded


def ensure_builtins() -> None:
    global _builtins_loaded
    if _builtins_loaded:
        return
    with _lock:
        if _builtins_loaded:
            return
        _builtins_loaded = True
        importlib.import_module("sajha.ai.llm.mock")
        importlib.import_module("sajha.ai.llm.providers")
