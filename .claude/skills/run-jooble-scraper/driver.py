"""Smoke driver for jooble_scraper.

Runs scraper_source.py end-to-end and validates the CSV it writes.

Modes:
  python driver.py              mock mode (default): no API key needed.
                                Patches requests.post with a canned Jooble
                                response and feeds the interactive prompt.
  python driver.py --live       live mode: real HTTP to jooble.org.
                                Requires a real KEY in the environment.

Options:
  --pages N    page count fed to the script's input() prompt (default 2)

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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="hit the real Jooble API (needs KEY)")
    ap.add_argument("--pages", type=int, default=2, help="pages to request (default 2, max 10)")
    args = ap.parse_args()

    csv_path = run_scraper(args.pages, args.live)
    error = validate(csv_path, args.pages, args.live)
    if error:
        sys.exit(f"FAIL: {error}")


if __name__ == "__main__":
    main()
