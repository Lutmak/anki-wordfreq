"""Language module registry for dynamic language support."""

from freqanki.languages.base import LanguageModule, MorphologyInfo


class GenericModule(LanguageModule):
    """Generic language module with minimal support."""

    has_full_support = False

    def __init__(
        self,
        code: str,
        name: str,
        tatoeba_code: str,
        deepl_code: str | None = None,
    ) -> None:
        self.code = code
        self.name = name
        self.wordfreq_code = code
        self.tatoeba_code = tatoeba_code
        self.deepl_code = deepl_code or code.upper()

    def is_valid_token(self, word: str) -> bool:
        """Accept all non-empty tokens."""
        return bool((word or "").strip())

    def get_romanization(self, word: str) -> str | None:
        """No romanization for generic modules."""
        return None

    def get_morphology(self, word: str) -> MorphologyInfo | None:
        """No morphology for generic modules."""
        return None


# Registry of available language modules
_LANGUAGE_MODULES: dict[str, type[LanguageModule] | LanguageModule] = {}

# Languages supported by wordfreq (all 40)
WORDFREQ_LANGUAGES = {
    "ar": ("Arabic", "ara", "AR"),
    "bg": ("Bulgarian", "bul", "BG"),
    "bn": ("Bengali", "ben", None),
    "ca": ("Catalan", "cat", None),
    "cs": ("Czech", "ces", "CS"),
    "da": ("Danish", "dan", "DA"),
    "de": ("German", "deu", "DE"),
    "el": ("Greek", "ell", "EL"),
    "en": ("English", "eng", "EN"),
    "es": ("Spanish", "spa", "ES"),
    "et": ("Estonian", "est", "ET"),
    "fa": ("Persian", "pes", None),
    "fi": ("Finnish", "fin", "FI"),
    "fr": ("French", "fra", "FR"),
    "he": ("Hebrew", "heb", None),
    "hi": ("Hindi", "hin", None),
    "hr": ("Croatian", "hrv", None),
    "hu": ("Hungarian", "hun", "HU"),
    "id": ("Indonesian", "ind", "ID"),
    "is": ("Icelandic", "isl", None),
    "it": ("Italian", "ita", "IT"),
    "ja": ("Japanese", "jpn", "JA"),
    "ko": ("Korean", "kor", "KO"),
    "lt": ("Lithuanian", "lit", "LT"),
    "lv": ("Latvian", "lvs", "LV"),
    "mk": ("Macedonian", "mkd", None),
    "ms": ("Malay", "zsm", None),
    "nb": ("Norwegian Bokmal", "nob", "NB"),
    "nl": ("Dutch", "nld", "NL"),
    "pl": ("Polish", "pol", "PL"),
    "pt": ("Portuguese", "por", "PT"),
    "ro": ("Romanian", "ron", "RO"),
    "ru": ("Russian", "rus", "RU"),
    "sk": ("Slovak", "slk", "SK"),
    "sl": ("Slovenian", "slv", "SL"),
    "sr": ("Serbian", "srp", None),
    "sv": ("Swedish", "swe", "SV"),
    "th": ("Thai", "tha", None),
    "tr": ("Turkish", "tur", "TR"),
    "uk": ("Ukrainian", "ukr", "UK"),
    "vi": ("Vietnamese", "vie", None),
    "zh": ("Chinese", "cmn", "ZH"),
}


def _register_builtin_modules() -> None:
    """Register all built-in language modules."""
    # Import specialized modules
    from freqanki.languages.russian import RussianModule

    # Register specialized modules
    _LANGUAGE_MODULES["ru"] = RussianModule

    # Register generic modules for all other languages
    for code, (name, tatoeba, deepl) in WORDFREQ_LANGUAGES.items():
        if code not in _LANGUAGE_MODULES:
            _LANGUAGE_MODULES[code] = GenericModule(code, name, tatoeba, deepl)


def get_language_module(code: str) -> LanguageModule:
    """
    Get the language module for a given language code.

    Args:
        code: ISO 639-1 language code (e.g., "ru", "en", "zh")

    Returns:
        LanguageModule instance for the language

    Raises:
        ValueError: If language code is not supported
    """
    if not _LANGUAGE_MODULES:
        _register_builtin_modules()

    if code not in _LANGUAGE_MODULES:
        raise ValueError(
            f"Unsupported language: {code}. "
            f"Supported languages: {', '.join(sorted(_LANGUAGE_MODULES.keys()))}"
        )

    module = _LANGUAGE_MODULES[code]

    # If it's a class, instantiate it
    if isinstance(module, type):
        module = module()
        _LANGUAGE_MODULES[code] = module

    return module


def list_supported_languages() -> list[tuple[str, str, bool]]:
    """
    List all supported languages.

    Returns:
        List of (code, name, has_full_support) tuples
    """
    if not _LANGUAGE_MODULES:
        _register_builtin_modules()

    result = []
    for code in sorted(_LANGUAGE_MODULES.keys()):
        module = get_language_module(code)
        result.append((code, module.name, module.has_full_support))

    return result


def is_language_supported(code: str) -> bool:
    """Check if a language code is supported."""
    if not _LANGUAGE_MODULES:
        _register_builtin_modules()
    return code in _LANGUAGE_MODULES
