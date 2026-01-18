"""Argos Translate backend."""

from freqanki.core.backends.base import BackendType, TranslationBackend
from freqanki.utils.console import console


class ArgosBackend(TranslationBackend):
    """
    Argos Translate backend.

    Uses offline neural machine translation models.
    Best for: Fast, free, works offline, no API keys needed.
    Limitations: Less nuanced than DeepL/LLMs for function words,
                 may need language pack installation.
    """

    name = "Argos Translate"
    backend_type = BackendType.ARGOS

    def __init__(self):
        self._available: bool | None = None
        self._translate_module = None
        self._installed_languages: set[str] | None = None

    def is_available(self) -> bool:
        """Check if Argos Translate is installed."""
        if self._available is not None:
            return self._available

        try:
            import argostranslate.translate

            self._translate_module = argostranslate.translate
            self._available = True
        except ImportError:
            self._available = False

        return self._available

    def _get_translation_func(self, source_lang: str, target_lang: str):
        """Get the translation function for a language pair."""
        if not self.is_available():
            return None

        installed_languages = self._translate_module.get_installed_languages()

        source = None
        target = None

        for lang in installed_languages:
            if lang.code == source_lang:
                source = lang
            elif lang.code == target_lang:
                target = lang

        if source is None or target is None:
            return None

        return source.get_translation(target)

    def translate_words(
        self,
        words: list[str],
        source_lang: str,
        target_lang: str,
        hints: str | None = None,  # Argos doesn't use hints
        word_hints: dict[str, list[str]] | None = None,
    ) -> list[str]:
        """
        Translate words using Argos Translate.

        Note: Argos doesn't support LLM-style hints since it's a
        neural MT model, not an LLM. Hints are ignored.
        """
        if not words:
            return words

        translation_func = self._get_translation_func(source_lang, target_lang)
        if translation_func is None:
            console.print(
                f"[yellow]Argos: No translation installed for "
                f"{source_lang} → {target_lang}[/yellow]"
            )
            return words

        results: list[str] = []

        for word in words:
            try:
                translated = translation_func.translate(word)
                results.append(self._clean_translation(translated))
            except Exception as e:
                console.print(f"[red]Argos error on '{word}': {e}[/red]")
                results.append(word)

        return results

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
    ) -> list[str]:
        """Translate texts in batch using Argos Translate."""
        if not texts:
            return texts

        translation_func = self._get_translation_func(source_lang, target_lang)
        if translation_func is None:
            console.print(
                f"[yellow]Argos: No translation installed for "
                f"{source_lang} → {target_lang}[/yellow]"
            )
            return texts

        results: list[str] = []

        for text in texts:
            try:
                translated = translation_func.translate(text)
                results.append(translated)
            except Exception as e:
                console.print(f"[red]Argos batch error: {e}[/red]")
                results.append(text)

        return results

    def _clean_translation(self, trans: str) -> str:
        """Clean up a translation for flashcard use."""
        trans = trans.strip().rstrip(".,;:!?")

        # Take first option if multiple
        if " or " in trans.lower():
            trans = trans.split(" or ")[0].strip()
        if ", " in trans:
            trans = trans.split(", ")[0].strip()

        # Limit length for flashcards
        words = trans.split()
        if len(words) > 3:
            trans = " ".join(words[:3])

        return trans

    def get_description(self) -> str:
        return "Argos Translate (fast, offline, free)"

    @classmethod
    def install_language_pack(cls, source_lang: str, target_lang: str) -> bool:
        """
        Download and install a language pack for translation.

        Call this if is_available() returns True but translation fails
        due to missing language pair.
        """
        try:
            import argostranslate.package

            # Update package index
            argostranslate.package.update_package_index()
            available_packages = argostranslate.package.get_available_packages()

            # Find matching package
            for pkg in available_packages:
                if pkg.from_code == source_lang and pkg.to_code == target_lang:
                    console.print(
                        f"[cyan]Installing Argos package: {source_lang} → {target_lang}[/cyan]"
                    )
                    argostranslate.package.install_from_path(pkg.download())
                    console.print("[green]Package installed successfully[/green]")
                    return True

            console.print(
                f"[yellow]No Argos package found for {source_lang} → {target_lang}[/yellow]"
            )
            return False

        except Exception as e:
            console.print(f"[red]Failed to install Argos package: {e}[/red]")
            return False

    @classmethod
    def list_installed_languages(cls) -> list[tuple[str, str]]:
        """List installed language pairs as (source, target) tuples."""
        try:
            import argostranslate.translate

            pairs = []
            for lang in argostranslate.translate.get_installed_languages():
                for target in lang.translations:
                    pairs.append((lang.code, target.code))
            return pairs

        except ImportError:
            return []
