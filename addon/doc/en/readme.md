# Clipboard Announcer

Clipboard Announcer is an NVDA add-on that speaks common editing and clipboard actions as you work. It is designed for users who want quick spoken feedback for copy, cut, paste, selection, undo, redo, and a few clipboard-related tasks without changing the normal behavior of those shortcuts.

## Key features

- Speaks common editing shortcuts such as copy, cut, paste, select all, undo, and redo
- Can optionally use smart clipboard feedback for Copy, Cut, and Paste, including content detection, file counts, and empty-state feedback
- Includes an optional append-copy command that adds newly copied text to the current clipboard text
- Can be temporarily silenced with a shortcut when you do not want spoken feedback
- Can copy the full path of the selected file or folder
- Keeps a persistent clipboard history for text and copied files
- Opens clipboard history with a shortcut and clears the clipboard when pressed twice quickly
- Can report clipboard access problems
- Includes a settings panel in NVDA so you can choose which announcements to hear

## Installation

1. Download or obtain the add-on package file for Clipboard Announcer.
2. Open the package file.
3. When NVDA asks whether you want to install the add-on, choose `Yes`.
4. Restart NVDA if prompted.

After installation, you can review or change the add-on settings from the NVDA Settings dialog.

`Use smart clipboard feedback for Copy, Cut, and Paste` is enabled by default, and you can turn it off in the settings if you prefer. When enabled, it can identify clipboard content, announce file counts for Copy and Cut, and report when nothing is available to copy, cut, or paste.

## Default shortcuts

- `Ctrl+C`: Announce copy, or when enabled, identify copied clipboard content, announce file counts for copied items, or report when nothing is selected
- `Ctrl+X`: Announce cut, or when enabled, announce file counts for cut items or report when nothing is selected
- `Ctrl+V`: Announce paste, or identify clipboard content being pasted and warn if the clipboard is empty when enabled
- `Ctrl+A`: Announce select all
- `Ctrl+Z`: Announce undo
- `Ctrl+Y`: Announce redo
- `Ctrl+Shift+S`: Temporarily disable or enable Clipboard Announcer
- `Ctrl+Shift+C`: Copy the selected file or folder path
- `Ctrl+Shift+X`: Open clipboard history; press it twice within 0.6 seconds to clear clipboard history while keeping pinned items, or three times to clear the clipboard. Disable clipboard history in Clipboard Announcer settings to make this shortcut clear the clipboard immediately.

## Clipboard history

When clipboard history is enabled, the add-on records text and copied files from all applications, including applications that do not use the add-on's Copy shortcut. Items copied while it is disabled are not added. History is stored in the NVDA configuration directory and is retained after restarting NVDA. The most recent 500 items are kept; text items larger than 1 MiB are not recorded.

Open the context menu with the Applications key, `Shift+F10`, or a right click to pin or unpin an item, rename its display name, edit text items, or delete an item. A display name changes only how the item is shown; its clipboard text or files remain unchanged. Press `Ctrl+P` to pin or unpin the selected item, `Ctrl+E` to edit the selected text item, or `Ctrl+R` to rename the selected item's display name. You can also press `Delete` to remove the selected item. Pinned items stay at the top of the history and are kept when you choose `Clear all history`; deleting a pinned item requires confirmation. Use `Move pinned item up` and `Move pinned item down` to choose their persistent order, or press `Ctrl+Page Up` and `Ctrl+Page Down` to move the selected pinned item.

## Additional commands

- `Append copied text to the existing clipboard text`: No default shortcut is assigned. You can bind it from NVDA `Input Gestures` under the `Clipboard Announcer` category.
  When the clipboard is empty, the command behaves like a normal copy. When the clipboard contains non-text content, it leaves the clipboard unchanged.

## Compatibility

Clipboard Announcer requires NVDA 2024.1 or later and was last tested with NVDA 2026.1.
