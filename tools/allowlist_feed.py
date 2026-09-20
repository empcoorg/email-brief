#!/usr/bin/env python3
"""Feed the allowlist into claude.ai one domain at a time, without retyping.

The panel — Settings -> Capabilities -> Allow network egress -> Domain
allowlist -> "Additional allowed domains" — takes ONE domain per Add. The
"or" in its placeholder is showing two accepted formats, not a separator: a
line of domains joined by "or" is refused as a whole.

So this walks the list, putting each entry on the clipboard in turn:

    python3 tools/allowlist_feed.py

For each one: paste into the field (Cmd-V), press Add, then press Return here
for the next. Ctrl-C stops; run it again with --from <domain> to pick up where
you left off. It reads docs/egress-allowlist-core.txt by default, which is the
short wildcard list; pass a path to feed any other file.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(ROOT, "docs", "egress-allowlist-core.txt")


def entries(path):
    with open(path, encoding="utf-8") as fh:
        return [l.strip() for l in fh if l.strip() and not l.startswith("#")]


def copy(text):
    """Onto the clipboard, on whichever of the three platforms this is."""
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"],
                ["clip.exe"]):
        try:
            subprocess.run(cmd, input=text.encode(), check=True)
            return True
        except (OSError, subprocess.CalledProcessError):
            continue
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", nargs="?", default=DEFAULT)
    ap.add_argument("--from", dest="start", help="resume at this domain")
    a = ap.parse_args(argv)
    items = entries(a.path)
    if a.start:
        rest = [i for i, d in enumerate(items) if d.lstrip("*.") == a.start.lstrip("*.")]
        if not rest:
            print(f"{a.start} is not in {os.path.basename(a.path)}", file=sys.stderr)
            return 2
        items = items[rest[0]:]
    print(f"{len(items)} domains from {os.path.basename(a.path)}. For each: "
          "paste into the field, press Add, then Return here.\n")
    for n, domain in enumerate(items, 1):
        if not copy(domain):
            print(f"  (no clipboard tool found — type it) {n:>2}/{len(items)}  {domain}")
        else:
            print(f"  {n:>2}/{len(items)}  {domain}   [copied]", end="", flush=True)
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            print(f"\nstopped at {domain} — resume with --from {domain}")
            return 0
    print("\nall of them are in. A run that is still refused a host wants the "
          "long list: docs/egress-allowlist.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
