"""HTML preview generation for FreqAnki cards.

Uses the same HTML generation as deck.py to ensure preview matches final cards.
"""

import json
import tempfile
import webbrowser
from pathlib import Path

from freqanki.core.deck import WordData, build_card_content_block


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
        # Use the same HTML generation as Anki cards for consistency
        content_html = build_card_content_block(
            data.translations or {},
            target_langs,
            data.morphology,
            data.examples,
            data.literal_translations,
            data.word_translations,
        )

        # Build romanization: "word | romanization | ipa" (no labels)
        romanization_parts: list[str] = []
        #TODO: instead of hardcoding "Russian:", get language name from lang module
        if data.display_word:
            romanization_parts.append("Russian: " + data.display_word)
        if data.romanization:
            romanization_parts.append("Romanization: " + data.romanization)
        if data.transliteration and data.transliteration != data.romanization:
            # Remove brackets from IPA
            ipa_clean = data.transliteration.strip("[]")
            romanization_parts.append("Ipa: " + ipa_clean)

        romanization_display = " | ".join(romanization_parts) if romanization_parts else ""

        cards_json.append(
            {
                "word": data.display_word,
                "rank": data.rank,
                "romanization": romanization_display,
                "audio": "Audio" if data.audio_path else "",
                "content": content_html,
            }
        )

    html_content = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>FreqAnki Preview</title>
    <style>
        /* Page layout - preview wrapper only */
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
            background: #111;
            border-radius: 16px;
            padding: 32px;
            margin: 18px 0;
            box-shadow: 0 8px 30px rgba(0,0,0,0.35);
        }}
        .word {{ font-size: 68px; margin: 20px 0 14px; }}
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
        .chip.roman {{
            font-size: 12px;
            letter-spacing: 1px;
            color: #0f0f0f;
            background: #f9cf6c;
            border-radius: 999px;
            padding: 4px 10px;
            border: none;
        }}
        .chip.rank {{ color: #f9cf6c; }}
        .audio-line {{ color: #4CAF50; margin: 8px 0; font-size: 16px; min-height: 20px; }}
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
            <div id="content"></div>
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
            document.getElementById('content').innerHTML = card.content;
            setLine('back-audio', card.audio);
            setChip('back-romanization', card.romanization ? card.romanization : '');

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
