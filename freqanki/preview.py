"""HTML preview generation for FreqAnki cards."""

import html
import json
import re
import tempfile
import webbrowser
from pathlib import Path

from freqanki.core.deck import WordData, format_morphology_html, highlight_word


def build_meanings_preview_html(
    translations: dict[str, str] | None,
    target_langs: list[str],
) -> str:
    """Build meanings HTML for preview."""
    if not translations:
        return "<div class='muted'>No meanings available</div>"

    lines: list[str] = []
    for lang in target_langs:
        text = translations.get(lang)
        if not text:
            continue
        lines.append(
            "<div class='meaning-line'>"
            f"<span class='lang-pill'>{lang.upper()}</span>"
            f"<span class='meaning-text'>{html.escape(text)}</span>"
            "</div>"
        )

    if not lines:
        return "<div class='muted'>No meanings available</div>"

    return "".join(lines)


def build_examples_preview_html(
    examples: list[tuple[str, str, str]] | None,
    literal_translations: dict[str, str] | None = None,
) -> str:
    """Build examples HTML for preview."""
    if not examples:
        return "<div class='muted'>No examples found</div>"

    lines: list[str] = []
    for src, tgt, matched in examples:
        src_html = highlight_word(src, matched)
        tgt_html = highlight_word(tgt, matched)

        line = (
            "<div class='example-line'>"
            f"<div>• {src_html}</div>"
            f"<i>{tgt_html}</i>"
        )

        if literal_translations and src in literal_translations:
            line += f"<div class='literal'>[{html.escape(literal_translations[src])}]</div>"

        line += "</div>"
        lines.append(line)

    return "".join(lines)


def build_top_section_html(
    translations: dict[str, str] | None,
    target_langs: list[str],
    morphology: dict | None,
) -> str:
    """Build combined meanings and grammar section."""
    meanings_html = build_meanings_preview_html(translations, target_langs)
    morph_html = format_morphology_html(morphology)

    block = [
        "<div class='info-section stacked-info'>",
        "<div class='section-title'>Possible Meanings</div>",
        f"<div class='section-body meaning-body'>{meanings_html}</div>",
    ]

    if morph_html:
        block.append("<div class='section-divider'></div>")
        block.append("<div class='section-title'>Grammar Notes</div>")
        block.append(f"<div class='section-body grammar-body'>{morph_html}</div>")

    block.append("</div>")
    return "".join(block)


def create_preview_html(
    words_data: list[WordData],
    target_langs: list[str],
) -> Path:
    """
    Generate HTML preview for cards.

    Args:
        words_data: List of WordData objects
        target_langs: Target languages for display order

    Returns:
        Path to generated HTML file
    """
    cards_json = []

    for data in words_data:
        top_section = build_top_section_html(
            data.translations,
            target_langs,
            data.morphology,
        )

        examples_html = (
            "<div class='info-section'>"
            "<div class='section-title'>Usage Examples</div>"
            f"<div class='section-body'>{build_examples_preview_html(data.examples, data.literal_translations)}</div>"
            "</div>"
        )

        cards_json.append(
            {
                "word": data.display_word,
                "rank": data.rank,
                "romanization": data.romanization or "",
                "audio": "Audio" if data.audio_path else "",
                "top_section": top_section,
                "examples": examples_html,
            }
        )

    html_content = f'''<!DOCTYPE html>
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
        .literal {{ color: #8a8a8a; font-size: 14px; margin-top: 4px; }}
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
            <button onclick="prevCard()">Previous</button>
            <span class="counter"><span id="current">1</span> / <span id="total">0</span></span>
            <button onclick="nextCard()">Next</button>
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
            setChip('front-rank', 'Rank #' + card.rank);
            document.getElementById('top-section').innerHTML = card.top_section;
            document.getElementById('examples').innerHTML = card.examples;
            setLine('back-audio', card.audio);
            setChip('back-romanization', card.romanization ? 'Romanization: ' + card.romanization : '');

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
</html>'''

    # Write to temp file
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".html",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(html_content)
        return Path(f.name)


def open_preview(preview_path: Path) -> None:
    """Open preview HTML in default browser."""
    webbrowser.open(f"file://{preview_path}")
