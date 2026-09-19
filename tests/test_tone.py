"""Which way a number went, and whether that is good news.

A wrongly coloured figure says the opposite of the truth, so the rules here are
pinned in both directions: what must be coloured, and what must stay neutral
because the module cannot honestly tell. Stdlib unittest.
"""
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from brief import render_all  # noqa: E402
from brief.tone import direction, macro_tone, move_tone, polarity  # noqa: E402

SAMPLE = os.path.join(ROOT, "sample_payload.json")


def payload(**overrides):
    with open(SAMPLE, encoding="utf-8") as fh:
        p = json.load(fh)
    p.update(overrides)
    return p


class TestWhatAMoveMeans(unittest.TestCase):
    def test_a_rise_is_bad_news_when_the_thing_is_a_cost(self):
        for indicator in ("Unemployment rate", "CPI (headline, y/y)", "Fed funds target",
                          "10-yr Treasury", "30-yr mortgage rate", "Initial jobless claims"):
            self.assertEqual(polarity(indicator), -1, indicator)
            self.assertEqual(macro_tone(indicator, "up 0.2 pt"), "neg", indicator)
            self.assertEqual(macro_tone(indicator, "down 0.2 pt"), "pos", indicator)

    def test_a_rise_is_good_news_when_the_thing_is_activity(self):
        for indicator in ("Nonfarm payrolls", "Retail sales", "Average hourly earnings", "GDP"):
            self.assertEqual(polarity(indicator), 1, indicator)
            self.assertEqual(macro_tone(indicator, "+151,000"), "pos", indicator)
            self.assertEqual(macro_tone(indicator, "-12,000"), "neg", indicator)

    def test_a_rate_decision_reads_as_the_cost_it_defers_to_the_reader(self):
        self.assertEqual(macro_tone("Fed funds target", "raised 25 bp to 3.75-4.00%"), "neg")
        self.assertEqual(macro_tone("Fed funds target", "cut 25 bp"), "pos")

    def test_missing_a_forecast_is_the_direction_not_the_plus_sign_inside_it(self):
        """"below the +170,000 consensus" carries a plus that belongs to the forecast."""
        self.assertEqual(direction("below the +170,000 consensus"), -1)
        self.assertEqual(direction("above the +170,000 consensus"), 1)
        self.assertEqual(macro_tone("Nonfarm payrolls", "below the +170,000 consensus"), "neg")

    def test_what_stays_neutral(self):
        """Unplaceable, unchanged, or simply not a movement at all."""
        for indicator, change in (("Next FOMC", "Mar 17 - 18"),
                                  ("Unemployment rate", "unchanged at 4.1%"),
                                  ("Fed funds target", "4.25 - 4.50%"),
                                  ("Some index nobody has coined", "up 3%"),
                                  ("Unemployment rate", "")):
            self.assertEqual(macro_tone(indicator, change), "neu", f"{indicator} / {change}")

    def test_a_date_range_is_not_a_fall(self):
        """"Mar 17 - 18" read as a minus painted an FOMC row red."""
        self.assertEqual(direction("Mar 17 - 18"), 0)
        self.assertEqual(direction("-0.4 pt"), -1)

    def test_a_quote_takes_its_tone_from_its_own_1d_move(self):
        self.assertEqual((move_tone(0.6), move_tone(-0.26), move_tone(0), move_tone(None)),
                         ("pos", "neg", "neu", "neu"))


