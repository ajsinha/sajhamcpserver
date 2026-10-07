"""
Blocks (design §11.4) and their publication (protocol §12).

A block is a local decision of one participant in one net, at one of five levels:

=========  ===========================================================================
level      effect at the participant that set it
=========  ===========================================================================
instance   no calls to or from ``target_instance``; its catalog and key records ignored
inbound    calls from ``target_instance`` refused
outbound   calls to ``target_instance`` not made (its tools hidden)
tool       ``direction: inbound``: calls to the host tool ``tool`` from ``target_instance``
           (or ``*``) refused; ``direction: outbound``: the remote tool ``tool`` (qualified
           name, glob allowed) hidden and not called
user       calls on behalf of ``user`` (``alice@risk-eu``) refused
=========  ===========================================================================

Blocks are enforced only by the participant that set them; each participant publishes its blocks
document (signed, ``type: "blocks"``) so every console can draw the net-wide picture.
:class:`BlockPublication` serves ``/sajhanet/v1/blocks``, puts the version in ``digests.blocks``,
pulls the documents of peers whose version increased and reports blocks that name this
participant (event ``blocked_by_peer``).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import fnmatch
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from sajha.net import ENDPOINT, crypto, schemas

logger = logging.getLogger(__name__)

P = ENDPOINT.rstrip('/')
LEVELS = ('instance', 'inbound', 'outbound', 'tool', 'user')
PUBLISHED_FIELDS = ('id', 'level', 'target_instance', 'tool', 'user', 'reason', 'set_at', 'expires_at')


def is_active(block: Dict[str, Any], now: float) -> bool:
    exp = block.get('expires_at')
    if not exp:
        return True
    try:
        return crypto.parse_rfc3339(exp) > now
    except Exception:
        return False


def active(blocks: List[Dict[str, Any]], now: float) -> List[Dict[str, Any]]:
    return [b for b in blocks or [] if isinstance(b, dict) and is_active(b, now)]


def _target(b: Dict[str, Any], instance: str) -> bool:
    t = b.get('target_instance')
    return t == '*' or t == instance


def match_inbound(blocks: List[Dict[str, Any]], now: float, sender: str) -> Optional[Dict[str, Any]]:
    """Host step 3 (§15.4): a block on the sending participant, entire or inbound."""
    for b in active(blocks, now):
        if b.get('level') in ('instance', 'inbound') and _target(b, sender):
            return b
    return None


def match_user(blocks: List[Dict[str, Any]], now: float, net_user: str) -> Optional[Dict[str, Any]]:
    """Host step 6: a block on the remote user ``alice@risk-eu``."""
    for b in active(blocks, now):
        if b.get('level') == 'user' and b.get('user') == net_user:
            return b
    return None


def match_tool(blocks: List[Dict[str, Any]], now: float, sender: str, tool: str) -> Optional[Dict[str, Any]]:
    """Host step 8: a block on the host tool ``tool`` for ``sender`` (or every sender)."""
    for b in active(blocks, now):
        if (b.get('level') == 'tool' and b.get('direction', 'inbound') == 'inbound' and _target(b, sender)
                and fnmatch.fnmatchcase(tool, str(b.get('tool') or ''))):
            return b
    return None


def match_outbound(blocks: List[Dict[str, Any]], now: float, host: str,
                   qualified: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Home side: the host blocked entirely or outbound, or the remote tool hidden."""
    for b in active(blocks, now):
        lv = b.get('level')
        if lv in ('instance', 'outbound') and _target(b, host):
            return b
        if (lv == 'tool' and b.get('direction') == 'outbound' and qualified and _target(b, host)
                and fnmatch.fnmatchcase(qualified, str(b.get('tool') or ''))):
            return b
    return None


def blocked_entirely(blocks: List[Dict[str, Any]], now: float, peer: str) -> bool:
    return any(b.get('level') == 'instance' and _target(b, peer) for b in active(blocks, now))


def published(b: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: b[k] for k in PUBLISHED_FIELDS if b.get(k) not in (None, '')}
    if b.get('withhold_reason'):
        out.pop('reason', None)
    if 'reason' in out:
        out['reason'] = str(out['reason'])[:500]
    return out


