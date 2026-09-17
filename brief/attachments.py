"""The send path's attachment ceiling, as an enforced check.

Gmail's send tool SILENTLY TRUNCATES attachments: a 49,216-character base64
attachment shipped as the top half of a JPEG with solid grey below, and no error
anywhere. That was learned by sending a message and reading it back in RAW form,
and it lived in the prompt as a number to remember and a rule to apply by eye.

A byte count is arithmetic. Check the file.

But size alone does not predict survival, and this module used to imply it did.
A scan at 53% of the per-file ceiling still arrived truncated when the WHOLE
call was 99% full. The checks here are necessary, not sufficient: they say a
file is not too big by itself. verify_sent, run against the message read back
after sending, is the only thing that says it arrived.
"""
import base64
import math
import os

# A NECESSARY LIMIT, NOT A SUFFICIENT ONE. This was read back off a real send
# and it does bound a single attachment. It does NOT predict survival:
#
#   2026-09-11: a 9,824 B scan (13,100 base64 chars - 53% of this ceiling, and
#   62% of the "safe" limit below) was delivered as 9,177 B and would not
#   decode. Every per-file check had passed. The whole call was 121,654 B
#   against a 122,880 budget: 99.0% full, with the attachment last.
#
# So truncation tracks the TOTAL call, not the individual file, and what gets
# cut is the tail - which is the attachment. Passing every check here means the
# file is not too big by itself. It does not mean the file arrives.
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
# Observed refusal at ~145 KB. 135 KB keeps ~7% margin. Override with
# BRIEF_SEND_CALL_BYTES when a run proves it can carry more or less; raising it
# past what the model will emit turns a trimmed brief into a failed send, which
# is the worse trade.
SEND_CALL_BYTES = int(os.environ.get("BRIEF_SEND_CALL_BYTES", 135 * 1024))

# THE CONNECTOR'S OWN CEILING, which is a different limit from the one above.
# A provider refuses a message larger than this outright, attachments included.
# These are the providers' published defaults; an administrator can raise or
# lower them, so BRIEF_CONNECTOR_LIMIT_BYTES overrides whatever is picked here.
CONNECTOR_SEND_LIMITS = {
    "gmail": 25 * 1024 * 1024,
    "outlook": 20 * 1024 * 1024,          # outlook.com
    "microsoft365": 25 * 1024 * 1024,     # the Exchange Online default
    "": 20 * 1024 * 1024,                 # unknown connector: the lowest of these
}

# How much of the connector's ceiling a brief may use. Not 100%: MIME headers,
# base64 re-encoding and the provider's own framing all sit between this count
# and what the provider weighs, and a message refused for being one byte over
# is a brief that did not arrive.
USABLE_FRACTION = float(os.environ.get("BRIEF_USABLE_FRACTION", "0.98"))


def connector_limit(connector=None):
    """98% of the named connector's send ceiling, in bytes.

    >>> connector_limit("gmail") == int(0.98 * 25 * 1024 * 1024)
    True
    >>> connector_limit("nobody's heard of this one") == connector_limit("")
    True
    """
    override = os.environ.get("BRIEF_CONNECTOR_LIMIT_BYTES")
    if override:
        return int(int(override) * USABLE_FRACTION)
    name = str(connector or os.environ.get("BRIEF_CONNECTOR") or "").strip().lower()
    return int(CONNECTOR_SEND_LIMITS.get(name, CONNECTOR_SEND_LIMITS[""]) * USABLE_FRACTION)

# Headroom when attachments ride along. This was 30 KB, bought on the theory
# that corruption was truncation under size pressure. The second failure
# disproved that: the file came back the SAME LENGTH with one byte wrong at
# offset 218 - a single mistyped base64 character, 1 in 13,568. No headroom
# fixes that, because base64 carries no redundancy and one wrong character
# destroys the file.
#
# What fixes it is not sending blind. create_draft, then get_draft with
# messageFormat RAW, lets the attachment be read back and compared BEFORE the
# send; a bad draft is rewritten at no cost, because the one-send rule binds
# sending, not drafting. With that check in place headroom is a courtesy rather
# than the defence, so 8 KB - and the room goes back to the brief.
ATTACHMENT_RESERVE_BYTES = int(
    os.environ.get("BRIEF_ATTACHMENT_RESERVE_BYTES", 8 * 1024))


def call_limit(n_attachments, limit=None, connector=None):
    """The ceiling for one send call, tightened when attachments ride along.

    TWO ceilings apply and the SMALLER wins: the connector will not accept a
    message past its own limit, and the run cannot emit more than SEND_CALL_BYTES
    in one response, because the body, the text part and every attachment's
    base64 are inline arguments of a single tool call.

    Today the emit ceiling binds by three orders of magnitude - 98% of Gmail's
    25 MB is ~25 MB, and one call carries ~135 KB - so raising the provider's
    limit changes nothing until BRIEF_SEND_CALL_BYTES proves a run can emit
    more. Both are written down here so neither is silently assumed.

    >>> call_limit(0) - call_limit(1) == ATTACHMENT_RESERVE_BYTES
    True
    >>> call_limit(0) == min(SEND_CALL_BYTES, connector_limit())
    True
    """
    base = limit or min(SEND_CALL_BYTES, connector_limit(connector))
    return base - (ATTACHMENT_RESERVE_BYTES if n_attachments else 0)


def call_bytes(html_bytes, text_bytes, scan_sizes=()):
    """Total inline size of one send call, in bytes.

    >>> call_bytes(1000, 100, [300])          # 300 B -> 400 b64 chars
    1500
    """
    return html_bytes + text_bytes + sum(b64_chars(n) for n in scan_sizes)


def html_room(text_bytes, scan_sizes=(), limit=None, connector=None):
    """How many bytes of HTML body the send call can still carry.

    >>> html_room(15_508, [15_000, 15_000]) == call_limit(2) - 15_508 - 2 * 20_000
    True
    """
    limit = call_limit(len(list(scan_sizes)), limit, connector)
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
    """True when an attachment is within the per-file size limits.

    NOT a survival guarantee - see CEILING_B64_CHARS. Only reading the sent
    message back proves delivery; verify_sent does that comparison.
    """
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
