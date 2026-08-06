"""
A guided, click-through setup wizard for the one part of Reclaim's
setup that can't be automated: creating your own Google Cloud project
and OAuth credentials (see README for why Google doesn't allow this
step to be scripted).

Opens the right console page at each step, tells you exactly what to
click in plain language, and writes your credentials straight to
.env when you're done -- no manual file editing.

Uses only Python's standard library (tkinter, webbrowser, os, re) --
nothing to pip install, so this is safe to run before
`pip install -r requirements.txt`. In fact, run this first.

Run: python setup_wizard.py
"""

import os
import re
import tkinter as tk
import webbrowser
from tkinter import messagebox

ACCENT = "#0F6B5C"
ACCENT_HOVER = "#0B5347"
BG = "#F6F7F4"
SURFACE = "#FFFFFF"
BORDER = "#D8DBD6"
TEXT = "#1C201D"
TEXT_MUTED = "#667066"
FONT = "Segoe UI"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
]

# Write next to this script, not the current working directory --
# robust to being double-clicked rather than run from a terminal in
# the right folder.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, ".env")


def write_env_file(client_id, client_secret, path=ENV_PATH):
    """Write the client ID/secret to a .env file in the exact format
    auth.py's load_dotenv() expects."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"GOOGLE_CLIENT_ID={client_id.strip()}\n")
        f.write(f"GOOGLE_CLIENT_SECRET={client_secret.strip()}\n")


def looks_like_client_id(value):
    """Loose sanity check, not a strict validator -- Google's exact
    format could shift, so this only catches obvious paste mistakes
    (pasting the secret into this field, pasting a URL, leaving it
    blank)."""
    value = value.strip()
    return bool(value) and "apps.googleusercontent.com" in value


def looks_like_client_secret(value):
    """Same idea: loose, not strict. Client secrets have historically
    been GOCSPX-prefixed but that's not guaranteed forever, so this
    just checks for "something plausible was pasted", not an exact
    pattern."""
    value = value.strip()
    return bool(value) and not re.search(r"\s", value) and len(value) >= 10


class Wizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Reclaim Setup Wizard")
        self.geometry("680x600")
        self.minsize(680, 600)
        self.configure(bg=BG)

        self.steps = [
            self._step_welcome,
            self._step_create_project,
            self._step_enable_apis,
            self._step_consent_screen,
            self._step_create_credentials,
            self._step_enter_credentials,
            self._step_done,
        ]
        self.step_index = 0
        self.client_id_var = tk.StringVar()
        self.client_secret_var = tk.StringVar()

        self._build_chrome()
        self._render_step()

    # ---------- chrome (header, content area, nav bar) ----------

    def _build_chrome(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=36, pady=(28, 0))
        tk.Label(
            header, text="\U0001F4E6 Reclaim Setup", bg=BG, fg=TEXT,
            font=(FONT, 20, "bold"),
        ).pack(anchor="w")
        self.progress_label = tk.Label(
            header, text="", bg=BG, fg=TEXT_MUTED, font=(FONT, 10),
        )
        self.progress_label.pack(anchor="w", pady=(2, 0))

        divider = tk.Frame(self, bg=BORDER, height=1)
        divider.pack(fill="x", padx=36, pady=(16, 0))

        self.content = tk.Frame(self, bg=BG)
        self.content.pack(fill="both", expand=True, padx=36, pady=20)

        nav = tk.Frame(self, bg=BG)
        nav.pack(fill="x", padx=36, pady=(0, 28))
        self.back_btn = tk.Button(
            nav, text="Back", command=self._go_back, bg=SURFACE, fg=TEXT,
            font=(FONT, 10), relief="solid", borderwidth=1, padx=16, pady=6,
            cursor="hand2",
        )
        self.back_btn.pack(side="left")
        self.next_btn = tk.Button(
            nav, text="Next", command=self._go_next, bg=ACCENT, fg="white",
            font=(FONT, 10, "bold"), relief="flat", padx=20, pady=6,
            activebackground=ACCENT_HOVER, activeforeground="white",
            cursor="hand2",
        )
        self.next_btn.pack(side="right")

    def _render_step(self):
        for widget in self.content.winfo_children():
            widget.destroy()
        self.progress_label.config(
            text=f"Step {self.step_index + 1} of {len(self.steps)}"
        )
        self.back_btn.config(state="normal" if self.step_index > 0 else "disabled")
        is_last = self.step_index == len(self.steps) - 1
        self.next_btn.config(text="Finish" if is_last else "Next")
        self.steps[self.step_index]()

    def _go_back(self):
        if self.step_index > 0:
            self.step_index -= 1
            self._render_step()

    def _go_next(self):
        # Credentials step validates before advancing; every other
        # step just moves on.
        if self.step_index == len(self.steps) - 2:  # enter-credentials step
            if not self._save_credentials():
                return
        if self.step_index == len(self.steps) - 1:
            self.destroy()
            return
        self.step_index += 1
        self._render_step()

    # ---------- small widget helpers ----------

    def _title(self, text):
        tk.Label(
            self.content, text=text, bg=BG, fg=TEXT, font=(FONT, 16, "bold"),
            anchor="w", justify="left",
        ).pack(anchor="w", pady=(0, 14))

    def _body(self, text):
        tk.Label(
            self.content, text=text, bg=BG, fg=TEXT, font=(FONT, 11),
            anchor="w", justify="left", wraplength=580,
        ).pack(anchor="w", pady=(0, 10))

    def _open_button(self, label, url):
        tk.Button(
            self.content, text=label, command=lambda: webbrowser.open(url),
            bg=ACCENT, fg="white", font=(FONT, 10, "bold"), relief="flat",
            padx=16, pady=8, activebackground=ACCENT_HOVER,
            activeforeground="white", cursor="hand2",
        ).pack(anchor="w", pady=(4, 16))

    def _copy_row(self, text):
        row = tk.Frame(self.content, bg=SURFACE, highlightbackground=BORDER,
                        highlightthickness=1)
        row.pack(fill="x", pady=3)
        tk.Label(
            row, text=text, bg=SURFACE, fg=TEXT, font=("Consolas", 9),
            anchor="w",
        ).pack(side="left", padx=10, pady=6, fill="x", expand=True)

        def copy():
            self.clipboard_clear()
            self.clipboard_append(text)

        tk.Button(
            row, text="Copy", command=copy, bg=SURFACE, fg=ACCENT,
            font=(FONT, 9, "bold"), relief="solid", borderwidth=1,
            cursor="hand2", padx=8,
        ).pack(side="right", padx=8, pady=4)

    # ---------- steps ----------

    def _step_welcome(self):
        self._title("Welcome")
        self._body(
            "This walks you through the one part of Reclaim's setup that "
            "can't be automated -- creating your own private Google Cloud "
            "project and OAuth credentials. Google requires a human to do "
            "this through their console; it's a deliberate anti-abuse "
            "measure, not something this wizard failed to script around."
        )
        self._body(
            "Takes about 5 minutes. You'll need to be signed into the "
            "Google account you want Reclaim to manage. Each step below "
            "opens the right page in your browser and tells you exactly "
            "what to click."
        )
        self._body(
            "Nothing here is shared with anyone -- this creates a project "
            "that belongs only to you, under your own Google account."
        )

    def _step_create_project(self):
        self._title("1. Create a Google Cloud project")
        self._body(
            "Click below to open the project creation page. Give it any "
            "name you like (e.g. \"Reclaim\") and click Create. It takes "
            "about 30 seconds -- wait for the notification that it's ready "
            "before moving on."
        )
        self._open_button(
            "Open: Create a Google Cloud project",
            "https://console.cloud.google.com/projectcreate",
        )
        self._body("Already have a project you'd rather use? That's fine too -- just make sure it's selected in the console before continuing.")

    def _step_enable_apis(self):
        self._title("2. Enable the Gmail and Drive APIs")
        self._body(
            "Reclaim needs both APIs turned on for your project. Open each "
            "page below and click the blue Enable button."
        )
        self._open_button(
            "Open: Gmail API",
            "https://console.cloud.google.com/apis/library/gmail.googleapis.com",
        )
        self._open_button(
            "Open: Google Drive API",
            "https://console.cloud.google.com/apis/library/drive.googleapis.com",
        )

    def _step_consent_screen(self):
        self._title("3. Configure the OAuth consent screen")
        self._body(
            "Open the consent screen page below. Choose External as the "
            "user type, fill in an app name and your email where asked -- "
            "nothing else matters since you're staying in Testing mode."
        )
        self._open_button(
            "Open: OAuth consent screen",
            "https://console.cloud.google.com/apis/credentials/consent",
        )
        self._body(
            "When it asks for scopes, search for and add each of these "
            "three (click Copy, then paste into the scope search box):"
        )
        for scope in SCOPES:
            self._copy_row(scope)
        self._body(
            "Under Test users, add your own Gmail address. Leave the app "
            "in Testing status -- this is what avoids Google's "
            "verification process entirely."
        )

    def _step_create_credentials(self):
        self._title("4. Create your OAuth Client ID")
        self._body(
            "Open the credentials page, click Create Credentials > OAuth "
            "client ID, and choose Desktop app as the application type."
        )
        self._open_button(
            "Open: Credentials",
            "https://console.cloud.google.com/apis/credentials",
        )
        self._body(
            "Once created, click on the client in the list to reveal its "
            "Client ID and Client secret -- you'll need both on the next "
            "step."
        )

    def _step_enter_credentials(self):
        self._title("5. Enter your credentials")
        self._body("Paste the Client ID and Client secret from the previous step.")

        tk.Label(
            self.content, text="Client ID", bg=BG, fg=TEXT_MUTED,
            font=(FONT, 9, "bold"), anchor="w",
        ).pack(anchor="w", pady=(10, 2))
        tk.Entry(
            self.content, textvariable=self.client_id_var, font=(FONT, 10),
            relief="solid", borderwidth=1,
        ).pack(fill="x", ipady=5)

        tk.Label(
            self.content, text="Client secret", bg=BG, fg=TEXT_MUTED,
            font=(FONT, 9, "bold"), anchor="w",
        ).pack(anchor="w", pady=(14, 2))
        tk.Entry(
            self.content, textvariable=self.client_secret_var, font=(FONT, 10),
            relief="solid", borderwidth=1,
        ).pack(fill="x", ipady=5)

    def _step_done(self):
        self._title("\U0001F389 All set")
        self._body(f"Your credentials were saved to {ENV_PATH}.")
        self._body(
            "Next, from a terminal in this folder, run:\n\n"
            "  pip install -r requirements.txt\n"
            "  python gmail_fetch_data.py\n"
            "  python drive_fetch_data.py\n"
            "  streamlit run dashboard.py"
        )
        self._body(
            "The first script run will open a browser window asking you "
            "to sign in and consent -- you'll see Google's \"unverified "
            "app\" warning, which is expected (see the README for why). "
            "Click Advanced, then Go to Reclaim (unsafe) to continue."
        )

    # ---------- credential saving ----------

    def _save_credentials(self):
        client_id = self.client_id_var.get()
        client_secret = self.client_secret_var.get()

        if not client_id.strip() or not client_secret.strip():
            messagebox.showwarning(
                "Missing information",
                "Enter both the Client ID and Client secret before continuing.",
            )
            return False

        if not looks_like_client_id(client_id):
            if not messagebox.askyesno(
                "Double-check the Client ID",
                "That doesn't look like a typical Google Client ID (they "
                "usually end in \"apps.googleusercontent.com\"). Continue "
                "anyway?",
            ):
                return False

        if not looks_like_client_secret(client_secret):
            if not messagebox.askyesno(
                "Double-check the Client secret",
                "That doesn't look like a typical Client secret. Continue "
                "anyway?",
            ):
                return False

        try:
            write_env_file(client_id, client_secret)
        except OSError as e:
            messagebox.showerror("Couldn't save", f"Failed to write {ENV_PATH}:\n{e}")
            return False

        return True


if __name__ == "__main__":
    Wizard().mainloop()
