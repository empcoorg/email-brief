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
class _BrowserCase(unittest.TestCase):
    """Shared browser fixture. Holds no tests of its own — subclass it rather
    than subclassing a populated test case, or every test in that case reruns
    under the subclass."""

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


class TestRendering(_BrowserCase):
    """Layout, theming and overflow for the standalone file and the email."""

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

    def test_email_axis_zero_sits_over_the_track_centre(self):
        """The email cannot position elements, so the axis is three equal cells.
        The centre label must still land on the track's centre — a label that
        disagrees with the geometry beneath it misreads the chart."""
        for width in (860, 390):
            pg = self._page(width, content=self.email_html)
            pairs = pg.evaluate("""() => {
                const out = [];
                for (const table of document.querySelectorAll('table')) {
                    // rows of THIS table only - querySelectorAll descends into the
                    // nested axis/bar tables and would return their rows too
                    const rows = [...table.querySelectorAll('tr')]
                        .filter(tr => tr.closest('table') === table);
                    const head = rows[0];
                    if (!head) continue;
                    for (const th of head.querySelectorAll('th')) {
                        const cells = th.querySelectorAll('td');
                        if (cells.length !== 3) continue;               // not an axis header
                        const zero = cells[1];
                        if (zero.textContent.trim() !== '0') continue;
                        const i = [...head.children].indexOf(th);
                        const row = rows[1];
                        const cell = row && row.children[i];
                        const track = cell && cell.querySelector('table');
                        if (!track) continue;
                        const z = zero.getBoundingClientRect(), t = track.getBoundingClientRect();
                        out.push({dz: (z.left + z.width / 2) - (t.left + t.width / 2)});
                    }
                }
                return out;
            }""")
            self.assertGreaterEqual(len(pairs), 4,
                                    f"expected market+crypto axis headers @{width}px, saw {len(pairs)}")
            for p_ in pairs:
                self.assertLessEqual(abs(p_["dz"]), 2.0,
                                     f"email axis 0 is {p_['dz']:.1f}px off the track centre @{width}px")
            pg.close()

    def test_email_tables_max_three_columns(self):
        counts = [len(m) for m in
                  (re.findall(r"<th\b", row) for row in
                   re.findall(r"<tr>(.*?)</tr>", self.email_html, re.S)) if m]
        self.assertTrue(all(c <= 3 for c in counts),
                        f"email data tables must have at most 3 columns, saw {max(counts or [0])}")


