"""Tests for the email-brief template repo.

Run from the repo root (stdlib only, no dependencies):

    python3 -m unittest discover -s tests -v

Covers four things:
  1. The reference generator (build_brief.py) renders all three outputs and
     they respect the structural rules the template promises (section order,
     USPS recipient-only detail, email sanitizer survival, size budget).
  2. The AESTHETIC PIN — exact color tokens, fonts and theme mechanics.
     If this fails, a change altered the visual design; that is only
     acceptable in a PR whose stated purpose is a design change (and which
     regenerates the README screenshots).
  3. The prompt template's invariants (placeholders documented <-> used,
     safety rules present).
  4. Privacy — no personal data anywhere in tracked files, and README
     links/images resolve.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
THEME = open(os.path.join(ROOT, "brief", "theme.py"), encoding="utf-8").read()
RENDER = open(os.path.join(ROOT, "brief", "render.py"), encoding="utf-8").read()
TEMPLATE = open(os.path.join(ROOT, "ROUTINE_PROMPT.template.md"), encoding="utf-8").read()
README = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
PAYLOAD = json.load(open(os.path.join(ROOT, "sample_payload.json"), encoding="utf-8"))

_rendered = {}


def render_once():
    """Render the sample payload through the real CLI once; cache the outputs.

    Driving the published entry point (rather than importing internals) means
    these tests exercise exactly what a Routine run executes.
    """
    if _rendered:
        return _rendered
    td = tempfile.mkdtemp(prefix="brief-test-")
    subprocess.run([sys.executable, "-m", "brief", "render", "sample_payload.json",
                    "--out-dir", td, "--date", "2026-09-07"],
                   cwd=ROOT, check=True, capture_output=True)
    page = next(os.path.join(td, f) for f in os.listdir(td) if f.startswith("morning-brief"))
    _rendered.update(
        page=open(page, encoding="utf-8").read(),
        email=open(os.path.join(td, "email.html"), encoding="utf-8").read(),
        text=open(os.path.join(td, "email.txt"), encoding="utf-8").read(),
    )
    return _rendered


class TestGeneratorOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = render_once()

    def test_sections_numbered_in_order_in_file(self):
        nums = re.findall(r'<span class="num">(\d)\.</span>', self.r["page"])
        self.assertEqual(nums, [str(i) for i in range(1, 9)],
                         "file sections must be numbered 1..8 in order")

    def test_sections_in_email_and_text(self):
        # the numbered standing sections are never shed — only research cards are
        for i in range(1, 8):
            self.assertIn(f">{i}.</span>", self.r["email"], f"email missing section {i}")
        for line in ("1. HIGH PRIORITY", "2. RELEVANT JOB POSTS",
                     "4. UPCOMING FLIGHTS", "6. USPS INFORMED DELIVERY",
                     "PACKAGE TRACKING", "8. RETAIL SALES"):
            self.assertIn(line, self.r["text"])

    # (heading in the file, heading in the email, heading in the plain text)
    SECTIONS = [
        ("High priority", "High priority", "HIGH PRIORITY"),
        ("Relevant job posts", "Relevant job posts", "RELEVANT JOB POSTS"),
        ("Deposits &amp; finances", "Deposits &amp; finances", "DEPOSITS & FINANCES"),
        ("Upcoming flights", "Upcoming flights", "UPCOMING FLIGHTS"),
        ("VoIP voicemails", "VoIP voicemails", "VOIP VOICEMAILS"),
        ("USPS Informed Delivery", "USPS Informed Delivery", "USPS INFORMED DELIVERY"),
        ("Package tracking", "Package tracking", "PACKAGE TRACKING"),
        ("US market", "US market", "US MARKET"),
        ("Vanguard funds", "Vanguard funds", "Vanguard funds"),
        ("Cryptocurrency", "Cryptocurrency", "CRYPTOCURRENCY"),
        ("AI &amp; programming", "AI &amp; programming", "AI & PROGRAMMING"),
        ("Research &amp; publications", "Research &amp; publications", "RESEARCH & PUBLICATIONS"),
        ("Retail sales", "Retail sales", "RETAIL SALES"),
        ("Domain allowlist", "Domain allowlist", "DOMAIN ALLOWLIST"),
        ("Sources", "Sources", "SOURCES"),
    ]

    def test_every_section_reaches_the_file_and_the_plain_text(self):
        """Parity guard. The funds table once vanished from the standalone file
        while surviving in the email, because no test compared the outputs
        against each other — only each one against itself.

        The EMAIL is the one output allowed to be incomplete, and only when it
        exceeds Gmail's budget: see test_email_sheds_cards_only_when_over_budget.
        The file and the plain text always carry everything."""
        for in_file, _in_email, in_text in self.SECTIONS:
            self.assertIn(in_file, self.r["page"], f"FILE is missing section {in_file!r}")
            self.assertIn(in_text, self.r["text"], f"TEXT is missing section {in_text!r}")

    def test_direction_shown_as_arrows_in_html_words_in_plain_text(self):
        """Finance figures use arrows to save width. Shape carries the meaning,
        so color is never the only channel; the plain-text fallback has no
        color at all, so it keeps the words."""
        page, em, tx = self.r["page"], self.r["email"], self.r["text"]
        for out, name in ((page, "file"), (em, "email")):
            self.assertGreaterEqual(out.count("\u25b2"), 10, f"{name} missing up arrows")
            self.assertGreaterEqual(out.count("\u25bc"), 4, f"{name} missing down arrows")
            for word in (" Up<", " Down<", " Up ", " Down "):
                self.assertNotIn(word, out, f"{name} still spells out {word.strip()!r}")
        self.assertNotIn("\u25b2", tx, "plain text has no color, so it keeps words")
        self.assertIn("Up", tx); self.assertIn("Down", tx)
        # the sign still accompanies every figure, so direction survives without
        # color or glyph rendering
        self.assertRegex(page, r"\+\d+\.\d{2}% \u25b2")
        self.assertRegex(page, r"\u2212\d+\.\d{2}% \u25bc")

    def test_fund_rows_carry_change_bars_on_even_axes(self):
        page, em = self.r["page"], self.r["email"]
        funds = page.split("Vanguard funds")[1][:6000]
        self.assertIn('class="dbar"', funds, "fund rows must carry change bars")
        self.assertIn('class="daxis"', funds, "each fund bar column needs its own ruler")
        for horizon in ("1D", "1W", "YTD"):
            self.assertIn(horizon, funds, f"funds missing {horizon}")
            self.assertIn(f"{horizon} axis", page)
        # the email is capped at three columns, so YTD rides in the first one
        self.assertIn("Fund · NAV · YTD", em)

    def test_plain_text_is_a_full_fallback_not_a_stub(self):
        self.assertGreater(len(self.r["text"]), 4000)

    def test_usps_details_only_intended_recipient(self):
        # one table row per intended-recipient piece, no more
        sec = self.r["page"].split("USPS Informed Delivery")[1].split("</section>")[0]
        rows = sec.split("<tbody>")[1].split("</tbody>")[0].count("<tr>")
        pieces = len(PAYLOAD["USPS"]["pieces"])
        self.assertEqual(rows, pieces, "USPS table must contain exactly the intended-recipient pieces")
        # counts line covers all buckets
        for phrase in ("other named recipients", "generic addressee", "unreadable", "package"):
            self.assertIn(phrase, sec)

    def test_usps_scan_rendered_full_in_file_only(self):
        page_sec = self.r["page"].split("USPS Informed Delivery")[1].split("</section>")[0]
        self.assertIn('<figure class="scanfig"><img src="data:image/', page_sec,
                      "file must embed the mailpiece scan as a data: URI figure")
        self.assertIn("<figcaption>", page_sec)
        # the email never carries images (sanitizer strips them anyway)
        self.assertNotIn("<img", self.r["email"])

    def test_market_axes_timescale_magnitude_and_journals(self):
        page, em, tx = self.r["page"], self.r["email"], self.r["text"]
        # four header rulers: 24H + 7D on both the market and crypto tables
        self.assertGreaterEqual(page.count('class="daxis"'), 4)
        # every index and coin row carries two diverging tracks, plus money
        self.assertGreaterEqual(page.count('class="dbar"'), 20,
                                "file page lost its .dbar diverging tracks")
        # both horizons labelled identically in both tables
        for probe in ("1D", "1W"):
            self.assertIn(probe, page, f"file missing horizon label {probe}")
            self.assertIn(probe, em, f"email missing horizon label {probe}")
            self.assertIn(probe, tx, f"text missing horizon label {probe}")
        # separate even axes per horizon (7-day spread is wider than 1-day)
        # the email axis is three equal cells, so the center label sits over the
        # track's center instead of flowing from the left edge as a text run
        for lo, hi in (("\u22121%", "+1%"), ("\u22123%", "+3%"),
                       ("\u22122%", "+2%"), ("\u22126%", "+6%")):
            self.assertIn(f'align="left" style="{"{"}cell{"}"}">{lo}'.replace("{cell}", ""), em) \
                if False else None
            self.assertRegex(em, re.escape(lo) + r"</td>", f"email missing axis label {lo}")
            self.assertRegex(em, re.escape(hi) + r"</td>", f"email missing axis label {hi}")
        self.assertNotIn("\u22121% \u00b7 0 \u00b7 +1%", em,
                         "axis must not be a left-flowing text run")
        # magnitude: crypto % moves paired with $ moves everywhere
        for out in (page, em, tx):
            self.assertIn("$1,082", out, "crypto 24h move must carry $ magnitude")
            self.assertIn("$3,594", out, "crypto 7d move must carry $ magnitude")
        # journals research card in all three outputs
        self.assertIn("Research &amp; publications", page)
        self.assertIn("Research &amp; publications", em)
        self.assertIn("RESEARCH & PUBLICATIONS", tx)
        self.assertIn("Journal of Phycology", page)

    def test_money_bars_diverge_from_zero_with_even_axis_breaks(self):
        """Money movements are a DIVERGING chart: 0 at center, money out to the
        left in red, money in to the right in green, internal transfers neutral.
        Axis breaks are even round numbers, never raw data values."""
        page, em = self.r["page"], self.r["email"]
        fin = page.split("Deposits &amp; finances")[1].split("</section>")[0]
        self.assertIn('class="dbar money"', fin, "money bars must ride the diverging track")
        self.assertNotIn('class="sbar"', fin, "single-direction money track is retired")
        for fill in ('class="fill pos right"', 'class="fill neg left"', 'class="fill neu right"'):
            self.assertIn(fill, fin, f"money bar missing {fill}")
        # even breaks: $2,450 of movement must yield round $1,000 steps to $3k,
        # never a data-derived $1,225 midpoint
        self.assertIn("even $2,000 steps", fin)
        self.assertIn(">−$6k<", fin); self.assertIn(">$6k<", fin); self.assertIn(">0<", fin)
        # the file names the unit in the column header, so the ruler must not
        # repeat it — a wrapped "USD" under the tick reads as a broken label
        self.assertIn("Out ← 0 → In, USD", fin)
        self.assertNotIn(">$6k USD<", fin)
        for raw in ("$2,640", "$5,280"):
            self.assertNotIn(f">{raw}<", fin, f"axis label {raw} is a raw data value, not an even break")
        # email carries the same axis as text, on its own line under the column name
        self.assertRegex(em, r"−\$6k</td>"); self.assertRegex(em, r"\$6k USD</td>")
        self.assertIn("green right of 0", em)

    def test_email_bars_are_fluid_not_fixed_stubs(self):
        """Email bar tracks size in %, so they fill the column at any width
        rather than sitting at a fixed ~80px stub."""
        em = self.r["email"]
        self.assertNotIn("width:40px", em); self.assertNotIn("width:80px", em)
        self.assertGreaterEqual(em.count('<td width="50.0%"'), 12,
                                "email bars must use percentage-width cells")
        # fills are drawn with borders — backgrounds never survive the sanitizer
        self.assertIn("border-top:5px solid", em)

    def test_high_priority_leads_the_numbered_sections(self):
        """Section 1, immediately after the action bar."""
        page, tx = self.r["page"], self.r["text"]
        self.assertIn('<span class="num">1.</span> High priority', page)
        self.assertLess(page.index("High priority"), page.index("Relevant job posts"))
        self.assertLess(tx.index("NEEDS YOU TODAY"), tx.index("1. HIGH PRIORITY"))
        self.assertLess(tx.index("1. HIGH PRIORITY"), tx.index("2. RELEVANT JOB POSTS"))

    def test_market_and_crypto_carry_1d_1w_and_ytd(self):
        """Both tables, both horizons, same bar scheme, separate even axes, and
        labels that are true of BOTH asset classes — an equity move is never
        '24H' (Fri->Mon close is ~65 hours)."""
        page, em, tx = self.r["page"], self.r["email"], self.r["text"]
        for out in (page, em):
            for sec in ("US market", "Cryptocurrency"):
                block = out.split(sec)[1][:6000]
                for horizon in ("1D", "1W", "YTD"):
                    self.assertIn(horizon, block, f"{sec} missing {horizon}")
        # the precise mechanics live in each table's own caption
        self.assertIn("close → close vs the prior session", page)
        self.assertIn("trailing 5 sessions", page)
        self.assertIn("rolling 24 h", page)
        self.assertIn("no daily close", page)
        for out in (page, em, tx):
            self.assertNotIn("24H", out, "an equity move must never be labelled 24H")
        self.assertIn("1D", tx); self.assertIn("1W", tx)
        self.assertNotIn(">MOVE<", page, "no per-table label variants")

    def test_flights_persist_link_flightaware_and_use_airport_local_time(self):
        page, em, tx = self.r["page"], self.r["email"], self.r["text"]
        # standing section 4, directly after Deposits & finances
        self.assertIn('<span class="num">4.</span> Upcoming flights', page)
        self.assertLess(page.index("Deposits &amp; finances"), page.index("Upcoming flights"))
        self.assertLess(page.index("Upcoming flights"), page.index("VoIP voicemails"))
        for out in (page, em, tx):
            self.assertIn("LOCAL TO EACH AIRPORT", out.upper())
            self.assertIn("carried forward", out.lower())
        # every leg time carries its own zone abbreviation
        self.assertRegex(page, r"\d{1,2}:\d{2} [AP]M (CST|EDT|EST|PDT|PST|CDT)")
        # FlightAware link per flight, ICAO ident, plus a recent on-time record
        idents = re.findall(r"flightaware\.com/live/flight/([A-Z]{3}\d+)", page)
        self.assertGreaterEqual(len(idents), 2, "each flight needs a FlightAware link")
        for out in (page, em, tx):
            self.assertIn("flightaware.com/live/flight/", out)
            self.assertRegex(out, r"\d+% on time")
            self.assertRegex(out, r"avg delay \d+ min")
        # framed as history, never as a prediction
        self.assertIn("not a prediction", page)

    def test_retail_sales_is_the_last_section(self):
        """Lowest priority — retail sits below the research sections."""
        page, tx = self.r["page"], self.r["text"]
        self.assertLess(page.index("US market"), page.index("Retail sales"))
        self.assertLess(page.index("Research &amp; publications"), page.index("Retail sales"))
        self.assertLess(tx.index("US MARKET"), tx.index("8. RETAIL SALES"))

    def test_every_ranked_lead_carries_a_fit_tier(self):
        """A row with no badge is the symptom of the renderer guessing fit from
        keywords it cannot know. The tier now comes from the payload, so every
        ranked row is labelled."""
        page = self.r["page"]
        rows = re.findall(r'data-l="Role">(.*?)</td>', page)
        self.assertGreaterEqual(len(rows), 3, "no ranked leads rendered")
        unbadged = [re.sub("<[^>]+>", "", r)[:40] for r in rows if "badge" not in r]
        self.assertEqual(unbadged, [], f"ranked leads with no fit badge: {unbadged}")

    def test_fit_badges_are_bordered_chips_labelled_strong_fit_and_related(self):
        """Fit badges are chips with a thin border in their own color — never
        bare colored text — and the near-miss label is RELATED, not ADJACENT."""
        page, em, tx = self.r["page"], self.r["email"], self.r["text"]
        for out, name in ((page, "file"), (em, "email"), (tx, "text")):
            self.assertNotIn(">ADJACENT<", out, f"{name} still uses the old ADJACENT badge")
            self.assertIn("RELATED", out, f"{name} missing the RELATED badge label")
            self.assertIn("STRONG FIT", out, f"{name} missing the STRONG FIT badge label")
        # file: themed chip via currentColor
        badge = re.search(r"\.badge\{([^}]*)\}", page).group(1)
        self.assertIn("border:1px solid currentColor", badge,
                      "file badge must be a bordered chip")
        self.assertIn("border-radius:4px", badge)
        # email: the color written literally (currentColor is unreliable there)
        chips = re.findall(r'<span style="[^"]*border:1px solid (#[0-9A-Fa-f]{6})[^"]*">'
                           r'(STRONG FIT|RELATED)</span>', em)
        self.assertTrue(chips, "email fit badges must be bordered chips with a literal color")
        for color, label in chips:
            expect = self.LIGHT_POS if label == "STRONG FIT" else self.LIGHT_ACCENT
            self.assertEqual(color, expect, f"{label} chip border must be its own token")

    LIGHT_POS = "#1B7F4B"
    LIGHT_ACCENT = "#0B7285"

    def test_package_tracking_columns(self):
        sec = self.r["page"].split("Package tracking")[1].split("</section>")[0]
        for col in ("Carrier", "Tracking", "Sender · item", "Recipient", "Status", "Est. arrival"):
            self.assertIn(col, sec)
        self.assertIn("tracking link only", sec, "the no-number case must be demonstrated")

    def test_email_survives_the_sanitizer(self):
        em = self.r["email"]
        self.assertNotIn("<style", em, "email must not rely on <style> blocks")
        self.assertNotIn(' class="', em, "email must not rely on class attributes")
        self.assertNotIn("<img", em, "email must not contain <img> tags")
        self.assertNotIn("white-space:nowrap", em)
        self.assertIsNone(re.search(r"background\s*:", em),
                          "email must not use background CSS (stripped by Gmail)")
        self.assertIn("max-width:860px", em)

    def test_email_size_budget(self):
        self.assertLess(len(self.r["email"].encode("utf-8")), 85 * 1024,
                        "email htmlBody must stay under the 85 KB budget")

    def test_file_theme_dark_by_default(self):
        page = self.r["page"]
        self.assertIn('<meta name="color-scheme" content="dark light">', page)
        root = re.search(r":root\{([^}]*)\}", page).group(1)
        self.assertIn("--bg:#0E1417", root, "bare :root must carry the DARK palette")
        self.assertIn("prefers-color-scheme: light", page)
        self.assertIn(':root:not([data-theme="dark"])', page)
        self.assertIn(':root[data-theme="light"]', page)


class TestAestheticPin(unittest.TestCase):
    """Exact visual constants. A failure here means the design changed —
    only allowed in an explicitly-requested design-change PR."""

    LIGHT = {"bg": "#F4F6F7", "surface": "#FFFFFF", "surface2": "#EAEFF1",
             "ink": "#161D21", "ink2": "#4A585F", "ink3": "#67757E",
             "line": "#DCE3E6", "lineS": "#C3CED3", "accent": "#0B7285",
             "pos": "#1B7F4B", "neg": "#B4342A", "warn": "#A9690A"}
    DARK = {"bg": "#0E1417", "surface": "#151D21", "surface2": "#1C262B",
            "ink": "#E6EDF0", "ink2": "#A6B6BE", "ink3": "#74858E",
            "line": "#26333A", "lineS": "#37474F", "accent": "#3EC5DE",
            "pos": "#4FC98A", "neg": "#F0796C", "warn": "#E0A548"}

    def _palette(self, name):
        body = re.search(name + r" = dict\((.*?)\)\n", THEME, re.S).group(1)
        return dict(re.findall(r'(\w+)="(#[0-9A-Fa-f]{6})"', body))

    def test_light_tokens_pinned(self):
        self.assertEqual(self._palette("L"), self.LIGHT)

    def test_dark_tokens_pinned(self):
        self.assertEqual(self._palette("D"), self.DARK)

    def test_fonts_pinned(self):
        page = render_once()["page"]
        self.assertIn("family=Archivo:wght@500;600;700", page)
        self.assertIn("family=JetBrains+Mono:wght@400;500;700", page)
        self.assertIn("family=Source+Sans+3:wght@400;600", page)

    def test_aesthetic_pin_is_centralised(self):
        """Every color lives in theme.py, so a drift is a one-file diff."""
        self.assertIn("AESTHETIC PIN", THEME)
        # no renderer may hardcode a hex color behind the theme's back
        stray = [h for h in re.findall(r"#[0-9A-Fa-f]{6}", RENDER)]
        self.assertEqual(stray, [], f"render.py hardcodes colors instead of using theme: {stray}")


class TestTemplate(unittest.TestCase):
    def setUp(self):
        fences = re.findall(r"^```\n(.*?)\n```", TEMPLATE, re.S | re.M)
        self.assertEqual(len(fences), 1, "template must contain exactly one fenced prompt")
        self.fence = fences[0]
        self.doc = TEMPLATE.split("```")[0]

    def test_prompt_tells_the_run_how_to_carry_the_html_body(self):
        """A body too big for one read must ship with a chunking scheme.

        The send tool takes the body as an inline string, so ~85 KB of email
        has to pass through the run's context. One run met the read cap
        mid-file, gave up, and downgraded the send. The renderer answers that
        by splitting the body itself; this asserts the prompt actually routes
        the run through the parts and never through the whole file. If the
        email ever shrinks under a single read, the requirement lapses.
        """
        from brief.render import SEND_PART_BYTES, split_for_send
        body = render_once()["email"]
        if len(body.encode("utf-8")) <= SEND_PART_BYTES:
            self.skipTest("email now fits one read; chunking no longer needed")
        self.assertRegex(self.fence, r"email\.part01\.html",
                         "the prompt must name the split parts")
        self.assertRegex(self.fence, r"do NOT read email\.html",
                         "the prompt must steer the run away from the whole file")
        self.assertRegex(self.fence, r"htmlBody",
                         "the HTML body is the point of the brief; the prompt "
                         "must still send it")

    def test_send_parts_rebuild_the_email_exactly(self):
        """Concatenating the parts must reproduce the body byte for byte.

        This is the property the whole send rests on: the run rebuilds the
        htmlBody from parts, so any drift here ships a corrupted brief.
        """
        from brief.render import SEND_PART_BYTES, split_for_send
        body = render_once()["email"]
        parts = split_for_send(body)
        self.assertEqual("".join(parts), body, "parts do not rebuild the email")
        self.assertTrue(all(p.startswith("<") for p in parts),
                        "a part starting mid-tag hides truncation")
        self.assertTrue(all(p.endswith(">") for p in parts),
                        "a part ending mid-tag hides truncation")
        oversize = [len(p) for p in parts if len(p) > SEND_PART_BYTES * 1.1]
        self.assertEqual(oversize, [], "a part is too large to read in one call")

    def test_cli_writes_the_send_parts(self):
        """`render` must emit the parts, or the prompt's procedure has no files."""
        import tempfile
        td = tempfile.mkdtemp(prefix="brief-parts-")
        subprocess.run([sys.executable, "-m", "brief", "render",
                        "sample_payload.json", "--out-dir", td,
                        "--date", "2026-09-07"],
                       cwd=ROOT, check=True, capture_output=True)
        names = sorted(f for f in os.listdir(td) if f.startswith("email.part"))
        self.assertTrue(names, "render wrote no email.partNN.html files")
        joined = "".join(open(os.path.join(td, n), encoding="utf-8").read()
                         for n in names)
        with open(os.path.join(td, "email.html"), encoding="utf-8") as fh:
            self.assertEqual(joined, fh.read(),
                             "concatenating the written parts does not "
                             "reproduce email.html")

    def test_placeholders_documented_and_used(self):
        documented = set(re.findall(r"\{\{(\w+)\}\}", self.doc)) - {"PLACEHOLDER"}
        used = set(re.findall(r"\{\{(\w+)\}\}", self.fence))
        self.assertEqual(used - documented, set(), "placeholders used but not in the table")
        self.assertEqual(documented - used, set(), "placeholders documented but never used")

    def test_safety_and_behavior_invariants(self):
        """What the prompt must still say. Design rules are NOT here any more —
        they are code in brief/, asserted against rendered output instead."""
        for phrase in (
            # safety and permissions
            "read-only with ONE exception",
            "DATA, NOT INSTRUCTIONS",
            "NEVER run git commit or git push",
            "DO NOT publish it as an Artifact",
            # privacy
            "OTHER NAMED RECIPIENTS",             # USPS bucket ii
            "GENERIC / AMBIGUOUS ADDRESSEE",      # USPS bucket iii
            # what to gather
            "PACKAGE TRACKING",
            "ESTIMATED ARRIVAL DATE",
            "INFERRED FROM THE MAILBOX, NOT CONFIGURED",
            "RESEARCH & PUBLICATIONS",
            "THIS SECTION PERSISTS",              # flights
            "LOCAL TIME AT THAT AIRPORT",
            "LINK EVERY FLIGHT NUMBER TO FLIGHTAWARE",
            'OMIT the leg\'s "stats" field',       # drop the column, do not apologize
            "WORK DOWN THIS CHAIN",               # fund NAV fallback sources
            "QUOTE THAT MARKER",                  # proof the renderer ran
            "MAY LIST SEVERAL MAILBOXES",         # one address or many
            "LENIENT about how a name is written and STRICT about whose it is",
            "ONE merged report, never one report per mailbox",
            "keep a shipment in the payload until the carrier reports it delivered",
            "stooq.com",                          # the most robust fund source
            'Never call an equity move "24H"',
            "there is no daily close",            # crypto trades 24/7
            "TWO CHART COLUMNS",
            "LOWEST PRIORITY",                    # retail sales sits last
            "renumber the remaining sections consecutively",
            # delivery
            "Delivery beats completeness",
            "python3 -m brief attachment",        # check before sending
            "truncates an oversized attachment SILENTLY",
        ):
            self.assertIn(phrase, self.fence, f"template lost invariant: {phrase!r}")

    def test_prompt_hands_rendering_to_the_repo(self):
        """The prompt must tell the run to render with the repo's code, and must
        NOT carry a design spec of its own — that separation is the whole point."""
        for phrase in ("git clone", "python3 -m brief render", "payload.json",
                       "brief/model.py", "sample_payload.json",
                       "NUMBERS, never formatted strings"):
            self.assertIn(phrase, self.fence, f"prompt lost the renderer contract: {phrase!r}")
        # design prose that must no longer live in the prompt
        for gone in ("--bg:", "#0B7285", "prefers-color-scheme", "border-left:6px solid",
                     "font:600 10.5px", "max-width:860px", "AESTHETICS ARE PINNED",
                     "EMAIL VISUAL IDENTITY"):
            self.assertNotIn(gone, self.fence,
                             f"design prose {gone!r} is back in the prompt; it belongs in brief/")


