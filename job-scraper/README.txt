Khojs Job Scraper — collection-only starter

This version fetches public listings from configured Greenhouse, Lever and Ashby boards.
It DOES NOT post jobs to your Khojs API.

1) Install Python 3.10+.
2) In this folder, create a virtual environment:
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
3) Edit boards.json. Replace the example IDs with real public board identifiers:
   - Greenhouse: the board token used in https://boards.greenhouse.io/{BOARD_TOKEN}
   - Lever: the site name used in https://jobs.lever.co/{SITE_NAME}
   - Ashby: the public job board name shown in the employer's Ashby job-board URL.
   Set companyName to the display name you want in the output. Only add boards you have permission to collect from; respect site terms and rate limits.
4) Run:
   python job_scraper.py
5) Review jobs.json. The first run writes all collected jobs; later runs update matching
   provider+board+job ID records and retain other records. This is a discovery dataset,
   not yet a production-ready active-job database.

Notes:
- The APIs are per employer; this does not search every company or all India jobs automatically.
- Some source APIs do not expose a publication date. sourceUpdatedAt is the source timestamp
  when available; collectedAt is when the scraper fetched it.
- Unknown salary, experience, openings and expiry are left null/blank rather than guessed.
- City/state parsing and skill extraction are intentionally not guessed in this first version.
- Review the source listing before publishing; closed jobs can become stale.
- Do not store raw source data publicly; rawSourceData is retained for debugging and mapping.
