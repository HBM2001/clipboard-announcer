# -*- coding: UTF-8 -*-
# A simple NVDA global plugin that announces common editing shortcuts.

import ctypes
from ctypes import wintypes
import json
import os
import tempfile
import time

import addonHandler
import api
import config
import controlTypes
import globalPluginHandler
import globalVars
import gui
import keyboardHandler
import scriptHandler
import textInfos
import ui
import wx
from gui import guiHelper
from gui.settingsDialogs import NVDASettingsDialog, SettingsPanel
from scriptHandler import script

addonHandler.initTranslation()


CONFIG_SECTION = "clipboardAnnouncer"
SMART_DUPLICATE_WINDOW_SECONDS = 0.6
STATUS_MESSAGE_REPEAT_WINDOW_SECONDS = 1.5
CLIPBOARD_COPY_INITIAL_DELAY_MS = 20
CLIPBOARD_COPY_RETRY_DELAY_MS = 35
CLIPBOARD_COPY_MAX_RETRIES = 2
APPEND_COPY_DISPATCH_DELAY_MS = 40
APPEND_COPY_DISPATCH_RETRY_MS = 25
APPEND_COPY_DISPATCH_MAX_RETRIES = 40
CLIPBOARD_HISTORY_POLL_INTERVAL_MS = 250
CLIPBOARD_HISTORY_DOUBLE_PRESS_WINDOW_MS = 600
CLIPBOARD_HISTORY_MAX_ITEMS = 500
CLIPBOARD_HISTORY_MAX_TEXT_BYTES = 1024 * 1024
CLIPBOARD_HISTORY_FILE_NAME = "clipboardAnnouncer-history.json"
SWC_DESKTOP = 0x8
SWFO_NEEDDISPATCH = 0x1
_UNSET = object()
CF_TEXT = 1
CF_BITMAP = 2
CF_DIB = 8
CF_HDROP = 15
CF_UNICODETEXT = 13
CF_DIBV5 = 17
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C
ANNOUNCEMENT_MODE_ALWAYS = "always"
ANNOUNCEMENT_MODE_SMART = "smart"
ANNOUNCEMENT_MODE_CHOICES = (
	(ANNOUNCEMENT_MODE_ALWAYS, _("Always announce")),
	(ANNOUNCEMENT_MODE_SMART, _("Smart (avoid repeated announcements)")),
)
CONFIG_SPEC = {
	"announcementsEnabled": "boolean(default=True)",
	"announcementMode": "option('always', 'smart', default='always')",
	"announceCopy": "boolean(default=True)",
	"announceCut": "boolean(default=True)",
	"announcePaste": "boolean(default=True)",
	"announceSelectAll": "boolean(default=True)",
	"announceUndo": "boolean(default=True)",
	"announceRedo": "boolean(default=True)",
	"announceAppendCopy": "boolean(default=True)",
	"announceCopyPath": "boolean(default=True)",
	"clipboardContentAwareness": "boolean(default=True)",
	"announceClearResult": "boolean(default=True)",
	"confirmBeforeClear": "boolean(default=False)",
	"announceClipboardAccessProblems": "boolean(default=True)",
	"clipboardHistoryEnabled": "boolean(default=True)",
}

_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_SHELL32 = ctypes.WinDLL("shell32", use_last_error=True)
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

OpenClipboard = _USER32.OpenClipboard
OpenClipboard.argtypes = [wintypes.HWND]
OpenClipboard.restype = wintypes.BOOL

CloseClipboard = _USER32.CloseClipboard
CloseClipboard.argtypes = []
CloseClipboard.restype = wintypes.BOOL

CountClipboardFormats = _USER32.CountClipboardFormats
CountClipboardFormats.argtypes = []
CountClipboardFormats.restype = wintypes.INT

IsClipboardFormatAvailable = _USER32.IsClipboardFormatAvailable
IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
IsClipboardFormatAvailable.restype = wintypes.BOOL

GetClipboardData = _USER32.GetClipboardData
GetClipboardData.argtypes = [wintypes.UINT]
GetClipboardData.restype = wintypes.HANDLE

RegisterClipboardFormatW = _USER32.RegisterClipboardFormatW
RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
RegisterClipboardFormatW.restype = wintypes.UINT

GetClipboardSequenceNumber = _USER32.GetClipboardSequenceNumber
GetClipboardSequenceNumber.argtypes = []
GetClipboardSequenceNumber.restype = wintypes.DWORD

GetForegroundWindow = _USER32.GetForegroundWindow
GetForegroundWindow.argtypes = []
GetForegroundWindow.restype = wintypes.HWND

SetForegroundWindow = _USER32.SetForegroundWindow
SetForegroundWindow.argtypes = [wintypes.HWND]
SetForegroundWindow.restype = wintypes.BOOL

GetAsyncKeyState = _USER32.GetAsyncKeyState
GetAsyncKeyState.argtypes = [wintypes.INT]
GetAsyncKeyState.restype = wintypes.SHORT

EmptyClipboard = _USER32.EmptyClipboard
EmptyClipboard.argtypes = []
EmptyClipboard.restype = wintypes.BOOL

DragQueryFileW = _SHELL32.DragQueryFileW
DragQueryFileW.argtypes = [
	wintypes.HANDLE,
	wintypes.UINT,
	wintypes.LPWSTR,
	wintypes.UINT,
]
DragQueryFileW.restype = wintypes.UINT

GlobalLock = _KERNEL32.GlobalLock
GlobalLock.argtypes = [wintypes.HGLOBAL]
GlobalLock.restype = wintypes.LPVOID

GlobalUnlock = _KERNEL32.GlobalUnlock
GlobalUnlock.argtypes = [wintypes.HGLOBAL]
GlobalUnlock.restype = wintypes.BOOL


class ClipboardEmptyError(RuntimeError):
	pass


class ClipboardAccessError(RuntimeError):
	pass


class ClipboardHistoryEmptyTextError(ValueError):
	pass


