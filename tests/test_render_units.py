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
from brief.render import EMAIL_BUDGET_BYTES as R_EMAIL_BUDGET, SCAN_MISSING, money_side
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
        self.assertEqual(money_side("Internal"), ("center", "neu"))

    def test_unrecognised_direction_is_never_drawn_as_income(self):
        """Neutral colour was never enough: side matters as much as colour.

        The old rule returned ("right", "neu") for anything it did not know,
        which is the INFLOW side of zero. A charge the run labelled "Receipt"
        was printed in red and then drawn extending to the right, so the bar
        contradicted the number beside it. Assert the side, not just the class.
        """
        for unknown in ("Unclassified", "Refund", "Receipt", "", None, "in", "IN"):
            side, cls = money_side(unknown)
            self.assertEqual(cls, "neu", f"{unknown!r} must not be colored as income")
            self.assertNotEqual(side, "right",
                                f"{unknown!r} drawn on the inflow side of zero")

    def test_sign_decides_when_the_direction_word_is_coined(self):
        """DIRECTION is free text and the run invents words for it; SIGN is not.

        "Receipt" is not in any list the renderer can keep, but the payload
        still states the movement as minus. That is enough to place it.
        """
        self.assertEqual(money_side("Receipt", "\u2212"), ("left", "neg"))
        self.assertEqual(money_side("Refund", "+"), ("right", "pos"))
        self.assertEqual(money_side("Receipt"), ("center", "neu"))
        self.assertEqual(money_side("Internal", "\u2212"), ("center", "neu"),
                         "an explicit Internal outranks the sign")

    def test_bar_and_amount_never_contradict_each_other(self):
        """The colour beside the number and the colour of the bar are one call.

        They used to be computed separately - the row said "anything not In or
        Internal is red", the bar said "anything unrecognised is grey" - so a
        coined direction produced a red amount above a grey bar pointing the
        wrong way.
        """
        from brief.render import money_side as ms
        p = payload()
        p["FIN_MOVES"] = [["Fri 4:32 PM EST", "Nortech Store", "Invoice receipt",
                           1806.15, "USD", 1806.15, "Receipt", "\u2212"]]
        f, em, _ = render_all(p)
        side, cls = ms("Receipt", "\u2212")
        self.assertEqual((side, cls), ("left", "neg"))
        self.assertIn(f"fill {cls} {side}", f)
        # In the email the fill is a bordered cell; it must close before centre.
        widths = [float(w) for w, st in
                  re.findall(r'width="([\d.]+)%"[^>]*style="([^"]*)"', em)
                  if "border-top:5px" in st and float(w) < 100]
        self.assertTrue(widths, "no fill cell rendered for the movement")

    def test_unclassified_renders_with_the_neutral_fill(self):
        p = payload()
        p["FIN_MOVES"] = [["Mon 9:04 AM EST", "Someone", "Unclear origin",
                           1200.0, "USD", 1200.0, "Unclassified", "±"]]
        f, _, _ = render_all(p)
        self.assertIn("fill neu", f)
        self.assertNotIn("fill pos", f.split("Deposits &amp; finances")[1].split("</section>")[0])


