#!/usr/bin/env python3
"""
Post collected jobs from jobs.json to the Workowon admin external-jobs API.

Dry run by default (prints payloads, sends nothing). Add --send to actually post.

Settings come from .env (or real environment variables):
    WORKOWON_TOKEN=your-admin-access-token
    POST_LIMIT=5        # jobs per run; 0 = all not yet posted

    GEMINI_API_KEY=...  # optional, used only with --ai (results cached in curated_jobs.json)
    GEMINI_MODEL=gemini-flash-lite-latest

Run:
    python3 post_jobs.py                # preview POST_LIMIT payloads
    python3 post_jobs.py --send         # post POST_LIMIT jobs
    python3 post_jobs.py --limit 10     # override POST_LIMIT for this run
    python3 post_jobs.py --send --ai    # improve listings with Gemini first
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from curate import apply_curation, curate_jobs
from htmlfmt import to_site_html
from workowon import BASE_URL, external_job_keys, record_keys

BASE_DIR = Path(__file__).resolve().parent
JOBS_FILE = BASE_DIR / "jobs.json"
POSTED_FILE = BASE_DIR / "posted_jobs.json"
ENV_FILE = BASE_DIR / ".env"

API_URL = "https://api.workowon.com/api/jobs/admin/external-jobs"
TIMEOUT = 30
REQUEST_DELAY_SECONDS = 0.5
# Source APIs rarely give an expiry date; expire listings this many days after posting.
DEFAULT_EXPIRY_DAYS = 30

# Adjust these to whatever enum values your API expects.
# Source values are matched by keyword (first match wins), e.g. "Full-time Employment", "On-roll".
EMPLOYMENT_TYPES = [
    (r"intern", "INTERNSHIP"),
    (r"freelance", "FREELANCE"),
    (r"contract|consult|temp", "CONTRACT"),
    (r"part", "PART_TIME"),
    (r"full|permanent|on-?roll|regular", "FULL_TIME"),
]
WORKPLACE_TYPES = [
    (r"remote", "REMOTE"),
    (r"hybrid", "HYBRID"),
    (r"on-?site|office", "ONSITE"),
]
EMPLOYMENT_LABELS = {
    "FULL_TIME": "Full Time", "PART_TIME": "Part Time", "CONTRACT": "Contract",
    "INTERNSHIP": "Internship", "FREELANCE": "Freelance",
}
# enrich.py levels -> API enum (ENTRY, MID, SENIOR, LEAD, EXECUTIVE)
EXPERIENCE_LEVELS = {
    "INTERNSHIP": "ENTRY",
    "ENTRY": "ENTRY",
    "MID": "MID",
    "SENIOR": "SENIOR",
    "LEAD": "LEAD",
    "EXECUTIVE": "EXECUTIVE",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def normalize(value: Any, mapping: list[tuple[str, str]]) -> str | None:
    text = str(value or "").lower()
    return next((api_value for pattern, api_value in mapping if re.search(pattern, text)), None)


def build_payload(job: dict) -> dict:
    title_and_locs = " ".join([job["title"]] + [l.get("raw") or "" for l in job["locations"]])
    # The API requires both types, but many sources (e.g. Greenhouse) omit them, so infer a default.
    workplace = normalize(job.get("workplaceType"), WORKPLACE_TYPES)
    if not workplace:
        if re.search(r"\bremote\b", title_and_locs, re.I):
            workplace = "REMOTE"
        elif re.search(r"\bhybrid\b", f"{title_and_locs} {job.get('description') or ''}", re.I):
            workplace = "HYBRID"
        else:
            workplace = "ONSITE"
    employment = normalize(job.get("employmentType"), EMPLOYMENT_TYPES) or normalize(job["title"], EMPLOYMENT_TYPES[:4]) or "FULL_TIME"
    expires = datetime.now(timezone.utc) + timedelta(days=DEFAULT_EXPIRY_DAYS)

    payload = {
        "externalCompanyName": job["externalCompanyName"],
        "externalCompanyLogoUrl": job.get("externalCompanyLogoUrl") or None,
        "externalCompanyWebsite": job.get("externalCompanyWebsite") or None,
        "externalListingUrl": job["externalListingUrl"],
        "title": job["title"],
        "description": to_site_html(job["description"]) or f"<p>{html.escape(job['title'])}</p>",
        "requirements": to_site_html(job.get("requirements") or "") or None,
        "employmentType": employment,
        "workplaceType": workplace,
        "experienceLevel": EXPERIENCE_LEVELS.get(job.get("experienceLevel") or ""),
        "experienceMinYears": job.get("experienceMinYears"),
        "experienceMaxYears": job.get("experienceMaxYears"),
        "salaryMin": job.get("salaryMin"),
        "salaryMax": job.get("salaryMax"),
        "salaryCurrency": job.get("salaryCurrency") or None,
        "salaryPeriod": job.get("salaryPeriod") or None,
        "salaryVisible": bool(job.get("salaryVisible")),
        "openings": job.get("openings") or 1,
        "expiresAt": job.get("expiresAt") or expires.isoformat().replace("+00:00", "Z"),
        "locations": [
            {k: l.get(k) for k in ("city", "state", "country")} | {"remote": bool(l.get("remote"))}
            for l in job["locations"] if l.get("raw")
        ],
        "skills": job.get("skills") or [],
        # Same tag style as jobs posted by hand: company, job type, sector, function/role keywords.
        "tags": sorted(dict.fromkeys(t for t in [
            job["externalCompanyName"], EMPLOYMENT_LABELS.get(employment), job.get("sector"), *job.get("tags", []),
        ] if t)),
        "benefits": job.get("benefits") or [],
    }
    # Drop unknown values rather than sending nulls/blank strings the API may reject.
    return {k: v for k, v in payload.items() if v is not None}


def improve_payload(payload: dict, fields: dict, sector: str | None = None) -> dict:
    """Overlay AI-curated fields on an API payload, keeping the site's tag style."""
    improved = apply_curation(payload, fields)
    improved["tags"] = sorted(dict.fromkeys(t for t in [
        improved.get("externalCompanyName"), EMPLOYMENT_LABELS.get(improved.get("employmentType")), sector,
        *(fields.get("tags") or payload.get("tags") or []),
    ] if t))
    return improved


