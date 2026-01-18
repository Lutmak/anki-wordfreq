"""Qwen3 (Ollama) translation backend."""

import requests

from freqanki.core.backends.base import BackendType, TranslationBackend
from freqanki.utils.console import console, create_progress


# Language code to name mapping
LANGUAGE_NAMES: dict[str, str] = {
    "ar": "Arabic",
    "bg": "Bulgarian",
    "bn": "Bengali",
    "ca": "Catalan",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "fa": "Persian",
    "fi": "Finnish",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "id": "Indonesian",
    "is": "Icelandic",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mk": "Macedonian",
    "ms": "Malay",
    "nb": "Norwegian",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sr": "Serbian",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "zh": "Chinese",
}


# Base system prompt - general for all languages
BASE_SYSTEM_PROMPT = """You are a bilingual dictionary creating flashcards for language learners.

TASK: Translate single {source_lang} words to {target_lang}. Give the PRIMARY dictionary meaning.

WHAT YOU'RE TRANSLATING: The most frequent words in the language:
- Prepositions, conjunctions, particles
- Pronouns (various grammatical cases)
- Verbs (various conjugations)
- Basic nouns, adjectives, adverbs
- Numbers, abbreviations

TRANSLATION GUIDELINES:

1. BREVITY: 1-2 {target_lang} words maximum.

2. FREQUENCY: Give the meaning seen 80%+ of the time in texts.

3. DICTIONARY FIRST: What's the FIRST entry in a bilingual dictionary?

4. LEARNER FOCUS: What helps a beginner parse basic sentences?

COMMON PITFALLS TO AVOID:

• COPULA vs POSSESSION: If a verb means "exists/is present", translate as "is" or "to be".
  Don't confuse "[thing] exists" with "someone has [thing]" - these use different verbs.

• QUESTION PARTICLES: Words that turn statements into yes/no questions mean "whether/if",
  not "or". The word for "or" connects alternatives, question particles create questions.

• EMPHATIC NEGATION: Particles meaning "not even one" or "not any" → use "neither/nor",
  not just "no" (which is simple negation).

• INFINITIVE vs CONJUGATED: When translating a conjugated form, give that specific form
  (e.g., "was", "is") not the infinitive, unless it's the dictionary form.

{language_hints}

OUTPUT RULES:
- {target_lang} ONLY - never include source language characters
- No quotes, no explanations
- One word per line, matching input order
- Keep it minimal: shorter is better for flashcards"""


# Simpler prompt for batch sentence translations
BATCH_SYSTEM_PROMPT = """You are a translator. Translate the following {source_lang} texts to {target_lang}.
Keep translations natural and accurate. Output one translation per line, matching input order."""