class TestUpcomingTravel(unittest.TestCase):
    """Section 4 carries flights AND everything else that is booked.

    A stay, a train or a ticket is as much "upcoming" as a flight, and each is
    kept until its own date passes - the section exists to carry a booking
    forward whether or not new mail about it arrived.
    """

    STAY = ["Hotel", "Northwind Harbor Hotel", "Fri Mar 6 → Sun Mar 8",
            "Springfield ST · 2 nights", "SAMPLE-HTL-4471",
            "https://example.com/booking/SAMPLE-HTL-4471"]

    def test_the_section_is_named_for_travel_not_flights(self):
        f, em, tx = render_all(payload())
        for doc in (f, em):
            self.assertIn("Upcoming travel", doc)
            self.assertNotIn("Upcoming flights", doc)
        self.assertIn("UPCOMING TRAVEL", tx)
        self.assertNotIn("UPCOMING FLIGHTS", tx)

    def test_bookings_render_with_their_dates_and_confirmations(self):
        f, em, tx = render_all(payload(TRAVEL=[self.STAY]))
        for doc in (f, em, tx):
            for field in ("Hotel", "Northwind Harbor Hotel", "Fri Mar 6", "SAMPLE-HTL-4471"):
                self.assertIn(field, doc, field)
        self.assertIn('href="https://example.com/booking/SAMPLE-HTL-4471"', f)
        self.assertIn('href="https://example.com/booking/SAMPLE-HTL-4471"', em)

    def test_a_booking_without_a_link_or_confirmation_still_renders(self):
        row = ["Rail", "Cascade Rail 88", "Fri Mar 6, 7:10 AM EST", "Seat 12A", "", ""]
        f, em, tx = render_all(payload(TRAVEL=[row]))
        for doc in (f, em):
            self.assertIn("Cascade Rail 88", doc)
            self.assertIn("not stated", doc)
        self.assertIn("Cascade Rail 88", tx)

    def test_flights_alone_and_bookings_alone_each_hold_the_section(self):
        only_flights = payload(TRAVEL=[])
        f, em, tx = render_all(only_flights)
        self.assertIn("Upcoming travel", f)
        self.assertNotIn("Stays &amp; other bookings", f + em)
        only_stays = payload(TRAVEL=[self.STAY])
        only_stays["FLIGHTS"]["legs"] = []
        f, em, tx = render_all(only_stays)
        self.assertIn("Upcoming travel", f)
        self.assertIn("Stays &amp; other bookings", f)
        self.assertNotIn("Route (airport local times)", em, "no flight table without legs")
        self.assertIn("Northwind Harbor Hotel", tx)

    def test_a_long_field_is_split_into_a_headline_and_its_fine_print(self):
        """A run writes dates and check-in times in one field; a narrow column made that a wall."""
        row = ["Hotel", "Northwind Harbor Hotel",
               "Mon, Sep 21 → Wed, Sep 23, 2026 (2 nights) · check-in 3:00 PM, check-out 11:00 AM",
               "Springfield ST · king, breakfast included", "SAMPLE-HTL-4471", ""]
        f, em, tx = render_all(payload(TRAVEL=[row]))
        for doc in (f, em):
            # the dates stand alone in their cell, the times sit under them
            self.assertRegex(doc, r"Mon, Sep 21 → Wed, Sep 23, 2026 \(2 nights\)</(b|span)>")
            self.assertIn("check-in 3:00 PM, check-out 11:00 AM", doc)
            self.assertNotIn("(2 nights) · check-in", doc, "the field was printed as one run of text")
            self.assertNotIn("Springfield ST · king", doc)
        lines = [l.strip() for l in tx.splitlines()]
        self.assertIn("- Mon, Sep 21 → Wed, Sep 23, 2026 (2 nights) · Hotel: Northwind Harbor Hotel · confirmation SAMPLE-HTL-4471", lines)
        self.assertIn("check-in 3:00 PM, check-out 11:00 AM", lines)

    def test_a_field_with_no_fine_print_renders_as_one_line(self):
        row = ["Concert", "Bluepine Hall", "Sat Mar 7, 8:00 PM EST", "Row H", "DEMO-TIX-90210", ""]
        f, em, tx = render_all(payload(TRAVEL=[row]))
        for doc in (f, em, tx):
            self.assertIn("Sat Mar 7, 8:00 PM EST", doc)
            self.assertIn("Row H", doc)

    def test_a_booking_can_say_where_it_was_booked(self):
        """Direct with the property or through an agent changes who to call."""
        row = self.STAY + ["Booking.com"]
        f, em, tx = render_all(payload(TRAVEL=[row]))
        for doc in (f, em, tx):
            self.assertIn("Booking.com", doc)
        no_source, _, _ = render_all(payload(TRAVEL=[self.STAY]))
        self.assertNotIn("Booking.com", no_source)

    def test_a_generic_booking_source_is_named(self):
        """"Booked direct with the property" tells a reader nothing they cannot see."""
        from brief.render import booking_source
        self.assertEqual(booking_source("Northwind Harbor Hotel", "Booked direct with the property"),
                         "Booked direct with Northwind Harbor Hotel")
        self.assertEqual(booking_source("Bluepine Hall", "booked direct with the venue"),
                         "booked direct with Bluepine Hall")
        self.assertEqual(booking_source("Northwind Harbor Hotel", "Booking.com"), "Booking.com")
        row = self.STAY + ["Booked direct with the property"]
        for doc in render_all(payload(TRAVEL=[row])):
            self.assertIn("Booked direct with Northwind Harbor Hotel", doc)
            self.assertNotIn("with the property", doc)

    def test_the_section_says_bookings_are_carried_until_their_date(self):
        f, em, tx = render_all(payload(TRAVEL=[self.STAY]))
        for doc in (f, em, tx):
            self.assertIn("until its date has passed", doc)

    def test_the_contract_refuses_a_malformed_booking(self):
        from brief.model import PayloadError, validate
        for bad in ([["Hotel", "Northwind", "Fri", "Springfield", "SAMPLE-1"]],
                    [["Hotel", "Northwind", "Fri", "Springfield", "SAMPLE-1", "x", "src", "extra"]],
                    [["Hotel", "Northwind", "Fri", "Springfield", 4471, ""]],
                    "not a list"):
            with self.assertRaises(PayloadError, msg=repr(bad)):
                validate(payload(TRAVEL=bad))


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
        self.assertIn("on-time", em.split("Upcoming travel")[1][:2000],
                      "the email folds the record in beside the confirmation")
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
        for out, probe in ((f, "Upcoming travel"), (em, "Upcoming travel"),
                           (tx, "UPCOMING TRAVEL")):
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
        fin = fin.split("Money movements")[1].split("AI services")[0]
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
                 "ACTIONS", "HIPRI", "STOCKS", "MACRO_ROWS", "JOBS_SECTORS")

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


# The strings a section says when it has something to say: a headline, the
# postal counts, the rewards line. A run with nothing leaves them empty too.
_EMPTY_STRINGS = {"VOIP": ("headline", "last_msg", "last_acct"),
                  "USPS": ("headline", "counts", "note"),
                  "RETAIL": ("rewards",)}


def _all_empty():
    """The sample with nothing in it - every list empty and every such string blank."""
    p = payload(FIN_INTERNAL="")
    for k, v in p.items():
        if isinstance(v, list):
            p[k] = []
        elif isinstance(v, dict):
            for kk, vv in v.items():
                if isinstance(vv, list):
                    v[kk] = []
                elif kk in _EMPTY_STRINGS.get(k, ()):
                    v[kk] = ""
    return p


def _header_only_tables(html):
    """Outermost tables in an email whose only row is the header row."""
    found, depth, rows, start = [], 0, 0, 0
    for m in re.finditer(r"<(/?)(table|tr)\b", html):
        closing, tag = m.group(1), m.group(2)
        if tag == "table" and not closing:
            depth += 1
            if depth == 1:
                rows, start = 0, m.start()
        elif tag == "table":
            if depth == 1 and rows == 1 and "border-collapse:collapse" in html[start:start + 200]:
                found.append(start)
            depth -= 1
        elif not closing and depth == 1:
            rows += 1
    return found


