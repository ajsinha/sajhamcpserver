"""
SAJHA MCP Server — the planner ``when`` expression language and runtime templates.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Reference: docs/architecture/Planner Reference.md §4 (templates) and §8 (expressions).

An expression is parsed once, at load, into a small tree; evaluating it reads state and calls a
fixed set of pure functions (``len``, ``exists``, ``empty``, ``lower``, ``number``, ``matches``,
``visits``, ``offered``). There is no arithmetic, no assignment, no attribute access beyond data
and no way to run code, call a tool or call a model. Booleans are strict (no truthiness); a
reference that walks off the data yields ``null``; a JSONPath (``$...``, the subset of
sajha/quality/jsonpath.py) always yields the list of every match.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

MAX_EXPR_CHARS = 1000
MAX_DEPTH = 64
FUNCTIONS = {"len": 1, "exists": 1, "empty": 1, "lower": 1, "number": 1, "matches": 2, "visits": 1, "offered": 1}
KEYWORDS = {"and", "or", "not", "in", "true", "false", "null"}
COMPARISONS = ("==", "!=", "<=", ">=", "<", ">", "in", "not in")


class ExprSyntaxError(ValueError):
    """P040 (syntax, JSONPath subset) — ``column`` is 1-based."""

    def __init__(self, message: str, column: int = 0):
        super().__init__(message)
        self.column = column


class ExprNameError(ValueError):
    """P041: an unknown root, function or arity, or a ``visits`` stage id that is not a stage."""


class ExprTypeError(ValueError):
    """P042 at load (literal-only type errors); at run time a type error makes the condition false."""


# ── lexer ─────────────────────────────────────────────────────────

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<str>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<op>==|!=|<=|>=|<|>|\(|\)|\[|\]|,|\.)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<dollar>\$)
""", re.VERBOSE)


def _unquote(raw: str) -> str:
    body = raw[1:-1]
    return re.sub(r"\\(.)", lambda m: m.group(1), body)


def _scan_jsonpath(text: str, i: int) -> int:
    """End index of the JSONPath starting at ``text[i] == '$'``."""
    j = i + 1
    n = len(text)
    while j < n:
        if text.startswith("..", j):
            j += 2
            if j < n and text[j] == "*":
                j += 1
                continue
            if j < n and text[j] == "[":
                continue
            m = re.compile(r"[A-Za-z_][\w\-]*").match(text, j)
            if not m:
                raise ExprSyntaxError("expected a name after '..' in a JSONPath", j + 1)
            j = m.end()
        elif text[j] == ".":
            j += 1
            if j < n and text[j] == "*":
                j += 1
                continue
            m = re.compile(r"[A-Za-z_][\w\-]*").match(text, j)
            if not m:
                raise ExprSyntaxError("expected a name after '.' in a JSONPath", j + 1)
            j = m.end()
        elif text[j] == "[":
            k = j + 1
            quote = None
            while k < n:
                c = text[k]
                if quote:
                    if c == "\\":
                        k += 2
                        continue
                    if c == quote:
                        quote = None
                elif c in "'\"":
                    quote = c
                elif c == "]":
                    break
                k += 1
            if k >= n:
                raise ExprSyntaxError("unclosed '[' in a JSONPath", j + 1)
            inner = text[j + 1:k].strip()
            if inner.startswith("?") or ":" in inner and not inner[:1] in "'\"":
                raise ExprSyntaxError("JSONPath filters and slices are not supported", j + 1)
            j = k + 1
        else:
            break
    return j


def tokenize(text: str) -> List[Tuple[str, Any, int]]:
    out: List[Tuple[str, Any, int]] = []
    i = 0
    while i < len(text):
        if text[i] == "$":
            j = _scan_jsonpath(text, i)
            path = text[i:j]
            try:
                from sajha.quality.jsonpath import parse as jp_parse
                jp_parse(path)
            except Exception as e:
                raise ExprSyntaxError(f"JSONPath {path!r}: {e}", i + 1)
            out.append(("jp", path, i + 1))
            i = j
            continue
        m = _TOKEN.match(text, i)
        if not m:
            raise ExprSyntaxError(f"unexpected character {text[i]!r}", i + 1)
        kind = m.lastgroup
        val = m.group(kind)
        if kind == "num":
            # a '-' is only a sign: there is no subtraction
            out.append(("num", float(val) if any(c in val for c in ".eE") else int(val), i + 1))
        elif kind == "str":
            out.append(("str", _unquote(val), i + 1))
        elif kind == "op":
            out.append(("op", val, i + 1))
        elif kind == "name":
            out.append(("kw" if val in KEYWORDS else "name", val, i + 1))
        i = m.end()
    out.append(("end", None, len(text) + 1))
    return out


