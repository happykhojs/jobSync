"""
Search the company catalog (boards.json) for jobs matching dashboard filters.

Filtering happens at listing level (title, department, location, posted date) before any
details are fetched or records built, so a search only does work for jobs it will show.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

import job_scraper
from enrich import logo_from_website
from post_jobs import EMPLOYMENT_TYPES, WORKPLACE_TYPES, interleave_companies, normalize

INDIA = (
    r"india|bengaluru|bangalore|mumbai|pune|hyderabad|chennai|delhi|gurgaon|gurugram|noida|"
    r"ghaziabad|faridabad|kolkata|ahmedabad|jaipur|kochi|coimbatore|chandigarh|indore|lucknow|thane"
)
LOCATIONS = {
    "Delhi NCR": r"delhi|gurgaon|gurugram|noida|ghaziabad|faridabad|\bncr\b",
    "Bengaluru": r"bengaluru|bangalore",
    "Mumbai": r"mumbai|thane",
    "Pune": r"pune",
    "Hyderabad": r"hyderabad",
    "Chennai": r"chennai",
    "Kolkata": r"kolkata",
    "Ahmedabad": r"ahmedabad",
    "Remote (India)": r"remote|work from home|anywhere",
}
EXPERIENCE_LEVELS = ["ENTRY", "MID", "SENIOR", "LEAD", "EXECUTIVE"]
# Experience bands shown in the filter: (label, min years from, min years to)
EXPERIENCE_BANDS = {
    "Internship": None,
    "Fresher (0–1 yrs)": (0, 1),
    "1–3 yrs": (1, 3),
    "3–5 yrs": (3, 5),
    "5–10 yrs": (5, 10),
    "10+ yrs": (10, 99),
}
# When a job states no years, fall back to its level.
LEVEL_BANDS = {
    "INTERNSHIP": {"Internship"},
    "ENTRY": {"Fresher (0–1 yrs)"},
    "MID": {"1–3 yrs", "3–5 yrs"},
    "SENIOR": {"5–10 yrs"},
    "LEAD": {"10+ yrs"},
    "EXECUTIVE": {"10+ yrs"},
}
INTERN_RE = re.compile(r"\b(intern|internship|trainee|apprentice|apprenticeship|co-?op|summer analyst)\b", re.I)
FRESHER_RE = re.compile(r"\b(fresher|graduate|entry[- ]level|campus|freshers|0\s*[-–]\s*1\s*(years?|yrs?))\b", re.I)
# Titles that usually mean an entry-level role; used to pre-filter listings for fresher searches.
ENTRY_TITLE_RE = re.compile(
    r"\b(fresher|graduate|trainee|entry[- ]level|junior|jr\.?|associate|apprentice|campus|analyst i|engineer i|"
    r"executive|assistant|specialist i|developer i|(?:[a-z]+ )?i)\s*$|\b(fresher|graduate|trainee|junior|jr\.?|entry[- ]level)\b",
    re.I,
)
# Companies sometimes publish placeholder postings like "TEST JR-do not apply".
TEST_POSTING_RE = re.compile(r"do not apply|\btest (employee|job|posting|requisition|jr)\b|^\s*test\b", re.I)
SENIOR_TITLE_RE = re.compile(r"\b(senior|sr\.?|lead|principal|staff|manager|head|director|vp|vice president|avp|chief)\b", re.I)


def experience_bands(rec: dict) -> set[str]:
    """Which experience filter bands a job belongs to."""
    title = rec.get("title") or ""
    if INTERN_RE.search(title) or "intern" in str(rec.get("employmentType") or "").lower():
        return {"Internship"}
    bands = set()
    lo = rec.get("experienceMinYears")
    if lo is not None:
        bands |= {label for label, rng in EXPERIENCE_BANDS.items() if rng and rng[0] <= lo <= rng[1]}
    else:
        bands |= LEVEL_BANDS.get(rec.get("experienceLevel") or "", set())
    if FRESHER_RE.search(title):
        bands.add("Fresher (0–1 yrs)")
    return bands
EMPLOYMENT = ["FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP", "FREELANCE"]
WORKPLACE = ["ONSITE", "HYBRID", "REMOTE"]
POSTED_WITHIN = [1, 3, 7, 14, 30]
MAX_WORKERS = 16


def options(catalog: list[dict]) -> dict:
    return {
        "locations": list(LOCATIONS),
        "sectors": sorted({b.get("sector") for b in catalog if b.get("sector")}),
        "companyTypes": sorted({b.get("companyType") for b in catalog if b.get("companyType")}),
        # Biggest India employers first, with their opening counts for the filter labels.
        "companies": [b["companyName"] for b in sorted(catalog, key=lambda b: b.get("indiaOpenings") or 0, reverse=True)],
        "companyOpenings": {b["companyName"]: b.get("indiaOpenings") or 0 for b in catalog},
        "sectorOpenings": {
            sector: sum(b.get("indiaOpenings") or 0 for b in catalog if b.get("sector") == sector)
            for sector in {b.get("sector") for b in catalog}
        },
        "experienceLevels": EXPERIENCE_LEVELS,
        "experience": list(EXPERIENCE_BANDS),
        "employmentTypes": EMPLOYMENT,
        "workplaceTypes": WORKPLACE,
        "postedWithin": POSTED_WITHIN,
    }


def _location_regex(locations: list[str]) -> re.Pattern:
    chosen = [LOCATIONS[l] for l in locations if l in LOCATIONS]
    return re.compile("|".join(chosen) if chosen else INDIA, re.I)


def _keyword_regex(keywords: str) -> re.Pattern | None:
    terms = [t.strip() for t in re.split(r"[,;]", keywords or "") if t.strip()]
    if not terms:
        return None
    return re.compile("|".join(rf"(?<!\w){re.escape(t)}(?!\w)" for t in terms), re.I)


def search(criteria: dict, catalog: list[dict], exclude: set[str]) -> dict:
    count = max(1, min(int(criteria.get("count") or 10), 50))
    sectors = set(criteria.get("sectors") or [])
    types = set(criteria.get("companyTypes") or [])
    companies = set(criteria.get("companies") or [])
    boards = [
        b for b in catalog
        if (not sectors or b.get("sector") in sectors)
        and (not types or b.get("companyType") in types)
        and (not companies or b["companyName"] in companies)
    ]

    loc_re = _location_regex(criteria.get("locations") or [])
    remote_only = criteria.get("locations") == ["Remote (India)"]
    india_re = re.compile(INDIA, re.I)
    kw_re = _keyword_regex(criteria.get("keywords", ""))
    days = int(criteria.get("postedWithinDays") or 30)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Internship/fresher-only searches can be narrowed from the title before any details are fetched.
    chosen_bands = set(criteria.get("experience") or [])
    intern_only = chosen_bands == {"Internship"}
    entry_only = bool(chosen_bands) and chosen_bands <= {"Internship", "Fresher (0–1 yrs)"} and not intern_only

    def keep(title: str, locations: list[str], posted: str | None, extra: str) -> bool:
        if TEST_POSTING_RE.search(title):
            return False
        if not posted or posted < cutoff:
            return False
        joined = " | ".join(locations)
        if not loc_re.search(joined):
            return False
        # Remote roles must still be open to India.
        if remote_only and not (india_re.search(joined) or joined.strip().lower() in ("remote", "")):
            return False
        if intern_only and not INTERN_RE.search(title):
            return False
        if entry_only and not (INTERN_RE.search(title) or (ENTRY_TITLE_RE.search(title) and not SENIOR_TITLE_RE.search(title))):
            return False
        return not kw_re or bool(kw_re.search(f"{title} {extra}"))

    # Post-enrichment filters (level/type/workplace) drop some jobs, so fetch a few spares.
    levels = set(criteria.get("experienceLevels") or [])
    bands = set(criteria.get("experience") or []) & set(EXPERIENCE_BANDS)
    employment = set(criteria.get("employmentTypes") or [])
    workplace = set(criteria.get("workplaceTypes") or [])
    # Already posted/skipped jobs are only known after records are built, so leave a little headroom.
    # Experience bands are only known after details load (years live in the description), so fetch more spares.
    target = count * 3 if (bands - {"Internship"}) else count * 2 if (levels or employment or workplace) else count + max(2, count // 3)
    terms = [t.strip() for t in re.split(r"[,;]", criteria.get("keywords", "")) if t.strip()]
    query = terms[0] if len(terms) == 1 else None

    def call(board: dict, **kwargs: Any) -> list:
        return job_scraper.SCRAPERS[board["provider"]](
            board["board"], keep=keep, query=query, country=board.get("country"), **kwargs,
        )

    def safely(fn, board: dict):
        try:
            return board, fn(board), None
        except Exception as exc:  # one broken board shouldn't fail the search
            logging.warning("Search: %s/%s failed: %s", board["provider"], board["board"], exc)
            return board, None, f"{board['companyName']}: {exc}"

    errors: list[str] = []
    # Phase 1: listings only (cheap, cached) -> how many matches each company has.
    with ThreadPoolExecutor(MAX_WORKERS) as pool:
        counted = list(pool.map(lambda b: safely(lambda x: call(x, count_only=True, limit=target), b), boards))
    available = {}
    for board, posted, err in counted:
        if err:
            errors.append(err)
        elif posted:
            available[board["board"]] = (board, len(posted))
    matched_total = sum(n for _, n in available.values())

    # Spread the quota round-robin, companies with more India openings first.
    ranked = sorted(available.values(), key=lambda bn: bn[0].get("indiaOpenings") or 0, reverse=True)
    quotas = {b["board"]: 0 for b, _ in ranked}
    remaining = target
    while remaining > 0 and any(quotas[b["board"]] < n for b, n in ranked):
        for b, n in ranked:
            if remaining and quotas[b["board"]] < n:
                quotas[b["board"]] += 1
                remaining -= 1

    # Phase 2: full details only for the jobs we will show.
    chosen = [b for b, _ in ranked if quotas[b["board"]]]
    found = []
    with ThreadPoolExecutor(MAX_WORKERS) as pool:
        for board, records, err in pool.map(lambda b: safely(lambda x: call(x, limit=quotas[x["board"]]), b), chosen):
            if err:
                errors.append(err)
            for rec in records or []:
                rec["externalCompanyName"] = board["companyName"]
                rec["externalCompanyWebsite"] = board.get("website", "")
                rec["externalCompanyLogoUrl"] = rec["externalCompanyLogoUrl"] or logo_from_website(board.get("website", ""))
                rec["sector"] = board.get("sector", "")
                rec["companyType"] = board.get("companyType", "")
                rec["indiaOpenings"] = board.get("indiaOpenings") or 0
                # Searched location first, so it becomes the primary location.
                rec["locations"].sort(key=lambda l: not loc_re.search(l.get("raw") or ""))
                found.append(rec)

    def passes(rec: dict) -> bool:
        # Listings like "3 Locations" are only resolved after details load.
        if not any(loc_re.search(l.get("raw") or "") for l in rec["locations"]):
            return False
        level = "ENTRY" if rec.get("experienceLevel") == "INTERNSHIP" else rec.get("experienceLevel")
        if bands and not (experience_bands(rec) & bands):
            return False
        if levels and level not in levels:
            return False
        if employment and (normalize(rec.get("employmentType"), EMPLOYMENT_TYPES) or "FULL_TIME") not in employment:
            return False
        if workplace and (normalize(rec.get("workplaceType"), WORKPLACE_TYPES) or "ONSITE") not in workplace:
            return False
        return rec["sourceKey"] not in exclude

    matched = [r for r in found if passes(r)]
    # Newest first within a company; companies with more openings lead each round.
    matched.sort(key=lambda r: r.get("sourceUpdatedAt") or "", reverse=True)
    matched.sort(key=lambda r: r["indiaOpenings"], reverse=True)
    results = interleave_companies(matched)[:count]
    return {
        "records": results,
        "matched": matched_total,
        "companiesSearched": len(boards),
        "errors": errors,
    }
