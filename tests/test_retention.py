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

from brief.retention import (BRIEF_FAVICON, RETENTION_DAYS, expired, is_brief_page,  # noqa: E402
                             load_rows, parse_listing, row_from_sent)

TODAY = "2026-09-13"


def row(title="Morning Brief", updated="2026-08-01", favicon=BRIEF_FAVICON,
        url="https://claude.ai/code/artifact/EXAMPLE-1"):
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
                                      row(updated="2026-07-01",
                                          url="https://claude.ai/code/artifact/EXAMPLE-2")],
                                     TODAY)), 2)

    def test_a_page_found_twice_is_deleted_once(self):
        self.assertEqual(expired([row(), row()], TODAY), [row()["url"]])

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


# The Artifact tool's listing, in the shape it prints (values invented).
LISTING = """5 published artifacts (most recent first):
- (mine) Morning Brief — https://claude.ai/code/artifact/EXAMPLE-new — favicon 📬 — updated 2026-09-12
- (mine) Morning Brief — https://claude.ai/code/artifact/EXAMPLE-old — favicon 📬 — updated 2026-08-01
- (mine) Morning Brief notes — https://claude.ai/code/artifact/EXAMPLE-notes — favicon 📬📡 — updated 2026-07-01
- (mine) Evening Update — Tue — https://claude.ai/code/artifact/EXAMPLE-eve — favicon 📬 — updated 2026-08-02
- (shared) Morning Brief — https://claude.ai/code/artifact/EXAMPLE-shared — favicon 📬 — updated 2026-07-01
"""


def sent(subject="Morning Brief — Sat Aug 1, 2026 (10:10 AM run)", date="2026-08-01T17:31:00Z",
         url="https://claude.ai/code/artifact/EXAMPLE-sent"):
    """A Gmail get_message result for a sent brief, trimmed to what matters."""
    return {"id": "EXAMPLE", "subject": subject, "date": date,
            "plaintextBody": "1. HIGH PRIORITY\n...\nBrief record: brief-0123456789ab | shed: none\n\n"
                             "Private: opens only when signed in to claude.ai. Deleted after 30 days.\n"
                             f"Full brief, never truncated: {url}\n"}


class TestListingAndSentBriefs(unittest.TestCase):
    def test_the_listing_is_read_exactly_as_the_tool_prints_it(self):
        rows = parse_listing(LISTING)
        self.assertEqual(len(rows), 4, "the header and the shared row are not rows")
        self.assertEqual(rows[3]["title"], "Evening Update — Tue",
                         "a title containing an em dash must not swallow the URL")
        self.assertEqual(rows[1], {"title": "Morning Brief",
                                   "url": "https://claude.ai/code/artifact/EXAMPLE-old",
                                   "favicon": BRIEF_FAVICON, "updated": "2026-08-01"})

    def test_from_the_listing_only_old_brief_pages_are_selected(self):
        """Not the new one, not a page whose favicon merely starts with the brief's, never a shared one."""
        self.assertEqual(expired(parse_listing(LISTING), TODAY),
                         ["https://claude.ai/code/artifact/EXAMPLE-old",
                          "https://claude.ai/code/artifact/EXAMPLE-eve"])

    def test_a_sent_brief_yields_its_page_and_send_date(self):
        self.assertEqual(row_from_sent(sent()),
                         {"title": "Morning Brief — Sat Aug 1, 2026 (10:10 AM run)",
                          "url": "https://claude.ai/code/artifact/EXAMPLE-sent",
                          "favicon": BRIEF_FAVICON, "updated": "2026-08-01T17:31:00Z"})

    def test_the_page_is_the_last_link_line_the_renderer_wrote(self):
        """A brief quoting an older one must not point the deletion at the older page."""
        msg = sent()
        msg["plaintextBody"] = ("Full brief, never truncated: https://claude.ai/code/artifact/EXAMPLE-quoted\n"
                                + msg["plaintextBody"])
        self.assertEqual(row_from_sent(msg)["url"], "https://claude.ai/code/artifact/EXAMPLE-sent")

    def test_test_sends_and_evening_updates_count_as_briefs(self):
        for subject in ("[TEST] Morning Brief — Sat Aug 1, 2026 (manual run)",
                        "Evening Update — Sat Aug 1, 2026 (6:10 PM run)"):
            self.assertIsNotNone(row_from_sent(sent(subject=subject)), subject)

    def test_a_sent_message_that_is_not_unmistakably_a_brief_is_ignored(self):
        body_without_link = dict(sent(), plaintextBody="Morning Brief\nno link here")
        for msg in (sent(subject="Re: Morning Brief"),
                    sent(subject="Fwd: invoice"),
                    sent(url="https://example.com/Morning-Brief"),
                    body_without_link, "not a message", None):
            self.assertIsNone(row_from_sent(msg), msg)

    def test_the_listing_cap_cannot_hide_a_page_the_sent_folder_still_names(self):
        """The listing holds the 50 newest; a month of briefs pushes the old page off it."""
        newest = [row(updated="2026-09-12", url=f"https://claude.ai/code/artifact/EXAMPLE-{i}")
                  for i in range(50)]
        self.assertEqual(expired(newest, TODAY), [], "the old page is not in the listing at all")
        self.assertEqual(expired(newest + [row_from_sent(sent())], TODAY),
                         ["https://claude.ai/code/artifact/EXAMPLE-sent"])

    def test_load_rows_reads_every_shape_a_run_can_save(self):
        cases = {
            "listing text": (LISTING, 4),
            "one message": (json.dumps(sent()), 1),
            "message after a preamble line": ("Result saved to file:\n" + json.dumps(sent()), 1),
            "several messages": (json.dumps({"messages": [sent(), sent(url="https://claude.ai/code/artifact/EXAMPLE-b")]}), 2),
            "a list of rows": (json.dumps([row()]), 1),
            "a message that is not a brief": (json.dumps(sent(subject="Hello")), 0),
            "prose": ("nothing to see here", 0),
        }
        for name, (text, n) in cases.items():
            self.assertEqual(len(load_rows(text)), n, name)


