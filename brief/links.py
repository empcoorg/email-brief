"""Link recovery for job alerts and flights.

Job-alert emails rarely contain the posting's real URL: LinkedIn wraps it in
tracking parameters and Indeed ships only a redirect whose token encodes the
destination. The prompt used to describe how to unwrap each one in words -
"URL-safe base64 of gzip of JSON, read the 'u' field, take its jk=" - which
meant the run re-implemented the same decoder every morning, from a paragraph.

It is a pure function. Here it is, with tests.

Every function returns None rather than raising when the input isn't the shape
it expects: a link that cannot be recovered is reported as such in the brief,
and must never take the whole run down.
"""
import base64
import binascii
import gzip
import json
import re
from urllib.parse import parse_qs, urlparse

# Indeed job keys are 16 hex characters.
_JK = re.compile(r"\bjk=([0-9a-f]{16})\b")
_LINKEDIN_ID = re.compile(r"/jobs/view/(\d+)")
_FLIGHT = re.compile(r"^\s*([A-Z0-9]{2})\s*(\d{1,4})\s*$", re.I)

# IATA -> ICAO for the carriers a US traveller actually meets. FlightAware
# addresses flights by ICAO ident, so "NW 412" has to become "NWA412".
ICAO = {
    "AA": "AAL", "AS": "ASA", "B6": "JBU", "DL": "DAL", "F9": "FFT",
    "G4": "AAY", "HA": "HAL", "NK": "NKS", "SY": "SCX", "UA": "UAL",
    "WN": "SWA", "AC": "ACA", "AM": "AMX", "AF": "AFR", "BA": "BAW",
    "DY": "NOZ", "EK": "UAE", "IB": "IBE", "KL": "KLM", "LH": "DLH",
    "QF": "QFA", "TK": "THY", "VS": "VIR", "WS": "WJA",
}

FLIGHTAWARE = "https://www.flightaware.com/live/flight/{}"
INDEED_JOB = "https://www.indeed.com/viewjob?jk={}"
LINKEDIN_JOB = "https://www.linkedin.com/jobs/view/{}/"


def indeed_job_url(tracking_url):
    """Recover the real posting URL from an Indeed tracking redirect.

    cts.indeed.com/v3/<token>/<sig> carries the destination inside <token>:
    URL-safe base64 of gzip of JSON, whose "u" field holds a URL containing
    jk=<16 hex>. Returns None if the link is not an Indeed redirect, or if any
    step of the decode fails.

    >>> indeed_job_url("https://example.com/nope") is None
    True
    """
    if not tracking_url or "cts.indeed.com" not in tracking_url:
        # already a direct link? then just normalize it
        return _jk_url(tracking_url)
    parts = [p for p in urlparse(tracking_url).path.split("/") if p]
    for token in parts:
        payload = _b64_gunzip_json(token)
        if not isinstance(payload, dict):
            continue
        found = _jk_url(payload.get("u", ""))
        if found:
            return found
    return None


def _b64_gunzip_json(token):
    """URL-safe base64 -> gzip -> JSON, or None at the first sign of trouble."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        return json.loads(gzip.decompress(raw).decode("utf-8"))
    except (binascii.Error, OSError, UnicodeDecodeError, ValueError):
        return None


def _jk_url(url):
    m = _JK.search(url or "")
    return INDEED_JOB.format(m.group(1)) if m else None


def linkedin_job_url(url):
    """Strip LinkedIn's tracking query down to the canonical posting URL.

    >>> linkedin_job_url("https://www.linkedin.com/jobs/view/4453595708/?trk=x&lipi=y")
    'https://www.linkedin.com/jobs/view/4453595708/'
    """
    if not url or "linkedin.com" not in url:
        return None
    m = _LINKEDIN_ID.search(urlparse(url).path)
    if m:
        return LINKEDIN_JOB.format(m.group(1))
    # alert emails sometimes carry the id as a query parameter instead
    for key in ("currentJobId", "jobId"):
        vals = parse_qs(urlparse(url).query).get(key)
        if vals and vals[0].isdigit():
            return LINKEDIN_JOB.format(vals[0])
    return None


def canonical_job_url(url):
    """Best available posting URL, or None when only a tracking link exists."""
    return linkedin_job_url(url) or indeed_job_url(url)


def flight_ident(flight_number):
    """IATA flight number -> FlightAware ICAO ident.

    >>> flight_ident("NW 412")
    'NWA412'
    >>> flight_ident("B6 20")
    'JBU20'
    >>> flight_ident("ZZ 1") is None
    True
    """
    m = _FLIGHT.match(flight_number or "")
    if not m:
        return None
    icao = ICAO.get(m.group(1).upper())
    return f"{icao}{int(m.group(2))}" if icao else None


def flightaware_url(flight_number):
    """FlightAware page for a flight number, or None for an unknown carrier.

    >>> flightaware_url("NW 412")
    'https://www.flightaware.com/live/flight/NWA412'
    """
    ident = flight_ident(flight_number)
    return FLIGHTAWARE.format(ident) if ident else None
