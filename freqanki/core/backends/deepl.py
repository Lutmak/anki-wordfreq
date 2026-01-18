"""DeepL translation backend."""

import os

import requests

from freqanki.config import DEEPL_CODES
from freqanki.core.backends.base import BackendType, TranslationBackend
from freqanki.utils.console import console


class DeepLBackend(TranslationBackend):
    """
    DeepL API translation backend.

    Premium quality translation, requires API key from environment.
    Best for: High accuracy, production use.
    Limitations: Requires internet, API key, has usage limits.
    """

    name = "DeepL"
    backend_type = BackendType.DEEPL

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str = "https://api-free.deepl.com/v2/translate",
        batch_size: int = 50,
    ):
        self.api_key = api_key or os.getenv("DEEPL_API_KEY", "")
        self.endpoint = endpoint
        self.batch_size = batch_size

    def is_available(self) -> bool:
        """Check if DeepL API key is configured."""
        return bool(self.api_key)

    def translate_words(
        self,
        words: list[str],
        source_lang: str,
        target_lang: str,
        hints: str | None = None,  # Not used by DeepL
        word_hints: dict[str, list[str]] | None = None,
    ) -> list[str]:
        """
        Translate individual words using DeepL.

        Uses split_sentences=0 and quality_optimized model for
        better literal word translations.
        """
        if not words or not self.api_key:
            return words

        source_deepl = DEEPL_CODES.get(source_lang, source_lang.upper())
        target_deepl = DEEPL_CODES.get(target_lang, target_lang.upper())

        results: list[str] = []

        for batch_start in range(0, len(words), self.batch_size):
            batch = words[batch_start : batch_start + self.batch_size]

            try:
                response = requests.post(
                    self.endpoint,
                    headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
                    json={
                        "text": batch,
                        "source_lang": source_deepl,
                        "target_lang": target_deepl,
                        "split_sentences": "0",
                        "model_type": "quality_optimized",
                    },
                    timeout=60,
                )
                response.raise_for_status()
                translations = [t["text"] for t in response.json().get("translations", [])]
                results.extend(translations)

            except Exception as e:
                console.print(f"[red]DeepL error: {e}[/red]")
                results.extend(batch)  # Return original on failure

        return results

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
    ) -> list[str]:
        """Translate texts in batch using DeepL."""
        if not texts or not self.api_key:
            return texts

        source_deepl = DEEPL_CODES.get(source_lang, source_lang.upper())
        target_deepl = DEEPL_CODES.get(target_lang, target_lang.upper())

        results: list[str] = [""] * len(texts)

        for batch_start in range(0, len(texts), self.batch_size):
            batch = texts[batch_start : batch_start + self.batch_size]

            try:
                response = requests.post(
                    self.endpoint,
                    headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
                    json={
                        "text": batch,
                        "source_lang": source_deepl,
                        "target_lang": target_deepl,
                    },
                    timeout=60,
                )
                response.raise_for_status()
                translations = [t["text"] for t in response.json().get("translations", [])]

                for i, trans in enumerate(translations):
                    results[batch_start + i] = trans

            except Exception as e:
                console.print(f"[red]DeepL error: {e}[/red]")
                for i, text in enumerate(batch):
                    results[batch_start + i] = text

        return results

    def get_description(self) -> str:
        return "DeepL API (premium, highest quality, requires API key)"