def document(net: str, instance: str, version: int, blocks: List[Dict[str, Any]], signer, now: float
             ) -> Dict[str, Any]:
    """The signed blocks document (§12): expired blocks omitted."""
    body = {'type': 'blocks', 'net': net, 'instance': instance, 'version': int(version),
            'blocks': [published(b) for b in active(blocks, now)][:1000]}
    return dict(body, signature=crypto.sign_record('blocks', body, signer.key, signer.keyid))


def acceptance_error(doc: Any, net: str, sender: str, certificate) -> Optional[str]:
    if not isinstance(doc, dict) or schemas.errors('blocks_document', doc):
        return 'schema'
    if doc['net'] != net:
        return 'net_mismatch'
    if doc['instance'] != sender:
        return 'not_home'
    sig = doc.get('signature') or {}
    if sig.get('keyid') != crypto.thumbprint(crypto.cert_der(certificate)):
        return 'signature_invalid'
    body = {k: v for k, v in doc.items() if k != 'signature'}
    if not crypto.verify_record('blocks', body, sig, certificate.public_key()):
        return 'signature_invalid'
    return None


class BlockPublication:
    """Publishes this participant's blocks in one net and keeps the peers' documents.

    ``local()`` returns ``(version, blocks)`` of this participant's own blocks in the net."""

    def __init__(self, node, local: Callable[[], Tuple[int, List[Dict[str, Any]]]], *,
                 skip: Optional[Callable[[str], bool]] = None):
        self.node = node
        self.local = local
        self.skip = skip or (lambda peer: False)

    def install(self) -> 'BlockPublication':
        n = self.node
        n.handlers[P + '/blocks'] = self.serve
        n.digest_sources['blocks'] = lambda: int(self.local()[0])
        if 'blocks' not in n.extra_features:
            n.extra_features.append('blocks')
        if self.tick not in n.tick_hooks:
            n.tick_hooks.append(self.tick)
        return self

    def serve(self, data: Any, v) -> Dict[str, Any]:
        version, blocks = self.local()
        return document(self.node.net, self.node.name, version, blocks, self.node.signer, self.node.clock())

    def peer_document(self, peer: str) -> Optional[Dict[str, Any]]:
        return self.node.kv.get(f'pblocks:{peer}')

    def peer_documents(self) -> Dict[str, Dict[str, Any]]:
        return {k[len('pblocks:'):]: v for k, v in self.node.kv.scan('pblocks:')}

    def pull(self, m: Dict[str, Any]) -> bool:
        x = self.node.request(m['record']['url'], P + '/blocks', {}, m['name'])
        why = acceptance_error(x.body, self.node.net, x.sender, x.verified.certificate)
        if why is not None:
            logger.warning(f'SAJHA Net {self.node.net}: blocks document of {m["name"]} ignored ({why})')
            return False
        held = self.peer_document(m['name']) or {}
        if int(held.get('version') or -1) >= int(x.body['version']) and held:
            return False
        self.node.kv.set(f'pblocks:{m["name"]}', x.body)
        self._report(m['name'], x.body)
        return True

    def _report(self, peer: str, doc: Dict[str, Any]) -> None:
        now = self.node.clock()
        mine = [b for b in active(doc.get('blocks') or [], now)
                if b.get('target_instance') in (self.node.name, '*')]
        self.node.event('blocked_by_peer', member=peer, blocks=mine)

    def tick(self) -> None:
        for m in self.node.members():
            if m['state'] not in ('alive', 'suspect') or 'blocks' not in (m['record'].get('features') or []):
                continue
            if self.skip(m['name']):
                continue
            theirs = int((m['record'].get('digests') or {}).get('blocks') or 0)
            held = self.peer_document(m['name'])
            if held is not None and int(held.get('version') or 0) >= theirs:
                continue
            if held is None and theirs == 0:
                continue
            try:
                self.pull(m)
            except Exception as e:
                logger.info(f'SAJHA Net {self.node.net}: blocks of {m["name"]} not pulled: {e}')
