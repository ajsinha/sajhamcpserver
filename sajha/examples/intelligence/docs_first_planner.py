"""
Example Planner: look in SAJHA's documentation first, then let ``react`` finish.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

The worked example of docs/architecture/Extending the Intelligence Layer.md (section 4.5).
For a how-to question about SAJHA itself, the first step searches the guides with
``sajha_search_docs`` (only if the shortlist offered it: the service decides what the caller
may run); every later step is the default ``react`` planner, which now sees the passages in
the history. Any other question goes to ``react`` straight away.

    ai:
      ask:
        planner: sajha.examples.intelligence.docs_first_planner:DocsFirstPlanner
        planner_config:
          docs_first: {pattern: '\\b(how (do|can) i|configure|set up|enable)\\b'}
"""

from __future__ import annotations

import re

from sajha.ai.llm.canonical import ToolCall
from sajha.ai.planners import CallTools, DelegatingPlanner, PlanState, PlannerConfig, register_planner

SEARCH_TOOL = "sajha_search_docs"


class DocsFirstConfig(PlannerConfig):
    pattern: str = r"\b(how (do|can) i|configure|set up|enable|what is)\b"
    top_k: int = 3
    then: str = "react"                      # the planner that finishes the ask


@register_planner
class DocsFirstPlanner(DelegatingPlanner):
    name = "docs_first"
    description = "Searches SAJHA's documentation first for how-to questions, then hands over to react."
    config_model = DocsFirstConfig

    def start(self, state: PlanState) -> None:
        self.searched = False
        wants_docs = re.search(self.config.pattern, state.question, re.IGNORECASE) is not None
        if not wants_docs or SEARCH_TOOL not in state.offered:
            self.hand_to(self.config.then, state)        # not a how-to question, or not allowed

    def next_action(self, state: PlanState):
        if self.delegate is not None:
            return self.delegate.next_action(state)
        if not self.searched:
            self.searched = True
            args = {"query": state.question, "top_k": self.config.top_k}
            call = ToolCall.of("docs_1", SEARCH_TOOL, args)
            state.emit({"type": "plan", "planner": self.name, "revision": 0, "steps": [
                {"id": "s1", "tool": SEARCH_TOOL, "arguments": args, "depends_on": [],
                 "why": "look it up in the guides", "status": "pending", "call_id": call.id}]})
            return CallTools([call])
        self.hand_to(self.config.then, state)            # the passages are in state.messages now
        return self.delegate.next_action(state)
