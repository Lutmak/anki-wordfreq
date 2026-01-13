"""Language-specific modules for FreqAnki."""

from freqanki.languages.base import LanguageModule
from freqanki.languages.registry import get_language_module, list_supported_languages

__all__ = ["LanguageModule", "get_language_module", "list_supported_languages"]
