"""Tests for the email-brief template repo.

Run from the repo root (stdlib only, no dependencies):

    python3 -m unittest discover -s tests -v

Covers four things:
  1. The reference generator (build_brief.py) renders all three outputs and
     they respect the structural rules the template promises (section order,
     USPS recipient-only detail, email sanitizer survival, size budget).
  2. The AESTHETIC PIN — exact colour tokens, fonts and theme mechanics.
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
        for i in range(1, 9):
            self.assertIn(f">{i}.</span>", self.r["email"], f"email missing section {i}")
        for line in ("1. HIGH PRIORITY", "2. RELEVANT JOB POSTS",
                     "4. UPCOMING FLIGHTS", "6. USPS INFORMED DELIVERY",
                     "7. PACKAGE TRACKING", "8. RETAIL SALES"):
            self.assertIn(line, self.r["text"])

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
        # the email axis is three equal cells, so the centre label sits over the
        # track's centre instead of flowing from the left edge as a text run
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
        self.assertIn("New publications", page); self.assertIn("New publications", em)
        self.assertIn("NEW PUBLICATIONS", tx)
        self.assertIn("Journal of Phycology", page)

    def test_money_bars_diverge_from_zero_with_even_axis_breaks(self):
        """Money movements are a DIVERGING chart: 0 at centre, money out to the
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
        self.assertIn("even $1,000 steps", fin)
        self.assertIn(">−$3k<", fin); self.assertIn(">$3k<", fin); self.assertIn(">0<", fin)
        for raw in ("$1,225", "$2,450"):
            self.assertNotIn(f">{raw}<", fin, f"axis label {raw} is a raw data value, not an even break")
        # email carries the same axis as text, on its own line under the column name
        self.assertRegex(em, r"−\$3k</td>"); self.assertRegex(em, r"\$3k</td>")
        self.assertIn("green right of 0", em)

    def test_email_bars_are_fluid_not_fixed_stubs(self):
        """Email bar tracks size in %, so they fill the column at any width
        rather than sitting at a fixed ~80px stub."""
        em = self.r["email"]
        self.assertNotIn("width:40px", em); self.assertNotIn("width:80px", em)
        self.assertGreaterEqual(em.count('<td width="50%" valign="middle"'), 12,
                                "email bars must use percentage half-tracks")
        # fills are drawn with borders — backgrounds never survive the sanitizer
        self.assertIn("border-top:5px solid", em)

    def test_high_priority_leads_the_numbered_sections(self):
        """Section 1, immediately after the action bar."""
        page, tx = self.r["page"], self.r["text"]
        self.assertIn('<span class="num">1.</span> High priority', page)
        self.assertLess(page.index("High priority"), page.index("Relevant job posts"))
        self.assertLess(tx.index("NEEDS YOU TODAY"), tx.index("1. HIGH PRIORITY"))
        self.assertLess(tx.index("1. HIGH PRIORITY"), tx.index("2. RELEVANT JOB POSTS"))

    def test_market_and_crypto_carry_1d_and_1w_bars(self):
        """Both tables, both horizons, same bar scheme, separate even axes, and
        labels that are true of BOTH asset classes — an equity move is never
        '24H' (Fri->Mon close is ~65 hours)."""
        page, em, tx = self.r["page"], self.r["email"], self.r["text"]
        for out in (page, em):
            for sec in ("US market", "Cryptocurrency"):
                block = out.split(sec)[1][:6000]
                self.assertIn("1D", block, f"{sec} missing the 1D column")
                self.assertIn("1W", block, f"{sec} missing the 1W column")
        # the precise mechanics live in each table's own caption
        self.assertIn("close→close vs the prior session", page)
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
        self.assertLess(page.index("New publications"), page.index("Retail sales"))
        self.assertLess(tx.index("US MARKET"), tx.index("8. RETAIL SALES"))

    def test_fit_badges_are_bordered_chips_labelled_strong_fit_and_related(self):
        """Fit badges are chips with a thin border in their own colour — never
        bare coloured text — and the near-miss label is RELATED, not ADJACENT."""
        page, em, tx = self.r["page"], self.r["email"], self.r["text"]
        for out, name in ((page, "file"), (em, "email"), (tx, "text")):
            self.assertNotIn("Adjacent", out, f"{name} still uses the old ADJACENT label")
            self.assertIn("Related", out, f"{name} missing the RELATED badge label")
        # file: themed chip via currentColor
        badge = re.search(r"\.badge\{([^}]*)\}", page).group(1)
        self.assertIn("border:1px solid currentColor", badge,
                      "file badge must be a bordered chip")
        self.assertIn("border-radius:4px", badge)
        # email: the colour written literally (currentColor is unreliable there)
        chips = re.findall(r'<span style="[^"]*border:1px solid (#[0-9A-Fa-f]{6})[^"]*">'
                           r'(Strong fit|Related)</span>', em)
        self.assertTrue(chips, "email fit badges must be bordered chips with a literal colour")
        for colour, label in chips:
            expect = self.LIGHT_POS if label == "Strong fit" else self.LIGHT_ACCENT
            self.assertEqual(colour, expect, f"{label} chip border must be its own token")

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
        """Every colour lives in theme.py, so a drift is a one-file diff."""
        self.assertIn("AESTHETIC PIN", THEME)
        # no renderer may hardcode a hex colour behind the theme's back
        stray = [h for h in re.findall(r"#[0-9A-Fa-f]{6}", RENDER)]
        self.assertEqual(stray, [], f"render.py hardcodes colours instead of using theme: {stray}")


class TestTemplate(unittest.TestCase):
    def setUp(self):
        fences = re.findall(r"^```\n(.*?)\n```", TEMPLATE, re.S | re.M)
        self.assertEqual(len(fences), 1, "template must contain exactly one fenced prompt")
        self.fence = fences[0]
        self.doc = TEMPLATE.split("```")[0]

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
            "NEW PUBLICATIONS",
            "THIS SECTION PERSISTS",              # flights
            "LOCAL TIME AT THAT AIRPORT",
            "LINK EVERY FLIGHT NUMBER TO FLIGHTAWARE",
            "on-time record not available",       # never invent a delay figure
            'Never call an equity move "24H"',
            "there is no daily close",            # crypto trades 24/7
            "TWO CHART COLUMNS",
            "LOWEST PRIORITY",                    # retail sales sits last
            "renumber the remaining sections consecutively",
            # delivery
            "Delivery beats completeness",
            "ATTACHMENT SIZE CEILING",
            "24,600",
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
    ALLOWED_EMAIL_DOMAINS = re.compile(
        r"@([\w.-]*\.)?(example\.com|usps\.com|voip\.ms|anthropic\.com|"
        r"claude\.ai|github\.com)$", re.I)

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
