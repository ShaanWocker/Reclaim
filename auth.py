"""
Handles Google OAuth for Reclaim -- covers both Gmail and Drive under
one consent screen, one token.

First run opens a browser window for you to sign in and consent.
After that, credentials are cached in token.json and refreshed
automatically -- you won't be prompted again unless you revoke access
or delete token.json.

Two ways to supply your OAuth client's own ID and secret (never
shared between users -- everyone who clones this creates their own):

1. .env file (recommended for anyone cloning this repo): copy
   .env.example to .env and fill in GOOGLE_CLIENT_ID and
   GOOGLE_CLIENT_SECRET from your own Google Cloud Console project.
2. credentials.json: the file Google Cloud Console lets you download
   directly for a Desktop app OAuth client. Still supported for
   backward compatibility -- if present, and no .env is set, it's
   used instead.

Whenever the SCOPES list below changes (as it did when Drive support
was added, and again when Empty Drive Trash required widening from
drive.metadata to the full drive scope), your existing token.json
won't cover the new scope -- delete it and run any script once to
re-consent. You'll approve the fuller set of permissions in one go,
not lose access to anything you'd already granted.
"""

import os

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()  # no-op if there's no .env file -- doesn't raise

# gmail.readonly powers the dashboard. gmail.modify is what lets the
# "trash selected sender" button work. drive covers listing, trashing,
# and emptying Drive's Trash.
#
# This used to be the narrower drive.metadata scope (metadata-only,
# never touches file content) until Empty Drive Trash was added --
# Google's files.emptyTrash endpoint specifically requires the full
# drive scope, with no narrower option, even though every other Drive
# action this app performs works fine under drive.metadata. Widening
# to drive for that one feature means the app can now technically
# read/write file content too, even though nothing here does.
#
# None of these scopes grant permanent, un-trashable deletion by
# default -- everything goes through Trash first, except the
# deliberate Empty Drive Trash action itself.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
]

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


def _build_flow():
    """Build the OAuth flow from .env vars if present, else credentials.json."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if client_id and client_secret:
        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        return InstalledAppFlow.from_client_config(client_config, SCOPES)

    if os.path.exists(CREDENTIALS_FILE):
        return InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)

    raise FileNotFoundError(
        "No OAuth credentials found. Either copy .env.example to .env and "
        "fill in GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET, or download "
        f"{CREDENTIALS_FILE} from Google Cloud Console and place it in this "
        "folder. See README.md for the full setup steps."
    )


def get_credentials():
    """Return valid user credentials, running the OAuth flow if needed."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = _build_flow()
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds
