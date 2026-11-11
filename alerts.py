"""Scheduled job-alert emails for the jooble_scraper Dash app.

One saved schedule (search + recipient + cadence) lives in a small JSON
document. A timer outside the app - Cloud Scheduler in production - POSTs to
the app's ``/tasks/send-digest`` endpoint (e.g. hourly); each call runs
:func:`run_due_digest`, which sends only when the schedule's cadence has
elapsed, and only listings that were not in an earlier email.

Email goes out through Gmail SMTP using an App Password, optionally from a
verified "Send mail as" alias on your own domain.

Configuration (environment variables):

    SMTP_USER           Gmail address that logs in to SMTP (required to send)
    SMTP_APP_PASSWORD   16-char Gmail App Password for SMTP_USER (required)
    ALERT_FROM          From address; a verified Gmail alias such as
                        jobs@yourdomain.com (default: SMTP_USER)
    ALERT_FROM_NAME     Display name on the From line (default "Jooble Job Alerts")
    ALERT_TO            Comma-separated allowlist of recipients the UI may
                        schedule (default: SMTP_USER only)
    ALERT_STORE         Where the schedule lives: gs://bucket/path.json on
                        Cloud Run (container disk is ephemeral), or a local
                        file path (default .alerts/schedule.json)
    TASK_TOKEN          Shared secret the scheduler sends in the
                        X-Task-Token header (required for the endpoint)
    SMTP_HOST/SMTP_PORT Default smtp.gmail.com / 587 (STARTTLS)
"""

from __future__ import annotations

import html
import json
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

import pandas as pd

from jooble_data import fetch_jobs

CADENCES = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}
#: The scheduler fires on a fixed tick (hourly); without slack a send that
#: ran a few seconds late yesterday would slip a whole tick today.
DUE_SLACK = timedelta(minutes=30)
#: Listing ids remembered so later emails only carry new jobs.
MAX_SENT_IDS = 5000
DEFAULT_STORE = ".alerts/schedule.json"
MAX_ROWS_IN_EMAIL = 100


class AlertConfigError(Exception):
    """Email alerts are not configured (missing env vars / bad recipient)."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def smtp_configured() -> bool:
    return bool(_env("SMTP_USER") and _env("SMTP_APP_PASSWORD"))


def allowed_recipients() -> list[str]:
    """Addresses the UI may schedule. Restricting this matters because the
    app is publicly reachable: without it anyone could use it to mail
    arbitrary addresses from your account."""
    raw = _env("ALERT_TO") or _env("SMTP_USER")
    return [a.strip().lower() for a in raw.split(",") if a.strip()]


def check_recipient(address: str | None) -> str:
    address = (address or "").strip().lower()
    if not address:
        raise AlertConfigError("Enter a recipient email address.")
    allowed = allowed_recipients()
    if address not in allowed:
        raise AlertConfigError(
            "That address is not on the alert allowlist. Add it to the "
            "ALERT_TO environment variable to enable it.")
    return address


# ---------------------------------------------------------------------------
# Schedule storage: one JSON document, on GCS or local disk
# ---------------------------------------------------------------------------

def _store_location() -> str:
    return _env("ALERT_STORE", DEFAULT_STORE)


def _gcs_blob(uri: str):
    from google.cloud import storage  # lazy: only needed on Cloud Run
    bucket, _, path = uri[len("gs://"):].partition("/")
    return storage.Client().bucket(bucket).blob(path or "alerts/schedule.json")


def load_schedule() -> dict | None:
    """The saved schedule, or None if none is set."""
    loc = _store_location()
    if loc.startswith("gs://"):
        blob = _gcs_blob(loc)
        if not blob.exists():
            return None
        data = json.loads(blob.download_as_text())
    else:
        path = Path(loc)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    return data or None


def save_schedule(schedule: dict | None) -> None:
    """Persist the schedule; None clears it."""
    loc = _store_location()
    text = json.dumps(schedule or {}, indent=2)
    if loc.startswith("gs://"):
        _gcs_blob(loc).upload_from_string(text,
                                          content_type="application/json")
    else:
        path = Path(loc)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_schedule(*, keywords: str, location: str, days: int,
                 recipient: str, cadence: str,
                 previous: dict | None = None) -> dict:
    """Build a schedule document. Re-saving the same search keeps the
    already-sent ids so the next email does not repeat listings."""
    if cadence not in CADENCES:
        raise AlertConfigError(f"Unknown cadence {cadence!r}.")
    sent_ids: list[str] = []
    if previous and (previous.get("keywords"), previous.get("location")) == (
            keywords, location):
        sent_ids = list(previous.get("sent_ids") or [])
    return {
        "keywords": keywords,
        "location": location,
        "days": int(days),
        "recipient": check_recipient(recipient),
        "cadence": cadence,
        "created": _now().isoformat(),
        "last_run": None,
        "last_sent": None,
        "sent_ids": sent_ids,
    }


def describe(schedule: dict | None) -> str:
    if not schedule:
        return "No email alert scheduled."
    last = schedule.get("last_sent")
    last_txt = (f" Last email: {last[:16].replace('T', ' ')} UTC."
                if last else " No email sent yet.")
    return (f'{schedule["cadence"].capitalize()} email to '
            f'{schedule["recipient"]} for "{schedule["keywords"]}" in '
            f'"{schedule["location"]}" (last {schedule["days"]} days).'
            f"{last_txt}")


def is_due(schedule: dict, now: datetime | None = None) -> bool:
    now = now or _now()
    last = schedule.get("last_run")
    if not last:
        return True
    elapsed = now - datetime.fromisoformat(last)
    return elapsed >= CADENCES[schedule["cadence"]] - DUE_SLACK


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def _safe_link(url: str | None) -> str:
    url = (url or "").strip()
    return url if url.startswith(("https://", "http://")) else ""


def build_email(schedule: dict, jobs: pd.DataFrame) -> EmailMessage:
    """Plain-text + HTML email listing ``jobs`` (already filtered to new)."""
    n = len(jobs)
    shown = jobs.head(MAX_ROWS_IN_EMAIL)
    subject = (f'{n} new job{"s" if n != 1 else ""}: '
               f'{schedule["keywords"]} - {schedule["location"]}')

    def cell(v) -> str:
        return "" if v is None or (isinstance(v, float) and pd.isna(v)) \
            else html.escape(str(v))

    rows_html, rows_text = [], []
    for _, r in shown.iterrows():
        link = _safe_link(r.get("link"))
        title = cell(r.get("title")) or "Untitled job"
        title_html = (f'<a href="{html.escape(link, quote=True)}" '
                      f'style="color:#5661c9">{title}</a>' if link else title)
        updated = r.get("updated")
        updated = updated.strftime("%Y-%m-%d") if hasattr(
            updated, "strftime") else cell(updated)
        rows_html.append(
            "<tr>"
            f'<td style="padding:6px 10px">{title_html}</td>'
            f'<td style="padding:6px 10px">{cell(r.get("company"))}</td>'
            f'<td style="padding:6px 10px">{cell(r.get("location"))}</td>'
            f'<td style="padding:6px 10px">{cell(r.get("salary"))}</td>'
            f'<td style="padding:6px 10px">{updated}</td>'
            "</tr>")
        rows_text.append(
            f"- {r.get('title') or 'Untitled job'} | {r.get('company') or ''}"
            f" | {r.get('location') or ''} | {link}")
    more = (f"<p>...and {n - len(shown)} more.</p>"
            if n > len(shown) else "")
    head = ("".join(
        f'<th style="text-align:left;padding:6px 10px;'
        f'background:#e9ebfa">{h}</th>'
        for h in ("Job title", "Company", "Location", "Salary", "Updated")))
    body_html = f"""\
