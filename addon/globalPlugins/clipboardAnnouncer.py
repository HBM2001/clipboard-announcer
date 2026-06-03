# -*- coding: UTF-8 -*-
# A simple NVDA global plugin that announces common editing shortcuts.

import ctypes
from ctypes import wintypes
import time

import addonHandler
import api
import config
import globalPluginHandler
import gui
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
CF_TEXT = 1
CF_BITMAP = 2
CF_DIB = 8
CF_HDROP = 15
CF_UNICODETEXT = 13
CF_DIBV5 = 17
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
}

_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_SHELL32 = ctypes.WinDLL("shell32", use_last_error=True)

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


class ClipboardEmptyError(RuntimeError):
	pass


class ClipboardAccessError(RuntimeError):
	pass


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
		self._registerConfig()
		self._registerSettingsPanel()

	def terminate(self):
		if (
			self._pendingClipboardAnnouncement
			and self._pendingClipboardAnnouncement.IsRunning()
		):
			self._pendingClipboardAnnouncement.Stop()
		self._pendingClipboardAnnouncement = None
		self._pendingClipboardRetryCount = 0
		self._pendingClipboardSequenceNumber = None
		self._pendingClipboardActionName = None
		self._pendingClipboardConfigKey = None
		self._pendingClipboardSelectedItemCount = 0
		self._pendingClipboardOperation = None
		self._pendingClipboardOriginalText = None
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

	def _announceAndPassThrough(self, gesture, message, configKey, actionName):
		try:
			if self._shouldAnnounceShortcut(configKey, actionName):
				ui.message(message)
		finally:
			gesture.send()

	def _announceCopyAndPassThrough(self, gesture):
		contextMessage = self._getContextAwareShortcutMessage("announceCopy", "copy")
		selectedItemCount = self._getSelectedFileSystemItemCount()
		if self._executeBrowseModeCopyScript(gesture):
			if contextMessage:
				self._announceStatusMessage(contextMessage)
				return
			if self._shouldUseClipboardAwareness("announceCopy"):
				self._scheduleClipboardAwareActionAnnouncement(
					"copy",
					"announceCopy",
					selectedItemCount=selectedItemCount,
				)
			elif self._shouldAnnounceShortcut("announceCopy", "copy"):
				ui.message(_("Copy"))
			return
		try:
			if contextMessage:
				self._announceStatusMessage(contextMessage)
			elif (
				not self._shouldUseClipboardAwareness("announceCopy")
				and self._shouldAnnounceShortcut("announceCopy", "copy")
			):
				ui.message(_("Copy"))
		finally:
			gesture.send()
		if contextMessage:
			return
		if self._shouldUseClipboardAwareness("announceCopy"):
			self._scheduleClipboardAwareActionAnnouncement(
				"copy",
				"announceCopy",
				selectedItemCount=selectedItemCount,
			)

	def _announceCutAndPassThrough(self, gesture):
		contextMessage = self._getContextAwareShortcutMessage("announceCut", "cut")
		selectedItemCount = self._getSelectedFileSystemItemCount()
		try:
			if contextMessage:
				self._announceStatusMessage(contextMessage)
			elif not self._shouldUseClipboardAwareness("announceCut") and self._shouldAnnounceShortcut(
				"announceCut", "cut"
			):
				ui.message(_("Cut"))
		finally:
			gesture.send()
		if contextMessage:
			return
		if self._shouldUseClipboardAwareness("announceCut"):
			self._scheduleClipboardAwareActionAnnouncement(
				"cut",
				"announceCut",
				selectedItemCount=selectedItemCount,
			)

	def _appendCopyAndPassThrough(self, gesture):
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
			self._announceCopyAndPassThrough(gesture)
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
		if self._executeBrowseModeCopyScript(gesture):
			self._scheduleAppendCopyAnnouncement(
				originalText,
				selectedItemCount,
				clipboardSequenceNumber,
			)
			return
		gesture.send()
		self._scheduleAppendCopyAnnouncement(
			originalText,
			selectedItemCount,
			clipboardSequenceNumber,
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
	):
		self._pendingClipboardRetryCount = 0
		self._pendingClipboardSequenceNumber = self._getClipboardSequenceNumber()
		self._pendingClipboardActionName = actionName
		self._pendingClipboardConfigKey = configKey
		self._pendingClipboardSelectedItemCount = selectedItemCount
		self._pendingClipboardOperation = "announceAction"
		self._pendingClipboardOriginalText = None
		self._scheduleNextClipboardActionAnnouncement(
			CLIPBOARD_COPY_INITIAL_DELAY_MS
		)

	def _scheduleAppendCopyAnnouncement(
		self,
		originalText,
		selectedItemCount=0,
		sequenceNumber=None,
	):
		self._pendingClipboardRetryCount = 0
		self._pendingClipboardSequenceNumber = sequenceNumber
		self._pendingClipboardActionName = "appendCopy"
		self._pendingClipboardConfigKey = "announceAppendCopy"
		self._pendingClipboardSelectedItemCount = selectedItemCount
		self._pendingClipboardOperation = "appendCopy"
		self._pendingClipboardOriginalText = originalText
		self._scheduleNextClipboardActionAnnouncement(
			CLIPBOARD_COPY_INITIAL_DELAY_MS
		)

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
		if self._pendingClipboardOperation == "appendCopy":
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

	def _resetPendingClipboardAnnouncementState(self):
		self._pendingClipboardRetryCount = 0
		self._pendingClipboardSequenceNumber = None
		self._pendingClipboardActionName = None
		self._pendingClipboardConfigKey = None
		self._pendingClipboardSelectedItemCount = 0
		self._pendingClipboardOperation = None
		self._pendingClipboardOriginalText = None

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
		paths = self._getSelectedFileSystemPaths()
		if not paths:
			gesture.send()
			return

		try:
			self._copyTextToClipboard("\r\n".join(paths))
		except ClipboardAccessError:
			self._announceStatusMessage(
				_("Could not access clipboard"),
				requireAccessProblems=True,
			)
			return

		if not self._shouldAnnounceShortcut("announceCopyPath", "copyPath"):
			return
		if len(paths) == 1:
			ui.message(_("Path copied"))
			return
		ui.message(_("Copied %d paths") % len(paths))

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
		description=_("Clear Clipboard."),
		gesture="kb:control+shift+x",
		speakOnDemand=True,
	)
	def script_clearClipboard(self, gesture):
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
