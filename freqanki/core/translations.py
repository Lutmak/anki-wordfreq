"""Batch translation using DeepL API."""

import re

import requests

from freqanki.config import DEEPL_CODES, WIKTIONARY_LANG_NAMES
from freqanki.core.kaikki import get_glosses_for_word
from freqanki.utils.console import console
from freqanki.utils.http import RateLimitedClient

# Wikilink pattern for parsing Wiktionary
WIKILINK_PATTERN = re.compile(r"\[\[([^|#\]]+)(?:#[^|\]]+)?(?:\|([^\]]+))?\]\]")


def get_wiktionary_glosses(
    word: str,
    source_lang: str,
    client: RateLimitedClient | None = None,
) -> list[str]:
    """
    Get English glosses from Wiktionary.

    Args:
        word: Word to look up
        source_lang: Source language code
        client: HTTP client to use

    Returns:
        List of up to 3 English translations
    """
    if client is None:
        client = RateLimitedClient()

    source_name = WIKTIONARY_LANG_NAMES.get(source_lang, source_lang.capitalize())

    try:
        response = client.get(
            "https://en.wiktionary.org/w/api.php",
            params={
                "action": "parse",
                "page": word,
                "prop": "wikitext",
                "format": "json",
            },
        )

        if response is None:
            return []

        data = response.json()
        if "error" in data:
            return []

        wikitext = data["parse"]["wikitext"]["*"]

        # Find the source language section
        lang_marker = f"=={source_name}=="
        if lang_marker not in wikitext:
            return []

        lang_start = wikitext.find(lang_marker)
        rest = wikitext[lang_start + len(lang_marker) :]

        # Find next language section
        next_lang_match = re.search(r"\n==[^=]", rest)
        if next_lang_match:
            lang_section = rest[: next_lang_match.start()]
        else:
            lang_section = rest

        # Extract translations from definition lines
        translations: list[str] = []
        current_pos = None
        allowed_pos = {
            "noun",
            "proper noun",
            "verb",
            "adjective",
            "adverb",
            "pronoun",
            "preposition",
            "postposition",
            "conjunction",
            "particle",
            "interjection",
            "numeral",
            "determiner",
            "phrase",
            "idiom",
            "proverb",
            "expression",
        }

        for raw_line in lang_section.splitlines():
            line = raw_line.strip()

            # Track section headings
            heading_match = re.match(r"^={4}([^=]+)={4}$", line)
            if heading_match:
                current_pos = heading_match.group(1).strip().lower()
                continue

            # Only process definition lines
            if not line.startswith("#"):
                continue
            if len(line) > 1 and line[1] in ":*;-=^":
                continue

            # Skip non-word sections
            if current_pos and current_pos not in allowed_pos:
                continue

            # Extract wikilinks
            for match in WIKILINK_PATTERN.finditer(line):
                link_target = match.group(1)
                display_text = match.group(2) if match.group(2) else link_target
                translation = display_text.strip()

                # Filter: must be alphabetic and reasonable length
                if not translation or len(translation) > 30:
                    continue
                if not re.match(r"^[A-Za-z\s\-']+$", translation):
                    continue

                if translation not in translations:
                    translations.append(translation)

        return translations[:3]

    except Exception:
        return []


def get_english_glosses_batch(
    words: list[str],
    source_lang: str,
    kaikki_entries: dict[str, list[dict]],
) -> list[str]:
    """
    Get English glosses for multiple words.

    Tries Wiktionary first, falls back to Kaikki.

    Args:
        words: Words to get glosses for
        source_lang: Source language code
        kaikki_entries: Pre-loaded Kaikki entries

    Returns:
        List of gloss strings (comma-separated) for each word
    """
    console.print(f"[blue]Getting English glosses for {len(words)} words...[/blue]")

    client = RateLimitedClient()
    glosses: list[str] = []

    for i, word in enumerate(words, 1):
        if i % 100 == 0:
            console.print(f"  Processing glosses: {i}/{len(words)}...", end="\r")

        # Try Wiktionary first
        en_candidates = get_wiktionary_glosses(word, source_lang, client)

        # Fall back to Kaikki
        if not en_candidates:
            en_candidates = get_glosses_for_word(word, kaikki_entries)

        # Last resort: use the word itself
        if not en_candidates:
            en_candidates = [word]

        glosses.append(", ".join(en_candidates[:3]))

    console.print(f"  Got glosses for {len(glosses)} words                    ")
    return glosses