# ── parser ────────────────────────────────────────────────────────

class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.toks = tokenize(text)
        self.i = 0
        self.depth = 0

    def peek(self, k: int = 0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def take(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def accept(self, kind: str, val: Any = None) -> bool:
        t = self.peek()
        if t[0] == kind and (val is None or t[1] == val):
            self.i += 1
            return True
        return False

    def expect(self, kind: str, val: Any = None):
        t = self.peek()
        if t[0] == kind and (val is None or t[1] == val):
            self.i += 1
            return t
        want = val if val is not None else kind
        got = t[1] if t[1] is not None else "the end"
        raise ExprSyntaxError(f"expected {want!r}, found {got!r}", t[2])

    def _deeper(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExprSyntaxError(f"the expression is nested more than {MAX_DEPTH} deep", self.peek()[2])

    def parse(self):
        node = self.or_expr()
        t = self.peek()
        if t[0] != "end":
            raise ExprSyntaxError(f"unexpected {t[1]!r}", t[2])
        return node

    def or_expr(self):
        self._deeper()
        node = self.and_expr()
        while self.accept("kw", "or"):
            node = ("or", node, self.and_expr())
        self.depth -= 1
        return node

    def and_expr(self):
        node = self.not_expr()
        while self.accept("kw", "and"):
            node = ("and", node, self.not_expr())
        return node

    def not_expr(self):
        if self.peek()[0] == "kw" and self.peek()[1] == "not" and not (self.peek(1)[0] == "kw" and self.peek(1)[1] == "in"):
            self.take()
            self._deeper()
            node = ("not", self.not_expr())
            self.depth -= 1
            return node
        return self.comparison()

    def comparison(self):
        left = self.operand()
        t = self.peek()
        op = None
        if t[0] == "op" and t[1] in ("==", "!=", "<=", ">=", "<", ">"):
            self.take()
            op = t[1]
        elif t[0] == "kw" and t[1] == "in":
            self.take()
            op = "in"
        elif t[0] == "kw" and t[1] == "not" and self.peek(1)[0] == "kw" and self.peek(1)[1] == "in":
            self.take()
            self.take()
            op = "not in"
        if op is None:
            return left
        right = self.operand()
        nt = self.peek()
        if (nt[0] == "op" and nt[1] in ("==", "!=", "<=", ">=", "<", ">")) or (nt[0] == "kw" and nt[1] == "in"):
            raise ExprSyntaxError("comparisons do not chain (write a < b and b < c)", nt[2])
        return ("cmp", op, left, right)

    def operand(self):
        t = self.peek()
        if t[0] == "num":
            self.take()
            return ("lit", t[1])
        if t[0] == "str":
            self.take()
            return ("lit", t[1])
        if t[0] == "kw" and t[1] in ("true", "false", "null"):
            self.take()
            return ("lit", {"true": True, "false": False, "null": None}[t[1]])
        if t[0] == "jp":
            self.take()
            return ("jp", t[1])
        if t[0] == "op" and t[1] == "(":
            self.take()
            self._deeper()
            node = self.or_expr()
            self.depth -= 1
            self.expect("op", ")")
            return node
        if t[0] == "op" and t[1] == "[":
            self.take()
            items = []
            if not self.accept("op", "]"):
                items.append(self.or_expr())
                while self.accept("op", ","):
                    items.append(self.or_expr())
                self.expect("op", "]")
            return ("list", items)
        if t[0] == "name":
            if self.peek(1)[0] == "op" and self.peek(1)[1] == "(":
                name = self.take()[1]
                self.take()
                args = []
                if not self.accept("op", ")"):
                    args.append(self.or_expr())
                    while self.accept("op", ","):
                        args.append(self.or_expr())
                    self.expect("op", ")")
                return ("call", name, args, t[2])
            return self.reference()
        raise ExprSyntaxError(f"unexpected {t[1] if t[1] is not None else 'end of expression'!r}", t[2])

    def reference(self):
        t = self.expect("name")
        root = t[1]
        steps: List[Any] = []
        if root == "state" and self.peek()[0] == "op" and self.peek()[1] == ".":
            self.take()
            root = self.expect("name")[1]
        while True:
            if self.accept("op", "."):
                nt = self.peek()
                if nt[0] in ("name", "kw"):
                    self.take()
                    steps.append(nt[1])
                else:
                    raise ExprSyntaxError("expected a name after '.'", nt[2])
            elif self.peek()[0] == "op" and self.peek()[1] == "[":
                self.take()
                nt = self.take()
                if nt[0] == "num" and isinstance(nt[1], int):
                    steps.append(nt[1])
                elif nt[0] == "str":
                    steps.append(nt[1])
                else:
                    raise ExprSyntaxError("an index is an integer or a quoted key", nt[2])
                self.expect("op", "]")
            else:
                break
        return ("ref", root, steps, t[2])


class Expression:
    """A parsed ``when`` expression. ``roots`` are the slot names it reads; ``stages`` the
    ``visits()`` stage ids (checked against the graph by the loader)."""

    def __init__(self, text: str, tree: Any):
        self.text = text
        self.tree = tree
        self.roots: Set[str] = set()
        self.stages: Set[str] = set()
        self.patterns: Dict[str, Any] = {}
        _walk(tree, self)

    def __repr__(self):
        return f"Expression({self.text!r})"


def _walk(node, ex: Expression) -> None:
    kind = node[0]
    if kind == "ref":
        ex.roots.add(node[1])
    elif kind == "call":
        for a in node[2]:
            _walk(a, ex)
    elif kind == "list":
        for a in node[1]:
            _walk(a, ex)
    elif kind == "not":
        _walk(node[1], ex)
    elif kind in ("and", "or"):
        _walk(node[1], ex)
        _walk(node[2], ex)
    elif kind == "cmp":
        _walk(node[2], ex)
        _walk(node[3], ex)


def _literal_type(node) -> Optional[str]:
    if node[0] != "lit":
        return "list" if node[0] == "list" else None
    v = node[1]
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    return "string"


def compile_expression(text: Any, roots: Set[str], stage_ids: Optional[Set[str]] = None) -> Expression:
    """Parse and statically check ``text``. Raises ExprSyntaxError (P040), ExprNameError (P041) or
    ExprTypeError (P042)."""
    if not isinstance(text, str) or not text.strip():
        raise ExprSyntaxError("an expression must be a non-empty string", 1)
    if len(text) > MAX_EXPR_CHARS:
        raise ExprSyntaxError(f"the expression is longer than {MAX_EXPR_CHARS} characters", MAX_EXPR_CHARS)
    tree = _Parser(text).parse()
    ex = Expression(text, tree)
    _check(tree, ex, roots, stage_ids)
    return ex


def _check(node, ex: Expression, roots: Set[str], stage_ids: Optional[Set[str]]) -> None:
    kind = node[0]
    if kind == "ref":
        if node[1] in FUNCTIONS:
            raise ExprNameError(f"unknown name {node[1]!r} (a function needs parentheses)")
        if node[1] not in roots:
            raise ExprNameError(f"unknown name {node[1]!r}")
    elif kind == "call":
        name, args = node[1], node[2]
        if name not in FUNCTIONS:
            raise ExprNameError(f"unknown function {name!r}")
        if len(args) != FUNCTIONS[name]:
            raise ExprNameError(f"{name}() takes {FUNCTIONS[name]} argument(s), got {len(args)}")
        for a in args:
            _check(a, ex, roots, stage_ids)
        if name == "len" and _literal_type(args[0]) in ("number", "boolean"):
            raise ExprTypeError(f"len cannot take a {_literal_type(args[0])}")
        if name == "lower" and _literal_type(args[0]) in ("number", "boolean", "null", "list"):
            raise ExprTypeError(f"lower cannot take a {_literal_type(args[0])}")
        if name == "matches":
            if args[1][0] != "lit" or not isinstance(args[1][1], str):
                raise ExprTypeError("matches() needs a string literal pattern")
            pat = args[1][1]
            if len(pat) > MAX_EXPR_CHARS:
                raise ExprTypeError("the pattern is longer than 1000 characters")
            try:
                ex.patterns[pat] = re.compile(pat)
            except re.error as e:
                raise ExprTypeError(f"matches(): the pattern does not compile: {e}")
        if name == "visits":
            if args[0][0] != "lit" or not isinstance(args[0][1], str):
                raise ExprTypeError("visits() needs a stage id as a string literal")
            ex.stages.add(args[0][1])
            if stage_ids is not None and args[0][1] not in stage_ids:
                raise ExprNameError(f"visits(): unknown stage {args[0][1]!r}")
    elif kind == "list":
        for a in node[1]:
            _check(a, ex, roots, stage_ids)
    elif kind == "not":
        _check(node[1], ex, roots, stage_ids)
        if _literal_type(node[1]) not in (None, "boolean"):
            raise ExprTypeError(f"not cannot take a {_literal_type(node[1])}")
    elif kind in ("and", "or"):
        for side in (node[1], node[2]):
            _check(side, ex, roots, stage_ids)
            if _literal_type(side) not in (None, "boolean"):
                raise ExprTypeError(f"{kind} cannot take a {_literal_type(side)}")
    elif kind == "cmp":
        op, a, b = node[1], node[2], node[3]
        _check(a, ex, roots, stage_ids)
        _check(b, ex, roots, stage_ids)
        ta, tb = _literal_type(a), _literal_type(b)
        if op in ("<", "<=", ">", ">=") and ta and tb and not (ta == tb and ta in ("number", "string")):
            raise ExprTypeError(f"{op} cannot compare {ta} and {tb}")


# ── evaluation ───────────────────────────────────────────────────

class Env:
    """What an expression can see: ``lookup(root)`` for slots, the whole state for JSONPath,
    ``visits(stage)`` and ``offered(tool)``."""

    def __init__(self, lookup: Callable[[str], Any], whole: Callable[[], Any],
                 visits: Callable[[str], int] = lambda s: 0, offered: Callable[[str], bool] = lambda t: False,
                 max_input_chars: int = 20000):
        self.lookup = lookup
        self.whole = whole
        self.visits = visits
        self.offered = offered
        self.max_input_chars = max_input_chars


def _type_name(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def deep_equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(deep_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(deep_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def walk_ref(value: Any, steps: List[Any]) -> Any:
    cur = value
    for s in steps:
        if isinstance(s, int) and not isinstance(s, bool):
            if isinstance(cur, list) and -len(cur) <= s < len(cur):
                cur = cur[s]
            else:
                return None
        elif isinstance(cur, dict):
            cur = cur.get(s)
        else:
            return None
    return cur


def parse_number(v: Any) -> float:
    if isinstance(v, bool):
        raise ExprTypeError("number() cannot take a boolean")
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        raw = v.replace(",", "").strip()
        try:
            return float(raw) if any(c in raw for c in ".eE") else int(raw)
        except ValueError:
            raise ExprTypeError(f"number(): {v!r} is not a number")
    raise ExprTypeError(f"number() cannot take a {_type_name(v)}")


def evaluate(ex: Any, env: Env) -> Any:
    node = ex.tree if isinstance(ex, Expression) else ex
    pats = ex.patterns if isinstance(ex, Expression) else {}
    return _ev(node, env, pats)


def _bool(v: Any, what: str) -> bool:
    if not isinstance(v, bool):
        raise ExprTypeError(f"{what} needs a boolean, got {_type_name(v)}")
    return v


def _ev(node, env: Env, pats) -> Any:
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "list":
        return [_ev(a, env, pats) for a in node[1]]
    if kind == "ref":
        return walk_ref(env.lookup(node[1]), node[2])
    if kind == "jp":
        from sajha.quality.jsonpath import find
        return find(env.whole(), node[1])
    if kind == "not":
        return not _bool(_ev(node[1], env, pats), "not")
    if kind == "and":
        return _bool(_ev(node[1], env, pats), "and") and _bool(_ev(node[2], env, pats), "and")
    if kind == "or":
        return _bool(_ev(node[1], env, pats), "or") or _bool(_ev(node[2], env, pats), "or")
    if kind == "call":
        name, args = node[1], node[2]
        if name == "exists":
            v = _ev(args[0], env, pats)
            return bool(v) if args[0][0] == "jp" else v is not None
        v = _ev(args[0], env, pats)
        if name == "len":
            if v is None:
                return 0
            if isinstance(v, (str, list, dict)):
                return len(v)
            raise ExprTypeError(f"len cannot take a {_type_name(v)}")
        if name == "empty":
            return v is None or v == "" or v == [] or v == {}
        if name == "lower":
            if not isinstance(v, str):
                raise ExprTypeError(f"lower cannot take a {_type_name(v)}")
            return v.lower()
        if name == "number":
            return parse_number(v)
        if name == "matches":
            if not isinstance(v, str):
                raise ExprTypeError(f"matches cannot take a {_type_name(v)}")
            pat = args[1][1]
            rx = pats.get(pat) or re.compile(pat)
            return rx.search(v[: env.max_input_chars]) is not None
        if name == "visits":
            return env.visits(args[0][1])
        if name == "offered":
            if not isinstance(v, str):
                raise ExprTypeError(f"offered cannot take a {_type_name(v)}")
            return bool(env.offered(v))
        raise ExprNameError(f"unknown function {name!r}")
    if kind == "cmp":
        op, a, b = node[1], _ev(node[2], env, pats), _ev(node[3], env, pats)
        if op == "==":
            return deep_equal(a, b)
        if op == "!=":
            return not deep_equal(a, b)
        if op in ("in", "not in"):
            if isinstance(b, list):
                hit = any(deep_equal(a, x) for x in b)
            elif isinstance(b, str) and isinstance(a, str):
                hit = a in b
            elif isinstance(b, dict) and isinstance(a, str):
                hit = a in b
            else:
                raise ExprTypeError(f"{op} cannot test {_type_name(a)} in {_type_name(b)}")
            return hit if op == "in" else not hit
        num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
        if not ((num(a) and num(b)) or (isinstance(a, str) and isinstance(b, str))):
            raise ExprTypeError(f"{op} cannot compare {_type_name(a)} and {_type_name(b)}")
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    raise ExprSyntaxError(f"unknown node {kind}")


def evaluate_bool(ex: Expression, env: Env) -> bool:
    v = evaluate(ex, env)
    if not isinstance(v, bool):
        raise ExprTypeError(f"the condition evaluated to {_type_name(v)}, not a boolean")
    return v


# ── templates (§4.1) and settings references (§4.2) ───────────────

PLACEHOLDER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
SETTINGS_REF = re.compile(r"^\{\{\s*settings((?:[.\[].*)?)\s*\}\}$")


def template_refs(text: str) -> List[Tuple[str, Any]]:
    """[(raw, ('ref', root, steps, col))] for each placeholder; raises ExprSyntaxError."""
    out = []
    for m in PLACEHOLDER.finditer(text or ""):
        raw = m.group(1)
        node = _Parser(raw).reference_only()
        out.append((raw, node))
    return out


def _reference_only(self):
    node = self.reference()
    t = self.peek()
    if t[0] != "end":
        raise ExprSyntaxError("a template holds a reference only (no expressions)", t[2])
    return node


_Parser.reference_only = _reference_only


def check_template(text: Any, roots: Set[str]) -> List[str]:
    """Unknown roots named by ``text``'s placeholders (P043); raises ExprSyntaxError."""
    if not isinstance(text, str):
        return []
    bad = []
    for _raw, node in template_refs(text):
        if node[1] not in roots:
            bad.append(node[1])
    return bad


def render_value_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, str):
        return v
    text = json.dumps(v, default=str, ensure_ascii=False, separators=(",", ":"))
    return text[:2000]


def render(template: Any, lookup: Callable[[str], Any], keep_type: bool = False) -> Any:
    """Fill ``{{ ref }}`` placeholders. With ``keep_type``, a string that is exactly one placeholder
    yields the referenced value itself."""
    if not isinstance(template, str):
        return template
    if keep_type:
        m = PLACEHOLDER.fullmatch(template.strip())
        if m:
            node = _Parser(m.group(1)).reference_only()
            return walk_ref(lookup(node[1]), node[2])

    def sub(m):
        try:
            node = _Parser(m.group(1)).reference_only()
        except ExprSyntaxError:
            return m.group(0)
        return render_value_text(walk_ref(lookup(node[1]), node[2]))
    return PLACEHOLDER.sub(sub, template)


def render_deep(value: Any, lookup: Callable[[str], Any]) -> Any:
    """``call.arguments``: whole-value templates keep the type, recursively."""
    if isinstance(value, dict):
        return {k: render_deep(v, lookup) for k, v in value.items()}
    if isinstance(value, list):
        return [render_deep(v, lookup) for v in value]
    return render(value, lookup, keep_type=True)


class SettingsRefMissing(ValueError):
    """P044: a settings reference matched nothing."""


def resolve_settings_refs(value: Any, settings: Dict[str, Any]) -> Any:
    """Replace every string that is exactly ``{{settings.<path>}}`` (§4.2), recursively."""
    if isinstance(value, dict):
        return {k: resolve_settings_refs(v, settings) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_settings_refs(v, settings) for v in value]
    if isinstance(value, str):
        m = SETTINGS_REF.match(value.strip())
        if m:
            from sajha.quality.jsonpath import find
            path = "$" + (m.group(1) or "")
            many = "[*]" in path or ".." in path or ".*" in path
            hits = find(settings, path)
            if many:
                return hits
            if not hits:
                raise SettingsRefMissing(f"{value} matches nothing")
            return hits[0]
    return value
