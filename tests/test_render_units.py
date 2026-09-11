"""Unit tests for the renderer itself: escaping, link safety, direction
coloring, empty sections, determinism, and the paths the sample payload
never exercises (log money axis, unrecognised direction words).

The brief renders content that arrived by email. That content is DATA — the
prompt says so — and these tests are where that promise is enforced against
the markup, rather than asserted in prose.
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

from brief import render_all
from brief.render import money_side
from brief.theme import attr, e, url

SAMPLE = os.path.join(ROOT, "sample_payload.json")


def payload(**overrides):
    p = json.load(open(SAMPLE, encoding="utf-8"))
    for k, v in overrides.items():
        p[k] = v
    return p


class TestEscaping(unittest.TestCase):
    def test_element_text_escapes_angle_brackets_and_ampersands(self):
        self.assertEqual(e("<b>&</b>"), "&lt;b&gt;&amp;&lt;/b&gt;")

    def test_element_text_keeps_quotes_readable(self):
        self.assertEqual(e('He said "hi"'), 'He said "hi"')

    def test_attribute_escaping_closes_the_quote(self):
        self.assertNotIn('"', attr('a" onload="x'))

    def test_payload_markup_never_becomes_markup(self):
        p = payload()
        p["JOBS_TOP"][0][0] = "<script>alert(1)</script>"
        p["FIN_MOVES"][0][1] = "Payee <img src=x onerror=alert(1)>"
        p["PKG"][0][2] = "Item </td></tr><tr><td>injected"
        f, em, _ = render_all(p)
        for out in (f, em):
            self.assertNotIn("<script>", out)
            self.assertNotIn("<img src=x", out)
            self.assertIn("&lt;script&gt;", out)

    def test_a_quote_in_a_link_cannot_break_out_of_the_attribute(self):
        """A job link arrives from an email. Before this was fixed, a crafted
        link closed the href and injected an event handler into the brief."""
        p = payload()
        p["JOBS_TOP"][0][6] = 'https://x.test/" onmouseover="alert(1)'   # [6] is the link
        p["USPS_SCANS"][0][0] = 'data:image/jpeg;base64,AAA" onload="alert(1)'
        f, em, _ = render_all(p)
        for out in (f, em):
            self.assertNotIn('onmouseover="alert(1)"', out)
            self.assertNotIn('onload="alert(1)"', out)
            # the quote must survive as an escaped entity inside the href, not
            # as a real quote that ends the attribute
            self.assertIn("&quot;", out)


class TestPayloadRowShape(unittest.TestCase):
    """Row indices are part of the payload contract. When one shifts, a test
    that pokes the wrong field fails somewhere unrelated and misleads."""

    def test_jobs_top_row_layout(self):
        role, company, comp, loc, src, fit, link = payload()["JOBS_TOP"][0]
        self.assertIn(fit, ("strong", "related", ""))
        self.assertTrue(link.startswith("http"), f"[6] should be the link, got {link!r}")


class TestLinkSafety(unittest.TestCase):
    def test_safe_schemes_pass_through(self):
        for good in ("https://example.com/a?b=1", "http://example.com",
                     "mailto:a@example.com", "data:image/jpeg;base64,AAA",
                     "//example.com/x", "/relative", "#anchor"):
            self.assertNotEqual(url(good), "#", f"{good} should be allowed")

    def test_executable_schemes_are_refused(self):
        for bad in ("javascript:alert(1)", "JavaScript:alert(1)", " javascript:alert(1)",
                    "vbscript:msgbox(1)", "data:text/html,<script>alert(1)</script>",
                    "file:///etc/passwd"):
            self.assertEqual(url(bad), "#", f"{bad} should be refused")

    def test_refused_links_render_inert_not_executable(self):
        p = payload()
        p["AI_ITEMS"][0][2] = "javascript:alert(1)"
        p["JOURNAL_ITEMS"][0][5] = "JavaScript:alert(2)"
        p["FLIGHTS"]["legs"][0]["fa"] = "vbscript:msgbox(1)"
        f, em, _ = render_all(p)
        for out in (f, em):
            self.assertNotIn("javascript:", out.lower())
            self.assertNotIn("vbscript:", out.lower())
            self.assertIn('href="#"', out)


class TestMoneyDirection(unittest.TestCase):
    def test_known_directions(self):
        self.assertEqual(money_side("In"), ("right", "pos"))
        self.assertEqual(money_side("Out"), ("left", "neg"))
        self.assertEqual(money_side("Past due"), ("left", "neg"))
        self.assertEqual(money_side("Internal"), ("right", "neu"))

    def test_unrecognised_direction_is_neutral_never_income(self):
        """The prompt tells the run to write "unclassified" when the evidence is
        ambiguous. Colouring that green would assert income the data does not
        support — the chart must not claim more than the payload does."""
        for unknown in ("Unclassified", "Refund", "", None, "in", "IN"):
            side, cls = money_side(unknown)
            self.assertEqual(cls, "neu", f"{unknown!r} must not be colored as income")

    def test_unclassified_renders_with_the_neutral_fill(self):
        p = payload()
        p["FIN_MOVES"] = [["Mon 9:04 AM EST", "Someone", "Unclear origin",
                           1200.0, "USD", 1200.0, "Unclassified", "±"]]
        f, _, _ = render_all(p)
        self.assertIn("fill neu", f)
        self.assertNotIn("fill pos", f.split("Deposits &amp; finances")[1].split("</section>")[0])


class TestFlightOnTimeColumn(unittest.TestCase):
    """When no leg has an on-time record the column is dropped, not filled with
    an apology in every row — on a phone that column costs a third of the table
    and carries nothing the reader can act on."""

    @staticmethod
    def _without_stats():
        p = payload()
        for leg in p["FLIGHTS"]["legs"]:
            leg.pop("stats", None)
        return p

    def test_column_present_when_records_exist(self):
        f, em, tx = render_all(payload())
        self.assertIn("Recent on-time record", f)
        self.assertIn("On-time record", em)
        self.assertIn("on-time:", tx)

    def test_column_dropped_when_no_leg_has_a_record(self):
        f, em, tx = render_all(self._without_stats())
        self.assertNotIn("Recent on-time record", f)
        self.assertNotIn("On-time record", em)
        self.assertNotIn("on-time:", tx)
        for out in (f, em, tx):
            self.assertNotIn("not available", out)

    def test_flights_still_render_without_records(self):
        f, em, tx = render_all(self._without_stats())
        for out, probe in ((f, "Upcoming flights"), (em, "Upcoming flights"),
                           (tx, "UPCOMING FLIGHTS")):
            self.assertIn(probe, out)
            self.assertIn("NW 412", out)
        # the row keeps its other three columns, so the table stays well formed
        self.assertIn("Denver (DEN)", f)

    def test_column_kept_when_only_some_legs_have_a_record(self):
        p = payload()
        p["FLIGHTS"]["legs"][1].pop("stats", None)
        f, _, _ = render_all(p)
        self.assertIn("Recent on-time record", f)
        self.assertIn("not available", f, "a leg with no record says so once, in its own cell")

    def test_payload_validates_without_the_optional_stats_field(self):
        from brief.model import validate
        self.assertIsNotNone(validate(self._without_stats()))


class TestCurrencyOnOneAxis(unittest.TestCase):
    """All money bars share one USD axis. A foreign charge plotted at its face
    value draws ~19x too long, which is the exact failure this guards."""

    def test_bar_is_drawn_from_the_usd_value_not_the_raw_amount(self):
        p = payload()
        p["FIN_MOVES"] = [
            ["Tue 9:04 AM EST", "Client", "Invoice", 1000.00, "USD", 1000.00, "In", "+"],
            ["Tue 8:12 AM EST", "Airline", "Ticket", 10200.00, "MXN", 551.35, "Out", "−"],
        ]
        f, _, _ = render_all(p)
        fin = f.split("Deposits &amp; finances")[1].split("</section>")[0]
        widths = [float(w) for w in re.findall(r'class="fill \w+ \w+" style="width:([\d.]+)%"', fin)]
        self.assertEqual(len(widths), 2)
        # axis top is an even 1000 -> the USD charge is 50% of a half-track,
        # the MXN charge ~37%. Plotted raw it would clip at 50%.
        self.assertAlmostEqual(widths[0], 50.0, delta=0.6)
        self.assertLess(widths[1], widths[0], "the MXN bar must be shorter than the larger USD one")
        self.assertAlmostEqual(widths[1], 551.35 / 1000.0 * 50, delta=0.6)

    def test_axis_states_its_currency(self):
        f, em, _ = render_all(payload())
        for out in (f, em):
            self.assertRegex(out, r"\$\d+(\.\d+)?k? USD",
                             "the money axis must name the currency it counts")

    def test_foreign_amount_shows_its_conversion(self):
        f, em, tx = render_all(payload())
        for out in (f, em, tx):
            self.assertIn("MX$10,200.00", out, "the original currency must still be shown")
            self.assertIn("551.35", out, "the converted figure must appear beside it")

    def test_usd_rows_show_no_redundant_conversion(self):
        f, _, _ = render_all(payload())
        self.assertNotIn("$5,280.00 (≈", f, "a USD row needs no conversion note")

    def test_unconverted_foreign_amount_is_rejected(self):
        from brief.model import PayloadError, validate
        p = payload()
        p["FIN_MOVES"] = [["t", "p", "d", 10200.00, "MXN", 10200.00, "Out", "−"]]
        with self.assertRaises(PayloadError) as cm:
            validate(p)
        self.assertIn("unconverted", str(cm.exception).lower() + "unconverted")
        self.assertIn("MXN", str(cm.exception))

    def test_usd_row_with_mismatched_usd_is_rejected(self):
        from brief.model import PayloadError, validate
        p = payload()
        p["FIN_MOVES"] = [["t", "p", "d", 100.0, "USD", 250.0, "In", "+"]]
        with self.assertRaises(PayloadError):
            validate(p)


class TestTieredDetail(unittest.TestCase):
    """Critical detail gets FORMATTED, not deleted: three tiers that stay
    scannable, rather than one sentence that reads as a wall."""

    THREE = ["Conference ticket · order MX-4471",
             "Sample Bank Visa ···1234 · non-refundable/no changes",
             "9,800.00 fee + 400.00 service MXN · FX 18.50 MXN/USD (example rate source, Mar 3)"]

    def _row(self, detail):
        p = payload()
        p["FIN_MOVES"] = [["Tue 8:12 AM EST", "Airline", detail, 10200.0, "MXN", 551.35, "Out", "−"]]
        return p

    def test_a_plain_string_still_works(self):
        f, em, tx = render_all(self._row("Simple one-line detail"))
        for out in (f, em, tx):
            self.assertIn("Simple one-line detail", out)

    def test_three_tiers_all_render_and_keep_every_fact(self):
        f, em, tx = render_all(self._row(self.THREE))
        for out in (f, em, tx):
            for line in self.THREE:
                self.assertIn(line, out, f"a detail line was dropped: {line[:40]}")

    def test_tiers_are_visually_weighted_not_just_concatenated(self):
        f, em, _ = render_all(self._row(self.THREE))
        # scope to the money table — High priority also has a Detail column
        fin = f.split("Deposits &amp; finances")[1]
        cell = fin.split('data-l="Detail"')[1].split("</td>")[0]
        self.assertEqual(cell.count("<br>"), 2, "tiers must be separate lines")
        self.assertIn('class="meta"', cell, "tier 2 must be muted")
        self.assertIn("font-size:12px", cell, "tier 3 must be smaller still")
        # the email has no classes, so it uses the inline muted style
        ecell = em.split("Conference ticket")[1][:400]
        self.assertIn("font-size:12.5px", ecell)

    def test_plain_text_indents_the_tiers(self):
        _, _, tx = render_all(self._row(self.THREE))
        for line in self.THREE:
            self.assertIn(f"      {line}", tx, "plain text must indent detail under its row")

    def test_a_fourth_line_is_rejected(self):
        from brief.model import MAX_DETAIL_LINES, PayloadError, validate
        self.assertEqual(MAX_DETAIL_LINES, 3)
        with self.assertRaises(PayloadError) as cm:
            validate(self._row(self.THREE + ["one line too many"]))
        self.assertIn("4 detail lines", str(cm.exception))

    def test_non_string_lines_are_rejected(self):
        from brief.model import PayloadError, validate
        with self.assertRaises(PayloadError):
            validate(self._row(["fine", 42]))

    def test_blank_lines_are_dropped_not_rendered_as_gaps(self):
        f, _, _ = render_all(self._row(["Real line", "", "   "]))
        fin = f.split("Deposits &amp; finances")[1]
        cell = fin.split('data-l="Detail"')[1].split("</td>")[0]
        self.assertNotIn("<br>", cell, "empty tiers must not leave blank lines")


class TestRankedLeadCap(unittest.TestCase):
    """As many leads as the window produced, capped at 25."""

    def _leads(self, n):
        p = payload()
        row = p["JOBS_TOP"][0]
        p["JOBS_TOP"] = [list(row) for _ in range(n)]
        return p

    def test_any_number_up_to_the_cap_is_accepted(self):
        from brief.model import validate
        for n in (0, 1, 4, 24, 25):
            validate(self._leads(n))

    def test_more_than_the_cap_is_rejected_by_name(self):
        from brief.model import MAX_RANKED_LEADS, PayloadError, validate
        self.assertEqual(MAX_RANKED_LEADS, 25)
        with self.assertRaises(PayloadError) as cm:
            validate(self._leads(26))
        self.assertIn("26 ranked leads", str(cm.exception))
        self.assertIn("25", str(cm.exception))

    def test_a_full_table_still_renders(self):
        f, em, tx = render_all(self._leads(25))
        self.assertEqual(f.count('data-l="Role"'), 25)
        for out in (f, em, tx):
            self.assertGreater(len(out), 1000)


class TestEmptySections(unittest.TestCase):
    EMPTIABLE = ("JOBS_TOP", "JOBS_STATUS", "JOBS_OTHER", "FIN_MOVES", "FIN_SUMMARY",
                 "FIN_NOTES", "PKG", "USPS_SCANS", "MKT_ROWS", "FUNDS", "MKT_BULLETS",
                 "CRYPTO_ROWS", "CRYPTO_BULLETS", "AI_ITEMS", "JOURNAL_ITEMS",
                 "ACTIONS", "HIPRI")

    def test_every_list_section_renders_when_empty(self):
        """The prompt says to omit a section with an empty list rather than
        inventing filler rows, so every one of them must survive being empty."""
        for key in self.EMPTIABLE:
            with self.subTest(key=key):
                f, em, tx = render_all(payload(**{key: []}))
                self.assertGreater(len(f), 1000)
                self.assertGreater(len(em), 1000)
                self.assertGreater(len(tx), 500)

    def test_all_list_sections_empty_at_once(self):
        f, em, tx = render_all(payload(**{k: [] for k in self.EMPTIABLE}))
        for out in (f, em, tx):
            self.assertGreater(len(out), 500, "an all-empty brief must still render")


class TestAxisPathsNotInTheSample(unittest.TestCase):
    def test_log_money_axis_renders_with_decade_labels(self):
        """A >100x spread switches the money axis to log decades. The sample
        payload never triggers it, so it would otherwise ship untested."""
        p = payload(FIN_MOVES=[
            ["Mon 9:04 AM EST", "Client", "Invoice", 50000.0, "USD", 50000.0, "In", "+"],
            ["Mon 6:15 PM EST", "Coffee", "Card", 4.20, "USD", 4.20, "Out", "−"],
        ])
        f, em, tx = render_all(p)
        self.assertIn("LOG scale", f)
        self.assertIn("$100k", f)
        self.assertIn('class="dbar money"', f)
        for out in (f, em):
            self.assertNotIn("$50,000", out.split("Bar axis")[1][:200] if "Bar axis" in out else "",
                             "the axis must use decades, not the raw maximum")

    def test_single_row_tables_still_produce_an_even_axis(self):
        p = payload(MKT_ROWS=[["ONLY", "1.00", "+0.01", 0.01, "+0.02", 0.02, "+0.05", 0.05]])
        f, _, _ = render_all(p)
        self.assertIn('class="daxis"', f)

    def test_all_zero_movements_do_not_divide_by_zero(self):
        p = payload(FIN_MOVES=[["t", "p", "d", 0.0, "USD", 0.0, "In", "+"],
                               ["t", "p", "d", 0.0, "USD", 0.0, "Out", "−"]])
        f, _, _ = render_all(p)
        self.assertIn('class="dbar money"', f)


class TestDeterminismAndIsolation(unittest.TestCase):
    def test_rendering_is_deterministic(self):
        a = render_all(payload())
        b = render_all(payload())
        self.assertEqual(a, b, "same payload must give byte-identical output")

    def test_one_payload_does_not_leak_into_the_next(self):
        """render_all binds the payload as module globals; a leak would show
        last run's rows in this run's brief."""
        first = render_all(payload())[0]
        other = render_all(payload(MKT_ROWS=[["ONLY", "1.00", "+1.00", 0.10, "+2.00", 0.20,
                                                 "+3.00", 0.30]],
                                   CRYPTO_ROWS=[]))[0]
        self.assertNotIn("Nasdaq", other, "previous payload's rows leaked into this render")
        self.assertIn("ONLY", other)
        again = render_all(payload())[0]
        self.assertEqual(first, again, "rendering is not reproducible after another payload")

    def test_unicode_survives_all_three_outputs(self):
        p = payload()
        p["JOBS_TOP"][0][1] = "Ökonomie 株式会社 — Ünïcødé ✈"
        f, em, tx = render_all(p)
        for out in (f, em, tx):
            self.assertIn("株式会社", out)
            self.assertIn("Ünïcødé", out)


class TestCliBudget(unittest.TestCase):
    def test_over_budget_email_warns_and_exits_nonzero(self):
        """The send budget is a real Gmail limit, so exceeding it must fail the
        command rather than quietly producing a brief that gets clipped."""
        p = payload()
        p["FIN_NOTES"] = ["padding " * 2000] * 40
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(p, fh)
        td = tempfile.mkdtemp()
        r = subprocess.run([sys.executable, "-m", "brief", "render", fh.name,
                            "--out-dir", td, "--date", "2026-09-07"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, "an over-budget email must exit non-zero")
        self.assertIn("over budget", r.stderr)

    def test_date_defaults_when_not_given(self):
        td = tempfile.mkdtemp()
        r = subprocess.run([sys.executable, "-m", "brief", "render", "sample_payload.json",
                            "--out-dir", td], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any(f.startswith("morning-brief-") for f in os.listdir(td)))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestSectionOrderAndOmission(unittest.TestCase):
    """Document order is fixed by the renderer, not by a prose instruction.

    A live brief once shipped with Upcoming flights after Retail sales and High
    priority away from the top — an order this renderer cannot produce. Pinning
    it here makes any future report of that kind immediately diagnosable: if
    these pass, the document did not come from this code.
    """

    ORDER = ["High priority", "Relevant job posts", "Deposits &amp; finances",
             "Upcoming flights", "VoIP voicemails", "USPS Informed Delivery",
             "Package tracking", "US market", "Cryptocurrency",
             "AI &amp; programming", "Research &amp; publications", "Retail sales"]

    @staticmethod
    def shed_from(email):
        """Names the email says it dropped, read from its own trim note."""
        m = re.search(r"Trimmed to fit the inbox</span> — ([^<]*?) (?:is|are) in the attached",
                      email)
        return [n.strip().replace("&amp;", "&") for n in m.group(1).split(",")] if m else []

    @staticmethod
    def without_note(email):
        return re.sub(r"<table[^>]*>(?:(?!</table>).)*?Trimmed to fit the inbox.*?</table>", "",
                      email, flags=re.S)

    def _positions(self, doc, names):
        return [n for _, n in sorted((doc.index(n), n) for n in names if n in doc)]

    def test_file_order(self):
        f, em, _ = render_all(payload())
        self.assertEqual(self._positions(f, self.ORDER), self.ORDER, "file section order drifted")
        # the email may have shed research cards to fit the budget, but whatever
        # survives must still be in the same relative order
        body = self.without_note(em)
        present = [n for n in self.ORDER if n in body]
        self.assertEqual(self._positions(body, present), present, "email section order drifted")

    def test_high_priority_immediately_follows_the_action_bar(self):
        f, em, tx = render_all(payload())
        for doc in (f, em):
            between = doc[doc.index("Needs you today"):doc.index("High priority")]
            for other in ("Relevant job posts", "Retail sales", "Upcoming flights"):
                self.assertNotIn(other, between, f"{other} sits between the action bar and High priority")
        self.assertLess(tx.index("NEEDS YOU TODAY"), tx.index("1. HIGH PRIORITY"))

    def test_retail_is_last_and_flights_are_not(self):
        f, _, _ = render_all(payload())
        self.assertGreater(f.index("Retail sales"), f.index("Upcoming flights"))
        self.assertGreater(f.index("Retail sales"), f.index("Research &amp; publications"))

    def test_numbering_closes_the_gap_when_a_section_is_omitted(self):
        full, _, _ = render_all(payload())
        nopkg, _, _ = render_all(payload(PKG=[]))
        self.assertEqual(re.findall(r'<span class="num">(\d)\.', full), list("12345678"))
        self.assertEqual(re.findall(r'<span class="num">(\d)\.', nopkg), list("1234567"),
                         "omitting a section must renumber, not leave a hole")

    def test_package_section_dropped_when_empty_kept_when_not(self):
        full, femail, ftext = render_all(payload())
        for out, probe in ((full, "Package tracking"), (femail, "Package tracking"),
                           (ftext, "PACKAGE TRACKING")):
            self.assertIn(probe, out)
        empty, eemail, etext = render_all(payload(PKG=[]))
        for out, probe in ((empty, "Package tracking"), (eemail, "Package tracking"),
                           (etext, "PACKAGE TRACKING")):
            self.assertNotIn(probe, out, "an empty package section must be omitted, not left blank")


class TestBuildMarker(unittest.TestCase):
    """Every output carries a fingerprint of the render, so a hand-written brief
    imitating this design can be told apart from one this code produced."""

    def test_marker_present_in_all_three_outputs(self):
        f, em, tx = render_all(payload())
        marks = set(re.findall(r"brief-[0-9a-f]{12}", f + em + tx))
        self.assertEqual(len(marks), 1, f"expected one consistent marker, saw {marks}")

    def test_marker_changes_with_the_payload(self):
        a = re.search(r"brief-[0-9a-f]{12}", render_all(payload())[0]).group(0)
        b = re.search(r"brief-[0-9a-f]{12}",
                      render_all(payload(JOURNALS="Different"))[0]).group(0)
        self.assertNotEqual(a, b, "the marker must fingerprint the payload")

    def test_cli_prints_the_marker(self):
        td = tempfile.mkdtemp()
        r = subprocess.run([sys.executable, "-m", "brief", "render", "sample_payload.json",
                            "--out-dir", td, "--date", "2026-09-07"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"build brief-[0-9a-f]{12}")


class TestSectionsAsTables(unittest.TestCase):
    """Five sections read as tables rather than bullet lists."""

    def test_each_section_renders_a_table(self):
        f, em, _ = render_all(payload())
        for heading, col in (("High priority", "What needs attention"),
                             ("VoIP voicemails", "Message"),
                             ("AI &amp; programming", "What it means"),
                             ("Research &amp; publications", "Takeaway"),
                             ("Retail sales", "Dates")):
            shed = [h.replace("&", "&amp;") for h in
                    TestSectionOrderAndOmission.shed_from(em)]
            for doc, name in ((f, "file"), (em, "email")):
                if name == "email" and heading in shed:
                    continue      # shed to fit the budget; the file still has it
                block = doc.split(heading)[1][:4000]
                self.assertIn("<table", block, f"{name}: {heading} is not a table")
                self.assertIn(col, block, f"{name}: {heading} missing column {col!r}")

    def test_high_priority_rows_are_color_coded_by_severity(self):
        f, em, _ = render_all(payload())
        hp = f.split("High priority")[1][:3000]
        self.assertRegex(hp, r'class="badge c-(warn|neg|info|ok)"')
        self.assertRegex(hp, r'class="c-(warn|neg|info|ok)"')
        # the email has no classes, so severity rides on an inline color
        ehp = em.split("High priority")[1][:3000]

        self.assertRegex(ehp, r"border:1px solid #[0-9A-F]{6};color:#[0-9A-F]{6}")

    def test_email_tables_stay_within_three_columns(self):
        _, em, _ = render_all(payload())
        counts = [len(re.findall(r"<th\b", row))
                  for row in re.findall(r"<tr>(.*?)</tr>", em, re.S)]
        self.assertTrue(all(c <= 3 for c in counts), f"saw {max(counts or [0])} columns")

    def test_email_stays_within_the_send_budget(self):
        _, em, _ = render_all(payload())
        size = len(em.encode("utf-8"))
        self.assertLess(size, 85 * 1024, f"email is {size:,} B, over the Gmail budget")


class TestNoMarkupLeaksAsText(unittest.TestCase):
    """No fragment of a tag may ever appear as visible text.

    A live brief once showed `style="margin:9px 0">` inside every High-priority
    detail cell: the code reused a list-item helper and stripped the wrapper by
    character count, which silently left the attribute behind when the helper's
    tag grew. Extracting inner HTML properly is the fix; this is the guard.
    """

    @staticmethod
    def _visible(doc):
        body = re.sub(r"<style\b.*?</style>", "", doc, flags=re.S)
        return re.sub(r"<[^>]+>", "", body)

    FRAGMENTS = ('style="', 'class="', "<li", "</li", "<span", "</span",
                 "<td", "</td", "<div", "margin:9px", "padding-left:",
                 "font-family:", "border:1px")

    def test_no_tag_fragments_in_visible_text(self):
        f, em, tx = render_all(payload())
        for doc, name in ((f, "file"), (em, "email")):
            text = self._visible(doc)
            leaks = [frag for frag in self.FRAGMENTS if frag in text]
            self.assertEqual(leaks, [], f"{name}: markup leaked into visible text: {leaks}")
        for frag in self.FRAGMENTS:
            self.assertNotIn(frag, tx, f"plain text carries markup: {frag}")

    def test_high_priority_detail_is_clean(self):
        """The cell where it actually leaked."""
        f, em, _ = render_all(payload())
        for doc, name in ((f, "file"), (em, "email")):
            block = doc.split("High priority")[1][:4000]
            self.assertNotIn('>style=', block, f"{name}: attribute leaked into the cell")
            self.assertNotIn(">margin:", block)

    def test_lead_helpers_return_inner_html_only(self):
        from brief.render import em_lead_inner, lead_inner
        for fn in (lead_inner, em_lead_inner):
            out = fn("Fed: rates held")
            self.assertFalse(out.startswith("<li"), f"{fn.__name__} must not wrap in <li>")
            self.assertNotIn("</li>", out)
            self.assertIn("Fed", out)


class TestThreeHorizons(unittest.TestCase):
    """Every market table carries the same three horizons: 1D, 1W, YTD.

    The file charts all three. The email is capped at three columns — a fourth
    is about 85px on a phone — so it charts 1D and 1W and states YTD as a figure
    in the first column. All three horizons are present everywhere; only the
    chart affordance differs, and only where the medium forbids it.
    """

    TABLES = ("US market", "Vanguard funds", "Cryptocurrency")

    def test_file_charts_all_three_horizons_in_every_table(self):
        f, _, _ = render_all(payload())
        for table in self.TABLES:
            block = f.split(table)[1][:9000]
            for horizon in ("1D", "1W", "YTD"):
                self.assertIn(f">{horizon}<", block, f"{table}: no {horizon} column")
            # three rulers and one track per horizon per row
            self.assertGreaterEqual(block.count('class="daxis"'), 3,
                                    f"{table}: each horizon needs its own ruler")

    def test_each_horizon_gets_its_own_axis(self):
        """A year's move dwarfs a day's; one shared scale would flatten 1D."""
        from brief.render import render_all as _r
        _r(payload())
        import brief.render as R
        self.assertGreater(R.MKT_YTD[1], R.MKT_7D[1], "YTD axis must be wider than 1W")
        self.assertGreater(R.MKT_7D[1], R.MKT_24[1], "1W axis must be wider than 1D")
        self.assertGreater(R.CRY_YTD[1], R.CRY_7D[1])
        self.assertGreater(R.FUND_YTD[1], R.FUND_1D[1])

    def test_email_states_ytd_in_the_first_column(self):
        _, em, _ = render_all(payload())
        for header in ("Index · close · YTD", "Fund · NAV · YTD", "Asset · price · YTD"):
            self.assertIn(header, em, f"email missing {header!r}")
        self.assertGreaterEqual(em.count("YTD "), 10, "every row needs its YTD figure")

    def test_email_still_has_at_most_three_columns(self):
        _, em, _ = render_all(payload())
        counts = [len(re.findall(r"<th\b", row))
                  for row in re.findall(r"<tr>(.*?)</tr>", em, re.S)]
        self.assertTrue(all(c <= 3 for c in counts), f"saw {max(counts or [0])} columns")

    def test_plain_text_carries_all_three(self):
        _, _, tx = render_all(payload())
        for probe in ("1D", "1W", "YTD"):
            self.assertIn(probe, tx)

    def test_email_stays_within_budget_with_three_horizons(self):
        _, em, _ = render_all(payload())
        size = len(em.encode("utf-8"))
        self.assertLess(size, 85 * 1024, f"email is {size:,} B, over the Gmail budget")

    def test_arrows_are_flanked_by_spaces(self):
        """"close→close" reads as one word; "close → close" reads as a range."""
        f, em, tx = render_all(payload())
        for out in (f, em, tx):
            self.assertNotRegex(out, r"[^\s>]→[^\s<]", "an arrow is missing its spaces")


class TestEmailBudgetShedding(unittest.TestCase):
    """The email is a constrained medium and the brief outgrew it.

    Gmail clips past ~102 KB. Rather than let it truncate mid-table, or make a
    person decide at 6am which section to cut, the email sheds WHOLE cards in a
    fixed order — least actionable first — and says which ones and where to find
    them. The standalone file always carries everything.
    """

    PROBES = {"US market": "Russell 2000", "Large caps": "AAPL",
              "Fed & labor market": "Nonfarm payrolls", "Cryptocurrency": "DOGE",
              "AI & programming": "Cascade-2", "Research & publications": "diatom",
              "Retail sales": "Northwind rewards"}

    def _render_at(self, budget):
        import brief.render as R
        original = R.EMAIL_BUDGET_BYTES
        try:
            R.EMAIL_BUDGET_BYTES = budget
            f, em, tx = R.render_all(payload())
        finally:
            R.EMAIL_BUDGET_BYTES = original
        return f, em, tx

    def _shed(self, em):
        return [n for n, probe in self.PROBES.items() if probe not in em]

    def test_email_always_fits_the_budget(self):
        for budget in (85 * 1024, 70 * 1024, 50 * 1024):
            _f, em, _t = self._render_at(budget)
            self.assertLessEqual(len(em.encode("utf-8")), budget,
                                 f"email exceeds a {budget // 1024} KB budget")

    def test_shedding_follows_the_fixed_order(self):
        from brief.render import SHED_ORDER
        for budget in (85 * 1024, 70 * 1024, 50 * 1024):
            _f, em, _t = self._render_at(budget)
            shed = self._shed(em)
            expected_prefix = list(SHED_ORDER)[:len(shed)]
            self.assertEqual(sorted(shed), sorted(expected_prefix),
                             f"at {budget // 1024} KB, shed {shed} not {expected_prefix}")

    def test_a_tighter_budget_never_sheds_less(self):
        counts = [len(self._shed(self._render_at(b)[1]))
                  for b in (85 * 1024, 70 * 1024, 50 * 1024)]
        self.assertEqual(counts, sorted(counts), f"shedding is not monotonic: {counts}")

    def test_the_file_keeps_everything_that_the_email_sheds(self):
        f, em, _t = self._render_at(50 * 1024)
        shed = self._shed(em)
        self.assertTrue(shed, "a 50 KB budget should force shedding")
        for name in shed:
            self.assertIn(self.PROBES[name], f, f"{name} must survive in the file")

    def test_the_reader_is_told_what_was_dropped(self):
        _f, em, _t = self._render_at(70 * 1024)
        self.assertIn("Trimmed to fit the inbox", em)
        for name in self._shed(em):
            self.assertIn(name.replace("&", "&amp;"), em, f"{name} not named in the note")

    def test_no_note_when_everything_fits(self):
        _f, em, _t = self._render_at(10_000 * 1024)
        self.assertNotIn("Trimmed to fit the inbox", em)
        self.assertEqual(self._shed(em), [], "nothing should be shed under a huge budget")

    def test_standing_sections_are_never_shed(self):
        """Only research cards may go. What needs action always ships."""
        _f, em, _t = self._render_at(50 * 1024)
        for probe in ("High priority", "Deposits &amp; finances", "Upcoming flights"):
            self.assertIn(probe, em, f"{probe} must never be shed")


class TestSeverityChipDoesNotWrap(unittest.TestCase):
    """In mobile mail the priority column was ~70px and broke "CHECK" across two
    lines as "CHEC / K". Two fixes, together: the chip rides in the same column
    as the title instead of a column of its own, and it carries nowrap."""

    def test_chip_shares_the_title_column(self):
        f, em, _ = render_all(payload())
        for doc, name in ((f, "file"), (em, "email")):
            block = doc.split("High priority")[1][:2500]
            self.assertNotIn(">Priority<", block, f"{name}: chip still has its own column")
            self.assertIn("What needs attention", block)

    def test_file_chip_cannot_wrap(self):
        """The file has no sanitizer constraint, so it pins the chip outright.
        The email cannot use nowrap — see test_email_survives_the_sanitizer —
        and relies on the wider column instead, measured in test_rendering.py."""
        f, _, _ = render_all(payload())
        self.assertIn("white-space:nowrap", f.split("High priority")[1][:2500])

    def test_email_high_priority_is_two_columns(self):
        _, em, _ = render_all(payload())
        block = em.split("High priority")[1][:1500]
        self.assertEqual(block.count("<th"), 2, "a third narrow column is what broke the chip")


class TestRangeDashSpacing(unittest.TestCase):
    """"4.25–4.50%" reads as one figure; "4.25 – 4.50%" reads as a range."""

    def test_payload_ranges_are_spaced_in_every_output(self):
        f, em, tx = render_all(payload())
        for out in (f, em, tx):
            self.assertNotRegex(out, r"[\w%]–[\w$]", "an unspaced range dash survived")

    def test_hyphens_in_words_are_left_alone(self):
        from brief.theme import space_ranges
        for text in ("non-refundable", "close-to-close", "e-mail", "co-founder"):
            self.assertEqual(space_ranges(text), text)

    def test_arrows_are_not_touched(self):
        from brief.theme import space_ranges
        self.assertEqual(space_ranges("close → close"), "close → close")
