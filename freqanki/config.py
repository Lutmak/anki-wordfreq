"""Configuration dataclasses and defaults for FreqAnki."""

from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum
import os


class BackendType(Enum):
    """Translation backend types."""

    AUTO = "auto"  # Auto-select best available
    DEEPL = "deepl"  # DeepL API (best quality, requires API key)
    QWEN = "qwen"  # Qwen3 via Ollama (local LLM, context-aware)
    ARGOS = "argos"  # Argos Translate (fast, offline)


@dataclass
class GenerationConfig:
    """Configuration for deck generation."""

    # Source language (the language being learned)
    source_lang: str

    # Target languages for translations
    target_langs: list[str] = field(default_factory=lambda: ["en"])

    # Number of words to include in the deck
    num_words: int = 2000

    # Number of example sentences per word
    num_examples: int = 2

    # Include literal word-by-word translations
    include_literal: bool = False

    # Output file path
    output_path: Path | None = None

    # Show HTML preview before generating
    show_preview: bool = True

    # Path to old deck for migration (preserves scheduling)
    migrate_from: Path | None = None

    def __post_init__(self) -> None:
        if self.output_path is None:
            # When migrating, use same filename as input for Anki to recognize as update
            if self.migrate_from:
                self.output_path = Path(self.migrate_from.name)
            else:
                self.output_path = Path(f"FreqAnki_{self.source_lang}_Top_{self.num_words}.apkg")


@dataclass
class APIConfig:
    """Configuration for external API services."""

    # Translation backend selection
    translation_backend: BackendType = BackendType.AUTO

    # DeepL API key (from environment or config)
    deepl_api_key: str = field(default_factory=lambda: os.getenv("DEEPL_API_KEY", ""))

    # DeepL API endpoint (free vs pro)
    deepl_endpoint: str = "https://api-free.deepl.com/v2/translate"

    # Maximum texts per DeepL batch request
    deepl_batch_size: int = 50

    # Ollama endpoint for Qwen backend
    ollama_endpoint: str = "http://localhost:11434/api/chat"

    # Ollama model name
    ollama_model: str = "qwen3:4b-instruct"


@dataclass
class DownloadConfig:
    """Configuration for file downloads and caching."""

    # Directory for downloaded audio files
    audio_dir: Path = field(default_factory=lambda: Path("audio"))

    # Directory for language dictionaries
    dict_dir: Path = field(default_factory=lambda: Path("language-dicts"))

    # Directory for cached API responses
    cache_dir: Path = field(default_factory=lambda: Path(".cache"))

    # Maximum concurrent download workers
    max_workers: int = 5

    # HTTP request timeout in seconds
    request_timeout: int = 30

    # Maximum retries for failed requests
    max_retries: int = 3

    # Base delay for exponential backoff (seconds)
    retry_base_delay: float = 1.0

    def __post_init__(self) -> None:
        # Ensure directories exist
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.dict_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class FreqAnkiConfig:
    """Main configuration combining all settings."""

    generation: GenerationConfig
    api: APIConfig = field(default_factory=APIConfig)
    download: DownloadConfig = field(default_factory=DownloadConfig)

    @classmethod
    def from_cli_args(
        cls,
        lang: str,
        targets: list[str],
        words: int,
        examples: int,
        literal: bool,
        output: Path | None,
        preview: bool,
        migrate_from: Path | None = None,
        backend: BackendType = BackendType.AUTO,
    ) -> "FreqAnkiConfig":
        """Create config from CLI arguments."""
        return cls(
            generation=GenerationConfig(
                source_lang=lang,
                target_langs=targets,
                num_words=words,
                num_examples=examples,
                include_literal=literal,
                output_path=output,
                show_preview=preview,
                migrate_from=migrate_from,
            ),
            api=APIConfig(translation_backend=backend),
        )


# Language code mappings
TATOEBA_CODES = {
    "ar": "ara",
    "cs": "ces",
    "de": "deu",
    "el": "ell",
    "en": "eng",
    "es": "spa",
    "fi": "fin",
    "fr": "fra",
    "he": "heb",
    "hi": "hin",
    "hu": "hun",
    "id": "ind",
    "it": "ita",
    "ja": "jpn",
    "ko": "kor",
    "ms": "zsm",
    "nb": "nob",
    "nl": "nld",
    "pl": "pol",
    "pt": "por",
    "ro": "ron",
    "ru": "rus",
    "sv": "swe",
    "th": "tha",
    "tr": "tur",
    "uk": "ukr",
    "vi": "vie",
    "zh": "cmn",
}

DEEPL_CODES = {
    "ar": "AR",
    "bg": "BG",
    "cs": "CS",
    "da": "DA",
    "de": "DE",
    "el": "EL",
    "en": "EN",
    "es": "ES",
    "et": "ET",
    "fi": "FI",
    "fr": "FR",
    "hu": "HU",
    "id": "ID",
    "it": "IT",
    "ja": "JA",
    "ko": "KO",
    "lt": "LT",
    "lv": "LV",
    "nb": "NB",
    "nl": "NL",
    "pl": "PL",
    "pt": "PT",
    "ro": "RO",
    "ru": "RU",
    "sk": "SK",
    "sl": "SL",
    "sv": "SV",
    "tr": "TR",
    "uk": "UK",
    "zh": "ZH",
}

# Wiktionary language name mapping
WIKTIONARY_LANG_NAMES = {
    "ar": "Arabic",
    "cs": "Czech",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "fi": "Finnish",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "ms": "Malay",
    "nb": "Norwegian Bokmål",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "zh": "Chinese",
}