class TestScreenshotsAreCurrent(unittest.TestCase):
    """The README screenshots must show the CURRENT UI.

    Regenerating them was a prose convention in the README, followed by hand -
    and it silently failed once already, leaving the market screenshot several
    commits out of date. This makes it mechanical.

    It compares a hash of the rendered HTML rather than the pixels: font
    rasterisation differs between macOS and the Linux CI runner, so a pixel
    comparison would fail on every run whether or not anything changed.
    """

    LOCK = os.path.join(ROOT, "docs", "screenshots.lock")

    def test_lock_file_exists(self):
        self.assertTrue(os.path.isfile(self.LOCK),
                        "docs/screenshots.lock is missing - run python3 docs/render_screenshots.py")

    def test_screenshots_match_the_current_render(self):
        import hashlib
        recorded = None
        for line in open(self.LOCK, encoding="utf-8"):
            if line.startswith("sha256"):
                recorded = line.split("=", 1)[1].strip()
        self.assertIsNotNone(recorded, "no sha256 recorded in docs/screenshots.lock")
        actual = hashlib.sha256(render_once()["page"].encode("utf-8")).hexdigest()
        self.assertEqual(
            actual, recorded,
            "The rendered brief has changed but the README screenshots were not "
            "regenerated, so the README is showing a stale UI.\n"
            "Fix: python3 docs/render_screenshots.py  (then commit docs/*.png and "
            "docs/screenshots.lock)")


