"""Command line: validate a payload and write the three outputs.

    python3 -m brief render payload.json --out-dir /mnt/user-data/outputs
    python3 -m brief validate payload.json

`render` writes morning-brief-<date>.html, email.html and email.txt, then
prints the paths, the email's size against the 85 KB send budget, and what one
send call would have to carry. `validate` checks the payload and says what is
wrong, without rendering. `carry` answers the question that actually blocks a
send: does the whole message fit in a single tool call?
"""
import argparse
import os
import sys

from .model import PayloadError, load
from .render import render_all, split_for_send

EMAIL_BUDGET = 85 * 1024   # Gmail clips ~102 KB and its sanitizer inflates ~12%


def _check_attachments(paths):
    """Would each file survive the send path, or be silently truncated?"""
    from .attachments import check, max_bytes
    bad = 0
    for path in paths:
        try:
            ok, _chars, msg = check(path)
        except OSError as ex:
            print(f"{path}: {ex}", file=sys.stderr)
            bad += 1
            continue
        print(f"{'OK  ' if ok else 'OVER'} {path}: {msg}")
        bad += 0 if ok else 1
    if bad:
        print(f"{bad} attachment(s) would be silently truncated by the send path. "
              f"Re-encode to at most {max_bytes():,} B each.", file=sys.stderr)
        return 4
    return 0


def _check_carry(out_dir, files):
    """Would one send call fit? The body budget alone does not answer that."""
    from .attachments import CARRY_BUDGET_CHARS, carry_cost
    try:
        html = open(os.path.join(out_dir, "email.html"), encoding="utf-8").read()
        text = open(os.path.join(out_dir, "email.txt"), encoding="utf-8").read()
    except OSError as ex:
        print(f"{ex} \u2014 run `render --out-dir {out_dir}` first", file=sys.stderr)
        return 2
    total, rows, ok = carry_cost(html, text, files)
    for label, n in rows:
        print(f"  {n:>9,}  {label}")
    print(f"  {total:>9,}  TOTAL for one send call (budget {CARRY_BUDGET_CHARS:,})")
    if ok:
        return 0
    print(f"OVER by {total - CARRY_BUDGET_CHARS:,} characters. One send call has to carry all of "
          "this at once, and the brief sends exactly once \u2014 a truncated send cannot be corrected. "
          "Shed cards, shorten the payload, or send fewer scans, and say in the chat reply what "
          "was left out. Do NOT downgrade the HTML to plain text.", file=sys.stderr)
    return 5


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m brief", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="validate a payload and write the outputs")
    r.add_argument("payload")
    r.add_argument("--out-dir", default=".", help="where to write the three files")
    r.add_argument("--date", default=None, help="date stamp for the file name (YYYY-MM-DD)")
    v = sub.add_parser("validate", help="check a payload without rendering")
    v.add_argument("payload")
    g = sub.add_parser("significant",
                       help="does this payload justify an extra send? exit 0 yes, 3 no")
    g.add_argument("payload")
    cr = sub.add_parser("carry",
                        help="does the whole message fit one send call? exit 0 yes, 5 no")
    cr.add_argument("--out-dir", default=".", help="directory holding email.html and email.txt")
    cr.add_argument("files", nargs="*", help="attachments the send will include")
    at = sub.add_parser("attachment",
                        help="will this file survive the send path? exit 0 yes, 4 no")
    at.add_argument("files", nargs="+")
    a = ap.parse_args(argv)

    if a.cmd == "attachment":
        return _check_attachments(a.files)

    if a.cmd == "carry":
        return _check_carry(a.out_dir, a.files)

    try:
        payload = load(a.payload)
    except PayloadError as ex:
        print(f"payload invalid: {ex}", file=sys.stderr)
        return 2

    if a.cmd == "significant":
        from .significance import reasons
        why = reasons(payload)
        if why:
            print(f"SEND — {len(why)} reason(s):")
            for r in why:
                print(f"  · {r}")
            return 0
        print("SKIP — nothing in this window meets the bar for an extra send.")
        return 3

    if a.cmd == "validate":
        print(f"{a.payload}: valid ({len(payload)} keys)")
        return 0

    from .render import build_marker
    marker = build_marker(payload)
    # The stamp is decided before rendering: the email names the standalone
    # file, so that name has to be the file actually written.
    stamp = a.date or payload["MAST"].get("file_date") or "brief"
    fh, eh, pt = render_all(payload, stamp=stamp)
    os.makedirs(a.out_dir, exist_ok=True)
    page = os.path.join(a.out_dir, f"morning-brief-{stamp}.html")
    email = os.path.join(a.out_dir, "email.html")
    text = os.path.join(a.out_dir, "email.txt")
    for path, body in ((page, fh), (email, eh), (text, pt)):
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)

    # The send tool takes the body as an inline string, so the run has to carry
    # ~85 KB through its context. Split it here rather than leaving the run to
    # invent a chunking scheme mid-send: parts concatenate back byte for byte.
    parts = split_for_send(eh)
    for n, part in enumerate(parts, 1):
        with open(os.path.join(a.out_dir, f"email.part{n:02d}.html"), "w",
                  encoding="utf-8") as f:
            f.write(part)

    size = len(eh.encode("utf-8"))
    print(f"wrote {page}")
    print(f"wrote {email}  ({size:,} B of the {EMAIL_BUDGET:,} B send budget)")
    print(f"wrote {text}")
    print(f"wrote email.part01..{len(parts):02d}.html — read these in order and "
          f"concatenate them with no separator to rebuild the htmlBody exactly; "
          f"do not read {os.path.basename(email)} itself, it exceeds the read cap.")
    from .attachments import CARRY_BUDGET_CHARS, carry_cost
    carried, _rows, _ok = carry_cost(eh, pt)
    print(f"one send call must carry {carried:,} chars before attachments "
          f"(htmlBody {len(eh):,} + plain text {len(pt):,}) of the "
          f"{CARRY_BUDGET_CHARS:,} carry budget; each scan adds its base64 length. "
          f"Check the real total with: python3 -m brief carry --out-dir {a.out_dir} <scan.jpg>")
    print(f"build {marker} — this marker appears in all three outputs. Quote it "
          "when you report the run; a brief without it did not come from here.")
    if size > EMAIL_BUDGET:
        print(f"WARNING: email body is {size - EMAIL_BUDGET:,} B over budget — "
              "Gmail will clip it. Shorten sections or drop embedded scans.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
