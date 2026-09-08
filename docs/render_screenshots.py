#!/usr/bin/env python3
"""Regenerate the README screenshots from build_brief.py's mock data.

Run from the repo root after any design-affecting change (see README):
    pip install playwright   # Chromium must be available to Playwright
    python3 docs/render_screenshots.py
Writes docs/mock-brief-top.png, docs/mock-brief-jobs.png,
docs/mock-brief-sections.png and docs/mock-brief-markets.png (all dark mode).
"""
import asyncio, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")

async def main():
    from playwright.async_api import async_playwright
    with tempfile.TemporaryDirectory() as td:
        gen = os.path.join(td, "gen.py")
        src = open(os.path.join(ROOT, "build_brief.py")).read()
        open(gen, "w").write(re.sub(r'^OUT_DIR = .*$', f'OUT_DIR = "{td}"', src, count=1, flags=re.M))
        subprocess.run([sys.executable, gen], cwd=td, check=True, capture_output=True)
        page_html = next(os.path.join(td, f) for f in os.listdir(td) if f.startswith("morning-brief"))
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=os.environ.get("BRIEF_CHROMIUM", "/opt/pw-browsers/chromium") if os.path.exists(os.environ.get("BRIEF_CHROMIUM", "/opt/pw-browsers/chromium")) else None)
            pg = await b.new_page(viewport={"width": 1180, "height": 1000}, color_scheme="dark", device_scale_factor=2)
            await pg.goto("file://" + page_html)
            await pg.wait_for_timeout(1500)  # let fonts settle
            # Top: masthead + action bar
            bar = await pg.query_selector("main > div, .actions, body")
            h = await pg.evaluate("() => { const s = document.querySelectorAll('section'); return s.length > 1 ? s[1].getBoundingClientRect().top + window.scrollY : 1200; }")
            await pg.screenshot(path=os.path.join(DOCS, "mock-brief-top.png"), clip={"x": 0, "y": 0, "width": 1180, "height": min(int(h), 2200)})
            # Section 1: relevant job posts (ranked table with badges + legend)
            secs = await pg.query_selector_all("section")
            jobs = None
            for s in secs:
                txt = (await s.inner_text())[:120].lower()
                if "job posts" in txt:
                    jobs = s
                    break
            if jobs:
                await jobs.screenshot(path=os.path.join(DOCS, "mock-brief-jobs.png"))
            # Section 2: finances (money table, bars, tiles)
            target = None
            for s in secs:
                txt = (await s.inner_text())[:120].lower()
                if "deposits" in txt and "finances" in txt:
                    target = s
                    break
            if target is None and secs:
                target = secs[1] if len(secs) > 1 else secs[0]
            await target.screenshot(path=os.path.join(DOCS, "mock-brief-sections.png"))
            # Research grid: US market + crypto cards (union bounding box)
            rect = await pg.evaluate("""() => {
                const cards = [...document.querySelectorAll('.card')];
                const pick = t => cards.find(c => (c.querySelector('h2')||{}).textContent?.trim().toLowerCase().startsWith(t));
                const m = pick('us market'), c = pick('crypto');
                if (!m || !c) return null;
                const a = m.getBoundingClientRect(), b = c.getBoundingClientRect(), y = window.scrollY, x = window.scrollX;
                const left = Math.min(a.left, b.left) + x, top = Math.min(a.top, b.top) + y;
                const right = Math.max(a.right, b.right) + x, bottom = Math.max(a.bottom, b.bottom) + y;
                return {x: Math.max(0, left - 8), y: Math.max(0, top - 8), width: right - left + 16, height: bottom - top + 16};
            }""")
            if rect:
                await pg.screenshot(path=os.path.join(DOCS, "mock-brief-markets.png"), clip=rect, full_page=True)
            await b.close()
    print("wrote mock-brief-top/jobs/sections/markets PNGs (dark mode)")

asyncio.run(main())
