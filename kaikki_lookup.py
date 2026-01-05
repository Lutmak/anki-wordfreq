#!/usr/bin/env python3
"""
Russian Word Viewer for Wiktextract Dictionary Data
Displays comprehensive information about Russian words for language learning and Anki flashcards.

For faster lookups, download per-language dumps with
`download_language_dicts.py` so this script can read
`language-dicts/<lang>.jsonl` instead of the 22GB combined file.
"""

import io
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

try:
    from download_language_dicts import LANGUAGE_SOURCES, download_language
except ImportError:  # pragma: no cover - fallback when helper unavailable
    LANGUAGE_SOURCES = {}

    def download_language(lang_code, dest_dir, force=False):  # type: ignore
        raise RuntimeError(
            "download_language_dicts.py is unavailable. Run it manually to fetch dictionaries."
        )


PROGRESS_INTERVAL = 100000

# --- Simple script configuration (edit as needed) ---
TARGET_WORDS = ["в", "на"]
LANG_CODE = "ru"
STOP_AFTER_FOUND = True
LANGUAGE_DICT_DIR = Path("language-dicts")


def language_dict_path(lang_code: str) -> Path:
    """Return the expected filesystem path for a downloaded per-language dict."""

    return LANGUAGE_DICT_DIR / f"{lang_code}.jsonl"


def get_language_dictionary(lang_code: str) -> str:
    """Ensure the per-language dictionary exists and return its path."""

    path = language_dict_path(lang_code)
    if not path.exists():
        if lang_code not in LANGUAGE_SOURCES:
            print(
                "Dictionary file not found: {path}.\n"
                "Language '{lang}' is not supported by download_language_dicts.py yet.".format(
                    path=path, lang=lang_code
                )
            )
            sys.exit(1)

        print(
            f"Dictionary file not found locally ({path}). Attempting to download from kaikki.org..."
        )
        try:
            download_language(lang_code, LANGUAGE_DICT_DIR)
        except Exception as exc:  # noqa: BLE001
            print(
                "Failed to download dictionary for '{lang}': {err}".format(
                    lang=lang_code, err=exc
                )
            )
            print(
                "Try running 'python download_language_dicts.py --languages {lang}' manually.".format(
                    lang=lang_code
                )
            )
            sys.exit(1)

    return str(path)


def open_dictionary_stream(filepath: str):
    """Return a text stream for JSONL files, supporting common compression formats."""
    path = Path(filepath)
    suffix = path.suffix.lower()

    if suffix == ".gz":
        import gzip

        return gzip.open(path, "rt", encoding="utf-8")
    if suffix in {".bz2", ".bzip2"}:
        import bz2

        return bz2.open(path, "rt", encoding="utf-8")
    if suffix in {".xz", ".lzma"}:
        import lzma

        return lzma.open(path, "rt", encoding="utf-8")
    if suffix == ".zst":
        try:
            import zstandard as zstd
        except ImportError as exc:
            raise RuntimeError(
                "Reading .zst files requires the 'zstandard' package."
            ) from exc

        dctx = zstd.ZstdDecompressor()
        reader = dctx.stream_reader(path.open("rb"))
        return io.TextIOWrapper(reader, encoding="utf-8")

    return path.open("r", encoding="utf-8")


