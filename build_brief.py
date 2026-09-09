#!/usr/bin/env python3
# AESTHETIC CONTRACT — the visual design in this file (colour tokens, fonts,
# sizes, spacing, markup structures, bar mechanics) is PINNED. Never alter it
# as a side effect of a content, feature, or bug-fix change; visual changes
# happen ONLY when explicitly requested, and must regenerate the README
# screenshots (docs/render_screenshots.py) in the same commit.
# Generates: morning-brief-2026-09-07.html (tokenised, theme-aware), email.html (inline light), email.txt
import base64, html as H, json, os

OUT_DIR = "/mnt/user-data/outputs"
SCRATCH = os.path.dirname(os.path.abspath(__file__))
os.makedirs(OUT_DIR, exist_ok=True)

# PINNED AESTHETICS — see the contract in the file header.
L = dict(bg="#F4F6F7", surface="#FFFFFF", surface2="#EAEFF1", ink="#161D21", ink2="#4A585F", ink3="#67757E",
         line="#DCE3E6", lineS="#C3CED3", accent="#0B7285", pos="#1B7F4B", neg="#B4342A", warn="#A9690A")
D = dict(bg="#0E1417", surface="#151D21", surface2="#1C262B", ink="#E6EDF0", ink2="#A6B6BE", ink3="#74858E",
         line="#26333A", lineS="#37474F", accent="#3EC5DE", pos="#4FC98A", neg="#F0796C", warn="#E0A548")

def e(s): return H.escape(str(s), quote=False)

# ------------------------------------------------------------------ DATA
# MOCK DATA ONLY — a fictional persona ("Alex Sample", example.com, 555 numbers,
# invented companies and figures) used for the README screenshots and as the
# layout reference. NEVER commit real brief content, email data, or personal
# details here — the daily run fills these structures in memory and writes
# outputs to /mnt/user-data/outputs only.
MAST = dict(
    title="Morning Brief",
    dateline="Tuesday, March 3, 2026",
    revised="",
    tz="America/New_York · EST (UTC−5)",
    window="Mon Mar 2, 9:00 AM → Tue Mar 3, 10:02 AM EST",
    slot="Tue Mar 3, 10:00 AM EST",
    run="Tue Mar 3, 10:02 AM EST",
    note="Only brief until the next scheduled run — covers the full ~25 h since yesterday's 10:00 AM brief. All content on this page is mock data for a fictional \u201cAlex Sample\u201d.",
)

USPS = dict(
    headline="1 mailpiece for the intended recipient (Alex Sample) today — detailed below with its full scan. Everyone else's mail is counted, never named.",
    pieces=[  # intended-recipient pieces ONLY: (date, sender, addressee as printed, type/notes)
        ("Tue Mar 3", "First Meridian Bank", "ALEX Q SAMPLE", "First-Class, window envelope · scan attached to the email as usps-2026-03-03-1.jpg"),
    ],
    counts="Not for the recipient: 2 piece(s) addressed to other named recipients — excluded (counted, never named) · 1 piece with generic addressee (\u201cCurrent Resident\u201d) — counted separately · 0 unreadable address blocks · 0 packages.",
    note="Only mail addressed to the intended recipient is ever detailed; its complete mailpiece scan is rendered below (full image, downsampled but readable) and attached to the email. Other named recipients and generic addressees (\u201cResident\u201d, \u201cHomeowner\u201d, \u201cCurrent Occupant\u201d) appear only as counts. An unreadable address block is listed by sender as \u201caddressee unverified\u201d rather than dropped.",
)
# Mock mailpiece scan (fictional, generated inline so the reference stays self-contained).
_SCAN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="760" height="360" viewBox="0 0 760 360">'
    '<rect width="760" height="360" fill="#e9e7e2"/><rect x="8" y="8" width="744" height="344" fill="#f6f4ef" stroke="#b8b4ac"/>'
    '<text x="20" y="32" font-family="monospace" font-size="13" fill="#6b675f">35720 *****AUTO**ALL FOR AADC 000</text>'
    '<text x="28" y="66" font-family="Georgia,serif" font-size="15" fill="#4a463f">FIRST MERIDIAN BANK</text>'
    '<text x="28" y="84" font-family="Georgia,serif" font-size="13" fill="#4a463f">PO BOX 100</text>'
    '<text x="28" y="100" font-family="Georgia,serif" font-size="13" fill="#4a463f">SPRINGFIELD ST 00000</text>'
    '<rect x="600" y="28" width="130" height="72" fill="none" stroke="#8b877e" stroke-dasharray="4 3"/>'
    '<text x="665" y="60" font-family="monospace" font-size="11" fill="#6b675f" text-anchor="middle">US POSTAGE</text>'
    '<text x="665" y="76" font-family="monospace" font-size="11" fill="#6b675f" text-anchor="middle">FIRST-CLASS</text>'
    '<text x="240" y="200" font-family="monospace" font-size="20" fill="#2f2c27">ALEX Q SAMPLE</text>'
    '<text x="240" y="226" font-family="monospace" font-size="17" fill="#2f2c27">123 MAIN ST APT 4</text>'
    '<text x="240" y="250" font-family="monospace" font-size="17" fill="#2f2c27">SPRINGFIELD ST 00000-0000</text>'
    + "".join(f'<rect x="{240 + i * 7}" y="272" width="{2 if i % 3 else 4}" height="26" fill="#2f2c27"/>' for i in range(58))
    + '<text x="20" y="342" font-family="monospace" font-size="11" fill="#8b877e">MOCK SCAN (fictional) — real briefs embed the actual USPS mailpiece image here.</text></svg>'
)
USPS_SCANS = [  # (data URI, caption) per intended-recipient piece
    ("data:image/svg+xml;base64," + base64.b64encode(_SCAN_SVG.encode()).decode(),
     "Full mailpiece scan — ALEX Q SAMPLE, First Meridian Bank envelope (mock image; downsampled but readable; attached to the email as usps-2026-03-03-1.jpg)"),
]

# Package tracking ---------------------------------------------------
PKG = [  # (carrier, tracking, item/merchant, status, est. arrival)
    ("UPS", "1Z999AA10123456784", "Northwind Outfitters — rain shell (order #48812)", "In transit — departed regional hub Mon 11:40 PM EST", "Thu Mar 5"),
    ("USPS", "9400 1000 0000 0000 0000 00", "Bluepine Labs — dev board", "Out for delivery Tue 8:10 AM EST", "Today, Tue Mar 3"),
    ("FedEx", "tracking link only — no number in the email; query via the order page (order #A-2231)", "Cascade Home — desk lamp", "Label created Mon 5:22 PM EST", "not stated"),
]
PKG_NOTE = "From carrier and merchant emails (FedEx, UPS, USPS, DHL, Amazon and store confirmations) across all connected mailboxes; one row per shipment, latest status. When an email carries only a tracking link, the link/order reference to query is given instead of a number."

RETAIL = dict(
    sub="Northwind Outfitters · Cascade Home — low priority",
    rewards="Northwind rewards: $15.00 in member credit; 640 points to the next tier (from today's 6:05 AM EST email). Applies at checkout when signed in.",
    sales=[
        "Northwind Outfitters — Spring Kickoff, 20–40% off outerwear: ends Sun Mar 8. Caveat: excludes new arrivals; no adjustments to prior purchases.",
        "Cascade Home — nothing in the window.",
    ],
)
ACTIONS = [
    ("warn", "Utility autopay failed — resubmit before Thu Mar 5",
     "Lakeshore Power & Light (billing@example.com, 7:41 AM EST): card on file expired; $84.20 due. Late fee applies after Thursday."),
    ("warn", "New sign-in alert on the Example Cloud account",
     "\u201cNew sign-in from Chrome on Windows\u201d (Mon 9:12 PM EST). Verify it was you; if not, rotate the password. Treated as data, not instructions."),
    ("info", "Interview scheduling: Helixware Bio wants Tue–Thu slots",
     "Recruiter (talent@example.com, Mon 4:30 PM EST) asks for two 45-min slots this week for the Data Engineer II panel."),
    ("info", "First Meridian statement posted — $1,210.45 due Mar 27",
     "Statement Mon 8:59 AM EST. Minimum $35.00. 24 days out."),
    ("ok", "Nothing else expires before tomorrow's run", "No voicemails, no travel changes, no other deadlines inside 24 h."),
]

