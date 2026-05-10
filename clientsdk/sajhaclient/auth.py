"""
SAJHA MCP Server — Client SDK Authentication

Three authentication methods, all producing the same headers:

    # API Key (simplest)
    auth = ApiKeyAuth("sja_your_key_here")

    # JWT (username/password login)
    auth = JWTAuth("http://localhost:3002", "admin", "admin123")

    # OAuth (external IdP)
    auth = OAuthAuth(token_url, client_id, client_secret)

    # Use with any client
    client = SajhaClient(config, auth=auth)
"""

import json
import time
import urllib.request
import urllib.parse
import logging
from typing import Optional, Dict
from abc import ABC, abstractmethod

from sajhaclient.exceptions import SajhaAuthError

logger = logging.getLogger(__name__)


class AuthProvider(ABC):
    """Base class for all authentication providers."""

    @abstractmethod
    def get_headers(self) -> Dict[str, str]:
        """Return HTTP headers for authentication."""
        pass

    @abstractmethod
    def refresh_if_needed(self) -> None:
        """Refresh credentials if expired."""
        pass

    @property
    @abstractmethod
    def auth_type(self) -> str:
        """Return the auth type name."""
        pass


class NoAuth(AuthProvider):
    """No authentication — for public endpoints only."""

    def get_headers(self) -> Dict[str, str]:
        return {}

    def refresh_if_needed(self) -> None:
        pass

    @property
    def auth_type(self) -> str:
        return "none"


class ApiKeyAuth(AuthProvider):
    """
    API Key authentication.

    The simplest method — pass your sja_ key and it's included
    in every request via the X-API-Key header.

    Usage:
        auth = ApiKeyAuth("sja_your_key_here")
    """

    def __init__(self, api_key: str):
        if not api_key:
            raise SajhaAuthError("API key cannot be empty")
        self._api_key = api_key

    def get_headers(self) -> Dict[str, str]:
        return {"X-API-Key": self._api_key}

    def refresh_if_needed(self) -> None:
        pass  # API keys don't expire (unless revoked server-side)

    @property
    def auth_type(self) -> str:
        return "apikey"


class JWTAuth(AuthProvider):
    """
    JWT authentication via username/password login.

    Logs in to SAJHA, obtains a JWT token, and includes it in
    every request. Auto-refreshes when the token expires.

    Usage:
        auth = JWTAuth("http://localhost:3002", "admin", "admin123")

    Or with a pre-obtained token:
        auth = JWTAuth.from_token("eyJhbG...")
    """

    def __init__(self, base_url: str, username: str, password: str, timeout: int = 30):
        self._base_url = base_url.rstrip('/')
        self._username = username
        self._password = password
        self._timeout = timeout
        self._token: Optional[str] = None
        self._token_obtained_at: float = 0
        self._token_lifetime: int = 3600  # 1 hour default

        # Login immediately
        self._login()

    @classmethod
    def from_token(cls, token: str) -> 'JWTAuth':
        """Create JWTAuth from a pre-obtained token (no auto-refresh)."""
        instance = object.__new__(cls)
        instance._base_url = None
        instance._username = None
        instance._password = None
        instance._timeout = 30
        instance._token = token
        instance._token_obtained_at = time.time()
        instance._token_lifetime = 3600
        return instance

    def _login(self) -> None:
        """Authenticate and obtain JWT token."""
        url = f"{self._base_url}/api/auth/login"
        payload = json.dumps({
            "user_id": self._username,
            "password": self._password,
        }).encode('utf-8')

        try:
            req = urllib.request.Request(url, data=payload, headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            })
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                self._token = data.get('token')
                if not self._token:
                    raise SajhaAuthError(f"Login response missing token: {data}")
                self._token_obtained_at = time.time()
                logger.info(f"JWT auth: logged in as {self._username}")
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            raise SajhaAuthError(f"Login failed ({e.code}): {body}")
        except urllib.error.URLError as e:
            raise SajhaAuthError(f"Cannot connect to {self._base_url}: {e.reason}")

    def get_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def refresh_if_needed(self) -> None:
        """Re-login if token is near expiry (within 5 minutes)."""
        if not self._base_url or not self._username:
            return  # from_token() — can't refresh
        elapsed = time.time() - self._token_obtained_at
        if elapsed > (self._token_lifetime - 300):
            logger.info("JWT token near expiry, refreshing...")
            self._login()

    @property
    def token(self) -> Optional[str]:
        return self._token

    @property
    def auth_type(self) -> str:
        return "jwt"


class OAuthAuth(AuthProvider):
    """
    OAuth 2.0 Client Credentials authentication.

    Obtains an access token from the OAuth token endpoint and
    includes it in every request. Auto-refreshes on expiry.

    Usage:
        auth = OAuthAuth(
            token_url="https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            client_id="your-client-id",
            client_secret="your-client-secret",
            scope="api://sajha/.default"
        )
    """

    def __init__(self, token_url: str, client_id: str, client_secret: str,
                 scope: str = "", timeout: int = 30):
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._timeout = timeout
        self._token: Optional[str] = None
        self._token_obtained_at: float = 0
        self._token_lifetime: int = 3600

        # Obtain token immediately
        self._obtain_token()

    def _obtain_token(self) -> None:
        """Request access token from OAuth server."""
        payload = urllib.parse.urlencode({
            'grant_type': 'client_credentials',
            'client_id': self._client_id,
            'client_secret': self._client_secret,
            'scope': self._scope,
        }).encode('utf-8')

        try:
            req = urllib.request.Request(self._token_url, data=payload, headers={
                'Content-Type': 'application/x-www-form-urlencoded',
            })
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                self._token = data.get('access_token')
                if not self._token:
                    raise SajhaAuthError(f"OAuth response missing access_token: {data}")
                self._token_lifetime = data.get('expires_in', 3600)
                self._token_obtained_at = time.time()
                logger.info(f"OAuth token obtained (expires in {self._token_lifetime}s)")
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            raise SajhaAuthError(f"OAuth token request failed ({e.code}): {body}")
        except urllib.error.URLError as e:
            raise SajhaAuthError(f"Cannot reach OAuth server: {e.reason}")

    def get_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def refresh_if_needed(self) -> None:
        elapsed = time.time() - self._token_obtained_at
        if elapsed > (self._token_lifetime - 300):
            logger.info("OAuth token near expiry, refreshing...")
            self._obtain_token()

    @property
    def auth_type(self) -> str:
        return "oauth"
