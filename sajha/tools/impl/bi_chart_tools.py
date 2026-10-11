"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Business Intelligence: ``bi_chart`` and ``bi_load_tool_result`` (tool folder ``bi``;
docs/architecture/Business Intelligence.md §4 to §6).

``bi_chart`` turns rows into three things: a chart spec (a small subset of Vega-Lite: ``mark`` or
``layer``, ``encoding`` with ``x``, ``y``, ``y2``, ``color`` and ``xOffset``, ``data.values``, and
``usermeta.kind``), an SVG drawn here in pure Python from that spec, and an MCP Apps view
(``sajha/core/mcp_app_views/bi_chart.html``) that redraws the SVG in the host's theme. Every value
derived for a kind (a waterfall's start and end, a pareto's cumulative share, stacked areas) is
computed into ``data.values``, so the spec needs no Vega-Lite transforms. Text from the data reaches
the SVG only XML-escaped, as element text, never as markup or an attribute that could run anything.

Rows come from ``data`` as a list of objects, from a ``bi_*`` tool called as the caller, or from one
read-only SELECT over the caller's loaded tool results (their scratch database).

``bi_load_tool_result`` calls a tool **as the caller** through ``execute_with_tracking`` (the caller's
tool access first, then policy, budgets, validation, cache and audit, exactly as for any call) and
loads the rows of its result into the caller's scratch database (``sajha/analytics/scratch.py``):
one DuckDB file per user, a time to live, row and size bounds, and the call's provenance.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sajha.tools.base_mcp_tool import BaseMCPTool

KINDS = ("line", "bar", "area", "scatter", "heatmap", "waterfall", "pareto")
MAX_ROWS = 5000
MAX_SERIES = 12
MAX_CATEGORIES = 200
VIEW_URI = "ui://sajha/bi-chart.html"
W, H = 720, 400
SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
# categorical palette (classes f0..f11 / k0..k11 in the SVG and the view)
PALETTE = ("#2a78d6", "#eb6834", "#2e9e6a", "#c6403a", "#8a5cc2", "#b8860b",
           "#d16ba5", "#5f7a8a", "#17a2b8", "#7f7f00", "#8c564b", "#4b5fd6")
HEAT_LO, HEAT_HI = (234, 242, 251), (31, 95, 168)
WATERFALL = {"increase": "#2e9e6a", "decrease": "#c6403a", "total": "#2a78d6"}
_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?)?$")
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


class ChartError(ValueError):
    """A chart that cannot be drawn from these rows and arguments (the message says why)."""


# ── small helpers ────────────────────────────────────────────────

def esc(value: Any) -> str:
    """Text for an SVG element or attribute: XML-escaped, characters XML forbids removed."""
    s = _XML_BAD.sub("", str(value))
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def _short(value: Any, n: int = 18) -> str:
    s = str(value)
    return s if len(s) <= n else s[: n - 1] + "…"


