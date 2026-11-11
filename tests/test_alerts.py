"""Tests for the scheduled email alerts (alerts.py + the app's endpoint).

No network: the Jooble fetch and SMTP are mocked, and the schedule is stored
in a temp file. Run from the repo root:

    python -m unittest discover -s tests
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ENV = {
    "KEY": "test-key",
    "SMTP_USER": "me@gmail.com",
    "SMTP_APP_PASSWORD": "app-password",
    "ALERT_FROM": "jobs@brucea-lee.com",
    "ALERT_TO": "me@gmail.com, Other@Example.com",
    "TASK_TOKEN": "s3cret",
}


def jobs_frame(ids):
    return pd.DataFrame([{
        "id": str(i), "title": f"Data Analyst <{i}>", "company": "Acme & Co",
        "location": "Austin, TX", "salary": "$90k",
        "link": "https://jooble.org/desc/%s" % i if i != 3 else "javascript:x",
        "updated": pd.Timestamp("2026-11-10 08:00"),
    } for i in ids])


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = dict(ENV, ALERT_STORE=os.path.join(self.tmp.name, "s.json"))
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        import alerts
        self.alerts = alerts
        self.smtp = mock.patch.object(alerts.smtplib, "SMTP").start()

    def tearDown(self):
        mock.patch.stopall()
        self.env.stop()
        self.tmp.cleanup()

    def schedule(self, **kw):
        args = dict(keywords="data analyst", location="United States",
                    days=7, recipient="me@gmail.com", cadence="daily")
        args.update(kw)
        return self.alerts.new_schedule(**args)

    def sent_messages(self):
        conn = self.smtp.return_value.__enter__.return_value
        return [c.args[0] for c in conn.send_message.call_args_list]


class AlertsTest(_Base):
    def test_recipient_allowlist(self):
        self.assertEqual(self.schedule(recipient=" OTHER@example.com ")
                         ["recipient"], "other@example.com")
        with self.assertRaises(self.alerts.AlertConfigError):
            self.schedule(recipient="stranger@evil.test")

    def test_due_logic(self):
        s = self.schedule()
        now = datetime(2026, 11, 11, 9, tzinfo=timezone.utc)
        self.assertTrue(self.alerts.is_due(s, now))       # never run
        s["last_run"] = (now - timedelta(hours=23, minutes=40)).isoformat()
        self.assertTrue(self.alerts.is_due(s, now))       # within slack
        s["last_run"] = (now - timedelta(hours=20)).isoformat()
        self.assertFalse(self.alerts.is_due(s, now))
        s["cadence"] = "weekly"
        s["last_run"] = (now - timedelta(days=3)).isoformat()
        self.assertFalse(self.alerts.is_due(s, now))

    def test_digest_sends_only_new_jobs_then_skips_when_nothing_new(self):
        self.alerts.save_schedule(self.schedule())
        with mock.patch.object(self.alerts, "fetch_jobs",
                               return_value=jobs_frame([1, 2, 3])):
            r = self.alerts.run_due_digest()
        self.assertEqual(r, {"status": "ran", "sent": 3, "found": 3})
        msg = self.sent_messages()[0]
        self.assertIn("jobs@brucea-lee.com", msg["From"])
        self.assertEqual(msg["To"], "me@gmail.com")
        html = msg.get_body(("html",)).get_content()
        self.assertIn("Data Analyst &lt;1&gt;", html)       # escaped
        self.assertIn("Acme &amp; Co", html)
        self.assertNotIn("javascript:", html)              # unsafe link dropped

        # Not due again right away.
        self.assertEqual(self.alerts.run_due_digest()["status"], "not-due")
        # Forced: job 4 is new, 1-3 were already sent.
        with mock.patch.object(self.alerts, "fetch_jobs",
                               return_value=jobs_frame([1, 2, 4])):
            r = self.alerts.run_due_digest(force=True)
        self.assertEqual(r["sent"], 1)
        # Forced again with nothing new: no email.
        with mock.patch.object(self.alerts, "fetch_jobs",
                               return_value=jobs_frame([1, 4])):
            r = self.alerts.run_due_digest(force=True)
        self.assertEqual(r["sent"], 0)
        self.assertEqual(len(self.sent_messages()), 2)

    def test_resaving_same_search_keeps_sent_ids(self):
        first = dict(self.schedule(), sent_ids=["1", "2"])
        again = self.schedule(cadence="weekly", previous=first)
        self.assertEqual(again["sent_ids"], ["1", "2"])
        other = self.schedule(keywords="data engineer", previous=first)
        self.assertEqual(other["sent_ids"], [])

    def test_no_schedule_and_missing_smtp(self):
        self.assertEqual(self.alerts.run_due_digest()["status"], "no-schedule")
        self.alerts.save_schedule(self.schedule())
        with mock.patch.dict(os.environ, {"SMTP_APP_PASSWORD": ""}), \
                mock.patch.object(self.alerts, "fetch_jobs",
                                  return_value=jobs_frame([1])):
            with self.assertRaises(self.alerts.AlertConfigError):
                self.alerts.run_due_digest()
        # A failed send leaves the schedule un-run, so the next tick retries.
        self.assertIsNone(self.alerts.load_schedule()["last_run"])


class EndpointTest(_Base):
    def test_endpoint_requires_token(self):
        import app
        client = app.server.test_client()
        url = "/tasks/send-digest"
        self.assertEqual(client.post(url).status_code, 403)
        self.assertEqual(client.post(url, headers={"X-Task-Token": "nope"})
                         .status_code, 403)
        # GET falls through to Dash's page catch-all, never to the handler.
        self.assertIsNone(client.get(url).get_json(silent=True))
        r = client.post(url, headers={"X-Task-Token": "s3cret"})
        self.assertEqual((r.status_code, r.get_json()),
                         (200, {"status": "no-schedule"}))
        with mock.patch.dict(os.environ, {"TASK_TOKEN": ""}):
            self.assertEqual(client.post(url).status_code, 503)

    def test_ui_callback_schedule_send_stop(self):
        import app
        args = ("data analyst", "United States", 7, False, "me@gmail.com",
                "weekly")

        def call(trigger):
            with mock.patch.object(app, "ctx",
                                   mock.Mock(triggered_id=trigger)):
                out = app.alert_action(True, 1, 1, 1, *args)
            return str(out[1])

        self.assertIn("Saved. Weekly email to me@gmail.com", call("alert-save"))
        with mock.patch.object(self.alerts, "fetch_jobs",
                               return_value=jobs_frame([7])):
            self.assertIn("Sent 1 new job", call("alert-send-now"))
        self.assertIn("Alerts stopped", call("alert-stop"))
        self.assertIn("No email alert scheduled", call("fetch-modal"))
        bad = ("data analyst", "United States", 7, False, "x@evil.test",
               "daily")
        with mock.patch.object(app, "ctx",
                               mock.Mock(triggered_id="alert-save")):
            self.assertIn("allowlist", str(app.alert_action(True, 1, 0, 0,
                                                            *bad)))


if __name__ == "__main__":
    unittest.main()