class TestBarGeometry(_BrowserCase):
    """Quantitative-chart guarantees for the diverging bars: fills anchored to
    the centre baseline, a visible bordered track, and the header axis ruler
    pixel-aligned with the bar column. Guards against helper shadowing or CSS
    drift that turns the charts into floating blobs."""

    def test_diverging_fills_anchored_to_centerline(self):
        pg = self._page(1280)
        bars = pg.evaluate("""() => [...document.querySelectorAll('.dbar')].map(b => {
            const r = b.getBoundingClientRect(), f = b.querySelector('.fill');
            const fr = f.getBoundingClientRect();
            return {w: r.width, center: r.left + r.width / 2,
                    fl: fr.left, fr_: fr.right, pos: f.className.includes('pos'),
                    neu: f.className.includes('neu'),
                    right: f.className.includes('right'),
                    border: getComputedStyle(b).borderTopWidth,
                    ticks: b.querySelectorAll('i').length};
        })""")
        self.assertGreaterEqual(len(bars), 10, "markets + crypto rows must carry .dbar tracks")
        for b in bars:
            anchor = b["fl"] if b["right"] else b["fr_"]
            self.assertLessEqual(abs(anchor - b["center"]), 1.6,
                                 f"fill not anchored to the centre baseline: {b}")
            if b["neu"]:
                continue  # internal transfer: magnitude only, colour implies no direction
            self.assertEqual(b["pos"], b["right"], "sign/side mismatch in bar fill")
            self.assertEqual(b["border"], "1px", "bar track must have a visible 1px border")
            # one notch per even step, symmetric about the centre line
            self.assertGreaterEqual(b["ticks"], 4, "bar track must carry micro-notch ticks")
            self.assertEqual(b["ticks"] % 2, 0, "ticks must be symmetric about 0")
        pg.close()

    def test_header_axis_aligned_with_bar_column(self):
        pg = self._page(1280)
        pairs = pg.evaluate("""() => {
            const out = [];
            for (const table of document.querySelectorAll('table')) {
                const axis = table.querySelector('thead .daxis');
                const bar = table.querySelector('tbody .dbar');
                if (!axis || !bar) continue;
                const a = axis.getBoundingClientRect(), b = bar.getBoundingClientRect();
                out.push({al: a.left, bl: b.left, aw: a.width, bw: b.width});
            }
            return out;
        }""")
        self.assertGreaterEqual(len(pairs), 2, "markets and crypto tables must pair axis with bars")
        for p in pairs:
            self.assertLessEqual(abs(p["al"] - p["bl"]), 1.6, f"axis not left-aligned with track: {p}")
            self.assertLessEqual(abs(p["aw"] - p["bw"]), 1.6, f"axis width differs from track: {p}")
        pg.close()

    def test_axis_labels_carry_units_and_dont_collide(self):
        pg = self._page(1280)
        axes = pg.evaluate("""() => [...document.querySelectorAll('thead .daxis')].map(a => {
            const spans = [...a.querySelectorAll('span')].filter(s => getComputedStyle(s).display !== 'none');
            const rects = spans.map(s => s.getBoundingClientRect());
            let overlap = false;
            for (let i = 1; i < rects.length; i++)
                if (rects[i].left < rects[i-1].right - 0.5) overlap = true;
            return {labels: spans.map(s => s.textContent), overlap};
        })""")
        self.assertGreaterEqual(len(axes), 2)
        for a in axes:
            self.assertTrue(any(l.endswith("%") or l.startswith("$") for l in a["labels"]),
                            f"axis labels must carry a unit (% or $): {a['labels']}")
            self.assertFalse(a["overlap"], f"axis labels collide: {a['labels']}")
        pg.close()

    def test_axis_aligns_with_track_at_every_width(self):
        """The ruler's 0 must fall on the track's centre at every width. At phone
        width the header collapses and the ruler repeats below the table, where
        it has to inset by the cell padding or it is wider than the bars."""
        for width in (1280, 1024, 768):
            pg = self._page(width)
            pairs = pg.evaluate("""() => {
                const out = [];
                for (const t of document.querySelectorAll('table')) {
                    for (const ax of t.querySelectorAll('thead .daxis')) {
                        if (ax.getBoundingClientRect().width === 0) continue;
                        const th = ax.closest('th');
                        const i = [...th.parentNode.children].indexOf(th);
                        for (const tr of t.querySelectorAll('tbody tr')) {
                            const bar = tr.children[i] && tr.children[i].querySelector('.dbar');
                            if (!bar) continue;
                            const a = ax.getBoundingClientRect(), r = bar.getBoundingClientRect();
                            const z = [...ax.querySelectorAll('span')].find(s => s.textContent.trim() === '0');
                            const zc = z ? z.getBoundingClientRect().left + z.getBoundingClientRect().width / 2 : null;
                            out.push({dl: a.left - r.left, dw: a.width - r.width,
                                      dz: zc === null ? 0 : zc - (r.left + r.width / 2)});
                        }
                    }
                }
                return out;
            }""")
            self.assertGreaterEqual(len(pairs), 10, f"no axis/track pairs found @{width}px")
            for p_ in pairs:
                self.assertLessEqual(abs(p_["dl"]), 1.6, f"ruler offset from track @{width}px: {p_}")
                self.assertLessEqual(abs(p_["dw"]), 1.6, f"ruler width differs @{width}px: {p_}")
                self.assertLessEqual(abs(p_["dz"]), 1.6, f"axis 0 misses track centre @{width}px: {p_}")
            pg.close()

        # phone: the repeated ruler under the table must match the track width
        pg = self._page(390)
        feet = pg.evaluate("""() => [...document.querySelectorAll('.daxis-foot')]
            .filter(f => f.getBoundingClientRect().width > 0)
            .map(f => {
                const a = f.querySelector('.daxis').getBoundingClientRect();
                const tbl = f.closest('.card').querySelector('.dbar');
                const r = tbl.getBoundingClientRect();
                return {dl: a.left - r.left, dw: a.width - r.width};
            })""")
        self.assertGreaterEqual(len(feet), 1, "phone width must repeat the ruler below the table")
        for f in feet:
            self.assertLessEqual(abs(f["dl"]), 2.5, f"phone ruler offset from tracks: {f}")
            self.assertLessEqual(abs(f["dw"]), 2.5, f"phone ruler width differs from tracks: {f}")
        pg.close()

    def test_money_bars_direction_colored_with_axis(self):
        pg = self._page(1280)
        r = pg.evaluate("""() => {
            const toRGB = h => { const n = parseInt(h.slice(1), 16);
                return `rgb(${n >> 16}, ${(n >> 8) & 255}, ${n & 255})`; };
            const out = {fills: [], axis: null};
            for (const b of document.querySelectorAll('.dbar.money')) {
                const f = b.querySelector('.fill');
                out.fills.push({cls: f.className, color: getComputedStyle(f).backgroundColor,
                                border: getComputedStyle(b).borderTopWidth,
                                ticks: b.querySelectorAll('i').length});
            }
            const cs = getComputedStyle(document.documentElement);
            out.pos = cs.getPropertyValue('--positive').trim();
            out.neg = cs.getPropertyValue('--negative').trim();
            const table = [...document.querySelectorAll('table')].find(t => t.querySelector('tbody .dbar.money'));
            const axis = table && table.querySelector('thead .daxis');
            const bar = table && table.querySelector('tbody .dbar.money');
            if (axis && bar) {
                const a = axis.getBoundingClientRect(), c = bar.getBoundingClientRect();
                out.axis = {dl: Math.abs(a.left - c.left), dw: Math.abs(a.width - c.width),
                            labels: [...axis.querySelectorAll('span')].map(s => s.textContent)};
            }
            return out;
        }""")
        self.assertGreaterEqual(len(r["fills"]), 3)
        def rgb(h):
            n = int(h.lstrip("#"), 16)
            return f"rgb({n >> 16}, {(n >> 8) & 255}, {n & 255})"
        for f in r["fills"]:
            self.assertEqual(f["border"], "1px", "money track must have a visible border")
            self.assertGreaterEqual(f["ticks"], 4, "money track must carry micro-notch ticks")
            self.assertEqual(f["ticks"] % 2, 0, "money ticks must be symmetric about 0")
            cls = f["cls"].split()
            if "pos" in cls:
                self.assertEqual(f["color"], rgb(r["pos"]), "money-in fill must be the positive token")
                self.assertIn("right", cls, "money in must sit right of the centre line")
            if "neg" in cls:
                self.assertEqual(f["color"], rgb(r["neg"]), "money-out fill must be the negative token")
                self.assertIn("left", cls, "money out must sit left of the centre line")
        self.assertIsNotNone(r["axis"], "money table must pair a header axis with its bars")
        self.assertLessEqual(r["axis"]["dl"], 1.6); self.assertLessEqual(r["axis"]["dw"], 1.6)
        self.assertEqual(r["axis"]["labels"], ["−$3k", "0", "$3k"],
                         "money axis must label even breaks either side of a centred 0")
        self.assertTrue(any(l.startswith("$") for l in r["axis"]["labels"]),
                        "money axis labels must carry $ units")
        pg.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
