"""Abstract base class for language modules."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class MorphologyInfo:
    """Grammatical information for a word."""

    lemma: str | None = None
    part_of_speech: str | None = None
    case: str | None = None
    gender: str | None = None
    number: str | None = None
    animacy: str | None = None
    aspect: str | None = None
    tense: str | None = None
    person: str | None = None
    mood: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in self.__dict__.items() if v is not None}


class LanguageModule(ABC):
    """
    Abstract base class for language-specific functionality.

    Each supported language should have a concrete implementation
    that handles language-specific validation, romanization, and morphology.
    """

    # ISO 639-1 language code (e.g., "ru", "zh", "ja")
    code: str

    # Human-readable language name
    name: str

    # Code used by wordfreq library (usually same as ISO code)
    wordfreq_code: str

    # Tatoeba corpus language code (e.g., "rus", "cmn", "jpn")
    tatoeba_code: str

    # DeepL API language code (e.g., "RU", "ZH", "JA")
    deepl_code: str

    # Whether this language has full support (morphology, romanization, etc.)
    has_full_support: bool = False

    @abstractmethod
    def is_valid_token(self, word: str) -> bool:
        """
        Check if a token is valid for this language.

        Used to filter wordfreq results to remove foreign words,
        symbols, or other unwanted tokens.

        Args:
            word: The word to validate

        Returns:
            True if the word is valid for this language
        """

    @abstractmethod
    def get_romanization(self, word: str) -> str | None:
        """
        Get the romanized (Latin script) form of a word.

        Args:
            word: The word to romanize

        Returns:
            Romanized form, or None if not available/applicable
        """

    @abstractmethod
    def get_morphology(self, word: str) -> MorphologyInfo | None:
        """
        Get morphological analysis for a word.

        Args:
            word: The word to analyze

        Returns:
            MorphologyInfo with grammatical details, or None if not available
        """

    def get_display_word(self, word: str) -> str:
        """
        Format a word for display on card front.

        Override in subclasses for special formatting needs.

        Args:
            word: The original word

        Returns:
            Formatted display string
        """
        return word

    def normalize_for_lookup(self, word: str) -> str:
        """
        Normalize a word for dictionary lookups.

        Override in subclasses for language-specific normalization
        (e.g., removing diacritics, converting to lowercase).

        Args:
            word: The word to normalize

        Returns:
            Normalized form for lookups
        """
        return word.lower().strip()

    def get_lemma(self, word: str) -> str:
        """
        Get the lemma (base/dictionary form) of a word.

        Default implementation uses morphology if available.

        Args:
            word: The word to lemmatize

        Returns:
            Lemma form, or original word if not available
        """
        morph = self.get_morphology(word)
        if morph and morph.lemma:
            return morph.lemma
        return word

    def expand_special_word(self, word: str) -> str | None:
        """
        Expand abbreviations or special forms.

        Override in subclasses to handle language-specific expansions
        (e.g., "млн" -> "миллион" in Russian).

        Args:
            word: The word to expand

        Returns:
            Expanded form, or None if no expansion needed
        """
        return None

    def __repr__(self) -> str:
        support = "full" if self.has_full_support else "basic"
        return f"<{self.__class__.__name__}({self.code}, {support})>"
