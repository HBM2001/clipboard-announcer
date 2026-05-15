# Build customizations
# Change this file instead of sconstruct or manifest files, whenever possible.

from site_scons.site_tools.NVDATool.typings import AddonInfo, BrailleTables, SpeechDictionaries, SymbolDictionaries

# Since some strings in `addon_info` are translatable,
# we need to include them in the .po files.
# Gettext recognizes only strings given as parameters to the `_` function.
# To avoid initializing translations in this module we simply import a "fake" `_` function
# which returns whatever is given to it as an argument.
from site_scons.site_tools.NVDATool.utils import _


addon_info = AddonInfo(
	addon_name="clipboardAnnouncer",
	# Translators: Summary/title for this add-on shown in install dialogs and the add-on store.
	addon_summary=_("Clipboard Announcer"),
	# Translators: Description shown for this add-on in the add-on store.
	addon_description=_("Provides spoken feedback for common editing and clipboard actions."),
	addon_version="1.2",
	# Translators: Changelog text shown for this version in the add-on store.
	addon_changelog=_(
		"No user-facing feature changes. Project packaging and metadata were standardized for future releases."
	),
	addon_author="H2k1",
	addon_url="https://github.com/HBM2001/clipboard-announcer",
	addon_sourceURL="https://github.com/HBM2001/clipboard-announcer",
	addon_docFileName="readme.html",
	addon_minimumNVDAVersion="2024.1",
	addon_lastTestedNVDAVersion="2026.1",
	addon_updateChannel=None,
	addon_license="GPL v2",
	addon_licenseURL="https://www.gnu.org/licenses/old-licenses/gpl-2.0.html",
)

pythonSources: list[str] = [
	"addon/globalPlugins/*.py",
]

i18nSources: list[str] = pythonSources + ["buildVars.py"]

# Keep source markdown docs out of the packaged add-on.
excludedFiles: list[str] = [
	"doc/*/*.md",
]

baseLanguage: str = "en"

markdownExtensions: list[str] = []

brailleTables: BrailleTables = {}

symbolDictionaries: SymbolDictionaries = {}

speechDictionaries: SpeechDictionaries = {}
