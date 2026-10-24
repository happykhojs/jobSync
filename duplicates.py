"""
Duplicate scoring against every job live on WorkOwon, read from its public job search API.

Exact matches (same listing URL, or same company + title + city; see workowon.job_keys) are hidden from
search outright. This scores near matches too: a reworded title, "Pvt Ltd" vs no suffix, another city.
The admin then sees "92% match" and can review it. Likely duplicates are blocked from posting unless
the admin marks them "Not a duplicate".
"""
from __future__ import annotations

import logging
import re
import threading
import time
from difflib import SequenceMatcher
from typing import Any

import requests

from workowon import BASE_URL, job_keys

SEARCH_URL = f"{BASE_URL}/api/jobs/search"
SITE_JOB_URL = "https://workowon.com/jobs/{}"
PAGE_SIZE = 500
MAX_PAGES = 40
CACHE_SECONDS = 5 * 60
TIMEOUT = 30
# Score bands (0-100): LIKELY blocks posting until the admin overrides; POSSIBLE is a warning only.
LIKELY = 90
POSSIBLE = 60
# Different companies with the same title are different jobs.
MIN_COMPANY_SIMILARITY = 0.75

_COMPANY_NOISE = {
    "inc", "ltd", "limited", "pvt", "private", "llc", "llp", "plc", "corp", "corporation", "co", "company",
    "the", "india", "group", "holdings", "gmbh", "ag", "sa", "bv", "nv",
}
_TITLE_STOP = {"and", "of", "the", "for", "in", "at", "to", "a", "an", "with", "on"}
_TITLE_SYNONYMS = {
    "sr": "senior", "snr": "senior", "jr": "junior", "mgr": "manager", "engg": "engineering", "eng": "engineer",
    "dev": "developer", "assoc": "associate", "exec": "executive", "asst": "assistant", "dir": "director",
    "vp": "vice president", "svp": "senior vice president", "avp": "assistant vice president", "ml": "machine learning",
    "ai": "artificial intelligence", "qa": "quality assurance", "hr": "human resources", "ui": "user interface",
    "ux": "user experience", "fullstack": "full stack", "frontend": "front end", "backend": "back end",
}
# Requisition ids and the like: "R199615", "JR-12345", "#4521".
_REQ_ID = re.compile(r"\b(?:[a-z]{0,3}-?\d{4,}|#\s*\d+)\b")

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "jobs": [], "keys": set()}


def _words(text: Any) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split()


def _company(text: Any) -> str:
    # "Cigna (Evernorth)" -> "cigna"
    base = re.sub(r"\(.*?\)", " ", str(text or ""))
    return " ".join(w for w in _words(base) if w not in _COMPANY_NOISE)


def _title_tokens(text: Any) -> list[str]:
    cleaned = _REQ_ID.sub(" ", str(text or "").lower())
    out = []
    for word in _words(cleaned):
        out.extend(_TITLE_SYNONYMS.get(word, word).split())
    return [w for w in out if w not in _TITLE_STOP]


def _city(text: Any) -> str:
    return " ".join(_words(text))


