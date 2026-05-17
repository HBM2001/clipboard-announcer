# -*- coding: UTF-8 -*-
# A simple NVDA global plugin that announces common editing shortcuts.

import ctypes
import time

import addonHandler
import api
import config
import globalPluginHandler
import gui
import scriptHandler
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
HDROP = ctypes.c_void_p
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
	"announceCopyPath": "boolean(default=True)",
	"clipboardContentAwareness": "boolean(default=False)",
	"announceClearResult": "boolean(default=True)",
	"confirmBeforeClear": "boolean(default=False)",
	"warnOnEmptyPaste": "boolean(default=False)",
	"announceClipboardAccessProblems": "boolean(default=True)",
}


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
			wx.CheckBox(self, label=_("Speak when these shortcuts are pressed"))
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
		self.announceCopyPathCheckbox = wx.CheckBox(self, label=_("Announce Copy Path"))
		self.clipboardContentAwarenessCheckbox = wx.CheckBox(
			self, label=_("Use clipboard content awareness for Copy and Paste")
		)

		self.announceCopyCheckbox.SetValue(conf["announceCopy"])
		self.announceCutCheckbox.SetValue(conf["announceCut"])
		self.announcePasteCheckbox.SetValue(conf["announcePaste"])
		self.announceSelectAllCheckbox.SetValue(conf["announceSelectAll"])
		self.announceUndoCheckbox.SetValue(conf["announceUndo"])
		self.announceRedoCheckbox.SetValue(conf["announceRedo"])
		self.announceCopyPathCheckbox.SetValue(conf["announceCopyPath"])
		self.clipboardContentAwarenessCheckbox.SetValue(conf["clipboardContentAwareness"])

		for checkbox in (
			self.announceCopyCheckbox,
			self.announceCutCheckbox,
			self.announcePasteCheckbox,
			self.announceSelectAllCheckbox,
			self.announceUndoCheckbox,
			self.announceRedoCheckbox,
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
		self.warnOnEmptyPasteCheckbox = wx.CheckBox(
			self, label=_("Warn if you try to paste when the clipboard is empty")
		)
		self.warnOnEmptyPasteCheckbox.SetValue(conf["warnOnEmptyPaste"])
		self.announceClipboardAccessProblemsCheckbox = wx.CheckBox(
			self, label=_("Speak an error if the clipboard cannot be accessed")
		)
		self.announceClipboardAccessProblemsCheckbox.SetValue(
			conf["announceClipboardAccessProblems"]
		)

		for checkbox in (
			self.warnOnEmptyPasteCheckbox,
			self.announceClipboardAccessProblemsCheckbox,
		):
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
		conf["announceCopyPath"] = self.announceCopyPathCheckbox.GetValue()
		conf["clipboardContentAwareness"] = (
			self.clipboardContentAwarenessCheckbox.GetValue()
		)
		conf["announceClearResult"] = self.announceClearResultCheckbox.GetValue()
		conf["confirmBeforeClear"] = self.confirmBeforeClearCheckbox.GetValue()
		conf["warnOnEmptyPaste"] = self.warnOnEmptyPasteCheckbox.GetValue()
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
		self._pendingCopyAnnouncement = None
		self._pendingCopyRetryCount = 0
		self._pendingCopyClipboardSequenceNumber = None
		self._registerConfig()
		self._registerSettingsPanel()

	def terminate(self):
		if self._pendingCopyAnnouncement and self._pendingCopyAnnouncement.IsRunning():
			self._pendingCopyAnnouncement.Stop()
		self._pendingCopyAnnouncement = None
		self._pendingCopyRetryCount = 0
		self._pendingCopyClipboardSequenceNumber = None
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
		if self._executeBrowseModeCopyScript(gesture):
			if self._shouldUseClipboardContentAwareness("announceCopy"):
				self._scheduleClipboardCopyAnnouncement()
			elif self._shouldAnnounceShortcut("announceCopy", "copy"):
				ui.message(_("Copy"))
			return
		try:
			if (
				not self._shouldUseClipboardContentAwareness("announceCopy")
				and self._shouldAnnounceShortcut("announceCopy", "copy")
			):
				ui.message(_("Copy"))
		finally:
			gesture.send()
		if self._shouldUseClipboardContentAwareness("announceCopy"):
			self._scheduleClipboardCopyAnnouncement()

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
			conf = _getConfig()
			try:
				clipboardContentType = self._getClipboardContentType()
			except ClipboardAccessError:
				self._announceStatusMessage(
					_("Could not access clipboard"),
					requireAccessProblems=True,
				)
				return
			if clipboardContentType == "empty" and conf["warnOnEmptyPaste"]:
				self._announceStatusMessage(_("Nothing to paste"))
				return
			if self._shouldUseClipboardContentAwareness("announcePaste"):
				self._announceClipboardAwarePasteMessage(clipboardContentType)
			elif self._shouldAnnounceShortcut("announcePaste", "paste"):
				ui.message(_("Paste"))
		finally:
			gesture.send()

	def _shouldUseClipboardContentAwareness(self, configKey):
		conf = _getConfig()
		return (
			conf["clipboardContentAwareness"]
			and conf["announcementsEnabled"]
			and conf[configKey]
		)

	def _shouldAnnounceShortcut(self, configKey, actionName):
		conf = _getConfig()
		if not conf["announcementsEnabled"] or not conf[configKey]:
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

	def _getSelectedFileSystemPaths(self):
		try:
			from comtypes import client as comtypesClient
		except ImportError:
			return []

		foregroundHwnd = ctypes.windll.user32.GetForegroundWindow()
		if not foregroundHwnd:
			return []

		try:
			shell = comtypesClient.CreateObject("Shell.Application", dynamic=True)
			windows = shell.Windows()
		except Exception:
			return []

		for index in range(windows.Count):
			try:
				window = windows.Item(index)
				if int(window.HWND) != foregroundHwnd:
					continue
				selectedPaths = self._extractSelectedPaths(window)
				if selectedPaths:
					return selectedPaths
			except Exception:
				continue
		return []

	def _extractSelectedPaths(self, shellWindow):
		paths = []
		try:
			selectedItems = shellWindow.Document.SelectedItems()
		except Exception:
			selectedItems = None

		if selectedItems:
			for index in range(selectedItems.Count):
				path = self._getShellItemPath(selectedItems.Item(index))
				if path:
					paths.append(path)
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

	def _openClipboard(self):
		if not ctypes.windll.user32.OpenClipboard(None):
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
			if ctypes.windll.user32.CountClipboardFormats() == 0:
				return {"type": "empty", "itemCount": 0}
			if ctypes.windll.user32.IsClipboardFormatAvailable(CF_HDROP):
				return self._getClipboardFileDropDetails()
			if (
				ctypes.windll.user32.IsClipboardFormatAvailable(CF_UNICODETEXT)
				or ctypes.windll.user32.IsClipboardFormatAvailable(CF_TEXT)
			):
				return {"type": "text", "itemCount": 0}
			if self._hasImageClipboardFormat():
				return {"type": "image", "itemCount": 0}
			return {"type": "generic", "itemCount": 0}
		finally:
			ctypes.windll.user32.CloseClipboard()

	def _getClipboardFileDropDetails(self):
		dropHandle = ctypes.windll.user32.GetClipboardData(CF_HDROP)
		if not dropHandle:
			return {"type": "files", "itemCount": 0}
		fileCount = ctypes.windll.shell32.DragQueryFileW(
			HDROP(dropHandle),
			0xFFFFFFFF,
			None,
			0,
		)
		if fileCount == 1:
			return {"type": "singleFile", "itemCount": 1}
		if fileCount > 1:
			return {"type": "multipleFiles", "itemCount": fileCount}
		return {"type": "files", "itemCount": 0}

	def _hasImageClipboardFormat(self):
		if (
			ctypes.windll.user32.IsClipboardFormatAvailable(CF_BITMAP)
			or ctypes.windll.user32.IsClipboardFormatAvailable(CF_DIB)
			or ctypes.windll.user32.IsClipboardFormatAvailable(CF_DIBV5)
		):
			return True
		pngClipboardFormat = ctypes.windll.user32.RegisterClipboardFormatW("PNG")
		return bool(
			pngClipboardFormat
			and ctypes.windll.user32.IsClipboardFormatAvailable(pngClipboardFormat)
		)

	def _getClipboardAwareMessage(self, actionName, clipboardContentType):
		if actionName == "copy":
			return {
				"text": _("Copy text"),
				"singleFile": _("Copy file"),
				"multipleFiles": _("Copy files"),
				"files": _("Copy files"),
				"image": _("Copy image"),
				"generic": _("Copy clipboard content"),
			}.get(clipboardContentType, _("Copy"))
		return {
			"text": _("Paste text"),
			"files": _("Paste files"),
			"image": _("Paste image"),
			"generic": _("Paste clipboard content"),
		}.get(clipboardContentType, _("Paste"))

	def _scheduleClipboardCopyAnnouncement(self):
		self._pendingCopyRetryCount = 0
		self._pendingCopyClipboardSequenceNumber = self._getClipboardSequenceNumber()
		self._scheduleNextClipboardCopyAnnouncement(
			CLIPBOARD_COPY_INITIAL_DELAY_MS
		)

	def _scheduleNextClipboardCopyAnnouncement(self, delayMs):
		if self._pendingCopyAnnouncement and self._pendingCopyAnnouncement.IsRunning():
			self._pendingCopyAnnouncement.Stop()
		self._pendingCopyAnnouncement = wx.CallLater(
			delayMs,
			self._announceClipboardAwareCopyMessage,
		)

	def _announceClipboardAwareCopyMessage(self):
		self._pendingCopyAnnouncement = None
		try:
			clipboardDetails = self._getClipboardContentDetails()
		except ClipboardAccessError:
			self._announceStatusMessage(
				_("Could not access clipboard"),
				requireAccessProblems=True,
			)
			return
		clipboardContentType = clipboardDetails["type"]
		if self._shouldRetryClipboardCopyAnnouncement(clipboardContentType):
			self._pendingCopyRetryCount += 1
			self._scheduleNextClipboardCopyAnnouncement(
				CLIPBOARD_COPY_RETRY_DELAY_MS
			)
			return
		if self._shouldAnnounceShortcut("announceCopy", "copy"):
			ui.message(self._getClipboardAwareMessage("copy", clipboardContentType))
		self._pendingCopyRetryCount = 0
		self._pendingCopyClipboardSequenceNumber = None

	def _announceClipboardAwarePasteMessage(self, clipboardContentType):
		if clipboardContentType == "empty":
			if self._shouldAnnounceShortcut("announcePaste", "paste"):
				ui.message(_("Paste"))
			return
		if self._shouldAnnounceShortcut("announcePaste", "paste"):
			ui.message(self._getClipboardAwareMessage("paste", clipboardContentType))

	def _getClipboardSequenceNumber(self):
		try:
			return ctypes.windll.user32.GetClipboardSequenceNumber()
		except Exception:
			return None

	def _shouldRetryClipboardCopyAnnouncement(self, clipboardContentType):
		if self._pendingCopyRetryCount >= CLIPBOARD_COPY_MAX_RETRIES:
			return False
		currentSequenceNumber = self._getClipboardSequenceNumber()
		if (
			currentSequenceNumber is not None
			and self._pendingCopyClipboardSequenceNumber is not None
			and currentSequenceNumber != self._pendingCopyClipboardSequenceNumber
		):
			return False
		return clipboardContentType == "empty"

	def _clearClipboard(self):
		self._openClipboard()
		try:
			if ctypes.windll.user32.CountClipboardFormats() == 0:
				raise ClipboardEmptyError(_("Clipboard is already empty."))
			if not ctypes.windll.user32.EmptyClipboard():
				raise OSError(_("Could not empty the clipboard."))
		finally:
			ctypes.windll.user32.CloseClipboard()

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
		description=_("Announce Cut."),
		gesture="kb:control+x",
		speakOnDemand=True,
	)
	def script_announceCut(self, gesture):
		self._announceAndPassThrough(gesture, _("Cut"), "announceCut", "cut")

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
