"""
Example model: a fine-tuned OpenAI model injected into the existing ``openai`` provider.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

The worked example of docs/architecture/Extending the Intelligence Layer.md (section 3).
``@register_model`` binds one model class to one ``provider/model`` id; the provider's
``chat_model()`` builds it instead of its default class, and ``list_models()`` lists it
(source "registered") with the class's ``capabilities``. Wire code, auth, retries, error
mapping, streaming and native async are inherited from OpenAIChatModel; only the difference
is written, as an edit of the canonical request before the pass-through ``wire``.

A model id that only needs different capabilities or prices needs no code at all: list it
under the provider's ``models:`` in application.yml (or SAJHA_AI_OPENAI_MODELS as JSON).
"""

from __future__ import annotations

from sajha.ai.llm import ChatCompletionRequest, ChatMessage
from sajha.ai.llm.spi import ModelCapabilities, OpenAIChatModel, WireCall, register_model

RISK_MODEL = "ft:gpt-6.1-sol:acme:risk:001"


@register_model(provider="openai", model_id=RISK_MODEL)
class AcmeRiskModel(OpenAIChatModel):
    """The risk team's fine-tune: a house style prepended to every system prompt, a fixed seed."""

    capabilities = ModelCapabilities(
        tools=True, structured_output=True, vision=False, streaming=True,
        context_window=1_050_000, max_output_tokens=32_000,
        input_cost_per_mtok=3.00, output_cost_per_mtok=12.00,     # fine-tune prices, not the base model's
        tags=frozenset({"risk"}))
    HOUSE_STYLE = "House style: lead with the figure, then the method, then the caveats."
    SEED = 7

    def wire(self, request: ChatCompletionRequest, stream: bool) -> WireCall:
        """The canonical request is edited, then the inherited pass-through does the rest."""
        update = {}
        if not any(self.HOUSE_STYLE in m.text for m in request.messages if m.role == "system"):
            update["messages"] = [ChatMessage.system(self.HOUSE_STYLE)] + list(request.messages)
        if request.seed is None:
            update["seed"] = self.SEED
        return super().wire(request.model_copy(update=update) if update else request, stream)
