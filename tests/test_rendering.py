"""Browser rendering tests: the brief must not break on desktop or mobile.

Optional suite — requires Playwright and a Chromium binary:

    pip install playwright
    python3 -m unittest tests.test_rendering -v

Chromium is found via $BRIEF_CHROMIUM, /opt/pw-browsers/chromium, or
Playwright's own installation; the whole module skips if none launches.
Checks: no horizontal overflow at desktop and phone widths, mobile
table-to-card collapse, the mailpiece scan staying inside its card,
dark-by-default theming with light/system/forced overrides, and the
email layout staying fluid down to phone width.
"""
import os
import re
import unittest

from test_email_brief import ROOT, render_once

try:
    from playwright.sync_api import sync_playwright
    _HAVE_PW = True
except ImportError:
    _HAVE_PW = False


def _launch(p):
    for exe in (os.environ.get("BRIEF_CHROMIUM"), "/opt/pw-browsers/chromium", None):
        if exe is not None and not os.path.exists(exe):
            continue
        try:
            return p.chromium.launch(executable_path=exe)
        except Exception:
            continue
    return None


@unittest.skipUnless(_HAVE_PW, "playwright not installed (pip install playwright)")
class TestRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = render_once()
        cls.page_html, cls.email_html = r["page"], r["email"]
        cls._pw = sync_playwright().start()
        cls.browser = _launch(cls._pw)
        if cls.browser is None:
            cls._pw.stop()
            raise unittest.SkipTest("no launchable Chromium found")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "browser", None):
            cls.browser.close()
            cls._pw.stop()

    def _page(self, width, height=900, scheme="dark", content=None):
        pg = self.browser.new_page(viewport={"width": width, "height": height},
                                   color_scheme=scheme)
        if content is None:
            pg.set_content(self.page_html, wait_until="load")
        else:
            pg.set_content(content, wait_until="load")
        pg.wait_for_timeout(300)
        return pg

    def _assert_no_horizontal_overflow(self, pg, width, what):
        sw = pg.evaluate("document.documentElement.scrollWidth")
        self.assertLessEqual(sw, width + 1, f"{what}: horizontal overflow ({sw}px > {width}px viewport)")

    # ---- the standalone HTML file ----

    def test_desktop_renders_without_breaking(self):
        pg = self._page(1280)
        self._assert_no_horizontal_overflow(pg, 1280, "file @1280")
        self.assertEqual(pg.locator("section").count() >= 8, True)
        self.assertGreater(pg.evaluate("document.body.scrollHeight"), 3000,
                           "page suspiciously short — did a section fail to render?")
        pg.close()

    def test_mobile_renders_without_breaking(self):
        pg = self._page(390)
        self._assert_no_horizontal_overflow(pg, 390, "file @390 (phone)")
        pg.close()

    def test_tablet_renders_without_breaking(self):
        pg = self._page(768)
        self._assert_no_horizontal_overflow(pg, 768, "file @768 (tablet)")
        pg.close()

    def test_mobile_tables_collapse_to_cards(self):
        pg = self._page(390)
        thead = pg.evaluate(
            "getComputedStyle(document.querySelector('table thead')).display")
        self.assertEqual(thead, "none", "on phones, table headers must hide (card layout)")
        td = pg.evaluate(
            "getComputedStyle(document.querySelector('table td')).display")
        self.assertEqual(td, "block", "on phones, table cells must stack as blocks")
        pg.close()

    def test_scan_image_fits_its_card(self):
        for width in (1280, 390):
            pg = self._page(width)
            fits = pg.evaluate("""() => {
                const img = document.querySelector('.scanfig img');
                if (!img) return 'missing';
                const card = img.closest('.card');
                return img.getBoundingClientRect().width <= card.getBoundingClientRect().width + 1;
            }""")
            self.assertTrue(fits is True, f"scan image overflows its card at {width}px ({fits})")
            pg.close()

    def test_theme_dark_by_default_light_on_preference(self):
        cases = [("dark", "rgb(14, 20, 23)"), ("light", "rgb(244, 246, 247)")]
        for scheme, expect in cases:
            pg = self._page(1280, scheme=scheme)
            bg = pg.evaluate("getComputedStyle(document.body).backgroundColor")
            self.assertEqual(bg, expect, f"system {scheme} should give body bg {expect}")
            pg.close()

    def test_theme_forced_overrides_beat_system(self):
        for forced, opposite, expect in (("dark", "light", "rgb(14, 20, 23)"),
                                         ("light", "dark", "rgb(244, 246, 247)")):
            pg = self._page(1280, scheme=opposite)
            pg.evaluate(f"document.documentElement.setAttribute('data-theme','{forced}')")
            bg = pg.evaluate("getComputedStyle(document.body).backgroundColor")
            self.assertEqual(bg, expect, f"data-theme={forced} must override system {opposite}")
            pg.close()

    def test_everything_visible_at_rest(self):
        pg = self._page(1280)
        hidden = pg.evaluate("""() => [...document.querySelectorAll('section, .card')]
            .filter(el => getComputedStyle(el).display === 'none').length""")
        self.assertEqual(hidden, 0, "no section/card may be hidden at rest")
        pg.close()

    # ---- the email layout ----

    def test_email_fluid_on_phone_and_desktop(self):
        for width in (860, 390):
            pg = self._page(width, content=self.email_html)
            self._assert_no_horizontal_overflow(pg, width, f"email @{width}")
            pg.close()

    def test_email_tables_max_three_columns(self):
        counts = [len(m) for m in
                  (re.findall(r"<th\b", row) for row in
                   re.findall(r"<tr>(.*?)</tr>", self.email_html, re.S)) if m]
        self.assertTrue(all(c <= 3 for c in counts),
                        f"email data tables must have at most 3 columns, saw {max(counts or [0])}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
