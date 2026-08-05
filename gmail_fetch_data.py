"""
Pulls message metadata (sender, size, date, unsubscribe info) for
every email in your Gmail account and saves it to messages.csv for
the dashboard to use.

Uses format="metadata" so message bodies are never downloaded -- only
headers and Gmail's own size estimate. Also captures the
List-Unsubscribe / List-Unsubscribe-Post headers (RFC 2369 / RFC
8058) that power the Subscriptions tab -- this costs nothing extra:
same API call, just more header names in the same request.

Gmail enforces a 6,000 quota-unit/minute-per-user limit, and each
messages.get call costs 20 units -- so this account can sustain about
300 messages/minute no matter how batching is tuned. Requests are
paced to that budget, and anything that still gets rate-limited is
automatically retried with exponential backoff (Google's own
recommended approach for time-based quota errors) rather than
dropped. On a ~14,000 message mailbox, expect this to take roughly
45-50 minutes -- that's Google's limit, not a bug.

Resumable: on each run, messages already in messages.csv are kept
as-is (and dropped if they're no longer in your mailbox -- e.g. you
deleted them elsewhere), and only genuinely new messages get fetched.
A "top-up" run after the first full scan is usually quick.

If messages.csv was created by an older version of this script (a
different set of columns), it's treated as fully stale and everything
gets re-fetched once to backfill the new fields -- a one-time cost
when upgrading, not something that happens on every run.

Run: python fetch_data.py
"""

import csv
import os
import random
import time

from googleapiclient.discovery import build

from auth import get_credentials

BATCH_SIZE = 100  # 100 x 20 units = 2,000 units per batch
# Per-user budget is 6,000 units/min -> 3 batches/min max -> one every 20s.
# A little padding keeps us safely under the limit.
SLEEP_BETWEEN_BATCHES = 21
MAX_RETRY_PASSES = 12
OUTPUT_FILE = "messages.csv"

CSV_FIELDS = [
    "id",
    "from",
    "date",
    "size_bytes",
    "list_unsubscribe",
    "list_unsubscribe_post",
]

# 403/429 = rate limit (expected, self-inflicted -- our own pacing).
# 500/502/503/504 = transient Gmail backend errors -- not our fault,
# but just as safe to retry after a short wait.
RETRYABLE_STATUSES = {403, 429, 500, 502, 503, 504}


def list_all_message_ids(service):
    """Page through every message ID in the mailbox."""
    ids = []
    request = service.users().messages().list(userId="me", maxResults=500)
    while request is not None:
        response = request.execute()
        ids.extend(m["id"] for m in response.get("messages", []))
        print(f"  found {len(ids)} messages so far...", end="\r")
        request = service.users().messages().list_next(request, response)
    print()
    return ids


def fetch_metadata_batch(service, message_ids, results):
    """
    Fetch metadata for a batch of message IDs in one HTTP round trip.
    Returns the IDs that got rate-limited so the caller can retry them
    -- nothing is silently dropped.
    """
    retry_ids = []

    def callback(request_id, response, exception):
        if exception is not None:
            status = getattr(getattr(exception, "resp", None), "status", None)
            if status in RETRYABLE_STATUSES:
                retry_ids.append(request_id)
            else:
                print(f"  skipped {request_id} (status={status}, non-retryable): {exception}")
            return
        headers = {
            h["name"]: h["value"]
            for h in response.get("payload", {}).get("headers", [])
        }
        results.append(
            {
                "id": response["id"],
                "from": headers.get("From", "(unknown)"),
                "date": headers.get("Date", ""),
                "size_bytes": response.get("sizeEstimate", 0),
                "list_unsubscribe": headers.get("List-Unsubscribe", ""),
                "list_unsubscribe_post": headers.get("List-Unsubscribe-Post", ""),
            }
        )

    batch = service.new_batch_http_request(callback=callback)
    for msg_id in message_ids:
        batch.add(
            service.users().messages().get(
                userId="me",
                id=msg_id,
                format="metadata",
                metadataHeaders=["From", "Date", "List-Unsubscribe", "List-Unsubscribe-Post"],
            ),
            request_id=msg_id,
        )
    batch.execute()
    return retry_ids


def fetch_all_metadata(service, message_ids):
    """Fetch metadata for every ID, retrying rate-limited ones with
    exponential backoff until they succeed or we give up."""
    results = []
    pending = list(message_ids)
    backoff = 2

    for attempt in range(1, MAX_RETRY_PASSES + 1):
        if not pending:
            break

        retry_ids = []
        total = len(pending)
        for i in range(0, total, BATCH_SIZE):
            chunk = pending[i : i + BATCH_SIZE]
            retry_ids.extend(fetch_metadata_batch(service, chunk, results))
            done = min(i + BATCH_SIZE, total)
            print(
                f"  pass {attempt}: processed {done}/{total} "
                f"({len(results)} saved so far)",
                end="\r",
            )
            time.sleep(SLEEP_BETWEEN_BATCHES)
        print()

        pending = retry_ids
        if pending:
            wait = min(backoff, 60) + random.uniform(0, 1)
            print(
                f"  {len(pending)} messages hit the rate limit -- "
                f"waiting {wait:.0f}s before retrying (pass {attempt})"
            )
            time.sleep(wait)
            backoff *= 2

    if pending:
        print(
            f"  gave up on {len(pending)} messages after {MAX_RETRY_PASSES} "
            "passes. Re-run the script to try again -- it's a full re-fetch, "
            "but this should be rare."
        )

    return results


def _cache_schema_current(path):
    """True if messages.csv already has today's column set."""
    if not os.path.exists(path):
        return True  # nothing to migrate
    with open(path, newline="", encoding="utf-8") as f:
        return csv.DictReader(f).fieldnames == CSV_FIELDS


def load_existing(path):
    """
    Load previously-fetched messages, keyed by message ID. If the file
    predates the current column set, it's treated as fully stale (empty
    dict) so every message gets re-fetched once with the new fields --
    a schema check, not a per-row guess about what's actually missing.
    """
    if not os.path.exists(path) or not _cache_schema_current(path):
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {row["id"]: row for row in csv.DictReader(f)}


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    print("Listing all messages (this walks your full mailbox)...")
    all_ids = list_all_message_ids(service)
    all_ids_set = set(all_ids)
    print(f"Total messages in mailbox: {len(all_ids)}")

    if os.path.exists(OUTPUT_FILE) and not _cache_schema_current(OUTPUT_FILE):
        print(
            "  messages.csv is from an older version of this tool -- doing a "
            "one-time full refetch to pick up newsletter-detection fields\n"
        )

    cached = load_existing(OUTPUT_FILE)
    kept = {mid: row for mid, row in cached.items() if mid in all_ids_set}
    dropped = len(cached) - len(kept)
    if dropped:
        print(f"  dropping {dropped} cached messages no longer in your mailbox")

    missing_ids = [mid for mid in all_ids if mid not in kept]

    if not missing_ids:
        print("Nothing new -- messages.csv is already up to date.")
        return

    print(
        f"{len(kept)} messages already cached. Fetching {len(missing_ids)} "
        f"new ones (~{len(missing_ids) / 300:.0f} min at Gmail's rate limit).\n"
    )

    new_results = fetch_all_metadata(service, missing_ids)

    all_results = list(kept.values()) + new_results
    write_csv(OUTPUT_FILE, all_results)

    print(
        f"Saved {len(all_results)} messages to {OUTPUT_FILE} "
        f"({len(new_results)} new, {len(kept)} carried over from cache)"
    )


if __name__ == "__main__":
    main()