class TestReadmeAndPrivacy(unittest.TestCase):
    def test_toc_and_anchor_links_resolve(self):
        def slug(h):
            return re.sub(r"[^\w\s-]", "", h.strip().lower()).replace(" ", "-")
        heads = {slug(m.group(1)) for m in re.finditer(r"^#{2,3} (.+)$", README, re.M)}
        missing = [l for l in re.findall(r"\]\(#([^)]+)\)", README) if l not in heads]
        self.assertEqual(missing, [], "dead anchor links in README")

    def test_readme_images_exist(self):
        for img in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", README):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, img)), f"missing image {img}")

    # Domains that may legitimately appear in the template and mock data.
    # example.com/.org/.net are reserved by IANA for documentation, so they can
    # never belong to a real person — that is exactly why mock data uses them.
    ALLOWED_EMAIL_DOMAINS = re.compile(
        r"@([\w.-]*\.)?(example\.(com|org|net)|usps\.com|voip\.ms|"
        r"anthropic\.com|claude\.ai|github\.com)$", re.I)

    def test_screenshots_share_a_scale(self):
        import struct
        widths = {}
        docs = os.path.join(ROOT, "docs")
        for f in sorted(os.listdir(docs)):
            if f.endswith(".png"):
                with open(os.path.join(docs, f), "rb") as fh:
                    fh.read(16)
                    widths[f] = struct.unpack(">I", fh.read(4))[0]
        self.assertTrue(widths, "no README screenshots found")
        lo, hi = min(widths.values()), max(widths.values())
        self.assertLessEqual(hi, lo * 1.10,
                             f"screenshot widths diverge — text renders at different scales: {widths}")

    def test_no_personal_data_in_tracked_files(self):
        """Generic detectors: any real-looking phone number (mock data must use
        the 555 prefix) or any email address outside the allowed mock/service
        domains fails the build. Repo owners can add their own patterns in an
        untracked tests/private_denylist.txt (one regex per line, gitignored) —
        never commit personal identifiers, not even inside this test."""
        phone = re.compile(r"(?<![\d.])(?!555[-.\s])\d{3}[-.\s]\d{3}[-.\s]\d{4}(?![\d.])")
        email = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
        private = []
        deny_path = os.path.join(ROOT, "tests", "private_denylist.txt")
        if os.path.isfile(deny_path):
            private = [re.compile(l.strip(), re.I)
                       for l in open(deny_path, encoding="utf-8")
                       if l.strip() and not l.startswith("#")]
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True,
                               capture_output=True, text=True).stdout.split()
        hits = []
        for f in files:
            if f.endswith(".png"):
                continue
            body = open(os.path.join(ROOT, f), encoding="utf-8", errors="ignore").read()
            hits += [f"{f}: phone {m!r}" for m in phone.findall(body)]
            hits += [f"{f}: email {m!r}" for m in email.findall(body)
                     if not self.ALLOWED_EMAIL_DOMAINS.search(m)]
            for rx in private:
                hits += [f"{f}: {m.group(0)!r}" for m in rx.finditer(body)
                         if f != "tests/private_denylist.txt"]
        self.assertEqual(hits, [], "personal data found in tracked files")


if __name__ == "__main__":
    unittest.main(verbosity=2)
