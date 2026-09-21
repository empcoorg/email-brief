"""Command line: validate a payload and write the three outputs.

    python3 -m brief render payload.json --out-dir /mnt/user-data/outputs
    python3 -m brief validate payload.json
    python3 -m brief expired artifacts.txt sent/ --today 2026-09-13
    python3 -m brief ai-spend --previous morning.txt --today 2026-09-15 --add "Acme AI=20.00"

`render` writes morning-brief-<date>.html, email.html and email.txt, then
prints the paths and the email's size against the 85 KB send budget.
`validate` checks the payload and says what is wrong, without rendering.
"""
import argparse
import json
import os
import sys

from .model import PayloadError, load
from .attachments import b64_chars as b64
from .render import render_all, split_for_send

from .render import EMAIL_BUDGET_BYTES as EMAIL_BUDGET  # Gmail clips ~102 KB


def _extract(page, out):
    from .evening import extract_payload
    try:
        found = extract_payload(open(page, encoding="utf-8").read())
    except (OSError, ValueError) as ex:
        print(f"cannot read a payload from {page}: {ex}", file=sys.stderr)
        return 2
    if found is None:
        print(f"no embedded payload in {page} - was it rendered before pages "
              "carried one, or is this the wrong file?", file=sys.stderr)
        return 2
    with open(out, "w", encoding="utf-8") as f:
        json.dump(found, f, ensure_ascii=False, indent=1)
    print(f"wrote {out}  ({len(found)} keys)")
    return 0


def _expired(sources, today):
    """Print the brief pages past retention, one URL per line."""
    from .retention import RETENTION_DAYS, expired, load_rows
    files = []
    for src in sources:
        if os.path.isdir(src):
            files += sorted(os.path.join(src, f) for f in os.listdir(src)
                            if os.path.isfile(os.path.join(src, f)))
        else:
            files.append(src)
    rows = []
    try:
        for path in files:
            with open(path, encoding="utf-8") as fh:
                rows += load_rows(fh.read())
        urls = expired(rows, today)
    except (OSError, ValueError) as ex:
        print(f"cannot decide retention: {ex}", file=sys.stderr)
        return 2
    for u in urls:
        print(u)
    if not urls:
        print(f"nothing older than {RETENTION_DAYS} days in {len(rows)} page(s) "
              f"from {len(files)} file(s)", file=sys.stderr)
    return 0 if urls else 3


def _pairs(items, what):
    """"Name=12.34" pairs from the command line, as (name, amount)."""
    out = []
    for item in items or []:
        name, sep, amount = str(item).rpartition("=")
        if not sep or not name.strip():
            raise ValueError(f"{what} must look like \"Service=12.34\", got {item!r}")
        try:
            out.append((name.strip(), float(amount.replace("$", "").replace(",", "").strip())))
        except ValueError:
            raise ValueError(f"{what} {item!r}: {amount!r} is not a number") from None
    return out


def _ai_spend(a):
    """Carry each AI service's year-to-date total forward and add this run's charges."""
    from .spend import accumulate, added, format_line, rows
    previous = ""
    if a.previous:
        try:
            with open(a.previous, encoding="utf-8") as fh:
                previous = fh.read()
        except OSError as ex:
            print(f"cannot read {a.previous}: {ex}", file=sys.stderr)
            return 2
    try:
        charges = _pairs(a.add, "--add")
        year, totals, carried, opening = accumulate(
            previous, charges, a.today, dict(_pairs(a.basis, "--basis")), a.basis_year,
            a.total_basis, a.total_basis_year)
    except ValueError as ex:
        print(f"cannot total AI spend: {ex}", file=sys.stderr)
        return 2
    block = {"year": year, "rows": rows(totals, added(charges))}
    if opening:
        block["opening"] = opening
    if a.note:
        block["note"] = a.note
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(block, fh, ensure_ascii=False, indent=1)
    where = (f"carried forward from the previous brief ({carried})" if carried
             else "nothing carried forward — this is the first brief of "
                  f"{year}, or the previous one had no line")
    print(f"wrote {a.out} — {where}.")
    for service, total, this_window, note in block["rows"]:
        arrived = f" + ${this_window:,.2f} this window" if this_window else ""
        print(f"  {service}: ${total:,.2f}{arrived}  ({note})")
    if opening:
        print(f"  (plus ${opening:,.2f} spent before this brief started counting)")
    print(format_line(year, totals, opening))
    print("Paste the contents of the file into the payload as AI_SPEND.")
    return 0


