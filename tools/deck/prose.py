"""
Small text helpers for the deck modules: lists in prose, wrapped lines for the
monospaced panels, and inline code without its backticks.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import textwrap
from typing import Any, Iterable


def listing(items: Iterable[Any], last: str = "and") -> str:
    """``a, b and c``."""
    xs = [str(i) for i in items]
    if len(xs) < 2:
        return "".join(xs)
    return f"{', '.join(xs[:-1])} {last} {xs[-1]}"


def wrap(text: str, width: int = 54, indent: str = "  ") -> list[str]:
    """Lines for a monospaced panel."""
    return textwrap.wrap(text, width, subsequent_indent=indent) or [""]


def plain(text: str) -> str:
    return text.replace("`", "")


def js(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True)
