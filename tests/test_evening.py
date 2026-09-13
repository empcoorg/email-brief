"""The full-page link, the email's record of what it left out, and the evening carry.

These are delivery guarantees rather than layout: a link that goes missing on a
budget re-render, a record that names the wrong sections, or a carried section
that quietly loses its rows all produce an email that looks fine and is wrong.
Stdlib unittest; no browser needed.
"""
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import brief.render as R  # noqa: E402
from brief.evening import (decide, embed_payload, extract_payload, merge,  # noqa: E402
                           parse_record)
from brief.model import PayloadError  # noqa: E402

SAMPLE = os.path.join(ROOT, "sample_payload.json")
URL = "https://claude.ai/code/artifact/00000000-0000-4000-8000-000000000000"


def payload():
    with open(SAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


def visible(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def quiet_evening():
    """An evening with nothing urgent and no rows in the research cards."""
    p = payload()
    for k in ("MKT_ROWS", "FUNDS", "MKT_BULLETS", "STOCKS", "MACRO_ROWS", "JOBS_SECTORS",
              "CRYPTO_ROWS", "CRYPTO_BULLETS", "AI_ITEMS", "JOURNAL_ITEMS", "HIPRI",
              "JOBS_TOP", "JOBS_STATUS", "JOBS_OTHER", "FIN_MOVES", "FIN_NOTES", "PKG",
              "USPS_SCANS"):
        p[k] = []
    p["ACTIONS"] = [r for r in p["ACTIONS"] if r[0] not in ("neg", "warn")]
    p["RETAIL"]["items"], p["RETAIL"]["sales"] = [], []
    p["VOIP"]["messages"], p["USPS"]["pieces"], p["FLIGHTS"]["legs"] = [], [], []
    return p


class TestFullPageLink(unittest.TestCase):
    def test_link_is_the_last_thing_in_the_email_and_the_text(self):
        _, em, tx = R.render_all(payload(), None, None, URL)
        self.assertTrue(visible(em).endswith(R.short_url(URL)),
                        "the full-page link must be the very last visible text")
        self.assertIn(f'href="{URL}"', em)
        self.assertEqual(tx.rstrip("\n").splitlines()[-1],
                         f"Full brief, never truncated: {URL}")

    def test_link_survives_the_email_shedding_its_cards(self):
        """The link is how a reader reaches what was shed, so it is never shed."""
        _, em, tx = R.render_all(payload(), 40_000, 3_000, URL)
        self.assertTrue(R.LAST_EMAIL_REPORT["shed"], "the budget should have forced shedding")
        self.assertIn(f'href="{URL}"', em)
        self.assertIn("in the full brief linked at the end", em)
        self.assertTrue(tx.rstrip().endswith(URL))

    def test_no_link_and_no_change_without_a_url(self):
        _, em, tx = R.render_all(payload())
        self.assertNotIn("Full brief, never truncated", em + tx)

    def test_an_unsafe_url_is_refused_outright(self):
        """Refusing only the href would still print the address as text."""
        with self.assertRaises(ValueError):
            R.render_all(payload(), None, None, "javascript:alert(1)")


class TestEmailRecord(unittest.TestCase):
    def test_every_rendered_section_heading_is_recognized(self):
        """Clip detection and carried captions both find sections by heading.

        If the heading markup changes and detection silently misses one, that
        section can be hidden by Gmail and never carried. Derived from the
        rendered email, so a new or renamed section fails here first.
        """
        _, em, _ = R.render_all(payload())
        found = {R._title_of(m.group(1)) for m in R._EM_H2.finditer(em)}
        missing = [n for n in R.SECTION_KEYS if n not in found]
        self.assertEqual(missing, [], "sections rendered but not recognized by heading")

    def test_shed_cards_are_recorded_in_the_order_they_went(self):
        R.render_all(payload(), R.EMAIL_BUDGET_BYTES)
        shed = R.LAST_EMAIL_REPORT["shed"]
        self.assertTrue(shed)
        self.assertEqual(shed, list(R.SHED_ORDER[:len(shed)]))

    def test_sections_past_the_clip_point_are_recorded(self):
        """Nothing shed, but the email is over the clip threshold: say what hides."""
        _, em, _ = R.render_all(payload())
        self.assertGreater(len(em.encode("utf-8")), R.EMAIL_BUDGET_BYTES)
        self.assertEqual(R.LAST_EMAIL_REPORT["shed"], [])
        self.assertIn("Retail sales", R.LAST_EMAIL_REPORT["clipped"],
                      "the last card sits past the clip point in the sample")
        self.assertNotIn("High priority", R.LAST_EMAIL_REPORT["clipped"])

    def test_the_record_line_round_trips(self):
        _, _, tx = R.render_all(payload(), R.EMAIL_BUDGET_BYTES, None, URL)
        rec = parse_record(tx)
        self.assertIsNotNone(rec, "text copy must carry a parseable record")
        self.assertEqual(rec["shed"], R.LAST_EMAIL_REPORT["shed"])
        self.assertEqual(rec["build"], R.build_marker(payload()))


class TestPayloadEmbedding(unittest.TestCase):
    def test_round_trip_including_a_closing_script_tag(self):
        p = payload()
        p["AI_ITEMS"] = [["</script><img src=x>", "detail", "https://example.com/a"]]
        self.assertEqual(extract_payload(embed_payload("<p>page</p>", p)), p)

    def test_extract_finds_the_block_inside_a_host_wrapper(self):
        page = embed_payload("<title>t</title><p>x</p>", {"A": 1})
        wrapped = ("[Artifact 1234 — owned by you, private; raw HTML follows] "
                   "<!doctype html><html><head></head><body>" + page + "</body></html>")
        self.assertEqual(extract_payload(wrapped), {"A": 1})

    def test_no_block_means_none_not_a_guess(self):
        self.assertIsNone(extract_payload("<p>an older page</p>"))


class TestEveningMerge(unittest.TestCase):
    def test_a_section_with_nothing_new_is_the_morning_section_verbatim(self):
        morning, evening = payload(), quiet_evening()
        merged, _ = merge(morning, evening, ["Large caps", "Fed & labor market"], "10:12 AM PDT")
        for k in ("STOCKS", "MACRO_ROWS", "JOBS_SECTORS", "MACRO_NOTE"):
            self.assertEqual(merged[k], morning[k], f"{k} must carry unchanged")
        self.assertEqual(merged["CARRIED"]["merged"], [])

    def test_a_section_with_new_rows_keeps_both_morning_first(self):
        morning, evening = payload(), quiet_evening()
        evening["AI_ITEMS"] = [["Evening item", "arrived after 10 AM", "https://example.com/e"]]
        merged, _ = merge(morning, evening, ["AI & programming"], "10:12 AM PDT")
        self.assertEqual(merged["AI_ITEMS"], morning["AI_ITEMS"] + evening["AI_ITEMS"])
        self.assertEqual(merged["CARRIED"]["merged"], ["AI & programming"])

    def test_carrying_does_not_touch_other_sections(self):
        morning, evening = payload(), quiet_evening()
        merged, _ = merge(morning, evening, ["Large caps"], "x")
        self.assertEqual(merged["CRYPTO_ROWS"], evening["CRYPTO_ROWS"])

    def test_an_unknown_section_name_is_an_error(self):
        with self.assertRaises(PayloadError):
            merge(payload(), quiet_evening(), ["Weather"], "x")

    def test_carried_sections_are_labelled_and_the_label_does_not_leak(self):
        morning, evening = payload(), quiet_evening()
        merged, _ = merge(morning, evening, ["Large caps"], "Sun Sep 13, 10:12 AM PDT")
        fh, em, tx = R.render_all(merged)
        label = "Carried from this morning's brief (Sun Sep 13, 10:12 AM PDT)"
        for name, doc in (("email", em), ("page", fh), ("text", tx)):
            self.assertIn(label, doc, f"{name} must label the carried section")
        fh2, em2, tx2 = R.render_all(payload())
        self.assertNotIn("Carried from this morning", fh2 + em2 + tx2,
                         "CARRIED must not survive into the next render")

    def test_decision(self):
        quiet = quiet_evening()
        self.assertEqual(decide(quiet, [])[0], False)
        self.assertEqual(decide(quiet, ["Large caps"])[0], True)


class TestEveningCli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "brief", *args], cwd=ROOT,
                              capture_output=True, text=True)

    def test_morning_to_evening_end_to_end(self):
        td = tempfile.mkdtemp(prefix="brief-evening-")
        m = self.run_cli("render", SAMPLE, "--out-dir", os.path.join(td, "m"),
                         "--date", "2026-09-07", "--clip-guard", "--full-url", URL)
        self.assertEqual(m.returncode, 0, m.stderr)
        page = os.path.join(td, "m", "full-brief-2026-09-07.html")
        pages = [f for f in os.listdir(os.path.join(td, "m")) if f.startswith("morning-brief")]
        self.assertEqual(len(pages), 1, "exactly one file may match the session-page lookup")
        text = os.path.join(td, "m", "email.txt")
        report = json.load(open(os.path.join(td, "m", "email.report.json"), encoding="utf-8"))
        self.assertTrue(report["shed"])
        ev = os.path.join(td, "evening.json")
        with open(ev, "w", encoding="utf-8") as fh:
            json.dump(quiet_evening(), fh)
        out = os.path.join(td, "merged.json")
        r = self.run_cli("evening", "--evening", ev, "--morning-page", page,
                         "--record", text, "--from", "10:12 AM PDT", "-o", out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        merged = json.load(open(out, encoding="utf-8"))
        self.assertEqual(merged["CARRIED"]["sections"], report["shed"] + report["clipped"])

    def test_quiet_evening_with_nothing_cut_is_skipped(self):
        td = tempfile.mkdtemp(prefix="brief-evening-")
        ev, rec = os.path.join(td, "e.json"), os.path.join(td, "r.txt")
        json.dump(quiet_evening(), open(ev, "w", encoding="utf-8"))
        open(rec, "w").write("Brief record: brief-0123456789ab | shed: none | beyond Gmail's clip: none\n")
        r = self.run_cli("evening", "--evening", ev, "--record", rec, "-o", os.path.join(td, "o.json"))
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)

    def test_cuts_without_a_page_to_carry_from_fail_loudly(self):
        td = tempfile.mkdtemp(prefix="brief-evening-")
        ev, rec = os.path.join(td, "e.json"), os.path.join(td, "r.txt")
        json.dump(quiet_evening(), open(ev, "w", encoding="utf-8"))
        open(rec, "w").write("Brief record: brief-0123456789ab | shed: Large caps | beyond Gmail's clip: none\n")
        r = self.run_cli("evening", "--evening", ev, "--record", rec, "-o", os.path.join(td, "o.json"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("no --morning-page", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