def _evening(a):
    """Decide the evening send and build its payload."""
    from .evening import decide, extract_payload, merge, parse_record
    try:
        evening = load(a.evening)
    except PayloadError as ex:
        print(f"evening payload invalid: {ex}", file=sys.stderr)
        return 2
    carry, morning = [], None
    if a.record:
        rec = parse_record(open(a.record, encoding="utf-8").read())
        if rec is None:
            print("no 'Brief record:' line in the morning text - nothing is "
                  "known to have been cut, so nothing is carried.")
        else:
            carry = list(dict.fromkeys(rec["shed"] + rec["clipped"]))
    if carry:
        if not a.morning_page:
            print(f"the morning email left out {', '.join(carry)} but no "
                  "--morning-page was given to carry them from", file=sys.stderr)
            return 2
        morning = extract_payload(open(a.morning_page, encoding="utf-8").read())
        if morning is None:
            print(f"{a.morning_page} holds no embedded payload; cannot carry "
                  f"{', '.join(carry)}", file=sys.stderr)
            return 2
    try:
        merged, carried = (merge(morning, evening, carry, a.carried_from)
                           if carry else (evening, []))
    except PayloadError as ex:
        print(f"cannot merge: {ex}", file=sys.stderr)
        return 2
    send, why = decide(evening, carried)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    if not send:
        print("SKIP — nothing important since the morning and nothing it left out.")
        return 3
    print(f"SEND — {len(why)} reason(s):")
    for w in why:
        print(f"  - {w}")
    print(f"wrote {a.out}")
    return 0


def _verify_sent(raw_path, html_path, text_path):
    """Is the message about to go out the BRIEF, or only its fallback?

    A morning brief arrived as the plain-text copy: no HTML part at all, so
    every client showed the fallback - headings gone, tables gone, the trimmed
    "SHORTENED" note at the top of what the reader saw. Carrying ~110 KB of
    HTML through a tool call is the most expensive step of a run, and a run
    that cannot finish it can finish the text instead and look like it worked.
    Nothing checked, so nothing failed; it just arrived wrong.

    This reads the draft back as RAW and answers four questions before a send:
    is there an HTML part at all, is it the brief (the build marker), is it
    WHOLE (byte identical to the file), and is it the LAST alternative - the
    one a mail client picks when it has both.
    """
    import email
    import email.policy
    try:
        raw = open(raw_path, "rb").read()
        want_html = open(html_path, encoding="utf-8").read()
    except OSError as ex:
        print(f"cannot check the draft: {ex}", file=sys.stderr)
        return 2
    if b"Content-Type" not in raw[:4096] and b"content-type" not in raw[:4096]:
        # a base64url blob, as some connectors hand RAW back
        import base64
        try:
            raw = base64.urlsafe_b64decode(raw.strip() + b"=" * (-len(raw.strip()) % 4))
        except Exception:
            pass
    def flat(text):
        """Line endings as the transport left them, not as the file has them.

        A mail transport rewrites the body to CRLF, and may re-wrap it. A
        check that compares raw bytes calls that a corrupted draft - which is
        what happened on the first brief this gate ever guarded: it refused a
        draft that was carrying the real HTML, over line endings. A gate that
        cries wolf is a gate that gets overridden, so it compares text as text.
        """
        return "\n".join(line.rstrip() for line in str(text).replace("\r\n", "\n")
                          .replace("\r", "\n").split("\n")).strip()

    msg = email.message_from_bytes(raw, policy=email.policy.default)
    parts = [p_ for p_ in msg.walk() if not p_.get_content_maintype() == "multipart"]
    html = [p_ for p_ in parts if p_.get_content_type() == "text/html"]
    text = [p_ for p_ in parts if p_.get_content_type() == "text/plain"]
    problems = []
    if not html:
        problems.append("NO HTML PART AT ALL — this draft would arrive as the plain-text "
                        "fallback. Do not send it. Rebuild the draft with the htmlBody "
                        "carried whole; if you cannot, re-render with --clip-guard (a "
                        "smaller email that is still the brief) rather than sending text.")
    else:
        got, want = flat(html[0].get_content()), flat(want_html)
        marker = _build_marker(want_html)
        if marker and marker not in got:
            problems.append(f"the HTML part does not carry this render's marker ({marker}) — "
                            "it is a different brief, or a placeholder")
        # Truncation is what this is looking for, so it asks whether the END
        # arrived - a transport may re-wrap the middle, but it cannot invent
        # the last line of a file it never received.
        tail = want[-160:]
        if tail and tail not in got:
            problems.append("the HTML part does not end where email.html ends — it was "
                            "truncated on the way in; rebuild the draft")
        elif len(got) < len(want) * 0.98:
            problems.append(f"the HTML part is {len(want) - len(got):,} characters short of "
                            "email.html; rebuild the draft")
        alts = [p_ for p_ in parts if p_.get_content_type() in ("text/plain", "text/html")]
        if alts and alts[-1].get_content_type() != "text/html":
            problems.append("the plain-text part comes AFTER the HTML one; a mail client "
                            "shows the last alternative, so the fallback would win")
    if text_path and text:
        try:
            want_text = open(text_path, encoding="utf-8").read()
        except OSError:
            want_text = ""
        if want_text and flat(want_text)[:200] not in flat(text[0].get_content()):
            problems.append("the plain-text part is not the renderer's email.txt")
    if problems:
        print("DRAFT IS NOT SENDABLE:", file=sys.stderr)
        for p_ in problems:
            print(f"  - {p_}", file=sys.stderr)
        return 6
    print(f"OK   the draft carries the brief: HTML part {len(html[0].get_content()):,} chars, "
          f"marker present, plain text second. Safe to send.")
    return 0


