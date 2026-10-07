"""
SAJHA Intelligence Layer — error taxonomy.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Every provider maps its HTTP/SDK failures onto these, so the gateway can retry and fall
back without knowing the vendor.

| Error                 | Meaning                    | Gateway reaction                         |
|-----------------------|----------------------------|------------------------------------------|
| RateLimited           | 429 or quota               | retry after the delay, then fall back    |
| ProviderUnavailable   | 5xx, timeout, connection   | retry with backoff, then fall back       |
| AuthenticationFailed  | bad or missing key         | no retry; mark provider unhealthy        |
| ContextTooLong        | prompt over the window     | next candidate (a larger model)          |
| ContentFiltered       | refused by provider safety | no retry; returned as a refusal          |
| UnsupportedFeature    | e.g. tools without support | next candidate by capability             |
| ModelFailed           | the model itself failed    | next candidate (no retry, breaker intact)|
|                       | (Gemini MALFORMED_FUNCTION_CALL, Cohere ERROR / TIMEOUT)              |
| InvalidRequest        | malformed request          | no retry                                 |
| PolicyDenied          | role policy forbids it     | no call                                  |
| BudgetExceeded        | token budget spent         | no call                                  |
| NoModelAvailable      | no candidate left          | raised to the caller                     |
"""

from typing import Optional


class LLMError(Exception):
    retryable: bool = False
    code: str = "llm_error"

    def __init__(self, message: str = "", *, provider: str = "", model: str = "",
                 status: Optional[int] = None):
        super().__init__(message or self.__class__.__name__)
        self.provider = provider
        self.model = model
        self.status = status

    def to_dict(self):
        return {"error": self.code, "message": str(self), "provider": self.provider, "model": self.model}


class RateLimited(LLMError):
    retryable = True
    code = "rate_limited"

    def __init__(self, message: str = "", *, retry_after: Optional[float] = None, **kw):
        super().__init__(message, **kw)
        self.retry_after = retry_after


class ProviderUnavailable(LLMError):
    retryable = True
    code = "provider_unavailable"


class AuthenticationFailed(LLMError):
    code = "authentication_failed"


class ContextTooLong(LLMError):
    code = "context_too_long"


class ContentFiltered(LLMError):
    code = "content_filtered"


class UnsupportedFeature(LLMError):
    code = "unsupported_feature"


class ModelFailed(LLMError):
    """The vendor answered, but the generation itself failed (a non-standard ``error`` finish).

    Responses carry only the standard finish reasons, so a vendor's error finish becomes this
    error and the gateway moves to the alias's next candidate."""
    code = "model_failed"


class InvalidRequest(LLMError):
    code = "invalid_request"


class PolicyDenied(LLMError):
    code = "policy_denied"


class BudgetExceeded(LLMError):
    code = "budget_exceeded"


class NoModelAvailable(LLMError):
    code = "no_model_available"


class ConfigurationError(LLMError):
    code = "configuration_error"


ERROR_BY_NAME = {
    "rate_limited": RateLimited,
    "unavailable": ProviderUnavailable,
    "provider_unavailable": ProviderUnavailable,
    "auth": AuthenticationFailed,
    "authentication_failed": AuthenticationFailed,
    "context_too_long": ContextTooLong,
    "content_filtered": ContentFiltered,
    "unsupported": UnsupportedFeature,
    "invalid_request": InvalidRequest,
    "model_failed": ModelFailed,
}