def batch_translate_deepl(
    texts: list[str],
    source_lang: str,
    target_lang: str,
    api_key: str,
    endpoint: str = "https://api-free.deepl.com/v2/translate",
    batch_size: int = 50,
) -> list[str]:
    """
    Translate texts using DeepL API in batches.

    Args:
        texts: Texts to translate
        source_lang: Source language code
        target_lang: Target language code (ISO or DeepL code)
        api_key: DeepL API key
        endpoint: DeepL API endpoint
        batch_size: Texts per API request

    Returns:
        List of translated texts (same order as input)
    """
    if not texts:
        return []

    # Convert to DeepL codes
    source_deepl = DEEPL_CODES.get(source_lang, source_lang.upper())
    target_deepl = DEEPL_CODES.get(target_lang, target_lang.upper())

    results: list[str] = [""] * len(texts)

    console.print(f"[blue]Translating {len(texts)} texts to {target_lang}...[/blue]")

    try:
        for batch_start in range(0, len(texts), batch_size):
            batch_end = min(batch_start + batch_size, len(texts))
            batch = texts[batch_start:batch_end]

            response = requests.post(
                endpoint,
                headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
                json={
                    "text": batch,
                    "source_lang": source_deepl,
                    "target_lang": target_deepl,
                },
                timeout=60,
            )
            response.raise_for_status()

            translations = [t["text"] for t in response.json().get("translations", [])]

            # Store results
            for i, trans in enumerate(translations):
                results[batch_start + i] = trans

            console.print(
                f"  Translated batch {batch_start + 1}-{batch_end}/{len(texts)}",
                end="\r",
            )

        console.print(f"[green]  Translated {len(texts)} texts successfully[/green]")

    except Exception as e:
        console.print(f"[red]DeepL error: {e}[/red]")
        # Return original texts on failure
        return texts

    return results


def translate_glosses_to_targets(
    words: list[str],
    source_lang: str,
    target_langs: list[str],
    kaikki_entries: dict[str, list[dict]],
    api_key: str,
    endpoint: str = "https://api-free.deepl.com/v2/translate",
) -> dict[str, list[str]]:
    """
    Translate word glosses to multiple target languages.

    Efficient pipeline:
    1. Get English glosses for all words (Wiktionary + Kaikki)
    2. If target is English, return glosses directly
    3. Otherwise, batch translate all glosses to target language

    Args:
        words: Words to translate
        source_lang: Source language code
        target_langs: Target language codes
        kaikki_entries: Pre-loaded Kaikki entries
        api_key: DeepL API key
        endpoint: DeepL API endpoint

    Returns:
        Dict mapping target language to list of translations
    """
    # Step 1: Get English glosses for all words
    en_glosses = get_english_glosses_batch(words, source_lang, kaikki_entries)

    # Step 2: Translate to each target language
    results: dict[str, list[str]] = {}

    for target in target_langs:
        if target.lower() == "en":
            results[target] = en_glosses
        else:
            if not api_key:
                console.print(
                    f"[yellow]No DeepL API key, using English for {target}[/yellow]"
                )
                results[target] = en_glosses
            else:
                translated = batch_translate_deepl(
                    en_glosses,
                    "en",
                    target,
                    api_key,
                    endpoint,
                )
                results[target] = translated

    return results


def translate_sentences_batch(
    sentences: list[str],
    source_lang: str,
    target_lang: str,
    api_key: str,
    endpoint: str = "https://api-free.deepl.com/v2/translate",
) -> dict[str, str]:
    """
    Translate sentences for literal translations.

    Args:
        sentences: Unique source sentences
        source_lang: Source language code
        target_lang: Target language code
        api_key: DeepL API key
        endpoint: DeepL API endpoint

    Returns:
        Dict mapping source sentence to translation
    """
    if not sentences or not api_key:
        return {}

    translations = batch_translate_deepl(
        sentences, source_lang, target_lang, api_key, endpoint
    )

    return dict(zip(sentences, translations))
