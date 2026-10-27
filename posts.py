"""
Community posts: several WorkOwon accounts to post from, and Gemini help to write or rewrite a post.

Accounts are any WorkOwon users (not only admins). Each keeps its own tokens in
.post_accounts/<hash>.json (git-ignored), so you can switch between them without logging in again.

AI is opt-in: it only runs when the user clicks a style or sends a prompt on the Post page.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from workowon import AuthError, WorkowonClient

BASE_DIR = Path(__file__).resolve().parent
ACCOUNTS_DIR = BASE_DIR / ".post_accounts"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-flash-lite-latest"
TIMEOUT = 90
MAX_CONTENT_CHARS = 10000  # API limit for post content
MAX_TITLE_CHARS = 300
POST_TAGS = {"p", "strong", "em", "ul", "ol", "li", "br"}

# Writing styles offered on the Post page: (label, instructions for the AI).
STYLES = {
    "professional": ("Professional post", "Polished and credible, like a respected professional on LinkedIn. Clear hook, 2-4 short paragraphs or a short list, a takeaway at the end. No hype."),
    "short": ("Short but real", "Short, honest and human: 2-5 short lines, plain words, no corporate buzzwords, no fake enthusiasm. Sounds like a real person talking."),
    "story": ("Storytelling", "Tell it as a short personal story: a moment or situation, what happened, and the lesson. Conversational and specific."),
    "casual": ("Friendly & casual", "Warm, relaxed and friendly, like talking to colleagues. A couple of fitting emojis are fine."),
    "funny": ("Funny & witty", "Light, witty and relatable workplace humour (dialogue or 'Me: / Also me:' style works). Keep it kind and still make a point."),
    "insight": ("Thought leadership", "Share a clear opinion or insight with reasoning, a few concrete points and a strong closing thought. Confident, not preachy."),
    "tips": ("Tips list", "A bold hook line, then 3-6 practical, specific tips as a list, then a one-line close."),
    "motivational": ("Motivational", "Encouraging and uplifting without clichés. Real, grounded, with a positive call to keep going."),
    "hiring": ("Hiring announcement", "A clear hiring post: role, team/company, where, what you'll do, who should apply and how. Inviting and direct."),
    "question": ("Ask the community", "End with an open question that invites comments. Short setup, then the question."),
    "human": ("Anti-AI", "Make it read like a real person typed it, not an AI. Keep the meaning, facts and roughly the length. "
              "Remove AI tells: no em dashes (—), no 'In today's fast-paced world', 'delve', 'unlock', 'leverage', 'game-changer', "
              "'journey', 'landscape', 'elevate', 'navigate', 'Here's the thing', 'Let's dive in', 'It's not just X, it's Y'. "
              "No neat groups of three, no bold hook line, no motivational wrap-up, at most one emoji. Use first person, contractions, "
              "plain everyday words, uneven sentence lengths, one specific detail, and a natural ending. Fewer, simpler hashtags (2-4)."),
    "grammar": ("Fix grammar only", "Keep the author's words, tone and length. Only fix spelling, grammar and punctuation, and tidy the formatting."),
}

INSTRUCTIONS = """You write posts for WorkOwon, an Indian professional community and job site (similar to LinkedIn).
Return JSON with: title, content, hashtags, pollOptions.
- content is HTML using ONLY <p>, <strong>, <em>, <ul>, <ol>, <li>, <br>. No other tags, no attributes, no markdown.
  Start with a hook as <p><strong>...</strong></p> unless the style is very short, casual or Anti-AI. Each paragraph is its own <p>.
  List items are <li><p>text</p></li>. Use emojis only when they fit the style, never more than a few.