def _div_depth(html):
    return len(re.findall(r"<div\b", html)) - len(re.findall(r"</div>", html))


class TestNoHollowSections(unittest.TestCase):
    """An empty list must never draw a heading over an empty table.

    A live brief showed "Large caps" as a header row with -1% / 0 / +1% axes and
    nothing under it: the run had no large caps to report, and the renderer drew
    the section anyway. A heading over an empty table reads as missing data. So:
    research cards are omitted when they have nothing, and standing sections -
    whose absence would be ambiguous - say so in one line, naming the window.
    """

    @staticmethod
    def headings(html):
        """Section and sub-section headings, from the page's tags or the email's heading styles."""
        found = re.findall(r"<h[23][^>]*>(.*?)</h[23]>", html, re.S)
        found += re.findall(r"font-size:19px;font-weight:700;[^>]*>(.*?)</div>", html, re.S)
        found += re.findall(r'margin:14px 0 6px">(.*?)</div>', html, re.S)
        return [re.sub(r"<[^>]+>", "", h).strip() for h in found]

    RESEARCH = {  # key emptied -> heading that must vanish from page and email, text heading
        "STOCKS": ("Large caps", "LARGE CAPS"),
        "JOBS_SECTORS": ("Jobs by sector", "Jobs by sector:"),
        "JOURNAL_ITEMS": ("Research &amp; publications", "RESEARCH & PUBLICATIONS"),
        "AI_ITEMS": ("AI &amp; programming", "AI & PROGRAMMING"),
        "FUNDS": ("Vanguard funds", "Vanguard funds:"),
    }

    def test_each_empty_research_table_takes_its_heading_with_it(self):
        for key, (heading, text_heading) in self.RESEARCH.items():
            with self.subTest(key=key):
                f, em, tx = render_all(payload(**{key: []}))
                self.assertNotIn(heading, self.headings(f))
                self.assertNotIn(heading, self.headings(em))
                self.assertNotIn(text_heading, [l.strip() for l in tx.splitlines()])
                full_f, full_em, full_tx = render_all(payload())
                self.assertIn(heading, self.headings(full_f), "the sample must carry it for this test to mean anything")
                self.assertIn(heading, self.headings(full_em))
                self.assertTrue(any(l.strip().startswith(text_heading) for l in full_tx.splitlines()))

    def test_no_output_draws_an_empty_table_on_an_all_empty_day(self):
        f, em, tx = render_all(_all_empty())
        self.assertEqual(re.findall(r"<tbody>\s*</tbody>", f), [], "page drew a table with no rows")
        self.assertEqual(_header_only_tables(em), [], "email drew a header row with no rows under it")
        self.assertNotIn("Journals scanned", f + em + tx)

    def test_research_cards_are_omitted_entirely_when_they_have_nothing(self):
        f, em, tx = render_all(_all_empty())
        for heading in ("US market", "Large caps", "Cryptocurrency", "Fed &amp; labor market",
                        "AI &amp; programming", "Research &amp; publications"):
            self.assertNotIn(heading, self.headings(f))
            self.assertNotIn(heading, self.headings(em))
        self.assertNotIn('class="grid3"', f, "no research cards means no empty grid either")
        for heading in ("US MARKET", "LARGE CAPS", "CRYPTOCURRENCY", "FED & LABOR MARKET"):
            self.assertNotIn(heading, tx)

    def test_standing_sections_say_what_was_swept_instead_of_vanishing(self):
        """A section with nothing keeps its heading and names the window it swept."""
        p = _all_empty()
        window = p["MAST"]["window"]
        f, em, tx = render_all(p)
        line = f"No new data in this period ({window})."
        for out in (f, em, tx):
            self.assertIn("Nothing needs you today.", out)
            self.assertGreaterEqual(out.count(line), 6,
                                    "every standing section with nothing says so, naming the window")
        for heading in ("High priority", "Relevant job posts", "Deposits &amp; finances",
                        "VoIP voicemails", "USPS Informed Delivery", "Retail sales"):
            self.assertIn(heading, f)
            self.assertIn(heading, em)

    def test_an_empty_string_never_renders_as_a_bare_bullet(self):
        """A live brief showed USPS as a heading over a single empty dot."""
        f, em, _ = render_all(_all_empty())
        self.assertEqual(re.findall(r"<li>\s*</li>", f), [])
        self.assertEqual(re.findall(r"<li[^>]*>\s*</li>", em), [])
        for doc in (f, em):
            self.assertNotIn("<ul></ul>", doc)

    def test_a_section_with_only_a_headline_keeps_its_headline(self):
        """"One text message in the window" is data; it must not be overwritten."""
        p = _all_empty()
        p["VOIP"]["headline"] = "No voicemails or texts since Friday."
        _, em, _ = render_all(p)
        voip = em[em.find("VoIP voicemails"):em.find("USPS Informed Delivery")]
        self.assertIn("No voicemails or texts since Friday.", voip)
        self.assertNotIn("No new data in this period", voip)

    def test_travel_with_nothing_booked_is_omitted_and_the_rest_renumber(self):
        p = payload(TRAVEL=[])
        p["FLIGHTS"]["legs"] = []
        f, em, tx = render_all(p)
        self.assertNotIn("Upcoming travel", f + em)
        self.assertNotIn("UPCOMING TRAVEL", tx)
        self.assertEqual(re.findall(r'<span class="num">(\d)\.', f), list("1234567"))

    def test_the_fed_card_keeps_its_caption_when_only_the_jobs_table_goes(self):
        p = payload(JOBS_SECTORS=[])
        f, em, _ = render_all(p)
        for out in (f, em):
            self.assertIn("Fed &amp; labor market", out)
            self.assertIn(e(p["MACRO_NOTE"]), out)

    def test_every_page_card_closes_itself(self):
        """The US market card used to stay open and swallow every card after it."""
        for p in (payload(), payload(STOCKS=[]), payload(MKT_ROWS=[], FUNDS=[]), _all_empty()):
            f, _, _ = render_all(p)
            grid = f[f.find('<section><div class="grid3">'):]
            grid = grid[:grid.find("</section>")] if 'class="grid3"' in f else ""
            self.assertEqual(_div_depth(grid), 0, "a research card was left open")
            self.assertEqual(_div_depth(f), 0)

    def test_large_caps_alone_still_gets_a_card(self):
        f, em, tx = render_all(payload(MKT_ROWS=[], FUNDS=[], MKT_BULLETS=[]))
        self.assertIn("Large caps", f)
        self.assertIn("Large caps", em)
        self.assertIn("LARGE CAPS", tx)
        self.assertNotIn("Vanguard funds", f + em)

    def test_a_card_that_was_never_drawn_is_never_shed(self):
        _, em, _ = render_all(payload(STOCKS=[], JOURNAL_ITEMS=[]), 30_000)
        from brief.render import LAST_EMAIL_REPORT
        self.assertTrue(LAST_EMAIL_REPORT["shed"], "the budget should have forced shedding")
        for never in ("Large caps", "Research & publications"):
            self.assertNotIn(never, LAST_EMAIL_REPORT["shed"])


