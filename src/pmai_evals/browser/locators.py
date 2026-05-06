"""Single source of truth for UI selectors.

Use Playwright ``getByRole(role, name=...)`` or ``getByText(...)``, never
CSS, except where the frontend offers no other unambiguous handle (icon
testids, hidden inputs).
"""

from __future__ import annotations

from typing import Final

# (role, accessible name) tuples for ``page.get_by_role(role, name=...)``.
PROMPT_INPUT: Final[tuple[str, str]] = ("textbox", "Ask anything.")
REGENERATE_BUTTON: Final[tuple[str, str]] = ("button", "Regenerate")
ACCOUNT_BUTTON: Final[tuple[str, str]] = ("button", "Account")

# Chat settings dialog hosts the model picker. ``SETTINGS_BUTTON_LABEL`` is
# matched via ``get_by_label`` because molstar ships two ``<button title="Settings">``
# controls; only the MUI IconButton has an explicit ``aria-label``.
SETTINGS_BUTTON_LABEL: Final[str] = "Settings"
SETTINGS_DIALOG: Final[tuple[str, str]] = ("dialog", "Settings")
MODEL_SELECT: Final[tuple[str, str]] = ("combobox", "Model")

# Login form (used by setup-auth).
EMAIL_LABEL: Final[str] = "Email"
PASSWORD_LABEL: Final[str] = "Password"
SUBMIT_BUTTON: Final[tuple[str, str]] = ("button", "Submit")

# pmview sidebar "Add Files" flow.
ADD_FILES_BUTTON: Final[tuple[str, str]] = ("button", "Add Files")
GET_PDB_MENU_ITEM: Final[tuple[str, str]] = ("menuitem", "Get PDB")
PDB_ID_FIELD: Final[tuple[str, str]] = ("textbox", "4 letter PDB identifier")
CONFIRM_BUTTON: Final[tuple[str, str]] = ("button", "Confirm")
FILE_UPLOAD_INPUT: Final[str] = "#raised-button-file"

# File Browser panel + Chonky toolbar. The sidebar entry is icon-only with
# no aria-label, so we target the FolderOpen icon by its MUI testid.
FILE_BROWSER_ICON: Final[str] = "[data-testid='FolderOpenIcon']"
CHONKY_ROOT: Final[str] = "[class*='chonkyRoot']"

# BackendFileBrowser's hidden ``<input type="file" multiple>`` driven by the
# Chonky Upload toolbar button. Distinguished from the sidebar Open input
# (``#raised-button-file``) by id exclusion.
PROJECT_UPLOAD_INPUT: Final[str] = "input[type='file']:not(#raised-button-file)"

# Sidebar "Export Viewer State". Two pmview variants exist: a single
# ListItemButton with tooltip "Export Viewer State" and a popup whose
# button has tooltip "Export" and inner menu item "Export Viewer State".
# Both wrap a SaveIcon, so we locate by the MUI testid and follow up
# with the menu item if the popup appears.
EXPORT_VIEWER_ICON: Final[str] = "[data-testid='SaveIcon']"
EXPORT_VIEWER_MENU_ITEM: Final[tuple[str, str]] = ("menuitem", "Export Viewer State")
