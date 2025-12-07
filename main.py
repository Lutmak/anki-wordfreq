#!/usr/bin/env python3
"""FreqAnki - Generate frequency-based Anki decks with translations"""

import os
import sys
import re
import hashlib
import webbrowser
import tempfile
import json

try:
    import requests
    import genanki
    from wordfreq import top_n_list
    from dotenv import load_dotenv
    from tatoebatools import ParallelCorpus
    from gtts import gTTS
except ImportError as e:
    print(f"Missing: {e}\nRun: pip install wordfreq genanki requests python-dotenv tatoebatools gTTS")
    sys.exit(1)

load_dotenv()

# =============================================================================
# CONFIG
# =============================================================================
DEEPL_KEY = os.getenv("DEEPL_API_KEY")
SOURCE = "ru"
TARGETS = ["en", "es"]
NUM_WORDS = 10
NUM_EXAMPLES = 2
GENERATE_AUDIO = True
# =============================================================================

# Tatoeba language code mapping
TATOEBA_CODES = {
    'en': 'eng', 'es': 'spa', 'fr': 'fra', 'de': 'deu', 'it': 'ita',
    'pt': 'por', 'ru': 'rus', 'ja': 'jpn', 'zh': 'cmn', 'ko': 'kor'
}

# Wiktionary language mapping
WIKTIONARY_LANG_NAMES = {
    'ru': 'Russian', 'en': 'English', 'es': 'Spanish', 'fr': 'French',
    'de': 'German', 'it': 'Italian', 'pt': 'Portuguese', 'zh': 'Chinese',
    'ja': 'Japanese', 'ko': 'Korean', 'ar': 'Arabic', 'hi': 'Hindi',
    'nl': 'Dutch', 'sv': 'Swedish', 'pl': 'Polish', 'tr': 'Turkish'
}

def get_wiktionary_translation(word, source_lang, target_lang='en'):
    """
    Get translation from Wiktionary for single-character words.
    Returns the first translation found, or None if not found.
    """
    source_name = WIKTIONARY_LANG_NAMES.get(source_lang, source_lang.capitalize())
    
    url = "https://en.wiktionary.org/w/api.php"
    params = {
        'action': 'parse',
        'page': word,
        'prop': 'wikitext',
        'format': 'json'
    }
    
    # CRITICAL: Wikimedia APIs require a User-Agent header
    headers = {
        'User-Agent': 'FreqAnki/1.0 (Language Learning Deck Generator; https://github.com/yourusername/freqanki)'
    }
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        
        if 'error' in data:
            return None
        
        wikitext = data['parse']['wikitext']['*']
        
        # Find the source language section (e.g., ==Russian==)
        lang_marker = f'=={source_name}=='
        if lang_marker not in wikitext:
            return None
        
        # Extract just the source language section
        lang_start = wikitext.find(lang_marker)
        rest = wikitext[lang_start + len(lang_marker):]
        
        # Find next top-level language section (==Language==)
        next_lang_match = re.search(r'\n==[^=]', rest)
        if next_lang_match:
            lang_section = rest[:next_lang_match.start()]
        else:
            lang_section = rest
        
        # Extract translations from definition lines
        translations = []
        
        # Pattern: [[word]] or [[word#Type|word]]
        wikilink_pattern = re.compile(r'\[\[([^|#\]]+)(?:#[^|\]]+)?(?:\|([^\]]+))?\]\]')
        
        # Track current part-of-speech to avoid unrelated senses
        current_pos = None
        allowed_pos = {
            'noun', 'proper noun', 'verb', 'adjective', 'adverb',
            'pronoun', 'preposition', 'postposition', 'conjunction',
            'particle', 'interjection', 'numeral', 'determiner',
            'phrase', 'idiom', 'proverb', 'expression'
        }
        
        for raw_line in lang_section.splitlines():
            line = raw_line.strip()
            
            # Track section headings (====Preposition====)
            heading_match = re.match(r'^={4}([^=]+)={4}$', line)
            if heading_match:
                current_pos = heading_match.group(1).strip().lower()
                continue
            
            # Only process definition lines (#)
            if not line.startswith('#'):
                continue
            if len(line) > 1 and line[1] in ':*;-=^':
                continue
            
            # Skip if we're in a non-word section
            if current_pos and current_pos not in allowed_pos:
                continue
            
            # Extract wikilinks from this line
            for match in wikilink_pattern.finditer(line):
                link_target = match.group(1)
                display_text = match.group(2) if match.group(2) else link_target
                translation = display_text.strip()
                
                # Filter: must be lowercase and reasonable length
                if not translation or len(translation) > 20:
                    continue
                if not re.match(r'^[a-z\s\-]+$', translation):
                    continue
                
                if translation not in translations:
                    translations.append(translation)
        
        # Return first translation or None
        return translations[0] if translations else None
        
    except Exception as e:
        print(f"\nWiktionary error for '{word}': {e}")
        return None