class TestColouredIntoTheBrief(unittest.TestCase):
    def test_the_macro_figure_is_coloured_by_meaning_in_page_and_email(self):
        p = payload(MACRO_ROWS=[["Unemployment rate", "4.4%", "up from 4.1% in July", "Aug data"],
                                ["Nonfarm payrolls", "+151,000", "+151,000 jobs added", "Aug data"],
                                ["Next FOMC", "Mar 17 - 18", "Mar 17 - 18", "as of Mar 2"]])
        f, em, _ = render_all(p)
        fed = f.split("Fed &amp; labor market")[1][:1500]
        self.assertIn('<b class="dir-neg mono">4.4%</b>', fed)
        self.assertIn('<b class="dir-pos mono">+151,000</b>', fed)
        self.assertRegex(fed, r'<b class=" mono">Mar 17 [-\u2013] 18</b>', "an unplaceable row stays plain")
        self.assertRegex(em, r'color:#[0-9A-F]{6};font-weight:600;">4\.4%')

    def test_close_price_and_nav_are_coloured_by_the_days_move(self):
        f, em, _ = render_all(payload())
        market = f.split("US market")[1].split("Cryptocurrency")[0]
        # The label carries the shared as-of when the rows agree on one, so the
        # column is matched by the word it ends with rather than the word alone.
        self.assertRegex(market, r'class="dir-pos">6,412\.30<')
        self.assertRegex(market, r'class="dir-neg">47,105\.88<')
        self.assertRegex(market, r'data-l="Fund \u00b7 NAV \(USD\)">.*?class="dir-(pos|neg)"')
        crypto = f.split("Cryptocurrency")[1][:4000]
        self.assertRegex(crypto, r'data-l="Asset \u00b7 price \(USD\)">.*?class="dir-(pos|neg)"')

    def test_a_quote_can_say_when_it_was_taken(self):
        """One time for the whole table is stated once, over the column."""
        p = payload()
        p["MKT_ROWS"] = [list(r)[:8] + ["9:41 AM EST, mid-session"] for r in p["MKT_ROWS"]]
        f, em, tx = render_all(p)
        market = f.split("US market")[1].split("</table>")[0]
        self.assertIn("(09:41 EST, mid-session)", market, "beside the figure it dates")
        self.assertIn("(09:41 EST, mid-session)", em)
        self.assertIn("(09:41 EST, mid-session)", tx)

    def test_quotes_taken_at_different_times_each_keep_their_own(self):
        """Then the time is news, and belongs beside the figure it dates."""
        p = payload()
        rows = [list(r)[:8] for r in p["MKT_ROWS"]]
        rows[0].append("9:41 AM EST, mid-session")
        for r in rows[1:]:
            r.append("Mon Mar 2, 4:00 PM EST close")
        p["MKT_ROWS"] = rows
        f, em, tx = render_all(p)
        for doc in (f, em, tx):
            self.assertIn("(09:41 EST, mid-session)", doc)
            self.assertIn("(Mon Mar 2, 16:00 EST close)", doc)

    def test_a_row_without_a_time_renders_exactly_as_before(self):
        """A run written against the old eight-field row loses nothing."""
        p = payload()
        p["MKT_ROWS"] = [list(r)[:8] for r in p["MKT_ROWS"]]
        f, _em, tx = render_all(p)
        market = tx.split("US MARKET")[1].split("Large caps:")[0]
        self.assertNotIn("(as of ", market, "no time stated, nothing added")
        self.assertRegex(market, r"S&P 500: 6,412\.30 ")   # its sparkline may follow
        self.assertRegex(f.split("US market")[1][:3000], r'class="dir-pos">6,412\.30</span>')


class TestAsOfCarriesItsYear(unittest.TestCase):
    """"Feb data" is ambiguous the moment the brief is read in another year."""

    def test_a_bare_month_gains_this_briefs_year(self):
        from brief.render import with_year
        render_all(payload())
        self.assertEqual(with_year("Feb data"), "Feb 2026 data")
        self.assertEqual(with_year("as of Mar 2"), "as of Mar 2, 2026")

    def test_a_year_already_stated_is_left_alone(self):
        from brief.render import with_year
        render_all(payload())
        for text in ("Feb 2025 data", "Mon Mar 2, 2026 close", "last close", ""):
            self.assertEqual(with_year(text), text, text)

    def test_the_jobs_and_macro_columns_show_it_in_every_output(self):
        f, em, tx = render_all(payload())
        for doc in (f, em, tx):
            self.assertIn("Feb 2026 data", doc)
            self.assertNotRegex(doc, r"Feb data\b")


class TestTerminalsReadPerAirport(unittest.TestCase):
    def test_each_airport_gets_its_own_line(self):
        f, em, tx = render_all(payload())
        # the airport code and the gate carry their own colour now, so the
        # line is matched around the tags rather than as one plain string
        self.assertRegex(f, r">DEN</b>: Terminal A, <b[^>]*>gate A12</b><br><b[^>]*>ORD</b>: Terminal 2")
        self.assertRegex(em, r">DEN</b>: Terminal A, <b[^>]*>gate A12</b>")
        self.assertRegex(tx, r"DEN: Terminal A, gate A12\n\s+ORD: Terminal 2")

    def test_a_single_terminal_is_left_alone(self):
        from brief.render import terminal_lines
        self.assertEqual(terminal_lines({"frm": "Denver (DEN)", "to": "Chicago (ORD)",
                                         "term": "Terminal 2"}), ["Terminal 2"])

    def test_a_leg_with_no_airport_codes_keeps_the_text_whole(self):
        from brief.render import terminal_lines
        self.assertEqual(terminal_lines({"frm": "Denver", "to": "Chicago",
                                         "term": "Terminal A → Terminal 2"}),
                         ["Terminal A", "Terminal 2"])

    def test_no_terminal_no_lines(self):
        from brief.render import terminal_lines
        self.assertEqual(terminal_lines({"frm": "Denver (DEN)", "to": "Chicago (ORD)"}), [])


if __name__ == "__main__":
    unittest.main()
