#!/usr/bin/env python3
"""Render the sample brief from sample_payload.json.

This used to be the whole system: 890 lines of interleaved mock data and layout
code, mirroring a design spec that also existed as prose in the Routine prompt.
The two drifted, because only one of them was executable.

Now the layout lives in the `brief` package (tested), the sample data lives in
sample_payload.json (data, not code), and this file is the thin wrapper that
joins them — kept so `python3 build_brief.py` and docs/render_screenshots.py
work exactly as before.

    python3 build_brief.py                     # -> ./out (or $BRIEF_OUT_DIR)
    python3 -m brief render payload.json --out-dir DIR   # the real entry point
"""
import os
import sys

from brief import load, render_all

OUT_DIR = os.environ.get("BRIEF_OUT_DIR", "/mnt/user-data/outputs")
SCRATCH = os.path.dirname(os.path.abspath(__file__))
try:
    os.makedirs(OUT_DIR, exist_ok=True)
except OSError:  # not the Claude sandbox (e.g. a dev laptop) — write beside the script
    OUT_DIR = os.path.join(SCRATCH, "out")
    os.makedirs(OUT_DIR, exist_ok=True)

PAYLOAD = os.path.join(SCRATCH, "sample_payload.json")
FILE_DATE = "2026-09-07"

if __name__ == "__main__":
    fh, eh, pt = render_all(load(PAYLOAD))
    page = os.path.join(OUT_DIR, f"morning-brief-{FILE_DATE}.html")
    open(page, "w", encoding="utf-8").write(fh)
    open(os.path.join(SCRATCH, "email.html"), "w", encoding="utf-8").write(eh)
    open(os.path.join(SCRATCH, "email.txt"), "w", encoding="utf-8").write(pt)
    print(f"file {len(fh)} B -> {OUT_DIR}; email {len(eh)} B, text {len(pt)} B -> {SCRATCH}")
