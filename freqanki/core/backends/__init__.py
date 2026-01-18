"""
Translation backend system for FreqAnki.

Provides a pluggable architecture for different translation services:
- DeepL (premium, requires API key)
- Qwen3 via Ollama (LLM-based, local)
- Argos Translate (fast, offline)

Usage:
    from freqanki.core.backends import get_backend, BackendType

    backend = get_backend(BackendType.AUTO)  # Auto-select best available
    translations = backend.translate_words(words, "ru", "en")
"""

from freqanki.core.backends.base import TranslationBackend, BackendType
from freqanki.core.backends.deepl import DeepLBackend
from freqanki.core.backends.qwen import QwenBackend
from freqanki.core.backends.argos import ArgosBackend
from freqanki.core.backends.factory import (
    get_backend,
    get_available_backends,
    list_backends,
    print_backend_status,
)

__all__ = [
    "TranslationBackend",
    "BackendType",
    "DeepLBackend",
    "QwenBackend",
    "ArgosBackend",
    "get_backend",
    "get_available_backends",
    "list_backends",
    "print_backend_status",
]
