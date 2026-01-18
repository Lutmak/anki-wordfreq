"""Wiktextract/Kaikki dictionary utilities."""

import bz2
import gzip
import json
import lzma
import re
import unicodedata
import urllib.request
from collections import defaultdict
from pathlib import Path

from freqanki.utils.console import console


def _strip_accents(text: str) -> str:
    """Strip combining diacritical marks (like stress marks) from text."""
    # Normalize to decomposed form, then remove combining marks
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


# Kaikki download URLs by language
KAIKKI_URLS = {
    "ar": "https://kaikki.org/dictionary/Arabic/kaikki.org-dictionary-Arabic.jsonl",
    "cs": "https://kaikki.org/dictionary/Czech/kaikki.org-dictionary-Czech.jsonl",
    "de": "https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl",
    "el": "https://kaikki.org/dictionary/Greek/kaikki.org-dictionary-Greek.jsonl",
    "en": "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl",
    "es": "https://kaikki.org/dictionary/Spanish/kaikki.org-dictionary-Spanish.jsonl",
    "fi": "https://kaikki.org/dictionary/Finnish/kaikki.org-dictionary-Finnish.jsonl",
    "fr": "https://kaikki.org/dictionary/French/kaikki.org-dictionary-French.jsonl",
    "he": "https://kaikki.org/dictionary/Hebrew/kaikki.org-dictionary-Hebrew.jsonl",
    "hi": "https://kaikki.org/dictionary/Hindi/kaikki.org-dictionary-Hindi.jsonl",
    "hu": "https://kaikki.org/dictionary/Hungarian/kaikki.org-dictionary-Hungarian.jsonl",
    "id": "https://kaikki.org/dictionary/Indonesian/kaikki.org-dictionary-Indonesian.jsonl",
    "it": "https://kaikki.org/dictionary/Italian/kaikki.org-dictionary-Italian.jsonl",
    "ja": "https://kaikki.org/dictionary/Japanese/kaikki.org-dictionary-Japanese.jsonl",
    "ko": "https://kaikki.org/dictionary/Korean/kaikki.org-dictionary-Korean.jsonl",
    "nl": "https://kaikki.org/dictionary/Dutch/kaikki.org-dictionary-Dutch.jsonl",
    "pl": "https://kaikki.org/dictionary/Polish/kaikki.org-dictionary-Polish.jsonl",
    "pt": "https://kaikki.org/dictionary/Portuguese/kaikki.org-dictionary-Portuguese.jsonl",
    "ru": "https://kaikki.org/dictionary/Russian/kaikki.org-dictionary-Russian.jsonl",
    "sv": "https://kaikki.org/dictionary/Swedish/kaikki.org-dictionary-Swedish.jsonl",
    "th": "https://kaikki.org/dictionary/Thai/kaikki.org-dictionary-Thai.jsonl",
    "tr": "https://kaikki.org/dictionary/Turkish/kaikki.org-dictionary-Turkish.jsonl",
    "uk": "https://kaikki.org/dictionary/Ukrainian/kaikki.org-dictionary-Ukrainian.jsonl",
    "vi": "https://kaikki.org/dictionary/Vietnamese/kaikki.org-dictionary-Vietnamese.jsonl",
    "zh": "https://kaikki.org/dictionary/Chinese/kaikki.org-dictionary-Chinese.jsonl",
}

# POS priority for selecting entries (lower = higher priority)
# Function words (particles, conjunctions, prepositions) are prioritized
# because for common words they often have the best/simplest definitions.
# Nouns are lower priority because single-letter words often have
# "letter name" entries as nouns (e.g., "и" as "the letter И").
POS_PRIORITY = {
    "pron": 1,  # pronouns: он, она, это, я
    "verb": 2,  # verbs: быть, делать
    "particle": 3,  # particles: не, же, ли
    "conj": 4,  # conjunctions: и, но, что
    "prep": 5,  # prepositions: в, на, с, к
    "det": 6,  # determiners: это, весь
    "adj": 7,  # adjectives
    "adv": 8,  # adverbs
    "intj": 9,  # interjections
    "noun": 10,  # nouns (lower because letter names are nouns)
    "name": 11,  # proper names
    "prefix": 12,  # prefixes
    "character": 99,  # always skip
    "symbol": 99,  # always skip
}