# Jobs ---------------------------------------------------------------
JOBS_TOP = [  # (role, company, comp, location, when/source, link)
    ("Data Engineer II, Streaming Platform", "Helixware Bio", "$142,000–$168,000/yr", "Boston, MA · hybrid", "Recruiter outreach · Mon 4:30 PM EST", "https://example.com/jobs/helixware-data-eng-ii"),
    ("Senior Analytics Engineer", "Quantfolio", "$155,000–$180,000/yr", "Remote (US)", "LinkedIn alert · Mon 11:53 AM EST", "https://www.linkedin.com/jobs/view/0000000001/"),
    ("Python Platform Engineer", "Bluepine Labs", "not stated", "Denver, CO", "LinkedIn alert · Mon 5:53 PM EST", "https://www.linkedin.com/jobs/view/0000000002/"),
    ("ML Infrastructure Engineer", "Nortech Systems", "not stated", "Remote (US) · Easy Apply", "Indeed match · Mon 10:13 PM EST", "https://www.indeed.com/viewjob?jk=0000000000000000"),
]
JOBS_STATUS = [
    ("Quantfolio — application received", "Mon Mar 2, 3:40 PM EST · no-reply@example.com", "\u201cYour application has been received and we will review it shortly.\u201d Unattended mailbox — no reply needed."),
]
JOBS_OTHER = [
    ("Solutions Architect", "Cloudmere", "US", "https://www.linkedin.com/jobs/view/0000000003/"),
    ("BI Developer", "Grayline Retail Group", "Chicago, IL", "https://www.linkedin.com/jobs/view/0000000004/"),
]
JOBS_RANKED_NOTE = "ranked: data engineering \u00b7 Python \u00b7 streaming platforms first"
JOBS_TEAL_LABEL = "remote or preferred location \u00b7 adjacent AI/ML fit"
ALIGNERR = "Gig-platform digest (Mon 9:35 AM EST): hourly contract listings, $40–95/hr, none matching the configured interests — tracking links only."
JOBS_SKIPPED = "Skipped as off-target: two sales roles, a staffing-agency blast with no named employer, and a job-board newsletter with no actual postings."

# Finances -----------------------------------------------------------
FIN_SUMMARY = [("In from outside", "$2,450.00", "1 deposit"), ("Moved internally", "$500.00", "1 transfer between own accounts"), ("Outstanding", "$1,294.65", "card statement + utility bill")]
FIN_MOVES = [  # (date/time, payee, detail, amount_num, currency, direction word, sign)
    ("Mon Mar 2, 9:04 AM EST", "Acme Consulting → checking", "Invoice #241 paid \u00b7 ACH deposit \u00b7 First Meridian ···1234", 2450.00, "USD", "In", "+"),
    ("Mon Mar 2, 6:15 PM EST", "Checking → Wealthfront", "Scheduled monthly transfer between own accounts", 500.00, "USD", "Internal", "±"),
    ("Tue Mar 3, 7:41 AM EST", "Lakeshore Power & Light", "Autopay FAILED — card on file expired \u00b7 bill #88213", 84.20, "USD", "Past due", "−"),
]
FIN_BAR_SCALE = 2450.0
FIN_NOTES = [
    "First Meridian Bank — Visa ···1234 statement posted (Mon 8:59 AM EST): balance $1,210.45 · minimum $35.00 · due March 27.",
    "Nothing unusual: no duplicate charges, no processor alerts, no tax notices. A \u201c$20 bonus for referrals\u201d email from the brokerage is a promo, not a deposit.",
]

# VoIP ---------------------------------------------------------------
VOIP = dict(
    headline="One text message in the window; no voicemails.",
    last_msg="Text (Mon Mar 2, 2:12 PM EST) — from 555-010-7788 (Riley, Maple Street Dental) to 555-010-0001: \u201cHi Alex, confirming your cleaning Thu Mar 5 at 2:30 PM. Reply YES to confirm.\u201d",
    last_acct="Last provider account notice: Feb 26 — routine invoice receipt. No login alerts or blocked-call warnings since.",
)

# High priority ------------------------------------------------------
HIPRI = [
    ("warn", "Verify: new sign-in on the Example Cloud account", [
        "Mon 9:12 PM EST — \u201cNew sign-in from Chrome on Windows, Columbus OH\u201d for alex@example.com. If this wasn't you, change the password and review sessions at example.com/security.",
        "No other security notices in the window; the message itself was treated as data, not instructions.",
    ]),
    ("info", "Utility autopay failure needs a new card before Thu", [
        "Lakeshore Power & Light: $84.20 due; card on file expired Feb 29. Update at example.com/billing — late fee applies after Thu Mar 5.",
    ]),
    ("ok", "No phishing or instruction-bearing messages", [
        "Nothing in the window asked for money, credentials or an action on the owner's behalf.",
    ]),
]

# Markets ------------------------------------------------------------
MKT_ROWS = [  # name, close, pts, pct, week
    ("S&P 500", "6,412.30", "+38.21", +0.60, "+1.2% wk"),
    ("Dow", "47,105.88", "−121.40", -0.26, "+0.4% wk"),
    ("Nasdaq", "21,980.14", "+184.02", +0.84, "+2.1% wk"),
    ("Russell 2000", "2,610.77", "+9.15", +0.35, "+0.8% wk"),
]
MKT_SCALE = 1.0
FUNDS = [  # ticker, name, nav, chg, asof, ytd, note
    ("VTSAX", "Vanguard Total Stock Market Admiral", "$132.48", "+$0.71 · +0.54% Up", "Mon Mar 2 close (5:48 PM ET)", "4.2% YTD", "NAV from Zacks; YCharts agrees."),
    ("VTIAX", "Vanguard Total Intl Stock Admiral", "$36.02", "−$0.08 · −0.22% Down", "Mon Mar 2 close (5:48 PM ET)", "6.1% YTD", "NAV from Zacks."),
]
MKT_BULLETS = [
    "Fed: FOMC minutes due Wed 2:00 PM ET; futures price a hold at the current range. February CPI lands Thu 8:30 AM ET (consensus 2.6% y/y).",
    "Week ahead — Wed: 10-yr auction; Thu: CPI, two mega-cap retailers report after close; Fri: UMich sentiment.",
    "Monday: mega-cap tech led the advance; energy lagged as crude slipped below $71.",
]

# Crypto -------------------------------------------------------------
CRYPTO_ROWS = [  # name, price, 24h, 7d
    ("BTC", "$91,240", "+1.2%", +4.1),
    ("ETH", "$3,105", "+0.8%", +2.9),
    ("SOL", "$168.40", "−0.6%", +1.5),
    ("XRP", "$1.72", "+0.3%", -1.2),
    ("BNB", "$612.00", "+0.5%", +0.9),
    ("DOGE", "$0.142", "−1.8%", -3.4),
]
CRYPTO_SCALE = 5.0
CRYPTO_NOTE = "Prices from CoinMarketCap ~9:55 AM EST; 7 d figures cross-checked against CoinGecko."
CRYPTO_BULLETS = [
    "BTC held above $90K for a fourth session; weekly ETF inflows remain positive per Farside's tracker.",
    "Regulation: the stablecoin bill markup is scheduled for Thu; no exchange incidents in the window.",
]

# AI -----------------------------------------------------------------
AI_ITEMS = [
    ("Open-weights release: Cascade-2 70B (Mar 2)", "A research lab released a 70B open-weights model with a permissive license and strong tool-use scores; day-one support landed in the major inference runtimes.", "https://example.com/ai/cascade-2"),
    ("Security — patch now: browser zero-day CVE-2026-00000", "Actively exploited type-confusion bug; fixed in the current stable channel. All Chromium-based tools affected.", "https://example.com/security/browser-zero-day"),
    ("Postgres 18 beta ships built-in columnar storage (Mar 1)", "The beta adds a native columnar access method aimed at analytics workloads, with early benchmarks showing 4–8× scan speedups.", "https://example.com/dev/postgres-18-beta"),
]

ALLOWLIST = {
 "Markets / finance": "finance.yahoo.com · reuters.com · zacks.com · ycharts.com · investing.com · federalreserve.gov · bls.gov",
 "Crypto": "coindesk.com · cointelegraph.com · coinmarketcap.com · coingecko.com · farside.co.uk",
 "AI / programming": "news.ycombinator.com · thehackernews.com · python.org · github.blog",
 "Additional domains fetched this run": "stockanalysis.com · theblock.co. Blocked/failed and abandoned: two paywalled news sites (403).",
}

