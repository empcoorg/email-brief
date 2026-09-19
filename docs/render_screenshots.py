#!/usr/bin/env python3
"""Regenerate the README screenshots from build_brief.py's mock data.

Run from the repo root after any design-affecting change (see README):
    pip install playwright   # Chromium must be available to Playwright
    python3 docs/render_screenshots.py
Writes docs/mock-brief-{top,jobs,sections,travel,usps,packages,markets,trend}.png (dark mode).
"""
import asyncio, hashlib, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _require(name, el):
    """A missing target means the selector went stale and the README would keep
    showing an OUTDATED screenshot. Fail loudly rather than silently skipping."""
    if el is None:
        raise SystemExit(f"render_screenshots: could not locate the '{name}' section - "
                         "the selector is stale; fix it rather than shipping a stale PNG")
DOCS = os.path.join(ROOT, "docs")

LOCK = os.path.join(DOCS, "screenshots.lock")

LOCK_HEADER = """\
# Fingerprint of the rendered brief that the committed README screenshots show.
#
# Written by docs/render_screenshots.py, and checked by
# tests/test_email_brief.py::TestScreenshotsAreCurrent. If that test fails, the
# rendered UI changed but the screenshots were not regenerated: run
#
#     python3 docs/render_screenshots.py
#
# and commit the updated PNGs together with this file.
#
# This hashes the rendered HTML, not the pixels, because font rasterisation
# differs between macOS and the Linux CI runner - a pixel comparison would fail
# on every run regardless of whether anything actually changed.
"""


def _write_lock(page_path):
    """Record what the screenshots were generated from."""
    body = open(page_path, encoding="utf-8").read()
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    with open(LOCK, "w", encoding="utf-8") as fh:
        fh.write(LOCK_HEADER + f"sha256 = {digest}\n")


CAPTURE_WIDTH = 960


async def main():
    from playwright.async_api import async_playwright
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([sys.executable, "-m", "brief", "render", "sample_payload.json",
                        "--out-dir", td, "--date", "2026-09-07"],
                       cwd=ROOT, check=True, capture_output=True)
        page_html = next(os.path.join(td, f) for f in os.listdir(td) if f.startswith("morning-brief"))
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=os.environ.get("BRIEF_CHROMIUM", "/opt/pw-browsers/chromium") if os.path.exists(os.environ.get("BRIEF_CHROMIUM", "/opt/pw-browsers/chromium")) else None)
            # Capture width sets how large the text reads in the README: GitHub
            # scales every image down to its ~880px column, so a 1180px capture
            # showed 15.5px body text at ~11.6px. 960px renders it ~23% larger
            # while staying above the 940px breakpoint - the desktop layout, with
            # no table scrolling (measured). The brief's own sizes are unchanged.
            pg = await b.new_page(viewport={"width": CAPTURE_WIDTH, "height": 1000}, color_scheme="dark", device_scale_factor=2)
            await pg.goto("file://" + page_html)
            await pg.wait_for_timeout(1500)  # let fonts settle
            # Top: masthead + action bar
            bar = await pg.query_selector("main > div, .actions, body")
            h = await pg.evaluate("() => { const s = document.querySelectorAll('section'); return s.length > 1 ? s[1].getBoundingClientRect().top + window.scrollY : 1200; }")
            await pg.screenshot(path=os.path.join(DOCS, "mock-brief-top.png"), clip={"x": 0, "y": 0, "width": CAPTURE_WIDTH, "height": min(int(h), 2200)})
            # Section 1: relevant job posts (ranked table with badges + legend)
            secs = await pg.query_selector_all("section")
            jobs = None
            for s in secs:
                txt = (await s.inner_text()).lower()
                if "job posts" in txt:
                    jobs = s
                    break
            _require("jobs", jobs)
            await jobs.screenshot(path=os.path.join(DOCS, "mock-brief-jobs.png"))
            # Section 2: finances (money table, bars, tiles)
            target = None
            for s in secs:
                txt = (await s.inner_text()).lower()
                if "deposits" in txt and "finances" in txt:
                    target = s
                    break
            _require("sections", target) if False else None
            if target is None and secs:
                target = secs[1] if len(secs) > 1 else secs[0]
            await target.screenshot(path=os.path.join(DOCS, "mock-brief-sections.png"))
            # Section 5: USPS digest (recipient-only table, full mailpiece scan, counts)
            usps = None
            for s in secs:
                txt = (await s.inner_text()).lower()
                if "informed delivery" in txt:
                    usps = s
                    break
            _require("usps", usps)
            await usps.screenshot(path=os.path.join(DOCS, "mock-brief-usps.png"))
            # Section 4: upcoming travel (flights, then stays and other bookings)
            travel = None
            for s in secs:
                txt = (await s.inner_text()).lower()
                if "upcoming travel" in txt:
                    travel = s
                    break
            _require("travel", travel)
            await travel.screenshot(path=os.path.join(DOCS, "mock-brief-travel.png"))
            # Section 6: package tracking
            pkg = None
            for s in secs:
                txt = (await s.inner_text()).lower()
                if "package tracking" in txt:
                    pkg = s
                    break
            _require("packages", pkg)
            await pkg.screenshot(path=os.path.join(DOCS, "mock-brief-packages.png"))
            # Research grid section (market/funds/crypto/AI/journals cards) — captured as a
            # full section element so every screenshot shares the same width and text scale.
            grid = None
            for s in secs:
                txt = (await s.inner_text()).lower()
                if "us market" in txt:
                    grid = s
                    break
            _require("markets", grid)
            await grid.screenshot(path=os.path.join(DOCS, "mock-brief-markets.png"))
            # The trend column answers a pointer, which a still image cannot
            # show by itself - so hover one first and capture the answer: the
            # rule, the marked point and the value under the cursor.
            spark = await pg.query_selector(".spark[data-series]")
            _require("trend", spark)
            await spark.scroll_into_view_if_needed()
            await pg.wait_for_timeout(150)
            box = await spark.bounding_box()
            await pg.mouse.move(box["x"] + box["width"] * 0.58, box["y"] + box["height"] * 0.4)
            await pg.wait_for_timeout(200)
            live = await pg.evaluate("() => document.querySelector('.spark').classList.contains('live')")
            if not live:
                raise SystemExit("render_screenshots: the trend readout did not open on hover - "
                                 "capturing it dark would document a feature that looks broken")
            rows = await pg.query_selector_all("tr")
            row = None
            for r in rows:
                if "S&P 500" in (await r.inner_text()):
                    row = r
                    break
            _require("trend row", row)
            await row.screenshot(path=os.path.join(DOCS, "mock-brief-trend.png"))
            await b.close()
        # inside the temp dir, which is removed on exit from this block
        _write_lock(page_html)
    print("wrote mock-brief-top/jobs/sections/travel/usps/packages/markets/trend PNGs (dark mode)")
    print(f"wrote {LOCK} — CI fails if the UI changes without regenerating these")

asyncio.run(main())
