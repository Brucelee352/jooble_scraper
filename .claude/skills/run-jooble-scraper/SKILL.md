---
name: run-jooble-scraper
description: Build, run, and smoke-test the jooble_scraper CLI. Use when asked to run or start the scraper, test scraper_source.py, or verify a change produces a valid jooble_list.csv.
---

A single-file interactive Python CLI (`scraper_source.py`) that POSTs to the
Jooble jobs API and writes `Documents/jooble_list.csv`. Drive it via
`.claude/skills/run-jooble-scraper/driver.py`, which runs the whole script
end-to-end against a mocked API (no key needed) and validates the CSV.

All paths are relative to the repo root.

## Prerequisites

Windows with the `py` launcher. Python **3.12** is required — the pinned
`pandas==2.2.3` has no wheels for 3.14, which is the default `python` on this
machine.

## Setup

```bash
py -3.12 -m venv venv
./venv/Scripts/python -m pip install -r requirements.txt
```

No env file needed for the agent path. For live runs, a real Jooble API key
(free, from https://jooble.org/api/about) must be in the `KEY` env var — see
Gotchas about the `.env` path in the source.

## Run (agent path)

The driver patches `requests.post` with a canned Jooble response and
`input()` with the page count, executes `scraper_source.py` via `runpy`, then
checks the CSV exists with the 10 expected columns and the expected row count.
Exit 0 = pass.

```bash
./venv/Scripts/python .claude/skills/run-jooble-scraper/driver.py
./venv/Scripts/python .claude/skills/run-jooble-scraper/driver.py --pages 3
```

Expected output ends with `PASS: ...\Documents\jooble_list.csv — N rows, columns OK`.

The importable data layer (`jooble_data.py`, repo root — see `INTERFACE.md`)
has its own mock smoke test, also no key needed:

```bash
./venv/Scripts/python .claude/skills/run-jooble-scraper/driver.py --module
```

It exercises `jooble_data.fetch_jobs` against a mocked `requests.post` and
validates the 12-column DataFrame (incl. lat/lon), the `days` filter, the
`limit` cap, negative-id preservation, offline geocoding, and that HTTP 403
raises `JoobleApiError`. Expected output: `PASS: jooble_data.fetch_jobs — ... all OK`.

With a real key you can run the same validation against the live API
(unverified here — no key available in this repo):

```bash
KEY=<real-key> ./venv/Scripts/python .claude/skills/run-jooble-scraper/driver.py --live --pages 1
```

Output CSV → `Documents/jooble_list.csv` (under the repo root; the driver
creates the directory and deletes any stale CSV before each run).

## Run: Dash app

`app.py` (repo root) is the Dash UI over `jooble_data.fetch_jobs` — data
table, map, and a fetch dialog. It starts fine with no `KEY` set (empty
state + message); fetches only run from the dialog, never at import/page
load.

```bash
./venv/Scripts/python app.py            # serves http://127.0.0.1:8050
curl http://127.0.0.1:8050              # returns the Dash index page
```

UI smoke test (no key needed — mocks `requests.post` with the canned Jooble
payload and exercises `do_fetch`, the map builder, and the Dash callback
endpoint):

```bash
./venv/Scripts/python .claude/skills/run-jooble-scraper/ui_smoke.py
```

Expected output: `PASS: ui_smoke — ... all OK`.

## Run (human path)

```bash
echo 2 | KEY=<real-key> ./venv/Scripts/python scraper_source.py
```

Prompts for a page count (max 10), fetches, prints the DataFrame, writes the
CSV. With an invalid key it prints `Error! Status code: 403` and exits with
code 0 and **no CSV** — check for the file, not the exit code.

## Test

There is no test suite. The driver's mock run is the smoke test.

## Gotchas

- **The script runs on import** — `jooble_list()` is called at module top
  level with no `if __name__ == "__main__"` guard. You cannot import it to
  call functions individually; the driver uses `runpy` + patching instead.
- **The dotenv path is phantom** — `load_dotenv("jooble_scraper/jooble_scraper.env")`
  points at a file that doesn't exist in the repo (only `example.env`, which
  is never loaded). In practice `KEY` must be set as a real environment
  variable, or you must create `jooble_scraper/jooble_scraper.env` yourself.
- **Output dir must exist** — it writes to `<cwd>/Documents/jooble_list.csv`
  relative to the *current working directory*. The driver chdirs to the repo
  root and creates `Documents/`; running the script manually from elsewhere
  changes where (or whether) the CSV lands.
- **Negative job IDs are silently rewritten** — the script strips the leading
  `-` from the `id` column (`str.lstrip('-')`), so Jooble's negative IDs come
  out positive in the CSV.
- **429 handling sleeps 30s per retry, up to 5 attempts per page** — a
  rate-limited live run can stall for minutes.
- **Search parameters are hardcoded** — keywords ("data engineer, analytics
  engineer"), location (United States), radius 500. Changing the search means
  editing `scraper_source.py`.

## Troubleshooting

- **`ValueError: Missing API key. Please set it in your .env file.`** —
  `KEY` isn't in the environment (the `.env` path in the source doesn't
  exist; see Gotchas). Set `KEY` as an env var. Mock mode sets it for you.
- **`pip install` fails building pandas** — you're on Python 3.14 (the
  machine default). Recreate the venv with `py -3.12 -m venv venv`.
- **`Error! Status code: 403`** — invalid/placeholder API key on a live run.
  The script exits silently without writing a CSV.
