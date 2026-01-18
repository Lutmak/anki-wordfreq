"""Batch translation using multiple backends."""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from freqanki.config import DEEPL_CODES, WIKTIONARY_LANG_NAMES, BackendType
from freqanki.core.kaikki import get_glosses_for_word
from freqanki.core.backends import get_backend, TranslationBackend
from freqanki.languages.translation_hints import get_hints
from freqanki.utils.console import console, create_progress
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


def translate_words_with_backend(
    words: list[str],
    source_lang: str,
    target_lang: str,
    backend_type: BackendType = BackendType.AUTO,
) -> list[str]:
    """
    Translate words using the configured backend.

    This is the main translation function that uses the modular backend system.
    It automatically loads language-specific hints for LLM backends.

    Args:
        words: Words to translate
        source_lang: Source language code (ISO 639-1)
        target_lang: Target language code
        backend_type: Which backend to use (AUTO selects best available)

    Returns:
        List of translations in same order as input words
    """
    if not words:
        return []

    # Get backend
    backend = get_backend(backend_type)
    if backend is None:
        console.print("[red]No translation backend available![/red]")
        return words  # Return original words as fallback

    console.print(f"[blue]Translating {len(words)} words with {backend.name}...[/blue]")

    # Get language hints for LLM backends
    hints = get_hints(source_lang)

    # Translate
    translations = backend.translate_words(
        words=words,
        source_lang=source_lang,
        target_lang=target_lang,
        hints=hints,
    )

    return translations


