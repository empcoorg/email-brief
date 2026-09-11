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
    """Escape text for HTML. Quotes are left alone — attribute values in this
    codebase are built from known-safe literals, never from payload text."""
    return _html.escape(str(s), quote=False)
