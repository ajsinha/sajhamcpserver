# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Turn qlrisk results (dataclasses, enums, numpy, dates, tuple-keyed dicts) into plain JSON values."""

from __future__ import annotations

import dataclasses
import math
from datetime import date, datetime
from enum import Enum
from typing import Any

import numpy as np


def key_str(key: Any) -> str:
    if isinstance(key, tuple):
        return "/".join(key_str(k) for k in key)
    if isinstance(key, Enum):
        return str(key.value)
    if isinstance(key, (date, datetime)):
        return key.isoformat()
    if isinstance(key, float) and key.is_integer():
        return str(key)
    return str(key)


def to_jsonable(obj: Any, _depth: int = 0) -> Any:
    if _depth > 25:
        return str(obj)
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, (int, np.integer)) and not isinstance(obj, bool):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist(), _depth + 1)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name), _depth + 1) for f in dataclasses.fields(obj)
                if not callable(getattr(obj, f.name))}
    if isinstance(obj, dict):
        return {key_str(k): to_jsonable(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_jsonable(v, _depth + 1) for v in obj]
    if hasattr(obj, "sort_key") and hasattr(obj, "field"):        # RiskFactorKey
        return str(obj)
    return str(obj)


def rounded(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)
