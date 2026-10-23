#!/usr/bin/env python3
"""
Refresh "indiaOpenings" for every company in boards.json and sort the catalog by it.
Search uses this count to show companies with more openings first.

Run (takes ~1 minute):
    .venv/bin/python update_catalog.py
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import job_scraper as js

BOARDS_FILE = Path(__file__).resolve().parent / "boards.json"


def india_openings(board: dict) -> int:
    provider, slug = board["provider"], board["board"]
    is_india = lambda text: bool(js.INDIA_PLACES.search(text or ""))
    if provider == "workday":
        facet = js.workday_country_facet(slug)
        return facet[2] if facet else 0
    if provider == "smartrecruiters":
        data = js.get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", {"limit": 1, "country": "in"})
        return int(data.get("totalFound") or 0)
    if provider == "greenhouse":
        jobs = js.get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs").get("jobs", [])
        return sum(1 for j in jobs if is_india((j.get("location") or {}).get("name")))
    if provider == "lever":
        jobs = js.get_json(f"https://api.lever.co/v0/postings/{slug}", {"mode": "json"})
        return sum(1 for j in jobs if j.get("country") == "IN" or is_india(" ".join((j.get("categories") or {}).get("allLocations") or [])))
    if provider == "ashby":
        jobs = js.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}").get("jobs", [])
        return sum(1 for j in jobs if is_india(" ".join([j.get("location") or ""] + [x.get("location", "") for x in j.get("secondaryLocations") or []])))
    if provider == "oracle":
        location = js.oracle_country_location(slug, "in")
        return location[1] if location else 0
    if provider == "amazon":
        return int(js.get_json("https://www.amazon.jobs/en/search.json", {"normalized_country_code[]": "IND", "result_limit": 1}).get("hits") or 0)
    if provider == "himalayas":
        data = js.get_json("https://himalayas.app/jobs/api/search", {"sort": "recent", "country": "India", "page": 1})
        return int(data.get("totalCount") or 0)
    return 0


def main() -> None:
    config = json.loads(BOARDS_FILE.read_text(encoding="utf-8"))
    boards = config["boards"]

    def count(board: dict) -> tuple[dict, int | None]:
        try:
            return board, india_openings(board)
        except Exception as exc:
            logging.warning("%s: %s", board["companyName"], exc)
            return board, None

    with ThreadPoolExecutor(16) as pool:
        for board, n in pool.map(count, boards):
            if n is not None:
                board["indiaOpenings"] = n
    boards.sort(key=lambda b: b.get("indiaOpenings") or 0, reverse=True)
    BOARDS_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    for b in boards:
        print(f"{b.get('indiaOpenings', '?'):>6}  {b['companyName']}  ({b.get('sector') or b.get('companyType', '')})")


if __name__ == "__main__":
    main()
