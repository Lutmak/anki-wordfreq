#!/usr/bin/env python3
"""Hybrid FreqAnki generator that combines frequency lists with Kaikki/Wiktextract data."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import tempfile
import webbrowser
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import requests
    import genanki
    from dotenv import load_dotenv
    from wordfreq import top_n_list
    from tatoebatools import ParallelCorpus

    from kaikki_lookup import (
        get_language_dictionary,
        load_dictionary,
        get_english_meanings,
    )
except ImportError as exc:  # pragma: no cover - surfaced to the user immediately
    print(
        f"Missing dependency: {exc}.\nRun: pip install wordfreq genanki requests python-dotenv tatoebatools"
    )
    sys.exit(1)

load_dotenv()

# -----------------------------------------------------------------------------
# Configuration (adjust as needed)
# -----------------------------------------------------------------------------
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
SOURCE_LANG = os.getenv("FREQANKI_SOURCE", "ru")
TARGET_LANGS = [
    lang.strip()
    for lang in os.getenv("FREQANKI_TARGETS", "en,es").split(",")
    if lang.strip()
]
NUM_WORDS = int(os.getenv("FREQANKI_NUM_WORDS", 10))
MAX_MEANINGS = int(os.getenv("FREQANKI_MAX_MEANINGS", 12))
MAX_EXAMPLES = int(os.getenv("FREQANKI_MAX_EXAMPLES", 2))
PREVIEW_ENABLED = os.getenv("FREQANKI_PREVIEW", "1") != "0"
DEEPL_URL = "https://api-free.deepl.com/v2/translate"
AUDIO_DIR = "audio"
PRIMARY_EXAMPLE_TARGET = TARGET_LANGS[0] if TARGET_LANGS else "en"
HTTP_HEADERS = {
    "User-Agent": "FreqAnki/1.0 (Language Learning Deck Generator; https://github.com/Lutmak/anki-wordfreq)",
}
MEANINGS_PER_SENSE = int(os.getenv("FREQANKI_MEANINGS_PER_SENSE", 3))
MEANING_BREAK_LENGTH = int(os.getenv("FREQANKI_MEANING_BREAK_LENGTH", 60))

PREFERRED_POS_ORDER = [
    "noun",
    "verb",
    "pron",
    "adjective",
    "adverb",
    "preposition",
    "conjunction",
    "particle",
    "interjection",
    "numeral",
    "determiner",
]

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

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def highlight_word(text: str, word: str, color: str = "#ffcc00") -> str:
    if not text:
        return ""
    if not word:
        return html.escape(text)

    pattern = re.compile(r"\\b" + re.escape(word) + r"\\b", re.IGNORECASE)
    last = 0
    parts: List[str] = []
    for match in pattern.finditer(text):
        parts.append(html.escape(text[last : match.start()]))
        parts.append(
            f"<b style='color:{color}'>" + html.escape(match.group(0)) + "</b>"
        )
        last = match.end()
    parts.append(html.escape(text[last:]))
    return "".join(parts)


def pick_entry(entries: Optional[Sequence[Dict]]) -> Optional[Dict]:
    if not entries:
        return None

    def weight(entry: Dict) -> int:
        pos = (entry.get("pos") or "").lower()
        if pos in PREFERRED_POS_ORDER:
            return PREFERRED_POS_ORDER.index(pos)
        return len(PREFERRED_POS_ORDER)

    return sorted(entries, key=weight)[0]


def clean_meaning_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"\[[^\]]+\]", "", cleaned)
    cleaned = cleaned.split(";", 1)[0]
    cleaned = re.sub(r"\([^)]*\)", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -–—:")


def meaning_is_too_long(text: str) -> bool:
    return len(text) > MEANING_BREAK_LENGTH or text.count(" ") >= 8


def collect_meanings(entry: Dict, limit: int) -> List[str]:
    meanings: List[str] = []
    seen_lower: set[str] = set()
    senses = entry.get("senses", [])

    for sense in senses:
        per_sense = 0
        raw_meanings = get_english_meanings(sense)

        for meaning in raw_meanings:
            variants = [seg.strip() for seg in meaning.split(";") if seg.strip()]
            for variant in variants:
                clean = clean_meaning_text(variant)
                lower = clean.lower()
                if not clean or lower in seen_lower:
                    continue
                if meaning_is_too_long(clean):
                    return meanings

                meanings.append(clean)
                seen_lower.add(lower)
                per_sense += 1

                if len(meanings) >= limit or per_sense >= MEANINGS_PER_SENSE:
                    break
            if len(meanings) >= limit or per_sense >= MEANINGS_PER_SENSE:
                break

        if len(meanings) >= limit:
            break

    return meanings


def get_tatoeba_examples(
    word: str,
    source_lang: str,
    target_lang: str,
    limit: int,
) -> List[Dict[str, str]]:
    try:
        src = TATOEBA_CODES.get(source_lang, source_lang)
        tgt = TATOEBA_CODES.get(target_lang, target_lang)
        corpus = ParallelCorpus(src, tgt)
        pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
        collected: List[Dict[str, str]] = []
        cap = max(limit * 4, limit)

        for sentence, translation in corpus:
            if pattern.search(sentence.text):
                collected.append(
                    {
                        "text": sentence.text,
                        "translation": translation.text if translation else "",
                    }
                )
                if len(collected) >= cap:
                    break

        collected.sort(key=lambda ex: len(ex["text"]))
        return collected[:limit]
    except Exception:
        return []


def gather_examples(entry: Dict, word: str, limit: int) -> List[Dict[str, str]]:
    if limit <= 0:
        return []
    return get_tatoeba_examples(
        word,
        SOURCE_LANG,
        PRIMARY_EXAMPLE_TARGET,
        limit,
    )


def extract_pronunciation(entry: Dict) -> Tuple[str, str]:
    ipa = ""
    romanization = ""

    for sound in entry.get("sounds", []):
        if not ipa and "ipa" in sound:
            ipa = sound["ipa"]

    for form in entry.get("forms", []):
        tags = form.get("tags") or []
        if "romanization" in tags:
            romanization = form.get("form", "")
            break

    if not romanization:
        for template in entry.get("head_templates", []):
            expansion = template.get("expansion") or ""
            match = re.search(r"\(([^)]+)\)", expansion)
            if match:
                romanization = match.group(1)
                break

    return ipa, romanization


def sanitize_filename(text: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", text)
    return safe.strip("_") or "audio"


def fetch_wikimedia_audio(entry: Dict, word: str) -> Optional[str]:
    sounds = entry.get("sounds", []) or []
    for sound in sounds:
        if "audio" not in sound:
            continue
        url = sound.get("mp3_url") or sound.get("ogg_url")
        if not url:
            continue

        ext = ".mp3" if url.lower().endswith(".mp3") else ".ogg"
        os.makedirs(AUDIO_DIR, exist_ok=True)
        filename = (
            f"{sanitize_filename(word)}_{hashlib.md5(url.encode()).hexdigest()}{ext}"
        )
        path = os.path.join(AUDIO_DIR, filename)

        if not os.path.exists(path):
            try:
                resp = requests.get(url, headers=HTTP_HEADERS, timeout=60)
                resp.raise_for_status()
                with open(path, "wb") as file_handle:
                    file_handle.write(resp.content)
            except Exception as exc:  # noqa: BLE001
                print(f"Audio download failed for '{word}': {exc}")
                return None
        return path
    return None


def translate_texts(
    texts: Sequence[str], target_lang: str, api_key: Optional[str]
) -> List[str]:
    if not texts:
        return []
    if target_lang.lower() == "en":
        return list(texts)
    if not api_key:
        return list(texts)

    payload = {
        "text": list(texts),
        "source_lang": "EN",
        "target_lang": target_lang.upper(),
    }

    try:
        resp = requests.post(
            DEEPL_URL,
            headers={**HTTP_HEADERS, "Authorization": f"DeepL-Auth-Key {api_key}"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        translations = [item["text"] for item in resp.json().get("translations", [])]
        if len(translations) == len(texts):
            return translations
        padded = list(translations)
        padded.extend(texts[len(translations) :])
        return padded
    except Exception as exc:  # noqa: BLE001
        print(f"DeepL error ({target_lang}): {exc}. Falling back to English meanings.")
        return list(texts)


def build_translations(
    meanings: List[str], targets: Sequence[str]
) -> Dict[str, List[str]]:
    texts = meanings or ["(definition unavailable)"]

    translations: Dict[str, List[str]] = {}
    for target in targets:
        rendered = translate_texts(texts, target, DEEPL_API_KEY)
        translations[target] = rendered
    return translations


def format_examples_for_field(examples: Iterable[Dict[str, str]], word: str) -> str:
    blocks: List[str] = []
    for example in examples:
        source = highlight_word(example.get("text", ""), word)
        target = highlight_word(example.get("translation", ""), word)
        blocks.append(f"• {source}<br><i style='color:#666'>{target}</i>")
    return "<br>".join(blocks) if blocks else "<i>No examples available</i>"


def create_preview_html(words_data: Sequence[Dict], targets: Sequence[str]) -> str:
    cards_payload = []
    for data in words_data:
        trans_payload = []
        for lang in targets:
            lines = data["translations"].get(lang, [])
            if lines:
                safe_lines = "<br>".join(html.escape(line) for line in lines)
            else:
                safe_lines = "<i>—</i>"
            trans_payload.append({"lang": lang.upper(), "text": safe_lines})

        sample_examples = []
        for example in data.get("examples", []):
            sample_examples.append(
                {
                    "src": highlight_word(example["text"], data["word"]),
                    "tgt": highlight_word(example.get("translation", ""), data["word"]),
                }
            )

        cards_payload.append(
            {
                "word": data["word"],
                "rank": data["rank"],
                "ipa": data.get("ipa", ""),
                "roman": data.get("romanization", ""),
                "translations": trans_payload,
                "examples": sample_examples,
                "audio": bool(data.get("audio")),
            }
        )

    cards_json = json.dumps(cards_payload)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset='UTF-8'>
<title>FreqAnki Preview</title>
<style>
    body {{ font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; background:#0e0e0f; color:#f5f6f8; margin:0; padding:24px; }}
    .container {{ max-width: 900px; margin: 0 auto; }}
    .nav {{ display:flex; justify-content:center; align-items:center; gap:18px; margin:20px 0 10px; }}
    button {{ background:#4caf50; color:#fff; border:none; border-radius:24px; padding:10px 26px; font-size:16px; cursor:pointer; }}
    button:disabled {{ background:#3a3a3a; cursor:not-allowed; }}
    .card {{ background:#18191d; border-radius:18px; padding:32px; margin:18px 0; box-shadow:0 20px 40px rgba(0,0,0,0.45); }}
    h2 {{ margin:0 0 12px; text-transform:uppercase; letter-spacing:3px; font-size:14px; color:#8b8d94; }}
    .word {{ font-size:72px; font-weight:500; margin:20px 0; text-align:center; }}
    .meta {{ font-size:15px; color:#9da0aa; text-align:center; margin:4px 0; }}
    .meta span {{ text-transform:uppercase; letter-spacing:2px; font-size:11px; color:#686b73; margin-right:8px; }}
    .audio {{ color:#4caf50; text-align:center; margin:8px 0; font-size:16px; }}
    .rank {{ text-align:center; color:#70727a; margin-top:10px; }}
    .translations div {{ margin:6px 0; font-size:18px; }}
    .translations span {{ color:#8b8d94; margin-right:8px; font-size:16px; }}
    .examples {{ background:#101114; border-radius:12px; padding:18px; margin-top:20px; font-size:18px; line-height:1.4; }}
    .examples i {{ color:#a3a6b3; font-size:16px; }}
    .etymology {{ margin-top:18px; font-size:15px; color:#9da0aa; }}
</style>
</head>
<body>
<div class='container'>
    <div class='nav'>
        <button onclick='prevCard()'>← Previous</button>
        <span id='counter'></span>
        <button onclick='nextCard()'>Next →</button>
    </div>
    <div class='card'>
        <h2>Front</h2>
        <div class='word' id='front-word'></div>
        <div class='meta' id='front-ipa'></div>
        <div class='meta' id='front-roman'></div>
        <div class='audio' id='front-audio'></div>
        <div class='rank'>Rank #<span id='front-rank'></span></div>
    </div>
    <div class='card'>
        <h2>Back</h2>
        <div class='word' id='back-word'></div>
        <div class='meta' id='back-ipa'></div>
        <div class='meta' id='back-roman'></div>
        <div class='translations' id='translations'></div>
        <div class='examples' id='examples'></div>
    </div>
</div>
<script>
const cards = {cards_json};
let index = 0;

function render(idx) {{
    const card = cards[idx];
    document.getElementById('front-word').textContent = card.word;
    document.getElementById('back-word').textContent = card.word;

    const ipaText = card.ipa ? 'IPA · ' + card.ipa : '';
    const romanText = card.roman ? 'Romanization · ' + card.roman : '';
    document.getElementById('front-ipa').textContent = ipaText;
    document.getElementById('back-ipa').textContent = ipaText;
    document.getElementById('front-roman').textContent = romanText;
    document.getElementById('back-roman').textContent = romanText;

    document.getElementById('front-audio').textContent = card.audio ? '🔊 Audio' : '';
    document.getElementById('front-rank').textContent = card.rank;

    const translations = card.translations
        .map(item => '<div><span>' + item.lang + ':</span>' + (item.text || '<i>—</i>') + '</div>')
        .join('');
    document.getElementById('translations').innerHTML = translations;

    if (card.examples.length) {{
        document.getElementById('examples').innerHTML = card.examples
            .map(ex => '• ' + ex.src + '<br><i>' + ex.tgt + '</i>')
            .join('<br><br>');
    }} else {{
        document.getElementById('examples').innerHTML = '<i>No examples found</i>';
    }}

    document.getElementById('counter').textContent = (idx + 1) + ' / ' + cards.length;
}}

function nextCard() {{ if (index < cards.length - 1) {{ index++; render(index); }} }}
function prevCard() {{ if (index > 0) {{ index--; render(index); }} }}
document.addEventListener('keydown', e => {{
    if (e.key === 'ArrowRight') nextCard();
    if (e.key === 'ArrowLeft') prevCard();
}});

render(0);
</script>
</body>
</html>"""


