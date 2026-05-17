# Clipboard Announcer

Clipboard Announcer is an NVDA add-on that speaks common editing and clipboard actions as you work. It is designed for users who want quick spoken feedback for copy, cut, paste, selection, undo, redo, and a few clipboard-related tasks without changing the normal behavior of those shortcuts.

## Key features

- Speaks common editing shortcuts such as copy, cut, paste, select all, undo, and redo
- Can optionally identify clipboard content types for Copy and Paste, including file counts for Copy and Cut
- Can warn when Copy or Cut is pressed with nothing selected
- Can be temporarily silenced with a shortcut when you do not want spoken feedback
- Can copy the full path of the selected file or folder
- Can clear the clipboard with a shortcut
- Can warn you when you try to paste from an empty clipboard
- Can report clipboard access problems
- Includes a settings panel in NVDA so you can choose which announcements to hear

## Installation

1. Download or obtain the add-on package file for Clipboard Announcer.
2. Open the package file.
3. When NVDA asks whether you want to install the add-on, choose `Yes`.
4. Restart NVDA if prompted.

After installation, you can review or change the add-on settings from the NVDA Settings dialog.

Clipboard content awareness for Copy and Paste is available as an optional setting and is turned off by default. When enabled, it can also announce file counts for Copy and Cut. Context-aware announcements for Copy and Cut are built into the add-on.

## Default shortcuts

- `Ctrl+C`: Announce copy, identify copied clipboard content when enabled, announce file counts for copied items when available, or warn if nothing is selected
- `Ctrl+X`: Announce cut, announce file counts for cut items when available, or warn if nothing is selected
- `Ctrl+V`: Announce paste, or identify clipboard content being pasted when enabled
- `Ctrl+A`: Announce select all
- `Ctrl+Z`: Announce undo
- `Ctrl+Y`: Announce redo
- `Ctrl+Shift+S`: Temporarily disable or enable Clipboard Announcer
- `Ctrl+Shift+C`: Copy the selected file or folder path
- `Ctrl+Shift+X`: Clear the clipboard

## Compatibility

Clipboard Announcer requires NVDA 2024.1 or later and was last tested with NVDA 2026.1.
