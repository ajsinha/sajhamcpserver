"""
SWIM membership rules that do not depend on transport (protocol §9): incarnations, the merge
rules of §9.4 as a pure decision, the dissemination bound of §9.6, and the saved peer list of §9.9.

The gossip agent that applies them (ping, ping-req, suspicion, sync, leave, dead probing) is
:class:`sajha.net.node.NetNode`.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from typing import Any, Dict, List, Optional

from sajha.net.models import PRECEDENCE


def new_incarnation(now_ms: int, last: Optional[int]) -> int:
    """§9.3: chosen when the gossip agent starts, and to refute a claim."""
    return max(int(now_ms), int(last or 0) + 1)


def dissemination_limit(members: int, factor: int = 3) -> int:
    """§9.6: each change is sent at most ``λ × ⌈log2(n + 1)⌉`` times."""
    return max(1, factor * math.ceil(math.log2(max(1, members) + 1)))


KEEP = 'keep'          # ignore the incoming entry
REPLACE = 'replace'    # take the incoming record and state
STATE = 'state'        # keep the held record, take the incoming state
RECORD = 'record'      # take the incoming record (higher seq), state by precedence


def decide_merge(held: Optional[Dict[str, Any]], incoming: Dict[str, Any]) -> tuple:
    """§9.4 rules 2-5 for two entries about the same instance (already verified, rule 1).

    Returns ``(action, record, state)``: the record and state the receiver should hold afterwards.
    A ``left`` state is honoured only with a record whose ``leaving`` is true (§9.2)."""
    u_rec, u_state = incoming['record'], incoming['state']
    if u_state == 'left' and not u_rec.get('leaving'):
        u_state = None                                   # §9.2: invalid left; at most the record counts
    if held is None:
        return REPLACE, u_rec, u_state or 'alive'
    e_rec, e_state = held['record'], held['state']
    ui, ei = int(u_rec['incarnation']), int(e_rec['incarnation'])
    if ui > ei:
        return REPLACE, u_rec, u_state or 'alive'
    if ui < ei:
        return KEEP, e_rec, e_state
    rec = e_rec
    action = KEEP
    if int(u_rec['seq']) > int(e_rec['seq']):
        rec, action = u_rec, RECORD
    state = e_state
    if u_state and PRECEDENCE[u_state] > PRECEDENCE[e_state]:
        if u_state != 'left' or rec.get('leaving'):
            state = u_state
            action = RECORD if action == RECORD else STATE
    return action, rec, state


# ── the saved peer list (§9.9, design §6.6) ─────────────────────────

class PeerCache:
    """One net's saved peers on local disk: written atomically with owner-only permissions."""

    def __init__(self, path: str):
        self.path = path

    def load(self) -> Dict[str, Any]:
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                doc = json.load(f)
            return doc if isinstance(doc, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, doc: Dict[str, Any]) -> None:
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, mode=0o700, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix='.peers-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(doc, f, indent=1, sort_keys=True)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def update(self, **fields) -> Dict[str, Any]:
        doc = self.load()
        doc.update(fields)
        self.save(doc)
        return doc


def saved_peers_to_try(doc: Dict[str, Any], now: float, max_age_days: float) -> List[Dict[str, Any]]:
    """Saved members, most recently seen first, skipping those not seen within ``max_age_days``."""
    out = []
    for m in doc.get('members') or []:
        try:
            seen = float(m.get('last_seen') or 0)
        except (TypeError, ValueError):
            continue
        if not m.get('url') or not m.get('name') or now - seen > max_age_days * 86400:
            continue
        out.append(m)
    return sorted(out, key=lambda m: -float(m['last_seen']))
