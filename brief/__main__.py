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
from .attachments import b64_chars as b64
from .render import render_all, split_for_send

from .render import EMAIL_BUDGET_BYTES as EMAIL_BUDGET  # Gmail clips ~102 KB


def _verify(source, readback):
    """Compare an attachment against what came back out of the message.

    Size alone is not enough. The failure that shipped was byte-identical in
    LENGTH: one wrong base64 character out of 13,568, one wrong byte at offset
    218, an image that would not decode. So compare the bytes, and say where
    they first differ - the offset tells you it was transcription rather than
    truncation, which is the difference between "retype it" and "make it
    smaller".
    """
    import hashlib
    try:
        a_ = open(source, "rb").read()
        b_ = open(readback, "rb").read()
    except OSError as ex:
        print(f"cannot compare: {ex}", file=sys.stderr)
        return 5
    if a_ == b_:
        print(f"OK   {os.path.basename(source)}: {len(a_):,} B, sha256 "
              f"{hashlib.sha256(a_).hexdigest()[:16]} — byte identical.")
        return 0
    where = next((i for i, (x, y) in enumerate(zip(a_, b_)) if x != y), min(len(a_), len(b_)))
    kind = ("TRUNCATED" if len(b_) < len(a_) and a_[:len(b_)] == b_
            else "CORRUPTED")
    print(f"{kind}: {os.path.basename(source)} is {len(a_):,} B, read back "
          f"{len(b_):,} B, first difference at offset {where:,}.\n"
          + ("The read-back is a clean prefix — the call ran out of room. Make "
             "the message smaller.\n" if kind == "TRUNCATED" else
             "Same length, different bytes — the base64 was mistyped, not cut. "
             "Rewrite the draft with the attachment re-transcribed; do NOT make "
             "it smaller, and do NOT send this draft.\n"), file=sys.stderr)
    return 5


