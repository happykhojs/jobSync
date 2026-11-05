"""
Rewrite jobs into clean, readable listings with Gemini.

AI is opt-in: the dashboard only calls this when the admin clicks an "Improve with AI" button.

Token-saving design:
- Only the jobs the admin picked are curated (never the whole jobs.json).
- Several jobs go in one request (CURATE_BATCH_SIZE), sharing one copy of the instructions.
- Results are cached in curated_jobs.json by sourceKey + content hash, so a job is
  never sent twice unless its source text changes.
- Input text is whitespace-collapsed and length-capped; thinking is disabled.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path

import requests

from htmlfmt import html_to_text, sanitize_html

BASE_DIR = Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "curated_jobs.json"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-flash-lite-latest"
CURATE_BATCH_SIZE = 10
# Bump when INSTRUCTIONS change so cached jobs are re-curated with the new rules.
PROMPT_VERSION = 4
MAX_DESCRIPTION_CHARS = 5000
MAX_REQUIREMENTS_CHARS = 2500
TIMEOUT = 120

INSTRUCTIONS = """You turn raw job listings into clean, well-formatted listings for an Indian job site.
For each input job return one object with the same "id". Rules:
- Use ONLY facts in the input. Never invent salary, years, benefits, skills or perks. Use null / [] when not stated.
- title: the role name with its specialisation (e.g. "Program Manager - Global Expansion"); remove only locations, grade codes and clutter like "|| Noida ||", "SG Grade-", "Gurgaon Based". Keep seniority words.
- description and requirements are HTML using ONLY these tags: <p>, <strong>, <ul>, <li>. No attributes, markdown, emojis or bullet characters.
  Every list item is <li><p>text</p></li>. Section titles are <p><strong>Title</strong></p>.
  Use <strong> inside sentences sparingly to highlight 1-3 key terms per section (tools, frameworks, outcomes), never whole sentences.
- description format:
  <p>2-3 sentence overview of the role and its purpose, mentioning the company briefly.</p>
  <p><strong>Key Responsibilities</strong></p><ul>5-10 items</ul>
  If the source groups responsibilities by area, use numbered subsections instead: <p><strong>1. Area name</strong></p><ul>items</ul> per area.
  Optionally end with <p><strong>Key Skills &amp; Competencies</strong></p><ul>items</ul> when the source lists soft/core skills.
  Drop legal/EEO text, ISMS/security policy text, application instructions and repeated company boilerplate.
- requirements format: <p><strong>Requirements</strong></p><ul>must-haves</ul>, then if the source has nice-to-haves
  <p><strong>Preferred Qualifications</strong></p><ul>items</ul>. Empty string if no requirements are stated.
- experienceLevel, by minimum years: 0-1 ENTRY, 2-4 MID, 5-9 SENIOR, 10+ LEAD. Title overrides upward: "Senior"/"Sr"/"Senior Manager" >= SENIOR; lead/principal/staff >= LEAD; director/head/VP/GM/AVP = EXECUTIVE; interns/freshers = ENTRY. In India "Executive"/"Senior Executive" titles are ENTRY/MID grades.
- experienceMinYears / experienceMaxYears: only from explicit numbers in the text.
- employmentType / workplaceType: from the input hints or text; default FULL_TIME / ONSITE.
- salary fields: only if an explicit amount is written; currency as ISO code (e.g. INR).
- skills: up to 10 concrete skills/tools for THIS role (not company boilerplate), short Title Case names, most important first.
  proficiencyLevel: BEGINNER, INTERMEDIATE, ADVANCED or EXPERT based on the seniority asked for. required=false for nice-to-haves.