<html><body style="font-family:Segoe UI,Arial,sans-serif;color:#111">
<h2 style="color:#5661c9;margin-bottom:4px">{html.escape(subject)}</h2>
<p style="color:#55596a;margin-top:0">Search: "{html.escape(schedule["keywords"])}"
in "{html.escape(schedule["location"])}", posted in the last
{int(schedule["days"])} days.</p>
<table style="border-collapse:collapse;border:1px solid #c9ccd8">
<tr>{head}</tr>
{''.join(rows_html)}
</table>{more}
<p style="color:#8a8fa3;font-size:12px">Sent {schedule["cadence"]} by the
Jooble Listings app. To stop, open the app's Fetch Jobs dialog and press
"Stop alerts".</p>
</body></html>"""

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((_env("ALERT_FROM_NAME", "Jooble Job Alerts"),
                              _env("ALERT_FROM") or _env("SMTP_USER")))
    msg["To"] = schedule["recipient"]
    msg.set_content(subject + "\n\n" + "\n".join(rows_text))
    msg.add_alternative(body_html, subtype="html")
    return msg


def send_email(msg: EmailMessage) -> None:
    if not smtp_configured():
        raise AlertConfigError(
            "Email is not configured: set SMTP_USER and SMTP_APP_PASSWORD.")
    host = _env("SMTP_HOST", "smtp.gmail.com")
    port = int(_env("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(_env("SMTP_USER"), _env("SMTP_APP_PASSWORD"))
        smtp.send_message(msg)


# ---------------------------------------------------------------------------
# The digest run (called by the scheduler endpoint and "Send now")
# ---------------------------------------------------------------------------

def run_digest(schedule: dict, now: datetime | None = None) -> dict:
    """Fetch the schedule's search, email jobs not sent before, and return
    the updated schedule plus a result summary under ``"result"``."""
    now = now or _now()
    df = fetch_jobs(days=schedule["days"], limit=None,
                    keywords=schedule["keywords"],
                    location=schedule["location"], strict=True)
    sent = set(schedule.get("sent_ids") or [])
    fresh = df[~df["id"].astype(str).isin(sent)] if not df.empty else df
    updated = dict(schedule, last_run=now.isoformat())
    if fresh.empty:
        updated["result"] = {"sent": 0, "found": len(df)}
        return updated
    send_email(build_email(schedule, fresh))
    ids = list(schedule.get("sent_ids") or []) + [
        str(i) for i in fresh["id"]]
    updated["sent_ids"] = ids[-MAX_SENT_IDS:]
    updated["last_sent"] = now.isoformat()
    updated["result"] = {"sent": len(fresh), "found": len(df)}
    return updated


def run_due_digest(force: bool = False) -> dict:
    """Load the schedule, run it if due (or ``force``), save, and report."""
    schedule = load_schedule()
    if not schedule:
        return {"status": "no-schedule"}
    if not force and not is_due(schedule):
        return {"status": "not-due", "last_run": schedule.get("last_run")}
    updated = run_digest(schedule)
    result = updated.pop("result")
    save_schedule(updated)
    return {"status": "ran", **result}
