"""Smoke driver for jooble_scraper.

Runs scraper_source.py end-to-end and validates the CSV it writes.

Modes:
  python driver.py              mock mode (default): no API key needed.
                                Patches requests.post with a canned Jooble
                                response and feeds the interactive prompt.
  python driver.py --live       live mode: real HTTP to jooble.org.
                                Requires a real KEY in the environment.
  python driver.py --module     smoke-test the importable data layer
                                (jooble_data.fetch_jobs) against mocked
                                requests.post. No API key needed.

Options:
  --pages N    page count fed to the script's input() prompt (default 2;
               legacy scraper_source.py mode only)

Exit code 0 = scraper ran and CSV validated; 1 = failure.
"""

import argparse
import builtins
import os
import runpy
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

UNIT_ROOT = Path(__file__).resolve().parents[3]  # <repo>/.claude/skills/run-jooble-scraper/
SCRIPT = UNIT_ROOT / "scraper_source.py"
EXPECTED_COLUMNS = [
    "id", "title", "company", "location", "salary",
    "job_type", "snippet", "link", "updated", "source",
]

FAKE_JOBS = [
    {
        "id": -7000123456789012345,
        "title": "Data Engineer",
        "company": "Acme Analytics",
        "location": "Austin, TX",
        "salary": "$120k - $150k",
        "type": "Full-time",
        "snippet": "Build and maintain data pipelines with Python and SQL.",
        "link": "https://jooble.org/jdp/1234567890",
        "updated": "2026-07-01T08:30:00.0000000",
        "source": "example.com",
    },
    {
        "id": 8000987654321098765,
        "title": "Analytics Engineer",
        "company": "Globex Corp",
        "location": "Remote, United States",
        "salary": "",
        "type": "Contract",
        "snippet": "dbt, Snowflake, and dashboarding experience required.",
        "link": "https://jooble.org/jdp/0987654321",
        "updated": "2026-06-28T17:05:00.0000000",
        "source": "jobs.example.org",
    },
]


class FakeResponse:
    status_code = 200

    def json(self):
        return {"totalCount": 2, "jobs": FAKE_JOBS}


def run_scraper(pages, live):
    os.chdir(UNIT_ROOT)  # script writes to <cwd>/Documents/jooble_list.csv
    (UNIT_ROOT / "Documents").mkdir(exist_ok=True)

    csv_path = UNIT_ROOT / "Documents" / "jooble_list.csv"
    if csv_path.exists():
        csv_path.unlink()

    patches = [mock.patch.object(builtins, "input", lambda *a: str(pages))]
    if live:
        if not os.environ.get("KEY"):
            sys.exit("--live requires a real Jooble API key in the KEY env var")
    else:
        os.environ["KEY"] = "fake-key-for-mock-run"
        import requests
        patches.append(mock.patch.object(
            requests, "post", lambda *a, **kw: FakeResponse()))

    with ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ))
        for p in patches:
            stack.enter_context(p)
        runpy.run_path(str(SCRIPT), run_name="__main__")

    return csv_path


def validate(csv_path, pages, live):
    import pandas as pd

    if not csv_path.exists():
        return f"CSV not written: {csv_path}"
    df = pd.read_csv(csv_path)
    if list(df.columns) != EXPECTED_COLUMNS:
        return f"unexpected columns: {list(df.columns)}"
    if live:
        if df.empty:
            return "live run returned no jobs"
    elif len(df) != pages * len(FAKE_JOBS):
        return f"expected {pages * len(FAKE_JOBS)} rows, got {len(df)}"
    if df["updated"].isna().all():
        return "'updated' column failed to parse as datetimes"
    print(f"\nPASS: {csv_path} — {len(df)} rows, columns OK")
    return None


