#!/usr/bin/env python3
"""
WorkOwon JobSync: search company career sites, review/edit jobs, and post selected ones to Workowon.

Run:
    .venv/bin/python app.py
then open http://127.0.0.1:5050
"""
from __future__ import annotations

import html
import json
import logging
import os
import random
import re
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Flask, Response, jsonify, request, send_from_directory

import duplicates
from curate import curate_jobs, new_stats, payload_to_input
from htmlfmt import sanitize_html
from job_scraper import release_memory
from enrich import SKILLS
from search import options, search, suggest
from posts import STYLES, Accounts, SavedLogins, clean_hashtags, parse_logins, sanitize_post_html, write_post
from post_jobs import ENV_FILE, JOBS_FILE, POSTED_FILE, build_payload, improve_payload, load_env, load_json
from workowon import AuthError, WorkowonClient, record_keys

BASE_DIR = Path(__file__).resolve().parent
EDITS_FILE = BASE_DIR / "edits.json"
SKIPPED_FILE = BASE_DIR / "skipped.json"
BOARDS_FILE = BASE_DIR / "boards.json"

load_env(ENV_FILE)
app = Flask(__name__, static_folder="static")
client = WorkowonClient()
accounts = Accounts()
saved_logins = SavedLogins()
files_lock = threading.Lock()
keys_lock = threading.Lock()
# Jobs already on WorkOwon (workowon.job_keys), refreshed at most every few minutes.
WORKOWON_KEYS_SECONDS = 5 * 60
_workowon_keys: dict = {"at": 0.0, "keys": set()}


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def catalog() -> list[dict]:
    return load_json(BOARDS_FILE, {}).get("boards", [])


def workowon_keys() -> set[str]:
    """Keys of jobs already on WorkOwon, so search and posting skip them: the admin external-jobs list
    (once logged in) plus every published job from the public job search API."""
    with keys_lock:
        if time.time() - _workowon_keys["at"] > WORKOWON_KEYS_SECONDS:
            try:
                _workowon_keys.update(at=time.time(), keys=client.external_job_keys())
            except Exception as exc:  # not logged in or API down: fall back to the local posted list
                logging.warning("Could not load jobs already on WorkOwon: %s", exc)
        keys = _workowon_keys["keys"]
    return keys | duplicates.site_job_keys()


def clean_payload(payload: dict) -> dict:
    """Keep edited HTML within the site's allowed tags."""
    for key in ("description", "requirements"):
        if payload.get(key):
            payload[key] = sanitize_html(payload[key])
    return payload


def api_payload(payload: dict) -> dict:
    # Keys starting with "_" are dashboard bookkeeping (e.g. _ai) and never go to the API.
    return {k: v for k, v in clean_payload(dict(payload)).items() if not k.startswith("_")}


def to_view(jobs: list[dict]) -> list[dict]:
    """Rule-based payloads only: no AI here. Saved edits (including earlier AI improvements) win."""
    edits = load_json(EDITS_FILE, {})
    site_jobs = duplicates.site_jobs()
    items = []
    for job in jobs:
        key = job["sourceKey"]
        payload = edits.get(key) or build_payload(job)
        items.append({
            "sourceKey": key,
            "provider": job["sourceProvider"],
            "sourceName": job.get("sourceName") if job["sourceProvider"] == "himalayas" else None,
            "sector": job.get("sector"),
            "companyType": job.get("companyType"),
            "sourcePostedAt": job.get("sourceUpdatedAt"),
            "edited": key in edits,
            "aiImproved": bool(payload.get("_ai")),
            "payload": payload,
            # Closest job already live on WorkOwon, if any looks like this one.
            "duplicate": duplicates.best_match(payload, site_jobs),
        })
    return items


def error(message: str, status: int = 400):
    return jsonify({"error": message}), status


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/session")
def session_info():
    if not client.access_token and not client.refresh_token:
        return jsonify({"loggedIn": False})
    try:
        me = client.me()
    except AuthError:
        return jsonify({"loggedIn": False})
    except Exception as exc:  # network hiccup: keep the session, report it
        return jsonify({"loggedIn": True, "email": client.email, "warning": str(exc)})
    return jsonify({"loggedIn": True, "email": client.email, "roles": me.get("roles", [])})


