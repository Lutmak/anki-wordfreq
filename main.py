#!/usr/bin/env python3
"""FreqAnki - Generate frequency-based Anki decks with translations"""

import os
import sys
import re
import hashlib
import webbrowser
import tempfile
import json
import html
from collections import defaultdict
from functools import lru_cache

try:
    import requests
    import genanki
    from wordfreq import top_n_list
    from dotenv import load_dotenv
    from tatoebatools import ParallelCorpus
    import pymorphy3
    from kaikki_lookup import (
        get_language_dictionary,
        load_dictionary,
        get_english_meanings,
    )
except ImportError as e:
    print(
        f"Missing: {e}\nRun: pip install wordfreq genanki requests python-dotenv tatoebatools pymorphy3"
    )
    sys.exit(1)

load_dotenv()

# =============================================================================
# CONFIG
# =============================================================================
DEEPL_KEY = os.getenv("DEEPL_API_KEY")
SOURCE = "ru"
TARGETS = ["en", "es"]
NUM_WORDS = 2000
NUM_EXAMPLES = 2
AUDIO_DIR = "audio"

HTTP_HEADERS = {
    "User-Agent": "FreqAnki/1.0 (Language Learning Deck Generator; https://github.com/Lutmak/anki-wordfreq)"
}
# =============================================================================

# Tatoeba language code mapping
TATOEBA_CODES = {
    "en": "eng",
    "es": "spa",
    "fr": "fra",
    "de": "deu",
    "it": "ita",
    "pt": "por",
    "ru": "rus",
    "ja": "jpn",
    "zh": "cmn",
    "ko": "kor",
}

# Wiktionary language mapping
WIKTIONARY_LANG_NAMES = {
    "ru": "Russian",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ar": "Arabic",
    "pl": "Polish",
    "tr": "Turkish",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
    "pt": "Portuguese",
}

CYRILLIC_PATTERN = re.compile(r"[А-Яа-яЁё]")
DIGIT_PATTERN = re.compile(r"^\d+$")
RUS_NUMBER_WORDS = {
    "0": "ноль",
    "1": "один",
    "2": "два",
    "3": "три",
    "4": "четыре",
    "5": "пять",
    "6": "шесть",
    "7": "семь",
    "8": "восемь",
    "9": "девять",
}
SPECIAL_CANONICAL_MAP = {
    "млн": "миллион",
    "тыс": "тысяча",
    "руб": "рубль",
    "ул": "улица",
    "млрд": "миллиард",
    "блн": "миллиард",
}
KAIKKI_SKIP_WORDS = {"нибудь", "нибыть"}


def is_numeric_token(token):
    return bool(DIGIT_PATTERN.fullmatch(token or ""))


def is_allowed_token(token):
    text = (token or "").strip()
    if not text:
        return False
    if is_numeric_token(text):
        return True
    return bool(CYRILLIC_PATTERN.search(text))


def get_frequency_words(source_lang, desired_count, oversample_factor=4):
    if desired_count <= 0:
        return []

    oversample = max(desired_count * oversample_factor, desired_count + 200)
    max_oversample = max(desired_count * 10, oversample)

    while True:
        raw_words = top_n_list(source_lang, oversample)
        filtered = []
        skipped_count = 0
        skipped_samples = []
        seen = set()

        for token in raw_words:
            normalized = token.strip()
            if not normalized or normalized in seen:
                continue

            if not is_allowed_token(normalized):
                skipped_count += 1
                if len(skipped_samples) < 5 and normalized not in skipped_samples:
                    skipped_samples.append(normalized)
                continue

            filtered.append(normalized)
            seen.add(normalized)
            if len(filtered) >= desired_count:
                break

        if len(filtered) >= desired_count or oversample >= max_oversample:
            if skipped_count:
                sample_msg = ", ".join(skipped_samples)
                print(
                    f"ℹ️ Filtered out {skipped_count} non-Russian tokens from the frequency list"
                    + (f" (e.g., {sample_msg})" if sample_msg else "")
                )
            if len(filtered) < desired_count:
                print(
                    f"⚠️ Only {len(filtered)} usable words found out of requested {desired_count}."
                )
            return filtered[:desired_count]

        oversample = min(oversample * 2, max_oversample)


# Morphological analysis mappings
CASE_NAMES = {
    "nomn": "Nominative",
    "gent": "Genitive",
    "datv": "Dative",
    "accs": "Accusative",
    "ablt": "Instrumental",
    "loct": "Prepositional",
}

GENDER_NAMES = {"masc": "Masculine", "femn": "Feminine", "neut": "Neuter"}

NUMBER_NAMES = {"sing": "Singular", "plur": "Plural"}

POS_NAMES = {
    "NOUN": "Noun",
    "VERB": "Verb",
    "ADJF": "Adjective",
    "ADJS": "Short Adjective",
    "ADVB": "Adverb",
    "PREP": "Preposition",
    "CONJ": "Conjunction",
    "PRCL": "Particle",
    "NPRO": "Pronoun",
    "NUMR": "Numeral",
    "INFN": "Infinitive",
}

ANIMACY_NAMES = {"anim": "Animate", "inan": "Inanimate"}

ASPECT_NAMES = {"perf": "Perfective", "impf": "Imperfective"}

TENSE_NAMES = {"past": "Past", "pres": "Present", "futr": "Future"}

PERSON_NAMES = {"1per": "First Person", "2per": "Second Person", "3per": "Third Person"}

