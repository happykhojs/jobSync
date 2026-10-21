#!/usr/bin/env python3
"""
Khojs public job-board collector (collection-only; does NOT call your API).

Supports public Greenhouse, Lever, Ashby, SmartRecruiters and Workday job boards.
Configure board identifiers in boards.json, run this script, and review jobs.json.
Structured fields (requirements, experience, skills, benefits, salary, locations)
are extracted from the listing text by enrich.py.

Install:
    python3 -m pip install requests beautifulsoup4

Run:
    python3 job_scraper.py
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from bs4 import BeautifulSoup

from enrich import REQUIREMENT_HEADINGS, enrich, logo_from_website, parse_location

BASE_DIR = Path(__file__).resolve().parent
BOARDS_FILE = BASE_DIR / "boards.json"
OUTPUT_FILE = BASE_DIR / "jobs.json"
SEEN_FILE = BASE_DIR / "seen_jobs.json"

TIMEOUT = 25
REQUEST_DELAY_SECONDS = 0.5
# Only keep "latest" jobs: posted/updated within this many days, newest N per board.
MAX_AGE_DAYS = 30
MAX_JOBS_PER_BOARD = 25
CACHE_SECONDS = 30 * 60
USER_AGENT = "KhojsJobResearchBot/0.1 (public job listing collection; contact: admin@khojs.com)"

# Set from boards.json "locationFilter" (regex); jobs with no matching location are dropped.
LOCATION_FILTER: re.Pattern | None = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


_CACHE: dict[str, tuple[float, Any]] = {}


def get_json(url: str, params: dict | None = None) -> Any:
    # Short-lived in-memory cache: repeated searches in the dashboard don't re-download boards.
    key = url + "?" + json.dumps(params or {}, sort_keys=True)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    response = session.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()
    _CACHE[key] = (time.time(), data)
    return data


def clean_html(value: Any) -> str:
    if not value:
        return ""
    # Greenhouse returns entity-escaped HTML, so unescape before stripping tags.
    soup = BeautifulSoup(html.unescape(str(value)), "html.parser")
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True)).strip()


def first_nonempty(*values: Any) -> Any:
    for value in values:
        if value is not None and str(value).strip():
            return value
    return None


def to_iso(value: Any) -> str | None:
    """Normalize ISO strings and epoch-millisecond timestamps (Lever) to UTC ISO."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def location_matches(*texts: Any) -> bool:
    return LOCATION_FILTER is None or any(LOCATION_FILTER.search(str(t or "")) for t in texts)


def make_record(
    provider: str,
    board: str,
    source_id: Any,
    title: Any,
    company: Any,
    url: Any,
    description: Any = "",
    location: Any = "",
    updated_at: Any = None,
    employment_type: Any = None,
    workplace_type: Any = None,
    logo_url: Any = None,
    website: Any = None,
    raw: dict | None = None,
    requirements: Any = "",
    extra_locations: list | None = None,
    country_code: str | None = None,
    source_level: str | None = None,
    tags: list | None = None,
) -> dict | None:
    title = str(title or "").strip()
    url = str(url or "").strip()
    if not title or not url.startswith(("https://", "http://")):
        return None

    raw_locations = []
    for value in [location, *(extra_locations or [])]:
        if isinstance(value, dict):
            value = first_nonempty(value.get("name"), value.get("location"), "")
        value = str(value or "").strip()
        if value and value not in raw_locations:
            raw_locations.append(value)
    remote = str(workplace_type or "").lower() == "remote"
    # List locations matching the filter first so the primary location is the one we searched for.
    raw_locations.sort(key=lambda v: not location_matches(v))
    locations = [parse_location(v, country_code, remote) for v in raw_locations] or [parse_location("", country_code, remote)]

    stable_source_id = str(source_id or "").strip()
    dedupe_material = f"{provider}|{board}|{stable_source_id or url}"
    source_key = hashlib.sha256(dedupe_material.encode("utf-8")).hexdigest()

    record = {
        "sourceProvider": provider,
        "sourceBoard": board,
        "sourceJobId": stable_source_id or None,
        "sourceKey": source_key,
        "sourceUpdatedAt": to_iso(updated_at),
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "externalCompanyName": str(company or board).strip(),
        "externalCompanyLogoUrl": logo_url or "",
        "externalCompanyWebsite": website or "",
        "externalListingUrl": url,
        "title": title[:300],
        "description": clean_html(description)[:50000],
        "requirements": clean_html(requirements)[:20000],
        "employmentType": employment_type or "unspecified",
        "workplaceType": workplace_type or "unspecified",
        "experienceLevel": "",
        "experienceMinYears": None,
        "experienceMaxYears": None,
        "salaryMin": None,
        "salaryMax": None,
        "salaryCurrency": "",
        "salaryPeriod": "",
        "salaryVisible": False,
        "openings": None,
        "expiresAt": None,
        "locations": locations,
        "skills": [],
        "tags": [t for t in dict.fromkeys(str(x).strip() for x in (tags or [])) if t],
        "benefits": [],
        "rawSourceData": raw or {},
    }
    return enrich(record, source_level)