def create_deck(words_data: Sequence[Dict], name: str, targets: Sequence[str]) -> str:
    deck_id = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)
    deck = genanki.Deck(deck_id, name)

    fields = [
        {"name": "Word"},
        {"name": "Rank"},
        {"name": "IPA"},
        {"name": "Romanization"},
    ]
    fields.extend({"name": f"Trans_{lang}"} for lang in targets)
    fields.extend([{"name": "Examples"}, {"name": "Audio"}])

    translations_block = "".join(
        [
            '<div style="margin:6px 0;font-size:20px;">'
            + f'<span style="color:#888;text-transform:uppercase;letter-spacing:1px;font-size:13px;margin-right:8px;">{lang.upper()}</span>'
            + f"{{{{Trans_{lang}}}}}</div>"
            for lang in targets
        ]
    )

    model = genanki.Model(
        int(hashlib.md5(b"FreqAnki-kaikki-v1").hexdigest()[:8], 16),
        "FreqAnki Kaikki",
        fields=fields,
        templates=[
            {
                "name": "Card",
                "qfmt": (
                    "<div style='text-transform:uppercase;letter-spacing:2px;font-size:13px;color:#777;text-align:center;'>Front</div>"
                    "<div style='font-size:72px;text-align:center;margin:28px 0'>{{Word}}</div>"
                    "{{#IPA}}<div style='text-align:center;font-size:18px;color:#8ad0ff;margin-bottom:4px;'>IPA · {{IPA}}</div>{{/IPA}}"
                    "{{#Romanization}}<div style='text-align:center;font-size:16px;color:#ffa6a6;'>Romanization · {{Romanization}}</div>{{/Romanization}}"
                    "{{#Audio}}<div style='text-align:center;margin:14px 0;color:#4caf50'>🔊 Audio</div>"
                    "<div style='text-align:center;margin-bottom:6px;'>{{Audio}}</div>{{/Audio}}"
                    "<div style='color:#777;text-align:center'>Rank #{{Rank}}</div>"
                ),
                "afmt": (
                    "<div style='text-transform:uppercase;letter-spacing:2px;font-size:13px;color:#777;text-align:center;'>Back</div>"
                    "<div style='font-size:52px;text-align:center;margin:18px 0'>{{Word}}</div><hr>"
                    "{{#IPA}}<div style='text-align:center;font-size:18px;color:#8ad0ff;margin-top:10px;'>IPA · {{IPA}}</div>{{/IPA}}"
                    "{{#Romanization}}<div style='text-align:center;font-size:16px;color:#ffa6a6;'>Romanization · {{Romanization}}</div>{{/Romanization}}"
                    + translations_block
                    + "<div style='margin:18px 0;font-size:18px;'>📝 Examples:<br>{{Examples}}</div>"
                    + "{{#Audio}}<div style='text-align:center;margin:10px 0;color:#4caf50'>🔊 Audio</div>"
                    + "<div style='text-align:center;margin-bottom:10px;'>{{Audio}}</div>{{/Audio}}"
                    + "<div style='color:#777;text-align:center'>Rank #{{Rank}}</div>"
                ),
            }
        ],
    )

    media_files: List[str] = []
    for data in words_data:
        row = [
            data["word"],
            str(data["rank"]),
            data.get("ipa", ""),
            data.get("romanization", ""),
        ]
        for lang in targets:
            lines = data["translations"].get(lang, [])
            if lines:
                rendered = "<br>".join(html.escape(line) for line in lines)
            else:
                rendered = ""
            row.append(rendered)
        row.append(format_examples_for_field(data.get("examples", []), data["word"]))

        audio_field = ""
        if data.get("audio"):
            media_files.append(data["audio"])
            audio_field = f"[sound:{os.path.basename(data['audio'])}]"
        row.append(audio_field)

        deck.add_note(genanki.Note(model=model, fields=row))

    package = genanki.Package(deck)
    package.media_files = media_files
    output = f"{name.replace(' ', '_')}.apkg"
    package.write_to_file(output)
    return output