def _n(v: float) -> str:
    """A coordinate: at most two decimals, no trailing zeros (stable for golden files)."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(v, str):
        t = v.strip().replace(",", "")
        if not t:
            return None
        try:
            f = float(t)
        except ValueError:
            return None
        return None if math.isnan(f) or math.isinf(f) else f
    try:
        return _num(float(v))            # Decimal and friends
    except (TypeError, ValueError):
        return None


def fmt(v: float) -> str:
    """A compact number for an axis: 1.2k, 3.4M, 5B, 0.25."""
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")):
        if a >= div:
            return f"{v / div:.3g}{suf}"
    if v == int(v):
        return str(int(v))
    return f"{v:.3g}"


def fmt_full(v: float) -> str:
    """A number for a tooltip: grouped digits, up to four decimals."""
    if v == int(v) and abs(v) < 1e15:
        return f"{int(v):,}"
    return f"{v:,.4f}".rstrip("0").rstrip(".")


def nice_ticks(lo: float, hi: float, count: int = 5) -> List[float]:
    """Round tick values covering [lo, hi] (steps of 1, 2 or 5 times a power of ten)."""
    if lo == hi:
        if lo == 0:
            hi = 1.0
        else:
            pad = abs(lo) * 0.1
            lo, hi = lo - pad, hi + pad
    raw = (hi - lo) / max(1, count)
    mag = 10 ** math.floor(math.log10(raw))
    norm = raw / mag
    step = (1 if norm <= 1 else 2 if norm <= 2 else 5 if norm <= 5 else 10) * mag
    start, stop = math.floor(lo / step + 1e-9) * step, math.ceil(hi / step - 1e-9) * step
    k = int(round((stop - start) / step))
    return [float(f"{start + i * step:.12g}") for i in range(k + 1)]


def _is_date(v: Any) -> bool:
    return isinstance(v, str) and bool(_DATE.match(v.strip()))


def _epoch(v: str) -> float:
    s = v.strip().replace(" ", "T").replace("Z", "+00:00")
    if len(s) == 7:
        s += "-01"
    d = datetime.fromisoformat(s)
    if d.tzinfo is not None:
        d = d.replace(tzinfo=None) - (d.utcoffset() or (d - d))
    return (d - datetime(1970, 1, 1)).total_seconds()


# ── the spec ─────────────────────────────────────────────────────

def _x_type(kind: str, xs: Sequence[Any]) -> str:
    if kind in ("bar", "heatmap", "waterfall", "pareto"):
        return "nominal"
    vals = [v for v in xs if v is not None]
    if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
        return "quantitative"
    if vals and all(_is_date(v) for v in vals):
        return "temporal"
    return "ordinal"


def _field(rows: List[Dict[str, Any]], name: Optional[str], what: str, required: bool = True) -> Optional[str]:
    if not name:
        if required:
            raise ChartError(f"{what} is required")
        return None
    if not any(name in r for r in rows):
        cols = []
        for r in rows[:20]:
            cols += [k for k in r if k not in cols]
        raise ChartError(f"{what} {name!r} is not a column of the rows (columns: {', '.join(map(str, cols[:30])) or 'none'})")
    return name


def _label(v: Any) -> Any:
    """A category or x value as it goes into the spec: scalars kept, anything else as text."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return json.dumps(v, default=str) if isinstance(v, (dict, list)) else str(v)