Keep = Callable[..., bool]


def _keep(keep: Keep | None, title: Any, locations: list, posted: Any, extra: Any = "") -> bool:
    """Apply a listing-level filter before building records, so non-matching jobs cost nothing."""
    if keep is None:
        return location_matches(*locations)
    return keep(
        title=str(title or ""),
        locations=[str(l) for l in locations if l],
        posted=to_iso(posted),
        extra=" ".join(str(x) for x in (extra if isinstance(extra, (list, tuple)) else [extra]) if x),
    )


def _newest(items: list, posted_of: Callable[[Any], Any], limit: int) -> list:
    items = sorted(items, key=lambda x: to_iso(posted_of(x)) or "", reverse=True)
    return items[:limit]


def scrape_greenhouse(board: str, keep: Keep | None = None, limit: int = MAX_JOBS_PER_BOARD, count_only: bool = False, **_: Any) -> list:
    # Public Greenhouse Job Board API; content=true includes descriptions/offices.
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    data = get_json(url, params={"content": "true"})
    matches = []
    for job in data.get("jobs", []):
        offices = [o.get("location") or o.get("name") for o in job.get("offices") or []]
        loc = first_nonempty((job.get("location") or {}).get("name"), *offices)
        departments = [d.get("name") for d in job.get("departments") or []]
        posted = first_nonempty(job.get("first_published"), job.get("updated_at"))
        if _keep(keep, job.get("title"), [loc, *offices], posted, departments):
            matches.append((job, loc, offices, departments, posted))
    if count_only:
        return [to_iso(m[4]) for m in matches]
    records = []
    for job, loc, offices, departments, posted in _newest(matches, lambda m: m[4], limit):
        record = make_record(
            "greenhouse", board, job.get("id"), job.get("title"), board,
            job.get("absolute_url"), job.get("content"), loc, posted, raw=job,
            extra_locations=offices, tags=departments,
        )
        if record:
            records.append(record)
    return records


def scrape_lever(board: str, keep: Keep | None = None, limit: int = MAX_JOBS_PER_BOARD, count_only: bool = False, **_: Any) -> list:
    url = f"https://api.lever.co/v0/postings/{board}"
    data = get_json(url, params={"mode": "json"})
    matches = []
    for job in data if isinstance(data, list) else []:
        categories = job.get("categories") or {}
        all_locations = categories.get("allLocations") or []
        location = first_nonempty(categories.get("location"), job.get("location"), "")
        posted = first_nonempty(job.get("createdAt"), job.get("updatedAt"))
        if _keep(keep, job.get("text"), [location, *all_locations], posted, [categories.get("department"), categories.get("team")]):
            matches.append(job)
    if count_only:
        return [to_iso(first_nonempty(j.get("createdAt"), j.get("updatedAt"))) for j in matches]
    records = []
    for job in _newest(matches, lambda j: first_nonempty(j.get("createdAt"), j.get("updatedAt")), limit):
        categories = job.get("categories") or {}
        # Lever splits postings into titled lists ("Requirements", "What you'll do", ...).
        description_parts = [job.get("description") or job.get("descriptionPlain") or ""]
        requirement_parts = []
        for section in job.get("lists") or []:
            heading = (section.get("text") or "").strip()
            block = f"<h3>{heading}</h3><ul>{section.get('content') or ''}</ul>"
            (requirement_parts if REQUIREMENT_HEADINGS.match(heading) else description_parts).append(block)
        description_parts.append(job.get("additional") or "")
        record = make_record(
            "lever", board, job.get("id"), job.get("text"), board,
            job.get("hostedUrl") or job.get("applyUrl"),
            "\n".join(description_parts),
            first_nonempty(categories.get("location"), job.get("location"), ""),
            first_nonempty(job.get("createdAt"), job.get("updatedAt")),
            categories.get("commitment"), job.get("workplaceType"), raw=job,
            requirements="\n".join(requirement_parts),
            extra_locations=categories.get("allLocations") or [],
            country_code=job.get("country"),
            tags=[categories.get("department"), categories.get("team")],
        )
        if record:
            salary = job.get("salaryRange") or {}
            if salary.get("min") and salary.get("max"):
                record.update(
                    salaryMin=salary["min"], salaryMax=salary["max"],
                    salaryCurrency=salary.get("currency") or "",
                    salaryPeriod="MONTHLY" if "month" in str(salary.get("interval", "")).lower() else "YEARLY",
                    salaryVisible=True,
                )
            records.append(record)
    return records