class QwenBackend(TranslationBackend):
    """
    Qwen3 translation backend via Ollama.

    Uses a local LLM for context-aware translations.
    Best for: Free, offline (after model download), handles particles/function words well.
    Limitations: Slower (~1-2s per word), requires Ollama running.
    """

    name = "Qwen3 (Ollama)"
    backend_type = BackendType.QWEN

    def __init__(
        self,
        model: str = "qwen3:4b-instruct",
        endpoint: str = "http://localhost:11434/api/chat",
        batch_size: int = 10,
    ):
        self.model = model
        self.endpoint = endpoint
        self.batch_size = batch_size
        self._available: bool | None = None

    def is_available(self) -> bool:
        """Check if Ollama is running and responsive."""
        # Only cache positive results - retry if previously unavailable
        if self._available is True:
            return True

        try:
            response = requests.get(
                "http://localhost:11434/api/tags",
                timeout=2,
            )
            self._available = response.status_code == 200
        except Exception:
            self._available = False

        return self._available

    def translate_words(
        self,
        words: list[str],
        source_lang: str,
        target_lang: str,
        hints: str | None = None,
        word_hints: dict[str, list[str]] | None = None,
    ) -> list[str]:
        """
        Translate words using Qwen3 via Ollama.

        Uses batching for efficiency and a carefully crafted prompt.
        """
        if not words or not self.is_available():
            return words

        source_name = LANGUAGE_NAMES.get(source_lang, source_lang.capitalize())
        target_name = LANGUAGE_NAMES.get(target_lang, target_lang.capitalize())

        # Build system prompt with optional language hints
        hints_section = f"\nLANGUAGE-SPECIFIC GUIDANCE:\n{hints}" if hints else ""
        system_message = BASE_SYSTEM_PROMPT.format(
            source_lang=source_name,
            target_lang=target_name,
            language_hints=hints_section,
        )

        results: list[str] = []

        with create_progress() as progress:
            task = progress.add_task("Translating words", total=len(words))
            for batch_start in range(0, len(words), self.batch_size):
                batch = words[batch_start : batch_start + self.batch_size]

                # Create numbered batch prompt
                user_prompt = (
                    f"Translate these {source_name} words to {target_name} (one per line):\n"
                )
                for i, w in enumerate(batch, 1):
                    line = f"{i}. {w}"
                    if word_hints and w in word_hints:
                        meanings = ", ".join(word_hints[w][:3])  # Limit to 3 meanings
                        line += f" (meanings: {meanings})"
                    user_prompt += line + "\n"

                try:
                    response = requests.post(
                        self.endpoint,
                        json={
                            "model": self.model,
                            "messages": [
                                {"role": "system", "content": system_message},
                                {"role": "user", "content": user_prompt},
                            ],
                            "stream": False,
                            "options": {
                                "temperature": 0.1,
                                "num_predict": self.batch_size * 15,
                                "num_ctx": 2048,
                            },
                            "keep_alive": "5m",
                        },
                        timeout=300,
                    )
                    response.raise_for_status()
                    raw = response.json().get("message", {}).get("content", "").strip()

                    # Parse response
                    translations = self._parse_batch_response(raw)

                    # Match translations to words
                    for i, word in enumerate(batch):
                        if i < len(translations):
                            results.append(self._clean_translation(translations[i]))
                        else:
                            results.append(word)  # Fallback to original

                    progress.update(task, advance=len(batch))

                    completed = progress.tasks[task].completed
                    elapsed = progress.tasks[task].elapsed
                    if completed > 0:
                        avg = elapsed / completed
                        eta = (len(words) - completed) * avg
                        progress.update(
                            task,
                            description=f"Translating words ({completed}/{len(words)}, {avg:.2f}s/word, ETA: {eta:.1f}s)",
                        )

                except Exception as e:
                    console.print(f"[red]Qwen error: {e}[/red]")
                    results.extend(batch)  # Return originals on failure
                    progress.update(task, advance=len(batch))

                    completed = progress.tasks[task].completed
                    elapsed = progress.tasks[task].elapsed
                    if completed > 0:
                        avg = elapsed / completed
                        eta = (len(words) - completed) * avg
                        progress.update(
                            task,
                            description=f"Translating words ({completed}/{len(words)}, {avg:.2f}s/word, ETA: {eta:.1f}s)",
                        )

        return results

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
    ) -> list[str]:
        """Translate texts in batch using Qwen3."""
        if not texts or not self.is_available():
            return texts

        source_name = LANGUAGE_NAMES.get(source_lang, source_lang.capitalize())
        target_name = LANGUAGE_NAMES.get(target_lang, target_lang.capitalize())
        system_message = BATCH_SYSTEM_PROMPT.format(
            source_lang=source_name,
            target_lang=target_name,
        )

        results: list[str] = []

        # Use smaller batches for longer texts
        batch_size = 5

        with create_progress() as progress:
            task = progress.add_task("Translating glosses", total=len(texts))
            for batch_start in range(0, len(texts), batch_size):
                batch = texts[batch_start : batch_start + batch_size]

                user_prompt = f"Translate these {source_name} texts to {target_name}:\n"
                user_prompt += "\n".join(f"{i}. {t}" for i, t in enumerate(batch, 1))

                try:
                    response = requests.post(
                        self.endpoint,
                        json={
                            "model": self.model,
                            "messages": [
                                {"role": "system", "content": system_message},
                                {"role": "user", "content": user_prompt},
                            ],
                            "stream": False,
                            "options": {
                                "temperature": 0.3,
                                "num_predict": 2000,
                                "num_ctx": 4096,
                            },
                            "keep_alive": "5m",
                        },
                        timeout=300,
                    )
                    response.raise_for_status()
                    raw = response.json().get("message", {}).get("content", "").strip()

                    translations = self._parse_batch_response(raw)

                    for i, text in enumerate(batch):
                        if i < len(translations):
                            results.append(translations[i])
                        else:
                            results.append(text)

                    progress.update(task, advance=len(batch))

                    completed = progress.tasks[task].completed
                    elapsed = progress.tasks[task].elapsed
                    if completed > 0:
                        avg = elapsed / completed
                        eta = (len(texts) - completed) * avg
                        progress.update(
                            task,
                            description=f"Translating glosses ({completed}/{len(texts)}, {avg:.2f}s/item, ETA: {eta:.1f}s)",
                        )

                except Exception as e:
                    console.print(f"[red]Qwen batch error: {e}[/red]")
                    results.extend(batch)
                    progress.update(task, advance=len(batch))

                    completed = progress.tasks[task].completed
                    elapsed = progress.tasks[task].elapsed
                    if completed > 0:
                        avg = elapsed / completed
                        eta = (len(texts) - completed) * avg
                        progress.update(
                            task,
                            description=f"Translating glosses ({completed}/{len(texts)}, {avg:.2f}s/item, ETA: {eta:.1f}s)",
                        )

        return results

    def _parse_batch_response(self, raw: str) -> list[str]:
        """Parse numbered or plain list response from LLM."""
        lines = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Remove numbering (1. / 1) / 1: etc.)
            if line and line[0].isdigit():
                for sep in [". ", ") ", ": ", " "]:
                    if sep in line[:5]:
                        line = line.split(sep, 1)[-1]
                        break
            line = line.strip().strip("\"'`")
            if line:
                lines.append(line)
        return lines

    def _clean_translation(self, trans: str) -> str:
        """Clean up a translation for flashcard use."""
        trans = trans.rstrip(".,;:!?")

        # Take first option if multiple given
        if " or " in trans.lower():
            trans = trans.split(" or ")[0].strip()
        if ", " in trans:
            trans = trans.split(", ")[0].strip()

        # Limit to 3 words max
        words = trans.split()
        if len(words) > 3:
            if words[0].lower() in ["to", "in"]:
                trans = " ".join(words[:3])
            else:
                trans = words[0]

        return trans

    def get_description(self) -> str:
        return "Qwen3 via Ollama (free, local LLM, slower but context-aware)"