def company_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    # "jll" vs "jll india", "hitachi" vs "hitachi energy": one name contains the other.
    if ta <= tb or tb <= ta:
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def title_similarity(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    dice = 2 * len(sa & sb) / (len(sa) + len(sb))
    # Typos and spacing ("Sofware Engineer") still count, but loose look-alikes don't.
    ratio = SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()
    return max(dice, ratio if ratio >= 0.9 else 0.0)


def location_similarity(cities: set[str], states: set[str], remote: bool, other: dict) -> float:
    if remote and other["remote"]:
        return 1.0
    if not cities or not other["cities"]:
        return 0.5  # unknown: neither evidence for nor against
    if cities & other["cities"]:
        return 1.0
    if states & other["states"]:
        return 0.6
    return 0.0


def _locations(locs: list) -> tuple[set[str], set[str], bool]:
    cities = {_city(l.get("city")) for l in locs or [] if l.get("city")}
    states = {_city(l.get("state")) for l in locs or [] if l.get("state")}
    remote = any(l.get("remote") for l in locs or [])
    return cities, states, remote


def _site_job(job: dict) -> dict:
    cities, states, remote = _locations(job.get("locations"))
    first = (job.get("locations") or [{}])[0]
    return {
        "jobId": job.get("jobId"),
        "title": job.get("title") or "",
        "company": job.get("companyName") or "",
        "city": first.get("city") or ("Remote" if remote else ""),
        "sourceType": job.get("sourceType"),
        "publishedAt": job.get("publishedAt"),
        "externalListingUrl": job.get("externalListingUrl"),
        "keys": job_keys(job.get("companyName"), job.get("title"), first.get("city"), job.get("externalListingUrl")),
        "_company": _company(job.get("companyName")),
        "_title": _title_tokens(job.get("title")),
        "cities": cities, "states": states, "remote": remote,
    }


def _fetch_site_jobs() -> list[dict]:
    jobs, page = [], 0
    while page < MAX_PAGES:
        response = requests.get(SEARCH_URL, params={"page": page, "pageSize": PAGE_SIZE}, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json().get("data") or {}
        jobs.extend(_site_job(j) for j in data.get("content") or [])
        page += 1
        if data.get("last", True) or page >= (data.get("totalPages") or 0):
            break
    return jobs


def site_jobs() -> list[dict]:
    """Every published WorkOwon job (external and posted on the site), refreshed every few minutes."""
    with _lock:
        if time.time() - _cache["at"] > CACHE_SECONDS:
            try:
                jobs = _fetch_site_jobs()
                _cache.update(at=time.time(), jobs=jobs, keys=set().union(*(j["keys"] for j in jobs)))
            except (requests.RequestException, ValueError) as exc:  # keep the last good copy
                logging.warning("Could not load WorkOwon jobs for duplicate check: %s", exc)
        return _cache["jobs"]


def site_job_keys() -> set[str]:
    """job_keys of every published WorkOwon job, for hiding exact duplicates."""
    site_jobs()
    return _cache["keys"]


def remember_posted(payload: dict, job_id: str | None) -> None:
    """Count a job posted from here right away, so a near copy in the same batch is caught too."""
    job = _site_job({
        "jobId": job_id, "title": payload.get("title"), "companyName": payload.get("externalCompanyName"),
        "locations": payload.get("locations"), "externalListingUrl": payload.get("externalListingUrl"),
        "sourceType": "EXTERNAL",
    })
    with _lock:
        _cache["jobs"].append(job)
        _cache["keys"] |= job["keys"]


def _reason(title: float, company: float, location: float) -> str:
    parts = ["same title" if title >= 0.99 else "similar title"]
    parts.append("same company" if company >= 0.99 else "similar company name")
    parts.append({1.0: "same location", 0.6: "same state", 0.0: "different city"}.get(location, "location unknown"))
    return ", ".join(parts)


def find_matches(payload: dict, jobs: list[dict] | None = None, limit: int = 3) -> list[dict]:
    """WorkOwon jobs that look like this posting payload, best first, each with a 0-100 score."""
    jobs = site_jobs() if jobs is None else jobs
    company = _company(payload.get("externalCompanyName"))
    title = _title_tokens(payload.get("title"))
    cities, states, remote = _locations(payload.get("locations"))
    keys = job_keys(payload.get("externalCompanyName"), payload.get("title"),
                    ((payload.get("locations") or [{}])[0]).get("city"), payload.get("externalListingUrl"))
    company_sims: dict[str, float] = {}
    found = []
    for job in jobs:
        url_match = any(k.startswith("url:") for k in keys & job["keys"])
        if url_match:
            score, reason = 100, "same listing URL"
        else:
            if job["_company"] not in company_sims:
                company_sims[job["_company"]] = company_similarity(company, job["_company"])
            c = company_sims[job["_company"]]
            if c < MIN_COMPANY_SIMILARITY:
                continue
            t = title_similarity(title, job["_title"])
            if t < 0.5:
                continue
            loc = location_similarity(cities, states, remote, job)
            # The title decides; company and location move the score within its range.
            score = round(100 * t * (0.6 + 0.2 * c + 0.2 * loc))
            reason = _reason(t, c, loc)
        if score >= POSSIBLE:
            found.append({
                "score": score, "level": "likely" if score >= LIKELY else "possible", "reason": reason,
                "jobId": job["jobId"], "title": job["title"], "company": job["company"], "city": job["city"],
                "sourceType": job["sourceType"], "publishedAt": job["publishedAt"],
                "url": SITE_JOB_URL.format(job["jobId"]) if job["jobId"] else job["externalListingUrl"],
            })
    found.sort(key=lambda m: m["score"], reverse=True)
    return found[:limit]


def best_match(payload: dict, jobs: list[dict] | None = None) -> dict | None:
    matches = find_matches(payload, jobs, limit=3)
    if not matches:
        return None
    return {**matches[0], "others": matches[1:]}
