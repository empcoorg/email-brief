"""email-brief renderer.

The Routine gathers the facts and writes one JSON payload; this package turns
that payload into the three outputs. No network, no API keys, stdlib only.

    python3 -m brief render payload.json --out-dir /mnt/user-data/outputs
"""
from .model import PayloadError, load, validate
from .render import email_html, file_html, plain_text, render_all

__all__ = ["load", "validate", "PayloadError", "render_all",
           "file_html", "email_html", "plain_text"]
