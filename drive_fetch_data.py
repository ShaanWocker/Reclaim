"""
Lists every file in your Google Drive that actually counts against
your storage quota, and saves it to drive_files.csv for the dashboard.

Two things are filtered out automatically at the query level, because
neither takes up any of your quota:
  - Files owned by someone else (shared with you, not by you) -- those
    count against the OWNER's quota, not yours.
And one more filtered client-side:
  - Native Google Docs/Sheets/Slides/Forms/Drawings/folders/shortcuts
    -- these have no byte size of their own; Google doesn't charge for
    them regardless of how much content is "inside" them. The API
    simply omits the size field entirely for these, which is the
    signal used here rather than maintaining a list of mimeTypes.

Also fetches your real account storage quota (limit, usage, Drive's
own share of it) via the same Drive API call Google's own storage
page uses, and saves it to quota.json.

Drive's rate limits (12,000+ queries/minute/user) are far more
generous than Gmail's, and files.list returns up to 1000 files per
call, so this finishes in seconds to low minutes even for large
Drives -- no elaborate pacing needed the way Gmail required.

Run: python drive_fetch_data.py
"""

import csv
import json
import time

from googleapiclient.errors import HttpError

from drive_actions import get_service, get_storage_quota

OUTPUT_FILE = "drive_files.csv"
QUOTA_FILE = "quota.json"
CSV_FIELDS = ["id", "name", "mime_type", "size_bytes", "modified_time"]

FIELDS = "nextPageToken, files(id, name, mimeType, size, modifiedTime)"
QUERY = "trashed = false and 'me' in owners"
MAX_RETRIES = 5


def list_owned_files(service):
    """Page through every file that counts against your quota."""
    files = []
    page_token = None

    while True:
        for attempt in range(MAX_RETRIES):
            try:
                response = (
                    service.files()
                    .list(q=QUERY, fields=FIELDS, pageSize=1000, pageToken=page_token)
                    .execute()
                )
                break
            except HttpError as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                status = e.resp.status if getattr(e, "resp", None) else "?"
                wait = 2**attempt
                print(f"  transient error ({status}), retrying in {wait}s...")
                time.sleep(wait)

        for f in response.get("files", []):
            if "size" in f:  # excludes native Google formats and folders
                files.append(f)

        print(f"  found {len(files)} files so far...", end="\r")
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    print()
    return files


def main():
    service = get_service()

    print("Listing your Drive files (owned by you, real storage cost only)...")
    files = list_owned_files(service)
    print(f"Found {len(files)} files that count against your quota.")

    rows = [
        {
            "id": f["id"],
            "name": f["name"],
            "mime_type": f["mimeType"],
            "size_bytes": int(f["size"]),
            "modified_time": f.get("modifiedTime", ""),
        }
        for f in files
    ]
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} files to {OUTPUT_FILE}")

    print("Fetching your real account storage quota...")
    quota = get_storage_quota(service=service)
    with open(QUOTA_FILE, "w") as out:
        json.dump(quota, out)
    if quota["limit"]:
        pct = quota["usage"] / quota["limit"] * 100
        print(f"Saved quota.json -- {pct:.0f}% of your account storage used.")
    else:
        print("Saved quota.json -- unlimited storage plan, no percentage to show.")


if __name__ == "__main__":
    main()
