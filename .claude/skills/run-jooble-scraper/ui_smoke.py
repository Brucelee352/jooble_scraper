"""UI smoke test for the Dash app (app.py).

Exercises the fetch path end-to-end with requests.post mocked (no API key
needed), reusing the canned Jooble payload pattern from driver.py's
run_module_smoke. Calls the app's plain fetch function (do_fetch) and the
map builder under the mock and asserts on the results, plus the error path
with no KEY set.

Run:
    ./venv/Scripts/python .claude/skills/run-jooble-scraper/ui_smoke.py

Exit code 0 = pass.
"""

import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import requests  # noqa: E402

now = datetime.now()


def iso(days_ago):
    return (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.0000000")


FAKE_JOBS = [
    {"id": -7000123456789012345, "title": "Data Engineer",
     "company": "Acme Analytics", "location": "Austin, TX",
     "salary": "$120k - $150k", "type": "Full-time",
     "snippet": "Pipelines.", "link": "https://jooble.org/jdp/1",
     "updated": iso(1), "source": "example.com"},
    {"id": 8000987654321098765, "title": "Analytics Engineer",
     "company": "Globex Corp", "location": "Remote, United States",
     "salary": "", "type": "Contract",
     "snippet": "dbt + Snowflake.", "link": "https://jooble.org/jdp/2",
     "updated": iso(3), "source": "jobs.example.org"},
]


class FakeResp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def fake_post(url, **kw):
    page = int(kw["json"]["page"])
    return FakeResp({"totalCount": 2, "jobs": FAKE_JOBS if page <= 1 else []})


def main():
    # Importing the app must not touch the network and must work with no KEY.
    os.environ.pop("KEY", None)
    with mock.patch.object(
        requests, "post",
        mock.Mock(side_effect=AssertionError("network call at import time")),
    ):
        import app  # noqa: F401

    import app as app_mod

    # 1. Error path: no KEY set -> user-presentable error mentioning KEY.
    with mock.patch.dict(os.environ, clear=True):
        records, error = app_mod.do_fetch(7)
    assert records is None and error, "expected an error with no KEY set"
    assert "KEY" in error, f"error should mention the KEY env var: {error!r}"

    # 2. Happy path under the mocked API.
    with mock.patch.dict(os.environ, {"KEY": "fake-key-for-mock-run"}), \
            mock.patch.object(requests, "post", fake_post):
        records, error = app_mod.do_fetch(7)
    assert error is None, f"unexpected error: {error}"
    assert records, "no records returned"
    titles = {r["title"] for r in records}
    assert {"Data Engineer", "Analytics Engineer"} <= titles, titles
    de = next(r for r in records if r["title"] == "Data Engineer")
    assert de["link_md"] == "[Open](https://jooble.org/jdp/1)", de["link_md"]
    assert de["id"] == "-7000123456789012345", de["id"]
    remote = next(r for r in records if r["company"] == "Globex Corp")
    assert math.isnan(remote["lat"]), "Remote job should have NaN lat"

    # 3. Map figure: only geocodable rows plotted, unmapped count correct.
    import pandas as pd
    fig, unmapped = app_mod.build_map(pd.DataFrame(records))
    assert unmapped == 1, f"expected 1 unmapped job, got {unmapped}"
    trace = fig.data[0]
    assert len(trace.lat) == 1, f"expected 1 mapped point, got {len(trace.lat)}"
    assert trace.customdata[0][0] == "Data Engineer", trace.customdata[0]

    # 4. Drive the fetch callback through the Dash HTTP endpoint too.
    with mock.patch.dict(os.environ, {"KEY": "fake-key-for-mock-run"}), \
            mock.patch.object(requests, "post", fake_post):
        client = app_mod.app.server.test_client()
        # Use the exact multi-output key Dash registered for the fetch
        # callback (includes the allow_duplicate hash suffix).
        output_key = next(
            k for k in app_mod.app.callback_map if "jobs-store.data" in k
        )
        outputs = []
        for spec in output_key.strip(".").split("..."):
            ident, prop = spec.rsplit(".", 1)
            outputs.append({"id": ident, "property": prop})
        body = {
            "output": output_key,
            "outputs": outputs,
            "inputs": [{"id": "do-fetch", "property": "n_clicks", "value": 1}],
            "state": [{"id": "window-radio", "property": "value", "value": 7}],
            "changedPropIds": ["do-fetch.n_clicks"],
        }
        resp = client.post("/_dash-update-component", json=body)
    assert resp.status_code == 200, (resp.status_code, resp.data[:500])
    text = resp.get_data(as_text=True)
    assert "Data Engineer" in text and "Globex Corp" in text, text[:500]

    print("PASS: ui_smoke — import w/o KEY, error path mentions KEY, "
          "mocked fetch, map figure, and Dash callback endpoint all OK")


if __name__ == "__main__":
    main()