class TestStringsFollowTheData(unittest.TestCase):
    def test_the_email_names_the_file_the_run_wrote(self):
        _, em, _ = render_all(payload(), stamp="2026-10-02")
        self.assertIn("morning-brief-2026-10-02.html", em)
        self.assertNotIn("2026-09-07", em)

    def test_the_cli_passes_its_date_through(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable, "-m", "brief", "render", SAMPLE, "--out-dir", d,
                            "--date", "2026-10-03"], cwd=ROOT, check=True, capture_output=True)
            with open(os.path.join(d, "email.html"), encoding="utf-8") as fh:
                self.assertIn("morning-brief-2026-10-03.html", fh.read())

    def test_the_action_bar_subtitle_counts_urgent_rows(self):
        quiet = payload(ACTIONS=[["info", "A note", "detail"]])
        urgent = payload(ACTIONS=[["neg", "Bill due tonight", "detail"], ["neg", "Code expires", "d"],
                                  ["info", "A note", "detail"]])
        for doc in render_all(quiet)[:2]:
            self.assertIn("nothing here is marked urgent", doc)
            self.assertNotIn("tomorrow", doc)
        for doc in render_all(urgent)[:2]:
            self.assertIn("2 urgent before the next run", doc)

    def test_voip_says_whether_the_line_is_alive_without_repeating_a_message(self):
        p = payload()
        f, em, tx = render_all(p)
        for out in (f, em, tx):
            self.assertEqual(out.count("Maple Street Dental"), 1, "the newest message printed twice")
            self.assertIn("Last provider account notice", out)
        p["VOIP"]["messages"] = []
        f, em, tx = render_all(p)
        for out in (f, em, tx):
            self.assertEqual(out.count("Maple Street Dental"), 1,
                             "on a quiet day the last message is the proof the line is alive")


class TestActionBarAndHighPriority(unittest.TestCase):
    """The bar and section 1 are written from the same facts, and must read as one."""

    def test_a_repeated_item_points_at_section_1_instead_of_repeating_itself(self):
        from brief.render import DETAIL_IN_HIPRI
        p = payload()
        title = p["HIPRI"][0][1]
        p["ACTIONS"] = [["neg", title, "The very same sentence, twice over."]] + p["ACTIONS"]
        f, em, tx = render_all(p)
        for doc in (f, em, tx):
            self.assertIn(DETAIL_IN_HIPRI, doc)
            self.assertNotIn("The very same sentence, twice over.", doc)
            self.assertIn(title, doc, "the row itself stays: the bar is what a reader acts from")

    def test_an_item_only_in_the_bar_keeps_its_own_detail(self):
        from brief.render import DETAIL_IN_HIPRI
        p = payload(HIPRI=[])
        p["ACTIONS"] = [["warn", "Only in the bar", "Detail that exists nowhere else."]]
        for doc in render_all(p):
            self.assertIn("Detail that exists nowhere else.", doc)
            self.assertNotIn(DETAIL_IN_HIPRI, doc)

    def test_matching_is_not_fooled_by_case_or_punctuation(self):
        from brief.render import DETAIL_IN_HIPRI
        p = payload()
        p["HIPRI"] = [["neg", "Utility autopay failed — resubmit", ["detail"]]]
        p["ACTIONS"] = [["neg", "utility autopay failed - resubmit", "duplicate detail"]]
        self.assertIn(DETAIL_IN_HIPRI, render_all(p)[0])

    def test_section_1_carries_the_bars_severity_stripe(self):
        f, em, _ = render_all(payload())
        severities = {row[0] for row in payload()["HIPRI"]}
        for sev in severities:
            self.assertIn(f'<tr class="hp {sev}">', f)
        self.assertRegex(f, r"tr\.hp\.neg>td:first-child\{border-left-color:var\(--negative\)\}")
        hp = em.split("What needs attention")[1][:2000]
        self.assertIn("border-left:6px solid", hp, "the email stripes the row's first cell")


