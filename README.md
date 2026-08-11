# jooble_scraper

![Python](https://img.shields.io/badge/python-3.12-blue)
![Dash](https://img.shields.io/badge/Dash-2.18-5661c9)
![Deploy](https://img.shields.io/badge/deploy-Cloud%20Run-4285F4)
![License](https://img.shields.io/badge/license-MIT-green)

A program to scour Jooble.org for job listings — and now a full Plotly Dash web app that pulls those listings into a sortable table, maps them across the US, and charts a few insights about them. The original CSV script is still here too. Works with any IDE; I built it in Visual Studio Code with extensions.

## Introduction

This was born out of a desire to share my projects with the public. I've been upskilling and looking for work for the last couple of years, and I figured that — in addition to scratching my own itch — this might help my friends cut through some of the noise in the current labor market.

What started as a single script has grown quite a bit. There are now three pieces:

- **`app.py`** — the Dash web app: a fetch dialog, an interactive US map, five insight charts, and a sortable/filterable listings table.
- **`jooble_data.py`** — a reusable, importable data layer (`fetch_jobs` plus parsers). No network calls happen at import time.
- **`scraper_source.py`** — the original CLI script, still here if all you want is the `.csv`.

## What the web app does

The app is built with **Plotly Dash**, **Dash Bootstrap Components**, and **Dash Mantine Components (DMC 2.8)**, themed with a light indigo / silver gradient and the Sora typeface. No network calls happen on page load — a fetch only runs when you click the button in the modal.

**A note for anyone hacking on `app.py`:** DMC 2.x is built on Mantine 7, which needs React 18, but Dash 2.x still ships React 16 by default. So `app.py` pins the renderer with `dash._dash_renderer._set_react_version("18.2.0")` *before* the `Dash(...)` app is created. That line, together with the `dash-mantine-components` pin in `requirements.txt`, is load-bearing — remove either and the Mantine components break.

What you get after a fetch:

- **Fetch dialog** — type in keywords and a location (they start filled in with my data-engineering defaults), flip a **Remote** toggle, and choose a **recency window of 1–21 days** (up to 100 jobs). Blank inputs fall back to the defaults.
- **Interactive map** — every job that can be geocoded is plotted on an OpenStreetMap of the US. Click a marker and it selects that job's row in the table below.
- **Filter by state** — a dropdown in the sidebar filters the **map and the listings table** down to a single state. (The insight charts always reflect the full fetch, not the state filter.)
- **Five insight charts** — Top companies, Postings per day, Jobs by state, Top skills mentioned, and a **Median salary by state** bubble chart (bubble size scales with how many salaried jobs back that state's figure).
- **Listings table** — sortable and filterable, paginated 15 rows at a time, with columns for Job Title, Company, Location, Salary, Job Type, Seniority, Min Yrs Exp, Skills, Last Updated, and a clickable link. Select a row (or click a map marker) to see the job's snippet in a detail card.

Listings that can't be pinned to a location (remote roles, mostly) stay in the table but sit the map out. The app starts up fine without an API key — it'll just remind you to set one before it can fetch anything.

### About the extra columns

The data layer pulls a bit of extra signal out of each listing with the parsers in `jooble_data.py`:

- `parse_seniority` — a best-effort level (Intern / Junior / Mid / Senior / Lead / Staff / Principal) from the title, falling back to the snippet.
- `parse_min_years` — the minimum years of experience mentioned (e.g. "5+ years").
- `extract_skills` — matches a built-in vocabulary of ~35 tools/languages (Python, SQL, dbt, Airflow, Snowflake, AWS, …).
- `parse_salary` — normalizes Jooble's messy free-text salary ("$90k–$120k", "$45/hr", "$8,000 per month") into an estimated annual USD figure, exposed as the `salary_value` column that powers the salary bubble chart.

Be honest with yourself about these: Jooble only gives a truncated snippet per listing, so all of the above are best-effort and can be sparse or empty. Unknowns come back as `None` / `[]`.

## Getting started

1. Clone the repository.
2. Open PowerShell, Git Bash, or the Windows command line (run as administrator if needed).
3. `cd` into the project folder: `cd path/to/the/project/folder`.
4. Get your free API key here: https://jooble.org/api/about
5. Set it as the `KEY` environment variable, or copy `example.env` to `.env` and put your key inside:
   ```
   KEY=your_api_key_here
   ```

> **Use Python 3.12.** The pinned version of pandas doesn't ship wheels for 3.14 yet, so a newer interpreter will fail to install the requirements.

## Setting up a virtual environment

You *can* just copy the scripts into your IDE and configure things ad hoc, but I recommend a virtual environment to keep this sequestered from your global one.

1. Create it:
   ```
   py -3.12 -m venv venv
   ```
2. Activate it:
   - **Windows:**
     ```
     venv\Scripts\activate
     ```
   - **Mac/Linux:**
     ```
     source venv/bin/activate
     ```
3. Install the dependencies:
   ```
   pip install -r requirements.txt
   ```
4. **Optional:** run `deactivate` to turn the virtual environment off later.

## Running the web app

This is the fun part. With your key set, run:

```
python app.py
```

Then open http://127.0.0.1:8050 in your browser. Click **Fetch Jobs**, adjust the keywords / location / Remote toggle / day window, and hit **Fetch** — you'll get the map, the charts, and the table.

## Running the original script

The classic experience. With your key set, run:

```
python scraper_source.py
```

It'll ask how many pages you want (up to 10), then save the results to `Documents/jooble_list.csv` under the project folder. **Make sure that `Documents` folder exists first**, or the save will fail. This script writes a plain CSV — it doesn't do any of the geocoding, salary parsing, or skill extraction the Dash app does.

## Deploy to Google Cloud Run

The repo ships everything needed to run the app as a container on Google Cloud Run:

- a **`Dockerfile`** that serves the Dash WSGI app with **gunicorn** — `app.py` exposes it as `server = app.server`, and the container binds gunicorn to Cloud Run's injected `$PORT` (8080 by default);
- a **`.dockerignore`** that keeps the image small and keeps local/secret files (like `.env`) out of it;
- a **`.gcloudignore`** that controls what `gcloud ... --source .` uploads to Cloud Build;
- `gunicorn` pinned in **`requirements.txt`**.

The app reads the Jooble API key from the `KEY` environment variable, so the deploy below injects it at runtime via Secret Manager.

> Placeholders below — `YOUR_PROJECT_ID`, `YOUR_JOOBLE_KEY` — are yours to fill in. `us-central1` is just an example region; use whichever is closest to you.

```bash
# 0) Authenticate and select project + default region
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region us-central1

# 1) Enable required APIs
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com

# 2) Store the Jooble API key as a secret (recommended over a plaintext env var)
printf "YOUR_JOOBLE_KEY" | gcloud secrets create jooble-key --data-file=- --replication-policy=automatic

# 3) Grant the Cloud Run runtime service account access to the secret
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)')
gcloud secrets add-iam-policy-binding jooble-key \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# 4) Build the Dockerfile with Cloud Build and deploy to Cloud Run
gcloud run deploy jooble-scraper \
  --source . \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --port 8080 \
  --set-secrets KEY=jooble-key:latest
```

A few things worth knowing:

- **`--source .` uploads the current directory (respecting `.gcloudignore`) to Cloud Build.** It builds from the local files on disk, *not* from GitHub — so run it from the repo root where the `Dockerfile` lives, or pass `--source <path>`.
- **A simpler but less secure alternative to steps 2–3** is to skip Secret Manager and pass the key directly: `--set-env-vars KEY=YOUR_JOOBLE_KEY`. It works, but the key ends up in the service config in plaintext.
- **`.env` is excluded from both the image and the upload** (via `.dockerignore` and `.gcloudignore`), which is why the key has to be injected at runtime rather than baked in.
- **Seeing OOM?** Bump `--memory 1Gi`.
- The service **scales to zero when idle**, so you're not paying for it between fetches.

### Test the container locally first (optional)

```bash
docker build -t jooble .
docker run -e KEY=YOUR_JOOBLE_KEY -e PORT=8080 -p 8080:8080 jooble
```

Then open http://127.0.0.1:8080.

## For the curious

There's a smoke-test harness under `.claude/skills/run-jooble-scraper/` that exercises everything against a **mocked** API — no key needed. Handy if you want to poke at the code without burning requests:

```
python .claude/skills/run-jooble-scraper/driver.py --module
python .claude/skills/run-jooble-scraper/ui_smoke.py
```

The data layer's contract lives in `INTERFACE.md` if you want to build something of your own on top of `fetch_jobs`.

## To-Dos

1. Send the output `.csv` as an email to yourself or others.
2. Offer an `.xlsx` export for further manipulation in Excel.
3. Smarter geocoding — right now the map works off a built-in list of ~60 major cities plus state centroids, so smaller towns land on their state's center.

*(Docker / Cloud Run support was on this list and is now done — see [Deploy to Google Cloud Run](#deploy-to-google-cloud-run) above.)*

## License

MIT — see [`LICENSE`](LICENSE).

---

Bruce A. Lee © 2026, All Rights Reserved.