FIN_INTERNAL = "One scheduled transfer between the owner's own accounts today (in the table above); no other internal movement."

SOURCES = {
 "Markets": ["https://example.com/markets-source-1", "https://example.com/markets-source-2", "https://example.com/markets-source-3"],
 "Crypto": ["https://example.com/crypto-source-1", "https://example.com/crypto-source-2"],
 "AI & programming": ["https://example.com/ai-source-1", "https://example.com/ai-source-2"],
 "Mailbox items referenced": ["https://example.com/mailbox-item-1"],
}

# ------------------------------------------------------------------ shared helpers
SCAN_CSS = ".scanfig{margin:14px 0 4px}.scanfig img{max-width:min(720px,100%);border:1px solid var(--line);border-radius:6px;display:block}.scanfig figcaption{font-size:12.5px;color:var(--ink-3);margin-top:6px}"
def cur_sym(cur): return {"USD": "$", "MXN": "MX$", "EUR": "\u20ac", "GBP": "\u00a3"}.get(cur, cur + " ")
import re as _re
def short_url(u):
    v = _re.sub(r"^https?://(www\.)?", "", u)
    return v[:72] + ("…" if len(v) > 72 else "")
def lead_split(text):
    """Split a bullet into (lead-in, rest) at the first ': ' or ' — ' within the first ~60 chars."""
    m = _re.match(r'^(.{2,60}?)(: | — )(.*)$', text, _re.S)
    if m: return m.group(1), m.group(2), m.group(3)
    return None, "", text

def job_fit(role):
    r = role.lower()
    strong = ("scientist", "computational", "genom", "rna", "crispr", "sequenc", "bioinformat", "biolog", "data scien", "postdoc")
    adjacent = ("ai", "ml", "machine", "engineer", "informatics", "knowledge")
    if any(k in r for k in strong): return "Strong fit", "pos"
    if any(k in r for k in adjacent): return "Adjacent", "accent"
    return "", ""
def loc_tier(loc):
    l = loc.lower()
    if any(k in l for k in ("boston", "denver", "preferred")): return "accent", "Preferred area"
    if "remote" in l: return "accent", "Remote"
    return "", ""

# ------------------------------------------------------------------ RENDER: FILE (tokens)
def bar_div(pct, scale):
    w = min(abs(pct) / scale, 1.0) * 50
    side = "right" if pct >= 0 else "left"
    cls = "pos" if pct >= 0 else "neg"
    return f'<div class="dbar" aria-hidden="true"><div class="fill {cls} {side}" style="width:{w:.1f}%"></div></div>'

def li_lead(text):
    a, sep, b = lead_split(text)
    if a: return f'<li><span class="lead">{e(a)}</span>{e(sep.rstrip()) if sep.strip()==":" else " —"} {e(b)}</li>'
    return f'<li>{e(text)}</li>'

def tdl(label, inner, cls=""):
    return f'<td class="{cls}" data-l="{e(label)}">{inner}</td>'

