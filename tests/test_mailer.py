"""Tests for emailing the Listings table as a CSV (mailer.py + app callback).

No network: SMTP is mocked. Run from the repo root:

    python -m unittest discover -s tests
"""

import csv
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ENV = {"KEY": "test-key", "SMTP_USER": "me@gmail.com",
       "SMTP_APP_PASSWORD": "app-password", "ALERT_FROM": "jobs@example.com"}

ROWS = [
    {"title": "Data Analyst", "company": "Acme & Co", "location": "Austin, TX",
     "salary": "$90k", "link_md": "[Open](https://x)", "link": "https://x/1",
     "skills_str": "python, sql", "updated": "2026-11-10"},
    {"title": "=HYPERLINK(\"evil\")", "company": None, "location": "Remote",
     "link": "https://x/2"},
]


class _Base(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        import mailer
        self.mailer = mailer
        mailer._last_send = 0.0
        smtp = mock.patch("mailer.smtplib.SMTP")
        self.smtp_cls = smtp.start()
        self.addCleanup(smtp.stop)
        self.smtp = self.smtp_cls.return_value.__enter__.return_value


class TestMailer(_Base):
    def test_check_recipient(self):
        self.assertEqual(self.mailer.check_recipient("  a@b.co "), "a@b.co")
        for bad in ("", None, "nope", "a@b", "a@b.co, c@d.co", "a b@c.co"):
            with self.assertRaises(self.mailer.MailError, msg=bad):
                self.mailer.check_recipient(bad)

    def test_csv_columns_and_formula_escaping(self):
        data = self.mailer.rows_to_csv(
            ROWS, [("Job Title", "title"), ("Company", "company"),
                   ("Link", "link")])
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))  # BOM for Excel
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        self.assertEqual(rows[0], ["Job Title", "Company", "Link"])
        self.assertEqual(rows[1], ["Data Analyst", "Acme & Co", "https://x/1"])
        self.assertEqual(rows[2][0], "'=HYPERLINK(\"evil\")")
        self.assertEqual(rows[2][1], "")

    def test_email_has_csv_attachment(self):
        msg = self.mailer.build_email("you@x.com", b"a,b\n", 2)
        self.assertEqual(msg["To"], "you@x.com")
        self.assertIn("jobs@example.com", msg["From"])
        att = list(msg.iter_attachments())
        self.assertEqual(len(att), 1)
        self.assertEqual(att[0].get_content_type(), "text/csv")
        self.assertTrue(att[0].get_filename().endswith(".csv"))

    def test_send_requires_config(self):
        with mock.patch.dict(os.environ, {"SMTP_APP_PASSWORD": ""}):
            with self.assertRaises(self.mailer.MailError):
                self.mailer.send_email(self.mailer.build_email("y@x.com", b"", 0))
        self.smtp.send_message.assert_not_called()

    def test_cooldown_blocks_rapid_second_send(self):
        msg = self.mailer.build_email("y@x.com", b"", 0)
        self.mailer.send_email(msg)
        with self.assertRaises(self.mailer.MailError):
            self.mailer.send_email(msg)
        self.assertEqual(self.smtp.send_message.call_count, 1)


class TestAppCallback(_Base):
    def setUp(self):
        super().setUp()
        import app
        self.app = app

    def test_sends_shown_rows_with_table_headers(self):
        out = self.app.email_csv(1, "you@x.com", ROWS[:1], ROWS)
        self.assertIn("Sent 1 job", str(out))
        sent = self.smtp.send_message.call_args[0][0]
        body = next(sent.iter_attachments()).get_content()
        header = next(csv.reader(io.StringIO(body.lstrip("﻿"))))
        self.assertEqual(header[0], "Job Title")
        self.assertIn("https://x/1", body)        # plain URL, not Markdown
        self.assertNotIn("[Open]", body)

    def test_no_rows(self):
        out = self.app.email_csv(1, "you@x.com", [], ROWS)
        self.assertIn("no rows", str(out))
        self.smtp.send_message.assert_not_called()

    def test_bad_address(self):
        out = self.app.email_csv(1, "not-an-email", None, ROWS)
        self.assertIn("doesn't look like", str(out))
        self.smtp.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
