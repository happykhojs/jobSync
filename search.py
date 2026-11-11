"""
Search the company catalog (boards.json) for jobs matching dashboard filters.

Filtering happens at listing level (title, department, location, posted date) before any
details are fetched or records built, so a search only does work for jobs it will show.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import job_scraper
from enrich import logo_from_website
from post_jobs import EMPLOYMENT_TYPES, WORKPLACE_TYPES, interleave_companies, normalize
from workowon import record_keys

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
    "Ahmedabad": r"ahmedabad|gandhinagar",
    "Kochi / Kerala": r"kochi|cochin|thiruvananthapuram|trivandrum|kerala",
    "Coimbatore": r"coimbatore",
    "Jaipur": r"jaipur",
    "Chandigarh / Mohali": r"chandigarh|mohali|panchkula",
    "Indore": r"indore",
    "Vadodara": r"vadodara|baroda",
    "Bhubaneswar": r"bhubaneswar",
    "Lucknow": r"lucknow",
    "Nagpur": r"nagpur",
    "Mysuru": r"mysuru|mysore",
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
# Company career sites (one employer per board) vs job platforms (many employers, marked "platform" in boards.json).
SOURCES = ["Company career sites", "Job platforms"]
# Tech = software/IT/data roles, read from the title; everything else (sales, finance, HR, hotel,
# operations, mechanical/civil engineering, pharma...) counts as non-tech.
ROLE_TYPES = ["Non-tech roles", "Tech roles"]
TECH_TITLE_RE = re.compile(
    r"software|developer|programmer|devops|\bsre\b|site reliability|full[- ]?stack|front[- ]?end|back[- ]?end|"
    r"\bdata (engineer|scientist|architect|analyst)|machine learning|\bml\b|\bai\b|\bllm|deep learning|"
    r"cloud|cyber|security (engineer|analyst|architect)|penetration|network engineer|\bqa\b|\bsdet\b|"
    r"test(ing)? (engineer|automation|lead)|automation (engineer|tester)|java|python|\.net\b|golang|react|angular|"
    r"node\.?js|android|\bios\b|mobile (developer|engineer)|\bui\b|\bux\b|database|\bdba\b|\bsap\b|salesforce|"
    r"servicenow|tech(nical)? lead|engineering manager|platform engineer|infrastructure|\bit (support|analyst|manager|specialist)|"
    r"system(s)? administrator|solutions? architect|enterprise architect|application (developer|engineer|support)|"
    r"firmware|embedded|\bvlsi\b|asic|fpga|computer vision|\bnlp\b|\bbi (developer|engineer)|power bi|tableau|etl|"
    r"big data|kubernetes|\baws\b|azure|\bgcp\b|sql\b|reliability engineer|network|application development|"
    r"\btechnical\b|microsoft dynamics|\berp\b|crm developer|it operations|helpdesk|service desk",
    re.I,
)
# Company size from India openings in the catalog (updated weekly by update_catalog.py).
COMPANY_SIZES = {
    "Large (200+ openings)": (200, None),
    "Mid-size (30–199 openings)": (30, 199),
    "Small (under 30 openings)": (0, 29),
}
NEW_COMPANY_DAYS = 30


def company_size(board: dict) -> str:
    n = board.get("indiaOpenings") or 0
    return next(label for label, (low, high) in COMPANY_SIZES.items() if n >= low and (high is None or n <= high))


def is_new_company(board: dict) -> bool:
    added = board.get("addedOn")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=NEW_COMPANY_DAYS)).date().isoformat()
    return bool(added) and added >= cutoff
SORTS = {"newest": "Newest first", "openings": "Biggest employers first"}
# 8, not 16: about as fast (sites are the bottleneck) and ~30 MB lighter on a small server.
MAX_WORKERS = 8


def is_startup(board: dict) -> bool:
    return "startup" in (board.get("companyType") or "").lower()


def is_small_company(board: dict) -> bool:
    return company_size(board) == "Small (under 30 openings)"


def options(catalog: list[dict]) -> dict:
    startups = [b for b in catalog if is_startup(b)]
    small = [b for b in catalog if is_small_company(b)]
    return {
        "locations": list(LOCATIONS),
        "sectors": sorted({b.get("sector") for b in catalog if b.get("sector")}),
        "companyTypes": sorted({b.get("companyType") for b in catalog if b.get("companyType")}),
        # Biggest India employers first, with their opening counts for the filter labels.
        "companies": [b["companyName"] for b in sorted(catalog, key=lambda b: b.get("indiaOpenings") or 0, reverse=True)],
        "companyOpenings": {b["companyName"]: b.get("indiaOpenings") or 0 for b in catalog},
        "sectorOpenings": {
            sector: sum(b.get("indiaOpenings") or 0 for b in catalog if b.get("sector") == sector)
            for sector in {b.get("sector") for b in catalog if b.get("sector")}
        },
        # Dedicated Startups filter: Indian Startup companies only, biggest first.
        "startups": [b["companyName"] for b in sorted(startups, key=lambda b: b.get("indiaOpenings") or 0, reverse=True)],
        "startupOpenings": {b["companyName"]: b.get("indiaOpenings") or 0 for b in startups},
        # Dedicated Smaller companies filter: under 30 India openings, biggest first.
        "smallCompanies": [b["companyName"] for b in sorted(small, key=lambda b: b.get("indiaOpenings") or 0, reverse=True)],
        "smallCompanyOpenings": {b["companyName"]: b.get("indiaOpenings") or 0 for b in small},
        "experienceLevels": EXPERIENCE_LEVELS,
        "experience": list(EXPERIENCE_BANDS),
        "employmentTypes": EMPLOYMENT,
        "workplaceTypes": WORKPLACE,
        "postedWithin": POSTED_WITHIN,
        "sources": SOURCES,
        "roleTypes": ROLE_TYPES,
        "companySizes": list(COMPANY_SIZES),
        "companySizeOpenings": {
            size: sum(b.get("indiaOpenings") or 0 for b in catalog if company_size(b) == size) for size in COMPANY_SIZES
        },
        # Companies added to the catalog in the last month, flagged "new" in the Companies filter.
        "newCompanies": [b["companyName"] for b in catalog if is_new_company(b)],
        "sorts": SORTS,
    }


# Shown in the keyword box before the admin types, and mixed into suggestions.
POPULAR_ROLES = [
    "Software Engineer", "Data Analyst", "Data Scientist", "Product Manager", "Business Analyst",
    "Sales Executive", "Account Executive", "Customer Success", "HR", "Recruiter", "Marketing",
    "Digital Marketing", "Finance", "Accountant", "Operations", "Supply Chain", "Project Manager",
    "UI/UX Designer", "DevOps Engineer", "Cloud Engineer", "QA Engineer", "Frontend Developer",
    "Backend Developer", "Full Stack Developer", "Machine Learning Engineer", "Cybersecurity",
    "Customer Support", "Content Writer", "Graphic Designer", "Mechanical Engineer", "Electrical Engineer",
    "Civil Engineer", "Pharmacist", "Clinical Research", "Medical Representative", "Legal", "Consultant",
    "Intern", "Graduate Trainee", "Teacher",
]
# Strip " - Team", "(Contract)", "II", "Sr." etc. so job titles group into common role names.
_TITLE_NOISE = re.compile(r"\s*[\(\[].*?[\)\]]|\s*,.*$|\s+[-–|/:].*$|\b(i{1,3}|iv|v|\d+)\s*$", re.I)


def _role_name(title: str) -> str:
    return re.sub(r"\s{2,}", " ", _TITLE_NOISE.sub("", title or "")).strip(" -")


def suggest(q: str, catalog: list[dict], jobs: list[dict], skills: list[str], limit: int = 8) -> list[dict]:
    """Keyword-box suggestions: roles (common + seen job titles), skills and companies."""
    q = (q or "").strip().lower()
    roles: dict[str, int] = {r: 1000 - i for i, r in enumerate(POPULAR_ROLES)}
    for job in jobs:
        name = _role_name(job.get("title") or "")
        if 3 <= len(name) <= 40:
            roles[name] = roles.get(name, 0) + 1
    if not q:
        return [{"text": r, "type": "role"} for r in POPULAR_ROLES[:limit]]

    def score(text: str) -> int:
        t = text.lower()
        if t == q:
            return 0
        if t.startswith(q):
            return 1
        if re.search(rf"\b{re.escape(q)}", t):
            return 2
        return 3 if q in t else -1

    found = []
    for kind, items in (
        ("role", roles),
        ("skill", {s: 0 for s in skills}),
        ("company", {b["companyName"]: b.get("indiaOpenings") or 0 for b in catalog}),
    ):
        for text, popularity in items.items():
            rank = score(text)
            if rank >= 0:
                found.append((rank, -popularity, len(text), text, kind))
    found.sort()
    seen, out = set(), []
    for _, _, _, text, kind in found:
        if text.lower() not in seen:
            seen.add(text.lower())
            out.append({"text": text, "type": kind})
        if len(out) >= limit:
            break
    return out


def _location_regex(locations: list[str]) -> re.Pattern:
    chosen = [LOCATIONS[l] for l in locations if l in LOCATIONS]
    return re.compile("|".join(chosen) if chosen else INDIA, re.I)


def _keyword_regex(keywords: str) -> re.Pattern | None:
    terms = [t.strip() for t in re.split(r"[,;]", keywords or "") if t.strip()]
    if not terms:
        return None
    return re.compile("|".join(rf"(?<!\w){re.escape(t)}(?!\w)" for t in terms), re.I)


def search(
    criteria: dict, catalog: list[dict], exclude: set[str], seen: set[str] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """exclude: sourceKeys already posted/skipped here; seen: workowon.job_keys of jobs already on WorkOwon.
    progress(done, total) is called as company sites answer, so the dashboard can show how far along it is."""
    seen = seen or set()
    progress = progress or (lambda done, total: None)
    count = max(1, min(int(criteria.get("count") or 10), 50))
    sectors = set(criteria.get("sectors") or [])
    types = set(criteria.get("companyTypes") or [])
    companies = set(criteria.get("companies") or [])
    startups = set(criteria.get("startups") or [])
    small_companies = set(criteria.get("smallCompanies") or [])
    # Company picker sections (Companies / Startups / Smaller) all select employers; either match is enough.
    wanted_companies = companies | startups | small_companies
    sources = set(criteria.get("sources") or []) & set(SOURCES)
    sizes = set(criteria.get("companySizes") or []) & set(COMPANY_SIZES)
    new_only = bool(criteria.get("newCompaniesOnly"))
    startups_only = bool(criteria.get("startupsOnly"))
    small_only = bool(criteria.get("smallCompaniesOnly"))
    # Both or neither role type selected means any role.
    role_types = set(criteria.get("roleTypes") or []) & set(ROLE_TYPES)
    tech_only = role_types == {"Tech roles"}
    non_tech_only = role_types == {"Non-tech roles"}
    boards = [
        b for b in catalog
        if (not sectors or b.get("sector") in sectors)
        and (not types or b.get("companyType") in types)
        and (not wanted_companies or b["companyName"] in wanted_companies)
        and (not sources or SOURCES[bool(b.get("platform"))] in sources)
        and (not sizes or company_size(b) in sizes)
        and (not new_only or is_new_company(b))
        and (not startups_only or is_startup(b))
        and (not small_only or is_small_company(b))
    ]

    loc_re = _location_regex(criteria.get("locations") or [])
    remote_only = criteria.get("locations") == ["Remote (India)"]
    india_re = re.compile(INDIA, re.I)
    kw_re = _keyword_regex(criteria.get("keywords", ""))
    exclude_re = _keyword_regex(criteria.get("excludeKeywords", ""))
    title_only = bool(criteria.get("titleOnly"))
    salary_only = bool(criteria.get("salaryOnly"))
    newest = criteria.get("sort") != "openings"
    days = int(criteria.get("postedWithinDays") or 30)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Internship/fresher-only searches can be narrowed from the title before any details are fetched.
    chosen_bands = set(criteria.get("experience") or [])
    intern_only = chosen_bands == {"Internship"}
    entry_only = bool(chosen_bands) and chosen_bands <= {"Internship", "Fresher (0–1 yrs)"} and not intern_only

    def keep(title: str, locations: list[str], posted: str | None, extra: str) -> bool:
        if TEST_POSTING_RE.search(title) or (exclude_re and exclude_re.search(title)):
            return False
        if not posted or posted < cutoff:
            return False
        joined = " | ".join(locations)
        if not loc_re.search(joined):
            return False
        # Remote roles must still be open to India.
        if remote_only and not (india_re.search(joined) or joined.strip().lower() in ("remote", "")):
            return False
        if (tech_only or non_tech_only) and bool(TECH_TITLE_RE.search(title)) != tech_only:
            return False
        if intern_only and not INTERN_RE.search(title):
            return False
        if entry_only and not (INTERN_RE.search(title) or (ENTRY_TITLE_RE.search(title) and not SENIOR_TITLE_RE.search(title))):
            return False
        return not kw_re or bool(kw_re.search(title if title_only else f"{title} {extra}"))

    # Post-enrichment filters (level/type/workplace) drop some jobs, so fetch a few spares.
    levels = set(criteria.get("experienceLevels") or [])
    bands = set(criteria.get("experience") or []) & set(EXPERIENCE_BANDS)
    employment = set(criteria.get("employmentTypes") or [])
    workplace = set(criteria.get("workplaceTypes") or [])
    # Already posted/skipped and duplicate jobs are only known after records are built, so leave some headroom.
    # Experience bands are only known after details load (years live in the description), so fetch more spares.
    target = count * 3 if (bands - {"Internship"}) or salary_only else count * 2 if (levels or employment or workplace) else count + max(3, count // 2)
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
    # Phase 2 (details for the chosen jobs) counts as the last few steps of the progress bar.
    total = len(boards) + 1
    counted = []
    with ThreadPoolExecutor(MAX_WORKERS) as pool:
        futures = [pool.submit(safely, lambda x: call(x, count_only=True, limit=target), b) for b in boards]
        for future in as_completed(futures):  # count each company as soon as it answers
            counted.append(future.result())
            progress(len(counted), total)
    available = {}
    for board, posted, err in counted:
        if err:
            errors.append(err)
        elif posted:
            available[board["board"]] = (board, sorted(posted, reverse=True))
    matched_total = sum(len(p) for _, p in available.values())
    ranked = sorted(available.values(), key=lambda bp: bp[0].get("indiaOpenings") or 0, reverse=True)
    quotas = {b["board"]: 0 for b, _ in ranked}
    remaining = target

    if newest:
        # Take the newest postings across all companies. On the first pass no company gets more
        # than a third of the slots, so one busy employer can't fill the whole page.
        pool = sorted(
            ((posted, i, b["board"]) for b, dates in ranked for i, posted in enumerate(dates)),
            reverse=True,
        )
        cap = max(2, -(-target // 3))
        for capped in (True, False):
            for _, i, key in pool:
                if remaining and i == quotas[key] and (not capped or quotas[key] < cap):
                    quotas[key] += 1
                    remaining -= 1
    else:
        # Spread the quota round-robin, companies with more India openings first.
        while remaining > 0 and any(quotas[b["board"]] < len(p) for b, p in ranked):
            for b, p in ranked:
                if remaining and quotas[b["board"]] < len(p):
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
                # Job platforms list many employers; keep each job's own company.
                if not board.get("platform"):
                    rec["externalCompanyName"] = board["companyName"]
                    rec["externalCompanyWebsite"] = board.get("website", "")
                    rec["externalCompanyLogoUrl"] = rec["externalCompanyLogoUrl"] or logo_from_website(board.get("website", ""))
                rec["sourceName"] = board["companyName"]
                rec["sector"] = board.get("sector", "")
                rec["companyType"] = board.get("companyType", "")
                rec["indiaOpenings"] = board.get("indiaOpenings") or 0
                # Searched location first, so it becomes the primary location.
                rec["locations"].sort(key=lambda l: not loc_re.search(l.get("raw") or ""))
                found.append(rec)
    progress(total, total)

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
        if salary_only and not rec.get("salaryVisible"):
            return False
        return rec["sourceKey"] not in exclude and not (record_keys(rec) & seen)

    matched, shown = [], set()
    for rec in sorted(found, key=lambda r: r.get("sourceUpdatedAt") or "", reverse=True):
        # The same job can be listed on two sites or reposted under a new requisition: keep the newest copy.
        keys = record_keys(rec)
        if passes(rec) and not keys & shown:
            shown |= keys
            matched.append(rec)
    if newest:
        results = matched[:count]
    else:
        # Newest first within a company; companies with more openings lead each round.
        matched.sort(key=lambda r: r["indiaOpenings"], reverse=True)
        results = interleave_companies(matched)[:count]
    return {
        "records": results,
        "matched": matched_total,
        "companiesSearched": len(boards),
        "errors": errors,
    }