class ClipboardHistoryDialog(wx.Dialog):
	"""A keyboard-first view of the add-on's persisted clipboard history."""

	def __init__(self, plugin, entries):
		super().__init__(
			gui.mainFrame,
			title=_("Clipboard history"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._plugin = plugin
		self._entries = entries
		self.selectedEntry = None
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(
			wx.StaticText(
				self,
				label=_("History:"),
			),
			border=10,
			flag=wx.ALL,
		)
		self._list = wx.ListBox(self, choices=[self._labelFor(entry) for entry in entries])
		sizer.Add(self._list, proportion=1, border=10, flag=wx.LEFT | wx.RIGHT | wx.EXPAND)
		if entries:
			self._list.SetSelection(0)
		buttonSizer = wx.StdDialogButtonSizer()
		self._clearButton = wx.Button(self, label=_("Clear all history"))
		buttonSizer.AddButton(self._clearButton)
		buttonSizer.Realize()
		sizer.Add(buttonSizer, border=10, flag=wx.ALL | wx.ALIGN_RIGHT)
		self.SetSizerAndFit(sizer)
		self.SetMinSize((480, 300))
		self.CentreOnScreen()
		self._list.Bind(wx.EVT_LISTBOX_DCLICK, self._onActivate)
		self._list.Bind(wx.EVT_CONTEXT_MENU, self._onContextMenu)
		self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
		self._clearButton.Bind(wx.EVT_BUTTON, self._onClear)
		self.Bind(wx.EVT_CLOSE, self._onWindowClose)

	def focusList(self):
		self._list.SetFocus()

	def _labelFor(self, entry):
		pinnedPrefix = _("Pinned: ") if entry.get("pinned", False) else ""
		if entry["type"] == "files":
			paths = entry["paths"]
			firstPath = paths[0] if paths else ""
			return pinnedPrefix + firstPath
		text = entry["text"].replace("\r", " ").replace("\n", " ").strip()
		return pinnedPrefix + (text[:120] or _("(empty text)"))

	def _onCharHook(self, evt):
		keyCode = evt.GetKeyCode()
		if keyCode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
			self._activateSelected()
			return
		if keyCode == wx.WXK_ESCAPE:
			self.Close()
			return
		if keyCode in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE):
			self._deleteSelected()
			return
		if keyCode in (wx.WXK_MENU, wx.WXK_WINDOWS_MENU):
			self._showContextMenu()
			return
		if keyCode == wx.WXK_F10 and evt.ShiftDown():
			self._showContextMenu()
			return
		evt.Skip()

	def _onActivate(self, evt):
		self._activateSelected()

	def _activateSelected(self):
		selection = self._list.GetSelection()
		if selection != wx.NOT_FOUND:
			self.selectedEntry = self._entries[selection]
			self.EndModal(wx.ID_OK)

	def _onClear(self, evt):
		removedCount, pinnedCount = self._plugin._clearClipboardHistory()
		self._refreshEntries()
		if pinnedCount:
			ui.message(
				_("Cleared %d history items. Kept %d pinned items.")
				% (removedCount, pinnedCount)
			)
			return
		ui.message(_("Cleared %d history items.") % removedCount)

	def _onContextMenu(self, evt):
		position = evt.GetPosition()
		if position != wx.DefaultPosition:
			position = self._list.ScreenToClient(position)
			selection = self._list.HitTest(position)
			if selection != wx.NOT_FOUND:
				self._list.SetSelection(selection)
		self._showContextMenu(position)

	def _showContextMenu(self, position=wx.DefaultPosition):
		selection = self._list.GetSelection()
		if selection == wx.NOT_FOUND:
			return
		entry = self._entries[selection]
		menu = wx.Menu()
		pinItem = menu.Append(
			wx.ID_ANY,
			_("Unpin history") if entry.get("pinned", False) else _("Pin history"),
		)
		moveUpItem = menu.Append(wx.ID_ANY, _("Move pinned item up"))
		moveDownItem = menu.Append(wx.ID_ANY, _("Move pinned item down"))
		moveUpItem.Enable(self._plugin._canMovePinnedClipboardHistoryEntry(entry, -1))
		moveDownItem.Enable(self._plugin._canMovePinnedClipboardHistoryEntry(entry, 1))
		editItem = menu.Append(wx.ID_ANY, _("Edit"))
		editItem.Enable(entry["type"] == "text")
		deleteItem = menu.Append(wx.ID_ANY, _("Delete"))
		menu.Bind(wx.EVT_MENU, lambda evt: self._onPin(entry), pinItem)
		menu.Bind(wx.EVT_MENU, lambda evt: self._onMovePinned(entry, -1), moveUpItem)
		menu.Bind(wx.EVT_MENU, lambda evt: self._onMovePinned(entry, 1), moveDownItem)
		menu.Bind(wx.EVT_MENU, lambda evt: self._onEdit(entry), editItem)
		menu.Bind(wx.EVT_MENU, lambda evt: self._onDelete(entry), deleteItem)
		try:
			self._list.PopupMenu(menu, position)
		finally:
			menu.Destroy()

	def _onPin(self, entry):
		self._plugin._setClipboardHistoryPinned(entry, not entry.get("pinned", False))
		self._refreshEntries(entry)

	def _onMovePinned(self, entry, direction):
		if self._plugin._movePinnedClipboardHistoryEntry(entry, direction):
			self._refreshEntries(entry)

	def _onEdit(self, entry):
		if entry["type"] != "text":
			return
		dialog = wx.TextEntryDialog(
			self,
			_("Edit clipboard history text:"),
			_("Edit history"),
			value=entry["text"],
			style=wx.OK | wx.CANCEL | wx.TE_MULTILINE,
		)
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			try:
				newEntry = self._plugin._editClipboardHistoryText(
					entry, dialog.GetValue()
				)
			except ClipboardHistoryEmptyTextError:
				ui.message(_("History item cannot be empty"))
				return
		finally:
			dialog.Destroy()
		if newEntry is None:
			ui.message(_("History item is too large"))
			return
		self._refreshEntries(newEntry)

	def _onDelete(self, entry):
		if entry.get("pinned", False):
			dialog = wx.MessageDialog(
				self,
				_("Delete this pinned history item?"),
				_("Clipboard history"),
				wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
			)
			try:
				if dialog.ShowModal() != wx.ID_YES:
					return
			finally:
				dialog.Destroy()
		self._plugin._deleteClipboardHistoryEntry(entry)
		self._refreshEntries()

	def _deleteSelected(self):
		selection = self._list.GetSelection()
		if selection != wx.NOT_FOUND:
			self._onDelete(self._entries[selection])

	def _refreshEntries(self, selectedEntry=None):
		self._entries = list(self._plugin._clipboardHistory)
		self._list.Set([self._labelFor(entry) for entry in self._entries])
		if not self._entries:
			return
		try:
			selection = self._entries.index(selectedEntry)
		except ValueError:
			selection = 0
		self._list.SetSelection(selection)

	def _onWindowClose(self, evt):
		evt.Skip()


def _getConfig():
	return config.conf[CONFIG_SECTION]


def _openSettingsPanel():
	popupSettingsDialog = getattr(gui.mainFrame, "popupSettingsDialog", None)
	if popupSettingsDialog is None:
		popupSettingsDialog = gui.mainFrame._popupSettingsDialog
	popupSettingsDialog(NVDASettingsDialog, ClipboardAnnouncerSettingsPanel)


class ClipboardAnnouncerSettingsPanel(SettingsPanel):
	title = _("Clipboard Announcer")
	panelDescription = _("Configure announcements and clipboard clearing behavior.")

	def makeSettings(self, settingsSizer):
		sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		conf = _getConfig()

		self.enableAnnouncementsCheckbox = sHelper.addItem(
			wx.CheckBox(self, label=_("Enable spoken shortcut feedback"))
		)
		self.enableAnnouncementsCheckbox.SetValue(conf["announcementsEnabled"])
		self.enableAnnouncementsCheckbox.Bind(wx.EVT_CHECKBOX, self._onAnnouncementsToggle)
		self.enableClipboardHistoryCheckbox = sHelper.addItem(
			wx.CheckBox(
				self,
				label=_("Enable clipboard history with Control+Shift+X"),
			)
		)
		self.enableClipboardHistoryCheckbox.SetValue(conf["clipboardHistoryEnabled"])

		self.announcementModeChoice = sHelper.addLabeledControl(
			_("Announcement behavior:"),
			wx.Choice,
			choices=[label for _, label in ANNOUNCEMENT_MODE_CHOICES],
		)
		self.announcementModeChoice.SetSelection(
			self._getAnnouncementModeSelection(conf["announcementMode"])
		)

		shortcutsGroup = wx.StaticBoxSizer(wx.VERTICAL, self, _("Shortcuts to announce"))
		self.announceCopyCheckbox = wx.CheckBox(self, label=_("Announce Copy"))
		self.announceCutCheckbox = wx.CheckBox(self, label=_("Announce Cut"))
		self.announcePasteCheckbox = wx.CheckBox(self, label=_("Announce Paste"))
		self.announceSelectAllCheckbox = wx.CheckBox(self, label=_("Announce Select All"))
		self.announceUndoCheckbox = wx.CheckBox(self, label=_("Announce Undo"))
		self.announceRedoCheckbox = wx.CheckBox(self, label=_("Announce Redo"))
		self.announceAppendCopyCheckbox = wx.CheckBox(self, label=_("Announce Append Copy"))
		self.announceCopyPathCheckbox = wx.CheckBox(self, label=_("Announce Copy Path"))
		self.clipboardContentAwarenessCheckbox = wx.CheckBox(
			self, label=_("Use smart clipboard feedback for Copy, Cut, and Paste")
		)

		self.announceCopyCheckbox.SetValue(conf["announceCopy"])
		self.announceCutCheckbox.SetValue(conf["announceCut"])
		self.announcePasteCheckbox.SetValue(conf["announcePaste"])
		self.announceSelectAllCheckbox.SetValue(conf["announceSelectAll"])
		self.announceUndoCheckbox.SetValue(conf["announceUndo"])
		self.announceRedoCheckbox.SetValue(conf["announceRedo"])
		self.announceAppendCopyCheckbox.SetValue(conf["announceAppendCopy"])
		self.announceCopyPathCheckbox.SetValue(conf["announceCopyPath"])
		self.clipboardContentAwarenessCheckbox.SetValue(conf["clipboardContentAwareness"])

		for checkbox in (
			self.announceCopyCheckbox,
			self.announceCutCheckbox,
			self.announcePasteCheckbox,
			self.announceSelectAllCheckbox,
			self.announceUndoCheckbox,
			self.announceRedoCheckbox,
			self.announceAppendCopyCheckbox,
			self.announceCopyPathCheckbox,
			self.clipboardContentAwarenessCheckbox,
		):
			shortcutsGroup.Add(checkbox, border=5, flag=wx.BOTTOM)

		settingsSizer.Add(shortcutsGroup, border=10, flag=wx.TOP | wx.EXPAND)

		self.announceClearResultCheckbox = sHelper.addItem(
			wx.CheckBox(self, label=_("Speak the result after clearing the clipboard"))
		)
		self.announceClearResultCheckbox.SetValue(conf["announceClearResult"])

		self.confirmBeforeClearCheckbox = sHelper.addItem(
			wx.CheckBox(self, label=_("Ask before clearing the clipboard"))
		)
		self.confirmBeforeClearCheckbox.SetValue(conf["confirmBeforeClear"])

		statusGroup = wx.StaticBoxSizer(
			wx.VERTICAL, self, _("Clipboard warnings and status messages")
		)
		self.announceClipboardAccessProblemsCheckbox = wx.CheckBox(
			self, label=_("Speak an error if the clipboard cannot be accessed")
		)
		self.announceClipboardAccessProblemsCheckbox.SetValue(
			conf["announceClipboardAccessProblems"]
		)

		for checkbox in (self.announceClipboardAccessProblemsCheckbox,):
			statusGroup.Add(checkbox, border=5, flag=wx.BOTTOM)

		settingsSizer.Add(statusGroup, border=10, flag=wx.TOP | wx.EXPAND)
		self._updateAnnouncementsControls()

	def onSave(self):
		conf = _getConfig()
		conf["announcementsEnabled"] = self.enableAnnouncementsCheckbox.GetValue()
		conf["clipboardHistoryEnabled"] = (
			self.enableClipboardHistoryCheckbox.GetValue()
		)
		conf["announcementMode"] = ANNOUNCEMENT_MODE_CHOICES[
			self.announcementModeChoice.GetSelection()
		][0]
		conf["announceCopy"] = self.announceCopyCheckbox.GetValue()
		conf["announceCut"] = self.announceCutCheckbox.GetValue()
		conf["announcePaste"] = self.announcePasteCheckbox.GetValue()
		conf["announceSelectAll"] = self.announceSelectAllCheckbox.GetValue()
		conf["announceUndo"] = self.announceUndoCheckbox.GetValue()
		conf["announceRedo"] = self.announceRedoCheckbox.GetValue()
		conf["announceAppendCopy"] = self.announceAppendCopyCheckbox.GetValue()
		conf["announceCopyPath"] = self.announceCopyPathCheckbox.GetValue()
		conf["clipboardContentAwareness"] = (
			self.clipboardContentAwarenessCheckbox.GetValue()
		)
		conf["announceClearResult"] = self.announceClearResultCheckbox.GetValue()
		conf["confirmBeforeClear"] = self.confirmBeforeClearCheckbox.GetValue()
		conf["announceClipboardAccessProblems"] = (
			self.announceClipboardAccessProblemsCheckbox.GetValue()
		)

	def _getAnnouncementModeSelection(self, mode):
		for index, (value, _label) in enumerate(ANNOUNCEMENT_MODE_CHOICES):
			if value == mode:
				return index
		return 0

	def _onAnnouncementsToggle(self, evt):
		self._updateAnnouncementsControls()
		evt.Skip()

	def _updateAnnouncementsControls(self):
		enabled = self.enableAnnouncementsCheckbox.GetValue()
		self.announcementModeChoice.Enable(enabled)
		for checkbox in (
			self.announceCopyCheckbox,
			self.announceCutCheckbox,
			self.announcePasteCheckbox,
			self.announceSelectAllCheckbox,
			self.announceUndoCheckbox,
			self.announceRedoCheckbox,
			self.announceAppendCopyCheckbox,
			self.announceCopyPathCheckbox,
			self.clipboardContentAwarenessCheckbox,
		):
			checkbox.Enable(enabled)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	"""Announce editing actions while preserving the original shortcut behavior."""

	scriptCategory = _("Clipboard Announcer")

	def __init__(self):
		super().__init__()
		self._lastAnnouncementAction = None
		self._lastAnnouncementTime = 0.0
		self._lastStatusMessage = None
		self._lastStatusMessageTime = 0.0
		self._clearConfirmationDialogOpen = False
		self._silenceModeEnabled = False
		self._pendingClipboardAnnouncement = None
		self._pendingClipboardRetryCount = 0
		self._pendingClipboardSequenceNumber = None
		self._pendingClipboardActionName = None
		self._pendingClipboardConfigKey = None
		self._pendingClipboardSelectedItemCount = 0
		self._pendingClipboardOperation = None
		self._pendingClipboardOriginalText = None
		self._pendingClipboardDispatch = None
		self._pendingClipboardDispatchRetryCount = 0
		self._clipboardHistory = []
		self._clipboardHistoryMonitor = None
		self._clipboardHistorySequenceNumber = None
		self._clipboardHistoryShortcutTimer = None
		self._clipboardHistoryDialog = None
		self._clipboardHistoryPasteTargetHwnd = None
		self._registerConfig()
		self._registerSettingsPanel()
		self._loadClipboardHistory()
		self._clipboardHistorySequenceNumber = self._getClipboardSequenceNumber()
		self._scheduleClipboardHistoryMonitor()

	def terminate(self):
		self._stopClipboardHistoryMonitor()
		if self._clipboardHistoryShortcutTimer and self._clipboardHistoryShortcutTimer.IsRunning():
			self._clipboardHistoryShortcutTimer.Stop()
		self._clipboardHistoryShortcutTimer = None
		if self._clipboardHistoryDialog:
			self._clipboardHistoryDialog.Destroy()
			self._clipboardHistoryDialog = None
		if (
			self._pendingClipboardAnnouncement
			and self._pendingClipboardAnnouncement.IsRunning()
		):
			self._pendingClipboardAnnouncement.Stop()
		if self._pendingClipboardDispatch and self._pendingClipboardDispatch.IsRunning():
			self._pendingClipboardDispatch.Stop()
		self._pendingClipboardDispatch = None
		self._pendingClipboardAnnouncement = None
		self._pendingClipboardRetryCount = 0
		self._pendingClipboardSequenceNumber = None
		self._pendingClipboardActionName = None
		self._pendingClipboardConfigKey = None
		self._pendingClipboardSelectedItemCount = 0
		self._pendingClipboardOperation = None
		self._pendingClipboardOriginalText = None
		self._pendingClipboardDispatch = None
		self._pendingClipboardDispatchRetryCount = 0
		self._unregisterSettingsPanel()
		super().terminate()

	def _registerConfig(self):
		config.conf.spec[CONFIG_SECTION] = CONFIG_SPEC
		_getConfig()

	def _registerSettingsPanel(self):
		if ClipboardAnnouncerSettingsPanel in NVDASettingsDialog.categoryClasses:
			return
		for index, categoryClass in enumerate(NVDASettingsDialog.categoryClasses):
			if categoryClass.__name__ == "AdvancedPanel":
				NVDASettingsDialog.categoryClasses.insert(
					index, ClipboardAnnouncerSettingsPanel
				)
				return
		NVDASettingsDialog.categoryClasses.append(ClipboardAnnouncerSettingsPanel)

	def _unregisterSettingsPanel(self):
		if ClipboardAnnouncerSettingsPanel in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.remove(ClipboardAnnouncerSettingsPanel)

	def _getClipboardHistoryPath(self):
		configPath = getattr(getattr(globalVars, "appArgs", None), "configPath", None)
		if not configPath:
			raise OSError("NVDA configuration path is unavailable")
		return os.path.join(configPath, CLIPBOARD_HISTORY_FILE_NAME)

	def _loadClipboardHistory(self):
		try:
			with open(
				self._getClipboardHistoryPath(), "r", encoding="utf-8"
			) as historyFile:
				entries = json.load(historyFile)
		except (OSError, ValueError, TypeError):
			return
		if not isinstance(entries, list):
			return
		for entry in reversed(entries[:CLIPBOARD_HISTORY_MAX_ITEMS]):
			if self._isValidClipboardHistoryEntry(entry):
				self._addClipboardHistoryEntry(entry, save=False)

	def _isValidClipboardHistoryEntry(self, entry):
		if not isinstance(entry, dict):
			return False
		if entry.get("type") == "text":
			return isinstance(entry.get("text"), str) and self._textFitsClipboardHistory(
				entry["text"]
			)
		if entry.get("type") == "files":
			paths = entry.get("paths")
			return (
				isinstance(paths, list)
				and bool(paths)
				and all(isinstance(path, str) and path for path in paths)
			)
		return False

	def _normalizeClipboardHistoryEntry(self, entry):
		normalizedEntry = dict(entry)
		normalizedEntry["pinned"] = bool(entry.get("pinned", False))
		return normalizedEntry

	def _clipboardHistoryEntriesMatch(self, firstEntry, secondEntry):
		if firstEntry.get("type") != secondEntry.get("type"):
			return False
		if firstEntry["type"] == "text":
			return firstEntry.get("text") == secondEntry.get("text")
		return firstEntry.get("paths") == secondEntry.get("paths")

	def _textFitsClipboardHistory(self, text):
		try:
			return (
				len(text.encode("utf-8", errors="surrogatepass"))
				<= CLIPBOARD_HISTORY_MAX_TEXT_BYTES
			)
		except UnicodeError:
			return False

	def _saveClipboardHistory(self):
		temporaryPath = None
		try:
			historyPath = self._getClipboardHistoryPath()
			directory = os.path.dirname(historyPath)
			fd, temporaryPath = tempfile.mkstemp(
				prefix=".clipboardAnnouncer-history-",
				suffix=".json",
				dir=directory,
			)
			try:
				with os.fdopen(fd, "w", encoding="utf-8") as historyFile:
					json.dump(self._clipboardHistory, historyFile, ensure_ascii=False)
					historyFile.flush()
					os.fsync(historyFile.fileno())
				os.replace(temporaryPath, historyPath)
			except Exception:
				if temporaryPath:
					try:
						os.unlink(temporaryPath)
					except OSError:
						pass
		except OSError:
			return

	def _addClipboardHistoryEntry(self, entry, save=True):
		if not self._isValidClipboardHistoryEntry(entry):
			return None
		entry = self._normalizeClipboardHistoryEntry(entry)
		matchingEntries = [
			existing
			for existing in self._clipboardHistory
			if self._clipboardHistoryEntriesMatch(existing, entry)
		]
		pinnedMatchingIndex = None
		for index, existing in enumerate(self._clipboardHistory):
			if (
				self._clipboardHistoryEntriesMatch(existing, entry)
				and existing.get("pinned", False)
			):
				pinnedMatchingIndex = sum(
					1
					for pinnedEntry in self._clipboardHistory[:index]
					if pinnedEntry.get("pinned", False)
				)
				break
		if any(existing.get("pinned", False) for existing in matchingEntries):
			entry["pinned"] = True
		self._clipboardHistory = [
			existing
			for existing in self._clipboardHistory
			if not self._clipboardHistoryEntriesMatch(existing, entry)
		]
		if entry["pinned"]:
			if pinnedMatchingIndex is not None:
				self._clipboardHistory.insert(pinnedMatchingIndex, entry)
			else:
				self._clipboardHistory.insert(0, entry)
		else:
			pinnedCount = sum(
				1 for existing in self._clipboardHistory if existing.get("pinned", False)
			)
			self._clipboardHistory.insert(pinnedCount, entry)
		del self._clipboardHistory[CLIPBOARD_HISTORY_MAX_ITEMS:]
		if save:
			self._saveClipboardHistory()
		return entry

	def _clearClipboardHistory(self):
		pinnedEntries = [
			entry for entry in self._clipboardHistory if entry.get("pinned", False)
		]
		removedCount = len(self._clipboardHistory) - len(pinnedEntries)
		self._clipboardHistory = pinnedEntries
		self._saveClipboardHistory()
		return removedCount, len(pinnedEntries)

	def _setClipboardHistoryPinned(self, entry, pinned):
		for index, existing in enumerate(self._clipboardHistory):
			if self._clipboardHistoryEntriesMatch(existing, entry):
				entry = self._clipboardHistory.pop(index)
				entry["pinned"] = pinned
				if pinned:
					self._clipboardHistory.insert(0, entry)
				else:
					pinnedCount = sum(
						1
						for historyEntry in self._clipboardHistory
						if historyEntry.get("pinned", False)
					)
					self._clipboardHistory.insert(pinnedCount, entry)
				self._saveClipboardHistory()
				return entry
		return None

	def _findClipboardHistoryEntryIndex(self, entry):
		for index, existing in enumerate(self._clipboardHistory):
			if self._clipboardHistoryEntriesMatch(existing, entry):
				return index
		return None

	def _canMovePinnedClipboardHistoryEntry(self, entry, direction):
		if direction not in (-1, 1) or not entry.get("pinned", False):
			return False
		index = self._findClipboardHistoryEntryIndex(entry)
		if index is None:
			return False
		targetIndex = index + direction
		return (
			0 <= targetIndex < len(self._clipboardHistory)
			and self._clipboardHistory[targetIndex].get("pinned", False)
		)

	def _movePinnedClipboardHistoryEntry(self, entry, direction):
		if not self._canMovePinnedClipboardHistoryEntry(entry, direction):
			return False
		index = self._findClipboardHistoryEntryIndex(entry)
		targetIndex = index + direction
		self._clipboardHistory[index], self._clipboardHistory[targetIndex] = (
			self._clipboardHistory[targetIndex],
			self._clipboardHistory[index],
		)
		self._saveClipboardHistory()
		return True

	def _editClipboardHistoryText(self, entry, text):
		if not text.strip():
			raise ClipboardHistoryEmptyTextError()
		if not self._textFitsClipboardHistory(text):
			return None
		self._clipboardHistory = [
			existing
			for existing in self._clipboardHistory
			if not self._clipboardHistoryEntriesMatch(existing, entry)
		]
		updatedEntry = {
			"type": "text",
			"text": text,
			"pinned": entry.get("pinned", False),
		}
		return self._addClipboardHistoryEntry(updatedEntry)

	def _deleteClipboardHistoryEntry(self, entry):
		self._clipboardHistory = [
			existing
			for existing in self._clipboardHistory
			if not self._clipboardHistoryEntriesMatch(existing, entry)
		]
		self._saveClipboardHistory()

	def _scheduleClipboardHistoryMonitor(self):
		if self._clipboardHistoryMonitor and self._clipboardHistoryMonitor.IsRunning():
			self._clipboardHistoryMonitor.Stop()
		self._clipboardHistoryMonitor = wx.CallLater(
			CLIPBOARD_HISTORY_POLL_INTERVAL_MS,
			self._pollClipboardHistory,
		)

	def _stopClipboardHistoryMonitor(self):
		if self._clipboardHistoryMonitor and self._clipboardHistoryMonitor.IsRunning():
			self._clipboardHistoryMonitor.Stop()
		self._clipboardHistoryMonitor = None

	def _pollClipboardHistory(self):
		self._clipboardHistoryMonitor = None
		try:
			currentSequenceNumber = self._getClipboardSequenceNumber()
			if (
				currentSequenceNumber is not None
				and currentSequenceNumber != self._clipboardHistorySequenceNumber
			):
				if not _getConfig()["clipboardHistoryEnabled"]:
					self._clipboardHistorySequenceNumber = currentSequenceNumber
					return
				entry = self._readClipboardHistoryEntry()
				if entry is _UNSET:
					return
				self._clipboardHistorySequenceNumber = currentSequenceNumber
				if entry:
					self._addClipboardHistoryEntry(entry)
		finally:
			self._scheduleClipboardHistoryMonitor()

	def _readClipboardHistoryEntry(self):
		try:
			self._openClipboard()
		except ClipboardAccessError:
			return _UNSET
		try:
			if CountClipboardFormats() == 0:
				return None
			if IsClipboardFormatAvailable(CF_HDROP):
				paths = self._getOpenClipboardFileDropPaths()
				return {"type": "files", "paths": paths} if paths else None
			if IsClipboardFormatAvailable(CF_UNICODETEXT):
				text = self._getOpenClipboardUnicodeText(CF_UNICODETEXT)
				if text is not None and self._textFitsClipboardHistory(text):
					return {"type": "text", "text": text}
			if IsClipboardFormatAvailable(CF_TEXT):
				text = self._getOpenClipboardAnsiText()
				if text is not None and self._textFitsClipboardHistory(text):
					return {"type": "text", "text": text}
		except Exception:
			return _UNSET
		finally:
			CloseClipboard()
		return None

	def _getOpenClipboardUnicodeText(self, clipboardFormat):
		handle = GetClipboardData(clipboardFormat)
		if not handle:
			return None
		address = GlobalLock(handle)
		if not address:
			return None
		try:
			return ctypes.wstring_at(address)
		finally:
			GlobalUnlock(handle)

	def _getOpenClipboardAnsiText(self):
		handle = GetClipboardData(CF_TEXT)
		if not handle:
			return None
		address = GlobalLock(handle)
		if not address:
			return None
		try:
			return ctypes.string_at(address).decode("mbcs", errors="replace")
		finally:
			GlobalUnlock(handle)

	def _getOpenClipboardFileDropPaths(self):
		dropHandle = GetClipboardData(CF_HDROP)
		if not dropHandle:
			return []
		fileCount = DragQueryFileW(dropHandle, 0xFFFFFFFF, None, 0)
		paths = []
		for index in range(fileCount):
			length = DragQueryFileW(dropHandle, index, None, 0)
			if not length:
				continue
			buffer = ctypes.create_unicode_buffer(length + 1)
			if DragQueryFileW(dropHandle, index, buffer, length + 1):
				paths.append(buffer.value)
		return paths

	def _announceAndPassThrough(self, gesture, message, configKey, actionName):
		try:
			if self._shouldAnnounceShortcut(configKey, actionName):
				ui.message(message)
		finally:
			gesture.send()

	def _announceCopyAndPassThrough(self, gesture, copyGesture=None):
		copyGesture = copyGesture or gesture
		if self._executeBrowseModeCopyScript(copyGesture):
			return
		if self._copySelectedFileSystemPathsForCopy(announceAsCopy=True):
			return
		clipboardSequenceNumber = self._getClipboardSequenceNumber()
		try:
			if not self._shouldUseClipboardAwareness("announceCopy") and self._shouldAnnounceShortcut(
				"announceCopy", "copy"
			):
				ui.message(_("Copy"))
		finally:
			copyGesture.send()
		if self._shouldUseClipboardAwareness("announceCopy"):
			self._scheduleClipboardAwareActionAnnouncement(
				"copy",
				"announceCopy",
				sequenceNumber=clipboardSequenceNumber,
			)

	def _announceCutAndPassThrough(self, gesture):
		clipboardSequenceNumber = self._getClipboardSequenceNumber()
		try:
			if not self._shouldUseClipboardAwareness("announceCut") and self._shouldAnnounceShortcut(
				"announceCut", "cut"
			):
				ui.message(_("Cut"))
		finally:
			gesture.send()
		if self._shouldUseClipboardAwareness("announceCut"):
			self._scheduleClipboardAwareActionAnnouncement(
				"cut",
				"announceCut",
				sequenceNumber=clipboardSequenceNumber,
			)

	def _appendCopyAndPassThrough(self, gesture):
		if not self._isEditableAppendTarget():
			self._announceAppendCopyMessage(
				_("Append copy is only available in editable text fields")
			)
			return
		try:
			clipboardDetails = self._getClipboardContentDetails()
		except ClipboardAccessError:
			self._announceStatusMessage(
				_("Could not access clipboard"),
				requireAccessProblems=True,
			)
			return
		clipboardContentType = clipboardDetails["type"]
		if clipboardContentType == "empty":
			contextMessage = self._getContextAwareShortcutMessage("announceCopy", "copy")
			if contextMessage:
				self._announceStatusMessage(contextMessage)
				return
			self._queuePendingCopyDispatch(
				operation="appendCopyFallbackCopy",
				actionName="copy",
				configKey="announceCopy",
				selectedItemCount=self._getSelectedFileSystemItemCount(),
			)
			return
		if clipboardContentType != "text":
			self._announceAppendCopyMessage(
				_("Clipboard text append requires text already in the clipboard")
			)
			return
		try:
			originalText = self._getClipboardText()
		except ClipboardAccessError:
			self._announceStatusMessage(
				_("Could not access clipboard"),
				requireAccessProblems=True,
			)
			return
		clipboardSequenceNumber = self._getClipboardSequenceNumber()
		selectedItemCount = self._getSelectedFileSystemItemCount()
		self._queuePendingCopyDispatch(
			operation="appendCopy",
			actionName="appendCopy",
			configKey="announceAppendCopy",
			selectedItemCount=selectedItemCount,
			sequenceNumber=clipboardSequenceNumber,
			originalText=originalText,
		)

	def _createCopyGesture(self):
		return keyboardHandler.KeyboardInputGesture.fromName("control+c")

	def _isEditableAppendTarget(self):
		focus = api.getFocusObject()
		if not focus:
			return False
		treeInterceptor = getattr(focus, "treeInterceptor", None)
		if treeInterceptor and getattr(treeInterceptor, "isReady", False):
			if not getattr(treeInterceptor, "passThrough", True):
				return False
		states = getattr(focus, "states", set())
		try:
			stateEditable = controlTypes.State.EDITABLE
		except AttributeError:
			stateEditable = None
		if stateEditable is not None and stateEditable in states:
			return True
		role = getattr(focus, "role", None)
		try:
			roleEditables = {
				controlTypes.Role.EDITABLETEXT,
				controlTypes.Role.RICHEDIT,
				controlTypes.Role.PASSWORDEDIT,
			}
		except AttributeError:
			roleEditables = set()
		if role in roleEditables:
			return True
		return callable(getattr(focus, "makeTextInfo", None)) and bool(
			stateEditable is not None and stateEditable in states
		)

	def _executeBrowseModeCopyScript(self, gesture):
		focus = api.getFocusObject()
		if not focus:
			return False
		treeInterceptor = getattr(focus, "treeInterceptor", None)
		if not treeInterceptor or not getattr(treeInterceptor, "isReady", False):
			return False
		if getattr(treeInterceptor, "passThrough", True):
			return False
		getScript = getattr(treeInterceptor, "getScript", None)
		if not callable(getScript):
			return False
		try:
			treeInterceptorScript = getScript(gesture)
		except Exception:
			return False
		if not treeInterceptorScript:
			return False
		try:
			scriptHandler.executeScript(treeInterceptorScript, gesture)
		except Exception:
			return False
		return True

	def _announcePasteAndPassThrough(self, gesture):
		try:
			try:
				clipboardContentType = self._getClipboardContentType()
			except ClipboardAccessError:
				self._announceStatusMessage(
					_("Could not access clipboard"),
					requireAccessProblems=True,
				)
				return
			if (
				clipboardContentType == "empty"
				and self._shouldUseClipboardAwareness("announcePaste")
				and self._shouldAnnounceShortcut("announcePaste", "paste")
			):
				self._announceStatusMessage(_("Nothing to paste"))
				return
			if self._shouldUseClipboardAwareness("announcePaste"):
				self._announceClipboardAwarePasteMessage(clipboardContentType)
			elif self._shouldAnnounceShortcut("announcePaste", "paste"):
				ui.message(_("Paste"))
		finally:
			gesture.send()

	def _shouldUseClipboardAwareness(self, configKey):
		conf = _getConfig()
		return (
			not self._isSilenced()
			and conf["clipboardContentAwareness"]
			and conf["announcementsEnabled"]
			and conf[configKey]
		)

	def _shouldAnnounceShortcut(self, configKey, actionName):
		conf = _getConfig()
		if self._isSilenced() or not conf["announcementsEnabled"] or not conf[configKey]:
			return False

		now = time.monotonic()
		if (
			conf["announcementMode"] == ANNOUNCEMENT_MODE_SMART
			and self._lastAnnouncementAction == actionName
			and now - self._lastAnnouncementTime < SMART_DUPLICATE_WINDOW_SECONDS
		):
			return False

		self._lastAnnouncementAction = actionName
		self._lastAnnouncementTime = now
		return True

	def _announceStatusMessage(
		self,
		message,
		requireClearResult=False,
		requireAccessProblems=False,
	):
		conf = _getConfig()
		if self._isSilenced():
			return
		if requireClearResult and not conf["announceClearResult"]:
			return
		if requireAccessProblems and not conf["announceClipboardAccessProblems"]:
			return

		now = time.monotonic()
		if (
			conf["announcementMode"] == ANNOUNCEMENT_MODE_SMART
			and self._lastStatusMessage == message
			and now - self._lastStatusMessageTime < STATUS_MESSAGE_REPEAT_WINDOW_SECONDS
		):
			return

		self._lastStatusMessage = message
		self._lastStatusMessageTime = now
		ui.message(message)

	def _isSilenced(self):
		return self._silenceModeEnabled

	def _shouldAnnounceTemporarySilenceStatus(self):
		return _getConfig()["announcementsEnabled"]

	def _getContextAwareShortcutMessage(self, configKey, actionName):
		conf = _getConfig()
		if (
			not conf["announcementsEnabled"]
			or not conf[configKey]
			or not conf["clipboardContentAwareness"]
		):
			return None

		selectionState = self._getSelectionContextState()
		if selectionState == "empty":
			return {
				"copy": _("Nothing to copy"),
				"cut": _("Nothing to cut"),
			}.get(actionName)
		return None

	def _getSelectionContextState(self):
		browseModeSelectionState = self._getTextSelectionState(
			self._getBrowseModeSelectionProvider()
		)
		if browseModeSelectionState != "unknown":
			return browseModeSelectionState

		focusSelectionState = self._getTextSelectionState(api.getFocusObject())
		if focusSelectionState == "selected":
			return "selected"

		explorerSelectionState = self._getExplorerSelectionState()
		if explorerSelectionState != "unknown":
			if explorerSelectionState == "selected":
				return "selected"
			if focusSelectionState == "empty":
				return "empty"
			return explorerSelectionState

		if focusSelectionState != "unknown":
			return focusSelectionState
		return "unknown"

	def _getBrowseModeSelectionProvider(self):
		focus = api.getFocusObject()
		if not focus:
			return None
		treeInterceptor = getattr(focus, "treeInterceptor", None)
		if not treeInterceptor or not getattr(treeInterceptor, "isReady", False):
			return None
		if getattr(treeInterceptor, "passThrough", True):
			return None
		return treeInterceptor

	def _getTextSelectionState(self, selectionProvider):
		makeTextInfo = getattr(selectionProvider, "makeTextInfo", None)
		if not callable(makeTextInfo):
			return "unknown"
		try:
			selection = makeTextInfo(textInfos.POSITION_SELECTION)
		except Exception:
			return "unknown"
		if selection is None:
			return "unknown"

		isCollapsed = getattr(selection, "isCollapsed", None)
		if isCollapsed is True:
			return "empty"
		if isCollapsed is False:
			return "selected"

		try:
			selectionText = selection.text
		except Exception:
			return "unknown"
		if selectionText is None:
			return "unknown"
		if selectionText:
			return "selected"
		return "empty"

	def _getExplorerSelectionState(self):
		shellWindow = self._getForegroundShellWindow()
		if shellWindow is None:
			return "unknown"
		selectedPaths = self._extractStrictSelectedPaths(shellWindow)
		if selectedPaths:
			return "selected"
		return "empty"

	def _getForegroundShellWindow(self):
		try:
			from comtypes import client as comtypesClient
		except ImportError:
			return None

		foregroundHwnd = GetForegroundWindow()
		if not foregroundHwnd:
			return None

		try:
			shell = comtypesClient.CreateObject("Shell.Application", dynamic=True)
			windows = shell.Windows()
		except Exception:
			return None

		for index in range(windows.Count):
			try:
				window = windows.Item(index)
				if int(window.HWND) == foregroundHwnd:
					return window
			except Exception:
				continue
		return self._getForegroundDesktopShellWindow(windows, foregroundHwnd)

	def _getForegroundDesktopShellWindow(self, windows, foregroundHwnd):
		try:
			result = windows.FindWindowSW(
				0,
				None,
				SWC_DESKTOP,
				0,
				SWFO_NEEDDISPATCH,
			)
		except Exception:
			return None
		candidates = result if isinstance(result, tuple) else (result,)
		for window in candidates:
			try:
				if int(window.HWND) == foregroundHwnd:
					return window
			except Exception:
				continue
		return None

	def _getSelectedFileSystemPaths(self):
		shellWindow = self._getForegroundShellWindow()
		if shellWindow is None:
			return []
		return self._extractSelectedPaths(shellWindow)

	def _getSelectedFileSystemItemCount(self):
		try:
			shellWindow = self._getForegroundShellWindow()
			if shellWindow is None:
				return 0
			return len(self._extractStrictSelectedPaths(shellWindow))
		except Exception:
			return 0

	def _copySelectedFileSystemPathsForCopy(
		self,
		requireSelection=True,
		announceAsCopy=False,
	):
		if requireSelection:
			shellWindow = self._getForegroundShellWindow()
			paths = self._extractStrictSelectedPaths(shellWindow) if shellWindow else []
		else:
			paths = self._getSelectedFileSystemPaths()
		if not paths:
			return False
		try:
			self._copyTextToClipboard("\r\n".join(paths))
		except ClipboardAccessError:
			self._announceStatusMessage(
				_("Could not access clipboard"),
				requireAccessProblems=True,
			)
			return True
		if announceAsCopy:
			self._announceExplorerPathCopy(paths)
		else:
			self._announceCopiedFileSystemPaths(paths)
		return True

	def _announceExplorerPathCopy(self, paths):
		if self._shouldUseClipboardAwareness("announceCopy"):
			if self._shouldAnnounceShortcut("announceCopy", "copy"):
				clipboardType = "singleFile" if len(paths) == 1 else "multipleFiles"
				ui.message(
					self._getClipboardAwareMessage(
						"copy",
						{"type": clipboardType, "itemCount": len(paths)},
					)
				)
			return
		if self._shouldAnnounceShortcut("announceCopy", "copy"):
			ui.message(_("Copy"))

	def _announceCopiedFileSystemPaths(self, paths):
		if not self._shouldAnnounceShortcut("announceCopyPath", "copyPath"):
			return
		if len(paths) == 1:
			ui.message(_("Path copied"))
			return
		ui.message(_("Copied %d paths") % len(paths))

	def _extractStrictSelectedPaths(self, shellWindow):
		paths = []
		try:
			selectedItems = shellWindow.Document.SelectedItems()
		except Exception:
			return []

		if not selectedItems:
			return []
		for index in range(selectedItems.Count):
			path = self._getShellItemPath(selectedItems.Item(index))
			if path:
				paths.append(path)
		return paths

	def _extractSelectedPaths(self, shellWindow):
		paths = self._extractStrictSelectedPaths(shellWindow)
		if paths:
			return paths

		try:
			focusedItem = shellWindow.Document.FocusedItem
		except Exception:
			focusedItem = None
		if not focusedItem:
			return []

		path = self._getShellItemPath(focusedItem)
		return [path] if path else []

	def _getShellItemPath(self, shellItem):
		try:
			isFileSystem = shellItem.IsFileSystem
			path = shellItem.Path
		except Exception:
			return None
		if not isFileSystem or not path:
			return None
		return str(path)

	def _copyTextToClipboard(self, text):
		if not wx.TheClipboard.Open():
			raise ClipboardAccessError(_("Could not open the clipboard."))
		try:
			if not wx.TheClipboard.SetData(wx.TextDataObject(text)):
				raise ClipboardAccessError(_("Could not copy text to the clipboard."))
			wx.TheClipboard.Flush()
		finally:
			wx.TheClipboard.Close()

	def _copyFilesToClipboard(self, paths):
		if not wx.TheClipboard.Open():
			raise ClipboardAccessError(_("Could not open the clipboard."))
		try:
			fileData = wx.FileDataObject()
			for path in paths:
				fileData.AddFile(path)
			if not wx.TheClipboard.SetData(fileData):
				raise ClipboardAccessError(_("Could not copy files to the clipboard."))
			wx.TheClipboard.Flush()
		finally:
			wx.TheClipboard.Close()

	def _showClipboardHistory(self):
		if self._clipboardHistoryDialog:
			self._clipboardHistoryDialog.Raise()
			self._clipboardHistoryDialog.focusList()
			return
		self._clipboardHistoryPasteTargetHwnd = GetForegroundWindow()
		dialog = ClipboardHistoryDialog(self, list(self._clipboardHistory))
		self._clipboardHistoryDialog = dialog
		gui.mainFrame.prePopup()
		try:
			gui.runScriptModalDialog(
				dialog,
				lambda result: self._onClipboardHistoryDialogResult(dialog, result),
			)
			dialog.focusList()
		except Exception:
			self._clipboardHistoryDialog = None
			self._clipboardHistoryPasteTargetHwnd = None
			gui.mainFrame.postPopup()
			raise

	def _onClipboardHistoryDialogResult(self, dialog, result):
		try:
			if self._clipboardHistoryDialog is not dialog:
				return
			self._clipboardHistoryDialog = None
			targetHwnd = self._clipboardHistoryPasteTargetHwnd
			self._clipboardHistoryPasteTargetHwnd = None
			if result == wx.ID_OK and dialog.selectedEntry is not None:
				self._selectClipboardHistoryItem(dialog.selectedEntry, targetHwnd)
		finally:
			gui.mainFrame.postPopup()

	def _selectClipboardHistoryItem(self, entry, targetHwnd):
		try:
			if entry["type"] == "files":
				self._copyFilesToClipboard(entry["paths"])
			else:
				self._copyTextToClipboard(entry["text"])
		except (ClipboardAccessError, KeyError):
			self._announceStatusMessage(
				_("Could not access clipboard"),
				requireAccessProblems=True,
			)
			return
		wx.CallLater(100, self._pasteClipboardHistoryItem, targetHwnd)

	def _pasteClipboardHistoryItem(self, targetHwnd):
		if not targetHwnd or not SetForegroundWindow(targetHwnd):
			self._announceStatusMessage(_("Could not return to the original application"))
			return
		try:
			keyboardHandler.KeyboardInputGesture.fromName("control+v").send()
		except Exception:
			self._announceStatusMessage(_("Could not paste clipboard history item"))

	def _getClipboardText(self):
		if not wx.TheClipboard.Open():
			raise ClipboardAccessError(_("Could not open the clipboard."))
		try:
			textData = wx.TextDataObject()
			if not wx.TheClipboard.GetData(textData):
				raise ClipboardAccessError(_("Could not read text from the clipboard."))
			return textData.GetText()
		finally:
			wx.TheClipboard.Close()

	def _openClipboard(self):
		if not OpenClipboard(None):
			raise ClipboardAccessError(_("Could not open the clipboard."))

	def _getClipboardState(self):
		clipboardContentType = self._getClipboardContentType()
		if clipboardContentType == "empty":
			return "empty"
		return "nonEmpty"

	def _getClipboardContentType(self):
		clipboardDetails = self._getClipboardContentDetails()
		return clipboardDetails["type"]

	def _getClipboardContentDetails(self):
		self._openClipboard()
		try:
			if CountClipboardFormats() == 0:
				return {"type": "empty", "itemCount": 0}
			if IsClipboardFormatAvailable(CF_HDROP):
				try:
					return self._getClipboardFileDropDetails()
				except Exception:
					return {"type": "files", "itemCount": 0}
			if (
				IsClipboardFormatAvailable(CF_UNICODETEXT)
				or IsClipboardFormatAvailable(CF_TEXT)
			):
				return {"type": "text", "itemCount": 0}
			if self._hasImageClipboardFormat():
				return {"type": "image", "itemCount": 0}
			return {"type": "generic", "itemCount": 0}
		finally:
			CloseClipboard()

	def _getClipboardFileDropDetails(self):
		dropHandle = GetClipboardData(CF_HDROP)
		if not dropHandle:
			return {"type": "files", "itemCount": 0}
		try:
			fileCount = DragQueryFileW(
				dropHandle,
				0xFFFFFFFF,
				None,
				0,
			)
		except Exception:
			return {"type": "files", "itemCount": 0}
		if fileCount == 1:
			return {"type": "singleFile", "itemCount": 1}
		if fileCount > 1:
			return {"type": "multipleFiles", "itemCount": fileCount}
		return {"type": "files", "itemCount": 0}

	def _hasImageClipboardFormat(self):
		if (
			IsClipboardFormatAvailable(CF_BITMAP)
			or IsClipboardFormatAvailable(CF_DIB)
			or IsClipboardFormatAvailable(CF_DIBV5)
		):
			return True
		pngClipboardFormat = RegisterClipboardFormatW("PNG")
		return bool(
			pngClipboardFormat
			and IsClipboardFormatAvailable(pngClipboardFormat)
		)

	def _getClipboardAwareMessage(
		self,
		actionName,
		clipboardDetails,
		fallbackItemCount=0,
	):
		clipboardContentType = clipboardDetails["type"]
		itemCount = clipboardDetails.get("itemCount", 0)
		resolvedItemCount = itemCount or fallbackItemCount
		if actionName == "copy":
			if resolvedItemCount > 1 and clipboardContentType in ("multipleFiles", "files"):
				return _("Copy %d files") % resolvedItemCount
			return {
				"text": _("Copy text"),
				"singleFile": _("Copy file"),
				"multipleFiles": _("Copy files"),
				"files": _("Copy file") if resolvedItemCount == 1 else _("Copy files"),
				"image": _("Copy image"),
				"generic": _("Copy clipboard content"),
			}.get(clipboardContentType, _("Copy"))
		if actionName == "cut":
			if resolvedItemCount > 1 and clipboardContentType in ("multipleFiles", "files"):
				return _("Cut %d files") % resolvedItemCount
			return {
				"text": _("Cut text"),
				"singleFile": _("Cut file"),
				"multipleFiles": _("Cut files"),
				"files": _("Cut file") if resolvedItemCount == 1 else _("Cut files"),
				"image": _("Cut image"),
				"generic": _("Cut clipboard content"),
			}.get(clipboardContentType, _("Cut"))
		return {
			"text": _("Paste text"),
			"singleFile": _("Paste files"),
			"multipleFiles": _("Paste files"),
			"files": _("Paste files"),
			"image": _("Paste image"),
			"generic": _("Paste clipboard content"),
		}.get(clipboardContentType, _("Paste"))

	def _scheduleClipboardAwareActionAnnouncement(
		self,
		actionName,
		configKey,
		selectedItemCount=0,
		sequenceNumber=_UNSET,
	):
		self._pendingClipboardRetryCount = 0
		if sequenceNumber is _UNSET:
			sequenceNumber = self._getClipboardSequenceNumber()
		self._pendingClipboardSequenceNumber = sequenceNumber
		self._pendingClipboardActionName = actionName
		self._pendingClipboardConfigKey = configKey
		self._pendingClipboardSelectedItemCount = selectedItemCount
		self._pendingClipboardOperation = "announceAction"
		self._pendingClipboardOriginalText = None
		self._scheduleNextClipboardActionAnnouncement(
			CLIPBOARD_COPY_INITIAL_DELAY_MS
		)

	def _queuePendingCopyDispatch(
		self,
		operation,
		actionName,
		configKey,
		selectedItemCount=0,
		sequenceNumber=None,
		originalText=None,
	):
		self._pendingClipboardRetryCount = 0
		self._pendingClipboardSequenceNumber = sequenceNumber
		self._pendingClipboardActionName = actionName
		self._pendingClipboardConfigKey = configKey
		self._pendingClipboardSelectedItemCount = selectedItemCount
		self._pendingClipboardOperation = operation
		self._pendingClipboardOriginalText = originalText
		self._pendingClipboardDispatchRetryCount = 0
		self._schedulePendingCopyDispatch(APPEND_COPY_DISPATCH_DELAY_MS)

	def _schedulePendingCopyDispatch(self, delayMs):
		if self._pendingClipboardDispatch and self._pendingClipboardDispatch.IsRunning():
			self._pendingClipboardDispatch.Stop()
		self._pendingClipboardDispatch = wx.CallLater(
			delayMs,
			self._dispatchPendingCopyAction,
		)

	def _dispatchPendingCopyAction(self):
		self._pendingClipboardDispatch = None
		operation = self._pendingClipboardOperation
		actionName = self._pendingClipboardActionName
		configKey = self._pendingClipboardConfigKey
		if not operation or not actionName or not configKey:
			self._resetPendingClipboardAnnouncementState()
			return
		if self._areModifierKeysDown():
			if (
				self._pendingClipboardDispatchRetryCount
				>= APPEND_COPY_DISPATCH_MAX_RETRIES
			):
				self._dispatchPendingCopyActionIgnoringModifiers()
				return
			self._pendingClipboardDispatchRetryCount += 1
			self._schedulePendingCopyDispatch(APPEND_COPY_DISPATCH_RETRY_MS)
			return
		self._dispatchPendingCopyActionIgnoringModifiers()

	def _dispatchPendingCopyActionIgnoringModifiers(self):
		operation = self._pendingClipboardOperation
		actionName = self._pendingClipboardActionName
		configKey = self._pendingClipboardConfigKey
		if not operation or not actionName or not configKey:
			self._resetPendingClipboardAnnouncementState()
			return
		copyGesture = self._createCopyGesture()
		if self._executeBrowseModeCopyScript(copyGesture):
			self._scheduleNextClipboardActionAnnouncement(
				CLIPBOARD_COPY_INITIAL_DELAY_MS
			)
			return
		try:
			copyGesture.send()
		except Exception:
			if operation == "appendCopy":
				self._restorePendingAppendCopyText()
				self._announceAppendCopyMessage(_("Nothing to append"))
			elif self._shouldAnnounceShortcut(configKey, actionName):
				ui.message(_("Copy"))
			self._resetPendingClipboardAnnouncementState()
			return
		self._scheduleNextClipboardActionAnnouncement(
			CLIPBOARD_COPY_INITIAL_DELAY_MS
		)

	def _areModifierKeysDown(self):
		for virtualKey in (
			VK_SHIFT,
			VK_CONTROL,
			VK_MENU,
			VK_LWIN,
			VK_RWIN,
		):
			try:
				if GetAsyncKeyState(virtualKey) & 0x8000:
					return True
			except Exception:
				continue
		return False

	def _scheduleNextClipboardActionAnnouncement(self, delayMs):
		if (
			self._pendingClipboardAnnouncement
			and self._pendingClipboardAnnouncement.IsRunning()
		):
			self._pendingClipboardAnnouncement.Stop()
		self._pendingClipboardAnnouncement = wx.CallLater(
			delayMs,
			self._announceClipboardAwareActionMessage,
		)

	def _announceClipboardAwareActionMessage(self):
		self._pendingClipboardAnnouncement = None
		if self._isSilenced() and self._pendingClipboardOperation != "appendCopy":
			self._resetPendingClipboardAnnouncementState()
			return
		try:
			clipboardDetails = self._getClipboardContentDetails()
		except ClipboardAccessError:
			self._announceStatusMessage(
				_("Could not access clipboard"),
				requireAccessProblems=True,
			)
			if self._pendingClipboardOperation == "appendCopy":
				self._restorePendingAppendCopyText()
			self._resetPendingClipboardAnnouncementState()
			return
		except Exception:
			actionName = self._pendingClipboardActionName
			configKey = self._pendingClipboardConfigKey
			if self._pendingClipboardOperation == "appendCopy":
				self._restorePendingAppendCopyText()
				self._announceAppendCopyMessage(_("Nothing to append"))
			elif actionName and configKey and self._shouldAnnounceShortcut(configKey, actionName):
				ui.message(_("Copy") if actionName == "copy" else _("Cut"))
			self._resetPendingClipboardAnnouncementState()
			return
		currentSequenceNumber = self._getClipboardSequenceNumber()
		if self._shouldRetryClipboardActionAnnouncement(
			clipboardDetails,
			currentSequenceNumber,
		):
			self._pendingClipboardRetryCount += 1
			self._scheduleNextClipboardActionAnnouncement(
				CLIPBOARD_COPY_RETRY_DELAY_MS
			)
			return
		if self._clipboardDidNotChangeForPendingAction(currentSequenceNumber):
			actionName = self._pendingClipboardActionName
			configKey = self._pendingClipboardConfigKey
			if actionName and configKey and self._shouldAnnounceShortcut(configKey, actionName):
				ui.message(_("Nothing to copy") if actionName == "copy" else _("Nothing to cut"))
			self._resetPendingClipboardAnnouncementState()
			return
		if self._pendingClipboardOperation == "appendCopyFallbackCopy":
			actionName = self._pendingClipboardActionName
			configKey = self._pendingClipboardConfigKey
			fallbackItemCount = self._pendingClipboardSelectedItemCount
			if actionName and configKey and self._shouldAnnounceShortcut(configKey, actionName):
				try:
					message = self._getClipboardAwareMessage(
						actionName,
						clipboardDetails,
						fallbackItemCount=fallbackItemCount,
					)
				except Exception:
					message = _("Copy")
				ui.message(message)
			self._resetPendingClipboardAnnouncementState()
			return
		if self._pendingClipboardOperation == "appendCopy":
			self._completeAppendCopyAnnouncement(
				clipboardDetails,
				currentSequenceNumber,
			)
			return
		actionName = self._pendingClipboardActionName
		configKey = self._pendingClipboardConfigKey
		fallbackItemCount = self._pendingClipboardSelectedItemCount
		if actionName and configKey and self._shouldAnnounceShortcut(configKey, actionName):
			try:
				message = self._getClipboardAwareMessage(
					actionName,
					clipboardDetails,
					fallbackItemCount=fallbackItemCount,
				)
			except Exception:
				message = _("Copy") if actionName == "copy" else _("Cut")
			ui.message(message)
		self._resetPendingClipboardAnnouncementState()

	def _announceClipboardAwarePasteMessage(self, clipboardContentType):
		if clipboardContentType == "empty":
			if self._shouldAnnounceShortcut("announcePaste", "paste"):
				ui.message(_("Paste"))
			return
		if self._shouldAnnounceShortcut("announcePaste", "paste"):
			ui.message(
				self._getClipboardAwareMessage(
					"paste",
					{"type": clipboardContentType, "itemCount": 0},
				)
			)

	def _getClipboardSequenceNumber(self):
		try:
			return GetClipboardSequenceNumber()
		except Exception:
			return None

	def _shouldRetryClipboardActionAnnouncement(
		self,
		clipboardDetails,
		currentSequenceNumber,
	):
		if self._pendingClipboardRetryCount >= CLIPBOARD_COPY_MAX_RETRIES:
			return False
		if (
			self._pendingClipboardOperation == "announceAction"
			and currentSequenceNumber is not None
			and self._pendingClipboardSequenceNumber is not None
		):
			return currentSequenceNumber == self._pendingClipboardSequenceNumber
		if self._pendingClipboardOperation in ("appendCopy", "appendCopyFallbackCopy"):
			if (
				currentSequenceNumber is not None
				and self._pendingClipboardSequenceNumber is not None
			):
				return currentSequenceNumber == self._pendingClipboardSequenceNumber
			return clipboardDetails["type"] == "empty"
		if (
			currentSequenceNumber is not None
			and self._pendingClipboardSequenceNumber is not None
			and currentSequenceNumber != self._pendingClipboardSequenceNumber
		):
			return False
		clipboardContentType = clipboardDetails["type"]
		itemCount = clipboardDetails.get("itemCount", 0)
		return (
			clipboardContentType == "empty"
			or (
				clipboardContentType == "files"
				and itemCount == 0
				and self._pendingClipboardSelectedItemCount > 0
			)
		)

	def _clipboardDidNotChangeForPendingAction(self, currentSequenceNumber):
		return (
			self._pendingClipboardOperation == "announceAction"
			and currentSequenceNumber is not None
			and self._pendingClipboardSequenceNumber is not None
			and currentSequenceNumber == self._pendingClipboardSequenceNumber
		)

	def _resetPendingClipboardAnnouncementState(self):
		self._pendingClipboardRetryCount = 0
		self._pendingClipboardSequenceNumber = None
		self._pendingClipboardActionName = None
		self._pendingClipboardConfigKey = None
		self._pendingClipboardSelectedItemCount = 0
		self._pendingClipboardOperation = None
		self._pendingClipboardOriginalText = None
		self._pendingClipboardDispatchRetryCount = 0
		if self._pendingClipboardDispatch and self._pendingClipboardDispatch.IsRunning():
			self._pendingClipboardDispatch.Stop()
		self._pendingClipboardDispatch = None

	def _announceAppendCopyMessage(self, message):
		if self._shouldAnnounceShortcut("announceAppendCopy", "appendCopy"):
			ui.message(message)

	def _restorePendingAppendCopyText(self):
		originalText = self._pendingClipboardOriginalText
		if originalText is None:
			return False
		try:
			self._copyTextToClipboard(originalText)
		except ClipboardAccessError:
			return False
		return True

	def _completeAppendCopyAnnouncement(
		self,
		clipboardDetails,
		currentSequenceNumber,
	):
		sequenceChanged = (
			currentSequenceNumber is not None
			and self._pendingClipboardSequenceNumber is not None
			and currentSequenceNumber != self._pendingClipboardSequenceNumber
		)
		if not sequenceChanged:
			self._restorePendingAppendCopyText()
			self._announceAppendCopyMessage(_("Nothing to append"))
			self._resetPendingClipboardAnnouncementState()
			return
		if clipboardDetails["type"] != "text":
			self._restorePendingAppendCopyText()
			self._announceAppendCopyMessage(_("Only copied text can be appended"))
			self._resetPendingClipboardAnnouncementState()
			return
		try:
			newText = self._getClipboardText()
		except ClipboardAccessError:
			self._restorePendingAppendCopyText()
			self._announceStatusMessage(
				_("Could not access clipboard"),
				requireAccessProblems=True,
			)
			self._resetPendingClipboardAnnouncementState()
			return
		if not newText:
			self._restorePendingAppendCopyText()
			self._announceAppendCopyMessage(_("Nothing to append"))
			self._resetPendingClipboardAnnouncementState()
			return
		originalText = self._pendingClipboardOriginalText or ""
		try:
			self._copyTextToClipboard(originalText + newText)
		except ClipboardAccessError:
			self._restorePendingAppendCopyText()
			self._announceStatusMessage(
				_("Could not access clipboard"),
				requireAccessProblems=True,
			)
			self._resetPendingClipboardAnnouncementState()
			return
		self._announceAppendCopyMessage(_("Copied text appended"))
		self._resetPendingClipboardAnnouncementState()

	def _clearClipboard(self):
		self._openClipboard()
		try:
			if CountClipboardFormats() == 0:
				raise ClipboardEmptyError(_("Clipboard is already empty."))
			if not EmptyClipboard():
				raise OSError(_("Could not empty the clipboard."))
		finally:
			CloseClipboard()

	def _performClipboardClear(self):
		try:
			self._clearClipboard()
		except ClipboardEmptyError:
			self._announceStatusMessage(
				_("Clipboard is already empty"),
				requireClearResult=True,
			)
			return
		except ClipboardAccessError:
			self._announceStatusMessage(
				_("Could not access clipboard"),
				requireClearResult=True,
				requireAccessProblems=True,
			)
			return
		except OSError:
			self._announceStatusMessage(
				_("Could not clear clipboard"),
				requireClearResult=True,
			)
			return
		self._announceStatusMessage(
			_("Clipboard cleared"),
			requireClearResult=True,
		)

	def _handleConfirmedClipboardClear(self):
		try:
			clipboardState = self._getClipboardState()
		except ClipboardAccessError:
			self._announceStatusMessage(
				_("Could not access clipboard"),
				requireClearResult=True,
				requireAccessProblems=True,
			)
			return
		if clipboardState == "empty":
			self._announceStatusMessage(
				_("Clipboard is already empty"),
				requireClearResult=True,
			)
			return
		self._performClipboardClear()

	def _onClearClipboardConfirmationResult(self, result):
		try:
			if result == wx.ID_YES:
				self._handleConfirmedClipboardClear()
		finally:
			self._clearConfirmationDialogOpen = False

	def _showClearClipboardConfirmation(self):
		if self._clearConfirmationDialogOpen:
			return
		self._clearConfirmationDialogOpen = True
		dialog = wx.MessageDialog(
			gui.mainFrame,
			_("Are you sure you want to clear the clipboard?"),
			_("Clipboard Announcer"),
			wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
		)
		gui.runScriptModalDialog(dialog, self._onClearClipboardConfirmationResult)

	def _openClipboardHistoryAfterShortcutDelay(self):
		self._clipboardHistoryShortcutTimer = None
		self._showClipboardHistory()

	def _handleClipboardHistoryShortcut(self):
		if self._clipboardHistoryShortcutTimer:
			if self._clipboardHistoryShortcutTimer.IsRunning():
				self._clipboardHistoryShortcutTimer.Stop()
			self._clipboardHistoryShortcutTimer = None
			self._requestClipboardClear()
			return
		self._clipboardHistoryShortcutTimer = wx.CallLater(
			CLIPBOARD_HISTORY_DOUBLE_PRESS_WINDOW_MS,
			self._openClipboardHistoryAfterShortcutDelay,
		)

	def _requestClipboardClear(self):
		try:
			clipboardState = self._getClipboardState()
		except ClipboardAccessError:
			self._announceStatusMessage(
				_("Could not access clipboard"),
				requireClearResult=True,
				requireAccessProblems=True,
			)
			return
		if clipboardState == "empty":
			self._announceStatusMessage(
				_("Clipboard is already empty"),
				requireClearResult=True,
			)
			return
		if _getConfig()["confirmBeforeClear"]:
			self._showClearClipboardConfirmation()
			return
		self._performClipboardClear()

	@script(
		description=_("Open the Clipboard Announcer settings panel."),
		speakOnDemand=True,
	)
	def script_openClipboardAnnouncerSettings(self, gesture):
		wx.CallAfter(_openSettingsPanel)

	@script(
		description=_("Temporarily disable or enable Clipboard Announcer."),
		gesture="kb:control+shift+s",
		speakOnDemand=True,
	)
	def script_toggleTemporarySilence(self, gesture):
		if not self._shouldAnnounceTemporarySilenceStatus():
			ui.message(
				_("Spoken shortcut feedback is currently disabled")
			)
			return
		self._silenceModeEnabled = not self._silenceModeEnabled
		if self._silenceModeEnabled:
			ui.message(_("Clipboard Announcer temporarily disabled"))
			return
		ui.message(_("Clipboard Announcer enabled"))

	@script(
		description=_("Copy the selected file or folder path."),
		gesture="kb:control+shift+c",
		speakOnDemand=True,
	)
	def script_copySelectedPath(self, gesture):
		if not self._copySelectedFileSystemPathsForCopy(requireSelection=False):
			gesture.send()

	@script(
		description=_("Announce Copy."),
		gesture="kb:control+c",
		speakOnDemand=True,
	)
	def script_announceCopy(self, gesture):
		self._announceCopyAndPassThrough(gesture)

	@script(
		description=_("Append newly copied text to the existing clipboard text."),
		speakOnDemand=True,
	)
	def script_appendCopiedText(self, gesture):
		self._appendCopyAndPassThrough(gesture)

	@script(
		description=_("Announce Cut."),
		gesture="kb:control+x",
		speakOnDemand=True,
	)
	def script_announceCut(self, gesture):
		self._announceCutAndPassThrough(gesture)

	@script(
		description=_("Announce Paste."),
		gesture="kb:control+v",
		speakOnDemand=True,
	)
	def script_announcePaste(self, gesture):
		self._announcePasteAndPassThrough(gesture)

	@script(
		description=_("Announce Select All."),
		gesture="kb:control+a",
		speakOnDemand=True,
	)
	def script_announceSelectAll(self, gesture):
		self._announceAndPassThrough(
			gesture, _("Select all"), "announceSelectAll", "selectAll"
		)

	@script(
		description=_("Announce Undo."),
		gesture="kb:control+z",
		speakOnDemand=True,
	)
	def script_announceUndo(self, gesture):
		self._announceAndPassThrough(gesture, _("Undo"), "announceUndo", "undo")

	@script(
		description=_("Announce Redo."),
		gesture="kb:control+y",
		speakOnDemand=True,
	)
	def script_announceRedo(self, gesture):
		self._announceAndPassThrough(gesture, _("Redo"), "announceRedo", "redo")

	@script(
		description=_("Open clipboard history. Press twice quickly to clear the clipboard."),
		gesture="kb:control+shift+x",
		speakOnDemand=True,
	)
	def script_clearClipboard(self, gesture):
		if not _getConfig()["clipboardHistoryEnabled"]:
			self._requestClipboardClear()
			return
		self._handleClipboardHistoryShortcut()