def batch_translate_with_backend(
    texts: list[str],
    source_lang: str,
    target_lang: str,
    backend_type: BackendType = BackendType.AUTO,
) -> list[str]:
    """
    Translate texts in batch using the configured backend.

    Args:
        texts: Texts to translate (sentences, glosses, etc.)
        source_lang: Source language code
        target_lang: Target language code
        backend_type: Which backend to use

    Returns:
        List of translations in same order as input
    """
    if not texts:
        return []

    backend = get_backend(backend_type)
    if backend is None:
        console.print("[red]No translation backend available![/red]")
        return texts

    console.print(f"[blue]Batch translating {len(texts)} texts with {backend.name}...[/blue]")

    return backend.translate_batch(
        texts=texts,
        source_lang=source_lang,
        target_lang=target_lang,
    )


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
        with create_progress() as progress:
            task = progress.add_task("Translating glosses", total=len(texts))
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

                progress.update(task, advance=len(batch))

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

    This is a simple check that just compares source and target.
    If they're identical, the word probably wasn't translated.

    Args:
        source_words: Original words in source language
        translations: Translated words

    Returns:
        True if any word appears untranslated (same as source)
    """
    for src, trans in zip(source_words, translations):
        src_clean = src.lower().strip()
        trans_clean = trans.lower().strip()

        # Skip numbers - they stay the same across languages
        if src_clean.replace(" ", "").isdigit():
            continue

        # Check if translation is identical to source (untranslated)
        if src_clean == trans_clean:
            return True

    return False


def translate_glosses_to_targets(
    words: list[str],
    source_lang: str,
    target_langs: list[str],
    kaikki_entries: dict[str, list[dict]],
    api_key: str,
    endpoint: str = "https://api-free.deepl.com/v2/translate",
    backend_type: BackendType = BackendType.AUTO,
) -> dict[str, list[str]]:
    """
    Translate word glosses to multiple target languages.

    Efficient pipeline:
    1. Get English glosses for all words (Wiktionary + Kaikki)
    2. If target is English, use backend for better word translations
    3. Otherwise, batch translate all glosses to target language

    Args:
        words: Words to translate
        source_lang: Source language code
        target_langs: Target language codes
        kaikki_entries: Pre-loaded Kaikki entries
        api_key: DeepL API key (for AUTO mode fallback)
        endpoint: DeepL API endpoint
        backend_type: Translation backend to use

    Returns:
        Dict mapping target language to list of translations
    """
    # Step 1: Get English glosses for all words
    en_glosses = get_english_glosses_batch(words, source_lang, kaikki_entries)

    # Step 2: Translate to each target language
    results: dict[str, list[str]] = {}

    # Determine if we should use DeepL (only in AUTO mode with valid key)
    use_deepl = (backend_type == BackendType.AUTO and api_key) or backend_type == BackendType.DEEPL

    for target in target_langs:
        if target.lower() == "en":
            # For English target, use backend for better word-level translations
            # This improves translations for function words, particles, etc.
            backend = get_backend(backend_type)
            if backend:
                improved = translate_words_with_backend(words, source_lang, target, backend_type)
                # Merge: use improved where gloss is same as original word (failed lookup)
                merged = []
                for gloss, word, improved_trans in zip(en_glosses, words, improved):
                    # If gloss lookup failed (returned original word), use backend translation
                    if gloss.strip().lower() == word.strip().lower():
                        merged.append(improved_trans)
                    else:
                        merged.append(gloss)
                results[target] = merged
            else:
                results[target] = en_glosses
        else:
            # For non-English targets, translate the glosses
            if use_deepl and api_key:
                translated = batch_translate_deepl(
                    en_glosses,
                    "en",
                    target,
                    api_key,
                    endpoint,
                )
                results[target] = translated
            else:
                # Use backend for gloss translation
                translated = batch_translate_with_backend(en_glosses, "en", target, backend_type)
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
    batch_size: int = 50,
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

    PERFORMANCE: All words from all sentences are batched together and sent
    in large batches to minimize API calls (e.g., 50 words per request).

    Args:
        unique_sentences: Unique source sentences to translate word-by-word
        source_lang: Source language code
        target_lang: Target language code
        api_key: DeepL API key
        endpoint: DeepL API endpoint
        min_words: Minimum number of final words/groups required (default: 3)
        batch_size: Words per API request (default: 50)

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

    # Collect ALL unique words across all sentences for batch translation
    all_words: list[str] = []
    word_to_index: dict[str, int] = {}  # Map word to its index in all_words

    for groups in sentence_word_groups.values():
        for _, clean in groups:
            if clean not in word_to_index:
                word_to_index[clean] = len(all_words)
                all_words.append(clean)

    console.print(f"  Translating {len(all_words)} unique words in batches of {batch_size}...")

    # Translate all words in parallel batches
    all_translations: list[str] = [""] * len(all_words)

    # Create batch ranges
    batch_ranges = [
        (batch_start, min(batch_start + batch_size, len(all_words)))
        for batch_start in range(0, len(all_words), batch_size)
    ]

    def translate_batch(batch_range: tuple[int, int]) -> tuple[int, int, list[str]]:
        """Translate a single batch and return (start, end, translations)."""
        start, end = batch_range
        batch_words = all_words[start:end]
        translations = _translate_word_batch(
            batch_words, source_lang, target_lang, api_key, endpoint
        )
        return start, end, translations

    # Use ThreadPoolExecutor for parallel API calls (I/O bound)
    # Limit workers to avoid overwhelming the API
    max_workers = min(4, len(batch_ranges))
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(translate_batch, br): br for br in batch_ranges}

        for future in as_completed(futures):
            start, end, translations = future.result()
            for i, trans in enumerate(translations):
                all_translations[start + i] = trans
            completed += end - start
            console.print(
                f"  Translated {completed}/{len(all_words)} words",
                end="\r",
            )

    console.print(f"  Translated {len(all_words)} unique words                    ")

    # Build results using the pre-translated words
    result: dict[str, list[tuple[str, str]]] = {}
    failed_sentences: set[str] = set()

    for sentence, groups in sentence_word_groups.items():
        clean_words = [clean for _, clean in groups]
        translations = [all_translations[word_to_index[clean]] for clean in clean_words]

        # Check if any words failed to translate
        if _has_untranslated_words(clean_words, translations):
            failed_sentences.add(sentence)
            continue  # Skip this sentence, don't add to result

        # Build result with display words paired with translations
        result[sentence] = [
            (display, translations[j] if j < len(translations) else clean)
            for j, (display, clean) in enumerate(groups)
        ]

    if failed_sentences:
        console.print(
            f"[yellow]  {len(failed_sentences)} sentences had untranslated words[/yellow]"
        )
    console.print(
        f"[green]  Translated {len(all_words)} unique words across {len(result)} sentences[/green]"
    )
    return result, failed_sentences


def translate_words_literal_with_backend(
    unique_sentences: list[str],
    source_lang: str,
    target_lang: str,
    backend_type: BackendType = BackendType.AUTO,
    min_words: int = 3,
    word_hints: dict[str, list[str]] | None = None,
) -> tuple[dict[str, list[tuple[str, str]]], set[str]]:
    """
    Get word-by-word literal translations using the backend system.

    Same as translate_words_literal but uses the modular backend system
    instead of requiring DeepL API key.

    Args:
        unique_sentences: Unique source sentences to translate word-by-word
        source_lang: Source language code
        target_lang: Target language code
        backend_type: Translation backend to use
        min_words: Minimum number of final words/groups required (default: 3)
        word_hints: Optional dict mapping word to list of meanings for context

    Returns:
        Tuple of:
        - Dict mapping sentence to list of (display_word, translation) tuples
        - Set of sentences that failed (had untranslated words)
    """
    if not unique_sentences:
        return {}, set()

    backend = get_backend(backend_type)
    if backend is None:
        console.print("[yellow]No backend available for literal translations[/yellow]")
        return {}, set()

    console.print(
        f"[blue]Getting word-by-word translations for {len(unique_sentences)} sentences "
        f"with {backend.name}...[/blue]"
    )

    # Map sentence -> list of (display_group, clean_group)
    sentence_word_groups: dict[str, list[tuple[str, str]]] = {}

    for sentence in unique_sentences:
        # Tokenize preserving punctuation
        words_with_punct = _tokenize_with_punctuation(sentence)
        # Merge single-letter particles
        # merged = _merge_single_letter_particles(words_with_punct)
        merged = words_with_punct

        # Filter out sentences with fewer than min_words
        if len(merged) < min_words:
            continue

        sentence_word_groups[sentence] = merged

    if not sentence_word_groups:
        return {}, set()

    # Collect ALL unique words across all sentences
    all_words: list[str] = []
    word_to_index: dict[str, int] = {}

    for groups in sentence_word_groups.values():
        for _, clean in groups:
            if clean not in word_to_index:
                word_to_index[clean] = len(all_words)
                all_words.append(clean)

    console.print(f"  Translating {len(all_words)} unique words...")

    # Get hints for LLM backends
    hints = get_hints(source_lang)

    # Translate all words using backend
    all_translations = backend.translate_words(
        words=all_words,
        source_lang=source_lang,
        target_lang=target_lang,
        hints=hints,
        word_hints=word_hints,
    )

    console.print(f"  Translated {len(all_words)} unique words")

    # Build results using the translated words
    result: dict[str, list[tuple[str, str]]] = {}
    failed_sentences: set[str] = set()

    for sentence, groups in sentence_word_groups.items():
        clean_words = [clean for _, clean in groups]
        translations = [all_translations[word_to_index[clean]] for clean in clean_words]

        # Check if any words failed to translate
        if _has_untranslated_words(clean_words, translations):
            failed_sentences.add(sentence)
            continue

        # Build result with display words paired with translations
        result[sentence] = [
            (display, translations[j] if j < len(translations) else clean)
            for j, (display, clean) in enumerate(groups)
        ]

    if failed_sentences:
        console.print(
            f"[yellow]  {len(failed_sentences)} sentences had untranslated words[/yellow]"
        )
    console.print(f"[green]  Word-by-word translations for {len(result)} sentences[/green]")
    return result, failed_sentences
