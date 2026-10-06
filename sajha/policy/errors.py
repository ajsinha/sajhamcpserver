"""
SAJHA MCP Server — policy outcomes that stop a tool call.

Each is a ``PermissionError`` so code that already treats "access denied" specially keeps
doing so; each carries what a transport needs to answer: an HTTP status, the rule that
decided, and (for approvals) the approval id. Design: docs/architecture/Policy and Audit.md.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class PolicyError(PermissionError):
    """A policy stopped the call."""

    kind = 'denied'
    http_status = 403

    def __init__(self, message: str, *, tool: str = '', rule: str = '', reason: str = ''):
        super().__init__(message)
        self.message = message
        self.tool = tool
        self.rule = rule
        self.reason = reason or message

    def to_dict(self) -> Dict[str, Any]:
        return {'kind': self.kind, 'tool': self.tool, 'rule': self.rule, 'reason': self.reason}


class PolicyDenied(PolicyError):
    """A deny rule, a violated argument constraint, a declined confirmation or a blocked output."""


class ApprovalRequired(PolicyError):
    """The call needs a human approval first; ``approval_id`` names the pending approval."""

    kind = 'approval_required'
    http_status = 202

    def __init__(self, message: str, *, approval_id: str = '', status: str = 'pending', interactive: bool = False,
                 **kw):
        super().__init__(message, **kw)
        self.approval_id = approval_id
        self.status = status
        self.interactive = interactive      # the caller confirms (Ask SAJHA), not an administrator

    def to_dict(self) -> Dict[str, Any]:
        return {**super().to_dict(), 'approval_id': self.approval_id, 'status': self.status,
                'interactive': self.interactive}


class RateLimited(PolicyError):
    """A rate limit or quota of a rule is exhausted."""

    kind = 'rate_limited'
    http_status = 429

    def __init__(self, message: str, *, retry_after: Optional[float] = None, **kw):
        super().__init__(message, **kw)
        self.retry_after = retry_after

    def to_dict(self) -> Dict[str, Any]:
        return {**super().to_dict(), 'retry_after': self.retry_after}
