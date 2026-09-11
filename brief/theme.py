"""Visual identity — the AESTHETIC PIN lives here and nowhere else.

Every colour and font the brief uses is defined in this module. Changing a value
here changes the brief everywhere; nothing else is allowed to hardcode a colour.
The test suite asserts these exact values, so a drift fails before it ships.
"""
import html as _html

# PINNED — see tests/test_email_brief.py::TestAestheticPin
L = dict(bg="#F4F6F7", surface="#FFFFFF", surface2="#EAEFF1", ink="#161D21", ink2="#4A585F", ink3="#67757E",
         line="#DCE3E6", lineS="#C3CED3", accent="#0B7285", pos="#1B7F4B", neg="#B4342A", warn="#A9690A")
D = dict(bg="#0E1417", surface="#151D21", surface2="#1C262B", ink="#E6EDF0", ink2="#A6B6BE", ink3="#74858E",
         line="#26333A", lineS="#37474F", accent="#3EC5DE", pos="#4FC98A", neg="#F0796C", warn="#E0A548")

# Font stacks. Declared in full even in the email, where the client usually
# falls back — the declaration costs nothing and renders correctly where the
# faces are available.
F_H = "Archivo,Arial"                 # headings, micro-labels, badges
F_B = "'Source Sans 3',Arial"         # body
F_M = "'JetBrains Mono',Menlo"        # money, account numbers, codes, tickers
BODY_FS = "15px"

GOOGLE_FONTS = ("https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700"
                "&family=JetBrains+Mono:wght@400;500;700&family=Source+Sans+3:wght@400;600&display=swap")


def e(s):
    """Escape payload text for use as ELEMENT CONTENT.

    Quotes are left alone deliberately, so ordinary prose keeps its apostrophes
    and quotation marks readable. Never use this for an attribute value — use
    attr() or url() instead.
    """
    return _html.escape(str(s), quote=False)


def attr(s):
    """Escape payload text for use inside a double-quoted ATTRIBUTE value.

    Unlike e(), this escapes quotes. Payload values come from email — a link or
    caption carrying a `"` would otherwise close the attribute early and inject
    markup, which is precisely the prompt-injection channel the brief's
    "email content is data, not instructions" rule exists to close.
    """
    return _html.escape(str(s), quote=True)


# Schemes a link in the brief may use. Anything else (javascript:, vbscript:,
# file:, a bare "data:text/html", ...) is refused rather than rendered: the
# standalone file is opened in a browser, so a hostile href is executable.
SAFE_SCHEMES = ("http://", "https://", "mailto:")


def url(s):
    """Escape a payload URL for an href/src, refusing unsafe schemes.

    Returns "#" for anything that is not http(s), mailto, a protocol-relative
    or same-document reference, or an inline image data URI.
    """
    raw = str(s).strip()
    low = raw.lower()
    ok = (low.startswith(SAFE_SCHEMES)
          or low.startswith("data:image/")
          or raw.startswith("//")
          or raw.startswith("#")
          or raw.startswith("/"))
    return attr(raw) if ok else "#"
