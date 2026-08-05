"""
Bulk actions on Gmail messages. Currently: move to Trash.

Trashing (not permanent delete) is intentional -- it's reversible for
30 days and only requires the gmail.modify scope, not full mailbox
access.
"""

from googleapiclient.discovery import build

from auth import get_credentials

BATCH_SIZE = 1000  # batchModify's own limit per call


def get_service():
    return build("gmail", "v1", credentials=get_credentials())


def trash_messages(message_ids, service=None):
    """Move the given message IDs to Trash, in batches."""
    service = service or get_service()
    trashed = 0
    for i in range(0, len(message_ids), BATCH_SIZE):
        chunk = message_ids[i : i + BATCH_SIZE]
        service.users().messages().batchModify(
            userId="me",
            body={
                "ids": chunk,
                "addLabelIds": ["TRASH"],
                "removeLabelIds": ["INBOX"],
            },
        ).execute()
        trashed += len(chunk)
    return trashed