def get_usage_examples(word, source_lang, count=3):
    """Get short usage examples for a word from Tatoeba (for context)"""
    try:
        src = TATOEBA_CODES.get(source_lang, source_lang)
        corpus = ParallelCorpus(src, 'eng')  # Just need source sentences
        
        pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
        examples = []
        
        for sentence, _ in corpus:
            if pattern.search(sentence.text):
                examples.append(sentence.text)
                if len(examples) >= count:
                    break
        
        return examples
    except:
        return []

def batch_translate(words, source, target, key):
    """
    Translate multiple words in one API call using DeepL.
    For single-character words, uses Wiktionary fallback instead.
    """
    if not key:
        raise ValueError("DEEPL_API_KEY not found in .env file")
    
    # Separate single-char from multi-char words
    single_char_words = [(i, w) for i, w in enumerate(words) if len(w) == 1]
    multi_char_words = [(i, w) for i, w in enumerate(words) if len(w) > 1]
    
    # Initialize results array
    results = [None] * len(words)
    
    # Process single-char words with Wiktionary
    if single_char_words:
        print(f"    Using Wiktionary for {len(single_char_words)} single-char word(s)...", end=' ')
        for idx, word in single_char_words:
            translation = get_wiktionary_translation(word, source, target)
            results[idx] = translation if translation else word  # Fallback to original if not found
        print("✓")
    
    # Process multi-char words with DeepL batch translation
    if multi_char_words:
        multi_indices = [idx for idx, _ in multi_char_words]
        multi_words = [w for _, w in multi_char_words]
        
        # Build context for multi-char words
        context_parts = []
        for word in multi_words[:8]:
            context_parts.append(f"{word}.")
        context = " ".join(context_parts) if context_parts else f"Common {source.upper()} words."
        
        payload = {
            "text": multi_words,
            "source_lang": source.upper(),
            "target_lang": target.upper(),
            "context": context
        }
        
        try:
            r = requests.post(
                "https://api-free.deepl.com/v2/translate",
                headers={"Authorization": f"DeepL-Auth-Key {key}"},
                json=payload,
                timeout=30
            )
            r.raise_for_status()
            translations = [t["text"] for t in r.json()["translations"]]
            
            # Map translations back to original indices
            for i, trans in zip(multi_indices, translations):
                results[i] = trans
                
        except Exception as e:
            print(f"\nDeepL API error: {e}")
            # Fallback: keep original words
            for idx in multi_indices:
                if results[idx] is None:
                    results[idx] = words[idx]
    
    return results

def get_examples(word, source_lang, target_lang, max_examples=2):
    """Get example sentences from Tatoeba - matches whole word only"""
    examples = []
    try:
        src = TATOEBA_CODES.get(source_lang, source_lang)
        tgt = TATOEBA_CODES.get(target_lang, target_lang)
        
        corpus = ParallelCorpus(src, tgt)
        
        # Use word boundary regex to match whole word only
        pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
        
        for sentence, translation in corpus:
            if pattern.search(sentence.text):
                examples.append((sentence.text, translation.text))
                if len(examples) >= max_examples:
                    break
    except Exception as e:
        print(f"\nTatoeba error for '{word}': {e}")
    
    return examples

def generate_audio(text, lang):
    """Generate audio file using gTTS"""
    try:
        os.makedirs("audio", exist_ok=True)
        filename = f"{hashlib.md5(text.encode()).hexdigest()}.mp3"
        filepath = os.path.join("audio", filename)
        
        if not os.path.exists(filepath):
            tts = gTTS(text=text, lang=lang, slow=False)
            tts.save(filepath)
        
        return filepath
    except Exception as e:
        print(f"\nAudio error for '{text}': {e}")
        return None

