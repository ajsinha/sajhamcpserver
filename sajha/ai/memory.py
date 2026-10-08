"""
SAJHA MCP Server — conversation memory for multi-turn asks and LLM tools.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A conversation belongs to one user and is never visible to another: every read, write and
delete is filtered by the caller's user id, so a conversation id alone gives nothing away.
A conversation also belongs to one *scope*: the Ask SAJHA page (``tool_name`` NULL) or one
LLM tool (``tool_name`` = the tool's name), and is never continued from another scope.

Each ask in a conversation sees (sajha/ai/intelligence.py):

* the most recent ``ai.memory.history_turns`` turns verbatim (question and answer); only
  those rows are read, never the whole conversation;
* a summary of the older turns, written through the gateway (``ai.memory.model``) once they
  leave the verbatim window, and kept on the conversation row;
* the question rewritten as a standalone question (``ai.memory.condense``), so a follow-up
  such as "and from 100 to 150?" finds the right tools.

Storage: two tables, ``ai_conversations`` and ``ai_conversation_turns`` (SQLAlchemy Core,
below). SQLite creates them on first use; on PostgreSQL they come from
db/scripts/postgresql/schema.sql (SAJHA runs no DDL there). Questions and answers are
clipped to ``ai.memory.max_turn_chars``. Conversations idle longer than
``ai.memory.retention_days``, past their own ``expires_ts`` (an LLM tool's
``memory.ttl_minutes``), beyond a user's ``max_conversations_per_user``, or beyond a user's
``ai.llm_tools.memory.max_conversations_per_tool`` for one tool are deleted by a purge job
that runs every ``ai.llm_tools.memory.purge_interval_minutes`` on exactly one worker
(:func:`start_purge`; a one-slot claim in the state store). Users delete their own history
with ``DELETE /api/ai/conversations``. Anonymous callers get no stored conversations.

API for LLM tools (the ``memory`` block of an LLM tool; docs/architecture/LLM Tools.md §10)
-----------------------------------------------------------------------------------------

``mem = get_intelligence().memory`` (a :class:`ConversationMemory`), then per call::

    # memory.mode: conversation  (the handle; §10.2)
    mc = mem.open(args.get("conversation_id"), question, ctx, tool_name=tool.name,
                  ttl_minutes=cfg.ttl_minutes, max_turns=cfg.max_turns, usage_sink=count)
        # no id            -> a new conversation (mc.is_new, mc.conversation_id to return)
        # an id it owns    -> continued: mc.history (Messages, oldest first), mc.summary,
        #                     mc.standalone (the follow-up rewritten), mc.turn
        # anything else    -> raises ConversationNotFound("conversation not found"): unknown,
        #                     expired, another user's or another tool's id. Never "forbidden".
        # anonymous caller -> mc.stored is False (nothing will be kept); with an id: not found
    ... run the tool with mc.history / mc.summary / mc.standalone ...
    turn = mem.record(mc, ctx, question, answer=text, tools=[names], stopped_by="answer",
                      confidence=0.9, usage_sink=count)       # None when nothing was stored
        # clips question and answer, renews expires_ts, and folds turns beyond max_turns
        # into the summary (their rows are deleted)

    # memory.mode: client  (the caller keeps the history; §10.1)
    mc = mem.from_client(args.get("messages"), question, ctx, usage_sink=count)
        # validates [{role: user|assistant, content}], keeps the last history_turns pairs,
        # clips each, condenses the question; raises ValueError on a malformed list.
        # Nothing is stored (mc.stored is False); record() is a no-op for it.

``ai.llm_tools.memory`` ceilings (:class:`ToolMemorySettings`): a tool's ``max_turns`` is
capped by ``max_turns``; its ``ttl_minutes`` by ``ai.memory.retention_days``.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import (Column, Float, ForeignKey, Index, Integer, MetaData, String, Table, Text, and_, delete,
                        func, insert, or_, select, update)

from sajha.ai.llm.settings import Layered, MemorySettings, load_ai_yaml, resolve_layers
from sajha.ai.llm import ChatCompletion, ChatMessage, RequestContext, ResponseFormat

logger = logging.getLogger(__name__)

metadata = MetaData()

ai_conversations = Table(
    'ai_conversations', metadata,
    Column('id', String(36), primary_key=True),
    Column('user_id', String(200), nullable=False),
    Column('title', String(200)),
    Column('summary', Text),
    Column('summarized_through', Integer, nullable=False, default=0),
    Column('turn_count', Integer, nullable=False, default=0),
    Column('created_ts', Float, nullable=False),
    Column('updated_ts', Float, nullable=False),
    Column('tool_name', String(200)),                 # NULL: the Ask SAJHA page; else the LLM tool
    Column('expires_ts', Float),                      # NULL: only ai.memory.retention_days applies
    Index('ix_ai_conversations_user_updated', 'user_id', 'updated_ts'),
    Index('ix_ai_conversations_user_tool_updated', 'user_id', 'tool_name', 'updated_ts'),
    Index('ix_ai_conversations_expires', 'expires_ts'),
)

ai_conversation_turns = Table(
    'ai_conversation_turns', metadata,
    Column('id', String(36), primary_key=True),
    Column('conversation_id', String(36), ForeignKey('ai_conversations.id', ondelete='CASCADE'), nullable=False),
    Column('user_id', String(200), nullable=False),
    Column('seq', Integer, nullable=False),
    Column('question', Text, nullable=False),
    Column('standalone', Text),
    Column('answer', Text),
    Column('tools', String(2000)),
    Column('stopped_by', String(40)),
    Column('confidence', Float),
    Column('created_ts', Float, nullable=False),
    Index('ux_ai_conversation_turns_conv_seq', 'conversation_id', 'seq', unique=True),
    Index('ix_ai_conversation_turns_user', 'user_id'),
)

TABLES = [ai_conversations, ai_conversation_turns]
NEW = "new"                          # conversation_id value that starts a conversation
ANY = object()                       # store filter: every scope (the conversations API)
ASK_LABEL = "ask"                    # the metrics label of Ask SAJHA page conversations
NOT_FOUND = "conversation not found"
_ID = re.compile(r"^[A-Za-z0-9-]{8,36}$")

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string", "description": "The summary of the conversation so far."}},
    "required": ["summary"], "additionalProperties": False,
}
SUMMARY_PROMPT = (
    "Summarise this conversation between a user and SAJHA's analyst for later turns: the questions asked, "
    "the figures and facts the answers gave, and anything the user said they want. Keep names, numbers "
    "and units exactly. Return JSON matching the schema. Write at most {n} characters."
)
CONDENSE_SCHEMA = {
    "type": "object",
    "properties": {"standalone_question": {
        "type": "string", "description": "The user's last message rewritten to stand on its own."}},
    "required": ["standalone_question"], "additionalProperties": False,
}
CONDENSE_PROMPT = (
    "Rewrite the user's last message as a standalone question that can be understood without the "
    "conversation: carry over the subject, figures and names it refers to. If it already stands on its "
    "own, return it unchanged. Return JSON matching the schema."
)


class ToolMemorySettings(Layered):
    """``ai.llm_tools.memory``: ceilings and the purge job (env ``SAJHA_AI_LLM_TOOLS_MEMORY_<FIELD>``)."""
    max_turns: int = 50                        # turns kept verbatim per tool conversation; older fold into the summary
    max_conversations_per_tool: int = 50       # per user per tool; the oldest beyond are deleted (0 = no cap)
    purge_interval_minutes: int = 15           # the scheduled purge (0 = off: purge at most hourly on a write)
    sqlite_vacuum: bool = False                # VACUUM the SQLite file after a purge that deleted rows


def tool_memory_settings(raw: Optional[Dict[str, Any]] = None) -> ToolMemorySettings:
    """Resolve ``ai.llm_tools.memory`` (env > YAML > default); keys of later build steps are ignored."""
    if raw is None:
        raw = ((load_ai_yaml().get("llm_tools") or {}).get("memory") or {})
    cfg = {k: v for k, v in dict(raw or {}).items() if k in ToolMemorySettings.model_fields}
    try:
        model, _src = resolve_layers(ToolMemorySettings, "llm_tools_memory", cfg)
        return model
    except Exception as e:
        logger.warning(f"ai.llm_tools.memory: {e}; using the defaults")
        return ToolMemorySettings()


class MemorySchemaMissing(RuntimeError):
    """PostgreSQL without the conversation tables (they come from the schema file)."""


class ConversationNotFound(LookupError):
    """No such conversation for this caller and scope: unknown, expired, another user's or another
    tool's are all reported the same way, so the answer never confirms that an id exists."""