def build_spec(rows: List[Dict[str, Any]], kind: str, x: str, y: str, series: Optional[str] = None,
               value: Optional[str] = None, title: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """``(spec, info)`` for ``rows``; ``info`` has ``rows`` (used), ``skipped``, ``combined``, ``series``.
    Raises :class:`ChartError` with the reason when the rows cannot make this chart."""
    if kind not in KINDS:
        raise ChartError(f"kind must be one of {', '.join(KINDS)}")
    if not isinstance(rows, list) or not rows:
        raise ChartError("no rows to chart")
    if len(rows) > MAX_ROWS:
        raise ChartError(f"{len(rows)} rows is more than {MAX_ROWS}; aggregate first")
    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        raise ChartError("the rows must be objects ({column: value})")
    x = _field(rows, x, "x")
    y = _field(rows, y, "y")
    if kind == "heatmap":
        value = _field(rows, value, "value (the column that colours each x, y cell)")
        series = None
    else:
        value = None
        series = _field(rows, series, "series", required=False)
        if series is not None and kind in ("waterfall", "pareto"):
            raise ChartError(f"a {kind} chart has one series; leave series out")
    if len({x, y, series or x, value or x}) < 2 + (1 if series else 0) + (1 if value else 0):
        raise ChartError("x, y, series and value must name different columns")
    title = str(title or "").strip()[:200] or (f"{value} by {x} and {y}" if kind == "heatmap" else f"{y} by {x}")

    measure = value if kind == "heatmap" else y
    used: List[Dict[str, Any]] = []
    skipped = 0
    for i, r in enumerate(rows):
        xv = _label(r.get(x))
        mv = _num(r.get(measure))
        if xv is None or mv is None:
            raw = r.get(measure)
            if raw not in (None, "") and mv is None and not (isinstance(raw, float) and math.isnan(raw)):
                raise ChartError(f"{measure} must be numbers; row {i + 1} has {_short(raw, 40)!r}")
            skipped += 1
            continue
        rec: Dict[str, Any] = {x: xv}
        if kind == "heatmap":
            yv = _label(r.get(y))
            if yv is None:
                skipped += 1
                continue
            rec[y], rec[value] = yv, mv
        else:
            rec[y] = mv
        if series:
            sv = _label(r.get(series))
            rec[series] = "(none)" if sv is None else sv
        used.append(rec)
    if not used:
        raise ChartError(f"no row has both {x} and a number in {measure}")

    x_type = _x_type(kind, [r[x] for r in used])
    if kind == "scatter" and x_type == "ordinal":
        x_type = "nominal"
    if x_type == "temporal":
        try:
            for r in used:
                _epoch(str(r[x]))
        except ValueError:
            x_type = "ordinal"
    series_order: List[Any] = []
    if series:
        for r in used:
            if r[series] not in series_order:
                series_order.append(r[series])
        if len(series_order) > MAX_SERIES:
            raise ChartError(f"{len(series_order)} series is more than {MAX_SERIES}; filter or group them first")

    # combine duplicates where a kind draws one mark per key (sum, as Vega-Lite's stacking would show)
    combined = 0
    if kind in ("bar", "area", "waterfall", "pareto", "heatmap"):
        key_of = (lambda r: (r[x], r[y])) if kind == "heatmap" else (lambda r: (r[x], r.get(series) if series else None))
        merged: Dict[Any, Dict[str, Any]] = {}
        order: List[Any] = []
        for r in used:
            k = key_of(r)
            if k in merged:
                merged[k][measure] += r[measure]
                combined += 1
            else:
                merged[k] = dict(r)
                order.append(k)
        used = [merged[k] for k in order]
    if x_type in ("quantitative", "temporal") and kind in ("line", "area", "scatter"):
        keyf = (lambda r: _epoch(str(r[x]))) if x_type == "temporal" else (lambda r: float(r[x]))
        used.sort(key=keyf)
    cats = []
    for r in used:
        if r[x] not in cats:
            cats.append(r[x])
    if x_type in ("nominal", "ordinal") and len(cats) > MAX_CATEGORIES:
        raise ChartError(f"{len(cats)} categories on x is more than {MAX_CATEGORIES}; aggregate first")

    x_enc: Dict[str, Any] = {"field": x, "type": x_type, "title": x}
    if x_type in ("nominal", "ordinal"):
        x_enc["sort"] = None                       # keep the rows' order
    y_enc: Dict[str, Any] = {"field": y, "type": "quantitative", "title": y}
    enc: Dict[str, Any] = {"x": x_enc, "y": y_enc}
    spec: Dict[str, Any] = {"$schema": SCHEMA, "title": title, "width": W, "height": H,
                            "usermeta": {"kind": kind, "generator": "sajha bi_chart"}}
    tooltip = [{"field": x}, {"field": y}] + ([{"field": series}] if series else [])

    if kind == "line":
        spec["mark"] = {"type": "line", "point": True, "tooltip": True}
    elif kind == "scatter":
        spec["mark"] = {"type": "point", "filled": True, "tooltip": True}
    elif kind == "bar":
        spec["mark"] = {"type": "bar", "tooltip": True}
        if series:
            enc["xOffset"] = {"field": series, "sort": series_order}
    elif kind == "area":
        spec["mark"] = {"type": "area", "line": True, "opacity": 0.35, "tooltip": True}
        if series:
            y_enc["stack"] = "zero"
            # the stacked extents, computed here (series order, missing points count as zero)
            totals: Dict[Any, float] = {}
            for r in used:
                base = totals.get(r[x], 0.0)
                r["_y0"], r["_y1"] = base, base + r[y]
                totals[r[x]] = base + r[y]
    elif kind == "waterfall":
        run = 0.0
        out = []
        for r in used:
            start, end = run, run + r[y]
            out.append({x: r[x], y: r[y], "_start": start, "_end": end,
                        "_kind": "increase" if r[y] >= 0 else "decrease"})
            run = end
        total_label = "Total" if "Total" not in cats else "Total (net)"
        out.append({x: total_label, y: run, "_start": 0.0, "_end": run, "_kind": "total"})
        used = out
        cats.append(total_label)
        spec["mark"] = {"type": "bar", "tooltip": True}
        enc = {"x": x_enc, "y": {"field": "_start", "type": "quantitative", "title": y}, "y2": {"field": "_end"},
               "color": {"field": "_kind", "type": "nominal",
                         "scale": {"domain": list(WATERFALL), "range": list(WATERFALL.values())},
                         "title": "change"}}
        tooltip = [{"field": x}, {"field": y}]
    elif kind == "pareto":
        if any(r[y] < 0 for r in used):
            raise ChartError("a pareto chart needs values of zero or more")
        total = sum(r[y] for r in used)
        if total <= 0:
            raise ChartError("a pareto chart needs a positive total")
        used.sort(key=lambda r: -r[y])
        cum = 0.0
        for r in used:
            cum += r[y]
            r["_cumulative_pct"] = round(cum / total * 100, 4)
        cats = [r[x] for r in used]
        spec["layer"] = [
            {"mark": {"type": "bar", "tooltip": True}, "encoding": {"x": dict(x_enc), "y": y_enc}},
            {"mark": {"type": "line", "point": True, "tooltip": True},
             "encoding": {"x": dict(x_enc), "y": {"field": "_cumulative_pct", "type": "quantitative",
                                                  "title": "cumulative %", "scale": {"domain": [0, 100]}}}}]
        spec["resolve"] = {"scale": {"y": "independent"}}
    elif kind == "heatmap":
        spec["mark"] = {"type": "rect", "tooltip": True}
        enc = {"x": x_enc, "y": {"field": y, "type": "nominal", "title": y, "sort": None},
               "color": {"field": value, "type": "quantitative", "title": value, "scale": {"scheme": "blues"}}}
        tooltip = [{"field": x}, {"field": y}, {"field": value}]
    if series and kind != "heatmap":
        enc["color"] = {"field": series, "type": "nominal", "title": series,
                        "scale": {"domain": series_order, "range": list(PALETTE[:len(series_order)])}}
    if "layer" not in spec:
        enc["tooltip"] = tooltip
        spec["encoding"] = enc
    spec["data"] = {"values": used}
    info = {"rows": len(used) - (1 if kind == "waterfall" else 0), "skipped": skipped, "combined": combined,
            "series": [str(s) for s in series_order], "categories": len(cats)}
    return spec, info


# ── the SVG ──────────────────────────────────────────────────────

_STYLE = (
    "text{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}"
    ".bg{fill:#fcfcfb}.title{font-size:15px;font-weight:600;fill:#0b0b0b}"
    ".tick,.lg{font-size:11px;fill:#52514e}.atitle{font-size:12px;fill:#52514e}"
    ".grid{stroke:#e4e3df;stroke-width:1}.axis{stroke:#9a9993;stroke-width:1}"
    ".line{fill:none;stroke-width:2}.area{fill-opacity:.35;stroke-width:1.5}.cell{stroke:#fcfcfb;stroke-width:1}"
    ".ref{stroke:#9a9993;stroke-dasharray:4 4}"
    + "".join(f".f{i}{{fill:{c}}}.k{i}{{stroke:{c}}}" for i, c in enumerate(PALETTE))
    + "".join(f".w-{k}{{fill:{c}}}" for k, c in WATERFALL.items())
    + "@media (prefers-color-scheme:dark){.bg{fill:#1a1a19}.title{fill:#ffffff}.tick,.lg,.atitle{fill:#c3c2b7}"
      ".grid{stroke:#3a3a37}.cell{stroke:#1a1a19}}"
)


class _Svg:
    def __init__(self):
        self.parts: List[str] = []

    def add(self, s: str) -> None:
        self.parts.append(s)

    def text(self, x: float, y: float, s: Any, cls: str, anchor: str = "start", rotate: Optional[float] = None) -> None:
        tr = f' transform="rotate({_n(rotate)} {_n(x)} {_n(y)})"' if rotate else ""
        self.add(f'<text class="{cls}" x="{_n(x)}" y="{_n(y)}" text-anchor="{anchor}"{tr}>{esc(s)}</text>')


def _tip(*pairs: Tuple[Any, Any]) -> str:
    return "<title>" + esc("; ".join(f"{k}: {fmt_full(v) if isinstance(v, float) else v}" for k, v in pairs)) + "</title>"


def _heat(t: float) -> str:
    t = 0.0 if t != t else max(0.0, min(1.0, t))
    return "#" + "".join(f"{int(round(a + (b - a) * t)):02x}" for a, b in zip(HEAT_LO, HEAT_HI))


def render_svg(spec: Dict[str, Any]) -> str:
    """The SVG of a spec made by :func:`build_spec` (pure Python; deterministic)."""
    kind = (spec.get("usermeta") or {}).get("kind")
    if kind not in KINDS:
        raise ChartError("the spec was not made by bi_chart (usermeta.kind)")
    rows: List[Dict[str, Any]] = (spec.get("data") or {}).get("values") or []
    if "layer" in spec:
        enc = spec["layer"][0]["encoding"]
    else:
        enc = spec["encoding"]
    x, x_type = enc["x"]["field"], enc["x"]["type"]
    y_title = enc["y"].get("title") or enc["y"]["field"]
    y = enc["y"]["field"] if kind != "waterfall" else next(k for k in rows[0] if k not in (x, "_start", "_end", "_kind"))
    color = enc.get("color") or {}
    series = color.get("field") if kind not in ("heatmap", "waterfall") else None
    series_order = list((color.get("scale") or {}).get("domain") or [])
    title = spec.get("title") or ""

    top = 40 + (18 if series else 0)
    left = 64
    right = 56 if kind == "pareto" else 24 if x_type == "nominal" else 40
    if kind == "heatmap":
        ylabels = []
        for r in rows:
            if r[y] not in ylabels:
                ylabels.append(r[y])
        left = min(160, 24 + 7 * max(len(_short(v)) for v in ylabels))
    cats: List[Any] = []
    for r in rows:
        if r[x] not in cats:
            cats.append(r[x])
    band_x = x_type in ("nominal",) or kind in ("bar", "waterfall", "pareto", "heatmap")
    rotate = band_x and (len(cats) > 6 or any(len(str(c)) > 10 for c in cats))
    bottom = 84 if rotate else 52
    pw, ph = W - left - right, H - top - bottom

    svg = _Svg()
    svg.add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
            f'role="img" aria-label="{esc(title)}" class="sajha-chart">')
    svg.add(f"<style>{_STYLE}</style>")
    svg.add(f"<title>{esc(title)}</title>")
    svg.add(f'<rect class="bg" x="0" y="0" width="{W}" height="{H}"/>')
    svg.text(16, 24, title, "title")
    if series:
        lx = 16.0
        svg.add('<g class="legend">')
        for i, s in enumerate(series_order):
            label = _short(s, 16)
            svg.add(f'<rect class="f{i}" x="{_n(lx)}" y="34" width="10" height="10" rx="2"/>')
            svg.text(lx + 14, 43, label, "lg")
            lx += 24 + 6.5 * len(label)
        svg.add("</g>")

    # y scale
    if kind == "heatmap":
        ys = None
    else:
        if kind == "waterfall":
            vals = [v for r in rows for v in (r["_start"], r["_end"])]
        elif kind == "area" and series:
            vals = [v for r in rows for v in (r["_y0"], r["_y1"])]
        else:
            vals = [r[y] for r in rows]
        lo, hi = min(vals), max(vals)
        if kind in ("bar", "area", "waterfall", "pareto"):
            lo, hi = min(lo, 0.0), max(hi, 0.0)
        ticks = nice_ticks(lo, hi)
        y0, y1 = ticks[0], ticks[-1]

        def ys(v: float) -> float:
            return top + ph - (v - y0) / (y1 - y0) * ph
        svg.add('<g class="yaxis">')
        for t in ticks:
            svg.add(f'<line class="grid" x1="{left}" x2="{left + pw}" y1="{_n(ys(t))}" y2="{_n(ys(t))}"/>')
            svg.text(left - 6, ys(t) + 4, fmt(t), "tick", "end")
        svg.add("</g>")
        svg.text(14, top + ph / 2, _short(y_title, 40), "atitle", "middle", rotate=-90)

    # x scale
    if band_x:
        band = pw / len(cats)
        pos = {c: left + i * band for i, c in enumerate(cats)}

        def xs(v: Any) -> float:
            return pos[v] + band / 2
    elif x_type in ("quantitative", "temporal"):
        conv = (lambda v: _epoch(str(v))) if x_type == "temporal" else float
        xv = [conv(r[x]) for r in rows]
        if x_type == "quantitative":
            xt = nice_ticks(min(xv), max(xv))
            x0, x1 = xt[0], xt[-1]
        else:
            x0, x1 = min(xv), max(xv)
            if x0 == x1:
                x0, x1 = x0 - 86400, x1 + 86400

        def xs(v: Any) -> float:
            return left + (conv(v) - x0) / (x1 - x0) * pw
    else:
        step = pw / len(cats)
        pos = {c: left + step * (i + 0.5) for i, c in enumerate(cats)}

        def xs(v: Any) -> float:
            return pos[v]

    svg.add('<g class="xaxis">')
    svg.add(f'<line class="axis" x1="{left}" x2="{left + pw}" y1="{top + ph}" y2="{top + ph}"/>')
    if x_type == "quantitative" and not band_x:
        for t in xt:
            svg.text(xs(t), top + ph + 16, fmt(t), "tick", "middle")
    elif x_type == "temporal" and not band_x:
        uniq = sorted({r[x] for r in rows}, key=lambda v: _epoch(str(v)))
        n = len(uniq)
        picks = sorted({int(round(i * (n - 1) / 5)) for i in range(6)}) if n > 6 else range(n)
        for i in picks:
            svg.text(xs(uniq[i]), top + ph + 16, str(uniq[i])[:10], "tick", "middle")
    else:
        every = max(1, math.ceil(len(cats) / 24))
        for i, c in enumerate(cats):
            if i % every:
                continue
            if rotate:
                svg.text(xs(c) + 4, top + ph + 12, _short(c), "tick", "end", rotate=-40)
            else:
                svg.text(xs(c), top + ph + 16, _short(c), "tick", "middle")
    svg.text(left + pw / 2, H - 8, _short(x, 40), "atitle", "middle")
    svg.add("</g>")

    sidx = {s: i for i, s in enumerate(series_order)}
    svg.add('<g class="marks">')
    if kind == "heatmap":
        ylabels_pos = {v: top + i * (ph / len(ylabels)) for i, v in enumerate(ylabels)}
        bh = ph / len(ylabels)
        for v in ylabels:
            svg.text(left - 6, ylabels_pos[v] + bh / 2 + 4, _short(v), "tick", "end")
        value = spec["encoding"]["color"]["field"]
        vals = [r[value] for r in rows]
        lo, hi = min(vals), max(vals)
        for r in rows:
            t = 0.5 if hi == lo else (r[value] - lo) / (hi - lo)
            svg.add(f'<rect class="cell" x="{_n(pos[r[x]])}" y="{_n(ylabels_pos[r[y]])}" width="{_n(band)}" '
                    f'height="{_n(bh)}" fill="{_heat(t)}">{_tip((x, r[x]), (y, r[y]), (value, r[value]))}</rect>')
        # colour legend: low and high
        svg.add(f'<rect x="{W - 180}" y="30" width="12" height="12" fill="{_heat(0)}"/>')
        svg.text(W - 164, 40, fmt(lo), "lg")
        svg.add(f'<rect x="{W - 100}" y="30" width="12" height="12" fill="{_heat(1)}"/>')
        svg.text(W - 84, 40, fmt(hi), "lg")
    elif kind in ("bar", "waterfall", "pareto"):
        nser = max(1, len(series_order)) if kind == "bar" else 1
        inner = band * 0.8
        bw = inner / nser
        for r in rows:
            if kind == "waterfall":
                a, b, cls = r["_start"], r["_end"], f"w-{r['_kind']}"
                tip = _tip((x, r[x]), (y, r[y]), ("running total", r["_end"]))
            else:
                a, b = 0.0, r[y]
                i = sidx.get(r.get(series), 0) if series else 0
                cls = f"f{i}"
                tip = _tip(*([(x, r[x]), (y, r[y])] + ([(series, r[series])] if series else [])))
            off = (sidx.get(r.get(series), 0) * bw) if (kind == "bar" and series) else 0.0
            bx = pos[r[x]] + (band - inner) / 2 + off
            ya, yb = ys(a), ys(b)
            svg.add(f'<rect class="{cls}" x="{_n(bx)}" y="{_n(min(ya, yb))}" width="{_n(max(1.0, bw - 1))}" '
                    f'height="{_n(abs(ya - yb))}">{tip}</rect>')
        if kind == "pareto":
            def ps(v: float) -> float:
                return top + ph - v / 100 * ph
            for t in (0, 20, 40, 60, 80, 100):
                svg.text(left + pw + 6, ps(t) + 4, f"{t}%", "tick", "start")
            svg.add(f'<line class="ref" x1="{left}" x2="{left + pw}" y1="{_n(ps(80))}" y2="{_n(ps(80))}"/>')
            d = " ".join(f"{'M' if i == 0 else 'L'}{_n(xs(r[x]))} {_n(ps(r['_cumulative_pct']))}" for i, r in enumerate(rows))
            svg.add(f'<path class="line k1" d="{d}"/>')
            for r in rows:
                svg.add(f'<circle class="f1" cx="{_n(xs(r[x]))}" cy="{_n(ps(r["_cumulative_pct"]))}" r="3">'
                        f'{_tip((x, r[x]), ("cumulative %", r["_cumulative_pct"]))}</circle>')
    else:
        groups: Dict[Any, List[Dict[str, Any]]] = {}
        for r in rows:
            groups.setdefault(r.get(series) if series else None, []).append(r)
        for key, pts in groups.items():
            i = sidx.get(key, 0)
            if kind == "area":
                top_key, base_key = ("_y1", "_y0") if series else (y, None)
                upper = [(xs(r[x]), ys(r[top_key])) for r in pts]
                lower = [(xs(r[x]), ys(r[base_key] if base_key else 0.0)) for r in reversed(pts)]
                d = "M" + " L".join(f"{_n(a)} {_n(b)}" for a, b in upper + lower) + " Z"
                svg.add(f'<path class="area f{i} k{i}" d="{d}"/>')
                d = "M" + " L".join(f"{_n(a)} {_n(b)}" for a, b in upper)
                svg.add(f'<path class="line k{i}" d="{d}"/>')
            elif kind == "line":
                d = "M" + " L".join(f"{_n(xs(r[x]))} {_n(ys(r[y]))}" for r in pts)
                svg.add(f'<path class="line k{i}" d="{d}"/>')
            if kind in ("line", "scatter", "area"):
                rad = 4 if kind == "scatter" else 2.5
                yk = "_y1" if (kind == "area" and series) else y
                for r in pts:
                    pairs = [(x, r[x]), (y, r[y])] + ([(series, r[series])] if series else [])
                    svg.add(f'<circle class="f{i}" cx="{_n(xs(r[x]))}" cy="{_n(ys(r[yk]))}" r="{rad}">{_tip(*pairs)}</circle>')
    if ys is not None and kind in ("bar", "waterfall", "pareto", "area"):
        svg.add(f'<line class="axis" x1="{left}" x2="{left + pw}" y1="{_n(ys(0.0))}" y2="{_n(ys(0.0))}"/>')
    svg.add("</g></svg>")
    return "".join(svg.parts)


