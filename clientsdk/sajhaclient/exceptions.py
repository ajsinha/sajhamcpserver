"""
SAJHA MCP Server — Client SDK Exceptions
"""


class SajhaError(Exception):
    """Base exception for all SAJHA client errors."""
    pass


class SajhaConnectionError(SajhaError):
    """Cannot connect to SAJHA server."""
    pass


class SajhaAuthError(SajhaError):
    """Authentication failed (invalid credentials, expired token, etc.)."""
    pass


class SajhaPermissionError(SajhaError):
    """Authorization failed (insufficient permissions)."""
    pass


class SajhaNotFoundError(SajhaError):
    """Requested resource not found (tool, user, etc.)."""
    pass


class SajhaValidationError(SajhaError):
    """Invalid input parameters."""
    pass


class SajhaServerError(SajhaError):
    """Server-side error (500)."""
    pass


class SajhaMCPError(SajhaError):
    """MCP protocol error (JSON-RPC error response)."""

    def __init__(self, code: int, message: str, data=None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"MCP Error {code}: {message}")


class SajhaA2AError(SajhaError):
    """A2A protocol error."""
    pass