@dataclass
class MemoryContext:
    conversation_id: str
    is_new: bool
    history: List[ChatMessage] = field(default_factory=list)   # earlier turns, oldest first
    summary: str = ""
    standalone: str = ""
    turn: int = 1                                           # the number of this turn
    tool_name: Optional[str] = None                         # None: the Ask SAJHA page
    stored: bool = True                                     # False: nothing is kept (anonymous, client mode)
    ttl_minutes: Optional[int] = None
    max_turns: Optional[int] = None


def valid_id(cid: Any) -> bool:
    return isinstance(cid, str) and bool(_ID.match(cid))


# ── metrics (docs/architecture/Observability.md) ──────────────────

def _metrics():
    try:
        from sajha.observability import metrics as m
        return m
    except Exception:
        return None


def _label(tool_name: Optional[str]) -> str:
    return tool_name or ASK_LABEL


# ── storage ───────────────────────────────────────────────────────

class ConversationStore:
    """Per-user conversations and turns. Every method takes the owner's user id.

    ``tool_name`` filters by scope: ``None`` the Ask SAJHA page, a name that tool, ``ANY`` both.
    Expired conversations (``expires_ts`` passed) are invisible even before the purge deletes them."""

    def __init__(self, engine=None):
        self._engine = engine
        self._ready_for = None
        self._lock = threading.Lock()

    @property
    def engine(self):
        if self._engine is not None:
            return self._engine
        from sajha.db.engine import get_engine
        return get_engine()

    def ensure_tables(self) -> None:
        engine = self.engine
        if self._ready_for is engine:
            return
        with self._lock:
            if self._ready_for is engine:
                return
            if engine.dialect.name == 'sqlite':
                metadata.create_all(engine, tables=TABLES, checkfirst=True)
            else:
                from sqlalchemy import inspect
                insp = inspect(engine)
                gone = [t.name for t in TABLES if not insp.has_table(t.name)]
                if gone:
                    from sajha.db.schema import apply_command
                    raise MemorySchemaMissing(f'tables {", ".join(gone)} are missing; create them from the '
                                              f'schema file:  {apply_command(engine)}  '
                                              '(docs/getting-started/Database Setup.md)')
            self._ready_for = engine

    @staticmethod
    def _scope(tool_name):
        conv = ai_conversations
        if tool_name is ANY:
            return None
        return conv.c.tool_name.is_(None) if tool_name is None else conv.c.tool_name == str(tool_name)

    @staticmethod
    def _live(now: Optional[float] = None):
        conv = ai_conversations
        return or_(conv.c.expires_ts.is_(None), conv.c.expires_ts > (time.time() if now is None else now))

    def _where(self, user_id: str, tool_name, *extra):
        conds = [ai_conversations.c.user_id == user_id, self._live(), *extra]
        scope = self._scope(tool_name)
        if scope is not None:
            conds.append(scope)
        return and_(*conds)

    def get(self, conversation_id: str, user_id: str, tool_name=ANY) -> Optional[Dict[str, Any]]:
        if not valid_id(conversation_id) or not user_id:
            return None
        self.ensure_tables()
        with self.engine.connect() as c:
            row = c.execute(select(ai_conversations).where(
                self._where(user_id, tool_name, ai_conversations.c.id == conversation_id))).mappings().first()
        return dict(row) if row else None

    def list(self, user_id: str, limit: int = 50, tool_name=ANY) -> List[Dict[str, Any]]:
        self.ensure_tables()
        with self.engine.connect() as c:
            rows = c.execute(select(ai_conversations).where(self._where(user_id, tool_name))
                             .order_by(ai_conversations.c.updated_ts.desc()).limit(limit)).mappings().all()
        return [dict(r) for r in rows]

    def turns(self, conversation_id: str, user_id: str, after: int = 0, through: Optional[int] = None
              ) -> List[Dict[str, Any]]:
        """Stored turns, oldest first: those with ``after < seq [<= through]`` (all by default)."""
        self.ensure_tables()
        t = ai_conversation_turns
        conds = [t.c.conversation_id == conversation_id, t.c.user_id == user_id]
        if after:
            conds.append(t.c.seq > after)
        if through is not None:
            conds.append(t.c.seq <= through)
        with self.engine.connect() as c:
            rows = c.execute(select(t).where(and_(*conds)).order_by(t.c.seq)).mappings().all()
        return [dict(r) for r in rows]

    def add_turn(self, conversation_id: str, user_id: str, *, question: str, standalone: str, answer: str,
                 tools: List[str], stopped_by: str, confidence: float, title: str = "",
                 tool_name: Optional[str] = None, expires_ts: Optional[float] = None) -> int:
        """Append a turn (creating the conversation on its first turn). Returns the turn's number.

        A conversation of another user or scope, or one that has expired, raises ConversationNotFound.
        ``expires_ts`` (when given) is set on the conversation, so each turn renews it."""
        self.ensure_tables()
        now = time.time()
        conv, t = ai_conversations, ai_conversation_turns
        with self.engine.begin() as c:
            row = c.execute(select(conv.c.user_id, conv.c.turn_count, conv.c.tool_name, conv.c.expires_ts)
                            .where(conv.c.id == conversation_id)).first()
            if row is None:
                c.execute(insert(conv).values(id=conversation_id, user_id=user_id, title=(title or question)[:200],
                                              summary=None, summarized_through=0, turn_count=0,
                                              created_ts=now, updated_ts=now, tool_name=tool_name,
                                              expires_ts=expires_ts))
                count = 0
            elif row[0] != user_id or (row[2] or None) != (tool_name or None) or (row[3] is not None and row[3] <= now):
                raise ConversationNotFound(NOT_FOUND)
            else:
                count = int(row[1] or 0)
            seq = count + 1
            c.execute(insert(t).values(id=uuid.uuid4().hex, conversation_id=conversation_id, user_id=user_id, seq=seq,
                                       question=question, standalone=standalone or None, answer=answer,
                                       tools=",".join(tools)[:2000], stopped_by=(stopped_by or "")[:40],
                                       confidence=None if confidence is None else float(confidence),
                                       created_ts=now))
            values = {"turn_count": seq, "updated_ts": now}
            if expires_ts is not None:
                values["expires_ts"] = expires_ts
            c.execute(update(conv).where(conv.c.id == conversation_id).values(**values))
        return seq

    def set_summary(self, conversation_id: str, user_id: str, summary: str, through: int) -> None:
        self.ensure_tables()
        conv = ai_conversations
        with self.engine.begin() as c:
            c.execute(update(conv).where(and_(conv.c.id == conversation_id, conv.c.user_id == user_id))
                      .values(summary=summary, summarized_through=through))

    def fold(self, conversation_id: str, user_id: str, through: int, summary: Optional[str]) -> int:
        """Delete the turns up to ``through`` (now represented by the summary). Returns rows deleted."""
        self.ensure_tables()
        conv, t = ai_conversations, ai_conversation_turns
        with self.engine.begin() as c:
            if summary is not None:
                c.execute(update(conv).where(and_(conv.c.id == conversation_id, conv.c.user_id == user_id))
                          .values(summary=summary, summarized_through=through))
            n = c.execute(delete(t).where(and_(t.c.conversation_id == conversation_id, t.c.user_id == user_id,
                                               t.c.seq <= through))).rowcount
        return int(n or 0)

    def delete(self, conversation_id: str, user_id: str) -> bool:
        self.ensure_tables()
        with self.engine.begin() as c:
            owned = c.execute(select(ai_conversations.c.id).where(and_(
                ai_conversations.c.id == conversation_id, ai_conversations.c.user_id == user_id))).first()
            if owned is None:
                return False
            c.execute(delete(ai_conversation_turns).where(ai_conversation_turns.c.conversation_id == conversation_id))
            c.execute(delete(ai_conversations).where(ai_conversations.c.id == conversation_id))
        return True

    def delete_all(self, user_id: str) -> int:
        self.ensure_tables()
        with self.engine.begin() as c:
            c.execute(delete(ai_conversation_turns).where(ai_conversation_turns.c.user_id == user_id))
            n = c.execute(delete(ai_conversations).where(ai_conversations.c.user_id == user_id)).rowcount
        return int(n or 0)

    def purge(self, retention_days: int, max_per_user: int, max_per_tool: int = 0,
              now: Optional[float] = None) -> int:
        """Delete conversations idle past the retention or past their own ``expires_ts``, each user's
        oldest beyond ``max_per_user``, and each user's oldest of one tool beyond ``max_per_tool``."""
        self.ensure_tables()
        now = time.time() if now is None else now
        conv, t = ai_conversations, ai_conversation_turns
        doomed: List[str] = []
        live = self._live(now)                 # the caps count only conversations that are kept anyway
        with self.engine.begin() as c:
            if retention_days and retention_days > 0:
                cutoff = now - retention_days * 86400
                doomed += [r[0] for r in c.execute(select(conv.c.id).where(conv.c.updated_ts < cutoff))]
                live = and_(live, conv.c.updated_ts >= cutoff)
            doomed += [r[0] for r in c.execute(select(conv.c.id).where(and_(
                conv.c.expires_ts.is_not(None), conv.c.expires_ts <= now)))]
            if max_per_user and max_per_user > 0:
                over = c.execute(select(conv.c.user_id).where(live).group_by(conv.c.user_id)
                                 .having(func.count(conv.c.id) > max_per_user)).all()
                for (uid,) in over:
                    ids = [r[0] for r in c.execute(select(conv.c.id).where(and_(live, conv.c.user_id == uid))
                                                   .order_by(conv.c.updated_ts.desc()))]
                    doomed += ids[max_per_user:]
            if max_per_tool and max_per_tool > 0:
                over = c.execute(select(conv.c.user_id, conv.c.tool_name).where(and_(live, conv.c.tool_name.is_not(None)))
                                 .group_by(conv.c.user_id, conv.c.tool_name)
                                 .having(func.count(conv.c.id) > max_per_tool)).all()
                for uid, tool in over:
                    ids = [r[0] for r in c.execute(select(conv.c.id).where(and_(
                        live, conv.c.user_id == uid, conv.c.tool_name == tool)).order_by(conv.c.updated_ts.desc()))]
                    doomed += ids[max_per_tool:]
            doomed = sorted(set(doomed))
            for i in range(0, len(doomed), 200):
                part = doomed[i:i + 200]
                c.execute(delete(t).where(t.c.conversation_id.in_(part)))
                c.execute(delete(conv).where(conv.c.id.in_(part)))
        return len(doomed)

    def counts(self) -> Dict[str, int]:
        """Stored conversations per scope label (``ask`` for the Ask SAJHA page)."""
        self.ensure_tables()
        conv = ai_conversations
        with self.engine.connect() as c:
            rows = c.execute(select(conv.c.tool_name, func.count(conv.c.id)).group_by(conv.c.tool_name)).all()
        return {_label(tool): int(n) for tool, n in rows}

    def vacuum(self) -> bool:
        """Return freed SQLite pages to the file system (no-op elsewhere)."""
        engine = self.engine
        if engine.dialect.name != 'sqlite':
            return False
        from sqlalchemy import text
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text("VACUUM"))
        return True