def _build_marker(html):
    """The build marker the renderer wrote into all three outputs."""
    import re as _re
    m = _re.search(r"brief-[0-9a-f]{12}", html)
    return m.group(0) if m else ""


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
    # Three different failures, three different things to do about them. The
    # advice used to read "same length, different bytes" whatever came back,
    # so a read-back that was LONGER - a re-encode, a re-wrap, a doubled
    # chunk - was diagnosed as a typo, which is the one case where retyping
    # the same draft does not help.
    if len(b_) < len(a_) and a_[:len(b_)] == b_:
        kind, advice = "TRUNCATED", (
            "The read-back is a clean prefix — the call ran out of room. Make "
            "the message smaller.")
    elif len(a_) == len(b_):
        kind, advice = "CORRUPTED", (
            "Same length, different bytes — the base64 was mistyped, not cut. "
            "Rewrite the draft with the attachment re-transcribed; do NOT make "
            "it smaller, and do NOT send this draft.")
    else:
        grew = len(b_) - len(a_)
        kind, advice = "CORRUPTED", (
            f"The read-back is {abs(grew):,} B {'longer' if grew > 0 else 'shorter'} "
            "AND diverges before its end, so it was re-encoded or re-wrapped "
            "rather than simply cut. Rebuild the draft from the source file — "
            "do not retype the read-back — and do NOT send this draft.")
    print(f"{kind}: {os.path.basename(source)} is {len(a_):,} B, read back "
          f"{len(b_):,} B, first difference at offset {where:,}.\n" + advice + "\n",
          file=sys.stderr)
    return 5