MOOD_NAMES = {"indc": "Indicative", "impr": "Imperative"}


def sanitize_filename(text):
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", text)
    return safe.strip("_") or "audio"



def load_kaikki_entries(words, source_lang):
    """Load Kaikki entries for the requested words (best effort)."""
    unique = [w for w in dict.fromkeys(words) if w not in KAIKKI_SKIP_WORDS]
    try:
        dictionary_path = get_language_dictionary(source_lang)
        entries = load_dictionary(
            dictionary_path,
            unique,
            lang_code=source_lang,
            stop_when_all_found=False,
        )

        grouped = defaultdict(list)
        for entry in entries:
            key = entry.get("word", "").lower()
            if key:
                grouped[key].append(entry)
        return grouped
    except Exception as exc:  # noqa: BLE001
        print(f"\nKaikki lookup unavailable: {exc}")
        return {}


def get_audio_for_word(word, grouped_entries):
    entries = grouped_entries.get(word.lower()) if grouped_entries else None
    if not entries:
        return None
    
    # Use the same prioritization as get_kaikki_glosses
    pos_priority = {
        "pron": 1,  # pronouns first
        "verb": 2,
        "noun": 3,
        "adj": 4,
        "adv": 5,
        "conj": 6,
        "prep": 7,
        "character": 10,  # characters last
    }
    
    def entry_sort_key(entry):
        pos = entry.get("pos", "")
        priority = pos_priority.get(pos, 8)  # default priority
        etymology = entry.get("etymology_number", 1)
        return (priority, etymology)
    
    sorted_entries = sorted(entries, key=entry_sort_key)
    
    for entry in sorted_entries:
        audio_url = get_audio_url(entry)
        if audio_url:
            return audio_url
    return None


def get_audio_url(entry):
    """Get audio URL from Wiktextract sounds metadata without downloading."""
    sounds = entry.get("sounds") or []
    for sound in sounds:
        url = sound.get("mp3_url") or sound.get("ogg_url")
        if url:
            return url
    return None


def download_audio_file(url, word):
    """Download a single audio file with retry logic."""
    import time
    
    ext = ".mp3" if url.lower().endswith(".mp3") else ".ogg"
    os.makedirs(AUDIO_DIR, exist_ok=True)
    filename = (
        f"{sanitize_filename(word)}_{hashlib.md5(url.encode()).hexdigest()}{ext}"
    )
    path = os.path.join(AUDIO_DIR, filename)

    if os.path.exists(path):
        return path

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=HTTP_HEADERS, timeout=60)
            if resp.status_code == 429:
                # Rate limited, wait and retry
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"Rate limited for '{word}', waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            resp.raise_for_status()
            with open(path, "wb") as handle:
                handle.write(resp.content)
            return path  # Success
        except Exception as exc:  # noqa: BLE001
            if attempt == max_retries - 1:
                print(f"Audio download failed for '{word}': {exc}")
                return None
            else:
                # Wait a bit before retrying
                time.sleep(1)
    return None