def scrape_ashby(board: str, keep: Keep | None = None, limit: int = MAX_JOBS_PER_BOARD, count_only: bool = False, **_: Any) -> list:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    data = get_json(url, params={"includeCompensation": "true"})
    matches = []
    for job in data.get("jobs", []):
        location = first_nonempty(job.get("location"), "")
        secondary = [x.get("location") for x in job.get("secondaryLocations") or [] if x.get("location")]
        posted = first_nonempty(job.get("publishedAt"), job.get("updatedAt"))
        if _keep(keep, job.get("title"), [location, *secondary], posted, [job.get("department"), job.get("team")]):
            matches.append((job, location, secondary, posted))
    if count_only:
        return [to_iso(m[3]) for m in matches]
    records = []
    for job, location, secondary, posted in _newest(matches, lambda m: m[3], limit):
        record = make_record(
            "ashby", board,
            first_nonempty(job.get("jobUrl"), job.get("applyUrl"), job.get("title")),
            job.get("title"), board,
            job.get("jobUrl") or job.get("applyUrl"),
            job.get("descriptionHtml") or job.get("descriptionPlain") or job.get("description"),
            location, posted,
            job.get("employmentType"), job.get("workplaceType"),
            raw=job,
            extra_locations=secondary,
            tags=[job.get("department"), job.get("team")],
        )
        if record:
            comp = job.get("compensation") or {}
            # Preserve only explicit structured compensation; don't infer a salary.
            if isinstance(comp, dict):
                record["rawSourceData"]["compensation"] = comp
            records.append(record)
    return records


def scrape_smartrecruiters(
    board: str, keep: Keep | None = None, limit: int = MAX_JOBS_PER_BOARD,
    query: str | None = None, country: str | None = None, count_only: bool = False, **_: Any,
) -> list:
    # Public SmartRecruiters Posting API: list is paginated; details hold the job ad sections.
    base = f"https://api.smartrecruiters.com/v1/companies/{board}/postings"
    params: dict[str, Any] = {"limit": 100}
    if country:
        params["country"] = country
    if query:
        params["q"] = query
    postings, offset = [], 0
    while True:
        page = get_json(base, params={**params, "offset": offset})
        postings.extend(page.get("content", []))
        offset += 100
        if offset >= page.get("totalFound", 0) or offset >= 1000:
            break
    # Only fetch details for matching postings to keep request volume low.
    matches = []
    for p in postings:
        loc = p.get("location") or {}
        extra = [(p.get("function") or {}).get("label"), (p.get("department") or {}).get("label")]
        if _keep(keep, p.get("name"), [loc.get("fullLocation"), loc.get("city")], p.get("releasedDate"), extra):
            matches.append(p)
    if count_only:
        return [to_iso(p.get("releasedDate")) for p in matches]

    records = []
    for posting in _newest(matches, lambda p: p.get("releasedDate"), limit):
        job = get_json(posting["ref"])
        sections = (job.get("jobAd") or {}).get("sections") or {}
        text = lambda key: (sections.get(key) or {}).get("text") or ""
        loc = job.get("location") or {}
        workplace = "remote" if loc.get("remote") else "hybrid" if loc.get("hybrid") else "onsite"
        record = make_record(
            "smartrecruiters", board, job.get("id"), job.get("name"),
            (job.get("company") or {}).get("name") or board,
            job.get("postingUrl") or job.get("applyUrl"),
            "\n".join([text("jobDescription"), text("companyDescription"), text("additionalInformation")]),
            ", ".join(x for x in [loc.get("city"), loc.get("region")] if x) or loc.get("fullLocation"),
            job.get("releasedDate"),
            (job.get("typeOfEmployment") or {}).get("label"), workplace,
            raw={k: v for k, v in job.items() if k != "jobAd"},
            requirements=text("qualifications"),
            country_code=loc.get("country"),
            source_level=(job.get("experienceLevel") or {}).get("id"),
            tags=[(job.get("function") or {}).get("label"), (job.get("industry") or {}).get("label")],
        )
        if record:
            records.append(record)
    return records