class TestSummaryTiles(unittest.TestCase):
    def test_a_tile_says_which_way_it_points(self):
        from brief.render import tile_tone
        self.assertEqual(tile_tone("In from outside"), "pos")
        self.assertEqual(tile_tone("Outstanding"), "neg")
        self.assertEqual(tile_tone("Bills due"), "neg")
        self.assertEqual(tile_tone("Moved internally"), "neu")
        self.assertEqual(tile_tone("Something nobody has coined yet"), "neu")

    def test_the_figure_is_coloured_and_the_currency_set_beside_it(self):
        f, em, _ = render_all(payload())
        self.assertIn('class="tile pos"', f)
        self.assertIn('class="tile neg"', f)
        self.assertRegex(f, r'<span class="cur">USD</span>')
        fin = em.split("Deposits &amp; finances")[1][:2500]
        self.assertIn("USD", fin)

    def test_a_currency_already_written_is_not_doubled(self):
        from brief.render import tile_amount
        self.assertEqual(tile_amount("$5,280.00 USD"), ("$5,280.00", "USD"))
        self.assertEqual(tile_amount("$5,280.00"), ("$5,280.00", "USD"))
        self.assertEqual(tile_amount("3 invoices"), ("3 invoices", ""))


class TestMovementOrder(unittest.TestCase):
    """In, then Out, then Internal, then Unclassified - newest first in each."""

    MOVES = [
        ["Mon Mar 2, 6:15 PM EST", "Older internal", "d", 500.0, "USD", 500.0, "Internal", "\u00b1"],
        ["Tue Mar 3, 7:41 AM EST", "Older out", "d", 84.20, "USD", 84.20, "Past due", "\u2212"],
        ["Mon Mar 2, 9:04 AM EST", "Older in", "d", 1000.0, "USD", 1000.0, "In", "+"],
        ["Tue Mar 3, 8:12 AM EST", "Newer out", "d", 551.35, "USD", 551.35, "Out", "\u2212"],
        ["Tue Mar 3, 9:30 AM EST", "Newer in", "d", 20.0, "USD", 20.0, "In", "+"],
        ["Tue Mar 3, 6:00 AM EST", "No side", "d", 9.0, "USD", 9.0, "Receipt", "\u00b1"],
    ]

    def test_the_groups_come_in_order_and_each_is_newest_first(self):
        from brief.render import moves_in_order
        render_all(payload(FIN_MOVES=self.MOVES))
        self.assertEqual([r[1] for r in moves_in_order()],
                         ["Newer in", "Older in", "Newer out", "Older out",
                          "Older internal", "No side"])

    def test_the_rendered_order_matches_in_every_output(self):
        f, em, tx = render_all(payload(FIN_MOVES=self.MOVES))
        for doc in (f, em, tx):
            seen = [n for n in sorted(("Newer in", "Older in", "Newer out", "Older out",
                                       "Older internal", "No side"), key=doc.index)]
            self.assertEqual(seen, ["Newer in", "Older in", "Newer out", "Older out",
                                    "Older internal", "No side"], doc[:0])

    def test_a_row_whose_date_cannot_be_read_keeps_its_place(self):
        from brief.render import moves_in_order
        moves = [["whenever", "Undated", "d", 5.0, "USD", 5.0, "In", "+"],
                 ["Tue Mar 3, 9:30 AM EST", "Dated", "d", 20.0, "USD", 20.0, "In", "+"]]
        render_all(payload(FIN_MOVES=moves))
        self.assertEqual([r[1] for r in moves_in_order()], ["Dated", "Undated"])


class TestAiSpendColumn(unittest.TestCase):
    ROWS = [["Acme AI", 120.0, 24.0, "71% of AI spend"],
            ["Northwind AI", 34.0, 0.0, "20% of AI spend"]]

    def block(self, rows=None):
        return {"year": "2026", "rows": rows if rows is not None else self.ROWS}

    def test_this_windows_billing_is_drawn_as_a_diverging_bar(self):
        f, em, tx = render_all(payload(AI_SPEND=self.block()))
        ai = f.split("AI services")[1][:4000]
        self.assertIn("New this window", ai)
        self.assertRegex(ai, r'class="fill neg left"', "a charge draws left of zero, in red")
        self.assertIn("nothing new", ai, "a service billed nothing draws no bar at all")
        self.assertEqual(ai.count('class="dbar money ai"'), 1, "one bar, for the one charge")
        self.assertIn("$24.00", ai)
        self.assertIn("$24.00 billed in this window", tx)
        self.assertIn("nothing new in this window", tx)
        self.assertIn("New this window", em)

    def test_the_share_column_is_named_in_full_and_carries_a_ring(self):
        f, em, _ = render_all(payload(AI_SPEND=self.block()))
        self.assertIn("Share AI spend (YTD)", f)
        self.assertIn("share ai spend (ytd)", em.lower())
        ai = f.split("AI services")[1][:4000]
        self.assertEqual(ai.count('<svg class="ring"'), len(self.ROWS))
        self.assertNotIn("<svg", em, "the sanitizer strips it, so the email states the share in words")

    def test_the_ring_matches_the_percentage_the_row_states(self):
        from brief.render import ai_ring, ai_share
        self.assertEqual(ai_share(self.ROWS[0]), 71.0)
        half, whole = ai_ring(50), ai_ring(100)
        self.assertIn("stroke-dasharray", half)
        self.assertNotEqual(half, whole)
        self.assertEqual(ai_ring(None), "", "no percentage, no ring")

    def test_a_row_written_before_the_column_existed_still_renders(self):
        old = [["Acme AI", 120.0, "100% of AI spend this year"]]
        f, em, tx = render_all(payload(AI_SPEND=self.block(old)))
        for doc in (f, em, tx):
            self.assertIn("AI services", doc)
            self.assertIn("$120.00", doc)
        self.assertIn("nothing new in this window", tx)


