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
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory

from curate import curate_jobs, new_stats, payload_to_input
from htmlfmt import sanitize_html
from enrich import SKILLS
from search import options, search, suggest
from post_jobs import ENV_FILE, JOBS_FILE, POSTED_FILE, build_payload, improve_payload, load_env, load_json
from workowon import AuthError, WorkowonClient, record_keys

BASE_DIR = Path(__file__).resolve().parent
EDITS_FILE = BASE_DIR / "edits.json"
SKIPPED_FILE = BASE_DIR / "skipped.json"
BOARDS_FILE = BASE_DIR / "boards.json"

load_env(ENV_FILE)
app = Flask(__name__, static_folder="static")
client = WorkowonClient()
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
    """Keys of jobs already on WorkOwon, so search and posting skip them. Empty until logged in."""
    with keys_lock:
        if time.time() - _workowon_keys["at"] > WORKOWON_KEYS_SECONDS:
            try:
                _workowon_keys.update(at=time.time(), keys=client.external_job_keys())
            except Exception as exc:  # not logged in or API down: fall back to the local posted list
                logging.warning("Could not load jobs already on WorkOwon: %s", exc)
        return _workowon_keys["keys"]


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


@app.get("/api/login-defaults")
def login_defaults():
    # Prefill values come from .env (LOGIN_EMAIL / LOGIN_PASSWORD_PREFILL); the dashboard only listens on localhost.
    return jsonify({
        "email": os.environ.get("LOGIN_EMAIL", ""),
        "password": os.environ.get("LOGIN_PASSWORD_PREFILL", ""),
    })


@app.post("/api/login")
def login():
    body = request.get_json(force=True)
    email, password = (body.get("email") or "").strip(), body.get("password") or ""
    if not email or not password:
        return error("Email and password are required.")
    try:
        client.login(email, password)
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


@app.post("/api/search")
def run_search():
    criteria = request.get_json(force=True) or {}
    exclude = set(load_json(POSTED_FILE, {})) | set(load_json(SKIPPED_FILE, {}))
    result = search(criteria, catalog(), exclude, workowon_keys())
    records = result["records"]
    # Keep found jobs in jobs.json too, so the command-line poster can use them.
    with files_lock:
        stored = {j["sourceKey"]: j for j in load_json(JOBS_FILE, []) if isinstance(j, dict)}
        stored.update({r["sourceKey"]: r for r in records})
        save_json(JOBS_FILE, sorted(stored.values(), key=lambda j: j.get("sourceUpdatedAt") or "", reverse=True))
    return jsonify({
        "jobs": to_view(records),
        "matched": result["matched"],
        "companiesSearched": result["companiesSearched"],
        "errors": result["errors"],
        "postedCount": len(load_json(POSTED_FILE, {})),
    })


@app.put("/api/jobs/<key>")
def save_edit(key: str):
    payload = (request.get_json(force=True) or {}).get("payload")
    if not isinstance(payload, dict):
        return error("Missing payload.")
    with files_lock:
        edits = load_json(EDITS_FILE, {})
        edits[key] = clean_payload(payload)
        save_json(EDITS_FILE, edits)
    return jsonify({"saved": True})


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
            improved.append({"sourceKey": key, "payload": payload})
        save_json(EDITS_FILE, edits)
    if not improved and stats["errors"]:
        return error(f"AI could not improve these jobs: {stats['errors'][0]}", 502)
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


if __name__ == "__main__":
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    print("WorkOwon JobSync running at http://127.0.0.1:5050")
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