def interleave_companies(jobs: list[dict]) -> list[dict]:
    """Round-robin by company (keeping each company's newest first) so one board doesn't dominate a run."""
    by_company: dict[str, list[dict]] = {}
    for job in jobs:
        by_company.setdefault(job["externalCompanyName"], []).append(job)
    queues = list(by_company.values())
    ordered = []
    while queues:
        ordered.extend(q.pop(0) for q in queues)
        queues = [q for q in queues if q]
    return ordered


def load_env(path: Path) -> None:
    # Minimal .env reader (KEY=value lines); real environment variables take precedence.
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip("'\"")
        os.environ.setdefault(key.strip(), value)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    load_env(ENV_FILE)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--send", action="store_true", help="actually POST (default is a dry run)")
    parser.add_argument("--limit", type=int, default=int(os.environ.get("POST_LIMIT") or 0),
                        help="max jobs to process (0 = all); defaults to POST_LIMIT from .env")
    parser.add_argument("--ai", action="store_true", help="improve listings with Gemini before posting (uses tokens)")
    args = parser.parse_args()

    jobs = load_json(JOBS_FILE, [])
    posted = load_json(POSTED_FILE, {})
    pending = interleave_companies([j for j in jobs if j.get("sourceKey") not in posted])
    if args.limit:
        pending = pending[: args.limit]
    logging.info("%d jobs in %s, %d already posted, processing %d", len(jobs), JOBS_FILE.name, len(posted), len(pending))
    if args.ai:
        # Curate only this run's jobs; cached results make re-runs (e.g. preview then --send) free.
        curated = curate_jobs(pending)
        pending = [apply_curation(j, curated[j["sourceKey"]]) if j["sourceKey"] in curated else j for j in pending]

    if not args.send:
        for job in pending:
            print(json.dumps(build_payload(job), ensure_ascii=False, indent=2)[:4000])
            print("-" * 60)
        logging.info("Dry run only. Re-run with --send to post.")
        return

    token = os.environ.get("WORKOWON_TOKEN")
    if not token:
        raise SystemExit(f"Set WORKOWON_TOKEN in {ENV_FILE} (or the environment) first.")
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
    })

    # Skip jobs already on WorkOwon (posted from another machine, or the same job from another site).
    existing = external_job_keys(lambda path, params: session.get(BASE_URL + path, params=params, timeout=TIMEOUT))
    ok = failed = 0
    for job in pending:
        if record_keys(job) & existing:
            logging.info("Already on WorkOwon, skipped: %s | %s", job["externalCompanyName"], job["title"])
            continue
        try:
            response = session.post(API_URL, json=build_payload(job), timeout=TIMEOUT)
        except requests.RequestException as exc:
            logging.error("%s | %s: %s", job["externalCompanyName"], job["title"], exc)
            failed += 1
            continue
        if response.ok:
            ok += 1
            existing |= record_keys(job)
            posted[job["sourceKey"]] = {
                "postedAt": datetime.now(timezone.utc).isoformat(),
                "title": job["title"],
                "company": job["externalCompanyName"],
                "response": response.text[:500],
            }
            # Save after every success so a crash never causes duplicate posts.
            POSTED_FILE.write_text(json.dumps(posted, ensure_ascii=False, indent=2), encoding="utf-8")
            logging.info("Posted: %s | %s", job["externalCompanyName"], job["title"])
        else:
            failed += 1
            logging.error("HTTP %s for %s | %s: %s", response.status_code, job["externalCompanyName"], job["title"], response.text[:500])
            if response.status_code in (401, 403):
                raise SystemExit("Auth failed; check WORKOWON_TOKEN.")
        time.sleep(REQUEST_DELAY_SECONDS)

    logging.info("Done. %d posted, %d failed.", ok, failed)


if __name__ == "__main__":
    main()
