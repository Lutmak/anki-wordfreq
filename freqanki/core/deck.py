"""Anki deck generation using genanki."""

import hashlib
import html
import os
import re
from dataclasses import dataclass
from pathlib import Path

import genanki

from freqanki.utils.console import console


@dataclass
class WordData:
    """Data for a single flashcard word."""

    word: str  # The wordfreq word (source of truth)
    rank: int
    display_word: str
    romanization: str | None = None
    transliteration: str | None = None  # From Kaikki (e.g., with stress marks)
    morphology: dict | None = None
    translations: dict[str, str] | None = None  # {lang: translation}
    examples: list[tuple[str, str, str]] | None = None  # [(src, tgt, matched)]
    literal_translations: dict[str, str] | None = None  # {sentence: translation}
    word_translations: dict[str, list[tuple[str, str]]] | None = None  # {sentence: [(word, trans)]}
    audio_path: Path | None = None


def highlight_word(text: str, word: str, color: str = "#ffcc00") -> str:
    """Highlight word occurrences in text with HTML styling."""
    if not text:
        return ""
    if not word:
        return html.escape(text)

    pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
    last = 0
    parts: list[str] = []

    for m in pattern.finditer(text):
        parts.append(html.escape(text[last : m.start()]))
        parts.append(f"<b style='color:{color}'>" + html.escape(m.group(0)) + "</b>")
        last = m.end()
    parts.append(html.escape(text[last:]))

    return "".join(parts)