# Public Turnstile site key used by workowon.com login. Override with TURNSTILE_SITE_KEY if WorkOwon rotates it.
# The JobSync hostname (e.g. jobsync-wgs9.onrender.com) must be allowed on that Turnstile widget.
DEFAULT_TURNSTILE_SITE_KEY = "0x4AAAAAAF8mwjtmsgdq3yaK"


def turnstile_site_key() -> str:
    return (os.environ.get("TURNSTILE_SITE_KEY") or DEFAULT_TURNSTILE_SITE_KEY).strip()


def turnstile_from_body(body: dict | None) -> str:
    body = body or {}
    return (body.get("turnstileToken") or body.get("cf-turnstile-response") or "").strip()


@app.get("/api/login-defaults")
def login_defaults():
    # Prefill values come from .env (LOGIN_EMAIL / LOGIN_PASSWORD_PREFILL); the dashboard only listens on localhost.
    return jsonify({
        "email": os.environ.get("LOGIN_EMAIL", ""),
        "password": os.environ.get("LOGIN_PASSWORD_PREFILL", ""),
        "turnstileSiteKey": turnstile_site_key(),
    })


@app.post("/api/login")
def login():
    body = request.get_json(force=True)
    email, password = (body.get("email") or "").strip(), body.get("password") or ""
    if not email or not password:
        return error("Email and password are required.")
    token = turnstile_from_body(body)
    if not token:
        return error("Complete the Cloudflare check before logging in.", 401)
    try:
        client.login(email, password, turnstile_token=token)
        me = client.me()
    except AuthError as exc:
        return error(str(exc), 401)
    if "ADMIN" not in me.get("roles", []):
        client.logout()
        return error("This account is not an admin.", 403)
    return jsonify({"loggedIn": True, "email": email, "roles": me.get("roles", [])})


@app.post("/api/logout")
def logout():
    client.logout()
    return jsonify({"loggedIn": False})


MEME_SUBREDDITS = ["wholesomememes", "ProgrammerHumor", "Catmemes", "recruitinghell"]
MEME_CACHE_SECONDS = 10 * 60
_memes: dict = {"at": 0.0, "items": []}


@app.get("/api/memes")
def memes():
    """Fun Zone loading memes: safe-for-work picks from a public meme API, cached for 10 minutes."""
    if time.time() - _memes["at"] > MEME_CACHE_SECONDS or not _memes["items"]:
        items = []
        for sub in MEME_SUBREDDITS:
            try:
                data = requests.get(f"https://meme-api.com/gimme/{sub}/15", timeout=8).json()
            except (requests.RequestException, ValueError):
                continue
            for m in data.get("memes") or []:
                url = m.get("url") or ""
                if m.get("nsfw") or m.get("spoiler") or not re.search(r"\.(png|jpe?g|gif|webp)$", url, re.I):
                    continue
                items.append({"title": html.unescape(m.get("title") or ""), "url": url,
                              "subreddit": m.get("subreddit"), "link": m.get("postLink")})
        if items:
            random.shuffle(items)
            _memes.update(at=time.time(), items=items)
    return jsonify({"memes": _memes["items"]})


@app.get("/api/options")
def get_options():
    return jsonify(options(catalog()))


@app.get("/api/suggest")
def get_suggestions():
    return jsonify({"suggestions": suggest(request.args.get("q", ""), catalog(), load_json(JOBS_FILE, []), SKILLS)})


# A search asks every company site and can take minutes, longer than a hosting proxy (Render) keeps a
# request open, so it runs in the background: POST /api/search starts it, GET /api/search/<id> reports
# progress and the result. State is kept in files so any server worker process can answer the poll.
SEARCH_DIR = BASE_DIR / ".searches"
SEARCH_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SEARCH_KEEP_SECONDS = 30 * 60
# No progress for this long means the worker running it was restarted.
SEARCH_STALL_SECONDS = 3 * 60


def _search_file(search_id: str) -> Path:
    return SEARCH_DIR / f"{search_id}.json"