# ── calling another tool as the caller ───────────────────────────

def _registry(tool: BaseMCPTool):
    reg = getattr(tool, "registry", None)
    if reg is not None:
        return reg
    try:
        from sajha.tools.tools_registry import ToolsRegistry
        return ToolsRegistry._instance
    except Exception:
        return None


def call_as_caller(outer: BaseMCPTool, name: str, arguments: Dict[str, Any]) -> Tuple[Any, BaseMCPTool]:
    """Run tool ``name`` as the current caller (their tool access, then everything
    ``execute_with_tracking`` applies: policy, budgets, validation, cache, audit), nested under
    ``outer`` in the call chain. A tool that does not exist and one the caller may not run are
    refused with the same message, so the refusal does not reveal which tools exist."""
    from sajha.core import inner_calls
    reg = _registry(outer)
    inner = reg.get_tool(name) if reg is not None else None
    if inner is None or not inner_calls.caller_may_run(name):
        raise inner_calls.InnerCallRefused(f"{name}: no such tool, or you may not call it")
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    with inner_calls.entered(outer.name):
        return inner.execute_with_tracking(dict(arguments)), inner


def result_data(result: Any) -> Any:
    """The data of a tool result: structuredContent, else JSON text content, else the result."""
    if isinstance(result, dict):
        sc = result.get("structuredContent")
        if isinstance(sc, (dict, list)):
            return sc
        content = result.get("content")
        if isinstance(content, list) and set(result) <= {"content", "isError", "_meta"}:
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    try:
                        return json.loads(block.get("text") or "")
                    except ValueError:
                        continue
    return result


