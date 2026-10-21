# WorkOwon JobSync

Find the latest jobs in India from 100+ company career sites, review and edit them, optionally polish them with AI, and post them to WorkOwon.

## Features

- **Search** company career sites (Greenhouse, Lever, Ashby, SmartRecruiters, Workday) by keywords, location, experience (internship, fresher, 1–3 yrs…), sector, company type and posting date. Companies with more India openings come first.
- **Review & edit** every field before posting: title, rich-text description and requirements, experience, salary, locations, skills, benefits, tags.
- **AI on demand**: the ✨ Improve buttons rewrite jobs in the WorkOwon style with Gemini. AI is never used unless you click one; results are cached so a job is never paid for twice.
- **Post** selected jobs to the WorkOwon admin API (login with email/password, tokens refresh automatically).
- **🎉 Fun Zone** (optional toggle): animals strolling, surprise weather and events, memes while searching, confetti when a job is posted. Everything is click-through and stays out of the way of posting.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in the values
```

## Run

```bash
.venv/bin/python app.py
```

Open http://127.0.0.1:5050, log in with your WorkOwon admin account, search, review, and post.

## Other scripts

| Command | What it does |
|---|---|
| `.venv/bin/python update_catalog.py` | Refresh each company's India opening count in `boards.json` (run weekly) |
| `.venv/bin/python job_scraper.py` | Command-line scrape using `locationFilter` from `boards.json` into `jobs.json` |
| `.venv/bin/python post_jobs.py [--send] [--ai]` | Command-line poster (dry run unless `--send`; Gemini only with `--ai`) |

## Files

| File | Purpose |
|---|---|
| `app.py` | Dashboard server (Flask) |
| `static/index.html` | Dashboard UI |
| `static/fun.js`, `static/fun.css` | Fun Zone |
| `search.py` | Search across the company catalog |
| `job_scraper.py` | Career-site scrapers |
| `enrich.py` | Rule-based extraction (experience, skills, benefits, locations) |
| `curate.py` | Gemini rewriting (only on request) |
| `htmlfmt.py` | HTML formatting to the site's format |
| `workowon.py` | WorkOwon API client (login, refresh, post) |
| `boards.json` | Company catalog: career site, sector, type, India openings |

Local state (`.env`, `.session.json`, `edits.json`, `posted_jobs.json`, `curated_jobs.json`, `skipped.json`, `jobs.json`) is git-ignored.

---

Powered by WorkOwon · Developed by Happy Yadav
