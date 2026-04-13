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

# Login form labels (used by setup-auth).
EMAIL_LABEL: Final[str] = "Email"
PASSWORD_LABEL: Final[str] = "Password"
SUBMIT_BUTTON: Final[tuple[str, str]] = ("button", "Submit")

# pmview sidebar "Add Files" flow — drives the Get-PDB dialog and the
# hidden file input that backs the "Open" menu item. ``CONFIRM_BUTTON``
# is reused by SaveSystemDialog, which also renders a "Confirm" button.
ADD_FILES_BUTTON: Final[tuple[str, str]] = ("button", "Add Files")
GET_PDB_MENU_ITEM: Final[tuple[str, str]] = ("menuitem", "Get PDB")
PDB_ID_FIELD: Final[tuple[str, str]] = ("textbox", "4 letter PDB identifier")
CONFIRM_BUTTON: Final[tuple[str, str]] = ("button", "Confirm")
# Stable element id on the hidden <input type="file"> inside LoadFileMenuItem.
FILE_UPLOAD_INPUT: Final[str] = "#raised-button-file"

# File Browser panel + Chonky toolbar. The sidebar entry is an icon-only
# MUI ListItemButton with no aria-label, so ``get_by_role`` can't find it
# by accessible name. We target the FolderOpen icon that MUI ships with
# ``data-testid="FolderOpenIcon"`` by default — it's unique in the sidebar.
FILE_BROWSER_ICON: Final[str] = "[data-testid='FolderOpenIcon']"
DOWNLOAD_SELECTED_BUTTON: Final[tuple[str, str]] = (
    "button",
    "Download selected files",
)
# Chonky mounts its grid inside an element carrying a class containing
# "chonkyRoot" (the exact name is webpack-hashed in production, so match
# by substring).
CHONKY_ROOT: Final[str] = "[class*='chonkyRoot']"

# BackendFileBrowser's hidden ``<input type="file" multiple>`` that the
# Chonky "Upload" toolbar button clicks. Distinguished from the sidebar
# "Add Files → Open" input (``#raised-button-file``) by id exclusion —
# both inputs exist in the DOM when the File Browser panel is open.
PROJECT_UPLOAD_INPUT: Final[str] = "input[type='file']:not(#raised-button-file)"

# Systems panel — per-system "⋮" menu + SaveSystemDialog. MUI
# @mui/icons-material icons expose ``data-testid="<Name>Icon"`` by default,
# which is how we find the more-options button without touching pmview.
SYSTEM_MORE_ICON: Final[str] = "[data-testid='MoreVertIcon']"
SYSTEM_DOWNLOAD_MENU_ITEM: Final[tuple[str, str]] = ("menuitem", "Download")
SAVE_FORMAT_FIELD: Final[str] = "#download-file-select-format"

# Sidebar "Export Viewer State" button. Two variants exist in pmview:
# a single ListItemButton (tooltip "Export Viewer State") and a popup
# menu whose outer button has tooltip "Export" and inner menu item
# "Export Viewer State". Both wrap a ``<SaveIcon />`` as their icon, so
# we locate by the MUI-default testid and — if a popup opens after the
# click — follow up with the menu item.
EXPORT_VIEWER_ICON: Final[str] = "[data-testid='SaveIcon']"
EXPORT_VIEWER_MENU_ITEM: Final[tuple[str, str]] = (
    "menuitem",
    "Export Viewer State",
)