def download_audio_files_parallel(audio_urls, max_workers=5):
    """Download multiple audio files in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    if not audio_urls:
        return {}
    
    results = {}
    
    def download_single(item):
        word, url = item
        return word, download_audio_file(url, word)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_word = {
            executor.submit(download_single, item): item[0] 
            for item in audio_urls.items()
        }
        
        for future in as_completed(future_to_word):
            word = future_to_word[future]
            try:
                word, path = future.result()
                results[word] = path
            except Exception as exc:  # noqa: BLE001
                print(f"Audio download failed for '{word}': {exc}")
                results[word] = None
    
    return results


def extract_romanization(entry):
    """Extract romanization from Kaikki entry if available."""
    for form in entry.get("forms", []) or []:
        tags = form.get("tags") or []
        if "romanization" in tags and form.get("form"):
            return form["form"]

    for template in entry.get("head_templates", []) or []:
        expansion = template.get("expansion") or ""
        match = re.search(r"\(([^)]+)\)", expansion)
        if match:
            return match.group(1)
    return ""


def get_romanization_for_word(word, grouped_entries):
    entries = grouped_entries.get(word.lower()) if grouped_entries else None
    if not entries:
        return ""
    
    # Use the same prioritization as get_kaikki_glosses
    pos_priority = {
        "pron": 1,  # pronouns first
        "verb": 2,
        "noun": 3,
        "adj": 4,
        "adv": 5,
        "conj": 6,
        "prep": 7,
        "character": 10,  # characters last
    }
    
    def entry_sort_key(entry):
        pos = entry.get("pos", "")
        priority = pos_priority.get(pos, 8)  # default priority
        etymology = entry.get("etymology_number", 1)
        return (priority, etymology)
    
    sorted_entries = sorted(entries, key=entry_sort_key)
    
    for entry in sorted_entries:
        roman = extract_romanization(entry)
        if roman:
            return roman
    return ""


def get_kaikki_glosses(word, grouped_entries, limit=3):
    """Return up to `limit` English meanings from Kaikki entries for a word."""

    entries = grouped_entries.get(word.lower()) if grouped_entries else None
    if not entries:
        return []

    # Prioritize certain parts of speech over others
    pos_priority = {
        "pron": 1,  # pronouns first
        "verb": 2,
        "noun": 3,
        "adj": 4,
        "adv": 5,
        "conj": 6,
        "prep": 7,
        "character": 10,  # characters last
    }
    
    # Sort entries by POS priority, then by etymology number
    def entry_sort_key(entry):
        pos = entry.get("pos", "")
        priority = pos_priority.get(pos, 8)  # default priority
        etymology = entry.get("etymology_number", 1)
        return (priority, etymology)
    
    sorted_entries = sorted(entries, key=entry_sort_key)

    # Group entries by priority
    from itertools import groupby
    grouped_by_priority = []
    for priority, group in groupby(sorted_entries, key=lambda e: pos_priority.get(e.get("pos", ""), 8)):
        grouped_by_priority.append((priority, list(group)))
    
    # Use only the highest priority group
    if grouped_by_priority:
        highest_priority_entries = grouped_by_priority[0][1]
    else:
        highest_priority_entries = sorted_entries

    meanings = []
    seen_lower = set()

    for entry in highest_priority_entries:
        senses = entry.get("senses", []) or []
        for sense in senses:
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


_MORPH_ANALYZER = None


def _get_morph_analyzer():
    """Lazily instantiate and reuse the heavy pymorphy3 analyzer."""
    global _MORPH_ANALYZER
    if _MORPH_ANALYZER is None:
        _MORPH_ANALYZER = pymorphy3.MorphAnalyzer()
    return _MORPH_ANALYZER


@lru_cache(maxsize=4096)
def get_morphological_info(word, source_lang):
    """
    Extract complete morphological information for a word.

    Args:
        word: The word to analyze
        source_lang: Language code (e.g., 'ru', 'es')

    Returns:
        Dictionary with grammatical info, or None if language not supported
    """
    # Only support Russian for now
    if source_lang != "ru":
        return None

    try:
        morph = _get_morph_analyzer()
        parsed = morph.parse(word)[0]

        # Extract all grammatical features
        info = {
            "lemma": parsed.normal_form,
            "part_of_speech": POS_NAMES.get(str(parsed.tag.POS), str(parsed.tag.POS))
            if parsed.tag.POS
            else None,
            # "part_of_speech": POS_NAMES.get(str(parsed.tag.POS), str(parsed.tag.POS))
            # if parsed.tag.POS
            # else None,
            "case": CASE_NAMES.get(str(parsed.tag.case)) if parsed.tag.case else None,
            "gender": GENDER_NAMES.get(str(parsed.tag.gender))
            if parsed.tag.gender
            else None,
            "number": NUMBER_NAMES.get(str(parsed.tag.number))
            if parsed.tag.number
            else None,
            "animacy": ANIMACY_NAMES.get(str(parsed.tag.animacy))
            if parsed.tag.animacy
            else None,
            "aspect": ASPECT_NAMES.get(str(parsed.tag.aspect))
            if parsed.tag.aspect
            else None,
            "tense": TENSE_NAMES.get(str(parsed.tag.tense))
            if parsed.tag.tense
            else None,
            "person": PERSON_NAMES.get(str(parsed.tag.person))
            if parsed.tag.person
            else None,
            "mood": MOOD_NAMES.get(str(parsed.tag.mood)) if parsed.tag.mood else None,
        }

        return info

    except Exception as e:
        print(f"\nMorphological analysis error for '{word}': {e}")
        return None


def canonicalize_word(word, source_lang=SOURCE):
    """Return the lemma or special expansion used for lookups."""

    if not word:
        return word

    normalized = word.strip()
    if is_numeric_token(normalized):
        return RUS_NUMBER_WORDS.get(normalized, normalized)

    lower = normalized.lower()
    if lower in SPECIAL_CANONICAL_MAP:
        return SPECIAL_CANONICAL_MAP[lower]

    if source_lang == "ru":
        morph = get_morphological_info(normalized, source_lang)
        if morph and morph.get("lemma"):
            return morph["lemma"]

    return normalized


def build_display_word(source_word, canonical_word):
    if source_word == canonical_word:
        return source_word

    lower = (source_word or "").strip().lower()
    if is_numeric_token(source_word) or lower in SPECIAL_CANONICAL_MAP:
        return f"{source_word} · {canonical_word}"

    return source_word


def get_wiktionary_translation(word, source_lang, target_lang="en"):
    """
    Get up to three translations from Wiktionary for fallback scenarios.
    Returns a list of up to three translations (empty if nothing found).
    """
    source_name = WIKTIONARY_LANG_NAMES.get(source_lang, source_lang.capitalize())

    url = "https://en.wiktionary.org/w/api.php"
    params = {"action": "parse", "page": word, "prop": "wikitext", "format": "json"}

    # CRITICAL: Wikimedia APIs require a User-Agent header
    headers = HTTP_HEADERS

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()

        if "error" in data:
            return []

        wikitext = data["parse"]["wikitext"]["*"]

        # Find the source language section (e.g., ==Russian==)
        lang_marker = f"=={source_name}=="
        if lang_marker not in wikitext:
            return []

        # Extract just the source language section
        lang_start = wikitext.find(lang_marker)
        rest = wikitext[lang_start + len(lang_marker) :]

        # Find next top-level language section (==Language==)
        next_lang_match = re.search(r"\n==[^=]", rest)
        if next_lang_match:
            lang_section = rest[: next_lang_match.start()]
        else:
            lang_section = rest

        # Extract translations from definition lines
        translations = []

        # Pattern: [[word]] or [[word#Type|word]]
        wikilink_pattern = re.compile(r"\[\[([^|#\]]+)(?:#[^|\]]+)?(?:\|([^\]]+))?\]\]")

        # Track current part-of-speech to avoid unrelated senses
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

            # Track section headings (====Preposition====)
            heading_match = re.match(r"^={4}([^=]+)={4}$", line)
            if heading_match:
                current_pos = heading_match.group(1).strip().lower()
                continue

            # Only process definition lines (#)
            if not line.startswith("#"):
                continue
            if len(line) > 1 and line[1] in ":*;-=^":
                continue

            # Skip if we're in a non-word section
            if current_pos and current_pos not in allowed_pos:
                continue

            # Extract wikilinks from this line
            for match in wikilink_pattern.finditer(line):
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

        # Return first translation or None
        return translations[:3]

    except Exception as e:
        print(f"\nWiktionary error for '{word}': {e}")
        return []


def get_usage_examples(word, source_lang, count=3):
    """Get short usage examples for a word from Tatoeba (for context)"""
    try:
        src = TATOEBA_CODES.get(source_lang, source_lang)
        corpus = ParallelCorpus(src, "eng")  # Just need source sentences

        pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
        examples = []

        for sentence, _ in corpus:
            if pattern.search(sentence.text):
                examples.append(sentence.text)
                if len(examples) >= count:
                    break

        return examples
    except Exception:
        return []


def batch_translate(words, source, target, key, fallback_entries=None):
    """
    Translate multiple words by collecting up to three English glosses from
    Wiktionary (with Kaikki fallback), then optionally translating those glosses to the target
    language via DeepL.
    """
    target_is_en = target.lower() == "en"
    if not target_is_en and not key:
        raise ValueError("DEEPL_API_KEY not found in .env file")

    print(f"    Using Wiktionary for {len(words)} gloss(es)...", end=" ")
    en_glosses = []
    for word in words:
        en_candidates = get_wiktionary_translation(word, source, "en")
        if not en_candidates and fallback_entries:
            en_candidates = get_kaikki_glosses(word, fallback_entries)
        if not en_candidates:
            en_candidates = [word]
        en_glosses.append(", ".join(en_candidates[:3]))
    print("✓")

    if target_is_en:
        return en_glosses

    print(f"    Translating glosses to {target.upper()} via DeepL...", end=" ")
    try:
        payload = {
            "text": en_glosses,
            "source_lang": "EN",
            "target_lang": target.upper(),
        }
        r = requests.post(
            "https://api-free.deepl.com/v2/translate",
            headers={"Authorization": f"DeepL-Auth-Key {key}"},
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        translations = [t["text"] for t in r.json().get("translations", [])]

        if len(translations) < len(en_glosses):
            translations.extend(en_glosses[len(translations) :])

        print("✓")
        return translations

    except Exception as e:
        print(f"\nDeepL API error: {e}")
        return en_glosses


def report_identity_translations(source_words, translations_map, labels=None):
    """Log how many outputs exactly match the source word for each language."""

    if not source_words or not translations_map:
        return

    print("\n🔍 Checking for untranslated entries...")
    for lang, translations in translations_map.items():
        if not translations:
            print(f"  {lang.upper()}: no translations available")
            continue

        matches = []
        limit = min(len(source_words), len(translations))
        for idx in range(limit):
            baseline = source_words[idx]
            label = labels[idx] if labels else baseline
            translation = translations[idx]
            if not translation:
                continue

            if translation.strip().lower() == baseline.strip().lower():
                matches.append(label)

        if matches:
            sample = ", ".join(matches[:10])
            print(
                f"  {lang.upper()}: {len(matches)} words identical to source (e.g., {sample})"
            )
        else:
            print(f"  {lang.upper()}: ✅ all translations differ from the source word")


def collect_examples_for_words(
    words, source_lang, target_lang, max_examples=2, canonical_map=None
):
    """Fetch usage examples for multiple words in a single pass over Tatoeba."""

    if max_examples <= 0 or not words:
        return {word: [] for word in words}

    # Create lookup preferences: try actual word first, then canonical
    lookup_preferences = {}
    for word in words:
        actual = word
        canonical = canonical_map[word] if canonical_map and word in canonical_map else word
        if actual != canonical:
            lookup_preferences[word] = [actual, canonical]
        else:
            lookup_preferences[word] = [actual]
    
    unique_words = list(set(word for prefs in lookup_preferences.values() for word in prefs))
    results = {word: [] for word in unique_words}
    
    try:
        src = TATOEBA_CODES.get(source_lang, source_lang)
        tgt = TATOEBA_CODES.get(target_lang, target_lang)
        corpus = ParallelCorpus(src, tgt)

        patterns = {
            word: re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
            for word in unique_words
        }

        remaining = set(lookup_preferences.keys())
        candidates = {word: [] for word in lookup_preferences.keys()}
        
        # Collect more candidates than needed
        max_candidates = max_examples * 3
        
        for sentence, translation in corpus:
            if not remaining:
                break

            text = sentence.text
            translated = translation.text if translation else ""

            for orig_word in list(remaining):
                for lookup_word in lookup_preferences[orig_word]:
                    if patterns[lookup_word].search(text):
                        candidates[orig_word].append((text, translated, lookup_word))
                        break
            
        # Check if we have enough candidates for each word
        for orig_word in list(remaining):
            if len(candidates[orig_word]) >= max_candidates:
                remaining.discard(orig_word)
    
        # Deduplicate examples based on source text
        for word in candidates:
            seen_texts = set()
            unique_candidates = []
            for item in candidates[word]:
                text = item[0]
                if text not in seen_texts:
                    seen_texts.add(text)
                    unique_candidates.append(item)
            candidates[word] = unique_candidates
        
        # Now select the best examples for each word
        results = {}
        for orig_word, candidate_list in candidates.items():
            if not candidate_list:
                results[orig_word] = []
                continue
            
            # Separate examples by whether they contain the actual word
            actual_word = lookup_preferences[orig_word][0]
            actual_examples = []
            canonical_examples = []
            
            for text, translated, matched in candidate_list:
                if patterns[actual_word].search(text):
                    actual_examples.append((text, translated, matched))
                else:
                    canonical_examples.append((text, translated, matched))
            
            # Prefer examples with actual word, then canonical
            selected = (actual_examples + canonical_examples)[:max_examples]
            results[orig_word] = selected

        # Return results keyed by original words
        return {word: results.get(word, []) for word in words}

    except Exception as e:
        print(f"\nTatoeba error while fetching examples: {e}")
        return {word: [] for word in words}


def highlight_word(text, word, color="#ffcc00"):
    """Return HTML-escaped text with whole-word occurrences of `word` wrapped in a bold colored span.
    Safe for insertion into HTML previews and Anki fields.
    """
    if not text:
        return ""
    if not word:
        return html.escape(text)

    pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
    last = 0
    parts = []
    for m in pattern.finditer(text):
        parts.append(html.escape(text[last : m.start()]))
        parts.append(f"<b style='color:{color}'>" + html.escape(m.group(0)) + "</b>")
        last = m.end()
    parts.append(html.escape(text[last:]))
    return "".join(parts)


def format_morphology_html(morph_info):
    """Return HTML rows describing morphology (without outer container)."""
    if not morph_info:
        return ""

    rows = []

    def add_row(label, value):
        if not value:
            return
        rows.append(
            "<div style='display:flex;flex-direction:column;align-items:center;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.12);'>"
            f"<span style='font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#a0a0a0;'>{label}</span>"
            f"<span style='font-size:20px;font-weight:600;color:#fdfdfd;margin-top:4px;text-align:center;'>{html.escape(str(value))}</span>"
            "</div>"
        )

    add_row("Part of Speech", morph_info.get("part_of_speech"))
    add_row("Lemma", morph_info.get("lemma"))
    add_row("Case", morph_info.get("case"))
    add_row("Gender", morph_info.get("gender"))
    add_row("Number", morph_info.get("number"))
    add_row("Animacy", morph_info.get("animacy"))
    add_row("Aspect", morph_info.get("aspect"))
    add_row("Tense", morph_info.get("tense"))
    add_row("Person", morph_info.get("person"))
    add_row("Mood", morph_info.get("mood"))

    if not rows:
        return ""

    container_style = "display:flex;flex-direction:column;gap:4px;margin-top:8px;text-align:center;"
    if len(rows) > 3:
        container_style = "display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px;text-align:center;"

    return (
        f"<div style='{container_style}'>"
        + "".join(rows)
        + "</div>"
    )


def build_section_html(title, body_html, subtitle=None):
    """Return a consistently styled section block for previews."""
    if not body_html:
        return ""

    subtitle_html = (
        f"<div class='section-subtitle'>{subtitle}</div>" if subtitle else ""
    )

    return (
        "<div class='info-section'>"
        f"<div class='section-title'>{title}</div>"
        f"{subtitle_html}"
        f"<div class='section-body'>{body_html}</div>"
        "</div>"
    )


def build_top_section(meanings_html, morph_html):
    """Return a single container that stacks meanings and grammar notes."""
    if not meanings_html and not morph_html:
        return ""

    meanings_block = meanings_html or "<div class='muted'>No meanings available</div>"
    block = [
        "<div class='info-section stacked-info'>",
        "<div class='section-title'>Possible Meanings</div>",
        f"<div class='section-body meaning-body'>{meanings_block}</div>",
    ]

    if morph_html:
        block.append("<div class='section-divider'></div>")
        block.append("<div class='section-title'>Grammar Notes</div>")
        block.append(f"<div class='section-body grammar-body'>{morph_html}</div>")

    block.append("</div>")
    return "".join(block)


def create_preview_html(words_data):
    """Generate HTML preview with navigation"""
    cards_json = []

    for data in words_data:
        display_word = data.get("display_word", data["word"])
        meaning_lines = []
        for lang, text in data["translations"].items():
            meaning_lines.append(
                "<div class='meaning-line'>"
                f"<span class='lang-pill'>{lang.upper()}</span>"
                f"<span class='meaning-text'>{text}</span>"
                "</div>"
            )
        if not meaning_lines:
            meaning_lines.append("<div class='muted'>No meanings available</div>")
        meanings_html = "".join(meaning_lines)

        morph_body = format_morphology_html(data.get("morphology"))

        if data.get("examples"):
            example_lines = []
            for src, tgt, matched in data["examples"]:
                highlighted_src = highlight_word(src, matched)
                highlighted_tgt = highlight_word(tgt, matched)
                example_lines.append(
                    "<div class='example-line'>"
                    f"<div>• {highlighted_src}</div>"
                    f"<i>{highlighted_tgt}</i>"
                    "</div>"
                )
            examples_body = "".join(example_lines)
        else:
            examples_body = "<div class='muted'>No examples found</div>"
        examples_html = build_section_html(
            "Usage Examples",
            examples_body,
        )

        top_section_html = build_top_section(meanings_html, morph_body)

        cards_json.append(
            {
                "word": display_word,
                "rank": data["rank"],
                "examples": examples_html,
                "audio": "🔊 Audio" if data.get("audio_url") else "",
                "romanization": data.get("romanization", ""),
                "top_section": top_section_html,
            }
        )

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>FreqAnki Preview</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            text-align: center;
            margin: 0;
            padding: 20px;
            background: #1a1a1a;
            color: #fff;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .card {{
            background: #2a2a2a;
            border-radius: 16px;
            padding: 32px;
            margin: 18px 0;
            box-shadow: 0 8px 30px rgba(0,0,0,0.35);
        }}
        .word {{ font-size: 68px; margin: 20px 0 14px; }}
        .info-section {{
            text-align: center;
            background: #1f1f1f;
            border: 1px solid #2f2f2f;
            border-radius: 14px;
            padding: 20px 24px;
            margin: 18px auto;
            max-width: 650px;
        }}
        .stacked-info {{
            display: flex;
            flex-direction: column;
            text-align: left;
        }}
        .section-title {{
            text-transform: uppercase;
            letter-spacing: 1px;
            font-size: 14px;
            color: #f9cf6c;
            text-align: center;
        }}
        .section-subtitle {{
            font-size: 13px;
            color: #a0a0a0;
            margin-top: 4px;
            text-align: center;
        }}
        .section-body {{
            margin-top: 16px;
            font-size: 19px;
            line-height: 1.5;
            color: #f7f7f7;
            text-align: center;
        }}
        .meaning-body {{ text-align: center; }}
        .grammar-body {{ text-align: center; }}
        .section-divider {{
            width: 100%;
            height: 1px;
            background: rgba(249,207,108,0.25);
            margin: 20px 0 12px;
        }}
        .meta-row {{
            display: flex;
            justify-content: center;
            gap: 12px;
            flex-wrap: wrap;
            margin: 16px 0 10px;
        }}
        .chip {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 6px 14px;
            border-radius: 999px;
            background: #1f1f1f;
            border: 1px solid #3a3a3a;
            font-size: 15px;
        }}
        .chip.roman {{ color: #ffa6a6; }}
        .chip.rank {{ color: #f9cf6c; }}
        .audio-line {{ color: #4CAF50; margin: 8px 0; font-size: 16px; min-height: 20px; }}
        .meaning-line {{
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 8px;
            justify-content: center;
            margin: 12px 0;
        }}
        .lang-pill {{
            font-size: 12px;
            letter-spacing: 1px;
            color: #0f0f0f;
            background: #f9cf6c;
            border-radius: 999px;
            padding: 4px 10px;
        }}
        .meaning-text {{ flex: 1; text-align: center; }}
        .example-line {{ margin: 12px 0; line-height: 1.6; font-size: 18px; text-align: center; }}
        .example-line i {{ color: #a3a3a3; font-size: 16px; display: block; margin-top: 6px; }}
        .muted {{ color: #8a8a8a; font-style: italic; }}
        .nav {{
            margin: 30px 0;
            display: flex;
            justify-content: center;
            gap: 20px;
            align-items: center;
        }}
        button {{
            background: #4CAF50;
            color: white;
            border: none;
            padding: 15px 30px;
            font-size: 18px;
            border-radius: 8px;
            cursor: pointer;
        }}
        button:hover {{ background: #45a049; }}
        button:disabled {{ background: #555; cursor: not-allowed; }}
        .counter {{ font-size: 20px; color: #888; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>FreqAnki Preview</h1>
        
        <div class="nav">
            <button onclick="prevCard()">← Previous</button>
            <span class="counter"><span id="current">1</span> / <span id="total">0</span></span>
            <button onclick="nextCard()">Next →</button>
        </div>
        
        <div class="card">
            <div class="word" id="front-word"></div>
            <div class="audio-line" id="front-audio"></div>
            <div class="meta-row">
                <div class="chip rank" id="front-rank"></div>
            </div>
        </div>
        
        <div class="card">
            <div class="meta-row">
                <div class="chip roman" id="back-romanization"></div>
            </div>
            <div class="audio-line" id="back-audio"></div>
            <div id="top-section"></div>
            <div id="examples"></div>
        </div>
        
        <div class="nav">
            <button onclick="window.close()">Close & Continue</button>
        </div>
    </div>
    
    <script>
        const cards = {json.dumps(cards_json)};
        let currentIndex = 0;

        function setChip(id, text) {{
            const el = document.getElementById(id);
            if (!el) return;
            if (text) {{
                el.textContent = text;
                el.style.display = 'inline-flex';
            }} else {{
                el.textContent = '';
                el.style.display = 'none';
            }}
        }}

        function setLine(id, text) {{
            const el = document.getElementById(id);
            if (!el) return;
            if (text) {{
                el.textContent = text;
                el.style.display = 'block';
            }} else {{
                el.textContent = '';
                el.style.display = 'none';
            }}
        }}
        
        function showCard(index) {{
            const card = cards[index];
            
            document.getElementById('front-word').textContent = card.word;
            setLine('front-audio', card.audio);
            setChip('front-rank', 'Rank · #' + card.rank);
            document.getElementById('top-section').innerHTML = card.top_section;
            document.getElementById('examples').innerHTML = card.examples;
            setLine('back-audio', card.audio);
            setChip('back-romanization', card.romanization ? 'Romanization · ' + card.romanization : '');
            
            document.getElementById('current').textContent = index + 1;
            document.getElementById('total').textContent = cards.length;
        }}
        
        function nextCard() {{
            if (currentIndex < cards.length - 1) {{
                currentIndex++;
                showCard(currentIndex);
            }}
        }}
        
        function prevCard() {{
            if (currentIndex > 0) {{
                currentIndex--;
                showCard(currentIndex);
            }}
        }}
        
        document.addEventListener('keydown', e => {{
            if (e.key === 'ArrowRight') nextCard();
            if (e.key === 'ArrowLeft') prevCard();
        }});
        
        showCard(0);
    </script>
</body>
</html>"""


