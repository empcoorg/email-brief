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

# THE WHOLE SEND IS ONE TOOL CALL. htmlBody, the plain-text body and every
# attachment's base64 are all inline string arguments, so the run has to emit
# them together in a single response. That response has a token ceiling, and it
# is the binding limit here - far tighter than anything Gmail imposes (25 MB of
# attachments, ~102 KB before it clips the body).
#
# Observed: a call totalling ~145 KB was refused as too large to send in one
# call. At roughly 2.2 bytes per token for this markup that is ~66,000 output
# tokens, which is the ceiling. 120 KB keeps ~17% margin, and base64 tokenizes
# worse than markup, so the margin is not generous.
#
# Budget arithmetic, so it is never guessed:
#     SEND_CALL_BYTES - len(email.txt) - sum(b64_chars(scan)) = room for HTML
# When the scans do not leave room, the EMAIL sheds cards (SHED_ORDER) rather
# than the send failing - the standalone file always carries everything.
SEND_CALL_BYTES = 120 * 1024


def call_bytes(html_bytes, text_bytes, scan_sizes=()):
    """Total inline size of one send call, in bytes.

    >>> call_bytes(1000, 100, [300])          # 300 B -> 400 b64 chars
    1500
    """
    return html_bytes + text_bytes + sum(b64_chars(n) for n in scan_sizes)


def html_room(text_bytes, scan_sizes=(), limit=SEND_CALL_BYTES):
    """How many bytes of HTML body the send call can still carry.

    >>> html_room(15_508, [15_000, 15_000]) == SEND_CALL_BYTES - 15_508 - 2 * 20_000
    True
    """
    return limit - text_bytes - sum(b64_chars(n) for n in scan_sizes)


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
