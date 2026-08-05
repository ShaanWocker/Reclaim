"""
Actions on Drive files: trashing, and reading your real account quota.

Trashing (not permanent delete) is intentional, same philosophy as
the Gmail side -- reversible for 30 days rather than gone immediately.
The drive.metadata scope covers both listing and trashing without
ever granting access to file content.
"""

from googleapiclient.discovery import build

from auth import get_credentials


def get_service():
    return build("drive", "v3", credentials=get_credentials())


def trash_files(file_ids, service=None):
    """Move the given file IDs to Trash, one call per file.

    Drive's API has no batch-trash endpoint (unlike Gmail's
    batchModify), so this is a loop -- fine at the volumes a personal
    Drive cleanup involves, and Drive's rate limits are generous
    (12,000+ queries/minute/user) compared to Gmail's.
    """
    trashed = 0
    service = service or get_service()
    for file_id in file_ids:
        service.files().update(fileId=file_id, body={"trashed": True}).execute()
        trashed += 1
    return trashed


def empty_trash(service=None):
    """
    Permanently delete everything already in Drive's Trash. This is the
    one action in the whole app that isn't a reversible "move to
    Trash" -- but by definition, everything it touches was already
    sitting in Trash waiting to be purged; this just does it now
    instead of waiting out the 30 days, so the space is actually freed
    immediately.
    """
    service = service or get_service()
    service.files().emptyTrash().execute()


def get_storage_quota(service=None):
    """
    Return your real Google account storage quota: limit, total usage
    across all services, and Drive's own share of that. There's no
    separate usageInGmail field in the current API, so Gmail+Photos
    combined is only inferable as usage - usageInDrive, not cleanly
    split further.
    """
    service = service or get_service()
    about = service.about().get(fields="storageQuota").execute()
    quota = about.get("storageQuota", {})
    return {
        "limit": int(quota["limit"]) if "limit" in quota else None,
        "usage": int(quota.get("usage", 0)),
        "usage_in_drive": int(quota.get("usageInDrive", 0)),
        "usage_in_drive_trash": int(quota.get("usageInDriveTrash", 0)),
    }
