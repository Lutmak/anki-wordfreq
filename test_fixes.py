#!/usr/bin/env python3
"""Test script for specific words to verify fixes"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from main import (
    canonicalize_word,
    load_kaikki_entries,
    get_kaikki_glosses,
    get_romanization_for_word,
    get_audio_for_word,
    get_morphological_info,
)

SOURCE = "ru"
TARGETS = ["en"]

def test_words(words):
    print(f"Testing {len(words)} words: {', '.join(words)}")

    # Canonicalize
    canonical_map = {word: canonicalize_word(word) for word in words}
    canonical_words = [canonical_map[word] for word in words]
    print(f"Canonical forms: {canonical_words}")

    # Load Kaikki entries
    kaikki_entries = load_kaikki_entries(canonical_words, SOURCE)

    # Test each word
    for word in words:
        canonical = canonical_map[word]
        print(f"\n--- Testing '{word}' (canonical: '{canonical}') ---")

        # Get meanings
        meanings = get_kaikki_glosses(canonical, kaikki_entries, limit=5)
        print(f"Meanings: {meanings}")

        # Get romanization
        romanization = get_romanization_for_word(canonical, kaikki_entries)
        print(f"Romanization: {romanization}")

        # Get audio (just check if available)
        audio = get_audio_for_word(canonical, kaikki_entries)
        print(f"Audio available: {audio is not None}")

        # Get morphology
        morphology = get_morphological_info(word, SOURCE)
        print(f"Morphology: {morphology}")

if __name__ == "__main__":
    # Test the problematic words from the user
    test_words = ["я", "мне", "меня", "что", "как"]
    test_words(test_words)