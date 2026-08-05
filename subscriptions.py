"""
Detects newsletter/subscription senders from the List-Unsubscribe and
List-Unsubscribe-Post headers (RFC 2369 / RFC 8058) already captured
by fetch_data.py, and handles the actual unsubscribe action.

No scraping, no guessing: these headers are what Gmail's own
"Unsubscribe" button reads, and since Feb 2024 Google and Yahoo
require them from any sender pushing 5,000+ messages/day -- so real
newsletters and marketing mail already carry this data.

Three possible methods, in order of how confidently we can act on them:
  - "one_click": an HTTPS URL plus List-Unsubscribe-Post. Safe to fire
    automatically -- this is exactly what Gmail's own button does,
    and Gmail only shows that button when the sender's DKIM signature
    verifiably covers both headers, which rules out spoofing.
  - "link": an HTTPS URL with no one-click support. Surfaced for you
    to open and review yourself -- no compliance guarantee behind it.
  - "mailto": only a mailto address. Never sent automatically -- shown
    so you can send it yourself if you want to.
  - "none": no List-Unsubscribe header on any of that sender's mail.
"""

import re

import pandas as pd
import requests

_URI_PATTERN = re.compile(r"<([^>]+)>")
USER_AGENT = "gmail-storage-manager/1.0 (one-click unsubscribe)"


def parse_list_unsubscribe(raw_value):
    """
    Parse a List-Unsubscribe header value into its component URIs.
    Returns {"https": url_or_None, "mailto": address_or_None}.
    """
    result = {"https": None, "mailto": None}
    if not raw_value or not isinstance(raw_value, str):
        return result

    for uri in _URI_PATTERN.findall(raw_value):
        uri = uri.strip()
        lower = uri.lower()
        if lower.startswith("mailto:"):
            result["mailto"] = uri[len("mailto:"):].split("?")[0].strip()
        elif lower.startswith("http://") or lower.startswith("https://"):
            result["https"] = uri
    return result


def is_one_click(list_unsubscribe_post_value):
    """True if the sender advertises RFC 8058 one-click unsubscribe."""
    if not list_unsubscribe_post_value or not isinstance(list_unsubscribe_post_value, str):
        return False
    return "list-unsubscribe=one-click" in list_unsubscribe_post_value.strip().lower()


def classify(list_unsubscribe_value, list_unsubscribe_post_value):
    """Classify a sender's unsubscribe method: one_click / link / mailto / none."""
    uris = parse_list_unsubscribe(list_unsubscribe_value)
    if uris["https"] and is_one_click(list_unsubscribe_post_value):
        return "one_click"
    if uris["https"]:
        return "link"
    if uris["mailto"]:
        return "mailto"
    return "none"


def summarize_senders(df):
    """
    Given the messages DataFrame (must include list_unsubscribe and
    list_unsubscribe_post columns), return one row per sender with its
    unsubscribe classification and the relevant URI.

    Returns a DataFrame with columns: from, count, total_mb, method,
    https_url, mailto.
    """
    if "list_unsubscribe" not in df.columns or "list_unsubscribe_post" not in df.columns:
        return pd.DataFrame(columns=["from", "count", "total_mb", "method", "https_url", "mailto"])

    rows = []
    for sender, group in df.groupby("from"):
        lu_series = group["list_unsubscribe"].dropna()
        lup_series = group["list_unsubscribe_post"].dropna()
        lu_val = next((v for v in lu_series if v), "")
        lup_val = next((v for v in lup_series if v), "")

        method = classify(lu_val, lup_val)
        uris = parse_list_unsubscribe(lu_val)

        rows.append(
            {
                "from": sender,
                "count": len(group),
                "total_mb": group["size_mb"].sum(),
                "method": method,
                "https_url": uris["https"],
                "mailto": uris["mailto"],
            }
        )
    return pd.DataFrame(rows)


def unsubscribe_one_click(https_url, timeout=15):
    """
    Fire the RFC 8058 one-click unsubscribe POST. A 2xx response means
    the sender's server accepted the request -- per spec, no further
    confirmation is expected. Returns (success: bool, detail: str).
    """
    try:
        resp = requests.post(
            https_url,
            data={"List-Unsubscribe": "One-Click"},
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
        if 200 <= resp.status_code < 300:
            return True, f"HTTP {resp.status_code}"
        return False, f"HTTP {resp.status_code}"
    except requests.RequestException as e:
        return False, str(e)