def create_deck(words_data, name, targets):
    """Create Anki deck with media files"""
    print("🎵 Downloading audio files...")
    
    # Collect all audio URLs
    audio_urls = {}
    for data in words_data:
        if data.get("audio_url"):
            audio_urls[data["word"]] = data["audio_url"]
    
    # Download audio files in parallel
    audio_paths = download_audio_files_parallel(audio_urls, max_workers=5)
    
    # Update words_data with downloaded paths
    for data in words_data:
        word = data["word"]
        if word in audio_paths and audio_paths[word]:
            data["audio"] = audio_paths[word]
        else:
            data["audio"] = None
    
    deck_id = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)
    deck = genanki.Deck(deck_id, name)

    # Build fields dynamically
    fields = [
        {"name": "Word"},
        {"name": "Rank"},
        {"name": "Romanization"},
        {"name": "Meanings"},
        {"name": "Morphology"},
        {"name": "Examples"},
        {"name": "Audio"},
    ]

    model = genanki.Model(
        int(hashlib.md5(b"FreqAnki-v9").hexdigest()[:8], 16),
        "FreqAnki",
        fields=fields,
        templates=[
            {
                "name": "Card",
                "qfmt": (
                    "<div style='font-family:Arial,sans-serif;background:#111;color:#fff;padding:32px;border-radius:16px;'>"
                    "<div style='font-size:64px;text-align:center;margin:12px 0 6px;'>{{Word}}</div>"
                    "{{#Audio}}<div style='text-align:center;margin:8px 0;'>{{Audio}}</div>{{/Audio}}"
                    "<div style='display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin-top:12px;'>"
                    "<div style='padding:6px 14px;border-radius:999px;border:1px solid #3a3a3a;background:#1f1f1f;color:#f9cf6c;font-size:15px;'>Rank · #{{Rank}}</div>"
                    "</div>"
                    "</div>"
                ),
                "afmt": (
                    "<div style='font-family:Arial,sans-serif;background:#111;color:#fff;padding:32px;border-radius:16px;'>"
                    "<div style='display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin:0 0 12px;'>"
                    "{{#Romanization}}<div style='padding:6px 14px;border-radius:999px;border:1px solid #3a3a3a;background:#1f1f1f;color:#ffa6a6;font-size:15px;'>Romanization · {{Romanization}}</div>{{/Romanization}}"
                    "</div>"
                    "{{#Audio}}<div style='text-align:center;margin-bottom:12px;'>{{Audio}}</div>{{/Audio}}"
                    "<div style='display:flex;justify-content:center;'>{{Meanings}}</div>"
                    "{{Examples}}"
                    "</div>"
                ),
            }
        ],
    )

    media_files = []

    for data in words_data:
        # Build field values
        display_word = data.get("display_word", data["word"])
        roman_value = data.get("romanization", "")
        roman_value = html.escape(roman_value) if roman_value else ""
        fields_data = [
            display_word,
            str(data["rank"]),
            roman_value,
        ]

        meaning_lines = []
        for lang in targets:
            text = data["translations"].get(lang)
            if not text:
                continue
            meaning_lines.append(
                "<div style='display:flex;flex-direction:column;align-items:center;gap:6px;margin:10px 0;'>"
                f"<span style='font-size:12px;letter-spacing:1px;color:#0f0f0f;background:#f9cf6c;border-radius:999px;padding:4px 10px;display:inline-flex;'>{lang.upper()}</span>"
                f"<span style='font-size:19px;color:#f7f7f7;text-align:center;'>{html.escape(text)}</span>"
                "</div>"
            )
        if not meaning_lines:
            meaning_lines.append(
                "<div style='color:#8a8a8a;font-style:italic;'>No meanings available</div>"
            )
        morph_html = format_morphology_html(data.get("morphology"))
        combined_block = (
            "<div style='text-align:left;background:#1f1f1f;border:1px solid #2f2f2f;border-radius:14px;padding:20px 24px;margin:18px auto;max-width:650px;'>"
            "<div style='text-transform:uppercase;letter-spacing:1px;font-size:14px;color:#f9cf6c;text-align:center;'>Possible Meanings</div>"
            "<div style='margin-top:16px;font-size:19px;line-height:1.5;color:#f7f7f7;text-align:center;'>"
            f"{''.join(meaning_lines)}"
            "</div>"
        )
        if morph_html:
            combined_block += (
                "<div style='width:100%;height:1px;background:rgba(249,207,108,0.25);margin:20px 0 12px;'></div>"
                "<div style='text-transform:uppercase;letter-spacing:1px;font-size:14px;color:#f9cf6c;text-align:center;'>Grammar Notes</div>"
                f"<div style='margin-top:12px;text-align:center;'>{morph_html}</div>"
            )
        combined_block += "</div>"
        fields_data.append(combined_block)

        # Morphology field kept for backwards-compatible template, but styling now lives in Meanings block
        fields_data.append("")

        # Examples
        example_lines = []
        if data.get("examples"):
            for src, tgt, matched in data["examples"]:
                src_html = highlight_word(src, matched)
                tgt_html = highlight_word(tgt, matched)
                example_lines.append(
                    "<div style='margin:12px 0;line-height:1.6;font-size:18px;text-align:center;'>"
                    f"• {src_html}<div style='color:#a3a3a3;font-size:16px;margin-top:6px;'><i>{tgt_html}</i></div>"
                    "</div>"
                )
        else:
            example_lines.append(
                "<div style='color:#8a8a8a;font-style:italic;'>No examples available</div>"
            )
        examples_section = (
            "<div style='text-align:center;background:#1f1f1f;border:1px solid #2f2f2f;border-radius:14px;padding:20px 24px;margin:18px auto;max-width:650px;'>"
            "<div style='text-transform:uppercase;letter-spacing:1px;font-size:14px;color:#f9cf6c;text-align:center;'>Usage Examples</div>"
            "<div style='margin-top:16px;font-size:19px;line-height:1.5;color:#f7f7f7;text-align:center;'>"
            f"{''.join(example_lines)}"
            "</div></div>"
        )
        fields_data.append(examples_section)

        audio_field = ""
        if data.get("audio"):
            media_files.append(data["audio"])
            audio_field = f"[sound:{os.path.basename(data['audio'])}]"
        fields_data.append(audio_field)

        deck.add_note(genanki.Note(model=model, fields=fields_data))

    # Save
    output = f"{name.replace(' ', '_')}.apkg"
    package = genanki.Package(deck)
    package.media_files = media_files
    package.write_to_file(output)

    print(f"✅ Created: {output}")
    return output