WORKDAY_PAGE = 20
WORKDAY_MAX_PAGES = 10


def post_json(url: str, body: dict) -> Any:
    key = url + "#" + json.dumps(body, sort_keys=True)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    response = session.post(url, json=body, timeout=TIMEOUT, headers={"Content-Type": "application/json"})
    response.raise_for_status()
    data = response.json()
    _CACHE[key] = (time.time(), data)
    return data


def _workday_base(board: str) -> tuple[str, str]:
    # board is "tenant/wdN/site", e.g. "jj/wd5/JJ"
    tenant, wd, site = board.split("/")
    host = f"https://{tenant}.{wd}.myworkdayjobs.com"
    return f"{host}/wday/cxs/{tenant}/{site}", f"{host}/{site}"


INDIA_PLACES = re.compile(
    r"\bindia\b|\bind\b|bengaluru|bangalore|mumbai|pune|hyderabad|chennai|delhi|gurgaon|gurugram|noida|"
    r"kolkata|ahmedabad|vadodara|jaipur|kochi|coimbatore|chandigarh|indore|lucknow|thane|mysuru|mysore|"
    r"visakhapatnam|vizag|bhubaneswar|goa|nagpur|nashik|surat|aurangabad|ghaziabad|faridabad|sriperumbudur",
    re.I,
)


def _location_facets(facets: list, param: str = "") -> list[tuple[str, dict]]:
    """Flatten Workday's nested facet groups into (facetParameter, value) pairs."""
    out = []
    for facet in facets or []:
        p = facet.get("facetParameter") or param
        for value in facet.get("values") or []:
            if value.get("values"):
                out.extend(_location_facets([value], value.get("facetParameter") or p))
            else:
                out.append((p, value))
    return out