- Keep facts the user gave (names, numbers, links, dates). Never invent statistics, companies, quotes or personal details.
- hashtags: 3-7 relevant hashtags, lowercase, no '#', no spaces (e.g. "careergrowth"). Put them ONLY in this list, not in content.
- title: only for ARTICLE posts (a short headline, max 120 characters); otherwise an empty string.
- pollOptions: only for POLL posts, 2-5 short options (max 60 characters each); otherwise an empty list. Keep the user's options if they gave good ones.
- Write in the language the user writes in (default English). Keep content under 2500 characters unless asked for longer."""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "content": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "pollOptions": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["title", "content", "hashtags", "pollOptions"],
}


def sanitize_post_html(value: str) -> str:
    """Keep only the tags the site's post editor uses; plain text becomes paragraphs."""
    value = (value or "").strip()
    if value and "<" not in value:
        value = "".join(f"<p>{line}</p>" for line in value.splitlines() if line.strip())
    soup = BeautifulSoup(value, "html.parser")
    for tag in soup.find_all(["script", "style", "iframe", "img", "video", "audio", "svg"]):
        tag.decompose()
    for tag in soup.find_all(True):
        if tag.name == "b":
            tag.name = "strong"
        elif tag.name == "i":
            tag.name = "em"
        if tag.name not in POST_TAGS:
            tag.unwrap()
        else:
            tag.attrs = {}
    return str(soup).strip()


def clean_hashtags(tags: list) -> list[str]:
    out = []
    for tag in tags or []:
        t = "".join(ch for ch in str(tag).lower().lstrip("#") if ch.isalnum() or ch == "_")
        if t and t not in out:
            out.append(t)
    return out[:10]


def write_post(action: str, style: str, prompt: str, post: dict) -> dict:
    """action "create" writes a new post from the prompt; "enhance" rewrites the current post."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in .env")
    model = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    label, guide = STYLES.get(style, (None, None))
    request_parts = [f"Post type: {post.get('type') or 'TEXT'}"]
    if label:
        request_parts.append(f"Style: {label}. {guide}")
    if action == "create":
        request_parts.append(f"Write a new post about: {prompt or post.get('content') or 'a useful career tip'}")
    else:
        if prompt:
            request_parts.append(f"Change it like this: {prompt}")
        request_parts.append("Rewrite this post:\n" + json.dumps({
            "title": post.get("title") or "",
            "content": post.get("content") or "",
            "hashtags": post.get("hashtags") or [],
            "pollOptions": post.get("pollOptions") or [],
        }, ensure_ascii=False))
    body = {
        "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
        "contents": [{"role": "user", "parts": [{"text": "\n\n".join(request_parts)}]}],
        "generationConfig": {
            "temperature": 0.2 if style == "grammar" else 0.8,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            "thinkingConfig": {"thinkingLevel": "minimal"},
        },
    }
    response = requests.post(
        GEMINI_URL.format(model=model), json=body, timeout=TIMEOUT,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
    )
    if not response.ok:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = response.text[:300]
        raise RuntimeError(f"Gemini HTTP {response.status_code}: {message}")
    data = response.json()
    usage = data.get("usageMetadata") or {}
    logging.info("Gemini wrote a post (%s/%s, tokens in=%s out=%s)", action, style, usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))
    out = json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
    return {
        "title": (out.get("title") or "").strip()[:MAX_TITLE_CHARS],
        "content": sanitize_post_html(out.get("content") or "")[:MAX_CONTENT_CHARS],
        "hashtags": clean_hashtags(out.get("hashtags")),
        "pollOptions": [o.strip()[:60] for o in out.get("pollOptions") or [] if o.strip()][:10],
    }


class Accounts:
    """Logged-in WorkOwon accounts, by email."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[str, WorkowonClient] = {}
        if ACCOUNTS_DIR.exists():
            for path in sorted(ACCOUNTS_DIR.glob("*.json")):
                client = WorkowonClient(path)
                if client.email and (client.access_token or client.refresh_token):
                    self._clients[client.email.lower()] = client

    @staticmethod
    def _file(email: str) -> Path:
        return ACCOUNTS_DIR / (hashlib.sha256(email.lower().encode()).hexdigest()[:16] + ".json")

    def list(self) -> list[str]:
        with self._lock:
            return [c.email for c in self._clients.values()]

    def login(self, email: str, password: str) -> None:
        ACCOUNTS_DIR.mkdir(mode=0o700, exist_ok=True)
        client = WorkowonClient(self._file(email))
        client.login(email, password)
        with self._lock:
            self._clients[email.lower()] = client

    def logout(self, email: str) -> None:
        with self._lock:
            client = self._clients.pop((email or "").lower(), None)
        if client:
            client.logout()

    def client(self, email: str) -> WorkowonClient:
        with self._lock:
            client = self._clients.get((email or "").lower())
        if not client:
            raise AuthError("This account is not logged in.")
        return client
