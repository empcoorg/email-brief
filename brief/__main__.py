"""Command line: validate a payload and write the three outputs.

    python3 -m brief render payload.json --out-dir /mnt/user-data/outputs
    python3 -m brief validate payload.json

`render` writes morning-brief-<date>.html, email.html and email.txt, then
prints the paths and the email's size against the 85 KB send budget.
`validate` checks the payload and says what is wrong, without rendering.
"""
import argparse
import os
import sys

from .model import PayloadError, load
from .render import render_all

EMAIL_BUDGET = 85 * 1024   # Gmail clips ~102 KB and its sanitizer inflates ~12%


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m brief", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="validate a payload and write the outputs")
    r.add_argument("payload")
    r.add_argument("--out-dir", default=".", help="where to write the three files")
    r.add_argument("--date", default=None, help="date stamp for the file name (YYYY-MM-DD)")
    v = sub.add_parser("validate", help="check a payload without rendering")
    v.add_argument("payload")
    a = ap.parse_args(argv)

    try:
        payload = load(a.payload)
    except PayloadError as ex:
        print(f"payload invalid: {ex}", file=sys.stderr)
        return 2

    if a.cmd == "validate":
        print(f"{a.payload}: valid ({len(payload)} keys)")
        return 0

    fh, eh, pt = render_all(payload)
    os.makedirs(a.out_dir, exist_ok=True)
    stamp = a.date or payload["MAST"].get("file_date") or "brief"
    page = os.path.join(a.out_dir, f"morning-brief-{stamp}.html")
    email = os.path.join(a.out_dir, "email.html")
    text = os.path.join(a.out_dir, "email.txt")
    for path, body in ((page, fh), (email, eh), (text, pt)):
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)

    size = len(eh.encode("utf-8"))
    print(f"wrote {page}")
    print(f"wrote {email}  ({size:,} B of the {EMAIL_BUDGET:,} B send budget)")
    print(f"wrote {text}")
    if size > EMAIL_BUDGET:
        print(f"WARNING: email body is {size - EMAIL_BUDGET:,} B over budget — "
              "Gmail will clip it. Shorten sections or drop embedded scans.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
