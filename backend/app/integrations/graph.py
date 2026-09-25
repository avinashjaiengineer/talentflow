"""Minimal Microsoft Graph client using the OAuth client-credentials flow.

Required application permissions (granted by a tenant admin):
  Mail.Send, Calendars.ReadWrite (Calendars.ReadBasic is enough for free/busy only)
"""

import threading
import time

import httpx

from ..config import Settings
from . import IntegrationError

GRAPH = "https://graph.microsoft.com/v1.0"


class GraphClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        missing = [k for k in ("ms_tenant_id", "ms_client_id", "ms_client_secret", "ms_sender") if not getattr(settings, k)]
        if missing:
            raise IntegrationError(f"Microsoft 365 is not configured: set {', '.join(m.upper() for m in missing)}")
        self.settings = settings
        self.sender = settings.ms_sender
        self._http = httpx.Client(timeout=30, transport=transport)
        self._token: str | None = None
        self._expires = 0.0
        self._lock = threading.Lock()

    def _access_token(self) -> str:
        with self._lock:
            if self._token and time.monotonic() < self._expires - 60:
                return self._token
            s = self.settings
            try:
                r = self._http.post(
                    f"https://login.microsoftonline.com/{s.ms_tenant_id}/oauth2/v2.0/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": s.ms_client_id,
                        "client_secret": s.ms_client_secret,
                        "scope": "https://graph.microsoft.com/.default",
                    },
                )
            except httpx.HTTPError as e:
                raise IntegrationError(f"Could not reach Microsoft sign-in: {e}", retryable=True) from e
            if r.status_code != 200:
                raise IntegrationError(f"Microsoft 365 sign-in failed ({r.status_code}): {_error_text(r)}")
            body = r.json()
            self._token = body["access_token"]
            self._expires = time.monotonic() + int(body.get("expires_in", 3600))
            return self._token

    def request(self, method: str, path: str, *, json: dict | None = None, headers: dict | None = None) -> httpx.Response:
        try:
            r = self._http.request(
                method, GRAPH + path, json=json,
                headers={"Authorization": f"Bearer {self._access_token()}", **(headers or {})},
            )
        except httpx.HTTPError as e:
            raise IntegrationError(f"Could not reach Microsoft Graph: {e}", retryable=True) from e
        if r.status_code >= 400:
            retryable = r.status_code == 429 or r.status_code >= 500
            raise IntegrationError(f"Microsoft Graph error {r.status_code}: {_error_text(r)}", retryable=retryable)
        return r


def _error_text(r: httpx.Response) -> str:
    try:
        body = r.json()
        err = body.get("error")
        if isinstance(err, dict):
            return err.get("message") or err.get("code") or r.text[:200]
        return body.get("error_description") or str(err) or r.text[:200]
    except ValueError:
        return r.text[:200]
