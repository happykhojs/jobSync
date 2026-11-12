# WorkOwon JobSync

Find the latest jobs in India from 373 company career sites and job platforms, from large employers to small startups, review and edit them, optionally polish them with AI, and post them to WorkOwon.

## Features

- **Search** company career sites (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Workday, Oracle Recruiting, Amazon Jobs) and the Himalayas remote-jobs platform by keywords (with suggestions for roles, skills and companies as you type), location, experience (internship, fresher, 1–3 yrs…), role type (tech or non-tech, from the job title), company size (large, mid-size, small by India openings), sector, company type, source and posting date. Dedicated **Startups** and **Smaller companies** filters list those employers (with “all” toggles), and newly added companies are marked *new*. Exclude title words, match keywords in the title only, show only jobs with a salary, or only companies added in the last 30 days. Newest jobs come first (or sort by biggest employers). Searches run in the background with a progress count, and a green **New** tag marks jobs the first time they show up in your searches (the very first time, jobs posted in the last 24 hours).
- **No duplicates**: jobs already on WorkOwon (checked against its external-jobs list after you log in) are hidden and can't be posted again, and the same job found on two sites or reposted under a new requisition (same company, title and city) is shown once.
- **Duplicate score**: every job is compared with all jobs live on WorkOwon (read from its public job search API, so jobs posted directly on the site count too). Near matches, like a reworded title, "Pvt Ltd" in the name or a new requisition ID, show a match score with a link to the existing job. A **likely duplicate** (90%+) can't be selected or posted until you click *Not a duplicate*; *Skip, it's a duplicate* hides it for good. A **possible duplicate** (60–89%) is a warning only. The command-line poster skips likely duplicates.
- **Himalayas jobs** keep their Himalayas `applicationLink` as the listing URL, unchanged, as their API terms require.
- **Review & edit** every field before posting: title, rich-text description and requirements, experience, salary, locations, skills, benefits, tags.
- **AI on demand**: the ✨ Improve buttons rewrite jobs in the WorkOwon style with Gemini. AI is never used unless you click one; results are cached so a job is never paid for twice.
- **Post** selected jobs to the WorkOwon admin API (login with email/password + Cloudflare Turnstile, tokens refresh automatically). The login form shows WorkOwon’s Turnstile widget and sends `X-Turnstile-Token` through to `api.workowon.com`. Add this JobSync hostname to that Turnstile widget’s allowed domains in Cloudflare.
- **✍️ Post page** (`/posts`, the *Post* button in the header): write community posts (text, article, question, poll, link, job share) with bold/italic/lists, photos (cropped to full, 1:1, 16:9 or 9:16), videos and documents, hashtags and visibility, with a live preview, and post them to your WorkOwon profile. Log in with several accounts (any WorkOwon user) and switch between them from the header. *Add many logins* or *Upload CSV file* (columns: email, password) saves many accounts in `.post_credentials.json` on your computer (git-ignored); pick one from the account menu and it logs in automatically, or *Log in all*; each account's posts are listed below the editor with Edit and Delete.
- **AI for posts**: *Anti-AI* rewrites a post so it reads like a person wrote it (no AI buzzwords, dashes or robotic structure). One click rewrites it in a style (*Professional post*, *Short but real*, *Storytelling*, *Friendly & casual*, *Funny & witty*, *Thought leadership*, *Tips list*, *Motivational*, *Hiring announcement*, *Ask the community*, *Fix grammar only*), or type instructions to write a new post or change the current one. Undo brings back the previous version. Uses the same Gemini key; nothing is sent to AI unless you click.
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
| `duplicates.py` | Duplicate score against jobs already live on WorkOwon |
| `posts.py` | Post page: logged-in accounts and the AI post writer |
| `static/posts.html` | Post page UI |
| `boards.json` | Company catalog: career site, sector, type, India openings |

Local state (`.env`, `.session.json`, `edits.json`, `posted_jobs.json`, `curated_jobs.json`, `skipped.json`, `jobs.json`) is git-ignored.

---

Powered by WorkOwon · Developed by Happy Yadav
