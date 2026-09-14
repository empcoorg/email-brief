"""Which published brief pages are deleted, and which are never touched.

Deleting an artifact cannot be undone, so these pin the narrowness of the rule
as much as its arithmetic: a page that is not unmistakably a brief page, or
whose date does not parse, is left alone. Stdlib unittest; no browser needed.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from brief.retention import BRIEF_FAVICON, RETENTION_DAYS, expired, is_brief_page  # noqa: E402

TODAY = "2026-09-13"


def row(title="Morning Brief", updated="2026-08-01", favicon=BRIEF_FAVICON,
        url="https://claude.ai/code/artifacts/EXAMPLE-1"):
    return {"title": title, "url": url, "favicon": favicon, "updated": updated}


class TestRetentionRule(unittest.TestCase):
    def test_retention_is_thirty_days(self):
        self.assertEqual(RETENTION_DAYS, 30)

    def test_a_page_exactly_at_the_limit_is_kept_and_one_day_past_goes(self):
        at = row(updated="2026-08-14", url="https://claude.ai/code/artifacts/EXAMPLE-at")
        past = row(updated="2026-08-13", url="https://claude.ai/code/artifacts/EXAMPLE-past")
        self.assertEqual(expired([at, past], TODAY), [past["url"]])

    def test_timestamps_and_dates_both_parse(self):
        self.assertEqual(len(expired([row(updated="2026-07-01T09:00:00Z"),
                                      row(updated="2026-07-01")], TODAY)), 2)

    def test_evening_pages_are_brief_pages_too(self):
        self.assertTrue(is_brief_page(row(title="Evening Update")))

    def test_other_artifacts_are_never_selected(self):
        """Only the brief's own favicon, title and host qualify - deleting is permanent."""
        for other in (row(favicon="\U0001F4CA"),
                      row(title="Budget dashboard"),
                      row(title="Notes on the Morning Brief"),
                      row(url="https://example.com/Morning-Brief")):
            self.assertEqual(expired([other], TODAY), [], other)

    def test_an_unreadable_date_is_left_alone_rather_than_guessed(self):
        for bad in ("", None, "last month", "2026-13-40"):
            self.assertEqual(expired([row(updated=bad)], TODAY), [], bad)

    def test_a_bad_today_is_refused(self):
        with self.assertRaises(ValueError):
            expired([row()], "yesterday")


class TestExpiredCli(unittest.TestCase):
    def run_cli(self, rows):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "listing.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(rows, fh)
            return subprocess.run([sys.executable, "-m", "brief", "expired", path, "--today", TODAY],
                                  cwd=ROOT, capture_output=True, text=True)

    def test_prints_one_url_per_line_and_exits_0(self):
        old = row(url="https://claude.ai/code/artifacts/EXAMPLE-old")
        new = row(updated="2026-09-12", url="https://claude.ai/code/artifacts/EXAMPLE-new")
        res = self.run_cli([old, new])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.split(), [old["url"]])

    def test_nothing_to_delete_exits_3_with_empty_stdout(self):
        res = self.run_cli([row(updated="2026-09-12")])
        self.assertEqual((res.returncode, res.stdout), (3, ""))

    def test_a_listing_that_is_not_a_list_exits_2(self):
        res = self.run_cli({"title": "Morning Brief"})
        self.assertEqual(res.returncode, 2)


if __name__ == "__main__":
    unittest.main()
