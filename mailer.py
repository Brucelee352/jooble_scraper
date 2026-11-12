"""Email the Listings table as a .csv attachment.

The user types a recipient address in the dashboard and presses "Email CSV";
the app sends the rows currently shown in the data viewer (after the state
filter and any column filters/sorting) through Gmail SMTP.

Configuration (environment variables):

    SMTP_USER           Gmail address that logs in to SMTP (required to send)
    SMTP_APP_PASSWORD   16-char Gmail App Password for SMTP_USER (required)
    ALERT_FROM          From address; a verified Gmail "Send mail as" alias
                        such as jobs@yourdomain.com (default: SMTP_USER)
    ALERT_FROM_NAME     Display name on the From line (default "Jooble Listings")
    SMTP_HOST/SMTP_PORT Default smtp.gmail.com / 587 (STARTTLS)
"""

from __future__ import annotations

import csv
import io
import os
import re
import smtplib
import threading
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr

#: Minimum seconds between sends (per app process). Any visitor can type any
#: address, so this keeps the app from being used to mass-send through your
#: Gmail account. Set to 0 to disable.
SEND_COOLDOWN_SECONDS = 45

# Pragmatic shape check: one "@", no spaces, a dot in the domain.
_EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
# Leading characters spreadsheet apps treat as a formula (CSV injection).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_last_send = 0.0
_send_lock = threading.Lock()


class MailError(Exception):
    """Email can't be sent (not configured, bad address, or too soon)."""


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def smtp_configured() -> bool:
    return bool(_env("SMTP_USER") and _env("SMTP_APP_PASSWORD"))


def check_recipient(address: str | None) -> str:
    """Return the trimmed address, or raise MailError if it isn't one."""
    address = (address or "").strip()
    if not address:
        raise MailError("Enter an email address.")
    if len(address) > 254 or not _EMAIL_RE.match(address):
        raise MailError(f"{address!r} doesn't look like an email address.")
    return address


def _cell(value) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    text = str(value)
    # Prefix a quote so Excel/Sheets show text instead of running a formula.
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def rows_to_csv(rows: list[dict], columns: list[tuple[str, str]]) -> bytes:
    """CSV bytes (UTF-8 with BOM, so Excel reads accents) for ``rows``.

    ``columns`` is a list of (header, row key) pairs, in output order.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([header for header, _ in columns])
    for row in rows:
        writer.writerow([_cell(row.get(key)) for _, key in columns])
    return buf.getvalue().encode("utf-8-sig")


def build_email(recipient: str, csv_bytes: bytes, n_rows: int,
                search: str = "") -> EmailMessage:
    now = datetime.now()
    noun = "job" if n_rows == 1 else "jobs"
    msg = EmailMessage()
    msg["Subject"] = f"Jooble listings: {n_rows} {noun}" + (
        f" ({search})" if search else "")
    msg["From"] = formataddr((_env("ALERT_FROM_NAME", "Jooble Listings"),
                              _env("ALERT_FROM") or _env("SMTP_USER")))
    msg["To"] = recipient
    msg.set_content(
        f"Attached: {n_rows} {noun} exported from the Jooble Listings "
        f"dashboard on {now:%Y-%m-%d %H:%M}."
        + (f"\nSearch: {search}" if search else ""))
    msg.add_attachment(csv_bytes, maintype="text", subtype="csv",
                       params={"charset": "utf-8"},
                       filename=f"jooble_listings_{now:%Y%m%d_%H%M}.csv")
    return msg


def send_email(msg: EmailMessage) -> None:
    """Send via SMTP, enforcing SEND_COOLDOWN_SECONDS between sends."""
    global _last_send
    if not smtp_configured():
        raise MailError(
            "Email is not configured: set SMTP_USER and SMTP_APP_PASSWORD.")
    with _send_lock:
        wait = SEND_COOLDOWN_SECONDS - (time.monotonic() - _last_send)
        if _last_send and wait > 0:
            raise MailError(
                f"Please wait {int(wait) + 1}s before sending another email.")
        host = _env("SMTP_HOST", "smtp.gmail.com")
        port = int(_env("SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(_env("SMTP_USER"), _env("SMTP_APP_PASSWORD"))
            smtp.send_message(msg)
        _last_send = time.monotonic()
