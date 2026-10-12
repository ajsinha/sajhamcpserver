# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Conversation memory for LLM tools that record their own turns (SAJHA Net §12 "Memory", §13).

A tool that calls ``ConversationMemory.record`` with the names of the tools it used and no steps gets the
same treatment as one that passed its steps: a remote tool among them (a SAJHA Net proxy) makes the turn an
answer that rests on remote results, masked by the data classes of that tool's results.
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine

from sajha.net.integration import residency as NR


class Catalogs:
    def __init__(self, proxies):
        self._proxies = proxies


def proxy(instance, results=None):
    meta = {'net': 'acme-net', 'instance': instance, 'locality': 'remote'}
    if results:
        meta['data_classes'] = {'results': results}
    return SimpleNamespace(meta=meta)


def test_named_remote_tools_mask_the_turn(tmp_path, monkeypatch):
    from sajha.ai.llm.types import RequestContext
    from sajha.ai.memory import ConversationMemory, ConversationStore, MemoryContext
    import sajha.net.integration.catalogs as cat
    monkeypatch.setattr(cat, 'get_catalogs', lambda: Catalogs({
        'acme-net__cust-na__account_balance': proxy('cust-na', ['confidential']),
        'acme-net__cust-eu__rates': proxy('cust-eu')}))
    NR.set_settings(NR.ResidencySettings(memory_by_class={'confidential': 'none'}))
    try:
        steps = NR.steps_of_tools(['local_tool', 'acme-net__cust-na__account_balance', 'acme-net__cust-eu__rates'])
        assert [(s.name, s.net['instance'], s.net['data_classes']) for s in steps] == [
            ('acme-net__cust-na__account_balance', 'cust-na', ['confidential']),
            ('acme-net__cust-eu__rates', 'cust-eu', [])]
        store = ConversationStore(create_engine(f'sqlite:///{tmp_path / "m.db"}'))
        mem = ConversationMemory(None, store=store)
        ctx = RequestContext(user_id='alice')
        mc = MemoryContext(conversation_id='c' * 32, is_new=True)
        mem.record(mc, ctx, 'q', answer='The balance is 1843200.5 EUR.',
                   tools=['acme-net__cust-na__account_balance'])
        assert '1843200' not in store.turns('c' * 32, 'alice')[0]['answer']
        mc2 = MemoryContext(conversation_id='d' * 32, is_new=True)
        mem.record(mc2, ctx, 'q', answer='The rate is 4.25.', tools=['local_tool'])
        assert store.turns('d' * 32, 'alice')[0]['answer'] == 'The rate is 4.25.'       # local only: as written
    finally:
        NR.set_settings(None)
