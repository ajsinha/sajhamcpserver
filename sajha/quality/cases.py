"""
SAJHA MCP Server — tool test cases and probe definitions.

Read from ``quality.tests_dir`` (``config/tool_tests/*.yaml|yml|json``: ``tool``, ``cases``,
optional ``probe``) and from ``"tests"`` / ``"probe"`` in a tool's own config.
Docs: docs/architecture/Tool Quality.md §2.1.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import fnmatch
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from sajha.quality.assertions import AssertionSpecError, validate_spec

logger = logging.getLogger(__name__)


class CaseError(ValueError):
    """A test file or case that is not valid."""


@dataclass
class TestCase:
    tool: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    expect: List[Dict[str, Any]] = field(default_factory=list)
    error: Any = None                    # None: must succeed; True or a regex: must fail
    version: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    skip: str = ''
    cassette: str = ''
    source: str = ''

    __test__ = False                     # not a pytest class

    @property
    def expects_error(self) -> bool:
        return self.error not in (None, False)

    @property
    def cassette_name(self) -> str:
        return self.cassette or self.name

    def to_dict(self) -> Dict[str, Any]:
        return {'tool': self.tool, 'name': self.name, 'arguments': self.arguments, 'expect': self.expect,
                'error': self.error, 'version': self.version, 'tags': self.tags, 'skip': self.skip,
                'source': self.source}


@dataclass
class ProbeSpec:
    tool: str
    case: str
    every: Optional[float] = None        # seconds
    cron: str = ''
    timezone: str = ''
    source: str = ''

    def schedule_text(self) -> str:
        if self.cron:
            return f'cron {self.cron}' + (f' ({self.timezone})' if self.timezone else '')
        return f'every {int(self.every or 0)} s'

    def to_dict(self) -> Dict[str, Any]:
        return {'tool': self.tool, 'case': self.case, 'every': self.every, 'cron': self.cron,
                'timezone': self.timezone, 'schedule': self.schedule_text(), 'source': self.source}


def _load_file(path: Path) -> Any:
    text = path.read_text(encoding='utf-8')
    if path.suffix.lower() == '.json':
        return json.loads(text)
    import yaml
    return yaml.safe_load(text)


def parse_case(tool: str, raw: Any, source: str = '', index: int = 0) -> TestCase:
    if not isinstance(raw, dict):
        raise CaseError(f'{source}: case {index + 1} of {tool} is not an object')
    name = str(raw.get('name') or f'case_{index + 1}')
    args = raw.get('arguments', {}) or {}
    if not isinstance(args, dict):
        raise CaseError(f'{source}: {tool}/{name}: arguments must be an object')
    expect = raw.get('expect', []) or []
    if isinstance(expect, dict):
        expect = [expect]
    if not isinstance(expect, list):
        raise CaseError(f'{source}: {tool}/{name}: expect must be a list of assertions')
    for spec in expect:
        try:
            validate_spec(spec)
        except AssertionSpecError as e:
            raise CaseError(f'{source}: {tool}/{name}: {e}') from e
        except Exception as e:      # a JSONPath error
            raise CaseError(f'{source}: {tool}/{name}: {e}') from e
    tags = raw.get('tags') or []
    return TestCase(tool=tool, name=name, arguments=args, expect=list(expect), error=raw.get('error'),
                    version=str(raw['version']) if raw.get('version') is not None else None,
                    tags=[str(t) for t in (tags if isinstance(tags, list) else [tags])],
                    skip=str(raw.get('skip') or ''), cassette=str(raw.get('cassette') or ''), source=source)


def parse_probe(tool: str, raw: Any, cases: List[TestCase], source: str = '') -> Optional[ProbeSpec]:
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise CaseError(f'{source}: probe of {tool} must be an object')
    case = str(raw.get('case') or (cases[0].name if cases else ''))
    if not case or case not in {c.name for c in cases}:
        raise CaseError(f'{source}: probe of {tool} names case {case!r}, which is not one of its cases')
    every, cron = raw.get('every'), str(raw.get('cron') or '')
    if cron:
        try:
            from sajha.workflows.cron import CronSchedule
            CronSchedule(cron, raw.get('timezone') or None)
        except ImportError:
            raise CaseError(f'{source}: probe of {tool}: cron schedules need sajha.workflows.cron')
        except ValueError as e:
            raise CaseError(f'{source}: probe of {tool}: {e}') from e
        every = None
    else:
        try:
            every = float(every) if every is not None else None
        except (TypeError, ValueError):
            raise CaseError(f'{source}: probe of {tool}: every must be a number of seconds')
        if every is None:
            from sajha.quality import setting_int
            every = float(setting_int('probes.default_every_seconds', 300))
        if every < 5:
            raise CaseError(f'{source}: probe of {tool}: every must be at least 5 seconds')
    return ProbeSpec(tool=tool, case=case, every=every, cron=cron, timezone=str(raw.get('timezone') or ''),
                     source=source)


@dataclass
class Suite:
    cases: List[TestCase] = field(default_factory=list)
    probes: Dict[str, ProbeSpec] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def for_tool(self, tool: str) -> List[TestCase]:
        return [c for c in self.cases if c.tool == tool]

    def tools(self) -> List[str]:
        return sorted({c.tool for c in self.cases})


def _add(suite: Suite, tool: str, raw_cases: Any, raw_probe: Any, source: str) -> None:
    if not isinstance(raw_cases, list):
        suite.errors.append(f'{source}: cases must be a list')
        return
    parsed: List[TestCase] = []
    for i, rc in enumerate(raw_cases):
        try:
            parsed.append(parse_case(tool, rc, source, i))
        except CaseError as e:
            suite.errors.append(str(e))
    names = [c.name for c in suite.for_tool(tool)] + []
    for c in parsed:
        if c.name in names:
            suite.errors.append(f'{source}: {tool}: duplicate case name {c.name!r}')
            continue
        names.append(c.name)
        suite.cases.append(c)
    try:
        probe = parse_probe(tool, raw_probe, suite.for_tool(tool), source)
        if probe:
            if tool in suite.probes:
                suite.errors.append(f'{source}: {tool} already has a probe (in {suite.probes[tool].source})')
            else:
                suite.probes[tool] = probe
    except CaseError as e:
        suite.errors.append(str(e))


def load_suite(directory: Optional[str] = None, registry: Any = None) -> Suite:
    """Every case and probe: the test files, then ``tests``/``probe`` inside tool configs."""
    from sajha.quality import tests_dir
    suite = Suite()
    root = Path(directory or tests_dir())
    if root.is_dir():
        for path in sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in ('.yaml', '.yml', '.json')):
            try:
                doc = _load_file(path)
            except Exception as e:
                suite.errors.append(f'{path}: {e}')
                continue
            docs = doc if isinstance(doc, list) else [doc]
            for d in docs:
                if not isinstance(d, dict) or not d.get('tool'):
                    suite.errors.append(f'{path}: a test file needs "tool" and "cases"')
                    continue
                _add(suite, str(d['tool']), d.get('cases', []) or [], d.get('probe'), str(path))
    tools = getattr(registry, 'tools', None) or {}
    for name in sorted(tools):
        cfg = getattr(tools[name], 'config', None) or {}
        if isinstance(cfg, dict) and (cfg.get('tests') or cfg.get('probe')):
            _add(suite, name, cfg.get('tests') or [], cfg.get('probe'), f'tool config {name}')
    return suite


def select(cases: List[TestCase], tool_glob: str = '', case_glob: str = '', tags: Optional[List[str]] = None) -> List[TestCase]:
    out = []
    for c in cases:
        if tool_glob and not any(fnmatch.fnmatchcase(c.tool, g.strip()) for g in tool_glob.split(',') if g.strip()):
            continue
        if case_glob and not fnmatch.fnmatchcase(c.name, case_glob):
            continue
        if tags and not set(tags) & set(c.tags):
            continue
        out.append(c)
    return out