class TestExpiredCli(unittest.TestCase):
    def run_cli(self, rows=None, files=None):
        """Run `brief expired`; `files` maps names to raw text, and a name ending "/" is a directory."""
        files = dict(files or {"listing.json": json.dumps(rows)})
        with tempfile.TemporaryDirectory() as d:
            args = []
            for name, text in files.items():
                path = os.path.join(d, name)
                if name.endswith("/"):
                    os.makedirs(path)
                    for i, t in enumerate(text):
                        with open(os.path.join(path, f"{i}.json"), "w", encoding="utf-8") as fh:
                            fh.write(t)
                else:
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(text)
                args.append(path)
            return subprocess.run([sys.executable, "-m", "brief", "expired", *args, "--today", TODAY],
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

    def test_unreadable_json_exits_2(self):
        for bad in ("[{not json", '{"messages": "not a list"}'):
            res = self.run_cli(files={"bad.json": bad})
            self.assertEqual(res.returncode, 2, bad)

    def test_the_listing_and_a_folder_of_sent_briefs_combine_without_repeats(self):
        res = self.run_cli(files={
            "artifacts.txt": LISTING,
            "sent/": [json.dumps(sent()), json.dumps(sent()),
                      json.dumps(sent(date="2026-09-10T17:00:00Z",
                                      url="https://claude.ai/code/artifact/EXAMPLE-recent"))],
        })
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.split(), ["https://claude.ai/code/artifact/EXAMPLE-old",
                                              "https://claude.ai/code/artifact/EXAMPLE-eve",
                                              "https://claude.ai/code/artifact/EXAMPLE-sent"])


class TestPromptRunsTheCleanUp(unittest.TestCase):
    """The template is what a run actually follows, so it must match this module."""

    def setUp(self):
        with open(os.path.join(ROOT, "ROUTINE_PROMPT.template.md"), encoding="utf-8") as fh:
            self.prompt = fh.read()
        self.step5 = self.prompt[self.prompt.find("STEP 5"):]

    def test_clean_up_comes_after_delivery(self):
        self.assertGreater(self.prompt.find("STEP 5"), self.prompt.find("STEP 4"))
        self.assertIn("ONLY after the brief has been sent", self.step5)

    def test_it_reads_both_sources_through_the_command(self):
        for needed in ('action "list"', "in:sent", "older_than:30d", "PLAIN_TEXT",
                       "python3 -m brief expired retention/", "on NOTHING else"):
            self.assertIn(needed, self.step5, needed)

    def test_the_window_it_searches_matches_retention(self):
        self.assertIn(f"older_than:{RETENTION_DAYS}d", self.step5)


if __name__ == "__main__":
    unittest.main()