# -----------------------------------------------------------------------------
# Main orchestration
# -----------------------------------------------------------------------------


def main() -> None:
    if not TARGET_LANGS:
        print("No target languages configured (env FREQANKI_TARGETS).")
        return

    print("FreqAnki Kaikki Hybrid\n")
    print(f"→ Source language: {SOURCE_LANG}")
    print(f"→ Targets: {', '.join(TARGET_LANGS)}")
    print(f"→ Fetching dictionary for {SOURCE_LANG}...")

    dictionary_path = get_language_dictionary(SOURCE_LANG)
    words = top_n_list(SOURCE_LANG, NUM_WORDS)
    print(f"📚 Loaded top {len(words)} words from wordfreq")

    entries = load_dictionary(
        dictionary_path,
        words,
        lang_code=SOURCE_LANG,
        stop_when_all_found=True,
    )

    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for entry in entries:
        grouped[entry.get("word", "").lower()].append(entry)

    print("\nBuilding cards...")
    cards: List[Dict] = []
    missing: List[str] = []

    for rank, word in enumerate(words, 1):
        entry = pick_entry(grouped.get(word.lower()))
        if not entry:
            missing.append(word)
            continue

        meanings = collect_meanings(entry, MAX_MEANINGS)
        translations = build_translations(meanings, TARGET_LANGS)
        examples = gather_examples(entry, word, MAX_EXAMPLES)
        ipa, romanization = extract_pronunciation(entry)
        audio_path = fetch_wikimedia_audio(entry, word)

        cards.append(
            {
                "word": entry.get("word", word),
                "rank": rank,
                "translations": translations,
                "examples": examples,
                "audio": audio_path,
                "ipa": ipa,
                "romanization": romanization,
            }
        )
        print(f"  [{rank}/{NUM_WORDS}] {word}", end="\r", flush=True)

    print(f"\nPrepared {len(cards)} cards")
    if missing:
        print(f"⚠️ Missing dictionary entries for: {', '.join(missing)}")

    if not cards:
        print("No cards to export. Exiting.")
        return

    if PREVIEW_ENABLED:
        html_doc = create_preview_html(cards, TARGET_LANGS)
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as tmp:
            tmp.write(html_doc)
            preview_path = tmp.name
        print("Opening preview. Close the browser tab when done...")
        webbrowser.open(f"file://{preview_path}")
        input("Press Enter to continue after preview...")
        os.unlink(preview_path)

    response = input("Generate Anki deck? (y/n): ").strip().lower()
    if response != "y":
        print("Cancelled.")
        return

    deck_name = f"FreqAnki_{SOURCE_LANG}_Top_{NUM_WORDS}"
    deck_file = create_deck(cards, deck_name, TARGET_LANGS)
    print(f"\n✅ Deck saved to {deck_file}")


if __name__ == "__main__":
    main()
