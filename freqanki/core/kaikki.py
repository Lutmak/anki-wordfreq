"""Wiktextract/Kaikki dictionary utilities."""

import bz2
import gzip
import json
import lzma
import os
import re
import urllib.request
from collections import defaultdict
from pathlib import Path

from freqanki.utils.console import console, create_progress

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

# POS priority for selecting entries
POS_PRIORITY = {
    "pron": 1,
    "verb": 2,
    "noun": 3,
    "adj": 4,
    "adv": 5,
    "conj": 6,
    "prep": 7,
    "character": 10,
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

    with open(dict_path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Check if entry matches our language and words
            entry_lang = entry.get("lang_code", "")
            entry_word = entry.get("word", "").lower()

            if entry_lang == lang_code and entry_word in lookup_set:
                grouped[entry_word].append(entry)
                found.add(entry_word)

            # Progress indicator every 100k lines
            if line_num % 100000 == 0:
                console.print(
                    f"  Scanned {line_num:,} entries, found {len(found)}/{len(lookup_set)}...",
                    end="\r",
                )

    console.print(f"  Loaded entries for {len(found)}/{len(lookup_set)} words        ")
    return dict(grouped)


def get_english_meanings(sense: dict) -> list[str]:
    """Extract English meanings from a Kaikki sense."""
    meanings = []

    # Primary glosses
    for gloss in sense.get("glosses", []):
        if gloss:
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
            if raw:
                meanings.append(raw)

    return meanings


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

    # Sort by POS priority
    sorted_entries = sorted(entries, key=_entry_sort_key)

    # Use only highest priority group
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
