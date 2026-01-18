"""Registry for language-specific translation hints."""

from typing import Callable
import importlib
import pkgutil


# Registry mapping language codes to hints strings
_hints_registry: dict[str, str] = {}


def register_hints(lang_code: str, hints: str) -> None:
    """
    Register hints for a language.

    Args:
        lang_code: ISO 639-1 language code (e.g., 'ru', 'ja')
        hints: Multi-line string with guidance for translators
    """
    _hints_registry[lang_code] = hints


def get_hints(lang_code: str) -> str | None:
    """
    Get hints for a language.

    First checks the registry, then tries to auto-load from a
    language-specific module.

    Args:
        lang_code: ISO 639-1 language code

    Returns:
        Hints string if available, None otherwise.
    """
    # Check if already registered
    if lang_code in _hints_registry:
        return _hints_registry[lang_code]

    # Try to auto-load from module
    try:
        module = importlib.import_module(f"freqanki.languages.translation_hints.{lang_code}")
        hints = getattr(module, "HINTS", None)
        if hints:
            _hints_registry[lang_code] = hints
            return hints
    except ImportError:
        pass

    return None


def list_available_hints() -> list[str]:
    """
    List language codes that have hints available.

    Returns:
        List of language codes with hints.
    """
    # Start with registered hints
    available = set(_hints_registry.keys())

    # Discover hint modules
    try:
        package = importlib.import_module("freqanki.languages.translation_hints")
        for _, name, _ in pkgutil.iter_modules(package.__path__):
            if name not in ("__init__", "registry"):
                available.add(name)
    except Exception:
        pass

    return sorted(available)
