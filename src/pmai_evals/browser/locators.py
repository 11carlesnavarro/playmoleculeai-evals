"""Single source of truth for UI selectors.

If a locator changes in the frontend, edit it here only. Tests and the
runner reference these constants by name, never inline. Use Playwright
``getByRole(role, name=...)`` or ``getByText(...)`` — never CSS.
"""

from __future__ import annotations

from typing import Final

# (role, accessible name) — fed to ``page.get_by_role(role, name=...)``.
PROMPT_INPUT: Final[tuple[str, str]] = ("textbox", "Ask anything.")
REGENERATE_BUTTON: Final[tuple[str, str]] = ("button", "Regenerate")
NEW_CHAT_BUTTON: Final[tuple[str, str]] = ("button", "New chat")
ACCOUNT_BUTTON: Final[tuple[str, str]] = ("button", "Account")
SHOW_HISTORY_BUTTON: Final[tuple[str, str]] = ("button", "Show chat history")
DELETE_MENUITEM: Final[tuple[str, str]] = ("menuitem", "Delete")

# Login form labels (used by setup-auth).
EMAIL_LABEL: Final[str] = "Email"
PASSWORD_LABEL: Final[str] = "Password"
SUBMIT_BUTTON: Final[tuple[str, str]] = ("button", "Submit")

# Model picker — exact selector TBD; this is the working assumption.
MODEL_PICKER_BUTTON: Final[tuple[str, str]] = ("button", "Model")