def file_html():
    css = f"""
:root{{--bg:{L['bg']};--surface:{L['surface']};--surface-2:{L['surface2']};--ink:{L['ink']};--ink-2:{L['ink2']};--ink-3:{L['ink3']};--line:{L['line']};--line-strong:{L['lineS']};--accent:{L['accent']};--positive:{L['pos']};--negative:{L['neg']};--warning:{L['warn']};}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:{D['bg']};--surface:{D['surface']};--surface-2:{D['surface2']};--ink:{D['ink']};--ink-2:{D['ink2']};--ink-3:{D['ink3']};--line:{D['line']};--line-strong:{D['lineS']};--accent:{D['accent']};--positive:{D['pos']};--negative:{D['neg']};--warning:{D['warn']};}}}}
:root[data-theme="dark"]{{--bg:{D['bg']};--surface:{D['surface']};--surface-2:{D['surface2']};--ink:{D['ink']};--ink-2:{D['ink2']};--ink-3:{D['ink3']};--line:{D['line']};--line-strong:{D['lineS']};--accent:{D['accent']};--positive:{D['pos']};--negative:{D['neg']};--warning:{D['warn']};}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:"Source Sans 3",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:15.5px;line-height:1.55}}
h1,h2,h3,.lbl,.act-title{{font-family:Archivo,"Helvetica Neue",Arial,sans-serif}}
.mono{{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}}
a{{color:var(--accent);text-decoration:none}} a:hover{{text-decoration:underline}}
.wrap{{max-width:1180px;margin:0 auto;padding:28px 20px 60px}}
.mast{{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:22px 26px;display:grid;grid-template-columns:1.4fr 1fr;gap:18px}}
.mast h1{{margin:0 0 4px;font-size:30px;font-weight:700;letter-spacing:-.01em}}
.mast .date{{font-size:17px;color:var(--ink-2);font-weight:600}}
.mast .note{{margin-top:10px;font-size:13.5px;color:var(--ink-3)}} .mast .rev{{margin-top:6px;font-size:13px;color:var(--warning);font-weight:600}}
.stamps{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px;align-content:start}}
.stamp .val{{font-size:13.5px;margin-top:2px}}
.lbl{{font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);font-weight:600}}
section{{margin-top:26px}}
h2{{font-size:19px;font-weight:700;margin:0 0 12px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}}
h2 .num{{color:var(--accent);font-weight:700}} h2 .sub{{font-family:"Source Sans 3",sans-serif;font-weight:400;color:var(--ink-3);font-size:13.5px}}
h3{{font-size:14.5px;font-weight:600;margin:16px 0 6px;color:var(--ink-2)}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px 20px}}
.actions{{display:grid;gap:8px}}
.act{{display:grid;grid-template-columns:6px 1fr;gap:14px;background:var(--surface);border:1px solid var(--line);border-radius:10px;overflow:hidden}}
.act .stripe{{background:var(--ink-3)}} .act.warn .stripe{{background:var(--warning)}} .act.neg .stripe{{background:var(--negative)}} .act.ok .stripe{{background:var(--positive)}} .act.info .stripe{{background:var(--accent)}}
.act .body{{padding:11px 14px 11px 0}}
.act-title{{font-weight:600;font-size:15px}} .act .tag{{display:inline-block;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;padding:1px 7px;border-radius:5px;border:1px solid var(--line-strong);color:var(--ink-2);margin-right:8px;vertical-align:middle}}
.act.warn .tag{{color:var(--warning);border-color:var(--warning)}} .act.ok .tag{{color:var(--positive);border-color:var(--positive)}} .act.info .tag{{color:var(--accent);border-color:var(--accent)}} .act.neg .tag{{color:var(--negative);border-color:var(--negative)}}
.act .det{{color:var(--ink-2);font-size:14px;margin-top:2px}}
.nothing{{color:var(--ink-3);font-style:italic;padding:8px 0}}
.lead{{color:var(--accent);font-weight:600}}
.tbl-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--surface)}}
table{{border-collapse:collapse;width:100%;min-width:640px;font-size:14px}}
th{{text-align:left;font-family:Archivo,sans-serif;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);font-weight:600;padding:10px 12px;border-bottom:1px solid var(--line-strong);background:var(--surface-2)}}
td{{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}} tr:last-child td{{border-bottom:0}}
td.num{{text-align:right;white-space:nowrap}}
.dir-pos,.c-pos{{color:var(--positive);font-weight:600}} .dir-neg,.c-neg{{color:var(--negative);font-weight:600}} .dir-neu{{color:var(--ink-2);font-weight:600}} .c-accent{{color:var(--accent);font-weight:600}} .c-warn{{color:var(--warning);font-weight:600}} .muted{{color:var(--ink-3)}}
.badge{{display:inline-block;font-family:Archivo,sans-serif;font-size:10px;letter-spacing:.06em;text-transform:uppercase;padding:1px 6px;border-radius:4px;border:1px solid currentColor;margin-left:6px;vertical-align:middle;font-weight:600}}
.legend{{font-size:12.5px;color:var(--ink-3);margin-top:8px}} .legend span{{margin-right:14px;white-space:nowrap}}
.dbar{{position:relative;height:12px;width:150px;background:var(--surface-2);border-radius:3px}}
.dbar::before{{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--line-strong)}}
.dbar .fill{{position:absolute;top:2px;bottom:2px;min-width:3px;border-radius:2px}}
.dbar .fill.right{{left:50%}} .dbar .fill.left{{right:50%}} .fill.pos{{background:var(--positive)}} .fill.neg{{background:var(--negative)}}
.sbar{{position:relative;height:12px;width:150px;background:var(--surface-2);border-radius:3px}} .sbar .fill{{position:absolute;left:0;top:2px;bottom:2px;min-width:3px;border-radius:2px;background:var(--negative)}} .sbar .fill.neu{{background:var(--ink-3)}}
.cap{{font-size:12.5px;color:var(--ink-3);padding:8px 2px}}
.tiles{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}}
.tile{{background:var(--surface-2);border-radius:10px;padding:12px 14px}} .tile .v{{font-size:22px;font-weight:700;margin:2px 0}} .tile .d{{font-size:12.5px;color:var(--ink-3)}}
ul{{margin:8px 0 0;padding-left:20px}} li{{margin:9px 0;line-height:1.55}}
.jobs li b{{font-weight:600}} .meta{{color:var(--ink-3);font-size:13px}}
.grid3{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
.grid3 .card{{min-width:0}} .grid3 h2{{font-size:17px}}
.grid3 .tbl-wrap table{{min-width:0;font-size:12px}} .grid3 th,.grid3 td{{padding:6px 6px}} .grid3 td.num{{white-space:normal}} .grid3 .dbar{{width:56px}}
.hp{{border-left:4px solid var(--ink-3);padding:10px 14px;margin:10px 0;background:var(--surface-2);border-radius:0 8px 8px 0}} .hp.warn{{border-color:var(--warning)}} .hp.ok{{border-color:var(--positive)}} .hp.info{{border-color:var(--accent)}}
.hp .t{{font-weight:600;font-family:Archivo,sans-serif}} .hp.warn .t{{color:var(--warning)}} .hp.ok .t{{color:var(--positive)}} .hp.info .t{{color:var(--accent)}}
details{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 16px;margin-top:18px}} summary{{cursor:pointer;font-family:Archivo,sans-serif;font-weight:600;font-size:14px}}
.allow p{{font-size:12.5px;margin:6px 0}} .allow b{{color:var(--ink-2)}}
.src{{columns:2;column-gap:28px;font-size:11.5px;margin-top:8px}} .src p{{break-inside:avoid;margin:0 0 4px;overflow-wrap:anywhere}} .src b{{display:block;margin:8px 0 3px;color:var(--ink-2)}}
footer{{margin-top:28px;font-size:12.5px;color:var(--ink-3);border-top:1px solid var(--line);padding-top:14px}}
@media (max-width:940px){{.grid3{{grid-template-columns:1fr}} .mast{{grid-template-columns:1fr}} .tiles{{grid-template-columns:1fr}} .src{{columns:1}} .grid3 .tbl-wrap table{{font-size:14px}} .grid3 th,.grid3 td{{padding:9px 12px}} .grid3 .dbar{{width:150px}}}}
@media (max-width:600px){{
 body{{font-size:17px;line-height:1.6}} .wrap{{padding:14px 10px 40px}} .mast{{padding:16px}} .mast h1{{font-size:26px}} .stamps{{grid-template-columns:1fr}} .stamp .val{{font-size:15px}}
 .card{{padding:14px}} .act{{grid-template-columns:5px 1fr;gap:10px}} .act-title{{font-size:16px}} .act .det{{font-size:15px}}
 .tbl-wrap{{border:0;background:transparent;overflow:visible}}
 table,thead,tbody,tr,td,th{{display:block;min-width:0;width:100%}} thead{{display:none}}
 tr{{background:var(--surface);border:1px solid var(--line);border-radius:10px;margin:0 0 10px;padding:6px 0}}
 td{{border:0;padding:5px 12px;font-size:15px;text-align:left!important;white-space:normal!important}}
 td[data-l]::before{{content:attr(data-l);display:block;font-family:Archivo,sans-serif;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);margin-bottom:1px}}
 td.num{{text-align:left}} .dbar,.sbar{{width:100%}} .grid3 .dbar{{width:100%}} .grid3 .tbl-wrap table{{font-size:15px}}
 li{{margin:11px 0}} .meta{{font-size:14px}} .legend span{{display:block;margin:2px 0}}
}}
"""
    o = []
    o.append("<title>Morning Brief</title>")
    o.append('<meta name="color-scheme" content="light dark">')
    o.append('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    o.append('<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">')
    o.append(f"<style>{css}{SCAN_CSS}</style>")
    o.append('<div class="wrap">')
    o.append(f"""<header class="mast"><div><h1>{e(MAST['title'])}</h1><div class="date">{e(MAST['dateline'])}</div><div class="note">{e(MAST['note'])}</div><div class="rev">{e(MAST['revised'])}</div></div>
<div class="stamps">
<div class="stamp"><div class="lbl">Timezone</div><div class="val">{e(MAST['tz'])}</div></div>
<div class="stamp"><div class="lbl">Scheduled slot</div><div class="val mono">{e(MAST['slot'])}</div></div>
<div class="stamp"><div class="lbl">Window covered</div><div class="val mono">{e(MAST['window'])}</div></div>
<div class="stamp"><div class="lbl">Run stamp</div><div class="val mono">{e(MAST['run'])}</div></div>
</div></header>""")
    o.append('<section><h2>Needs you today <span class="sub">ranked; nothing expires before tomorrow\'s run</span></h2><div class="actions">')
    tagmap = {"warn": "Check", "neg": "Urgent", "info": "Note", "ok": "Clear"}
    for sev, t, d in ACTIONS:
        o.append(f'<div class="act {sev}"><div class="stripe"></div><div class="body"><div class="act-title"><span class="tag">{tagmap[sev]}</span>{e(t)}</div><div class="det">{e(d)}</div></div></div>')
    o.append('</div></section>')
    # 1 jobs
    o.append(f'<section><h2><span class="num">1.</span> Relevant job posts <span class="sub">{e(JOBS_RANKED_NOTE)}</span></h2><div class="card">')
    o.append('<h3 style="margin-top:0">Application status</h3><ul class="jobs">')
    for t, m, d in JOBS_STATUS:
        o.append(f'<li><span class="lead">{e(t)}</span> <span class="meta">— {e(m)}</span><br>{e(d)}</li>')
    o.append('</ul><h3>Ranked leads</h3><div class="tbl-wrap"><table><thead><tr><th>Role</th><th>Company</th><th>Comp</th><th>Location</th><th>Source · received</th><th>Link</th></tr></thead><tbody>')
    for r, c, comp, loc, src, link in JOBS_TOP:
        fit, fcls = job_fit(r); lcls, ltag = loc_tier(loc)
        role = f'<b>{e(r)}</b>' + (f'<span class="badge c-{fcls}">{fit}</span>' if fit else "")
        compc = f'<span class="c-pos">{e(comp)}</span>' if comp != "not stated" else f'<span class="muted">{e(comp)}</span>'
        locc = f'<span class="c-accent">{e(loc)}</span>' if lcls else e(loc)
        o.append('<tr>' + tdl("Role", role) + tdl("Company", e(c)) + tdl("Comp", compc, "mono") + tdl("Location", locc) + tdl("Source · received", e(src), "meta") + tdl("Link", f'<a href="{e(link)}">open</a>') + '</tr>')
    o.append('</tbody></table></div><div class="legend"><span><b class="c-pos">Green</b> = comp stated / strong fit</span><span><b class="c-accent">Teal</b> = ' + e(JOBS_TEAL_LABEL) + '</span><span><b class="c-warn">Amber</b> = deadline stated (none today)</span><span class="muted">Grey = not stated</span></div>')
    o.append('<h3>Also seen (lower fit)</h3><ul class="jobs">')
    for r, c, loc, link in JOBS_OTHER:
        lcls, _ = loc_tier(loc)
        locc = f'<span class="c-accent">{e(loc)}</span>' if lcls else f'<span class="meta">{e(loc)}</span>'
        o.append(f'<li>{e(r)} — {e(c)} · {locc} · <a href="{e(link)}">link</a></li>')
    o.append(f'</ul><p class="meta">{e(ALIGNERR)}</p><p class="meta">{e(JOBS_SKIPPED)}</p></div></section>')
    # 2 finances
    o.append('<section><h2><span class="num">2.</span> Deposits &amp; finances</h2><div class="card"><div class="tiles">')
    for l, v, d in FIN_SUMMARY:
        o.append(f'<div class="tile"><div class="lbl">{e(l)}</div><div class="v mono">{e(v)}</div><div class="d">{e(d)}</div></div>')
    o.append('</div><h3 style="margin-top:0">Money movements (outside → you / you → outside)</h3><div class="tbl-wrap"><table><thead><tr><th>When</th><th>Payee / source</th><th>Detail</th><th>Direction</th><th style="text-align:right">Amount</th><th>Bar</th></tr></thead><tbody>')
    for when, payee, det, amt, cur, dirw, sign in FIN_MOVES:
        cls = "dir-neg" if dirw == "Out" else ("dir-pos" if dirw == "In" else "dir-neu")
        w = min(amt / FIN_BAR_SCALE, 1.0) * 100
        fcls = "" if dirw == "Out" else "neu"
        amt_s = (sign if sign != "±" else "") + f"{cur_sym(cur)}{amt:,.2f}"
        o.append('<tr>' + tdl("When", e(when), "mono") + tdl("Payee / source", e(payee)) + tdl("Detail", e(det)) + tdl("Direction", f'<span class="{cls}">{e(sign)} {e(dirw)}</span>') + tdl("Amount", amt_s, "num mono") + tdl("Bar", f'<div class="sbar"><div class="fill {fcls}" style="width:{w:.0f}%"></div></div>') + '</tr>')
    o.append('</tbody></table></div><div class="cap">Bar scale: full width = the largest movement in the window.</div>')
    o.append('<h3>Transfers between your own accounts</h3><div class="nothing">' + e(FIN_INTERNAL) + '</div><h3>Bills, statements &amp; notices</h3><ul>')
    for n in FIN_NOTES: o.append(li_lead(n))
    o.append('</ul></div></section>')
    # 3 voip
    o.append(f'<section><h2><span class="num">3.</span> VoIP voicemails &amp; texts <span class="sub">searched by the configured provider senders + Google Voice, Twilio, OpenPhone, Grasshopper, RingCentral, Dialpad</span></h2><div class="card"><div class="nothing">{e(VOIP["headline"])}</div><ul>{li_lead(VOIP["last_msg"])}{li_lead(VOIP["last_acct"])}</ul></div></section>')
    # 4 high priority
    o.append('<section><h2><span class="num">4.</span> High priority</h2><div class="card">')
    for sev, t, items in HIPRI:
        o.append(f'<div class="hp {sev}"><div class="t">{e(t)}</div><ul>' + "".join(li_lead(i) for i in items) + "</ul></div>")
    o.append('</div></section>')
    # 5 USPS
    o.append(f'<section><h2><span class="num">5.</span> USPS Informed Delivery <span class="sub">mail addressed to the intended recipient only; everyone else counted, never named</span></h2><div class="card"><div class="nothing">{e(USPS["headline"])}</div>')
    o.append('<div class="tbl-wrap"><table><thead><tr><th>Date</th><th>Sender</th><th>Addressee (as printed)</th><th>Type / notes</th></tr></thead><tbody>')
    for d_, s_, a_, ty in USPS["pieces"]:
        o.append('<tr>' + tdl("Date", e(d_), "mono") + tdl("Sender", e(s_)) + tdl("Addressee (as printed)", e(a_), "mono") + tdl("Type / notes", e(ty), "meta") + '</tr>')
    o.append('</tbody></table></div>')
    for uri, cap_ in USPS_SCANS:
        o.append(f'<figure class="scanfig"><img src="{uri}" alt="Full mailpiece scan (mock)"><figcaption>{e(cap_)}</figcaption></figure>')
    o.append(f'<ul>{li_lead(USPS["counts"])}</ul><p class="meta">{e(USPS["note"])}</p></div></section>')
    # 6 package tracking
    o.append('<section><h2><span class="num">6.</span> Package tracking <span class="sub">FedEx · UPS · USPS · DHL · merchant shipping emails</span></h2><div class="card"><div class="tbl-wrap"><table><thead><tr><th>Carrier</th><th>Tracking</th><th>Item / merchant</th><th>Status</th><th>Est. arrival</th></tr></thead><tbody>')
    for car, trk, item, st, eta in PKG:
        o.append('<tr>' + tdl("Carrier", e(car)) + tdl("Tracking", e(trk), "mono") + tdl("Item / merchant", e(item)) + tdl("Status", e(st), "meta") + tdl("Est. arrival", e(eta), "mono") + '</tr>')
    o.append(f'</tbody></table></div><p class="meta">{e(PKG_NOTE)}</p></div></section>')
    # 7 retail (low priority)
    o.append(f'<section><h2><span class="num">7.</span> Retail sales <span class="sub">{e(RETAIL["sub"])}</span></h2><div class="card"><ul>' + li_lead(RETAIL["rewards"]) + "".join(li_lead(x) for x in RETAIL["sales"]) + '</ul></div></section>')
    # research grid
    o.append('<section><div class="grid3">')
    o.append('<div class="card"><h2>US market</h2><div class="tbl-wrap"><table><thead><tr><th>Index</th><th style="text-align:right">Fri close</th><th style="text-align:right">Move</th><th>Bar</th></tr></thead><tbody>')
    for n, c, pts, pct, wk in MKT_ROWS:
        cls = "dir-pos" if pct >= 0 else "dir-neg"; word = "Up" if pct >= 0 else "Down"
        o.append('<tr>' + tdl("Index", e(n), "mono") + tdl("Fri close", e(c), "num mono") + tdl("Move · week", f'<span class="{cls}">{e(pts)}<br>{pct:+.2f}% {word}</span><br><span class="meta">{e(wk)}</span>', "num mono") + tdl("Bar", bar_div(pct, MKT_SCALE)) + '</tr>')
    o.append(f'</tbody></table></div><div class="cap">Diverging bars from a centre baseline; half-width = ±{MKT_SCALE:.1f}% daily move.</div>')
    o.append('<h3>Vanguard funds</h3><div class="tbl-wrap"><table><thead><tr><th>Fund</th><th style="text-align:right">NAV</th><th style="text-align:right">Change</th><th>As of</th></tr></thead><tbody>')
    for tk, nm, nav, chg, asof, ytd, note in FUNDS:
        cls = "dir-pos" if "+" in chg.split("·")[0] else "dir-neg"
        o.append('<tr>' + tdl("Fund", f'<span class="lead">{e(tk)}</span>', "mono") + tdl("NAV", e(nav), "num mono") + tdl("Change", f'<span class="{cls}">{e(chg)}</span>', "num mono") + tdl("As of", e(asof), "meta") + '</tr>')
    o.append('</tbody></table></div><div class="cap">' + " ".join(f'<b>{e(tk)}</b> ({e(nm)}): YTD {e(ytd)}. {e(note)}' for tk, nm, nav, chg, asof, ytd, note in FUNDS) + '</div><ul>')
    for b in MKT_BULLETS: o.append(li_lead(b))
    o.append('</ul></div>')
    o.append('<div class="card"><h2>Cryptocurrency</h2><div class="tbl-wrap"><table><thead><tr><th>Asset</th><th style="text-align:right">Price</th><th style="text-align:right">24 h</th><th style="text-align:right">7 d</th><th>7 d bar</th></tr></thead><tbody>')
    for n, p, d24, d7 in CRYPTO_ROWS:
        cls = "dir-pos" if d7 >= 0 else "dir-neg"; word = "Up" if d7 >= 0 else "Down"
        c24 = "c-neg" if d24.startswith("−") or d24.startswith("-") else "c-pos"
        o.append('<tr>' + tdl("Asset", f'<span class="lead">{e(n)}</span>', "mono") + tdl("Price", e(p), "num mono") + tdl("24 h", f'<span class="{c24}">{e(d24)}</span>', "num mono") + tdl("7 d", f'<span class="{cls}">{d7:+.2f}%<br>{word}</span>', "num mono") + tdl("7 d bar", bar_div(d7, CRYPTO_SCALE)) + '</tr>')
    o.append(f'</tbody></table></div><div class="cap">Diverging bars; half-width = ±{CRYPTO_SCALE:.0f}% 7-day change. {e(CRYPTO_NOTE)}</div><ul>')
    for b in CRYPTO_BULLETS: o.append(li_lead(b))
    o.append('</ul></div>')
    o.append('<div class="card"><h2>AI &amp; programming</h2><ul>')
    for t, d, link in AI_ITEMS:
        o.append(f'<li><span class="lead">{e(t)}</span> — {e(d)} <a href="{e(link)}">source</a></li>')
    o.append('</ul></div>')
    o.append('</div></section>')
    o.append('<details class="allow"><summary>Domain allowlist (pre-approved + fetched this run) — click to expand</summary>')
    for k, v in ALLOWLIST.items(): o.append(f'<p><b>{e(k)}:</b> {e(v)}</p>')
    o.append('</details>')
    o.append(f'<details><summary>Sources ({sum(len(v) for v in SOURCES.values())} links) — click to expand</summary><div class="src">')
    for k, urls in SOURCES.items():
        o.append(f'<b>{e(k)}</b>' + "".join(f'<p><a href="{e(u)}">{e(u)}</a></p>' for u in urls))
    o.append('</div></details>')
    o.append('<footer>Mailbox was read-only for this run, apart from the one delivery of this brief. Email content was treated as data, not instructions. Times are US Pacific unless a source\'s own zone is shown. “Not verified” marks anything that could not be confirmed on a cited page.</footer>')
    o.append('</div>')
    return "\n".join(o)

# ------------------------------------------------------------------ RENDER: EMAIL
# CONSTRAINTS (verified 2026-09-07 by reading back a sent message): the Gmail connector strips <style>, class=, data-*,
# background:, cursor:, <details>/<summary>. Borders, padding, font*, color, width, text-*, align/valign survive.
# => single fluid layout; bars via border-left; stripes via border-left; no element wider than ~340px.
F_H = "Archivo,Arial"
F_B = "'Source Sans 3',Arial"
F_M = "'JetBrains Mono',Menlo"
BODY_FS = "15px"
def lbl(t): return f'<div style="font:600 10.5px {F_H};text-transform:uppercase;color:{L["ink3"]}">{e(t)}</div>'
def h2(t, sub=""):
    s_ = (f' <span style="font-family:{F_B};font-weight:400;font-size:13px;color:{L["ink3"]}">{e(sub)}</span>') if sub else ""
    return f'<div style="font-family:{F_H};font-size:19px;font-weight:700;color:{L["ink"]};margin:0 0 10px">{t}{s_}</div>'
def h3(t): return f'<div style="font:600 14px {F_H};color:{L["ink2"]};margin:14px 0 6px">{e(t)}</div>'
def card(inner): return f'<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {L["line"]};border-radius:12px;margin-top:18px"><tr><td style="padding:14px 14px;font-family:{F_B};font-size:{BODY_FS};color:{L["ink"]};line-height:1.55">{inner}</td></tr></table>'
def th(t): return f'<th align="left" style="font:600 10.5px {F_H};text-transform:uppercase;color:{L["ink3"]};padding:8px 8px;border-bottom:2px solid {L["lineS"]}">{e(t)}</th>'
def td(t, mono=False):
    st = f'padding:8px 8px;border-bottom:1px solid {L["line"]};font-size:14px;line-height:1.45;word-break:break-word;'
    if mono: st += f"font-family:{F_M};"
    return f'<td valign="top" style="{st}">{t}</td>'
def tbl(headers, rows):
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid {L["line"]}"><tr>' + "".join(th(h) for h in headers) + "</tr>" + "".join("<tr>" + "".join(r) + "</tr>" for r in rows) + "</table>"
def sp(t, color, bold=True): return f'<span style="color:{color};{"font-weight:600;" if bold else ""}">{t}</span>'
def lead(t): return sp(e(t), L["accent"])
def muted(t): return f'<span style="color:{L["ink3"]}">{t}</span>'
def small(t): return f'<span style="color:{L["ink3"]};font-size:12.5px">{t}</span>'
def em_li(text):
    a, sep, b = lead_split(text)
    if a: return f'<li style="margin:9px 0">{lead(a)}{":" if sep.strip()==":" else " —"} {e(b)}</li>'
    return f'<li style="margin:9px 0">{e(text)}</li>'
def ul(items): return '<ul style="margin:8px 0 0;padding-left:20px">' + "".join(f'<li style="margin:9px 0">{i}</li>' for i in items) + "</ul>"
def _seg(w, col): return f'<span style="display:inline-block;width:0;height:0;border-left:{w}px solid {col};border-top:5px solid {col};border-bottom:5px solid {col}"></span>'
def bar_div(pct, scale, total=80):
    half = total // 2; w = max(3, int(min(abs(pct)/scale, 1.0) * half)); col = L["pos"] if pct >= 0 else L["neg"]
    if pct >= 0:
        return f'<div style="font-size:0;line-height:0"><span style="display:inline-block;width:{half}px;height:10px;border-right:1px solid {L["lineS"]}"></span>{_seg(w, col)}</div>'
    return f'<div style="font-size:0;line-height:0"><span style="display:inline-block;width:{half-w}px;height:10px"></span>{_seg(w, col)}<span style="display:inline-block;width:{half}px;height:10px;border-left:1px solid {L["lineS"]}"></span></div>'
def bar_single(val, scale, neu=False, total=80):
    w = max(3, int(min(val/scale, 1.0) * total)); col = L["ink3"] if neu else L["neg"]
    return f'<div style="font-size:0;line-height:0">{_seg(w, col)}<span style="display:inline-block;width:{total-w}px;height:10px;border-bottom:1px solid {L["lineS"]}"></span></div>'
def cap(t): return f'<div style="font-size:12px;color:{L["ink3"]};padding:6px 2px">{e(t)}</div>'
def stripe_row(color, title_html, det_html):
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {L["line"]};border-left:6px solid {color};margin-top:6px"><tr><td style="padding:10px 12px"><div style="font:600 15px {F_H};color:{L["ink"]}">{title_html}</div><div style="font-size:14px;color:{L["ink2"]};margin-top:2px">{det_html}</div></td></tr></table>'

LAYOUT_NOTE = ("Layout: one fluid layout for phone and desktop (the mail path strips stylesheets, so the email cannot adapt itself). "
               "The standalone file <b>morning-brief-2026-09-07.html</b> — full desktop tables, mobile cards, dark mode, collapsible sources, "
               "and embedded USPS scans — is delivered in the Claude session alongside this email.")

def email_html():
    o = [f'<div style="padding:12px 6px;font-family:{F_B};color:{L["ink"]}"><table width="100%" cellpadding="0" cellspacing="0" style="max-width:860px;margin:0 auto"><tr><td>']
    stamps = "".join(f'<div style="margin-top:8px">{lbl(k)}<div style="font-family:{F_M};font-size:14px">{e(v)}</div></div>' for k, v in [("Timezone", MAST["tz"]), ("Scheduled slot", MAST["slot"]), ("Window covered", MAST["window"]), ("Run stamp", MAST["run"])])
    o.append(f'<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {L["line"]};border-radius:14px"><tr><td style="padding:18px 16px">'
             f'<div style="font-family:{F_H};font-size:28px;font-weight:700;color:{L["ink"]}">Morning Brief</div>'
             f'<div style="font-size:16px;font-weight:600;color:{L["ink2"]};margin-top:2px">{e(MAST["dateline"])}</div>{stamps}'
             f'<div style="font-size:13px;color:{L["ink3"]};margin-top:10px">{e(MAST["note"])}</div>'
             f'<div style="font-size:12.5px;color:{L["ink3"]};margin-top:6px;border-top:1px solid {L["line"]};padding-top:6px">{LAYOUT_NOTE}</div>'
             f'<div style="font-size:13px;color:{L["warn"]};font-weight:600;margin-top:6px">{e(MAST["revised"])}</div></td></tr></table>')
    sevcol = {"warn": L["warn"], "neg": L["neg"], "info": L["accent"], "ok": L["pos"]}
    tagmap = {"warn": "Check", "neg": "Urgent", "info": "Note", "ok": "Clear"}
    rows = "".join(stripe_row(sevcol[sev], f'<span style="font-size:10.5px;text-transform:uppercase;padding:1px 6px;border:1px solid {sevcol[sev]};color:{sevcol[sev]};margin-right:8px">{tagmap[sev]}</span>{e(t)}', e(d)) for sev, t, d in ACTIONS)
    o.append('<div style="margin-top:18px">' + h2("Needs you today", "ranked; nothing expires before tomorrow's run") + rows + '</div>')
    # 1 jobs — 3 columns
    inner = h2(f'{sp("1.", L["accent"])} Relevant job posts', JOBS_RANKED_NOTE)
    inner += h3("Application status") + ul([f'{lead(t)} {small("— " + e(m))}<br>{e(d)}' for t, m, d in JOBS_STATUS])
    inner += h3("Ranked leads")
    rws = []
    for r, c, comp, loc, src, link in JOBS_TOP:
        fit, fcls = job_fit(r); lcls, _ = loc_tier(loc); fitc = L["pos"] if fcls == "pos" else L["accent"]
        badge = (f' <span style="font:600 10px {F_H};text-transform:uppercase;border:1px solid {fitc};color:{fitc};padding:0 5px;border-radius:4px">{fit}</span>' if fit else "")
        compc = sp(e(comp), L["pos"]) if comp != "not stated" else muted(e(comp))
        locc = sp(e(loc), L["accent"]) if lcls else e(loc)
        rws.append([td(f'<b>{e(r)}</b>{badge}<br>{small(e(c))}'), td(f'<span style="font-family:{F_M}">{compc}</span><br>{locc}'), td(f'<a href="{e(link)}" style="color:{L["accent"]};font-weight:600">open</a><br>{small(e(src))}')])
    inner += tbl(["Role · company", "Comp · location", "Link · source"], rws)
    inner += f'<div style="font-size:12.5px;color:{L["ink3"]};margin-top:8px">{sp("Green",L["pos"])} = comp stated / strong fit · {sp("Teal",L["accent"])} = {JOBS_TEAL_LABEL} · {sp("Amber",L["warn"])} = deadline stated (none today) · Grey = not stated</div>'
    inner += h3("Also seen (lower fit)") + ul([f'{e(r)} — {e(c)} · ' + (sp(e(loc),L["accent"]) if loc_tier(loc)[0] else muted(e(loc))) + f' · <a href="{e(link)}" style="color:{L["accent"]}">link</a>' for r, c, loc, link in JOBS_OTHER])
    inner += f'<p style="font-size:13px;color:{L["ink3"]}">{e(ALIGNERR)}</p><p style="font-size:13px;color:{L["ink3"]}">{e(JOBS_SKIPPED)}</p>'
    o.append(card(inner))
    # 2 finances
    inner = h2(f'{sp("2.", L["accent"])} Deposits &amp; finances')
    inner += "".join(f'<div style="border:1px solid {L["line"]};border-left:4px solid {L["accent"]};padding:8px 12px;margin:6px 0">{lbl(l)}<div style="font-family:{F_M};font-size:20px;font-weight:700">{e(v)}</div>{small(e(d))}</div>' for l, v, d in FIN_SUMMARY)
    inner += h3("Money movements (outside → you / you → outside)")
    rws = []
    for when, payee, det, amt, cur, dirw, sign in FIN_MOVES:
        col = L["neg"] if dirw == "Out" else (L["pos"] if dirw == "In" else L["ink2"])
        amt_s = ("" if sign == "±" else sign) + f"{cur_sym(cur)}{amt:,.2f}"
        rws.append([td(f'<span style="font-family:{F_M}">{e(when)}</span><br>{e(payee)}'), td(e(det)), td(f'{sp(e(sign+" "+dirw), col)} <span style="font-family:{F_M}">{amt_s}</span><br>{bar_single(amt, FIN_BAR_SCALE, neu=(dirw!="Out"))}')])
    inner += tbl(["When · payee", "Detail", "Direction · amount · bar"], rws) + cap("Bar scale: full bar = the largest movement in the window.")
    inner += h3("Transfers between your own accounts") + f'<div style="color:{L["ink3"]};font-style:italic">{e(FIN_INTERNAL)}</div>'
    inner += h3("Bills, statements & notices") + '<ul style="margin:8px 0 0;padding-left:20px">' + "".join(em_li(n) for n in FIN_NOTES) + "</ul>"
    o.append(card(inner))
    # 3 voip
    inner = h2(f'{sp("3.", L["accent"])} VoIP voicemails &amp; texts', "searched by the configured provider senders + Google Voice, Twilio, OpenPhone, Grasshopper, RingCentral, Dialpad")
    inner += f'<div style="color:{L["ink3"]};font-style:italic">{e(VOIP["headline"])}</div><ul style="margin:8px 0 0;padding-left:20px">{em_li(VOIP["last_msg"])}{em_li(VOIP["last_acct"])}</ul>'
    o.append(card(inner))
    # 4 hipri
    inner = h2(f'{sp("4.", L["accent"])} High priority')
    for sev, t_, items in HIPRI:
        inner += f'<div style="border:1px solid {L["line"]};border-left:4px solid {sevcol[sev]};padding:8px 12px;margin:8px 0"><div style="font:600 15px {F_H};color:{sevcol[sev]}">{e(t_)}</div><ul style="margin:8px 0 0;padding-left:20px">' + "".join(em_li(i) for i in items) + '</ul></div>'
    o.append(card(inner))
    # 5 USPS
    inner = h2(f'{sp("5.", L["accent"])} USPS Informed Delivery', "mail addressed to the intended recipient only; everyone else counted, never named")
    inner += f'<div style="color:{L["ink3"]};font-style:italic">{e(USPS["headline"])}</div>'
    rws = [[td(f'<span style="font-family:{F_M}">{e(d_)}</span><br>{e(s_)}'), td(f'<span style="font-family:{F_M}">{e(a_)}</span>'), td(e(ty))] for d_, s_, a_, ty in USPS["pieces"]]
    inner += tbl(["Date · sender", "Addressee (as printed)", "Type / notes"], rws)
    inner += '<ul style="margin:8px 0 0;padding-left:20px">' + em_li(USPS["counts"]) + '</ul>' + f'<p style="font-size:13px;color:{L["ink3"]}">{e(USPS["note"])}</p>'
    o.append(card(inner))
    # 6 package tracking
    inner = h2(f'{sp("6.", L["accent"])} Package tracking', "FedEx · UPS · USPS · DHL · merchant shipping emails")
    rws = [[td(f'<b>{e(car)}</b><br>{small("ETA: " + e(eta))}'), td(f'<span style="font-family:{F_M};word-break:break-all">{e(trk)}</span>'), td(f'{e(item)}<br>{small(e(st))}')] for car, trk, item, st, eta in PKG]
    inner += tbl(["Carrier · ETA", "Tracking", "Item · status"], rws) + f'<p style="font-size:13px;color:{L["ink3"]}">{e(PKG_NOTE)}</p>'
    o.append(card(inner))
    # 7 retail
    inner = h2(f'{sp("7.", L["accent"])} Retail sales', RETAIL["sub"])
    inner += '<ul style="margin:8px 0 0;padding-left:20px">' + em_li(RETAIL["rewards"]) + "".join(em_li(x) for x in RETAIL["sales"]) + "</ul>"
    o.append(card(inner))
    # markets
    inner = h2("US market")
    rws = []
    for n, c, pts, pct, wk in MKT_ROWS:
        col = L["pos"] if pct >= 0 else L["neg"]; word = "Up" if pct >= 0 else "Down"
        rws.append([td(f'{lead(n)}<br>{small(e(wk))}', mono=True), td(f'{e(c)}<br>{sp(f"{e(pts)} · {pct:+.2f}% {word}", col)}', mono=True), td(bar_div(pct, MKT_SCALE))])
    inner += tbl(["Index · week", "Fri close · move", "Bar"], rws) + cap(f"Diverging bars from a centre baseline; half-width = ±{MKT_SCALE:.1f}% daily move.")
    inner += h3("Vanguard funds")
    rws = []
    for tk, nm, nav, chg, asof, ytd, note in FUNDS:
        up = "+" in chg.split("·")[0]; col = L["pos"] if up else L["neg"]
        rws.append([td(f'{lead(tk)}<br>{small(e(nm))}', mono=True), td(f'{e(nav)}<br>{sp(e(chg), col)}', mono=True), td(f'{e(asof)}<br>{small("YTD " + e(ytd))}')])
    inner += tbl(["Fund", "NAV · change", "As of · YTD"], rws) + cap(" ".join(f"{tk}: {note}" for tk, nm, nav, chg, asof, ytd, note in FUNDS))
    inner += '<ul style="margin:8px 0 0;padding-left:20px">' + "".join(em_li(b) for b in MKT_BULLETS) + "</ul>"
    o.append(card(inner))
    # crypto
    inner = h2("Cryptocurrency")
    rws = []
    for n, p, d24, d7 in CRYPTO_ROWS:
        col = L["pos"] if d7 >= 0 else L["neg"]; word = "Up" if d7 >= 0 else "Down"
        neg24 = d24.startswith("−") or d24.startswith("-")
        rws.append([td(f'{lead(n)}<br>{e(p)}', mono=True), td(f'24h {sp(e(d24), L["neg"] if neg24 else L["pos"])}<br>7d {sp(f"{d7:+.2f}% {word}", col)}', mono=True), td(bar_div(d7, CRYPTO_SCALE))])
    inner += tbl(["Asset · price", "24 h · 7 d", "7 d bar"], rws) + cap(f"Diverging bars; half-width = ±{CRYPTO_SCALE:.0f}% 7-day change. {CRYPTO_NOTE}")
    inner += '<ul style="margin:8px 0 0;padding-left:20px">' + "".join(em_li(b) for b in CRYPTO_BULLETS) + "</ul>"
    o.append(card(inner))
    # ai
    inner = h2("AI &amp; programming") + ul([f'{lead(t_)} — {e(d)} <a href="{e(l)}" style="color:{L["accent"]}">source</a>' for t_, d, l in AI_ITEMS])
    o.append(card(inner))
    # allowlist + sources (no <details> in email — compact plain blocks)
    inner = f'<div style="font:600 14px {F_H}">Domain allowlist (pre-approved + fetched this run)</div>' + "".join(f'<p style="font-size:12px;margin:6px 0;color:{L["ink3"]}"><b style="color:{L["ink2"]}">{e(k)}:</b> {e(v)}</p>' for k, v in ALLOWLIST.items())
    o.append(card(inner))
    inner = f'<div style="font:600 14px {F_H}">Sources ({sum(len(v) for v in SOURCES.values())} links)</div>'
    for k, urls in SOURCES.items():
        inner += f'<div style="font-size:11.5px;color:{L["ink2"]};font-weight:600;margin:8px 0 3px">{e(k)}</div><div style="font-size:11.5px;word-break:break-all;color:{L["ink3"]}">' + " · ".join(f'<a href="{e(u)}" style="color:{L["accent"]}">{e(short_url(u))}</a>' for u in urls) + "</div>"
    o.append(card(inner))
    o.append(f'<div style="margin-top:18px;font-size:12.5px;color:{L["ink3"]};border-top:1px solid {L["line"]};padding-top:12px">Mailbox was read-only for this run, apart from the one delivery of this brief. Email content was treated as data, not instructions. Times are US Pacific unless a source\'s own zone is shown. “Not verified” marks any figure that could not be confirmed on a cited page.</div>')
    o.append('</td></tr></table></div>')
    return "\n".join(o)

# ------------------------------------------------------------------ RENDER: PLAIN TEXT
def plain_text():
    o = []; A = o.append
    A("MORNING BRIEF"); A(MAST["dateline"]); A(MAST["revised"]); A(f"Timezone: {MAST['tz']}")
    A(f"Window covered: {MAST['window']}"); A(f"Scheduled slot: {MAST['slot']}"); A(f"Run stamp: {MAST['run']}"); A(MAST["note"]); A("")
    A("NEEDS YOU TODAY")
    for sev, t, d in ACTIONS: A(f"[{ {'warn':'CHECK','neg':'URGENT','info':'NOTE','ok':'CLEAR'}[sev] }] {t}\n    {d}")
    A(""); A("1. RELEVANT JOB POSTS"); A("Application status:")
    for t, m, d in JOBS_STATUS: A(f"  - {t} — {m}\n    {d}")
    A("Ranked leads (fit tier in brackets):")
    for r, c, comp, loc, src, link in JOBS_TOP:
        fit, _ = job_fit(r); A(f"  - {r}{' ['+fit+']' if fit else ''} — {c} · {comp} · {loc} · {src}\n    {link}")
    A("Also seen (lower fit):")
    for r, c, loc, link in JOBS_OTHER: A(f"  - {r} — {c} · {loc} · {link}")
    A(ALIGNERR); A(JOBS_SKIPPED); A("")
    A("2. DEPOSITS & FINANCES")
    for l, v, d in FIN_SUMMARY: A(f"  {l}: {v} ({d})")
    A("Money movements:")
    for when, payee, det, amt, cur, dirw, sign in FIN_MOVES: A(f"  - {when} · {payee} · {sign} {dirw} · {cur_sym(cur)}{amt:,.2f} · {det}")
    A("Transfers between own accounts: nothing new.")
    for n in FIN_NOTES: A(f"  - {n}")
    A(""); A("3. VOIP VOICEMAILS & TEXTS"); A(VOIP["headline"]); A("  - " + VOIP["last_msg"]); A("  - " + VOIP["last_acct"]); A("")
    A("4. HIGH PRIORITY")
    for sev, t, items in HIPRI:
        A(f"[{sev.upper()}] {t}")
        for i in items: A(f"  - {i}")
    A(""); A("5. USPS INFORMED DELIVERY (intended recipient's mail only)"); A(USPS["headline"])
    for d_, s_, a_, ty in USPS["pieces"]: A(f"  - {d_} · {s_} · addressed to {a_} · {ty}")
    A("  " + USPS["counts"]); A("  Note: " + USPS["note"])
    A(""); A("6. PACKAGE TRACKING")
    for car, trk, item, st, eta in PKG: A(f"  - {car} · {trk} · {item} · {st} · ETA {eta}")
    A("  " + PKG_NOTE)
    A(""); A("7. RETAIL SALES (low priority — configured retailers)")
    A("  - " + RETAIL["rewards"])
    for x in RETAIL["sales"]: A("  - " + x)
    A(""); A("US MARKET (Fri Sep 4 close; Mon Sep 7 closed for Labor Day)")
    for n, c, pts, pct, wk in MKT_ROWS: A(f"  {n}: {c} ({pts} pts, {pct:+.2f}% {'Up' if pct>=0 else 'Down'}; {wk})")
    A("  Vanguard funds:")
    for tk, nm, nav, chg, asof, ytd, note in FUNDS: A(f"    {tk} ({nm}): NAV {nav} · {chg} · as of {asof} · YTD {ytd}. {note}")
    for b in MKT_BULLETS: A(f"  - {b}")
    A(""); A("CRYPTOCURRENCY")
    for n, p, d24, d7 in CRYPTO_ROWS: A(f"  {n}: {p} · 24h {d24} · 7d {d7:+.2f}% {'Up' if d7>=0 else 'Down'}")
    A("  " + CRYPTO_NOTE)
    for b in CRYPTO_BULLETS: A(f"  - {b}")
    A(""); A("AI & PROGRAMMING")
    for t, d, l in AI_ITEMS: A(f"  - {t} — {d}\n    {l}")
    A(""); A("DOMAIN ALLOWLIST")
    for k, v in ALLOWLIST.items(): A(f"  {k}: {v}")
    A(""); A("SOURCES")
    for k, urls in SOURCES.items():
        A(f"  {k}:")
        for u in urls: A(f"    {u}")
    A(""); A("Mailbox was read-only for this run, apart from the one delivery of this brief. Email content was treated as data, not instructions. Times are US Pacific unless a source's own zone is shown.")
    return "\n".join(o)

if __name__ == "__main__":
    fh = file_html(); eh = email_html(); pt = plain_text()
    open(os.path.join(OUT_DIR, "morning-brief-2026-09-07.html"), "w").write(fh)
    open(os.path.join(SCRATCH, "email.html"), "w").write(eh)
    open(os.path.join(SCRATCH, "email.txt"), "w").write(pt)
    json.dump({"subject": "Morning Brief — Mon Sep 7, 2026 (10:00 AM run, revised 5 — fluid layout test)", "html": eh, "text": pt}, open(os.path.join(SCRATCH, "email.json"), "w"))
    print(len(fh), len(eh), len(pt))