def workday_country_facet(board: str) -> tuple[str, list[str], int] | None:
    """Facet filter selecting India: the country facet if the site has one, else every Indian location."""
    api, _ = _workday_base(board)
    data = post_json(f"{api}/jobs", {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
    pairs = _location_facets(data.get("facets") or [])
    for param, value in pairs:
        if "ountry" in param and str(value.get("descriptor", "")).strip().lower() == "india":
            return param, [value["id"]], int(value.get("count") or 0)
    cities = [(param, v) for param, v in pairs if param.lower() in ("locations", "location") and INDIA_PLACES.search(v.get("descriptor", ""))]
    if not cities:
        return None
    return cities[0][0], [v["id"] for _, v in cities], sum(int(v.get("count") or 0) for _, v in cities)


def _workday_posted(text: str) -> str | None:
    # "Posted Today" / "Posted Yesterday" / "Posted 5 Days Ago" / "Posted 30+ Days Ago"
    t = (text or "").lower()
    now = datetime.now(timezone.utc)
    if "today" in t:
        days = 0
    elif "yesterday" in t:
        days = 1
    else:
        m = re.search(r"(\d+)\+?\s*day", t)
        if not m:
            return None
        days = int(m.group(1)) + (1 if "+" in t else 0)
    return (now - timedelta(days=days)).isoformat()


def scrape_workday(
    board: str, keep: Keep | None = None, limit: int = MAX_JOBS_PER_BOARD,
    query: str | None = None, country: str | None = None, count_only: bool = False, **_: Any,
) -> list:
    api, public = _workday_base(board)
    facet = workday_country_facet(board) if country == "in" else None
    if country == "in" and not facet:
        return []  # no India openings on this site
    applied = {facet[0]: facet[1]} if facet else {}
    matches = []
    for page in range(WORKDAY_MAX_PAGES):
        data = post_json(f"{api}/jobs", {
            "appliedFacets": applied, "limit": WORKDAY_PAGE, "offset": page * WORKDAY_PAGE, "searchText": query or "",
        })
        postings = data.get("jobPostings") or []
        for p in postings:
            posted = _workday_posted(p.get("postedOn"))
            loc = p.get("locationsText") or ""
            # "3 Locations" hides the cities; let it through and check locations after loading details.
            locs = [loc] if not re.match(r"\d+ Locations", loc) else ["India"]
            if _keep(keep, p.get("title"), locs, posted, p.get("bulletFields") or []):
                matches.append((p, posted))
        # Listings come newest first; stop once we have enough candidates.
        if len(postings) < WORKDAY_PAGE or len(matches) >= (limit if count_only else limit * 2):
            break
    if count_only:
        return [m[1] for m in matches]
    records = []
    for p, posted in _newest(matches, lambda m: m[1], limit):
        info = (get_json(f"{api}{p['externalPath']}") or {}).get("jobPostingInfo") or {}
        locations = [info.get("location"), *(info.get("additionalLocations") or [])]
        remote_type = str(info.get("remoteType") or "").lower()
        workplace = "remote" if "remote" in remote_type else "hybrid" if "hybrid" in remote_type else ("onsite" if remote_type else None)
        record = make_record(
            "workday", board, info.get("jobReqId") or p.get("externalPath"), info.get("title") or p.get("title"),
            board.split("/")[0], info.get("externalUrl") or f"{public}{p['externalPath']}",
            info.get("jobDescription"), locations[0], info.get("startDate") or posted,
            info.get("timeType"), workplace, raw={k: v for k, v in info.items() if k != "jobDescription"},
            extra_locations=locations[1:], country_code=(info.get("country") or {}).get("descriptor"),
        )
        if record:
            records.append(record)
    return records


SCRAPERS = {
    "greenhouse": scrape_greenhouse,
    "lever": scrape_lever,
    "ashby": scrape_ashby,
    "smartrecruiters": scrape_smartrecruiters,
    "workday": scrape_workday,
}


def latest_only(jobs: list[dict]) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    fresh = [j for j in jobs if j["sourceUpdatedAt"] and datetime.fromisoformat(j["sourceUpdatedAt"]) >= cutoff]
    fresh.sort(key=lambda j: j["sourceUpdatedAt"], reverse=True)
    return fresh[:MAX_JOBS_PER_BOARD]


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Cannot read {path}: {exc}") from exc


def main() -> None:
    global LOCATION_FILTER
    boards_config = load_json(BOARDS_FILE, {"boards": []})
    boards = boards_config.get("boards", [])
    if not boards:
        raise SystemExit(
            f"No boards configured. Edit {BOARDS_FILE} and add public board IDs. "
            "See README.txt for examples."
        )
    if boards_config.get("locationFilter"):
        LOCATION_FILTER = re.compile(boards_config["locationFilter"], re.I)

    existing = load_json(OUTPUT_FILE, [])
    if not isinstance(existing, list):
        existing = []
    by_key = {
        item.get("sourceKey"): item
        for item in existing
        if isinstance(item, dict) and item.get("sourceKey")
    }

    errors = []
    fetched_count = 0
    for item in boards:
        provider = str(item.get("provider", "")).strip().lower()
        board = str(item.get("board", "")).strip()
        if provider not in SCRAPERS or not board:
            logging.warning("Skipping invalid board config: %r", item)
            continue
        try:
            logging.info("Fetching %s board: %s", provider, board)
            jobs = latest_only(SCRAPERS[provider](board, country=item.get("country")))
            fetched_count += len(jobs)
            configured_company = str(item.get("companyName", "")).strip()
            website = str(item.get("website", "")).strip()
            for job in jobs:
                # ATS board slugs are not necessarily legal/company display names.
                # Use a configured display name when supplied.
                if configured_company:
                    job["externalCompanyName"] = configured_company
                if website:
                    job["externalCompanyWebsite"] = website
                    job["externalCompanyLogoUrl"] = job["externalCompanyLogoUrl"] or logo_from_website(website)
                # Keep the newest observed copy for each stable source key.
                by_key[job["sourceKey"]] = job
            logging.info("Fetched %d jobs from %s/%s", len(jobs), provider, board)
        except requests.HTTPError as exc:
            msg = f"{provider}/{board}: HTTP error: {exc}"
            logging.error(msg)
            errors.append(msg)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            msg = f"{provider}/{board}: {type(exc).__name__}: {exc}"
            logging.error(msg)
            errors.append(msg)
        time.sleep(REQUEST_DELAY_SECONDS)

    all_jobs = list(by_key.values())
    all_jobs.sort(key=lambda j: str(j.get("sourceUpdatedAt") or ""), reverse=True)
    OUTPUT_FILE.write_text(json.dumps(all_jobs, ensure_ascii=False, indent=2), encoding="utf-8")

    # A small index file makes it easy to inspect what was seen between runs.
    SEEN_FILE.write_text(
        json.dumps(
            {
                "lastRunAt": datetime.now(timezone.utc).isoformat(),
                "fetchedThisRun": fetched_count,
                "uniqueJobsStored": len(all_jobs),
                "errors": errors,
                "sourceKeys": sorted(by_key.keys()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logging.info("Finished. Fetched %d this run; %d unique jobs in %s", fetched_count, len(all_jobs), OUTPUT_FILE)
    if errors:
        logging.warning("%d source(s) failed; see %s", len(errors), SEEN_FILE)


if __name__ == "__main__":
    main()
