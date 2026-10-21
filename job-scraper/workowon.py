"""
Workowon API client: email/password login, automatic token refresh, and job posting.

Tokens are kept in .session.json (git-ignored) so a restart doesn't force a new login.
Access tokens live ~15 minutes; they are refreshed shortly before expiry, or on a 401.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://api.workowon.com"
SESSION_FILE = Path(__file__).resolve().parent / ".session.json"
TIMEOUT = 30
REFRESH_MARGIN_SECONDS = 60


class AuthError(Exception):
    pass


def _find_key(data: Any, names: tuple[str, ...]) -> str | None:
    """Find the first string value under any of `names`, searching nested dicts (response shapes vary)."""
    if isinstance(data, dict):
        for name in names:
            if isinstance(data.get(name), str) and data[name]:
                return data[name]
        for value in data.values():
            found = _find_key(value, names)
            if found:
                return found
    return None


def _jwt_exp(token: str) -> float:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0))
    except (IndexError, ValueError):
        return 0.0


def _error_message(response: requests.Response) -> str:
    try:
        return response.json().get("message") or response.text[:300]
    except ValueError:
        return response.text[:300] or f"HTTP {response.status_code}"


class WorkowonClient:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.email: str | None = None
        if SESSION_FILE.exists():
            try:
                saved = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
                self.access_token = saved.get("accessToken")
                self.refresh_token = saved.get("refreshToken")
                self.email = saved.get("email")
            except (ValueError, OSError):
                pass

    def _save(self) -> None:
        SESSION_FILE.write_text(
            json.dumps({"accessToken": self.access_token, "refreshToken": self.refresh_token, "email": self.email}),
            encoding="utf-8",
        )
        SESSION_FILE.chmod(0o600)

    def _store_tokens(self, body: dict) -> None:
        access = _find_key(body, ("accessToken", "access_token", "token", "jwt"))
        if not access:
            raise AuthError("Login response did not contain an access token.")
        self.access_token = access
        self.refresh_token = _find_key(body, ("refreshToken", "refresh_token")) or self.refresh_token
        self._save()

    def login(self, email: str, password: str) -> None:
        response = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=TIMEOUT)
        if not response.ok:
            raise AuthError(_error_message(response))
        with self._lock:
            self.email = email
            self._store_tokens(response.json())

    def logout(self) -> None:
        with self._lock:
            self.access_token = self.refresh_token = self.email = None
            SESSION_FILE.unlink(missing_ok=True)

    def _refresh(self) -> None:
        if not self.refresh_token:
            raise AuthError("Session expired. Please log in again.")
        response = requests.post(f"{BASE_URL}/api/auth/refresh", json={"refreshToken": self.refresh_token}, timeout=TIMEOUT)
        if not response.ok:
            self.access_token = self.refresh_token = None
            SESSION_FILE.unlink(missing_ok=True)
            raise AuthError("Session expired. Please log in again.")
        self._store_tokens(response.json())

    def _valid_token(self) -> str:
        with self._lock:
            if not self.access_token and not self.refresh_token:
                raise AuthError("Not logged in.")
            if not self.access_token or _jwt_exp(self.access_token) - time.time() < REFRESH_MARGIN_SECONDS:
                self._refresh()
            return self.access_token

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        headers = {"Accept": "*/*", "Authorization": f"Bearer {self._valid_token()}"}
        response = requests.request(method, f"{BASE_URL}{path}", headers=headers, timeout=TIMEOUT, **kwargs)
        if response.status_code == 401:
            # Token revoked or clock skew: refresh once and retry.
            with self._lock:
                self._refresh()
            headers["Authorization"] = f"Bearer {self.access_token}"
            response = requests.request(method, f"{BASE_URL}{path}", headers=headers, timeout=TIMEOUT, **kwargs)
        return response

    def me(self) -> dict:
        response = self.request("GET", "/api/auth/me")
        if not response.ok:
            raise AuthError(_error_message(response))
        return response.json().get("data") or {}

    def post_external_job(self, payload: dict) -> tuple[bool, str, dict]:
        """Returns (ok, message, response_json)."""
        response = self.request("POST", "/api/jobs/admin/external-jobs", json=payload)
        try:
            body = response.json()
        except ValueError:
            body = {}
        return response.ok, (body.get("message") if body else None) or _error_message(response), body