# Words to skip in Kaikki lookups
KAIKKI_SKIP_WORDS = {"нибудь", "нибыть"}


def get_dictionary_path(lang_code: str, dict_dir: Path) -> Path:
    """Get the path to a language dictionary file."""
    return dict_dir / f"{lang_code}.jsonl"


def download_dictionary(lang_code: str, dict_dir: Path) -> Path:
    """
    Download a Kaikki dictionary for a language.

    Args:
        lang_code: ISO language code
        dict_dir: Directory to save dictionary

    Returns:
        Path to downloaded dictionary

    Raises:
        ValueError: If language not supported
    """
    if lang_code not in KAIKKI_URLS:
        raise ValueError(f"No Kaikki dictionary available for language: {lang_code}")

    url = KAIKKI_URLS[lang_code]
    dest_path = get_dictionary_path(lang_code, dict_dir)

    if dest_path.exists():
        return dest_path

    dict_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"[blue]Downloading {lang_code} dictionary from Kaikki...[/blue]")

    # Try compressed versions first
    for ext in [".zst", ".bz2", ".gz", ".xz", ""]:
        try_url = url + ext if ext else url
        temp_path = dest_path.with_suffix(dest_path.suffix + ext)

        try:
            urllib.request.urlretrieve(try_url, temp_path)

            # Decompress if needed
            if ext == ".gz":
                with gzip.open(temp_path, "rb") as f_in:
                    with open(dest_path, "wb") as f_out:
                        f_out.write(f_in.read())
                temp_path.unlink()
            elif ext == ".bz2":
                with bz2.open(temp_path, "rb") as f_in:
                    with open(dest_path, "wb") as f_out:
                        f_out.write(f_in.read())
                temp_path.unlink()
            elif ext == ".xz":
                with lzma.open(temp_path, "rb") as f_in:
                    with open(dest_path, "wb") as f_out:
                        f_out.write(f_in.read())
                temp_path.unlink()
            elif ext == ".zst":
                try:
                    import zstandard as zstd

                    with open(temp_path, "rb") as f_in:
                        dctx = zstd.ZstdDecompressor()
                        with open(dest_path, "wb") as f_out:
                            dctx.copy_stream(f_in, f_out)
                    temp_path.unlink()
                except ImportError:
                    temp_path.unlink()
                    continue
            elif ext == "":
                # No compression, already at dest
                if temp_path != dest_path:
                    temp_path.rename(dest_path)

            console.print(f"[green]Downloaded {lang_code} dictionary[/green]")
            return dest_path

        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            continue

    raise RuntimeError(f"Failed to download dictionary for {lang_code}")


def ensure_dictionary(lang_code: str, dict_dir: Path) -> Path:
    """
    Ensure dictionary exists, downloading if needed.

    Args:
        lang_code: ISO language code
        dict_dir: Directory for dictionaries

    Returns:
        Path to dictionary file
    """
    path = get_dictionary_path(lang_code, dict_dir)
    if path.exists():
        return path
    return download_dictionary(lang_code, dict_dir)