def _check_attachments(paths, out_dir=None, connector=None):
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
        limit = call_limit(len(sizes), connector=connector)
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
                   help="max total for one send call: HTML + text + attachments. "
                        "Overrides both ceilings below")
    r.add_argument("--connector", default=None, metavar="NAME",
                   help="the email connector the brief is sent from (gmail, outlook, "
                        "microsoft365). The send call is capped at 98%% of that "
                        "connector's limit, or at what one call can carry, whichever "
                        "is smaller")
    r.add_argument("--clip-guard", action="store_true",
                   help="shed HTML cards to stay under Gmail's clip threshold. "
                        "Off by default: a clip is a link, a shed card is gone")
    r.add_argument("--text-budget", type=int, default=None, metavar="BYTES",
                   help="max plain-text body before sections are shed "
                        "(default 10 KB; it is charged to the same send call)")
    r.add_argument("--full-url", default=None, metavar="URL",
                   help="address of the privately published full page; goes in "
                        "the email's masthead, beside each mailpiece scan, and "
                        "last in the text copy")
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

    vs = sub.add_parser("verify-sent",
                        help="is the draft the BRIEF or only its text fallback? "
                             "(exit 0 sendable, 6 not)")
    vs.add_argument("raw", help="the draft read back with messageFormat RAW")
    vs.add_argument("--html", required=True, help="the email.html the renderer wrote")
    vs.add_argument("--text", help="the email.txt the renderer wrote")

    xp = sub.add_parser("extract-payload",
                        help="recover the payload embedded in a published page "
                             "(exit 0 found, 2 none)")
    xp.add_argument("page", help="the page file, or an Artifact read-back of it")
    xp.add_argument("-o", "--out", required=True, help="where to write the payload JSON")
    ev = sub.add_parser("evening",
                        help="merge what the morning email could not show into the "
                             "evening payload; exit 0 send, 3 skip")
    ev.add_argument("--evening", required=True, help="the evening run's own payload")
    ev.add_argument("--morning-page", help="the morning's published page (or its read-back)")
    ev.add_argument("--record", help="text file holding the morning email's text copy, "
                                     "which ends with its 'Brief record:' line")
    ev.add_argument("--from", dest="carried_from", default="this morning",
                    help="the morning run stamp, shown on every carried section")
    ev.add_argument("-o", "--out", required=True, help="where to write the merged payload")

    at = sub.add_parser("attachment",
                        help="is this file within the send-path size limits? "
                             "exit 0 yes, 4 no (size only, not proof of delivery)")
    at.add_argument("files", nargs="+")
    at.add_argument("--out-dir", help="also check the whole send call against "
                                      "the rendered email in this directory")
    at.add_argument("--connector", default=None, metavar="NAME",
                    help="the email connector the brief is sent from (gmail, outlook, "
                         "microsoft365)")
    sp_ = sub.add_parser("ai-spend",
                         help="carry AI billing totals forward and add this run's "
                              "charges; writes the payload's AI_SPEND block")
    sp_.add_argument("--previous", help="the previous brief's text copy, which ends with "
                                        "its 'AI spend YTD' line (omit on the first run)")
    sp_.add_argument("--today", required=True, help="the run's date, YYYY-MM-DD — its year "
                                                    "is what resets the total on 1 January")
    sp_.add_argument("--add", action="append", metavar="SERVICE=USD", default=[],
                     help="a charge that arrived in THIS window only; repeatable. Anything "
                          "older is already inside the carried total")
    sp_.add_argument("--basis", action="append", metavar="SERVICE=USD", default=[],
                     help="starting amount for a service, used only when nothing is carried "
                          "forward (an opening balance established outside the mailbox)")
    sp_.add_argument("--basis-year", help="the year a --basis applies to; outside it the "
                                          "basis is ignored")
    sp_.add_argument("--total-basis", type=float, metavar="USD",
                     help="AI spend already made this year that no service row itemises "
                          "- for a brief that starts mid-year. Added to the total once, "
                          "then carried forward on the brief's own line")
    sp_.add_argument("--total-basis-year", help="the year a --total-basis applies to")
    sp_.add_argument("--note", help="one line shown under the table")
    sp_.add_argument("-o", "--out", default="ai_spend.json", help="where to write the block")

    xr = sub.add_parser("expired",
                        help="which published brief pages are past retention? "
                             "prints their URLs; exit 0 some, 3 none")
    xr.add_argument("sources", nargs="+",
                    help="the Artifact listing as the tool printed it, sent briefs "
                         "saved from get_message, a directory of those, or a JSON "
                         "list of {title, url, favicon, updated}")
    xr.add_argument("--today", required=True, help="the run's date, YYYY-MM-DD")
    a = ap.parse_args(argv)

    if a.cmd == "verify-sent":
        return _verify_sent(a.raw, a.html, a.text)
    if a.cmd == "verify":
        return _verify(a.source, a.readback)

    if a.cmd == "extract-payload":
        return _extract(a.page, a.out)

    if a.cmd == "evening":
        return _evening(a)

    if a.cmd == "ai-spend":
        return _ai_spend(a)

    if a.cmd == "expired":
        return _expired(a.sources, a.today)

    if a.cmd == "attachment":
        return _check_attachments(a.files, a.out_dir, a.connector)

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
    limit = call_limit(len(sizes), a.send_budget or None, a.connector)
    cap = a.email_budget or (EMAIL_BUDGET if a.clip_guard else None)
    # Only a run that passes --scans says how many ride along; without it the
    # count is unknown, and the email keeps saying each scan is attached.
    attached = len(a.scans) if a.scans else None
    stamp = a.date or payload["MAST"].get("file_date") or "brief"
    try:
        fh, eh, pt = render_all(payload, cap, a.text_budget, a.full_url, attached, stamp)
    except ValueError as ex:
        print(f"cannot render: {ex}", file=sys.stderr)
        return 2

    total = call_bytes(len(eh.encode("utf-8")), len(pt.encode("utf-8")), sizes)
    if total > limit:
        # DECORATION FIRST. The email's trend drawings are the only thing in
        # the call that a reader loses nothing by: the page keeps the real
        # ones, and every email carries its link. They go before the text copy
        # is cut and long before a card is shed.
        from .render import draw_email_sparks
        draw_email_sparks(False)
        fh, eh, pt = render_all(payload, cap, a.text_budget, a.full_url, attached, stamp)
        draw_email_sparks(True)
        shrunk = call_bytes(len(eh.encode("utf-8")), len(pt.encode("utf-8")), sizes)
        if shrunk < total:
            print(f"send call was {total:,} B of {limit:,} — the email's trend "
                  f"drawings come out first ({total - shrunk:,} B); the page keeps them.")
        total = shrunk
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
        room = html_room(len(pt.encode("utf-8")), sizes, a.send_budget or None, a.connector)
        if cap:
            room = min(room, cap)
        print(f"still {total:,} B of {limit:,}; the HTML must shed to {room:,} B.")
        _, eh, _ = render_all(payload, room, a.text_budget, a.full_url, attached, stamp)
        # The HTML just got smaller, so the text gets its room back: it was
        # trimmed a moment ago against the LARGER html, and leaving it that way
        # spent the saving on nothing. (The email's decoration is shed before
        # any card, so this is usually a drawing's worth of bytes.)
        room_for_text = max(limit - len(eh.encode("utf-8"))
                            - sum(b64(n) for n in sizes), 1024)
        pt = plain_text(min(room_for_text, a.text_budget or room_for_text))

    os.makedirs(a.out_dir, exist_ok=True)
    page = os.path.join(a.out_dir, f"morning-brief-{stamp}.html")
    email = os.path.join(a.out_dir, "email.html")
    text = os.path.join(a.out_dir, "email.txt")
    # The page to publish carries the payload too, so a later evening run can
    # recover any section the morning email could not show. It is a separate
    # file so the page delivered in the session stays exactly as pinned.
    from .evening import embed_payload
    from .render import LAST_EMAIL_REPORT
    # Deliberately NOT prefixed "morning-brief": tooling finds the session page
    # as "the file starting with morning-brief", and a second match would make
    # that depend on directory order.
    published = os.path.join(a.out_dir, f"full-brief-{stamp}.html")
    report = os.path.join(a.out_dir, "email.report.json")
    with open(published, "w", encoding="utf-8") as f:
        f.write(embed_payload(fh, payload))
    with open(report, "w", encoding="utf-8") as f:
        json.dump(dict(LAST_EMAIL_REPORT, build=marker, full_url=a.full_url or ""), f, indent=1)
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