def load_dictionary(
    filepath: str,
    target_words: List[str],
    lang_code: Optional[str] = None,
    stop_when_all_found: bool = False,
) -> List[Dict]:
    """Load dictionary entries for specific target words."""

    entries: List[Dict] = []
    target_words_lower = {w.lower() for w in target_words if w.strip()}
    found_words = set()

    if not target_words_lower:
        print("No valid target words supplied.")
        return entries

    print(f"Loading dictionary from {filepath}...")
    print(f"Searching for words: {', '.join(target_words)}\n")

    try:
        with open_dictionary_stream(filepath) as f:
            for line_num, line in enumerate(f, 1):
                if line_num % PROGRESS_INTERVAL == 0:
                    print(f"Processed {line_num:,} lines...", end="\r")

                stripped = line.strip()
                if not stripped:
                    continue

                try:
                    entry = json.loads(stripped)
                except json.JSONDecodeError:
                    continue

                if lang_code and entry.get("lang_code") != lang_code:
                    continue

                word_lower = entry.get("word", "").lower()
                if word_lower in target_words_lower:
                    entries.append(entry)
                    found_words.add(word_lower)

                    # Only stop if we found at least one entry for each target word
                    # and stop_when_all_found is True
                    if stop_when_all_found and found_words == target_words_lower:
                        break

        print(f"\nFound {len(entries)} entries for language '{lang_code or 'any'}'")
        missing = target_words_lower - found_words
        if missing:
            print(f"Still missing: {', '.join(sorted(missing))}")
        return entries

    except FileNotFoundError:
        print(f"Error: Dictionary file '{filepath}' not found!")
        sys.exit(1)


def format_tags(tags: List[str]) -> str:
    """Format tags into a readable string."""
    if not tags:
        return ""
    return f"({', '.join(tags)})"


def format_ipa(sounds: List[Dict]) -> List[str]:
    """Extract and format IPA pronunciations."""
    ipas = []
    for sound in sounds:
        if "ipa" in sound:
            tags = sound.get("tags", [])
            tag_str = format_tags(tags)
            ipas.append(f"{sound['ipa']} {tag_str}".strip())
    return ipas


def format_audio(sounds: List[Dict]) -> List[str]:
    """Extract audio file information."""
    audios = []
    for sound in sounds:
        if "audio" in sound:
            audio_info = f"🔊 {sound['audio']}"
            if "ogg_url" in sound:
                audio_info += f" [{sound['ogg_url']}]"
            audios.append(audio_info)
    return audios


def get_etymology_info(entry: Dict) -> Optional[str]:
    """Extract etymology information."""
    if "etymology_text" in entry:
        # Truncate if too long
        etym = entry["etymology_text"]
        if len(etym) > 300:
            etym = etym[:297] + "..."
        return etym
    return None


def get_word_forms(forms: List[Dict]) -> Dict[str, List[str]]:
    """Group word forms by type."""
    forms_by_type = defaultdict(list)

    for form_entry in forms:
        form = form_entry.get("form", "")
        tags = form_entry.get("tags", [])

        if form and form != "-":
            # Create a readable tag string
            tag_key = ", ".join(sorted(tags)) if tags else "other"
            forms_by_type[tag_key].append(form)

    return dict(forms_by_type)


def get_english_meanings(sense: Dict) -> List[str]:
    """Collect all available English descriptions for a sense."""

    meanings: List[str] = []

    glosses = sense.get("glosses") or []
    for gloss in glosses:
        if gloss and gloss not in meanings:
            meanings.append(gloss)

    english_field = sense.get("english")
    if english_field and english_field not in meanings:
        meanings.append(english_field)

    translations = sense.get("translations") or []
    for translation in translations:
        lang = translation.get("lang")
        code = translation.get("code")
        if lang == "English" or code == "en":
            text = translation.get("word") or translation.get("english")
            if text and text not in meanings:
                note = translation.get("sense") or translation.get("note")
                if note:
                    text = f"{text} ({note})"
                meanings.append(text)

    if not meanings:
        raw_glosses = sense.get("raw_glosses") or []
        for raw in raw_glosses:
            if raw and raw not in meanings:
                meanings.append(raw)

    return meanings