def _caller_id() -> str:
    from sajha.observability.caller import current
    uid = str(current().user_id or "")
    if not uid or uid == "anonymous":
        raise PermissionError("loaded tool results are kept per user: sign in first")
    return uid


# ── the tools ────────────────────────────────────────────────────

class BIChartTool(BaseMCPTool):
    """``bi_chart``: rows (given, from a ``bi_*`` call, or from one SELECT over your loaded tool
    results) as a Vega-Lite-subset spec, an SVG and an MCP Apps view."""

    registry = None                      # tests inject a registry; otherwise the running one

    def get_input_schema(self) -> Dict[str, Any]:
        return self._input_schema

    def get_output_schema(self) -> Dict[str, Any]:
        return self._output_schema

    def _rows(self, data: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        from sajha.analytics.scratch import ScratchDB, ScratchError, extract_rows
        if isinstance(data, list):
            return data, {"from": "rows"}
        if not isinstance(data, dict):
            raise ChartError("data must be rows (a list of objects), {tool, arguments} or {sql}")
        if "sql" in data:
            try:
                out = ScratchDB(_caller_id()).query(str(data.get("sql") or ""), max_rows=MAX_ROWS)
            except ScratchError as e:
                raise ChartError(str(e)) from None
            if out.get("truncated"):
                raise ChartError(f"the query returns more than {MAX_ROWS} rows; aggregate in the SQL")
            return out["rows"], {"from": "sql", "sql": out["sql"], "tables": out["tables"]}
        name = str(data.get("tool") or "").strip()
        if not name:
            raise ChartError("data must be rows (a list of objects), {tool, arguments} or {sql}")
        if not name.startswith("bi_") or name in ("bi_chart", "bi_load_tool_result"):
            raise ChartError("data.tool must be a bi_* analysis tool (for any other tool, load it with "
                             "bi_load_tool_result and chart it with data {sql})")
        args = data.get("arguments") or {}
        result, _ = call_as_caller(self, name, args)
        try:
            rows = extract_rows(result_data(result), data.get("rows_path"))
        except ScratchError as e:
            raise ChartError(f"{name}: {e}") from None
        return rows, {"from": "tool", "tool": name, "arguments": args}

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        kind = str(arguments.get("kind") or "")
        rows, source = self._rows(arguments.get("data"))
        spec, info = build_spec(rows, kind, arguments.get("x"), arguments.get("y"), arguments.get("series"),
                                arguments.get("value"), arguments.get("title"))
        out = {"kind": kind, "title": spec["title"], "spec": spec, "svg": render_svg(spec),
               "rows": info["rows"], "skipped": info["skipped"], "combined": info["combined"],
               "series": info["series"], "source": source, "view": VIEW_URI}
        return out


class BILoadToolResultTool(BaseMCPTool):
    """``bi_load_tool_result``: call a tool as the caller and load its rows into the caller's scratch
    database; returns the table's provenance."""

    registry = None

    def get_input_schema(self) -> Dict[str, Any]:
        return self._input_schema

    def get_output_schema(self) -> Dict[str, Any]:
        return self._output_schema

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from sajha.analytics.scratch import ScratchDB, ScratchError
        name = str(arguments.get("tool") or "").strip()
        if not name:
            raise ValueError("tool is required")
        if name in ("bi_load_tool_result", "bi_chart"):
            raise ValueError(f"{name} cannot be loaded; load the tool whose rows you want")
        uid = _caller_id()
        db = ScratchDB(uid)                       # refuses before the call when there is no user
        args = arguments.get("arguments") or {}
        call_id = "call_" + uuid.uuid4().hex[:16]
        result, inner = call_as_caller(self, name, args)
        classes: List[str] = []
        try:
            from sajha.net.integration.residency import catalog_summary
            classes = list(catalog_summary(inner).get("results") or [])
        except Exception:
            classes = []
        try:
            meta = db.load(result_data(result), tool=name, call_id=call_id, arguments=args,
                           rows_path=arguments.get("rows_path") or None, table=arguments.get("table") or None,
                           ttl_minutes=arguments.get("ttl_minutes"), tool_version=str(getattr(inner, "version", "") or ""),
                           data_classes=classes)
        except ScratchError as e:
            raise ValueError(f"{name}: {e}") from None
        try:
            meta["sample"] = db.query(f'SELECT * FROM "{meta["table"]}" LIMIT 3', tables=[meta["table"]],
                                      max_rows=3)["rows"]
        except ScratchError:
            meta["sample"] = []
        meta["query_with"] = {"tool": "bi_chart", "data": {"sql": f'SELECT * FROM {meta["table"]}'}}
        return meta