def main():
    print("FreqAnki - Frequency-Based Anki Deck Generator\n")

    # Get words
    words = get_frequency_words(SOURCE, NUM_WORDS)
    print(f"📚 Got {len(words)} most frequent {SOURCE.upper()} words")
    canonical_map = {word: canonicalize_word(word) for word in words}
    canonical_words = [canonical_map[word] for word in words]

    # Load Kaikki entries once for audio
    kaikki_entries = {}
    if words:
        print("\n🔊 Fetching Kaikki metadata for audio...")
        lookup_targets = list(set(words + [canonical_map[word] for word in words]))
        kaikki_entries = load_kaikki_entries(lookup_targets, SOURCE)

    # Batch translate all words for each target language
    print(f"\n🌐 Translating to {len(TARGETS)} language(s)...")
    all_translations = {}
    for target in TARGETS:
        print(f"  → {target.upper()}")
        translations = batch_translate(
            canonical_words, SOURCE, target, DEEPL_KEY, kaikki_entries
        )
        all_translations[target] = translations

    report_identity_translations(canonical_words, all_translations, labels=words)

    examples_by_word = {}
    if TARGETS and NUM_EXAMPLES > 0:
        print("\n📝 Collecting usage examples from Tatoeba...", end=" ")
        examples_by_word = collect_examples_for_words(
            words, SOURCE, TARGETS[0], NUM_EXAMPLES, canonical_map
        )
        print("✓")

    # Process each word
    print(f"\n⚙️  Processing {NUM_WORDS} words...")
    words_data = []

    for i, word in enumerate(words, 1):
        print(f"  [{i}/{NUM_WORDS}] {word}", end="\r")

        canonical = canonical_map[word]

        # Collect translations
        translations = {
            t: all_translations[t][i - 1] for t in TARGETS if all_translations[t][i - 1]
        }

        # Get morphological information
        morphology = get_morphological_info(word, SOURCE)

        # Examples (only from first target)
        examples = examples_by_word.get(word, []) if examples_by_word else []

        audio_url = get_audio_for_word(word, kaikki_entries) or get_audio_for_word(canonical, kaikki_entries)
        romanization = get_romanization_for_word(word, kaikki_entries) or get_romanization_for_word(canonical, kaikki_entries)
        display_word = build_display_word(word, canonical)

        words_data.append(
            {
                "word": word,
                "lookup_word": canonical,
                "display_word": display_word,
                "rank": i,
                "translations": translations,
                "morphology": morphology,
                "examples": examples,
                "audio_url": audio_url,
                "romanization": romanization,
            }
        )

    print(f"\n✅ Processed {len(words_data)} words")

    # Preview
    if words_data:
        html = create_preview_html(words_data)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write(html)
            temp_path = f.name

        print("\n📋 Opening preview in browser...")
        webbrowser.open("file://" + temp_path)
        input("Press Enter after viewing to continue...")
        os.unlink(temp_path)

    # Generate deck
    response = input("\nGenerate Anki deck? (y/n): ").strip().lower()
    if response == "y":
        create_deck(words_data, f"FreqAnki_{SOURCE}_Top_{NUM_WORDS}", TARGETS)
        print("\n🎉 Done! Import the .apkg file into Anki Desktop")
    else:
        print("❌ Cancelled")


if __name__ == "__main__":
    main()
