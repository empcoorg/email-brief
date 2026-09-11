"""Unit tests for the renderer itself: escaping, link safety, direction
colouring, empty sections, determinism, and the paths the sample payload
never exercises (log money axis, unrecognised direction words).

The brief renders content that arrived by email. That content is DATA — the
prompt says so — and these tests are where that promise is enforced against
the markup, rather than asserted in prose.
"""
import copy
import json
import os
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
        p["JOBS_TOP"][0][5] = 'https://x.test/" onmouseover="alert(1)'
        p["USPS_SCANS"][0][0] = 'data:image/jpeg;base64,AAA" onload="alert(1)'
        f, em, _ = render_all(p)
        for out in (f, em):
            self.assertNotIn('onmouseover="alert(1)"', out)
            self.assertNotIn('onload="alert(1)"', out)
            # the quote must survive as an escaped entity inside the href, not
            # as a real quote that ends the attribute
            self.assertIn("&quot;", out)


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
            self.assertEqual(cls, "neu", f"{unknown!r} must not be coloured as income")

    def test_unclassified_renders_with_the_neutral_fill(self):
        p = payload()
        p["FIN_MOVES"] = [["Mon 9:04 AM EST", "Someone", "Unclear origin",
                           1200.0, "USD", "Unclassified", "±"]]
        f, _, _ = render_all(p)
        self.assertIn("fill neu", f)
        self.assertNotIn("fill pos", f.split("Deposits &amp; finances")[1].split("</section>")[0])


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
            ["Mon 9:04 AM EST", "Client", "Invoice", 50000.0, "USD", "In", "+"],
            ["Mon 6:15 PM EST", "Coffee", "Card", 4.20, "USD", "Out", "−"],
        ])
        f, em, tx = render_all(p)
        self.assertIn("LOG scale", f)
        self.assertIn("$100k", f)
        self.assertIn('class="dbar money"', f)
        for out in (f, em):
            self.assertNotIn("$50,000", out.split("Bar axis")[1][:200] if "Bar axis" in out else "",
                             "the axis must use decades, not the raw maximum")

    def test_single_row_tables_still_produce_an_even_axis(self):
        p = payload(MKT_ROWS=[["ONLY", "1.00", "+0.01", 0.01, "+0.02", 0.02]])
        f, _, _ = render_all(p)
        self.assertIn('class="daxis"', f)

    def test_all_zero_movements_do_not_divide_by_zero(self):
        p = payload(FIN_MOVES=[["t", "p", "d", 0.0, "USD", "In", "+"],
                               ["t", "p", "d", 0.0, "USD", "Out", "−"]])
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
        other = render_all(payload(MKT_ROWS=[["ONLY", "1.00", "+1.00", 0.10, "+2.00", 0.20]],
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
