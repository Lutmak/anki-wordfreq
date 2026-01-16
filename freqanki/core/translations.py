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
    context: str | None = None,
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
        context: Optional context to improve translation accuracy (not billed)

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

            payload = {
                "text": batch,
                "source_lang": source_deepl,
                "target_lang": target_deepl,
            }
            if context:
                payload["context"] = context

            response = requests.post(
                endpoint,
                headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
                json=payload,
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


def _translate_word_batch(
    words: list[str],
    source_lang: str,
    target_lang: str,
    api_key: str,
    endpoint: str = "https://api-free.deepl.com/v2/translate",
) -> list[str]:
    """
    Translate a batch of individual words for literal word-by-word translation.

    Uses DeepL's next-gen models (quality_optimized) which provide better
    literal translations without any context (context was found to cause
    some words like 'не', 'за', 'а' to remain untranslated).

    Key settings:
    - Each word is sent as a separate text[] item (forces per-word translation)
    - split_sentences=0 prevents DeepL from merging words
    - model_type=quality_optimized uses next-gen models for better accuracy
    - No context (found to cause issues with short common words)

    Args:
        words: Individual words/groups to translate
        source_lang: Source language code
        target_lang: Target language code
        api_key: DeepL API key
        endpoint: DeepL API endpoint

    Returns:
        List of translated words (same order as input)
    """
    if not words or not api_key:
        return words

    # Convert to DeepL codes
    source_deepl = DEEPL_CODES.get(source_lang, source_lang.upper())
    target_deepl = DEEPL_CODES.get(target_lang, target_lang.upper())

    try:
        response = requests.post(
            endpoint,
            headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
            json={
                "text": words,
                "source_lang": source_deepl,
                "target_lang": target_deepl,
                "split_sentences": "0",  # Treat each word as standalone, no merging
                "model_type": "quality_optimized",  # Use next-gen models for better literal translations
            },
            timeout=60,
        )
        response.raise_for_status()

        translations = [t["text"] for t in response.json().get("translations", [])]
        return translations

    except Exception as e:
        console.print(f"[red]DeepL error translating words: {e}[/red]")
        return words


def _has_untranslated_words(
    source_words: list[str],
    translations: list[str],
) -> bool:
    """
    Check if any source word was returned unchanged (untranslated).

    This detects cases where DeepL doesn't recognize a word and just
    returns it as-is or with simple transliteration (e.g., "ко" -> "ko").

    Skips numbers since they typically stay the same across languages.

    Args:
        source_words: Original words in source language
        translations: Translated words

    Returns:
        True if any word appears untranslated
    """
    for src, trans in zip(source_words, translations):
        src_clean = src.lower().strip()
        trans_clean = trans.lower().strip()

        # Skip numbers - they stay the same across languages
        if src_clean.replace(" ", "").isdigit():
            continue

        # Check if translation is same as source
        if src_clean == trans_clean:
            return True

        # Check for Cyrillic -> Latin transliteration (same letters, just converted)
        # e.g., "ко" -> "ko", "бе" -> "be"
        # Only for short words (1-2 chars) where transliteration is more likely
        if len(src_clean) <= 2 and len(trans_clean) <= 2:
            has_cyrillic = any("\u0400" <= c <= "\u04ff" for c in src)
            is_latin = all(c.isascii() for c in trans_clean)
            # If source is Cyrillic, result is Latin, and they "sound" similar
            # Simple check: if transliterated version matches
            if has_cyrillic and is_latin:
                # Common Cyrillic -> Latin mappings for short words
                translit_map = {
                    "а": "a",
                    "б": "b",
                    "в": "v",
                    "г": "g",
                    "д": "d",
                    "е": "e",
                    "ж": "zh",
                    "з": "z",
                    "и": "i",
                    "й": "y",
                    "к": "k",
                    "л": "l",
                    "м": "m",
                    "н": "n",
                    "о": "o",
                    "п": "p",
                    "р": "r",
                    "с": "s",
                    "т": "t",
                    "у": "u",
                    "ф": "f",
                    "х": "kh",
                    "ц": "ts",
                    "ч": "ch",
                    "ш": "sh",
                    "щ": "sch",
                    "ы": "y",
                    "э": "e",
                    "ю": "yu",
                    "я": "ya",
                }
                transliterated = "".join(translit_map.get(c, c) for c in src_clean)
                if transliterated == trans_clean:
                    return True

    return False


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
                console.print(f"[yellow]No DeepL API key, using English for {target}[/yellow]")
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

    translations = batch_translate_deepl(sentences, source_lang, target_lang, api_key, endpoint)

    return dict(zip(sentences, translations))


def _merge_single_letter_particles(
    words_with_punct: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """
    Merge single-letter words (particles like 'С', 'В', 'К') with adjacent words.

    In Russian and other languages, prepositions/particles like 'с', 'в', 'к', 'у'
    are single letters that make more sense when grouped with their following word.
    If a single-letter word is at the end, merge it with the previous word.

    Args:
        words_with_punct: List of (display_word, clean_word) tuples
            display_word: word with original punctuation for display
            clean_word: word without punctuation for translation

    Returns:
        List of (display_group, clean_group) tuples with single-letter words merged
    """
    if not words_with_punct:
        return []

    merged: list[tuple[str, str]] = []
    i = 0
    while i < len(words_with_punct):
        display_word, clean_word = words_with_punct[i]
        # If single-letter clean word and there's a next word, merge forward
        if len(clean_word) == 1 and i + 1 < len(words_with_punct):
            next_display, next_clean = words_with_punct[i + 1]
            merged.append((f"{display_word} {next_display}", f"{clean_word} {next_clean}"))
            i += 2  # Skip the next word since it's merged
        # If single-letter at the end and there's a previous merged item, merge backward
        elif len(clean_word) == 1 and merged:
            prev_display, prev_clean = merged.pop()
            merged.append((f"{prev_display} {display_word}", f"{prev_clean} {clean_word}"))
            i += 1
        else:
            merged.append((display_word, clean_word))
            i += 1
    return merged


def _tokenize_with_punctuation(sentence: str) -> list[tuple[str, str]]:
    """
    Tokenize sentence preserving trailing punctuation for display.

    Args:
        sentence: The sentence to tokenize

    Returns:
        List of (display_word, clean_word) tuples
            display_word: word with trailing punctuation (e.g., "реку.")
            clean_word: word without punctuation (e.g., "реку")
    """
    # Match word with optional trailing punctuation
    pattern = re.compile(r"(\b\w+\b)([.,!?;:]*)")
    result: list[tuple[str, str]] = []

    for match in pattern.finditer(sentence):
        clean_word = match.group(1)
        punct = match.group(2)
        display_word = clean_word + punct
        result.append((display_word, clean_word))

    return result


def translate_words_literal(
    unique_sentences: list[str],
    source_lang: str,
    target_lang: str,
    api_key: str,
    endpoint: str = "https://api-free.deepl.com/v2/translate",
    min_words: int = 3,
) -> tuple[dict[str, list[tuple[str, str]]], set[str]]:
    """
    Get word-by-word literal translations for sentences.

    Splits each sentence into words, merges single-letter particles with
    the next word, filters sentences with fewer than min_words, and
    translates each word/group individually.

    Uses DeepL's next-gen models (quality_optimized) for better literal
    translations. Sentences where any word fails to translate (returns
    unchanged) are excluded and reported in the failed_sentences set.

    Preserves punctuation in display but strips it for translation to get
    consistent results (e.g., "важно." displays with period but translates
    as "важно" to get "importantly" not "importantly.").

    Args:
        unique_sentences: Unique source sentences to translate word-by-word
        source_lang: Source language code
        target_lang: Target language code
        api_key: DeepL API key
        endpoint: DeepL API endpoint
        min_words: Minimum number of final words/groups required (default: 3)

    Returns:
        Tuple of:
        - Dict mapping sentence to list of (display_word, translation) tuples
        - Set of sentences that failed (had untranslated words)
    """
    if not unique_sentences or not api_key:
        return {}, set()

    console.print(
        f"[blue]Getting word-by-word translations for {len(unique_sentences)} sentences...[/blue]"
    )

    # Map sentence -> list of (display_group, clean_group)
    sentence_word_groups: dict[str, list[tuple[str, str]]] = {}

    for sentence in unique_sentences:
        # Tokenize preserving punctuation
        words_with_punct = _tokenize_with_punctuation(sentence)
        # Merge single-letter particles
        merged = _merge_single_letter_particles(words_with_punct)

        # Filter out sentences with fewer than min_words
        if len(merged) < min_words:
            continue

        sentence_word_groups[sentence] = merged

    if not sentence_word_groups:
        return {}, set()

    # Translate each sentence's words
    result: dict[str, list[tuple[str, str]]] = {}
    failed_sentences: set[str] = set()
    total_words = 0

    for i, (sentence, groups) in enumerate(sentence_word_groups.items()):
        clean_words = [clean for _, clean in groups]

        # Translate words using next-gen models
        translations = _translate_word_batch(
            clean_words, source_lang, target_lang, api_key, endpoint
        )

        # Check if any words failed to translate
        if _has_untranslated_words(clean_words, translations):
            failed_sentences.add(sentence)
            continue  # Skip this sentence, don't add to result

        # Build result with display words paired with translations
        result[sentence] = [
            (display, translations[j] if j < len(translations) else clean)
            for j, (display, clean) in enumerate(groups)
        ]

        total_words += len(clean_words)

        console.print(
            f"  Translated sentence {i + 1}/{len(sentence_word_groups)}",
            end="\r",
        )

    if failed_sentences:
        console.print(
            f"[yellow]  {len(failed_sentences)} sentences had untranslated words[/yellow]"
        )
    console.print(f"[green]  Translated {total_words} words across {len(result)} sentences[/green]")
    return result, failed_sentences