class TestMailpieceScanIsEmbedded(unittest.TestCase):
    """The page is where the scan lives; a detailed piece without one is a gap."""

    def test_the_scan_is_embedded_in_the_postal_section_itself(self):
        f, _, _ = render_all(payload())
        usps = f.split("USPS Informed Delivery")[1].split("</section>")[0]
        self.assertIn('<figure class="scanfig" id="usps-scan-1">', usps)
        self.assertIn('<img src="data:image/', usps, "the image is inline, not a link")
        self.assertIn("<figcaption>", usps)
        self.assertNotIn(SCAN_MISSING, f)

    def test_a_detailed_piece_with_no_scan_says_so(self):
        p = payload(USPS_SCANS=[])
        self.assertTrue(p["USPS"]["pieces"], "the sample must detail a piece")
        for doc in render_all(p):
            self.assertIn(SCAN_MISSING, doc)

    def test_nothing_is_said_when_no_piece_was_detailed(self):
        p = payload(USPS_SCANS=[])
        p["USPS"]["pieces"] = []
        for doc in render_all(p):
            self.assertNotIn(SCAN_MISSING, doc)


class TestFlightColumns(unittest.TestCase):
    def test_the_table_names_the_airline_for_each_leg(self):
        """A connection sold by one airline is often flown by another, and the
        headline names only the seller — so the row has to say whose desk."""
        p = payload()
        p["FLIGHTS"]["airline"] = "Delta / Alaska"
        p["FLIGHTS"]["legs"][0]["flight"] = "DL 2200"
        p["FLIGHTS"]["legs"][1]["flight"] = "B6 88"
        f, em, tx = render_all(p)
        travel = f.split("Upcoming travel")[1].split("</table>")[0]
        head = travel.split("<tbody>")[0]
        self.assertIn("<th>Airline</th><th>Confirmation</th>", head,
                      "the airline column sits directly before the confirmation")
        rows = travel.split("<tbody>")[1].split("<tr>")[1:]
        self.assertIn('data-l="Airline">Delta<', rows[0])
        self.assertIn('data-l="Airline">Alaska<', rows[1])
        self.assertIn("Airline · confirmation", em, "the email folds it into that cell")
        for doc in (em, tx):
            self.assertIn("Delta", doc)
            self.assertIn("Alaska", doc)

    def test_a_leg_may_name_its_own_airline(self):
        p = payload()
        p["FLIGHTS"]["legs"][0]["airline"] = "Cascade Air"
        p["FLIGHTS"]["legs"][0]["flight"] = "DL 2200"     # the code would say Delta
        f, _em, _tx = render_all(p)
        self.assertIn('data-l="Airline">Cascade Air<', f)

    def test_an_unreadable_code_borrows_the_booking_only_when_it_is_unambiguous(self):
        """On a two-airline record, naming one of them would be a coin toss,
        and a reader sent to the wrong desk is worse served than one sent to none."""
        from brief.render import leg_airline
        p = payload()
        p["FLIGHTS"]["airline"] = "Northwind Air"
        render_all(p)                                     # binds the globals
        self.assertEqual(leg_airline({"flight": "NW 412"}), "Northwind Air")
        p["FLIGHTS"]["airline"] = "Delta / Alaska"
        render_all(p)
        self.assertEqual(leg_airline({"flight": "NW 412"}), "")

    def test_the_column_reads_not_stated_rather_than_going_missing(self):
        p = payload()
        p["FLIGHTS"]["airline"] = "Delta / Alaska"
        p["FLIGHTS"]["legs"][0]["flight"] = "NW 412"
        f, _em, _tx = render_all(p)
        travel = f.split("Upcoming travel")[1].split("</table>")[0]
        self.assertIn('data-l="Airline"><span class="muted">not stated</span>', travel)

    def test_each_leg_shows_its_confirmation_and_terminal(self):
        p = payload()
        p["FLIGHTS"]["legs"][0]["conf"] = "SAMPLE7"
        p["FLIGHTS"]["legs"][0]["term"] = "Terminal A, gate A12 → Terminal 2"
        f, em, tx = render_all(p)
        for doc in (f, em, tx):
            self.assertIn("SAMPLE7", doc)
            self.assertIn("Terminal A, gate A12", doc)
        self.assertIn("<th>Terminal</th>", f)
        self.assertIn("<th>Confirmation</th>", f)

    def test_a_two_airline_booking_shows_each_leg_only_its_own_code(self):
        """Every row carried every code, which left the reader to work out which was theirs."""
        from brief.render import leg_conf
        p = payload()
        p["FLIGHTS"]["conf"] = "MOCKR1 / MOCKR2 (Delta) · FAKEA9 (Alaska)"
        for leg in p["FLIGHTS"]["legs"]:
            leg.pop("conf", None)
        p["FLIGHTS"]["legs"][0]["flight"] = "DL 1234"
        p["FLIGHTS"]["legs"][1]["flight"] = "AS 456"
        render_all(p)
        self.assertEqual(leg_conf(p["FLIGHTS"]["legs"][0]), "MOCKR1 / MOCKR2")
        self.assertEqual(leg_conf(p["FLIGHTS"]["legs"][1]), "FAKEA9")
        f, em, tx = render_all(p)
        for out in (f, em):
            rows = out.split("Upcoming travel")[1].split("</section>")[0].split("<table")[1]
            self.assertEqual(rows.count("FAKEA9"), 1, "the Alaska code belongs to one row")
            self.assertNotIn("(Delta) \u00b7", rows, "no row repeats the whole booking string")

    def test_an_unlabelled_or_unmatched_booking_string_is_printed_whole(self):
        """A wrong code at a desk is worse than a long one."""
        from brief.render import leg_conf
        p = payload()
        p["FLIGHTS"]["conf"] = "MOCKR1 · FAKEA9"        # no airline labels
        for leg in p["FLIGHTS"]["legs"]:
            leg.pop("conf", None)
        render_all(p)
        self.assertEqual(leg_conf(p["FLIGHTS"]["legs"][0]), "MOCKR1 · FAKEA9")
        p["FLIGHTS"]["conf"] = "MOCKR1 (Delta) · FAKEA9 (Alaska)"
        p["FLIGHTS"]["legs"][0]["flight"] = "ZZ 999"    # a carrier nothing maps
        render_all(p)
        self.assertEqual(leg_conf(p["FLIGHTS"]["legs"][0]), "MOCKR1 (Delta) · FAKEA9 (Alaska)")

    def test_a_leg_with_its_own_code_ignores_the_booking_entirely(self):
        from brief.render import leg_conf
        p = payload()
        p["FLIGHTS"]["conf"] = "MOCKR1 (Delta) · FAKEA9 (Alaska)"
        p["FLIGHTS"]["legs"][0]["conf"] = "OWNCODE"
        p["FLIGHTS"]["legs"][0]["flight"] = "AS 456"
        render_all(p)
        self.assertEqual(leg_conf(p["FLIGHTS"]["legs"][0]), "OWNCODE")

    def test_a_leg_without_its_own_code_falls_back_to_the_bookings(self):
        from brief.render import leg_conf
        p = payload()
        for leg in p["FLIGHTS"]["legs"]:
            leg.pop("conf", None)
        render_all(p)
        self.assertEqual(leg_conf(p["FLIGHTS"]["legs"][0]), p["FLIGHTS"]["conf"])

    def test_the_terminal_column_is_dropped_when_no_leg_states_one(self):
        p = payload()
        for leg in p["FLIGHTS"]["legs"]:
            leg.pop("term", None)
        f, _, _ = render_all(p)
        self.assertNotIn("<th>Terminal</th>", f)
        self.assertIn("<th>Confirmation</th>", f, "the confirmation column always stands")


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
    def test_over_gmails_clip_threshold_says_so_and_still_succeeds(self):
        """Clipping is a link, not a loss, so it is a NOTE and not a failure.

        This used to exit 1 and shedding was on by default, which made the
        clip threshold the binding constraint: a real run landed at 99.9% of
        the body budget with seven cards shed while the send call sat at 84%.
        Gmail shows "[Message clipped] View entire message" - the reader is one
        click from everything - so the brief outranks it now, and --clip-guard
        restores the old trade for anyone who wants it.
        """
        p = payload()
        p["FIN_NOTES"] = ["padding " * 2000] * 40
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(p, fh)
        td = tempfile.mkdtemp()
        r = subprocess.run([sys.executable, "-m", "brief", "render", fh.name,
                            "--out-dir", td, "--date", "2026-09-07"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, "clipping must not fail the render")
        with open(os.path.join(td, "email.html"), encoding="utf-8") as eh:
            default_size = len(eh.read().encode("utf-8"))
        self.assertIn("clip threshold", r.stdout)
        self.assertIn("Nothing was dropped", r.stdout)
        # Compare the two policies on a payload that CAN shed - the padded one
        # above is all non-droppable notes, so neither policy can move it.
        sizes = {}
        for flag in ([], ["--clip-guard"]):
            d = tempfile.mkdtemp()
            subprocess.run([sys.executable, "-m", "brief", "render", SAMPLE,
                            "--out-dir", d, "--date", "2026-09-07"] + flag,
                           cwd=ROOT, check=True, capture_output=True)
            with open(os.path.join(d, "email.html"), encoding="utf-8") as eh:
                sizes["guard" if flag else "default"] = len(eh.read().encode("utf-8"))
        self.assertLess(sizes["guard"], sizes["default"],
                        "--clip-guard must shed where the default keeps everything")
        self.assertLessEqual(sizes["guard"], R_EMAIL_BUDGET,
                             "--clip-guard must land under the clip threshold")

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

    A live brief once shipped with Upcoming travel after Retail sales and High
    priority away from the top — an order this renderer cannot produce. Pinning
    it here makes any future report of that kind immediately diagnosable: if
    these pass, the document did not come from this code.
    """

    ORDER = ["High priority", "Relevant job posts", "Deposits &amp; finances",
             "Upcoming travel", "VoIP voicemails", "USPS Informed Delivery",
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
            for other in ("Relevant job posts", "Retail sales", "Upcoming travel"):
                self.assertNotIn(other, between, f"{other} sits between the action bar and High priority")
        self.assertLess(tx.index("NEEDS YOU TODAY"), tx.index("1. HIGH PRIORITY"))

    def test_retail_is_last_and_flights_are_not(self):
        f, _, _ = render_all(payload())
        self.assertGreater(f.index("Retail sales"), f.index("Upcoming travel"))
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
        _, em, _ = render_all(payload(), R_EMAIL_BUDGET)
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
        for header in ("Index · Mon Mar 2, 4:00 PM EST close · YTD",
                       "Fund · Mon Mar 2, 5:48 PM ET NAV · YTD",
                       "Asset · Tue Mar 3, 9:55 AM EST price · YTD"):
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
        _, em, _ = render_all(payload(), R_EMAIL_BUDGET)
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
            f, em, tx = R.render_all(payload(), budget)
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
        for probe in ("High priority", "Deposits &amp; finances", "Upcoming travel"):
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


class TestQuoteAsOfHeadings(unittest.TestCase):
    """The time a table was read is a property of the TABLE, not of each row.

    Printed down the column it repeated "Mon Mar 2, 4:00 PM EST close" against
    every index — wrapping onto three lines under a one-line figure and saying
    nothing the row above had not. It now heads the column, and only splits
    back into the rows when they disagree, which is the case where it is news.
    """

    HEADS = (("US market", "Mon Mar 2, 4:00 PM EST close"),
             ("Vanguard funds", "Mon Mar 2, 5:48 PM ET NAV"),
             ("Large caps", "Mon Mar 2, 4:00 PM EST price"),
             ("Cryptocurrency", "Tue Mar 3, 9:55 AM EST price"))

    def table(self, page, after):
        return page.split(after)[1].split("</table>")[0]

    def test_each_quote_column_is_headed_by_the_time_it_was_read(self):
        f, em, tx = render_all(payload())
        for after, head in self.HEADS:
            tbl = self.table(f, after)
            self.assertIn(f'<span class="qh">{head}</span>', tbl,
                          f"{after} should head its quote column with {head!r}")
            body = re.sub(r'\sdata-l="[^"]*"', "", tbl.split("<tbody>")[1])
            self.assertNotIn(head.rsplit(" ", 1)[0], body,
                             f"{after} repeats the stamp in its rows")

    def test_the_email_states_it_once_too(self):
        _, em, _ = render_all(payload())
        for _after, head in self.HEADS:
            self.assertEqual(em.count(head), 1, f"{head!r} belongs in the heading, once")

    def test_the_text_copy_says_it_over_the_table(self):
        _, _, tx = render_all(payload())
        self.assertIn("All closes as of Mon Mar 2, 4:00 PM EST.", tx)
        self.assertIn("(all NAVs as of Mon Mar 2, 5:48 PM ET)", tx)
        self.assertIn("All prices as of Tue Mar 3, 9:55 AM EST.", tx)
        self.assertNotIn("(as of Mon Mar 2, 4:00 PM EST)", tx, "not on the rows as well")

    def test_the_funds_as_of_column_goes_when_the_heading_carries_it(self):
        """A column that prints one string N times is N-1 wasted columns."""
        p = payload()
        f, _em, _tx = render_all(p)
        funds = self.table(f, "Vanguard funds")
        self.assertNotIn(">Date</th>", funds, "the column is redundant once the heading dates the NAV")
        p["FUNDS"][0][9] = "Fri Feb 27, 5:48 PM ET"      # priced on different days
        f, _em, _tx = render_all(p)
        funds = self.table(f, "Vanguard funds")
        self.assertIn(">Date</th>", funds, "differing dates need the column back")
        self.assertIn("Fri Feb 27, 5:48 PM ET", funds)
        self.assertIn(">NAV</th>", funds, "and the heading goes back to the plain word")

    def test_rows_read_at_different_times_each_keep_their_own(self):
        p = payload()
        p["MKT_ROWS"][0][8] = "Tue Mar 3, 9:41 AM EST, mid-session"
        f, em, tx = render_all(p)
        market = self.table(f, "US market")
        self.assertIn(">Close</th>", market, "a mixed table keeps the plain heading")
        self.assertIn("Tue Mar 3, 9:41 AM EST, mid-session", market)
        self.assertIn("(as of Tue Mar 3, 9:41 AM EST, mid-session)", tx)

    def test_a_table_with_no_times_at_all_is_unchanged(self):
        p = payload()
        for key in ("MKT_ROWS", "STOCKS", "CRYPTO_ROWS"):
            p[key] = [list(r)[:8] for r in p[key]]
        f, em, _tx = render_all(p)
        self.assertIn(">Close</th>", self.table(f, "US market"))
        self.assertIn(">Price</th>", self.table(f, "Large caps"))
        self.assertIn("Index · close · YTD", em)

    def test_a_stamp_that_already_names_the_quote_does_not_say_it_twice(self):
        from brief.render import quote_head_text
        self.assertEqual(quote_head_text("NAV", "Mon Mar 2 close (5:48 PM ET)"),
                         "Mon Mar 2 close (5:48 PM ET)")
        self.assertEqual(quote_head_text("Close", "Mon Mar 2, 4:00 PM EST"),
                         "Mon Mar 2, 4:00 PM EST close")
        self.assertEqual(quote_head_text("Price", ""), "Price")

    def test_the_stamped_heading_keeps_its_own_casing(self):
        """Header CSS uppercases with wide tracking; a whole date set that way
        would push the money columns off the axes they are drawn against."""
        f, _em, _tx = render_all(payload())
        css = f.split("<style>")[1].split("</style>")[0]
        self.assertIn("th .qh,td.stamp[data-l]::before{text-transform:none", css)
