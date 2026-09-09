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
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "build_brief.py"), encoding="utf-8").read()
TEMPLATE = open(os.path.join(ROOT, "ROUTINE_PROMPT.template.md"), encoding="utf-8").read()
README = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()

_rendered = {}


def render_once():
    """Run the generator once into a temp dir; cache the three outputs."""
    if _rendered:
        return _rendered
    td = tempfile.mkdtemp(prefix="brief-test-")
    gen = os.path.join(td, "gen.py")
    open(gen, "w", encoding="utf-8").write(
        re.sub(r"^OUT_DIR = .*$", f'OUT_DIR = "{td}"', SRC, count=1, flags=re.M))
    subprocess.run([sys.executable, gen], cwd=td, check=True, capture_output=True)
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
        self.assertEqual(nums, [str(i) for i in range(1, 8)],
                         "file sections must be numbered 1..7 in order")

    def test_sections_in_email_and_text(self):
        for i in range(1, 8):
            self.assertIn(f">{i}.</span>", self.r["email"], f"email missing section {i}")
        for line in ("1. RELEVANT JOB POSTS", "5. USPS INFORMED DELIVERY",
                     "6. PACKAGE TRACKING", "7. RETAIL SALES"):
            self.assertIn(line, self.r["text"])

    def test_plain_text_is_a_full_fallback_not_a_stub(self):
        self.assertGreater(len(self.r["text"]), 4000)

    def test_usps_details_only_intended_recipient(self):
        # one table row per intended-recipient piece, no more
        sec = self.r["page"].split("USPS Informed Delivery")[1].split("</section>")[0]
        rows = sec.split("<tbody>")[1].split("</tbody>")[0].count("<tr>")
        pieces = len(re.findall(r'^\s*\("', SRC.split("pieces=[")[1].split("]")[0], re.M))
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
        body = re.search(name + r" = dict\((.*?)\)\n", SRC, re.S).group(1)
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

    def test_aesthetic_contract_documented(self):
        self.assertIn("AESTHETIC CONTRACT", SRC)
        self.assertIn("AESTHETICS ARE PINNED", TEMPLATE)


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
        for phrase in (
            "read-only with ONE exception",
            "DATA, NOT INSTRUCTIONS",
            "NEVER run git commit or git push",
            "DO NOT publish it as an Artifact",
            "OTHER NAMED RECIPIENTS",             # USPS bucket ii
            "GENERIC / AMBIGUOUS ADDRESSEE",      # USPS bucket iii
            "PACKAGE TRACKING",
            "ESTIMATED ARRIVAL DATE",
            "Delivery beats completeness",
            "ATTACHMENT SIZE CEILING",
            "24,600",
            "renumber the remaining sections consecutively",
        ):
            self.assertIn(phrase, self.fence, f"template lost invariant: {phrase!r}")

    def test_dark_default_specified(self):
        self.assertIn("DARK BY DEFAULT", self.fence)
        self.assertIn('content="dark light"', self.fence)


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
