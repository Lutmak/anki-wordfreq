"""Tatoeba example sentence collection."""

import re
from collections import defaultdict

from freqanki.config import TATOEBA_CODES
from freqanki.utils.console import console, create_progress


def compile_word_pattern(word: str) -> re.Pattern:
    """Compile a word boundary pattern for matching."""
    return re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)


def collect_examples_for_words(
    words: list[str],
    source_lang: str,
    target_lang: str,
    max_examples: int = 2,
) -> dict[str, list[tuple[str, str, str]]]:
    """
    Collect example sentences for multiple words in a single pass.

    This is the key optimization - we iterate through the Tatoeba corpus
    ONCE and collect examples for ALL words simultaneously.

    Args:
        words: List of words to find examples for
        source_lang: Source language code
        target_lang: Target language code
        max_examples: Maximum examples per word

    Returns:
        Dict mapping word to list of (source, target, matched_word) tuples
        Sorted by sentence length (shortest first)
    """
    if max_examples <= 0 or not words:
        return {word: [] for word in words}

    try:
        from tatoebatools import ParallelCorpus

        # Convert language codes
        src = TATOEBA_CODES.get(source_lang, source_lang)
        tgt = TATOEBA_CODES.get(target_lang, target_lang)

        # Compile patterns for all words
        patterns = {word: compile_word_pattern(word) for word in words}

        # Collect more candidates than needed for sorting
        max_candidates = max_examples * 3
        candidates: dict[str, list[tuple[str, str, str, int]]] = defaultdict(list)

        console.print(f"[blue]Collecting examples from Tatoeba ({src}-{tgt})...[/blue]")

        corpus = ParallelCorpus(src, tgt)
        remaining = set(words)

        with create_progress() as progress:
            task = progress.add_task("Scanning corpus...", total=None)
            count = 0

            for sentence, translation in corpus:
                if not remaining:
                    break

                text = sentence.text
                translated = translation.text if translation else ""

                # Skip very long sentences
                if len(text) > 200:
                    continue

                for word in list(remaining):
                    if patterns[word].search(text):
                        # Store with length for sorting
                        candidates[word].append((text, translated, word, len(text)))

                        # Check if we have enough for this word
                        if len(candidates[word]) >= max_candidates:
                            remaining.discard(word)

                count += 1
                if count % 10000 == 0:
                    progress.update(
                        task,
                        description=f"Scanning corpus... ({len(words) - len(remaining)}/{len(words)} words found)",
                    )

        # Process results: deduplicate, sort by length, take top N
        results: dict[str, list[tuple[str, str, str]]] = {}

        for word in words:
            word_candidates = candidates.get(word, [])

            # Deduplicate by source text
            seen_texts: set[str] = set()
            unique: list[tuple[str, str, str, int]] = []
            for text, trans, matched, length in word_candidates:
                if text not in seen_texts:
                    seen_texts.add(text)
                    unique.append((text, trans, matched, length))

            # Sort by length (shortest first) and take top N
            unique.sort(key=lambda x: x[3])
            results[word] = [(t, tr, m) for t, tr, m, _ in unique[:max_examples]]

        # Summary
        found = sum(1 for ex in results.values() if ex)
        console.print(f"[green]  Found examples for {found}/{len(words)} words[/green]")

        return results

    except Exception as e:
        console.print(f"[red]Tatoeba error: {e}[/red]")
        return {word: [] for word in words}


def collect_all_example_sentences(
    words: list[str],
    source_lang: str,
    target_lang: str,
    max_examples: int = 2,
) -> tuple[dict[str, list[tuple[str, str, str]]], list[str]]:
    """
    Collect examples and return unique source sentences for batch translation.

    Args:
        words: List of words
        source_lang: Source language code
        target_lang: Target language code
        max_examples: Maximum examples per word

    Returns:
        Tuple of:
        - Dict mapping word to examples
        - List of unique source sentences (for literal translation)
    """
    examples = collect_examples_for_words(words, source_lang, target_lang, max_examples)

    # Collect unique source sentences
    unique_sentences: list[str] = []
    seen: set[str] = set()

    for word_examples in examples.values():
        for source, _, _ in word_examples:
            if source not in seen:
                seen.add(source)
                unique_sentences.append(source)

    return examples, unique_sentences