# ── memory: context for the next ask, and recording its turn ──────

def _remote_safe(answer: str, steps) -> str:
    """SAJHA Net residency (design §12): an answer that used results from other instances is stored as
    written, without its figures, or not at all, by the data classes of those results
    (``sajhanet.memory.remote_results`` and ``sajhanet.memory.by_class``)."""
    try:
        from sajha.net.integration.residency import memory_answer
        return memory_answer(answer, steps)[0]
    except Exception as e:
        logger.debug(f"conversation memory: residency of remote results: {e}")
        return answer


def _clip(text: str, n: int) -> str:
    text = text or ""
    return text if n <= 0 or len(text) <= n else text[: n - 1] + "…"


class ConversationMemory:
    def __init__(self, gateway, settings: Optional[MemorySettings] = None, store: Optional[ConversationStore] = None,
                 tool_settings: Optional[ToolMemorySettings] = None):
        self.gateway = gateway
        self.settings = settings or MemorySettings()
        self.store = store or ConversationStore()
        self._tool_settings = tool_settings
        self._last_purge = 0.0

    @property
    def tool_settings(self) -> ToolMemorySettings:
        if self._tool_settings is None:
            self._tool_settings = tool_memory_settings()
        return self._tool_settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enabled)

    def exists(self, conversation_id: str, user_id: str, tool_name: Optional[str] = None) -> bool:
        return self.store.get(conversation_id, user_id, tool_name) is not None

    # the Ask SAJHA page
    def context(self, conversation_id: Optional[str], question: str, ctx: RequestContext,
                usage_sink=None) -> MemoryContext:
        """History, summary and the standalone question for an ask in this conversation.

        ``conversation_id`` "new" (or None) starts one; an id that is not this user's Ask SAJHA page
        conversation raises ConversationNotFound. ``usage_sink(resp)`` receives each model response."""
        if not ctx.user_id:
            raise ConversationNotFound("conversations belong to signed-in users")
        if not conversation_id or conversation_id == NEW:
            return MemoryContext(str(uuid.uuid4()), True, standalone=question)
        conv = self.store.get(conversation_id, ctx.user_id, None)
        if conv is None:
            raise ConversationNotFound(conversation_id)
        return self._continue(conv, question, ctx, usage_sink, MemoryContext(conversation_id, False))

    # LLM tools: the handle (docs/architecture/LLM Tools.md §10.2)
    def open(self, conversation_id: Optional[str], question: str, ctx: RequestContext, *, tool_name: str,
             ttl_minutes: Optional[int] = None, max_turns: Optional[int] = None, usage_sink=None
             ) -> MemoryContext:
        """The conversation of an LLM tool call. No id: a new one. An id this caller owns for this
        tool and that has not expired: continued. Any other id: ConversationNotFound("conversation
        not found"). Anonymous callers keep nothing (``stored`` False), and their ids are not found."""
        if not tool_name:
            raise ValueError("open() needs the tool's name; the Ask SAJHA page uses context()")
        given = conversation_id not in (None, "", NEW)
        if not ctx.user_id:
            if given:
                raise ConversationNotFound(NOT_FOUND)
            return MemoryContext("", True, standalone=question, tool_name=tool_name, stored=False)
        base = MemoryContext(str(uuid.uuid4()), True, standalone=question, tool_name=tool_name,
                             ttl_minutes=ttl_minutes, max_turns=max_turns)
        if not given:
            return base
        conv = self.store.get(conversation_id, ctx.user_id, tool_name) if valid_id(conversation_id) else None
        if conv is None:
            raise ConversationNotFound(NOT_FOUND)
        base.conversation_id, base.is_new = conversation_id, False
        return self._continue(conv, question, ctx, usage_sink, base)

    # LLM tools: memory.mode client
    def from_client(self, messages: Any, question: str, ctx: RequestContext, usage_sink=None) -> MemoryContext:
        """A context from the history the caller sent (``[{role, content}]``); nothing is stored."""
        history = client_history(messages, max_turns=max(0, int(self.settings.history_turns)),
                                 max_chars=self.settings.max_turn_chars)
        standalone = question
        if history and self.settings.condense:
            standalone = self._condense(question, history, "", ctx, usage_sink) or question
        return MemoryContext("", True, history, "", standalone, len(history) // 2 + 1, stored=False)

    def _continue(self, conv: Dict[str, Any], question: str, ctx: RequestContext, usage_sink,
                  mc: MemoryContext) -> MemoryContext:
        """Load the window (and only the window) and the summary; summarise turns that left it."""
        s = self.settings
        cid = conv["id"]
        count = int(conv.get("turn_count") or 0)
        window = max(0, int(s.history_turns))
        first_recent = count - window                      # turns with seq > this are verbatim
        summary = conv.get("summary") or ""
        through = int(conv.get("summarized_through") or 0)
        rows = self.store.turns(cid, ctx.user_id, after=min(through, first_recent) if s.summarize else first_recent)
        older = [t for t in rows if through < t["seq"] <= first_recent]      # left the window, not yet summarised
        recent = [t for t in rows if t["seq"] > first_recent]
        if older and s.summarize:
            summary = self._summarize(summary, older, ctx, usage_sink) or summary
            if summary:
                self.store.set_summary(cid, ctx.user_id, summary, older[-1]["seq"])
        elif not s.summarize:
            summary = ""
        history: List[ChatMessage] = []
        for t in recent:
            history.append(ChatMessage.user(t["question"]))
            history.append(ChatMessage.assistant(_clip(t.get("answer") or "", s.max_turn_chars)))
        standalone = question
        if s.condense and (history or summary):
            standalone = self._condense(question, history, summary, ctx, usage_sink) or question
        mc.history, mc.summary, mc.standalone, mc.turn = history, summary, standalone, count + 1
        return mc

    def record(self, mc: MemoryContext, ctx: RequestContext, question: str, result=None, *,
               answer: Optional[str] = None, tools: Optional[List[str]] = None, stopped_by: Optional[str] = None,
               confidence: Optional[float] = None, usage_sink=None, steps: Optional[List[Any]] = None) -> Optional[int]:
        """Store the turn; returns its number, or None when nothing was stored (anonymous caller,
        client mode, or a storage error, which is logged). ``result`` is an AskResult (the Ask
        SAJHA page); LLM tools pass ``answer``/``tools``/``stopped_by``/``confidence`` instead."""
        if mc is None or not mc.stored or not ctx.user_id:
            return None
        s = self.settings
        if result is not None:
            answer = result.answer if answer is None else answer
            tools = [st.name for st in result.steps] if tools is None else tools
            stopped_by = result.stopped_by if stopped_by is None else stopped_by
            confidence = result.confidence if confidence is None else confidence
            steps = getattr(result, "steps", None) if steps is None else steps
        if steps:
            answer = _remote_safe(answer or "", steps)       # ``steps``: what the answer rests on (AskStep-like)
        expires = None
        if mc.tool_name and mc.ttl_minutes and int(mc.ttl_minutes) > 0:
            minutes = int(mc.ttl_minutes)
            if s.retention_days and s.retention_days > 0:
                minutes = min(minutes, int(s.retention_days) * 1440)
            expires = time.time() + minutes * 60
        try:
            seq = self.store.add_turn(mc.conversation_id, ctx.user_id, question=_clip(question, s.max_turn_chars),
                                      standalone=_clip(mc.standalone, s.max_turn_chars)
                                      if mc.standalone and mc.standalone != question else "",
                                      answer=_clip(answer or "", s.max_turn_chars), tools=list(tools or []),
                                      stopped_by=stopped_by or "", confidence=confidence,
                                      tool_name=mc.tool_name, expires_ts=expires)
        except Exception as e:
            logger.warning(f"conversation memory: could not record the turn: {e}")
            return None
        m = _metrics()
        if m is not None:
            m.LLM_TOOL_TURNS.inc((_label(mc.tool_name),))
        limit = self._max_turns(mc)
        if limit and seq > limit:
            try:
                self._fold(mc.conversation_id, ctx, seq - limit, usage_sink)
            except Exception as e:
                logger.warning(f"conversation memory: could not fold old turns: {e}")
        if not _purger_running():
            self._maybe_purge()
        return seq

    def _max_turns(self, mc: MemoryContext) -> int:
        """Turns kept per conversation: a tool's ``max_turns`` under the ``ai.llm_tools`` ceiling; the
        Ask SAJHA page keeps every turn (its window is still ``history_turns``)."""
        if not mc.tool_name:
            return int(mc.max_turns or 0)
        ceiling = int(self.tool_settings.max_turns or 0)
        asked = int(mc.max_turns or 0)
        n = min(asked, ceiling) if asked and ceiling else (asked or ceiling)
        return max(n, 1) if n else 0

    def _fold(self, cid: str, ctx: RequestContext, through: int, usage_sink) -> int:
        """Turns up to ``through`` go into the summary and their rows are deleted."""
        conv = self.store.get(cid, ctx.user_id)
        if conv is None:
            return 0
        done = int(conv.get("summarized_through") or 0)
        summary = None
        if self.settings.summarize and through > done:
            pending = self.store.turns(cid, ctx.user_id, after=done, through=through)
            if pending:
                summary = self._summarize(conv.get("summary") or "", pending, ctx, usage_sink) or (conv.get("summary") or "")
        elif through > done:
            summary = conv.get("summary") or ""
        return self.store.fold(cid, ctx.user_id, through, summary)

    # purging
    def purge_now(self) -> int:
        """One purge pass (the scheduled job calls this); returns conversations deleted."""
        ts = self.tool_settings
        n = self.store.purge(self.settings.retention_days, self.settings.max_conversations_per_user,
                             ts.max_conversations_per_tool)
        m = _metrics()
        if m is not None:
            if n:
                m.LLM_TOOL_PURGED.inc((), n)
            try:
                counts = self.store.counts()
                for k in list(m.LLM_TOOL_CONVERSATIONS._series):
                    if k and k[0] not in counts:
                        m.LLM_TOOL_CONVERSATIONS.set(k, 0)
                for label, cnt in counts.items():
                    m.LLM_TOOL_CONVERSATIONS.set((label,), cnt)
            except Exception as e:
                logger.debug(f"conversation memory: counts: {e}")
        if n:
            logger.info(f"conversation memory: deleted {n} expired conversation(s)")
            if ts.sqlite_vacuum:
                try:
                    self.store.vacuum()
                except Exception as e:
                    logger.info(f"conversation memory: VACUUM failed: {e}")
        return n

    def _maybe_purge(self) -> None:
        now = time.time()
        if now - self._last_purge < 3600:
            return
        self._last_purge = now
        try:
            self.purge_now()
        except Exception as e:
            logger.debug(f"conversation memory purge: {e}")

    # model calls (through the gateway: policy, budgets, fallback; the mock answers both)
    def _call(self, system: str, messages: List[ChatMessage], schema: Dict[str, Any], key: str, ctx, usage_sink):
        if self.gateway is None:
            return ""
        model = self.gateway.model(self.settings.model, context=ctx, needs="structured_output")
        try:
            resp: ChatCompletion = model.chat_completions_create(
                messages=[ChatMessage.system(system)] + list(messages),
                response_format=ResponseFormat.of_schema(schema), temperature=0.0)
        except Exception as e:
            logger.info(f"conversation memory: {key} call failed ({e})")
            return ""
        if usage_sink is not None:
            usage_sink(resp)
        try:
            return str((resp.parsed() or {}).get(key) or "").strip()
        except Exception:
            return ""

    def _summarize(self, previous: str, turns: List[Dict[str, Any]], ctx, usage_sink) -> str:
        n = self.settings.summary_max_chars
        lines = []
        if previous:
            lines.append(f"Summary so far: {previous}")
        for t in turns:
            lines.append(f"User: {t['question']}")
            lines.append(f"SAJHA: {_clip(t.get('answer') or '', 1200)}")
        text = self._call(SUMMARY_PROMPT.format(n=n), [ChatMessage.user("\n".join(lines))], SUMMARY_SCHEMA,
                          "summary", ctx, usage_sink)
        return _clip(text, n)

    def _condense(self, question: str, history: List[ChatMessage], summary: str, ctx, usage_sink) -> str:
        system = CONDENSE_PROMPT + (f"\nEarlier in the conversation (summary): {summary}" if summary else "")
        return self._call(system, list(history) + [ChatMessage.user(question)], CONDENSE_SCHEMA,
                          "standalone_question", ctx, usage_sink)


# ── memory.mode: client ───────────────────────────────────────────

def client_history(messages: Any, max_turns: int = 6, max_chars: int = 2000) -> List[ChatMessage]:
    """The caller's ``[{role: user|assistant, content: str}]`` as ChatMessages: the last ``max_turns``
    exchanges (``2 * max_turns`` messages), each clipped to ``max_chars``. ``system`` and other roles
    are not accepted (a caller cannot replace the tool's instructions). Raises ValueError."""
    if messages is None:
        return []
    if not isinstance(messages, list):
        raise ValueError("messages must be a list of {role, content}")
    out: List[ChatMessage] = []
    for i, m in enumerate(messages):
        if not isinstance(m, dict) or not isinstance(m.get("content"), str):
            raise ValueError(f"messages[{i}] must be an object with a string content")
        role = m.get("role")
        if role not in ("user", "assistant"):
            raise ValueError(f"messages[{i}].role must be user or assistant")
        text = _clip(m["content"], max_chars)
        out.append(ChatMessage.user(text) if role == "user" else ChatMessage.assistant(text))
    keep = 2 * max(0, int(max_turns))
    return out[-keep:] if keep else []


# ── the scheduled purge: once per interval across every worker ────

PURGE_SLOT_PREFIX = "ai:memory:purge:"


class PurgeScheduler:
    """Runs :meth:`ConversationMemory.purge_now` every ``interval_s``. Every worker wakes in the same
    slot; the first to add the slot's key to the state store (``add`` is atomic in every backend)
    runs the purge, the others skip it. The purge is idempotent, so a lost slot costs nothing."""

    def __init__(self, memory: ConversationMemory, interval_s: float, state=None):
        self.memory = memory
        self.interval_s = max(30.0, float(interval_s))
        self._state = state
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_run: Optional[float] = None
        self.last_deleted = 0

    def state(self):
        if self._state is None:
            from sajha.core.state import get_state_store
            self._state = get_state_store()
        return self._state

    def claim(self, now: float) -> bool:
        from sajha.core.state import WORKER_ID
        slot = int(now // self.interval_s)
        return bool(self.state().add(f"{PURGE_SLOT_PREFIX}{slot}", WORKER_ID, ttl=self.interval_s * 2))

    def tick(self, now: Optional[float] = None) -> Optional[int]:
        """One scheduled attempt: purge when this worker wins the slot. None when it did not."""
        now = time.time() if now is None else now
        try:
            if not self.claim(now):
                return None
            self.last_deleted = self.memory.purge_now()
            self.last_run = now
            return self.last_deleted
        except Exception as e:
            logger.warning(f"conversation memory: scheduled purge failed: {e}")
            return None

    def _loop(self) -> None:
        iv = self.interval_s
        while True:
            wait = iv - (time.time() % iv) + random.uniform(1.0, 5.0)
            if self._stop.wait(wait):
                return
            self.tick()

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="sajha-memory-purge", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


_purger: Optional[PurgeScheduler] = None


def _purger_running() -> bool:
    return _purger is not None and _purger.running


def start_purge(memory: Optional[ConversationMemory] = None) -> bool:
    """Start the scheduled purge (app start-up). False when memory or the schedule is off."""
    global _purger
    if memory is None:
        from sajha.ai.llm import llm_factory
        gw = llm_factory()
        memory = ConversationMemory(None, getattr(getattr(gw, "settings", None), "memory", None))
    minutes = int(memory.tool_settings.purge_interval_minutes or 0)
    if not memory.enabled or minutes <= 0:
        return False
    shutdown_purge()
    _purger = PurgeScheduler(memory, minutes * 60)
    _purger.start()
    return True


def shutdown_purge() -> None:
    global _purger
    if _purger is not None:
        _purger.stop()
        _purger = None


def turn_view(t: Dict[str, Any]) -> Dict[str, Any]:
    return {"seq": t["seq"], "question": t["question"], "standalone": t.get("standalone") or None,
            "answer": t.get("answer") or "", "tools": [x for x in (t.get("tools") or "").split(",") if x],
            "stopped_by": t.get("stopped_by") or "", "confidence": t.get("confidence"),
            "created_ts": t.get("created_ts")}


def conversation_view(c: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": c["id"], "title": c.get("title") or "", "turns": int(c.get("turn_count") or 0),
            "summarized_through": int(c.get("summarized_through") or 0),
            "has_summary": bool(c.get("summary")), "created_ts": c.get("created_ts"),
            "updated_ts": c.get("updated_ts"), "tool_name": c.get("tool_name") or None,
            "expires_ts": c.get("expires_ts")}