def _check_attachments(paths, out_dir=None):
    """Are the files within the size limits, and does the WHOLE call fit?

    Two different limits. Each attachment must stay under the per-file ceiling
    or the send path truncates it silently. Separately, htmlBody + the text body
    + every attachment travel as inline arguments in ONE tool call, and that
    call has its own ceiling - which is what a run means when it reports the
    payload was "too large to send in one call".
    """
    from .attachments import (check, max_bytes, b64_chars, call_bytes,
                              call_limit)
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
        limit = call_limit(len(sizes))
        print(f"\nwhole send call: htmlBody {html:,} + text {text:,} + "
              f"{len(sizes)} attachment(s) {sum(b64_chars(n) for n in sizes):,} "
              f"(base64) = {total:,} B of {limit:,}")
        if total > limit:
            over = total - limit
            risk = ("the send path truncates the tail silently, and the tail "
                    "is the attachment" if sizes else
                    "the call is refused outright as too large to send at once")
            print(f"OVER BY {over:,} B — {risk}.\n"
                  f"Re-render with the scans accounted for:\n"
                  f"  python3 -m brief render payload.json --out-dir {out_dir} "
                  f"--scans {' '.join(paths)}\nThe email will shed its least "
                  f"actionable cards to make room and say so; the standalone "
                  f"file still carries everything.", file=sys.stderr)
            return 4
        print(f"OK   the call is within budget ({100 * total / limit:.0f}% of "
              f"{limit:,} B). This bounds the SIZE only. Size does not prove "
              "an attachment arrives: one mistyped base64 character corrupts it "
              "at exactly the right length. Draft it, read the draft back with "
              "get_draft RAW, and run `brief verify` before sending.")
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
    r.add_argument("--clip-guard", action="store_true",
                   help="shed HTML cards to stay under Gmail's clip threshold. "
                        "Off by default: a clip is a link, a shed card is gone")
    r.add_argument("--text-budget", type=int, default=None, metavar="BYTES",
                   help="max plain-text body before sections are shed "
                        "(default 10 KB; it is charged to the same send call)")
    r.add_argument("--scans", nargs="*", default=[], metavar="JPG",
                   help="mailpiece scans that will ride along in the same send "
                        "call; the email body budget shrinks to make room")
    v = sub.add_parser("validate", help="check a payload without rendering")
    v.add_argument("payload")
    g = sub.add_parser("significant",
                       help="does this payload justify an extra send? exit 0 yes, 3 no")
    g.add_argument("payload")
    vf = sub.add_parser("verify",
                        help="did an attachment survive? compare source against "
                             "what was read back (exit 0 same, 5 differs)")
    vf.add_argument("source", help="the file as it exists on disk")
    vf.add_argument("readback", help="the same file decoded out of the draft "
                                     "or sent message")

    at = sub.add_parser("attachment",
                        help="is this file within the send-path size limits? "
                             "exit 0 yes, 4 no (size only, not proof of delivery)")
    at.add_argument("files", nargs="+")
    at.add_argument("--out-dir", help="also check the whole send call against "
                                      "the rendered email in this directory")
    a = ap.parse_args(argv)

    if a.cmd == "verify":
        return _verify(a.source, a.readback)

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

    # Everything in the send call competes for the same room, so allocate once
    # and degrade nothing unless the total is actually over.
    #
    # The BRIEF outranks everything. The Gmail-clip budget used to shed HTML
    # cards on its own, and it became the binding constraint: a real run landed
    # at 99.9% of the 87,040 B body budget with seven cards gone, while the send
    # call sat at 84% with 21 KB spare that the HTML was not allowed to touch.
    # That is the wrong trade. Gmail CLIPS - "[Message clipped] View entire
    # message" is a link, and the content is one click away - whereas a shed
    # card is gone. So clipping is now a warning, not a trigger; pass
    # --clip-guard to shed for it instead.
    from .attachments import call_bytes, call_limit, html_room
    from .render import TEXT_BUDGET_BYTES, plain_text
    sizes = [os.path.getsize(s_) for s_ in a.scans]
    limit = call_limit(len(sizes), a.send_budget or None)
    cap = a.email_budget or (EMAIL_BUDGET if a.clip_guard else None)
    fh, eh, pt = render_all(payload, cap, a.text_budget)

    total = call_bytes(len(eh.encode("utf-8")), len(pt.encode("utf-8")), sizes)
    if total > limit:
        # Text before HTML: it is an alternative body, and a reader whose client
        # shows HTML never sees it.
        room_for_text = max(limit - len(eh.encode("utf-8"))
                            - sum(b64(n) for n in sizes), 1024)
        print(f"send call would be {total:,} B of {limit:,} — trimming the "
              f"plain-text part to {room_for_text:,} B first, so the brief "
              f"keeps its sections.")
        pt = plain_text(min(room_for_text, a.text_budget or room_for_text))
        total = call_bytes(len(eh.encode("utf-8")), len(pt.encode("utf-8")), sizes)
    if total > limit:
        room = html_room(len(pt.encode("utf-8")), sizes, a.send_budget or None)
        if cap:
            room = min(room, cap)
        print(f"still {total:,} B of {limit:,}; the HTML must shed to {room:,} B.")
        _, eh, _ = render_all(payload, room, a.text_budget)
        pt = plain_text(min(room_for_text, a.text_budget or room_for_text))

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
    budget_used = cap or EMAIL_BUDGET
    print(f"wrote {email}  ({size:,} B of the {budget_used:,} B body budget)")
    print(f"wrote {text}")
    print(f"wrote email.part01..{len(parts):02d}.html — read these in order and "
          f"concatenate them with no separator to rebuild the htmlBody exactly; "
          f"do not read {os.path.basename(email)} itself, it exceeds the read cap.")
    print(f"build {marker} — this marker appears in all three outputs. Quote it "
          "when you report the run; a brief without it did not come from here.")
    if size > EMAIL_BUDGET:
        print(f"NOTE: the body is {size - EMAIL_BUDGET:,} B over Gmail's clip "
              f"threshold, so Gmail will show \"[Message clipped] View entire "
              f"message\". Nothing was dropped — every section is in the email, "
              f"one click away. Pass --clip-guard to shed cards instead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
