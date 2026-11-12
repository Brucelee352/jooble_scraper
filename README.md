# jooble_scraper

![Python](https://img.shields.io/badge/python-3.12-blue)
![Dash](https://img.shields.io/badge/Dash-4.5-5661c9)
![Deploy](https://img.shields.io/badge/deploy-Cloud%20Run-4285F4)
![License](https://img.shields.io/badge/license-MIT-green)

A program that pulls job listings from Jooble.org. It started as a script that saved them to a CSV, and it's now a Plotly Dash web app that puts the listings in a sortable table, maps them across the US, and charts a few insights about them. The original CSV script is still here too. Works with any IDE; I built it in Visual Studio Code with extensions.

## Introduction

I started this because I wanted to share my projects with the public. I've been upskilling and looking for work for the last couple of years, and I figured that besides scratching my own itch, it might help my friends cut through some of the noise in the current labor market.

What started as a single script has grown quite a bit. There are now four pieces:

- `app.py`: the Dash web app, with a fetch dialog, an interactive US map, five insight charts, a sortable and filterable listings table you can email as a `.csv`, and an About panel.
- `jooble_data.py`: a reusable data layer (`fetch_jobs` plus parsers) that you can import without triggering any network calls.
- `mailer.py`: emails the listings table as a `.csv` attachment through Gmail SMTP.
- `scraper_source.py`: the original CLI script, still here if all you want is the `.csv`.

## What the web app does

The app is built with Plotly Dash 4.5, Dash Bootstrap Components, and Dash Mantine Components (DMC 3), themed with a light indigo and silver gradient and the Sora typeface. Each page load runs one fetch of the default search so the dashboard opens populated. After that, fetches run from the **Fetch Jobs** dialog.

A note for anyone hacking on `app.py`: DMC 3 requires React 19. Dash 4.5 bundles React 19 but still serves React 18 by default, so `app.py` opts in with `dash._dash_renderer._set_react_version("19.2.4")` *before* the `Dash(...)` app is created. Keep that line and the `dash>=4.5` and `dash-mantine-components>=3.0.0` requirements in `pyproject.toml`; remove either and the Mantine components break.

What you get after a fetch:

- Fetch dialog: type in keywords and a location (they start filled in with the defaults, "data analyst" in "United States"), flip the **Remote** toggle, and choose a recency window of 1 to 21 days (up to 100 jobs). Blank inputs fall back to the defaults.
- Interactive map: every job that can be geocoded is plotted on an OpenStreetMap of the US. Click a marker and it selects that job's row in the table below.
- Filter by state: a dropdown in the sidebar narrows the map and the listings table to a single state. The insight charts always show the full fetch.
- Five insight charts: Top companies, Postings per day, Jobs by state, Top skills mentioned, and a Median salary by state bubble chart, where bubble size scales with how many salaried jobs back that state's figure. Each bar chart shades its bars with its own color scale, darker for higher counts; the scales are set in `CHART_SCALES` in `app.py`.
- Listings table: sortable and filterable, 15 rows per page, with columns for Job Title, Company, Location, Salary, Job Type, Seniority, Min Yrs Exp, Skills, Last Updated, and a clickable link. Select a row (or click a map marker) to see the job's snippet in a detail card, or click a job title to open it in a pop-up.
- Email CSV: above the table, type an address to get the rows currently shown as a `.csv` attachment (see [Email a CSV of the listings](#email-a-csv-of-the-listings)).
- About: a button in the header that opens a scrollable panel describing the API, the data pipeline, the configuration, and deployment.

Listings that can't be pinned to a location (remote roles, mostly) stay in the table but sit the map out. The app starts up fine without an API key; it'll just remind you to set one before it can fetch anything.

### About the extra columns

The data layer pulls a bit of extra signal out of each listing with the parsers in `jooble_data.py`:

- `parse_seniority` guesses a level (Intern / Junior / Mid / Senior / Lead / Staff / Principal) from the title, falling back to the snippet.
- `parse_min_years` finds the minimum years of experience mentioned (e.g. "5+ years").
- `extract_skills` matches a built-in list of about 45 tools and languages (Python, SQL, dbt, Airflow, Snowflake, AWS, …).
- `parse_salary` turns Jooble's messy free-text salary ("$90k–$120k", "$45/hr", "$8,000 per month") into an estimated annual USD figure. That's the `salary_value` column behind the salary bubble chart.

Jooble only gives a truncated snippet per listing, so all of these are best guesses and can come back sparse or empty. Unknowns come back as `None` / `[]`.

## Getting started

1. Clone the repository.
2. Open PowerShell, Git Bash, or the Windows command line (run as administrator if needed).
3. `cd` into the project folder: `cd path/to/the/project/folder`.
4. Get your free API key here: https://jooble.org/api/about
5. Set it as the `KEY` environment variable, or copy `example.env` to `.env` and put your key inside:
   ```
   KEY=your_api_key_here
   ```

> Use Python 3.12 or newer. pandas 3 needs at least 3.11, and the Docker image uses 3.12.

## Setting up a virtual environment

You *can* just copy the scripts into your IDE and configure things ad hoc, but I recommend a virtual environment to keep this sequestered from your global one.

1. Create it:
   ```
   py -3.12 -m venv venv
   ```
2. Activate it:
   - Windows:
     ```
     venv\Scripts\activate
     ```
   - Mac/Linux:
     ```
     source venv/bin/activate
     ```
3. Install the dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Run `deactivate` when you want to turn the virtual environment off.

If you use [uv](https://docs.astral.sh/uv/), skip the steps above: `uv run app.py` creates the environment from `pyproject.toml` / `uv.lock` and starts the app. After changing dependencies in `pyproject.toml`, run `uv lock` and regenerate `requirements.txt` with `uv export --no-hashes --no-dev --no-emit-project --format requirements-txt -o requirements.txt`.

## Running the web app

This is the fun part. With your key set, run:

```
python app.py
```

Then open http://127.0.0.1:8050 in your browser. The default search loads automatically. To run your own, click **Fetch Jobs**, adjust the keywords, location, Remote toggle, or day window, and hit **Fetch**.

## Running the original script

The classic experience. With your key set, run:

```
python scraper_source.py
```

It'll ask how many pages you want (up to 10), then save the results to `Documents/jooble_list.csv` under the project folder. Make sure that `Documents` folder exists first, or the save will fail. This script writes a plain CSV and skips the geocoding, salary parsing, and skill extraction the Dash app does.

## Deploy to Google Cloud Run

The repo has everything needed to run the app as a container on Google Cloud Run:

- `Dockerfile` serves the Dash WSGI app with gunicorn. `app.py` exposes it as `server = app.server`, and the container binds gunicorn to Cloud Run's injected `$PORT` (8080 by default).
- `.dockerignore` keeps the image small and keeps local and secret files (like `.env`) out of it.
- `.gcloudignore` controls what `gcloud ... --source .` uploads to Cloud Build.
- `gunicorn` is listed in `pyproject.toml` and `requirements.txt`. It's Linux/macOS only and doesn't run on Windows.

The app reads the Jooble API key from the `KEY` environment variable, so the deploy below injects it at runtime via Secret Manager.

> Fill in `YOUR_PROJECT_ID` and `YOUR_JOOBLE_KEY` below. `us-central1` is just an example region; use whichever is closest to you.

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

- `--source .` uploads the current directory (minus anything in `.gcloudignore`) to Cloud Build. It builds from the files on your disk, *not* from GitHub, so run it from the repo root where the `Dockerfile` lives, or pass `--source <path>`.
- You can skip Secret Manager (steps 2 and 3) and pass the key directly with `--set-env-vars KEY=YOUR_JOOBLE_KEY`. It's simpler, but the key ends up in the service config in plaintext.
- `.env` is kept out of both the image and the upload (by `.dockerignore` and `.gcloudignore`), which is why the key has to be injected at runtime.
- If you see out-of-memory errors, bump it to `--memory 1Gi`.
- The service scales to zero when idle, so you're not paying for it between fetches.

### Test the container locally first (optional)

```bash
docker build -t jooble .
docker run -e KEY=YOUR_JOOBLE_KEY -e PORT=8080 -p 8080:8080 jooble
```

Then open http://127.0.0.1:8080.

## Email a CSV of the listings

Under **Listings**, type an email address and press **Email CSV**. The app sends the rows currently in the table as a `.csv` attachment, with the state filter and any column filters or sorting you've applied, under the table's own column headers. The logic lives in `mailer.py`.

Any visitor can enter any address, so sends are limited to one every 45 seconds per app instance (`SEND_COOLDOWN_SECONDS` in `mailer.py`). Cell values that start with `=`, `+`, `-` or `@` get a leading `'` so spreadsheet apps don't run them as formulas.

Mail goes out through Gmail SMTP, optionally *from* an address on your own domain:

1. Make the alias able to receive mail. Set up forwarding for e.g. `jobs@yourdomain.com` to your Gmail (Cloudflare Email Routing, ImprovMX, or your registrar's forwarding). Gmail sends a confirmation code to that address.
2. Verify it in Gmail: Settings → Accounts and Import → *Send mail as* → Add another email address, with "Treat as an alias" ticked.
3. Add an SPF record to the domain that includes Google, e.g. `v=spf1 include:_spf.google.com ~all`, merged with whatever your forwarding service needs. Avoid a strict DMARC policy (`p=quarantine` or `p=reject`): Gmail can't sign mail as your domain, so those emails would get filtered.
4. Create a Gmail App Password (requires 2-Step Verification): Google Account → Security → App passwords.

| Variable | What it is |
|---|---|
| `SMTP_USER` | Gmail address that logs in to SMTP |
| `SMTP_APP_PASSWORD` | The App Password from step 4 |
| `ALERT_FROM` | The verified alias, e.g. `jobs@yourdomain.com` (defaults to `SMTP_USER`) |

Locally, put these in `.env` (see `example.env`). On Cloud Run:

```bash
printf "YOUR_APP_PASSWORD" | gcloud secrets create smtp-app-password --data-file=-
# Grant secretAccessor on it, as for jooble-key above, then redeploy:
gcloud run deploy jooble-scraper --source . \
  --set-secrets KEY=jooble-key:latest,SMTP_APP_PASSWORD=smtp-app-password:latest \
  --set-env-vars SMTP_USER=you@gmail.com,ALERT_FROM=jobs@yourdomain.com
```

Tests (no network; SMTP is mocked): `python -m unittest discover -s tests`.

## For the curious

There's a smoke-test harness under `.claude/skills/run-jooble-scraper/` that runs everything against a mocked API, so you don't need a key. Handy if you want to poke at the code without burning requests:

```
python .claude/skills/run-jooble-scraper/driver.py --module
python .claude/skills/run-jooble-scraper/ui_smoke.py
```

The data layer's contract lives in `INTERFACE.md` if you want to build something of your own on top of `fetch_jobs`.

## To-Dos

1. Offer an `.xlsx` export for further manipulation in Excel.
2. Smarter geocoding. Right now the map works off a built-in list of about 60 major cities plus state centroids, so smaller towns land on their state's center.

*(Docker and Cloud Run support was on this list and is done; see [Deploy to Google Cloud Run](#deploy-to-google-cloud-run) above.)*

## License

MIT. See [`LICENSE`](LICENSE).

---

Bruce A. Lee © 2026, All Rights Reserved.
