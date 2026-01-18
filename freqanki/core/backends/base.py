"""Abstract base class for translation backends."""

from abc import ABC, abstractmethod

# Import BackendType from config to avoid duplication
from freqanki.config import BackendType


class TranslationBackend(ABC):
    """
    Abstract base class for translation backends.

    All translation backends must implement these methods to provide
    a consistent interface for the translation pipeline.
    """

    # Human-readable name for display
    name: str

    # Backend type
    backend_type: BackendType

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this backend is currently available.

        Returns:
            True if the backend can be used (API key set, service running, etc.)
        """

    @abstractmethod
    def translate_words(
        self,
        words: list[str],
        source_lang: str,
        target_lang: str,
        hints: str | None = None,
        word_hints: dict[str, list[str]] | None = None,
    ) -> list[str]:
        """
        Translate individual words (for dictionary-style translations).

        This is optimized for single-word translations like those used
        for flashcard definitions.

        Args:
            words: List of words to translate
            source_lang: Source language code (e.g., "ru")
            target_lang: Target language code (e.g., "en")
            hints: Optional language-specific hints for LLM backends

        Returns:
            List of translations (same order as input)
        """

    @abstractmethod
    def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
    ) -> list[str]:
        """
        Translate texts in batch (for sentences, glosses, etc.).

        This handles longer texts and sentences, optimizing for
        batch efficiency.

        Args:
            texts: List of texts to translate
            source_lang: Source language code
            target_lang: Target language code

        Returns:
            List of translations (same order as input)
        """

    def get_description(self) -> str:
        """Get a human-readable description of this backend."""
        return f"{self.name} translation backend"
