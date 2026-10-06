"""
SAJHA MCP Server — conversation memory for multi-turn asks.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A conversation belongs to one user and is never visible to another: every read, write and
delete is filtered by the caller's user id, so a conversation id alone gives nothing away.

Each ask in a conversation sees (sajha/ai/intelligence.py):

* the most recent ``ai.memory.history_turns`` turns verbatim (question and answer);
* a summary of the older turns, written through the gateway (``ai.memory.model``) once they
  leave the verbatim window, and kept on the conversation row;
* the question rewritten as a standalone question (``ai.memory.condense``), so a follow-up
  such as "and from 100 to 150?" finds the right tools.

Storage: two tables, ``ai_conversations`` and ``ai_conversation_turns`` (SQLAlchemy Core,
below). SQLite creates them on first use; on PostgreSQL they come from
db/scripts/postgresql/schema.sql (SAJHA runs no DDL there). Conversations idle longer than
``ai.memory.retention_days`` are deleted, as are a user's oldest beyond
``max_conversations_per_user``. Users delete their own history with
``DELETE /api/ai/conversations``.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import (Column, Float, ForeignKey, Index, Integer, MetaData, String, Table, Text, and_, delete,
                        func, insert, select, update)

from sajha.ai.llm.settings import MemorySettings
from sajha.ai.llm.types import ChatRequest, Message, RequestContext

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
    Index('ix_ai_conversations_user_updated', 'user_id', 'updated_ts'),
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


class MemorySchemaMissing(RuntimeError):
    """PostgreSQL without the conversation tables (they come from the schema file)."""


class ConversationNotFound(LookupError):
    """No such conversation for this user (another user's conversation is reported the same way)."""


@dataclass
class MemoryContext:
    conversation_id: str
    is_new: bool
    history: List[Message] = field(default_factory=list)   # earlier turns, oldest first
    summary: str = ""
    standalone: str = ""
    turn: int = 1                                           # the number of this turn


def valid_id(cid: Any) -> bool:
    return isinstance(cid, str) and bool(_ID.match(cid))


# ── storage ───────────────────────────────────────────────────────

class ConversationStore:
    """Per-user conversations and turns. Every method takes the owner's user id."""

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

    def get(self, conversation_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        if not valid_id(conversation_id) or not user_id:
            return None
        self.ensure_tables()
        with self.engine.connect() as c:
            row = c.execute(select(ai_conversations).where(and_(
                ai_conversations.c.id == conversation_id, ai_conversations.c.user_id == user_id))).mappings().first()
        return dict(row) if row else None

    def list(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        self.ensure_tables()
        with self.engine.connect() as c:
            rows = c.execute(select(ai_conversations).where(ai_conversations.c.user_id == user_id)
                             .order_by(ai_conversations.c.updated_ts.desc()).limit(limit)).mappings().all()
        return [dict(r) for r in rows]

    def turns(self, conversation_id: str, user_id: str) -> List[Dict[str, Any]]:
        self.ensure_tables()
        t = ai_conversation_turns
        with self.engine.connect() as c:
            rows = c.execute(select(t).where(and_(t.c.conversation_id == conversation_id, t.c.user_id == user_id))
                             .order_by(t.c.seq)).mappings().all()
        return [dict(r) for r in rows]

    def add_turn(self, conversation_id: str, user_id: str, *, question: str, standalone: str, answer: str,
                 tools: List[str], stopped_by: str, confidence: float, title: str = "") -> int:
        """Append a turn (creating the conversation on its first turn). Returns the turn's number."""
        self.ensure_tables()
        now = time.time()
        conv, t = ai_conversations, ai_conversation_turns
        with self.engine.begin() as c:
            row = c.execute(select(conv.c.user_id, conv.c.turn_count).where(conv.c.id == conversation_id)).first()
            if row is None:
                c.execute(insert(conv).values(id=conversation_id, user_id=user_id, title=(title or question)[:200],
                                              summary=None, summarized_through=0, turn_count=0,
                                              created_ts=now, updated_ts=now))
                count = 0
            elif row[0] != user_id:
                raise ConversationNotFound(conversation_id)
            else:
                count = int(row[1] or 0)
            seq = count + 1
            c.execute(insert(t).values(id=uuid.uuid4().hex, conversation_id=conversation_id, user_id=user_id, seq=seq,
                                       question=question, standalone=standalone or None, answer=answer,
                                       tools=",".join(tools)[:2000], stopped_by=stopped_by[:40],
                                       confidence=float(confidence), created_ts=now))
            c.execute(update(conv).where(conv.c.id == conversation_id).values(turn_count=seq, updated_ts=now))
        return seq

    def set_summary(self, conversation_id: str, user_id: str, summary: str, through: int) -> None:
        self.ensure_tables()
        conv = ai_conversations
        with self.engine.begin() as c:
            c.execute(update(conv).where(and_(conv.c.id == conversation_id, conv.c.user_id == user_id))
                      .values(summary=summary, summarized_through=through))

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

    def purge(self, retention_days: int, max_per_user: int) -> int:
        """Delete conversations idle past the retention, and each user's oldest beyond the cap."""
        self.ensure_tables()
        conv, t = ai_conversations, ai_conversation_turns
        doomed: List[str] = []
        with self.engine.begin() as c:
            if retention_days and retention_days > 0:
                cutoff = time.time() - retention_days * 86400
                doomed += [r[0] for r in c.execute(select(conv.c.id).where(conv.c.updated_ts < cutoff))]
            if max_per_user and max_per_user > 0:
                over = c.execute(select(conv.c.user_id).group_by(conv.c.user_id)
                                 .having(func.count(conv.c.id) > max_per_user)).all()
                for (uid,) in over:
                    ids = [r[0] for r in c.execute(select(conv.c.id).where(conv.c.user_id == uid)
                                                   .order_by(conv.c.updated_ts.desc()))]
                    doomed += ids[max_per_user:]
            doomed = sorted(set(doomed))
            for i in range(0, len(doomed), 200):
                part = doomed[i:i + 200]
                c.execute(delete(t).where(t.c.conversation_id.in_(part)))
                c.execute(delete(conv).where(conv.c.id.in_(part)))
        return len(doomed)


# ── memory: context for the next ask, and recording its turn ──────

def _clip(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


class ConversationMemory:
    def __init__(self, gateway, settings: Optional[MemorySettings] = None, store: Optional[ConversationStore] = None):
        self.gateway = gateway
        self.settings = settings or MemorySettings()
        self.store = store or ConversationStore()
        self._last_purge = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enabled)

    def exists(self, conversation_id: str, user_id: str) -> bool:
        return self.store.get(conversation_id, user_id) is not None

    def context(self, conversation_id: Optional[str], question: str, ctx: RequestContext,
                usage_sink=None) -> MemoryContext:
        """History, summary and the standalone question for an ask in this conversation.

        ``conversation_id`` "new" (or None) starts one; an id that is not this user's raises
        ConversationNotFound. ``usage_sink(resp)`` receives each model response (tokens)."""
        if not ctx.user_id:
            raise ConversationNotFound("conversations belong to signed-in users")
        if not conversation_id or conversation_id == NEW:
            return MemoryContext(str(uuid.uuid4()), True, standalone=question)
        conv = self.store.get(conversation_id, ctx.user_id)
        if conv is None:
            raise ConversationNotFound(conversation_id)
        turns = self.store.turns(conversation_id, ctx.user_id)
        s = self.settings
        window = max(0, int(s.history_turns))
        recent = turns[-window:] if window else []
        older = turns[: len(turns) - len(recent)]
        summary = conv.get("summary") or ""
        through = int(conv.get("summarized_through") or 0)
        if older and s.summarize and older[-1]["seq"] > through:
            summary = self._summarize(summary, [t for t in older if t["seq"] > through], ctx, usage_sink) or summary
            if summary:
                self.store.set_summary(conversation_id, ctx.user_id, summary, older[-1]["seq"])
        elif older and not s.summarize:
            summary = ""
        history: List[Message] = []
        for t in recent:
            history.append(Message.user(t["question"]))
            history.append(Message.assistant(_clip(t.get("answer") or "", s.max_turn_chars)))
        standalone = question
        if s.condense and (history or summary):
            standalone = self._condense(question, history, summary, ctx, usage_sink) or question
        return MemoryContext(conversation_id, False, history, summary, standalone, len(turns) + 1)

    def record(self, mc: MemoryContext, ctx: RequestContext, question: str, result) -> Optional[int]:
        try:
            seq = self.store.add_turn(mc.conversation_id, ctx.user_id, question=question,
                                      standalone=mc.standalone if mc.standalone != question else "",
                                      answer=_clip(result.answer or "", self.settings.max_turn_chars),
                                      tools=[st.name for st in result.steps], stopped_by=result.stopped_by,
                                      confidence=result.confidence)
        except Exception as e:
            logger.warning(f"conversation memory: could not record the turn: {e}")
            return None
        self._maybe_purge()
        return seq

    def _maybe_purge(self) -> None:
        now = time.time()
        if now - self._last_purge < 3600:
            return
        self._last_purge = now
        try:
            n = self.store.purge(self.settings.retention_days, self.settings.max_conversations_per_user)
            if n:
                logger.info(f"conversation memory: deleted {n} expired conversation(s)")
        except Exception as e:
            logger.debug(f"conversation memory purge: {e}")

    # model calls (through the gateway: policy, budgets, fallback; the mock answers both)
    def _call(self, system: str, messages: List[Message], schema: Dict[str, Any], key: str, ctx, usage_sink):
        if self.gateway is None:
            return ""
        req = ChatRequest(messages, system=system, response_schema=schema, tool_choice="none",
                          temperature=0.0, metadata=ctx)
        try:
            resp = self.gateway.chat(req, model=self.settings.model, needs="structured_output")
        except Exception as e:
            logger.info(f"conversation memory: {key} call failed ({e})")
            return ""
        if usage_sink is not None:
            usage_sink(resp)
        try:
            return str((resp.json() or {}).get(key) or "").strip()
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
        text = self._call(SUMMARY_PROMPT.format(n=n), [Message.user("\n".join(lines))], SUMMARY_SCHEMA,
                          "summary", ctx, usage_sink)
        return _clip(text, n)

    def _condense(self, question: str, history: List[Message], summary: str, ctx, usage_sink) -> str:
        system = CONDENSE_PROMPT + (f"\nEarlier in the conversation (summary): {summary}" if summary else "")
        return self._call(system, list(history) + [Message.user(question)], CONDENSE_SCHEMA,
                          "standalone_question", ctx, usage_sink)


def turn_view(t: Dict[str, Any]) -> Dict[str, Any]:
    return {"seq": t["seq"], "question": t["question"], "standalone": t.get("standalone") or None,
            "answer": t.get("answer") or "", "tools": [x for x in (t.get("tools") or "").split(",") if x],
            "stopped_by": t.get("stopped_by") or "", "confidence": t.get("confidence"),
            "created_ts": t.get("created_ts")}


def conversation_view(c: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": c["id"], "title": c.get("title") or "", "turns": int(c.get("turn_count") or 0),
            "summarized_through": int(c.get("summarized_through") or 0),
            "has_summary": bool(c.get("summary")), "created_ts": c.get("created_ts"),
            "updated_ts": c.get("updated_ts")}