def run_module_smoke():
    """Exercise jooble_data.fetch_jobs against a mocked requests.post.

    Returns an error string on failure, None on success.
    """
    import math
    from datetime import datetime, timedelta

    sys.path.insert(0, str(UNIT_ROOT))
    import requests

    import jooble_data

    now = datetime.now()

    def iso(days_ago):
        return (now - timedelta(days=days_ago)).strftime(
            "%Y-%m-%dT%H:%M:%S.0000000")

    job_a = {  # fresh, matches keywords, duplicated on page 2
        "id": -7000123456789012345, "title": "Data Engineer",
        "company": "Acme Analytics", "location": "Austin, TX",
        "salary": "$120k - $150k", "type": "Full-time",
        "snippet": "Pipelines.", "link": "https://jooble.org/jdp/1",
        "updated": iso(1), "source": "example.com"}
    job_b = {  # fresh (3 days), matches keywords
        "id": 8000987654321098765, "title": "Analytics Engineer",
        "company": "Globex Corp", "location": "Remote, United States",
        "salary": "", "type": "Contract",
        "snippet": "dbt + Snowflake.", "link": "https://jooble.org/jdp/2",
        "updated": iso(3), "source": "jobs.example.org"}
    job_stale = {  # older than 7 days -> always dropped
        "id": 12345, "title": "Stale Engineer",
        "company": "Oldco", "location": "Cheyenne, Wyoming",
        "salary": "", "type": "Full-time",
        "snippet": "Too old.", "link": "https://jooble.org/jdp/3",
        "updated": iso(10), "source": "old.example.com"}
    job_fuzzy = {  # fresh, but no keyword phrase in title/snippet
        "id": 999, "title": "Software Developer",
        "company": "Fuzzco", "location": "Denver, CO",
        "salary": "", "type": "Full-time",
        "snippet": "Java microservices.", "link": "https://jooble.org/jdp/4",
        "updated": iso(1), "source": "fuzz.example.com"}
    job_e = {  # fresh, matches via "data engineer" substring in title
        "id": 111, "title": "Senior Data Engineer",
        "company": "Plains Data", "location": "Cheyenne, Wyoming",
        "salary": "", "type": "Full-time",
        "snippet": "Airflow.", "link": "https://jooble.org/jdp/5",
        "updated": iso(1), "source": "plains.example.com"}

    pages = {
        1: [job_a, job_b, job_stale, job_fuzzy],
        2: [job_a, job_e],  # job_a repeated -> must be deduped by id
    }

    class FakeResp:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, **kw):
        page = int(kw["json"]["page"])
        return FakeResp({"totalCount": 6, "jobs": pages.get(page, [])})

    kwargs = dict(max_retries=0, retry_wait=0.0)

    with mock.patch.dict(os.environ, {"KEY": "fake-key-for-mock-run"}), \
            mock.patch.object(requests, "post", fake_post):
        # limit is a cap, not padding: 4 matches << limit=50 -> 4 rows
        # (a, b, fuzzy, e; stale dropped by days, duplicate a deduped)
        df = jooble_data.fetch_jobs(days=7, limit=50, **kwargs)
        if list(df.columns) != jooble_data.COLUMNS:
            return f"unexpected columns: {list(df.columns)}"
        if len(df) != 4:
            return f"days=7 limit=50 expected 4 rows (cap, not padding), got {len(df)}"
        if df["id"].duplicated().any():
            return "duplicate ids across pages were not deduped"
        if not str(df["updated"].dtype).startswith("datetime64"):
            return f"'updated' dtype is {df['updated'].dtype}, not datetime64"
        neg = df.loc[df["title"] == "Data Engineer", "id"].iloc[0]
        if neg != "-7000123456789012345":
            return f"negative id corrupted: {neg!r}"
        austin = df.loc[df["location"] == "Austin, TX"].iloc[0]
        if abs(austin["lat"] - 30.2672) > 0.01 or abs(austin["lon"] + 97.7431) > 0.01:
            return f"Austin, TX geocoded to ({austin['lat']}, {austin['lon']})"
        remote = df.loc[df["location"] == "Remote, United States"].iloc[0]
        if not (math.isnan(remote["lat"]) and math.isnan(remote["lon"])):
            return f"ungeocodable row got coords ({remote['lat']}, {remote['lon']})"

        # limit=None -> uncapped, returns every match
        df_all = jooble_data.fetch_jobs(days=7, limit=None, **kwargs)
        if len(df_all) != 4:
            return f"limit=None expected all 4 matches, got {len(df_all)}"

        # limit smaller than match count -> hard cap
        df3 = jooble_data.fetch_jobs(days=7, limit=3, **kwargs)
        if len(df3) != 3:
            return f"limit=3 expected 3 rows, got {len(df3)}"

        # days=2 -> only the 1-day-old jobs (a, fuzzy, e)
        df2 = jooble_data.fetch_jobs(days=2, **kwargs)
        if len(df2) != 3:
            return f"days=2 expected 3 rows, got {len(df2)}"

        # strict=True -> drop the job whose title/snippet lacks the keywords
        df_strict = jooble_data.fetch_jobs(days=7, strict=True, **kwargs)
        if len(df_strict) != 3 or "999" in set(df_strict["id"]):
            return (f"strict=True expected 3 rows without id 999, got "
                    f"{len(df_strict)} rows, ids {sorted(df_strict['id'])}")

    # 403 must raise JoobleApiError with status_code
    with mock.patch.dict(os.environ, {"KEY": "bad-key"}), \
            mock.patch.object(requests, "post",
                              lambda *a, **kw: FakeResp({}, status=403)):
        try:
            jooble_data.fetch_jobs(**kwargs)
        except jooble_data.JoobleApiError as exc:
            if exc.status_code != 403:
                return f"403 raised JoobleApiError but status_code={exc.status_code}"
        else:
            return "403 response did not raise JoobleApiError"

    # state-centroid fallback check (offline geocoder)
    lat, lon = jooble_data.geocode_location("Cheyenne, Wyoming")
    if abs(lat - 42.9957) > 0.01:
        return f"state-name fallback failed: {(lat, lon)}"

    print("PASS: jooble_data.fetch_jobs — columns, days filter, limit cap / "
          "limit=None, strict keyword filter, id dedupe, id sign, geocoding, "
          "and 403 -> JoobleApiError all OK")
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="hit the real Jooble API (needs KEY)")
    ap.add_argument("--pages", type=int, default=2, help="pages to request (default 2, max 10)")
    ap.add_argument("--module", action="store_true",
                    help="smoke-test jooble_data.fetch_jobs against a mocked API")
    args = ap.parse_args()

    if args.module:
        error = run_module_smoke()
    else:
        csv_path = run_scraper(args.pages, args.live)
        error = validate(csv_path, args.pages, args.live)
    if error:
        sys.exit(f"FAIL: {error}")


if __name__ == "__main__":
    main()
