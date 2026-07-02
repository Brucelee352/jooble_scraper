# Data-layer contract: `jooble_data`

Contract between the data layer (`jooble_data.py`, repo root, owned by
super-programmer) and the Dash UI (owned by ui-dev). The UI imports this
module and codes against exactly what is documented here.

## Module

```python
import jooble_data
# or
from jooble_data import fetch_jobs, JoobleApiError, COLUMNS
```

Pure module: importing it performs no network calls, no I/O, no prompts.

## `fetch_jobs`

```python
def fetch_jobs(
    days: int = 7,                 # recency window: keep jobs updated within the last N days
    limit: int = 100,              # stop after this many matching jobs
    keywords: str = "data engineer, analytics engineer",
    location: str = "United States",
    radius: int = 500,             # miles, sent to the API as a string
    *,
    api_key: str | None = None,    # overrides the KEY env var
    max_pages: int = 10,           # hard cap on API pages fetched
    max_retries: int = 2,          # extra attempts after a 429/network failure
    retry_wait: float = 2.0,       # seconds between attempts
    timeout: float = 10.0,         # per-request timeout, seconds
) -> pandas.DataFrame
```

Behavior:

- Paginates `POST https://jooble.org/api/{KEY}` until `limit` matching jobs
  are collected, a page returns no jobs, or `max_pages` is reached.
- The `days` window is filtered client-side on the `updated` timestamp
  (Jooble has no server-side date filter). For the "2-day increments" use
  case, call `fetch_jobs(days=2)`.
- Jobs with an unparseable `updated` timestamp are dropped.
- May return fewer than `limit` rows (including 0 — the empty DataFrame
  still has all 12 columns with the dtypes below).
- Worst-case latency ≈ `max_pages * (max_retries + 1) * (timeout + retry_wait)`
  with defaults; pass `max_retries=0`/smaller `timeout` for snappier failure.

## Returned DataFrame

Columns, in this exact order (also exported as `jooble_data.COLUMNS`):

| column   | dtype           | notes |
|----------|-----------------|-------|
| id       | object (str)    | Jooble job id as a string; leading `-` preserved (ids can be negative). |
| title    | object (str)    | |
| company  | object (str)    | may be `""` |
| location | object (str)    | raw Jooble location string, e.g. `"Austin, TX"`, `"Remote, United States"` |
| salary   | object (str)    | may be `""` |
| job_type | object (str)    | Jooble's `type` field, e.g. `"Full-time"` |
| snippet  | object (str)    | may contain HTML tags like `<b>` |
| link     | object (str)    | job posting URL |
| updated  | datetime64[ns]  | tz-naive |
| source   | object (str)    | |
| lat      | float64         | NaN when the location can't be geocoded |
| lon      | float64         | NaN when the location can't be geocoded |

Geocoding is **offline only**: a bundled `"City, ST"` lookup (~60 major US
cities) with a fallback to US state centroids parsed from the location
string (state abbreviation or full name, incl. DC). `"Remote"`, non-US, and
unrecognized locations get NaN — the UI should drop NaN rows for the map
(`df.dropna(subset=["lat", "lon"])`) but keep them in tables/lists.
Helper `jooble_data.geocode_location(s) -> (lat, lon)` is also public.

## Exceptions

```python
class JoobleApiError(Exception):
    status_code: int | None   # HTTP status, or None (missing key, retries exhausted, network)
```

Raised for:

- missing API key (`status_code=None`),
- HTTP 403 — invalid/expired key (`status_code=403`),
- any other non-200/429 HTTP status (`status_code=<status>`),
- retries exhausted on 429 or network errors (`status_code=None`).

The UI should wrap `fetch_jobs` in `try/except JoobleApiError` and show
`str(exc)` — messages are user-presentable.

## Environment

- `KEY` — Jooble API key (required unless `api_key=` is passed). If the env
  var is unset and python-dotenv is installed, a `./.env` file is tried as a
  fallback; the env var always wins. Never hardcode a key.
- Dependencies: `pandas`, `requests` (already pinned in `requirements.txt`);
  `python-dotenv` optional.

## Smoke test

```bash
./venv/Scripts/python .claude/skills/run-jooble-scraper/driver.py --module
```

Runs `fetch_jobs` against a mocked `requests.post` (no key needed) and
validates columns, the days filter, `limit`, id sign preservation,
geocoding, and the 403 → `JoobleApiError` path.
