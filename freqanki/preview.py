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
        # Get IPA from transliteration (strip brackets)
        ipa = ""
        if data.transliteration:
            ipa = data.transliteration.strip("[]")

        # Use the same HTML generation as Anki cards for consistency
        content_html = build_card_content_block(
            display_word=data.display_word,
            audio_field="🔊" if data.audio_path else "",
            romanization=data.romanization or "",
            ipa=ipa,
            translations=data.translations or {},
            target_langs=target_langs,
            morphology=data.morphology,
            examples=data.examples,
            literal_translations=data.literal_translations,
            word_translations=data.word_translations,
        )

        cards_json.append(
            {
                "word": data.display_word,
                "rank": data.rank,
                "content": content_html,
            }
        )

    html_content = f"""<!DOCTYPE html>
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
        .front-card {{
            background: #111;
            border-radius: 16px;
            padding: 32px;
            margin: 18px 0;
            box-shadow: 0 8px 30px rgba(0,0,0,0.35);
        }}
        .back-card {{
            background: #111;
            border-radius: 16px;
            padding: 32px;
            margin: 18px 0;
            box-shadow: 0 8px 30px rgba(0,0,0,0.35);
        }}
        .word {{ font-size: 64px; margin: 12px 0 6px; }}
        .chip {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 6px 14px;
            border-radius: 999px;
            background: #1f1f1f;
            border: 1px solid #3a3a3a;
            font-size: 15px;
            color: #f9cf6c;
        }}
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

        <div class="front-card">
            <div class="word" id="front-word"></div>
            <div style="display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin-top:12px;">
                <div class="chip" id="front-rank"></div>
            </div>
        </div>

        <div class="back-card">
            <div id="content"></div>
        </div>

        <div class="nav">
            <button onclick="window.close()">Close & Continue</button>
        </div>
    </div>

    <script>
        const cards = {json.dumps(cards_json)};
        let currentIndex = 0;

        function showCard(index) {{
            const card = cards[index];

            document.getElementById('front-word').textContent = card.word;
            document.getElementById('front-rank').textContent = 'Rank #' + card.rank;
            document.getElementById('content').innerHTML = card.content;

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