- benefits: only perks the text explicitly offers, each with a short description.
- tags: 4-6 Title Case tags for search: the function plus " Jobs" (e.g. "HR Jobs", "Sales Jobs", "Software Engineering Jobs"),
  exactly one of "IT Jobs" or "Non-IT Jobs", a generic role name (e.g. "Human Resources Manager"), and 1-3 domain/skill keywords.
  No company names, cities or employment type."""

_nullable_int = {"type": "INTEGER", "nullable": True}
RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "id": {"type": "STRING"},
            "title": {"type": "STRING"},
            "description": {"type": "STRING"},
            "requirements": {"type": "STRING"},
            "employmentType": {"type": "STRING", "enum": ["FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP", "FREELANCE"]},
            "workplaceType": {"type": "STRING", "enum": ["REMOTE", "HYBRID", "ONSITE"]},
            "experienceLevel": {"type": "STRING", "enum": ["ENTRY", "MID", "SENIOR", "LEAD", "EXECUTIVE"]},
            "experienceMinYears": _nullable_int,
            "experienceMaxYears": _nullable_int,
            "salaryMin": {"type": "NUMBER", "nullable": True},
            "salaryMax": {"type": "NUMBER", "nullable": True},
            "salaryCurrency": {"type": "STRING", "nullable": True},
            "salaryPeriod": {"type": "STRING", "enum": ["YEARLY", "MONTHLY", "HOURLY"], "nullable": True},
            "skills": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "skillName": {"type": "STRING"},
                        "proficiencyLevel": {"type": "STRING", "enum": ["BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"]},
                        "required": {"type": "BOOLEAN"},
                    },
                    "required": ["skillName", "proficiencyLevel", "required"],
                },
            },
            "benefits": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "benefitType": {"type": "STRING", "enum": ["HEALTH", "STOCK", "REMOTE", "GYM", "FOOD", "LEARNING", "VISA", "BONUS", "OTHER"]},
                        "description": {"type": "STRING"},
                    },
                    "required": ["benefitType", "description"],
                },
            },
            "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["id", "title", "description", "requirements", "employmentType", "workplaceType",
                     "experienceLevel", "skills", "benefits", "tags"],
    },
}


def _squash(text: str, limit: int) -> str:
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text[:limit]


def _content_hash(job: dict) -> str:
    material = f"{PROMPT_VERSION}|{job['title']}|{job['description']}|{job['requirements']}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _job_input(job: dict) -> dict:
    return {
        "id": job["sourceKey"][:12],
        "company": job["externalCompanyName"],
        "title": job["title"],
        "location": "; ".join(l.get("raw") or "" for l in job["locations"]),
        "employmentTypeHint": job.get("employmentType"),
        "workplaceTypeHint": job.get("workplaceType"),
        "description": _squash(job["description"], MAX_DESCRIPTION_CHARS),
        "requirements": _squash(job["requirements"], MAX_REQUIREMENTS_CHARS),
    }


# Gemini sometimes answers 503 "high demand" (or 429/500) for a while. Retry the same model a couple of
# times, then fall back to other models. GEMINI_FALLBACK_MODELS (comma-separated) overrides the list.
DEFAULT_FALLBACK_MODELS = ["gemini-3-flash-preview", "gemini-flash-latest"]
RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_WAITS = [2, 5]  # seconds before the 2nd and 3rd try of one model
# Not every model accepts thinkingLevel "minimal"; these get the lowest level they do accept.
THINKING_LEVEL = {"gemini-flash-latest": "low"}


class GeminiError(RuntimeError):
    def __init__(self, message: str, busy: bool = False) -> None:
        super().__init__(message)
        self.busy = busy  # every model was overloaded or rate limited: worth trying again later


def gemini_models(model: str | None = None) -> list[str]:
    primary = model or os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    extra = os.environ.get("GEMINI_FALLBACK_MODELS")
    fallbacks = [m.strip() for m in extra.split(",")] if extra is not None else DEFAULT_FALLBACK_MODELS
    return list(dict.fromkeys(m for m in [primary, *fallbacks] if m))


def _error_text(response: requests.Response) -> str:
    try:
        return response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return response.text[:300]


def gemini_generate(body: dict, api_key: str, model: str | None = None, timeout: int = TIMEOUT) -> tuple[dict, str]:
    """POST generateContent with retries and model fallback. Returns (response JSON, model used)."""
    models = gemini_models(model)
    last, all_busy = "", True
    for name in models:
        config = dict(body.get("generationConfig") or {})
        if "thinkingConfig" in config and name in THINKING_LEVEL:
            config["thinkingConfig"] = {**config["thinkingConfig"], "thinkingLevel": THINKING_LEVEL[name]}
        request_body = {**body, "generationConfig": config}
        for attempt in range(len(RETRY_WAITS) + 1):
            if attempt:
                time.sleep(RETRY_WAITS[attempt - 1])
            try:
                response = requests.post(
                    GEMINI_URL.format(model=name), json=request_body, timeout=timeout,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                )
            except requests.RequestException as exc:  # timeout or network problem: try the next model
                last = f"Gemini ({name}): {exc}"
                break
            if response.ok:
                if name != models[0]:
                    logging.info("Gemini: %s was busy, used %s", models[0], name)
                return response.json(), name
            last = f"Gemini HTTP {response.status_code} ({name}): {_error_text(response)}"
            logging.warning(last)
            if response.status_code not in RETRY_STATUSES:
                all_busy = False
                break  # bad request or model unavailable: retrying won't help, try the next model
    if all_busy:
        raise GeminiError("Gemini is overloaded right now (all models busy). Please try again in a minute.", busy=True)
    raise GeminiError(last or "Gemini request failed.")


def _call_gemini(batch: list[dict], api_key: str, model: str, stats: dict) -> list[dict]:
    body = {
        "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps([_job_input(j) for j in batch], ensure_ascii=False)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            "thinkingConfig": {"thinkingLevel": "minimal"},
        },
    }
    data, _ = gemini_generate(body, api_key, model)
    usage = data.get("usageMetadata") or {}
    stats["calls"] += 1
    stats["inputTokens"] += usage.get("promptTokenCount") or 0
    stats["outputTokens"] += usage.get("candidatesTokenCount") or 0
    logging.info(
        "Gemini curated %d jobs (tokens in=%s out=%s)",
        len(batch), usage.get("promptTokenCount"), usage.get("candidatesTokenCount"),
    )
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def new_stats() -> dict:
    return {"calls": 0, "inputTokens": 0, "outputTokens": 0, "cached": 0, "errors": []}


def payload_to_input(key: str, payload: dict) -> dict:
    """Shape an API payload (possibly admin-edited) like a scraped job so it can be curated."""
    return {
        "sourceKey": key,
        "externalCompanyName": payload.get("externalCompanyName", ""),
        "title": payload.get("title", ""),
        "description": html_to_text(payload.get("description", "")),
        "requirements": html_to_text(payload.get("requirements", "")),
        "employmentType": payload.get("employmentType"),
        "workplaceType": payload.get("workplaceType"),
        "locations": [{"raw": ", ".join(x for x in (l.get("city"), l.get("state"), l.get("country")) if x)}
                      for l in payload.get("locations") or []],
    }


def curate_jobs(jobs: list[dict], stats: dict | None = None) -> dict[str, dict]:
    """Return {sourceKey: curated fields} for the given jobs, calling Gemini only for uncached ones."""
    stats = stats if stats is not None else new_stats()
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    model = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}

    result, todo = {}, []
    for job in jobs:
        entry = cache.get(job["sourceKey"])
        if entry and entry.get("hash") == _content_hash(job):
            result[job["sourceKey"]] = entry["fields"]
            stats["cached"] += 1
        else:
            todo.append(job)
    if todo and not api_key:
        stats["errors"].append("GEMINI_API_KEY is not set in .env")
        return result
    if todo:
        logging.info("%d cached, %d to curate with %s", len(result), len(todo), model)

    for i in range(0, len(todo), CURATE_BATCH_SIZE):
        batch = todo[i : i + CURATE_BATCH_SIZE]
        try:
            curated = _call_gemini(batch, api_key, model, stats)
        except (requests.RequestException, RuntimeError, KeyError, IndexError, ValueError) as exc:
            logging.warning("Curation failed for %d jobs, using rule-based fields: %s", len(batch), exc)
            stats["errors"].append(str(exc))
            stats["busy"] = stats.get("busy", False) or bool(getattr(exc, "busy", False))
            continue
        by_id = {c.get("id"): c for c in curated if isinstance(c, dict)}
        for job in batch:
            fields = by_id.get(job["sourceKey"][:12])
            if not fields:
                continue
            fields.pop("id", None)
            cache[job["sourceKey"]] = {"hash": _content_hash(job), "model": model, "fields": fields}
            result[job["sourceKey"]] = fields
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def apply_curation(job: dict, fields: dict) -> dict:
    """Overlay curated fields on a job; keep rule-based values where the model returned nothing."""
    merged = dict(job)
    for key in ("title", "employmentType", "workplaceType", "experienceLevel"):
        if fields.get(key):
            merged[key] = fields[key]
    for key in ("description", "requirements"):
        if fields.get(key):
            merged[key] = sanitize_html(fields[key])
    for key in ("experienceMinYears", "experienceMaxYears"):
        if fields.get(key) is not None:
            merged[key] = fields[key]
    if fields.get("salaryMin") and fields.get("salaryMax"):
        merged.update(
            salaryMin=fields["salaryMin"], salaryMax=fields["salaryMax"],
            salaryCurrency=fields.get("salaryCurrency") or "INR",
            salaryPeriod=fields.get("salaryPeriod") or "YEARLY", salaryVisible=True,
        )
    if fields.get("skills"):
        merged["skills"] = [dict(s, orderIndex=i) for i, s in enumerate(fields["skills"][:10])]
    if fields.get("benefits"):
        merged["benefits"] = fields["benefits"]
    if fields.get("tags"):
        merged["tags"] = fields["tags"][:8]
    return merged