def _write_search(search_id: str, state: dict) -> None:
    SEARCH_DIR.mkdir(exist_ok=True)
    tmp = _search_file(search_id).with_suffix(f".{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _search_file(search_id))


def _clean_old_searches() -> None:
    for path in SEARCH_DIR.glob("*"):
        try:
            if time.time() - path.stat().st_mtime > SEARCH_KEEP_SECONDS:
                path.unlink()
        except OSError:
            pass


def _run_search(search_id: str, criteria: dict) -> None:
    started = time.time()
    current = {"done": 0, "total": 0, "written": 0.0}
    finished = threading.Event()
    write_lock = threading.Lock()

    def write_running() -> None:
        with write_lock:
            if not finished.is_set():
                current["written"] = time.time()
                _write_search(search_id, {"status": "running", "startedAt": started, "updatedAt": time.time(),
                                          "done": current["done"], "total": current["total"]})

    def progress(done: int, total: int) -> None:
        current.update(done=done, total=total)
        if time.time() - current["written"] >= 1:
            write_running()

    def heartbeat() -> None:
        # A slow company site can go minutes without progress; keep showing the search is alive.
        while not finished.wait(15):
            write_running()

    threading.Thread(target=heartbeat, daemon=True).start()
    try:
        exclude = set(load_json(POSTED_FILE, {})) | set(load_json(SKIPPED_FILE, {}))
        result = search(criteria, catalog(), exclude, workowon_keys(), progress)
        records = result["records"]
        # Keep found jobs in jobs.json too, so the command-line poster can use them.
        with files_lock:
            stored = {j["sourceKey"]: j for j in load_json(JOBS_FILE, []) if isinstance(j, dict)}
            stored.update({r["sourceKey"]: r for r in records})
            save_json(JOBS_FILE, sorted(stored.values(), key=lambda j: j.get("sourceUpdatedAt") or "", reverse=True))
        state = {"status": "done", "result": {
            "jobs": to_view(records),
            "matched": result["matched"],
            "companiesSearched": result["companiesSearched"],
            "errors": result["errors"],
            "postedCount": len(load_json(POSTED_FILE, {})),
        }}
    except Exception as exc:
        logging.exception("Search failed")
        state = {"status": "failed", "error": f"Search failed: {exc}"}
    release_memory()
    with write_lock:
        finished.set()
        _write_search(search_id, state)


@app.post("/api/search")
def run_search():
    criteria = request.get_json(force=True) or {}
    SEARCH_DIR.mkdir(exist_ok=True)
    _clean_old_searches()
    search_id = uuid.uuid4().hex
    _write_search(search_id, {"status": "running", "startedAt": time.time(), "updatedAt": time.time(), "done": 0, "total": 0})
    threading.Thread(target=_run_search, args=(search_id, criteria), daemon=True).start()
    return jsonify({"searchId": search_id}), 202


@app.get("/api/search/<search_id>")
def search_status(search_id: str):
    if not SEARCH_ID_RE.match(search_id):
        return error("Unknown search.", 404)
    try:
        state = json.loads(_search_file(search_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return error("This search has expired or the server restarted. Please search again.", 404)
    if state["status"] == "running" and time.time() - state.get("updatedAt", 0) > SEARCH_STALL_SECONDS:
        return error("The search stopped (the server restarted). Please search again.", 410)
    return jsonify(state)


@app.put("/api/jobs/<key>")
def save_edit(key: str):
    payload = (request.get_json(force=True) or {}).get("payload")
    if not isinstance(payload, dict):
        return error("Missing payload.")
    with files_lock:
        edits = load_json(EDITS_FILE, {})
        edits[key] = clean_payload(payload)
        save_json(EDITS_FILE, edits)
    # A changed title, company or city changes the duplicate score.
    return jsonify({"saved": True, "duplicate": duplicates.best_match(edits[key])})


@app.post("/api/improve")
def improve_jobs():
    """The only place the dashboard uses AI: runs when the admin clicks an Improve button."""
    items = [i for i in (request.get_json(force=True) or {}).get("jobs") or [] if i.get("sourceKey") and isinstance(i.get("payload"), dict)]
    if not items:
        return error("No jobs to improve.")
    if len(items) > 50:
        return error("Improve at most 50 jobs at a time.")
    sectors = {j["sourceKey"]: j.get("sector") for j in load_json(JOBS_FILE, []) if isinstance(j, dict)}
    stats = new_stats()
    curated = curate_jobs([payload_to_input(i["sourceKey"], i["payload"]) for i in items], stats)
    improved = []
    with files_lock:
        edits = load_json(EDITS_FILE, {})
        for item in items:
            key = item["sourceKey"]
            if key not in curated:
                continue
            payload = clean_payload(improve_payload(item["payload"], curated[key], sectors.get(key)))
            payload["_ai"] = True
            edits[key] = payload
            improved.append({"sourceKey": key, "payload": payload, "duplicate": duplicates.best_match(payload)})
        save_json(EDITS_FILE, edits)
    if not improved and stats["errors"]:
        # Gemini overloaded is temporary (503, the dashboard shows the message); other failures are upstream errors.
        return error(f"AI could not improve these jobs: {stats['errors'][0]}", 503 if stats.get("busy") else 502)
    return jsonify({"jobs": improved, "stats": stats})


@app.delete("/api/jobs/<key>/edit")
def reset_edit(key: str):
    with files_lock:
        edits = load_json(EDITS_FILE, {})
        edits.pop(key, None)
        save_json(EDITS_FILE, edits)
    return jsonify({"reset": True})


@app.post("/api/jobs/<key>/skip")
def skip_job(key: str):
    with files_lock:
        skipped = load_json(SKIPPED_FILE, {})
        skipped[key] = datetime.now(timezone.utc).isoformat()
        save_json(SKIPPED_FILE, skipped)
    return jsonify({"skipped": True})


@app.post("/api/post")
def post_jobs():
    items = (request.get_json(force=True) or {}).get("jobs") or []
    results = []
    for item in items:
        key, payload = item.get("sourceKey"), item.get("payload")
        if not key or not isinstance(payload, dict):
            results.append({"sourceKey": key, "ok": False, "message": "Invalid job"})
            continue
        with files_lock:
            if key in load_json(POSTED_FILE, {}):
                results.append({"sourceKey": key, "ok": True, "message": "Already posted"})
                continue
        if record_keys(payload) & workowon_keys():
            results.append({"sourceKey": key, "ok": True, "message": "Already on WorkOwon"})
            continue
        match = duplicates.best_match(payload)
        if match and match["level"] == "likely" and not item.get("allowDuplicate"):
            results.append({"sourceKey": key, "ok": False, "duplicate": match,
                            "message": f"Not posted: {match['score']}% match with “{match['title']}” at {match['company']} already on WorkOwon. "
                                       "Choose “Not a duplicate” if this is a different job."})
            continue
        try:
            ok, message, body = client.post_external_job(api_payload(payload))
        except AuthError as exc:
            return error(str(exc), 401)
        except Exception as exc:
            results.append({"sourceKey": key, "ok": False, "message": str(exc)})
            continue
        if ok:
            with keys_lock:
                # Also stops the same job being posted twice from one batch.
                _workowon_keys["keys"] |= record_keys(payload)
            duplicates.remember_posted(payload, (body.get("data") or {}).get("jobId"))
            with files_lock:
                posted = load_json(POSTED_FILE, {})
                posted[key] = {
                    "postedAt": datetime.now(timezone.utc).isoformat(),
                    "title": payload.get("title"),
                    "company": payload.get("externalCompanyName"),
                    "jobId": (body.get("data") or {}).get("jobId"),
                    "response": json.dumps(body)[:500],
                }
                save_json(POSTED_FILE, posted)
                edits = load_json(EDITS_FILE, {})
                if edits.pop(key, None) is not None:
                    save_json(EDITS_FILE, edits)
        results.append({"sourceKey": key, "ok": ok, "message": message,
                        "jobId": (body.get("data") or {}).get("jobId") if ok else None})
    return jsonify({"results": results})


# ---------- Community posts (Post page) ----------
POST_TYPES = ["TEXT", "ARTICLE", "QUESTION", "POLL", "LINK", "JOB_SHARE"]
VISIBILITY = ["PUBLIC", "CONNECTIONS", "PRIVATE"]
MEDIA_KINDS = {"image": "IMAGE", "video": "VIDEO", "document": "DOCUMENT"}


def post_client() -> WorkowonClient:
    # The Post page sends the account it is posting as; several can be logged in at once.
    return accounts.client(request.headers.get("X-Account", ""))


def post_payload(body: dict, creating: bool) -> dict:
    """Validated create/update body for the community posts API."""
    post_type = body.get("type") if body.get("type") in POST_TYPES else "TEXT"
    content = sanitize_post_html(body.get("content") or "")
    if len(content) > 10000:
        raise ValueError("The post is too long (10,000 characters at most).")
    payload = {
        "title": (body.get("title") or "").strip()[:300] or None,
        "content": content,
        "visibility": body.get("visibility") if body.get("visibility") in VISIBILITY else "PUBLIC",
        "hashtags": clean_hashtags(body.get("hashtags")),
        "tags": [t.strip() for t in body.get("tags") or [] if str(t).strip()][:10],
        "media": [
            {k: m.get(k) for k in ("type", "url", "fileName", "mimeType", "fileSizeBytes", "width", "height") if m.get(k) is not None}
            | {"orderIndex": i}
            for i, m in enumerate(body.get("media") or []) if m.get("url") and m.get("type") in MEDIA_KINDS.values()
        ],
    }
    if body.get("linkUrl"):
        payload.update({k: (body.get(k) or "").strip() or None for k in ("linkUrl", "linkPreviewTitle", "linkPreviewDescription", "linkPreviewImage")})
    if not content and not payload["media"] and not body.get("linkUrl"):
        raise ValueError("Write something, add media or a link first.")
    if creating:
        payload["type"] = post_type
        if post_type == "POLL":
            poll = body.get("poll") or {}
            options = [o.strip()[:60] for o in poll.get("options") or [] if str(o).strip()][:10]
            if len(options) < 2:
                raise ValueError("A poll needs at least 2 options.")
            payload["poll"] = {"options": options, "endsAt": poll.get("endsAt"), "multipleChoice": bool(poll.get("multipleChoice"))}
            if not payload["poll"]["endsAt"]:
                raise ValueError("Pick when the poll ends.")
        if post_type in ("LINK", "JOB_SHARE") and not body.get("linkUrl"):
            raise ValueError("Add the link for this post.")
    return {k: v for k, v in payload.items() if v not in (None, [])}


def posts_error(exc: Exception):
    if isinstance(exc, AuthError):
        return error(str(exc), 401)
    return error(str(exc), 400 if isinstance(exc, ValueError) else 502)


@app.get("/posts")
def posts_page():
    return send_from_directory(app.static_folder, "posts.html")


@app.get("/api/posts/options")
def post_options():
    return jsonify({
        "types": POST_TYPES, "visibility": VISIBILITY,
        "turnstileSiteKey": turnstile_site_key(),
        "styles": [{"id": k, "label": label} for k, (label, _) in STYLES.items()],
        "aiEnabled": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
    })


def accounts_view(**extra):
    return jsonify({"accounts": accounts.list(), "saved": saved_logins.emails(), **extra})


@app.get("/api/posts/accounts")
def post_accounts():
    return accounts_view()


@app.post("/api/posts/accounts")
def post_account_login():
    body = request.get_json(force=True)
    email, password = (body.get("email") or "").strip(), body.get("password") or ""
    if not email or not password:
        return error("Email and password are required.")
    token = turnstile_from_body(body)
    if not token:
        return error("Complete the Cloudflare check before logging in.", 401)
    try:
        accounts.login(email, password, turnstile_token=token)
    except AuthError as exc:
        return error(str(exc), 401)
    return accounts_view(email=email)


@app.delete("/api/posts/accounts/<path:email>")
def post_account_logout(email: str):
    accounts.logout(email)
    return accounts_view()


@app.post("/api/posts/saved")
def save_logins():
    """Save many email/password pairs, from an uploaded CSV file or pasted text."""
    file = request.files.get("file")
    if file:
        text = file.read().decode("utf-8-sig", errors="replace")
    else:
        text = (request.get_json(force=True) or {}).get("text") or ""
    pairs, skipped = parse_logins(text)
    if not pairs:
        return error("No logins found. Use one per line: email,password")
    new, updated = saved_logins.add(pairs)
    return accounts_view(added=new, updated=updated, skipped=skipped)


@app.post("/api/posts/saved/login")
def login_saved():
    body = request.get_json(force=True) or {}
    email = (body.get("email") or "").strip()
    password = saved_logins.password(email)
    if not password:
        return error("This email isn't in your saved logins.", 404)
    token = turnstile_from_body(body)
    if not token:
        return error("Complete the Cloudflare check before logging in.", 401)
    try:
        accounts.login(email, password, turnstile_token=token)
    except AuthError as exc:
        return error(f"{email}: {exc}", 401)
    return accounts_view(email=email)


@app.delete("/api/posts/saved/<path:email>")
def forget_saved(email: str):
    saved_logins.remove(email)
    return accounts_view()


@app.get("/api/posts/mine")
def my_posts():
    try:
        page = post_client().my_posts(int(request.args.get("page") or 0), 20)
    except Exception as exc:
        return posts_error(exc)
    return jsonify(page)


@app.post("/api/posts/mine")
def create_post():
    try:
        return jsonify({"post": post_client().create_post(post_payload(request.get_json(force=True), creating=True))})
    except Exception as exc:
        return posts_error(exc)


@app.put("/api/posts/mine/<post_id>")
def update_post(post_id: str):
    try:
        return jsonify({"post": post_client().update_post(post_id, post_payload(request.get_json(force=True), creating=False))})
    except Exception as exc:
        return posts_error(exc)


@app.delete("/api/posts/mine/<post_id>")
def delete_post(post_id: str):
    try:
        post_client().delete_post(post_id)
    except Exception as exc:
        return posts_error(exc)
    return jsonify({"deleted": post_id})


@app.post("/api/posts/media")
def upload_post_media():
    file = request.files.get("file")
    if not file:
        return error("No file.")
    mime = file.mimetype or "application/octet-stream"
    kind = "image" if mime.startswith("image/") else "video" if mime.startswith("video/") else "document"
    data = file.read()
    try:
        url = post_client().upload_post_media(kind, file.filename or "upload", mime, data)
    except Exception as exc:
        return posts_error(exc)
    return jsonify({"type": MEDIA_KINDS[kind], "url": url, "fileName": file.filename, "mimeType": mime, "fileSizeBytes": len(data)})


# Post media lives in a bucket that only serves pages on workowon.com, so the Post page loads it through here.
MEDIA_HOSTS = ("connectsphere-media-production.s3.ap-south-1.amazonaws.com",)
MEDIA_REFERER = "https://workowon.com/"


@app.get("/api/posts/media-proxy")
def media_proxy():
    url = request.args.get("url", "")
    if urlparse(url).scheme != "https" or urlparse(url).hostname not in MEDIA_HOSTS:
        return error("Not a WorkOwon media URL.")
    headers = {"Referer": MEDIA_REFERER}
    if request.headers.get("Range"):  # videos seek with range requests
        headers["Range"] = request.headers["Range"]
    upstream = requests.get(url, headers=headers, stream=True, timeout=30)
    passed = {k: upstream.headers[k] for k in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "ETag", "Last-Modified") if k in upstream.headers}
    passed["Cache-Control"] = "private, max-age=86400"
    return Response(upstream.iter_content(64 * 1024), status=upstream.status_code, headers=passed)


@app.post("/api/posts/ai")
def post_ai():
    body = request.get_json(force=True) or {}
    action = "create" if body.get("action") == "create" else "enhance"
    prompt = (body.get("prompt") or "").strip()[:2000]
    post = body.get("post") or {}
    if action == "enhance" and not (post.get("content") or "").strip() and not prompt:
        return error("Write something first, or describe the post you want.")
    try:
        return jsonify(write_post(action, body.get("style") or "", prompt, post))
    except Exception as exc:
        logging.warning("AI post failed: %s", exc)
        return error(str(exc), 503 if getattr(exc, "busy", False) else 502)


if __name__ == "__main__":
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    print("WorkOwon JobSync running at http://127.0.0.1:5050")
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