def format_morphology_html(morph_info: dict | None) -> str:
    """Format morphology info as HTML."""
    if not morph_info:
        return ""

    rows: list[str] = []

    def add_row(label: str, value: str | None) -> None:
        if not value:
            return
        rows.append(
            "<div style='display:flex;flex-direction:column;align-items:center;"
            "padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.12);'>"
            f"<span style='font-size:12px;text-transform:uppercase;"
            f"letter-spacing:1px;color:#a0a0a0;'>{label}</span>"
            f"<span style='font-size:20px;font-weight:600;color:#fdfdfd;"
            f"margin-top:4px;text-align:center;'>{html.escape(str(value))}</span>"
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

    # Dynamic grid: 1 col for 1-2 items, 3 cols for 3+ items (2 rows x 3 cols)
    if len(rows) <= 2:
        container_style = (
            "display:flex;flex-direction:column;gap:4px;margin-top:8px;text-align:center;"
        )
    else:
        container_style = (
            "display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;"
            "margin-top:8px;text-align:center;"
        )

    return f"<div style='{container_style}'>" + "".join(rows) + "</div>"


def format_meanings_html(translations: dict[str, str], target_langs: list[str]) -> str:
    """Format translations as HTML meaning lines."""
    lines: list[str] = []

    for lang in target_langs:
        text = translations.get(lang)
        if not text:
            continue
        lines.append(
            "<div style='display:flex;flex-direction:column;align-items:center;"
            "gap:4px;margin:6px 0;'>"
            f"<span style='font-size:12px;letter-spacing:1px;color:#0f0f0f;"
            f"background:#f9cf6c;border-radius:999px;padding:4px 10px;"
            f"display:inline-flex;'>{lang.upper()}</span>"
            f"<span style='font-size:19px;color:#f7f7f7;text-align:center;'>"
            f"{html.escape(text)}</span>"
            "</div>"
        )

    if not lines:
        return "<div style='color:#8a8a8a;font-style:italic;'>No meanings available</div>"

    return "".join(lines)


def format_word_by_word_html(
    word_pairs: list[tuple[str, str]],
    matched_word: str,
    highlight_color: str = "#ffcc00",
) -> tuple[list[str], list[str]]:
    """
    Format word-by-word translations as cell lists (not full rows).

    Args:
        word_pairs: List of (source_display, translated) tuples
            source_display may be merged words like "С Хэллоуином"
        matched_word: The target word to highlight
        highlight_color: Color for highlighting

    Returns:
        Tuple of (source_cells, translation_cells) - lists of <td> elements
    """
    source_cells: list[str] = []
    trans_cells: list[str] = []

    # Create pattern to check if matched word is contained in source
    matched_pattern = re.compile(r"\b" + re.escape(matched_word) + r"\b", re.IGNORECASE)

    for src_display, trans_word in word_pairs:
        # Check if matched word is CONTAINED in source (for merged groups)
        is_matched = bool(matched_pattern.search(src_display))

        if is_matched:
            src_style = f"color:{highlight_color};font-weight:bold;"
            trans_style = f"color:{highlight_color};font-weight:bold;"
        else:
            src_style = "color:#f7f7f7;"
            trans_style = "color:#a0a0a0;"

        source_cells.append(
            f"<td style='padding:4px 10px;text-align:center;font-size:17px;{src_style}'>"
            f"{html.escape(src_display)}</td>"
        )
        trans_cells.append(
            f"<td style='padding:4px 10px;text-align:center;{trans_style}font-size:15px;'>"
            f"{html.escape(trans_word)}</td>"
        )

    return source_cells, trans_cells


def format_examples_html(
    examples: list[tuple[str, str, str]] | None,
    literal_translations: dict[str, str] | None = None,
    word_translations: dict[str, list[tuple[str, str]]] | None = None,
) -> str:
    """
    Format example sentences as HTML tables.

    Args:
        examples: List of (source, target, matched_word) tuples
        literal_translations: Dict of sentence -> full literal translation (fallback)
        word_translations: Dict of sentence -> [(word, translation)] for table format

    Returns:
        HTML string with formatted examples
    """
    if not examples:
        return "<div style='color:#8a8a8a;font-style:italic;'>No examples available</div>"

    blocks: list[str] = []

    # Simple label style - subtle text, no background
    label_style = (
        "font-size:10px;letter-spacing:0.5px;color:#666;text-transform:uppercase;"
    )

    for src, tgt, matched in examples:
        # Check if we have word-by-word translations for this sentence
        if word_translations and src in word_translations:
            word_pairs = word_translations[src]
            source_cells, trans_cells = format_word_by_word_html(word_pairs, matched)
            num_cols = len(source_cells)

            # Label cell style - subtle and unobtrusive
            label_cell_style = "padding:2px 6px;text-align:right;vertical-align:middle;"

            # Table with simple text labels at start of each row
            block = (
                "<div style='margin:10px 0;text-align:center;'>"
                "<table style='display:inline-table;border-collapse:collapse;background:#1a1a1a;"
                "border-radius:8px;overflow:hidden;'>"
                # Row 1: RUSSIAN [source words]
                f"<tr><td style='{label_cell_style}{label_style}'>RUSSIAN</td>"
                + "".join(source_cells) + "</tr>"
                # Row 2: LITERALLY [translations]
                f"<tr><td style='{label_cell_style}{label_style}'>LITERALLY</td>"
                + "".join(trans_cells) + "</tr>"
                # Row 3: ENGLISH [natural translation]
                f"<tr><td style='{label_cell_style}{label_style}'>ENGLISH</td>"
                f"<td colspan='{num_cols}' style='padding:4px 10px;"
                f"color:#a3a3a3;font-style:italic;text-align:left;font-size:16px;'>"
                f"{html.escape(tgt)}</td></tr>"
                "</table></div>"
            )
        else:
            # Fallback to simple format
            src_html = highlight_word(src, matched)
            tgt_html = highlight_word(tgt, matched)

            block = (
                "<div style='margin:12px 0;line-height:1.6;font-size:18px;text-align:center;'>"
                f"• {src_html}"
                f"<div style='color:#a3a3a3;font-size:16px;margin-top:6px;'>"
                f"<i>{tgt_html}</i></div>"
            )

            # Add literal translation if available (old format fallback)
            if literal_translations and src in literal_translations:
                literal = literal_translations[src]
                block += (
                    f"<div style='color:#8a8a8a;font-size:14px;margin-top:4px;'>"
                    f"[{html.escape(literal)}]</div>"
                )

            block += "</div>"

        blocks.append(block)

    return "".join(blocks)


def build_card_content_block(
    translations: dict[str, str],
    target_langs: list[str],
    morphology: dict | None,
    examples: list[tuple[str, str, str]] | None,
    literal_translations: dict[str, str] | None = None,
    word_translations: dict[str, list[tuple[str, str]]] | None = None,
) -> str:
    """Build the complete card content block with all sections in one container."""
    meanings_html = format_meanings_html(translations, target_langs)
    morph_html = format_morphology_html(morphology)
    examples_html = format_examples_html(examples, literal_translations, word_translations)

    # Section title style
    title_style = (
        "text-transform:uppercase;letter-spacing:1px;font-size:14px;"
        "color:#f9cf6c;text-align:center;"
    )
    # Divider style
    divider = (
        "<div style='width:100%;height:1px;background:rgba(249,207,108,0.25);"
        "margin:12px 0 8px;'></div>"
    )

    # Start container
    block = (
        "<div style='text-align:left;background:#1f1f1f;border:1px solid #2f2f2f;"
        "border-radius:14px;padding:16px 20px;margin:14px auto;max-width:650px;'>"
    )

    # Possible Meanings section
    block += (
        f"<div style='{title_style}'>Possible Meanings</div>"
        "<div style='margin-top:4px;font-size:19px;line-height:1.4;color:#f7f7f7;"
        f"text-align:center;'>{meanings_html}</div>"
    )

    # Grammar Notes section (if available)
    if morph_html:
        block += divider
        block += (
            f"<div style='{title_style}'>Grammar Notes</div>"
            f"<div style='margin-top:4px;text-align:center;'>{morph_html}</div>"
        )

    # Usage Examples section
    block += divider
    block += (
        f"<div style='{title_style}'>Usage Examples</div>"
        "<div style='margin-top:4px;font-size:19px;line-height:1.4;color:#f7f7f7;"
        f"text-align:center;'>{examples_html}</div>"
    )

    block += "</div>"
    return block


def create_anki_model() -> genanki.Model:
    """Create the Anki note model."""
    # v11: Combined content block (meanings + grammar + examples in one)
    model_id = int(hashlib.md5(b"FreqAnki-v11").hexdigest()[:8], 16)

    return genanki.Model(
        model_id,
        "FreqAnki",
        fields=[
            {"name": "Word"},
            {"name": "Rank"},
            {"name": "Romanization"},
            {"name": "Content"},
            {"name": "Audio"},
        ],
        templates=[
            {
                "name": "Card",
                "qfmt": (
                    "<div style='font-family:Arial,sans-serif;background:#111;"
                    "color:#fff;padding:32px;border-radius:16px;'>"
                    "<div style='font-size:64px;text-align:center;margin:12px 0 6px;'>"
                    "{{Word}}</div>"
                    "{{#Audio}}<div style='text-align:center;margin:8px 0;'>"
                    "{{Audio}}</div>{{/Audio}}"
                    "<div style='display:flex;justify-content:center;gap:10px;"
                    "flex-wrap:wrap;margin-top:12px;'>"
                    "<div style='padding:6px 14px;border-radius:999px;"
                    "border:1px solid #3a3a3a;background:#1f1f1f;color:#f9cf6c;"
                    "font-size:15px;'>Rank #{{Rank}}</div>"
                    "</div></div>"
                ),
                "afmt": (
                    "<div style='font-family:Arial,sans-serif;background:#111;"
                    "color:#fff;padding:32px;border-radius:16px;'>"
                    # Header with word and romanization
                    "<div style='text-align:center;margin-bottom:12px;'>"
                    "<div style='font-size:48px;margin-bottom:8px;'>{{Word}}</div>"
                    "{{#Romanization}}<div style='padding:6px 14px;"
                    "border-radius:999px;border:1px solid #3a3a3a;background:#1f1f1f;"
                    "color:#f9cf6c;font-size:15px;display:inline-block;'>"
                    "{{Romanization}}</div>{{/Romanization}}"
                    "</div>"
                    "{{#Audio}}<div style='text-align:center;margin-bottom:12px;'>"
                    "{{Audio}}</div>{{/Audio}}"
                    "{{Content}}"
                    "</div>"
                ),
            }
        ],
    )


def create_deck(
    words_data: list[WordData],
    deck_name: str,
    target_langs: list[str],
) -> str:
    """
    Create an Anki deck from word data.

    Args:
        words_data: List of WordData objects
        deck_name: Name for the deck
        target_langs: Target languages for ordering meanings

    Returns:
        Path to created .apkg file
    """
    console.print(f"[blue]Creating Anki deck: {deck_name}[/blue]")

    # Create deck
    deck_id = int(hashlib.md5(deck_name.encode()).hexdigest()[:8], 16)
    deck = genanki.Deck(deck_id, deck_name)
    model = create_anki_model()

    media_files: list[str] = []

    for data in words_data:
        # Build combined content block (meanings + grammar + examples)
        content_block = build_card_content_block(
            data.translations or {},
            target_langs,
            data.morphology,
            data.examples,
            data.literal_translations,
            data.word_translations,
        )

        audio_field = ""
        if data.audio_path and data.audio_path.exists():
            media_files.append(str(data.audio_path))
            audio_field = f"[sound:{data.audio_path.name}]"

        # Build romanization badge: "word | romanization | ipa" (no labels)
        romanization_parts: list[str] = []
        if data.display_word:
            romanization_parts.append(data.display_word)
        if data.romanization:
            romanization_parts.append(data.romanization)
        if data.transliteration and data.transliteration != data.romanization:
            # Remove brackets from IPA
            ipa_clean = data.transliteration.strip("[]")
            romanization_parts.append(ipa_clean)

        romanization_field = " | ".join(romanization_parts) if romanization_parts else ""

        fields = [
            data.display_word,
            str(data.rank),
            html.escape(romanization_field),
            content_block,
            audio_field,
        ]

        deck.add_note(genanki.Note(model=model, fields=fields))

    # Save package
    output_path = f"{deck_name.replace(' ', '_')}.apkg"
    package = genanki.Package(deck)
    package.media_files = media_files
    package.write_to_file(output_path)

    console.print(f"[green]Created: {output_path}[/green]")
    return output_path