def format_sense(sense: Dict, sense_num: int, total_senses: int) -> str:
    """Format a single word sense with examples."""
    output = []

    english_meanings = get_english_meanings(sense)
    if english_meanings:
        header = f"[{sense_num}] " if total_senses > 1 else ""
        output.append(f"  {header}English meanings:")
        for meaning in english_meanings:
            output.append(f"      - {meaning}")
    else:
        if total_senses > 1:
            output.append(f"  [{sense_num}] (no English gloss available)")
        else:
            output.append("  (no English gloss available)")

    # Tags and qualifiers
    tags = sense.get("tags", [])
    if tags:
        output.append(f"      Tags: {', '.join(tags)}")

    # Topics
    topics = sense.get("topics", [])
    if topics:
        output.append(f"      Topics: {', '.join(topics)}")

    # Examples (limit to 2 general examples as requested)
    examples = sense.get("examples", [])
    if examples:
        output.append("      Examples:")
        for i, ex in enumerate(examples[:2], 1):
            text = ex.get("text", "")
            english = ex.get("english", "")

            if text:
                output.append(f"        • {text}")
                if english:
                    output.append(f"          → {english}")

    return "\n".join(output)


def display_word_entry(entry: Dict):
    """Display comprehensive information about a word entry."""
    word = entry.get("word", "")
    pos = entry.get("pos", "unknown")

    print("=" * 80)
    print(f"WORD: {word}")
    print(f"Part of Speech: {pos.upper()}")
    print("=" * 80)

    # Pronunciation
    sounds = entry.get("sounds", [])
    if sounds:
        print("\n📢 PRONUNCIATION:")

        ipas = format_ipa(sounds)
        if ipas:
            print("  IPA:")
            for ipa in ipas:
                print(f"    {ipa}")

        audios = format_audio(sounds)
        if audios:
            print("  Audio:")
            for audio in audios:
                print(f"    {audio}")

    # Etymology
    etymology = get_etymology_info(entry)
    if etymology:
        print(f"\n📚 ETYMOLOGY:")
        print(f"  {etymology}")

    # Word Forms (declensions/conjugations)
    forms = entry.get("forms", [])
    if forms:
        print(f"\n📋 WORD FORMS:")
        forms_grouped = get_word_forms(forms)

        for form_type, form_list in sorted(forms_grouped.items()):
            print(f"  {form_type}:")
            for form in form_list:
                print(f"    • {form}")

    # Senses (meanings)
    senses = entry.get("senses", [])
    if senses:
        print(f"\n💡 MEANINGS ({len(senses)} sense{'s' if len(senses) != 1 else ''}):")
        for i, sense in enumerate(senses, 1):
            print()
            print(format_sense(sense, i, len(senses)))

    # Categories
    categories = entry.get("categories", [])
    if categories:
        print(f"\n🏷️  CATEGORIES:")
        print(f"  {', '.join(categories)}")

    # Wikidata/Wikipedia links
    if "wikidata" in entry:
        print(f"\n🔗 WIKIDATA: {entry['wikidata']}")

    if "wikipedia" in entry:
        wiki = entry["wikipedia"]
        if isinstance(wiki, list):
            wiki = ", ".join(wiki)
        print(f"🔗 WIKIPEDIA: {wiki}")

    print("\n")


def main():
    """Main function to run the word viewer."""
    dictionary_file = get_language_dictionary(LANG_CODE)
    print(f"Using dictionary file: {dictionary_file}")

    entries = load_dictionary(
        dictionary_file,
        TARGET_WORDS,
        lang_code=LANG_CODE,
        stop_when_all_found=STOP_AFTER_FOUND,
    )

    if not entries:
        print(f"No entries found for the specified word(s) in language '{LANG_CODE}'.")
        return

    # Group entries by word
    entries_by_word = defaultdict(list)
    for entry in entries:
        entries_by_word[entry["word"]].append(entry)

    # Display entries
    for word in TARGET_WORDS:
        word_entries = entries_by_word.get(word, [])
        if not word_entries:
            print(f"\n⚠️  No entries found for '{word}'")
            continue

        for entry in word_entries:
            display_word_entry(entry)


if __name__ == "__main__":
    main()
