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
from .render import render_all, split_for_send

from .render import EMAIL_BUDGET_BYTES as EMAIL_BUDGET  # Gmail clips ~102 KB


def _check_attachments(paths, out_dir=None):
    """Would each file survive the send path, and does the WHOLE call fit?

    Two different limits. Each attachment must stay under the per-file ceiling
    or the send path truncates it silently. Separately, htmlBody + the text body
    + every attachment travel as inline arguments in ONE tool call, and that
    call has its own ceiling - which is what a run means when it reports the
    payload was "too large to send in one call".
    """
    from .attachments import (check, max_bytes, b64_chars, call_bytes,
                              SEND_CALL_BYTES)
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

    if out_dir:
        try:
            html = os.path.getsize(os.path.join(out_dir, "email.html"))
            text = os.path.getsize(os.path.join(out_dir, "email.txt"))
        except OSError as ex:
            print(f"cannot size the rendered email: {ex}", file=sys.stderr)
            return 4
        sizes = [os.path.getsize(p) for p in paths]
        total = call_bytes(html, text, sizes)
        print(f"\nwhole send call: htmlBody {html:,} + text {text:,} + "
              f"{len(sizes)} attachment(s) {sum(b64_chars(n) for n in sizes):,} "
              f"(base64) = {total:,} B of {SEND_CALL_BYTES:,}")
        if total > SEND_CALL_BYTES:
            over = total - SEND_CALL_BYTES
            print(f"OVER BY {over:,} B — this call will be refused as too large "
                  f"to send at once.\nRe-render with the scans accounted for:\n"
                  f"  python3 -m brief render payload.json --out-dir {out_dir} "
                  f"--scans {' '.join(paths)}\nThe email will shed its least "
                  f"actionable cards to make room and say so; the standalone "
                  f"file still carries everything.", file=sys.stderr)
            return 4
        print("OK   the whole call fits in one send")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m brief", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="validate a payload and write the outputs")
    r.add_argument("payload")
    r.add_argument("--out-dir", default=".", help="where to write the three files")
    r.add_argument("--date", default=None, help="date stamp for the file name (YYYY-MM-DD)")
    r.add_argument("--email-budget", type=int, default=None, metavar="BYTES",
                   help="max HTML body before cards are shed (default 85 KB; "
                        "past ~85 KB Gmail clips rather than rejects)")
    r.add_argument("--send-budget", type=int, default=None, metavar="BYTES",
                   help="max total for one send call: HTML + text + attachments")
    r.add_argument("--scans", nargs="*", default=[], metavar="JPG",
                   help="mailpiece scans that will ride along in the same send "
                        "call; the email body budget shrinks to make room")
    v = sub.add_parser("validate", help="check a payload without rendering")
    v.add_argument("payload")
    g = sub.add_parser("significant",
                       help="does this payload justify an extra send? exit 0 yes, 3 no")
    g.add_argument("payload")
    at = sub.add_parser("attachment",
                        help="will this file survive the send path? exit 0 yes, 4 no")
    at.add_argument("files", nargs="+")
    at.add_argument("--out-dir", help="also check the whole send call against "
                                      "the rendered email in this directory")
    a = ap.parse_args(argv)

    if a.cmd == "attachment":
        return _check_attachments(a.files, a.out_dir)

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
    if a.send_budget:
        os.environ["BRIEF_SEND_CALL_BYTES"] = str(a.send_budget)
    fh, eh, pt = render_all(payload, a.email_budget)

    # The scans ride in the SAME send call as the body, so they take their room
    # out of the HTML. Render once to learn the text size, then re-render the
    # email against what is actually left. Shedding a card is recoverable; a
    # send refused for being too large is not - the run gets one attempt.
    if a.scans:
        from .attachments import html_room
        sizes = [os.path.getsize(s_) for s_ in a.scans]
        room = html_room(len(pt.encode("utf-8")), sizes,
                         a.send_budget or None)
        if a.email_budget:
            room = min(room, a.email_budget)
        if len(eh.encode("utf-8")) > room:
            print(f"{len(a.scans)} scan(s) leave {room:,} B for the HTML body; "
                  f"re-rendering the email to fit.")
            _, eh, _ = render_all(payload, room)
    os.makedirs(a.out_dir, exist_ok=True)
    stamp = a.date or payload["MAST"].get("file_date") or "brief"
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
    budget_used = a.email_budget or EMAIL_BUDGET
    print(f"wrote {email}  ({size:,} B of the {budget_used:,} B body budget)")
    print(f"wrote {text}")
    print(f"wrote email.part01..{len(parts):02d}.html — read these in order and "
          f"concatenate them with no separator to rebuild the htmlBody exactly; "
          f"do not read {os.path.basename(email)} itself, it exceeds the read cap.")
    print(f"build {marker} — this marker appears in all three outputs. Quote it "
          "when you report the run; a brief without it did not come from here.")
    if size > budget_used:
        print(f"WARNING: email body is {size - budget_used:,} B over budget — "
              "Gmail will clip it. Shorten sections or drop embedded scans.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
