# WorkOwon JobSync

Find the latest jobs in India from 100+ company career sites, review and edit them, optionally polish them with AI, and post them to WorkOwon.

## Features

- **Search** company career sites (Greenhouse, Lever, Ashby, SmartRecruiters, Workday) and the Himalayas remote-jobs platform by keywords (with suggestions for roles, skills and companies as you type), location, experience (internship, fresher, 1–3 yrs…), sector, company type, source and posting date. Exclude title words, match keywords in the title only, or show only jobs with a salary. Newest jobs come first (or sort by biggest employers).
- **Himalayas jobs** keep their Himalayas `applicationLink` as the listing URL, unchanged, as their API terms require.
- **Review & edit** every field before posting: title, rich-text description and requirements, experience, salary, locations, skills, benefits, tags.
- **AI on demand**: the ✨ Improve buttons rewrite jobs in the WorkOwon style with Gemini. AI is never used unless you click one; results are cached so a job is never paid for twice.
- **Post** selected jobs to the WorkOwon admin API (login with email/password, tokens refresh automatically).
- **🎉 Fun Zone** (optional toggle): animals strolling, surprise weather and events, memes while searching, confetti when a job is posted. Everything is click-through and stays out of the way of posting.
- **🚀 Super Fun** (on top of Fun Zone): anything can happen. Buttons sometimes blast, turn into birds or vanish (they come back and still do their job), giant animals take over the screen, a train crosses the middle, hunts and cavemen run along the bottom, floods rise over the jobs, synth sounds (🔊 toggle), recruiter XP, combos, achievements and secret words (`meow`, `party`, `hire`, `boom`, the Konami code).
- **📖 Story mode** (in Super Fun): an endless show of little episodes (war, love, an election, a tsunami, sunny and rainy days, a job interview, aliens, a heist, a dragon) acted out on the grass with narration, weather and sound.
- **🦖 Dino mini-game** (in Super Fun): you're the dino at the bottom. ← → move, ↑ jump, F fire, A bite/eat, D dash, S shield, G giant, Q earthquake, C change avatar, ? controls. Eat small animals to stay strong; when you're weak, predators hunt you. Your dino naps after a minute without input, so it never interrupts real work.

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
| `static/superfun.js`, `static/superfun.css` | Super Fun: XP, levels, achievements, secret words |
| `static/chaos.js`, `static/chaos.css` | Super Fun chaos: pranks, takeovers, train, hunts, flood, sounds |
| `static/story.js`, `static/story.css` | Super Fun story mode |
| `static/game.js`, `static/game.css` | Super Fun dino mini-game |
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