def create_preview_html(words_data):
    """Generate HTML preview with navigation"""
    cards_json = []
    
    for data in words_data:
        trans_html = "".join([f"<div><b>{k.upper()}:</b> {v}</div>" 
                              for k, v in data['translations'].items()])
        
        examples_html = ""
        if data.get('examples'):
            for src, tgt in data['examples']:
                examples_html += f"<div style='margin:10px 0'>• {src}<br><i style='color:#999'>{tgt}</i></div>"
        else:
            examples_html = "<i style='color:#666'>No examples found</i>"
        
        cards_json.append({
            'word': data['word'],
            'rank': data['rank'],
            'translations': trans_html,
            'examples': examples_html,
            'audio': "🔊 Audio" if data.get('audio') else ""
        })
    
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
            border-radius: 12px;
            padding: 40px;
            margin: 20px 0;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }}
        .word {{ font-size: 72px; margin: 40px 0; }}
        .translations {{ font-size: 24px; margin: 30px 0; }}
        .translations div {{ margin: 15px 0; }}
        .examples {{
            text-align: left;
            font-size: 18px;
            margin: 30px auto;
            max-width: 600px;
            padding: 20px;
            background: #1a1a1a;
            border-radius: 8px;
        }}
        .rank {{ color: #888; margin: 20px 0; }}
        .audio {{ color: #4CAF50; margin: 10px 0; }}
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
        hr {{ border: 1px solid #444; margin: 40px 0; }}
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
            <h2>FRONT</h2>
            <div class="word" id="front-word"></div>
            <div class="audio" id="front-audio"></div>
            <div class="rank">Rank: #<span id="front-rank"></span></div>
        </div>
        
        <div class="card">
            <h2>BACK</h2>
            <div class="word" id="back-word"></div>
            <hr>
            <div class="translations" id="translations"></div>
            <div class="examples" id="examples"></div>
            <div class="audio" id="back-audio"></div>
            <div class="rank">Rank: #<span id="back-rank"></span></div>
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
            document.getElementById('front-rank').textContent = card.rank;
            document.getElementById('front-audio').textContent = card.audio;
            document.getElementById('back-word').textContent = card.word;
            document.getElementById('back-rank').textContent = card.rank;
            document.getElementById('back-audio').textContent = card.audio;
            document.getElementById('translations').innerHTML = card.translations;
            document.getElementById('examples').innerHTML = card.examples;
            
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
    deck_id = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)
    deck = genanki.Deck(deck_id, name)
    
    # Build fields dynamically
    fields = [{'name': 'Word'}, {'name': 'Rank'}]
    fields.extend([{'name': f'Trans_{t}'} for t in targets])
    fields.extend([{'name': 'Examples'}, {'name': 'Audio'}])
    
    # Build template
    trans_back = "".join([f"<div style='margin:15px 0'><b>{t.upper()}:</b> {{{{Trans_{t}}}}}</div>" 
                          for t in targets])
    
    model = genanki.Model(
        int(hashlib.md5(b"FreqAnki-v7").hexdigest()[:8], 16),
        'FreqAnki',
        fields=fields,
        templates=[{
            'name': 'Card',
            'qfmt': '<div style="font-size:72px;text-align:center;margin:60px;">{{Word}}</div>'
                    '<div style="text-align:center;">{{Audio}}</div>'
                    '<div style="color:#666;text-align:center;">Rank: {{Rank}}</div>',
            'afmt': '<div style="font-size:48px;text-align:center;margin:40px;">{{Word}}</div><hr>' +
                    trans_back +
                    '<div style="margin:30px;padding:20px;background:#f9f9f9;border-radius:8px;text-align:left;">'
                    '<b>📝 Examples:</b><br>{{Examples}}</div>'
                    '<div style="text-align:center;">{{Audio}}</div>'
                    '<div style="color:#666;text-align:center;margin-top:40px;">Rank: {{Rank}}</div>'
        }]
    )
    
    media_files = []
    
    for data in words_data:
        # Build field values
        fields_data = [data['word'], str(data['rank'])]
        fields_data.extend([data['translations'].get(t, '') for t in targets])
        
        # Examples
        examples = ""
        if data.get('examples'):
            for src, tgt in data['examples']:
                examples += f"• {src}<br><i>{tgt}</i><br><br>"
        else:
            examples = "<i>No examples available</i>"
        fields_data.append(examples)
        
        # Audio
        audio = ""
        if data.get('audio'):
            media_files.append(data['audio'])
            audio = f"[sound:{os.path.basename(data['audio'])}]"
        fields_data.append(audio)
        
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
    words = top_n_list(SOURCE, NUM_WORDS)
    print(f"📚 Got {len(words)} most frequent {SOURCE.upper()} words")
    
    # Batch translate all words for each target language
    print(f"\n🌐 Translating to {len(TARGETS)} language(s)...")
    all_translations = {}
    for target in TARGETS:
        print(f"  → {target.upper()}")
        translations = batch_translate(words, SOURCE, target, DEEPL_KEY)
        all_translations[target] = translations
    
    # Process each word
    print(f"\n⚙️  Processing {NUM_WORDS} words...")
    words_data = []
    
    for i, word in enumerate(words, 1):
        print(f"  [{i}/{NUM_WORDS}] {word}", end='\r')
        
        # Collect translations
        translations = {t: all_translations[t][i-1] for t in TARGETS if all_translations[t][i-1]}
        
        # Examples (only from first target)
        examples = []
        if TARGETS and NUM_EXAMPLES > 0:
            examples = get_examples(word, SOURCE, TARGETS[0], NUM_EXAMPLES)
        
        # Audio
        audio_file = None
        if GENERATE_AUDIO:
            audio_file = generate_audio(word, SOURCE)
        
        words_data.append({
            'word': word,
            'rank': i,
            'translations': translations,
            'examples': examples,
            'audio': audio_file
        })
    
    print(f"\n✅ Processed {len(words_data)} words")
    
    # Preview
    if words_data:
        html = create_preview_html(words_data)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
            f.write(html)
            temp_path = f.name
        
        print("\n📋 Opening preview in browser...")
        webbrowser.open('file://' + temp_path)
        input("Press Enter after viewing to continue...")
        os.unlink(temp_path)
    
    # Generate deck
    response = input("\nGenerate Anki deck? (y/n): ").strip().lower()
    if response == 'y':
        create_deck(words_data, f"FreqAnki_{SOURCE}_Top_{NUM_WORDS}", TARGETS)
        print("\n🎉 Done! Import the .apkg file into Anki Desktop")
    else:
        print("❌ Cancelled")

if __name__ == "__main__":
    main()