"""
Workowon API client: email/password login, automatic token refresh, and job posting.

Tokens are kept in .session.json (git-ignored) so a restart doesn't force a new login.
Access tokens live ~15 minutes; they are refreshed shortly before expiry, or on a 401.
"""
from __future__ import annotations

import base64
import json
import re
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


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def job_keys(company: Any, title: Any, city: Any, url: Any) -> set[str]:
    """Keys that identify the same job across sources and WorkOwon: its listing URL, and company + title + city
    (the same role reposted under another requisition or found on two sites counts as a duplicate)."""
    keys = set()
    link = re.sub(r"^https?://(www\.)?|#.*$|/+$", "", str(url or "").strip().lower())
    if link:
        keys.add("url:" + link)
    if _norm(company) and _norm(title):
        keys.add(f"job:{_norm(company)}|{_norm(title)}|{_norm(city)}")
    return keys


def record_keys(rec: dict) -> set[str]:
    """job_keys for a scraped record or a posting payload (both use the externalX field names)."""
    first = (rec.get("locations") or [{}])[0]
    return job_keys(rec.get("externalCompanyName"), rec.get("title"), first.get("city"), rec.get("externalListingUrl"))


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


def external_job_keys(get: Any) -> set[str]:
    """job_keys of every external job already on WorkOwon; get(path, params) makes an authorized GET."""
    keys: set[str] = set()
    page = 0
    while True:
        response = get("/api/jobs/admin/external-jobs", {"page": page, "pageSize": 100})
        if not response.ok:
            raise AuthError(_error_message(response))
        data = response.json().get("data") or {}
        for job in data.get("content") or []:
            city = ((job.get("locations") or [{}])[0]).get("city")
            keys |= job_keys(job.get("companyName"), job.get("title"), city, job.get("externalListingUrl"))
        page += 1
        if data.get("last", True) or page >= (data.get("totalPages") or 0):
            return keys


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

    def external_job_keys(self) -> set[str]:
        return external_job_keys(lambda path, params: self.request("GET", path, params=params))

    def post_external_job(self, payload: dict) -> tuple[bool, str, dict]:
        """Returns (ok, message, response_json)."""
        response = self.request("POST", "/api/jobs/admin/external-jobs", json=payload)
        try:
            body = response.json()
        except ValueError:
            body = {}
        return response.ok, (body.get("message") if body else None) or _error_message(response), body