def load_entries_for_words(
    dict_path: Path,
    words: list[str],
    lang_code: str,
) -> dict[str, list[dict]]:
    """
    Load Kaikki entries for specific words.

    Also loads base words referenced by form_of entries, so inflected forms
    like "книги" can look up their base word "книга" for meanings.

    Args:
        dict_path: Path to JSONL dictionary
        words: Words to look up
        lang_code: Language code for filtering

    Returns:
        Dict mapping lowercase words to list of entries
    """
    if not dict_path.exists():
        return {}

    # Build lookup set
    lookup_set = {w.lower() for w in words if w not in KAIKKI_SKIP_WORDS}
    if not lookup_set:
        return {}

    grouped: dict[str, list[dict]] = defaultdict(list)
    found: set[str] = set()

    # First pass: load requested words
    with open(dict_path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_lang = entry.get("lang_code", "")
            entry_word = entry.get("word", "").lower()

            if entry_lang == lang_code and entry_word in lookup_set:
                grouped[entry_word].append(entry)
                found.add(entry_word)

            if line_num % 100000 == 0:
                console.print(
                    f"  Scanned {line_num:,} entries, found {len(found)}/{len(lookup_set)}...",
                    end="\r",
                )

    console.print(f"  Loaded entries for {len(found)}/{len(lookup_set)} words        ")

    # Collect base words from form_of references that we don't have yet
    base_words_needed: set[str] = set()
    for word_entries in grouped.values():
        for entry in word_entries:
            for sense in entry.get("senses", []) or []:
                for form_of in sense.get("form_of", []):
                    if isinstance(form_of, dict) and form_of.get("word"):
                        base = _strip_accents(form_of["word"]).lower()
                        if base not in grouped:
                            base_words_needed.add(base)

    # Second pass: load base words if any are needed
    if base_words_needed:
        console.print(f"  Loading {len(base_words_needed)} base words for inflected forms...")
        with open(dict_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_lang = entry.get("lang_code", "")
                entry_word = entry.get("word", "").lower()

                if entry_lang == lang_code and entry_word in base_words_needed:
                    grouped[entry_word].append(entry)

    return dict(grouped)


def get_english_meanings(sense: dict) -> list[str]:
    """Extract English meanings from a Kaikki sense.

    Skips "form-of" definitions (like "genitive of X") as these are
    grammatical references, not actual meanings.

    Prioritizes the 'links' field which contains clean English words
    (e.g., [['he', 'he'], ['it', 'it']]) over 'glosses' which may contain
    grammatical descriptions.
    """
    # Skip form-of senses - they contain grammatical info, not meanings
    if sense.get("form_of"):
        return []

    tags = sense.get("tags", [])
    if "form-of" in tags:
        return []

    meanings = []

    # Primary source: links field (contains clean English words)
    # Format: [['he', 'he'], ['it', 'it']] or [['word', 'link_target']]
    # Filter out links to non-English (e.g., ['бы', 'бы#Russian'])
    for link in sense.get("links", []):
        if isinstance(link, list) and len(link) >= 2:
            word = link[0]
            target = link[1] if len(link) > 1 else ""
            # Skip links that reference non-English words (contain #Russian, #French, etc.)
            if "#" in target and not target.endswith("#English"):
                continue
            # Skip links to appendices (e.g., Appendix:Cyrillic script)
            if target.startswith("Appendix:"):
                continue
            # Skip if the word itself contains Cyrillic (not English)
            if word and any("\u0400" <= c <= "\u04ff" for c in word):
                continue
            # Skip grammatical terms that aren't translations
            skip_terms = {
                "singular",
                "plural",
                "demonstrative pronoun",
                "demonstrative determiner",
                "personal pronoun",
            }
            if word and word.lower() in skip_terms:
                continue
            if word and isinstance(word, str):
                meanings.append(word)
        elif isinstance(link, list) and len(link) == 1:
            word = link[0]
            # Skip Cyrillic words
            if word and any("\u0400" <= c <= "\u04ff" for c in word):
                continue
            if word and isinstance(word, str):
                meanings.append(word)

    # If we got meanings from links, return those (they're cleaner)
    if meanings:
        return meanings

    # Fallback: glosses (may have grammatical descriptions)
    for gloss in sense.get("glosses", []):
        if gloss:
            # Skip glosses that are just grammatical form references
            if _is_form_of_gloss(gloss):
                continue
            # Skip glosses about letter/script names (not useful for flashcards)
            if _is_letter_gloss(gloss):
                continue
            # Skip glosses that are descriptive rather than translations
            if _is_descriptive_gloss(gloss):
                continue
            meanings.append(gloss)

    # English field
    english = sense.get("english")
    if english:
        meanings.append(english)

    # Translations to English
    for trans in sense.get("translations", []):
        if trans.get("lang") == "English" and trans.get("word"):
            meanings.append(trans["word"])

    # Raw glosses as fallback
    if not meanings:
        for raw in sense.get("raw_glosses", []):
            if raw and not _is_form_of_gloss(raw):
                meanings.append(raw)

    return meanings


def _is_form_of_gloss(gloss: str) -> bool:
    """Check if a gloss is just a grammatical form reference.

    Examples that should return True:
    - "genitive/accusative of он (on)"
    - "plural of дом"
    - "past tense of делать"
    """
    import re

    # Pattern: starts with grammatical term + " of "
    form_of_pattern = re.compile(
        r"^(?:genitive|accusative|dative|instrumental|prepositional|locative|"
        r"nominative|vocative|plural|singular|masculine|feminine|neuter|"
        r"past|present|future|imperative|infinitive|participle|gerund|"
        r"perfective|imperfective|comparative|superlative|diminutive|"
        r"first-person|second-person|third-person|short form|"
        r"[a-z]+/[a-z]+)"  # handles "genitive/accusative"
        r"\s+(?:of|form of)\s+",
        re.IGNORECASE,
    )
    return bool(form_of_pattern.match(gloss))


def _is_letter_gloss(gloss: str) -> bool:
    """Check if a gloss is about letter/script names (not useful for flashcards).

    Examples that should return True:
    - "The name of the Cyrillic script letter Я."
    - "The thirty-third letter of the Russian alphabet"
    - "alternative letter-case form of я (ja)."
    - "Yi (an ethnic group of southwestern China)" - letter names as proper nouns
    """
    gloss_lower = gloss.lower()
    letter_patterns = [
        "letter of the",
        "script letter",
        "letter-case form",
        "the name of the",
        "cyrillic script",
        "russian alphabet",
        # Letter names that are often misidentified as nouns
        "an ethnic group",  # "Yi" for letter И
    ]
    return any(p in gloss_lower for p in letter_patterns)


def _is_descriptive_gloss(gloss: str) -> bool:
    """Check if a gloss is a description rather than a translation.

    Glosses that describe usage rather than provide a translation are not
    useful for flashcards. We want short, clean translations like "and",
    "but", "in" - not descriptions like "Used as an emphasiser".

    Examples that should return True:
    - "Used as an emphasiser, including in a few set phrases."
    - "To emphasise the truth of a verb"
    - "[with prepositional]" (grammatical marker)
    - "same as X" (cross-reference)
    - "As other emphasis or in set phrases" (usage description)
    """
    gloss_lower = gloss.lower()

    # Descriptions that start with certain patterns
    descriptive_starts = [
        "used as",
        "used to",
        "used for",
        "to emphasise",
        "to emphasize",
        "to express",
        "to indicate",
        "to introduce",
        "same as",
        "see also",
        "compare ",
        "cf. ",
        "as other",  # "As other emphasis..."
        "as a ",  # "As a conjunction..."
        "demonstrative pronoun",
        "demonstrative determiner",
        "singular",  # grammatical label
        "plural",  # grammatical label
    ]

    # Grammatical markers in brackets
    if gloss.startswith("[with ") or gloss.startswith("["):
        return True

    # Contains non-ASCII (likely non-English translation like Russian)
    if any(ord(c) > 127 for c in gloss):
        return True

    return any(gloss_lower.startswith(p) for p in descriptive_starts)


def _entry_sort_key(entry: dict) -> tuple[int, int]:
    """Sort key for prioritizing Kaikki entries."""
    pos = entry.get("pos", "")
    priority = POS_PRIORITY.get(pos, 8)
    etymology = entry.get("etymology_number", 1)
    return (priority, etymology)


def get_glosses_for_word(
    word: str,
    grouped_entries: dict[str, list[dict]],
    limit: int = 3,
) -> list[str]:
    """
    Get English glosses for a word from Kaikki entries.

    For inflected forms (like "него" which is genitive of "он"), this will
    look up the base word's meaning if the inflected form only has
    grammatical descriptions.

    Args:
        word: Word to look up
        grouped_entries: Pre-loaded entries grouped by word
        limit: Maximum glosses to return

    Returns:
        List of English meanings
    """
    entries = grouped_entries.get(word.lower())
    if not entries:
        return []

    # Sort by POS priority (but don't filter - some high-priority entries
    # may be form-of with no real meanings)
    sorted_entries = sorted(entries, key=_entry_sort_key)

    meanings: list[str] = []
    seen_lower: set[str] = set()
    base_words: set[str] = set()  # Track base words for fallback

    # POS types to skip entirely (not useful for language learning)
    skip_pos = {"character", "symbol", "punctuation mark"}

    for entry in sorted_entries:
        # Skip entries that aren't useful for flashcards
        if entry.get("pos", "") in skip_pos:
            continue

        for sense in entry.get("senses", []) or []:
            # Collect base words from form_of references for fallback
            # Strip accents since dictionary uses stress marks (кни́га) but
            # our index uses plain words (книга)
            for form_of in sense.get("form_of", []):
                if isinstance(form_of, dict) and form_of.get("word"):
                    base_word = _strip_accents(form_of["word"]).lower()
                    base_words.add(base_word)

            for meaning in get_english_meanings(sense):
                clean = meaning.strip()
                if not clean:
                    continue
                lower = clean.lower()
                if lower in seen_lower:
                    continue
                meanings.append(clean)
                seen_lower.add(lower)
                if len(meanings) >= limit:
                    return meanings

    # If no meanings found but we have base words, look them up
    if not meanings and base_words:
        for base_word in base_words:
            base_meanings = _get_base_word_meanings(base_word, grouped_entries, limit)
            for meaning in base_meanings:
                lower = meaning.lower()
                if lower not in seen_lower:
                    meanings.append(meaning)
                    seen_lower.add(lower)
                    if len(meanings) >= limit:
                        return meanings

    return meanings


def _get_base_word_meanings(
    word: str,
    grouped_entries: dict[str, list[dict]],
    limit: int = 3,
) -> list[str]:
    """Get meanings for a base word (non-recursive, no form-of lookup)."""
    entries = grouped_entries.get(word.lower())
    if not entries:
        return []

    sorted_entries = sorted(entries, key=_entry_sort_key)
    if sorted_entries:
        top_priority = _entry_sort_key(sorted_entries[0])[0]
        sorted_entries = [e for e in sorted_entries if _entry_sort_key(e)[0] == top_priority]

    meanings: list[str] = []
    seen_lower: set[str] = set()

    for entry in sorted_entries:
        for sense in entry.get("senses", []) or []:
            for meaning in get_english_meanings(sense):
                clean = meaning.strip()
                if not clean:
                    continue
                lower = clean.lower()
                if lower in seen_lower:
                    continue
                meanings.append(clean)
                seen_lower.add(lower)
                if len(meanings) >= limit:
                    return meanings

    return meanings


def get_audio_url_for_word(
    word: str,
    grouped_entries: dict[str, list[dict]],
) -> str | None:
    """
    Get audio URL for a word from Kaikki entries.

    Args:
        word: Word to look up
        grouped_entries: Pre-loaded entries grouped by word

    Returns:
        Audio URL or None
    """
    entries = grouped_entries.get(word.lower())
    if not entries:
        return None

    sorted_entries = sorted(entries, key=_entry_sort_key)

    for entry in sorted_entries:
        sounds = entry.get("sounds") or []
        for sound in sounds:
            url = sound.get("mp3_url") or sound.get("ogg_url")
            if url:
                return url

    return None


def get_romanization_for_word(
    word: str,
    grouped_entries: dict[str, list[dict]],
) -> str | None:
    """
    Get romanization for a word from Kaikki entries.

    Args:
        word: Word to look up
        grouped_entries: Pre-loaded entries grouped by word

    Returns:
        Romanization or None
    """
    entries = grouped_entries.get(word.lower())
    if not entries:
        return None

    sorted_entries = sorted(entries, key=_entry_sort_key)

    for entry in sorted_entries:
        # Check forms for romanization tag
        for form in entry.get("forms", []) or []:
            tags = form.get("tags") or []
            if "romanization" in tags and form.get("form"):
                return form["form"]

        # Check head_templates
        for template in entry.get("head_templates", []) or []:
            expansion = template.get("expansion") or ""
            match = re.search(r"\(([^)]+)\)", expansion)
            if match:
                return match.group(1)

    return None


def get_transliteration_for_word(
    word: str,
    grouped_entries: dict[str, list[dict]],
) -> str | None:
    """
    Get transliteration for a word from Kaikki entries.

    This may include stress marks or other annotations not in the romanization.

    Args:
        word: Word to look up
        grouped_entries: Pre-loaded entries grouped by word

    Returns:
        Transliteration or None
    """
    entries = grouped_entries.get(word.lower())
    if not entries:
        return None

    sorted_entries = sorted(entries, key=_entry_sort_key)

    for entry in sorted_entries:
        # Check forms for transliteration tag
        for form in entry.get("forms", []) or []:
            tags = form.get("tags") or []
            if "transliteration" in tags and form.get("form"):
                return form["form"]

        # Check sounds for IPA (can serve as transliteration)
        for sound in entry.get("sounds", []) or []:
            ipa = sound.get("ipa")
            if ipa:
                return ipa

    return None
