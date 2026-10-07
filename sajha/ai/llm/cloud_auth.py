"""
SAJHA Intelligence Layer — short-lived cloud credentials for model providers.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A TokenSource fetches an OAuth access token, caches it, and fetches a new one shortly before
it expires (``refresh_margin_s``), so a provider asks for a token on every request and pays for
a token call only when one is due. Thread-safe; ``atoken()`` is the async twin.

    GoogleTokenSource   Vertex AI (Gemini, Claude). Sources, first match wins:
                        a credentials file (``credentials_file`` or GOOGLE_APPLICATION_CREDENTIALS):
                          service_account   -> signed JWT assertion (RS256), exchanged at token_uri
                          authorized_user   -> refresh-token grant
                          external_account  -> workload identity federation via google-auth, if installed
                        otherwise the metadata server: GKE workload identity, Cloud Run, Compute Engine
    EntraTokenSource    Azure OpenAI with Microsoft Entra ID. Sources (``mode: auto`` picks):
                          client_secret      -> client-credentials grant
                          workload_identity  -> federated token file (AZURE_FEDERATED_TOKEN_FILE) as
                                                client assertion (AKS workload identity)
                          managed_identity   -> App Service / Functions identity endpoint, else IMDS

No vendor SDK is needed; tokens never appear in logs or in the effective-configuration view.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from sajha.ai.llm.errors import AuthenticationFailed, ConfigurationError, LLMError, ProviderUnavailable

logger = logging.getLogger(__name__)

GOOGLE_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
ENTRA_SCOPE = "https://cognitiveservices.azure.com/.default"
ENTRA_AUTHORITY = "https://login.microsoftonline.com"


class TokenSource:
    """Base: cached access token with refresh before expiry. Subclasses implement ``_fetch``."""

    refresh_margin_s: float = 300.0
    name: str = "token"

    def __init__(self, *, transport: Any = None, timeout_s: float = 10.0, environ: Optional[Dict[str, str]] = None):
        self._transport = transport
        self._timeout = timeout_s
        self.environ = os.environ if environ is None else environ
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._expires_at = 0.0
        self.fetches = 0

    def _client(self) -> httpx.Client:
        kw: Dict[str, Any] = {"timeout": self._timeout}
        if self._transport is not None:
            kw["transport"] = self._transport
        return httpx.Client(**kw)

    def _fetch(self) -> Tuple[str, float]:            # pragma: no cover - abstract
        """(access token, seconds until it expires)."""
        raise NotImplementedError

    def valid(self) -> bool:
        return bool(self._token) and time.time() < self._expires_at - self.refresh_margin_s

    def token(self) -> str:
        if self.valid():
            return self._token            # type: ignore[return-value]
        with self._lock:
            if self.valid():
                return self._token        # type: ignore[return-value]
            try:
                tok, ttl = self._fetch()
            except LLMError:
                raise
            except httpx.HTTPError as e:
                raise ProviderUnavailable(f"{self.name}: token endpoint unreachable ({e.__class__.__name__})") from None
            self.fetches += 1
            self._token, self._expires_at = tok, time.time() + max(60.0, float(ttl or 3600))
            return tok

    async def atoken(self) -> str:
        if self.valid():
            return self._token            # type: ignore[return-value]
        import anyio
        return await anyio.to_thread.run_sync(self.token)

    def invalidate(self) -> None:
        self._token, self._expires_at = None, 0.0

    def _json(self, resp: httpx.Response) -> Dict[str, Any]:
        if resp.status_code >= 400:
            detail = resp.text[:300]
            if resp.status_code >= 500:
                raise ProviderUnavailable(f"{self.name}: token endpoint HTTP {resp.status_code}: {detail}")
            raise AuthenticationFailed(f"{self.name}: token request refused (HTTP {resp.status_code}): {detail}")
        try:
            return resp.json()
        except Exception:
            raise AuthenticationFailed(f"{self.name}: token endpoint returned no JSON") from None


def _ttl(data: Dict[str, Any]) -> float:
    if data.get("expires_in") not in (None, ""):
        return float(data["expires_in"])
    if data.get("expires_on") not in (None, ""):
        try:
            return float(data["expires_on"]) - time.time()
        except ValueError:
            pass
    return 3600.0


# ── Google (Vertex AI) ───────────────────────────────────────────

class GoogleTokenSource(TokenSource):
    name = "google-auth"

    def __init__(self, credentials_file: Optional[str] = None, scopes: str = GOOGLE_SCOPE, **kw):
        super().__init__(**kw)
        self.credentials_file = credentials_file
        self.scopes = scopes

    @property
    def path(self) -> str:
        return self.credentials_file or self.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

    def describe(self) -> str:
        if not self.path:
            return "metadata server (workload identity)"
        try:
            return f"{json.load(open(self.path)).get('type', 'unknown')} credentials file"
        except Exception:
            return "credentials file (unreadable)"

    def _fetch(self) -> Tuple[str, float]:
        if not self.path:
            return self._metadata()
        try:
            with open(self.path, encoding="utf-8") as f:
                info = json.load(f)
        except Exception as e:
            raise ConfigurationError(f"google credentials file {self.path!r} unreadable: {e}") from None
        kind = info.get("type")
        if kind == "service_account":
            return self._service_account(info)
        if kind == "authorized_user":
            return self._form(info.get("token_uri") or GOOGLE_TOKEN_URI, {
                "grant_type": "refresh_token", "client_id": info.get("client_id", ""),
                "client_secret": info.get("client_secret", ""), "refresh_token": info.get("refresh_token", "")})
        if kind == "external_account":
            return self._google_auth()
        raise ConfigurationError(f"google credentials of type {kind!r} are not supported")

    def _form(self, url: str, form: Dict[str, str]) -> Tuple[str, float]:
        with self._client() as c:
            data = self._json(c.post(url, data=form))
        if not data.get("access_token"):
            raise AuthenticationFailed(f"{self.name}: no access_token in the token response")
        return data["access_token"], _ttl(data)

    def _service_account(self, info: Dict[str, Any]) -> Tuple[str, float]:
        try:
            import jwt
        except ImportError:                       # pragma: no cover - PyJWT is a dependency
            return self._google_auth()
        now = int(time.time())
        token_uri = info.get("token_uri") or GOOGLE_TOKEN_URI
        claims = {"iss": info["client_email"], "scope": self.scopes, "aud": token_uri, "iat": now, "exp": now + 3600}
        headers = {"kid": info["private_key_id"]} if info.get("private_key_id") else None
        assertion = jwt.encode(claims, info["private_key"], algorithm="RS256", headers=headers)
        return self._form(token_uri, {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                      "assertion": assertion})

    def _metadata(self) -> Tuple[str, float]:
        host = self.environ.get("GCE_METADATA_HOST", "metadata.google.internal")
        url = f"http://{host}/computeMetadata/v1/instance/service-accounts/default/token"
        with self._client() as c:
            data = self._json(c.get(url, params={"scopes": self.scopes}, headers={"Metadata-Flavor": "Google"}))
        return data["access_token"], _ttl(data)

    def _google_auth(self) -> Tuple[str, float]:
        try:
            import google.auth
            import google.auth.transport.requests
        except ImportError:
            raise ConfigurationError("this Google credential type needs google-auth: pip install google-auth") from None
        if self.path:
            creds, _ = google.auth.load_credentials_from_file(self.path, scopes=[self.scopes])
        else:                                     # pragma: no cover - environment-dependent
            creds, _ = google.auth.default(scopes=[self.scopes])
        creds.refresh(google.auth.transport.requests.Request())
        ttl = (creds.expiry.timestamp() - time.time()) if getattr(creds, "expiry", None) else 3600.0
        return creds.token, ttl


# ── Microsoft Entra ID (Azure OpenAI) ────────────────────────────

class EntraTokenSource(TokenSource):
    name = "entra-id"

    def __init__(self, tenant_id: str = "", client_id: str = "", client_secret: Optional[str] = None, *,
                 federated_token_file: Optional[str] = None, scope: str = ENTRA_SCOPE,
                 authority: str = ENTRA_AUTHORITY, mode: str = "auto", **kw):
        super().__init__(**kw)
        self.tenant_id = tenant_id or self.environ.get("AZURE_TENANT_ID", "")
        self.client_id = client_id or self.environ.get("AZURE_CLIENT_ID", "")
        self.client_secret = client_secret or self.environ.get("AZURE_CLIENT_SECRET") or None
        self.federated_token_file = federated_token_file or self.environ.get("AZURE_FEDERATED_TOKEN_FILE") or None
        self.scope = scope
        self.authority = (authority or ENTRA_AUTHORITY).rstrip("/")
        self.mode = mode

    def effective_mode(self) -> str:
        if self.mode != "auto":
            return self.mode
        if self.client_secret:
            return "client_secret"
        if self.federated_token_file:
            return "workload_identity"
        return "managed_identity"

    def _fetch(self) -> Tuple[str, float]:
        mode = self.effective_mode()
        if mode == "managed_identity":
            return self._managed_identity()
        if not self.tenant_id or not self.client_id:
            raise ConfigurationError(f"entra {mode} needs tenant_id and client_id")
        form = {"grant_type": "client_credentials", "client_id": self.client_id, "scope": self.scope}
        if mode == "client_secret":
            if not self.client_secret:
                raise ConfigurationError("entra client_secret mode needs client_secret")
            form["client_secret"] = self.client_secret
        elif mode == "workload_identity":
            try:
                with open(self.federated_token_file or "", encoding="utf-8") as f:
                    assertion = f.read().strip()
            except Exception as e:
                raise ConfigurationError(f"entra workload identity: cannot read the federated token file: {e}") from None
            form["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            form["client_assertion"] = assertion
        else:
            raise ConfigurationError(f"entra: unknown mode {mode!r}")
        url = f"{self.authority}/{self.tenant_id}/oauth2/v2.0/token"
        with self._client() as c:
            data = self._json(c.post(url, data=form))
        if not data.get("access_token"):
            raise AuthenticationFailed("entra-id: no access_token in the token response")
        return data["access_token"], _ttl(data)

    def _managed_identity(self) -> Tuple[str, float]:
        resource = self.scope[:-len("/.default")] if self.scope.endswith("/.default") else self.scope
        endpoint, secret = self.environ.get("IDENTITY_ENDPOINT"), self.environ.get("IDENTITY_HEADER")
        params = {"resource": resource}
        if self.client_id:
            params["client_id"] = self.client_id
        with self._client() as c:
            if endpoint and secret:               # App Service / Functions / Container Apps
                params["api-version"] = "2019-08-01"
                resp = c.get(endpoint, params=params, headers={"X-IDENTITY-HEADER": secret})
            else:                                 # VM / VMSS / AKS node identity (IMDS)
                params["api-version"] = "2018-02-01"
                resp = c.get("http://169.254.169.254/metadata/identity/oauth2/token", params=params,
                             headers={"Metadata": "true"})
            data = self._json(resp)
        return data["access_token"], _ttl(data)
