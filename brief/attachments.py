"""The send path's attachment ceiling, as an enforced check.

Gmail's send tool SILENTLY TRUNCATES any single attachment whose base64 exceeds
roughly 24,600 characters: a 49,216-character attachment shipped as the top half
of a JPEG with solid grey below, and no error anywhere. That was learned by
sending a message and reading it back in RAW form, and it lived in the prompt as
a number to remember and a rule to apply by eye.

A byte count is arithmetic. Check the file.
"""
import base64
import math
import os

# Verified by RAW read-back: the point at which the send path starts truncating.
CEILING_B64_CHARS = 24_600

# What to aim for. The margin covers MIME header overhead and any re-encoding
# between here and the wire; ~15 KB of JPEG (about 414x271 px) stays legible.
SAFE_B64_CHARS = 21_000


def b64_chars(n_bytes):
    """Base64 length of n_bytes, the number the send path actually counts.

    >>> b64_chars(15000)
    20000
    """
    return 4 * math.ceil(n_bytes / 3)


def max_bytes(limit=SAFE_B64_CHARS):
    """Largest attachment that stays under a base64 limit.

    >>> max_bytes()
    15750
    """
    return (limit // 4) * 3


# THE SEND CALL IS ONE CALL, AND THE RUN HAS TO EMIT ALL OF IT.
#
# The connector's send tool takes the HTML body, the plain-text alternative and
# every attachment as inline strings in a SINGLE invocation. Splitting the body
# into email.partNN.html fixed READING it; nothing fixed emitting it. So the
# binding limit is not Gmail's 85 KB body budget but how much one tool call can
# carry, and that limit counts the text alternative and the base64 of every
# scan too.
#
# Measured on the run that hit it: an 86,085-char body, a 27,623-char text
# alternative and one 15,435 B scan (20,580 chars of base64) came to 134,288
# characters in one call - past what the run could emit, and the brief sends
# exactly once, so a truncated send cannot be corrected. The budget below sits
# under that observed failure. Base64 is the worst of it: a JPEG has no
# redundancy, so unlike prose it cannot be re-emitted approximately.
#
# Check this BEFORE carrying anything, not at send time.
CARRY_BUDGET_CHARS = 120_000


def carry_cost(html, text="", attachment_paths=()):
    """What one send call must carry, in characters.

    Returns (total, rows, ok): `rows` is [(label, chars), ...] so the caller can
    show where the weight is, and `ok` is whether it fits CARRY_BUDGET_CHARS.

    >>> total, rows, ok = carry_cost("<p>hi</p>", "hi")
    >>> total, ok
    (11, True)
    """
    rows = [("htmlBody", len(html))]
    if text:
        rows.append(("plain-text body", len(text)))
    for path in attachment_paths:
        rows.append((os.path.basename(path), b64_chars(os.path.getsize(path))))
    total = sum(n for _label, n in rows)
    return total, rows, total <= CARRY_BUDGET_CHARS


def check(path_or_size, limit=SAFE_B64_CHARS):
    """Report how an attachment stands against the ceiling.

    Returns (ok, chars, message). `ok` is False when the file is over the SAFE
    limit; the message says by how much and what size would fit.
    """
    size = path_or_size if isinstance(path_or_size, int) else os.path.getsize(path_or_size)
    chars = b64_chars(size)
    if chars > CEILING_B64_CHARS:
        return (False, chars,
                f"{size:,} B -> {chars:,} base64 chars, past the {CEILING_B64_CHARS:,} "
                f"truncation ceiling: this WILL ship half an image with no error. "
                f"Re-encode to at most {max_bytes(limit):,} B.")
    if chars > limit:
        return (False, chars,
                f"{size:,} B -> {chars:,} base64 chars, over the {limit:,} safe limit "
                f"(ceiling {CEILING_B64_CHARS:,}). Re-encode to at most {max_bytes(limit):,} B.")
    return (True, chars, f"{size:,} B -> {chars:,} base64 chars, within the {limit:,} limit.")


def fits(path_or_size, limit=SAFE_B64_CHARS):
    """True when an attachment will survive the send path intact."""
    return check(path_or_size, limit)[0]


def verify_sent(original_path, sent_bytes):
    """Compare an attachment read back from the sent message against the source.

    The only way to know truncation happened is to read the message back, so the
    prompt asks for exactly one such check per run. Returns (ok, message).
    """
    original = os.path.getsize(original_path)
    if sent_bytes == original:
        return True, f"attachment intact: {original:,} B round-tripped."
    return False, (f"ATTACHMENT TRUNCATED: sent {sent_bytes:,} B of {original:,} B "
                   f"({100 * sent_bytes / original:.0f}%). Do not resend - the one-send "
                   f"rule stands. Say so in the reply and use at most "
                   f"{max_bytes():,} B next run.")
