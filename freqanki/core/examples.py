"""Tatoeba example sentence collection."""

import re
from collections import defaultdict

from freqanki.config import TATOEBA_CODES
from freqanki.utils.console import console, create_progress


def compile_word_pattern(word: str) -> re.Pattern:
    """Compile a word boundary pattern for matching."""
    return re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)


def _tokenize_sentence(sentence: str) -> list[str]:
    """Tokenize sentence into words (without punctuation)."""
    return re.findall(r"\b\w+\b", sentence)


def _merge_particles_count(words: list[str]) -> int:
    """
    Count final word groups after merging single-letter particles.

    Returns the number of word groups (for filtering).
    """
    if not words:
        return 0

    count = 0
    i = 0
    while i < len(words):
        if len(words[i]) == 1 and i + 1 < len(words):
            # Single letter + next word = 1 group
            i += 2
        else:
            i += 1
        count += 1
    return count


def collect_examples_for_words(
    words: list[str],
    source_lang: str,
    target_lang: str,
    max_examples: int = 2,
    min_word_groups: int = 4,
    extra_candidates: int = 3,
) -> tuple[dict[str, list[tuple[str, str, str]]], dict[str, list[tuple[str, str, str]]]]:
    """
    Collect the absolute shortest example sentences for each word.

    Scans the ENTIRE Tatoeba corpus to find all valid sentences,
    then picks the shortest ones for each word. Also returns backup
    candidates for retrying if sentences fail translation.

    Filtering:
    - Only sentences with min_word_groups+ word groups (after merging particles)
    - Sorted by length, shortest first

    Args:
        words: List of words to find examples for
        source_lang: Source language code
        target_lang: Target language code
        max_examples: Maximum examples per word
        min_word_groups: Minimum word groups after merging particles (default: 4)
        extra_candidates: Extra backup sentences to keep per word (default: 5)

    Returns:
        Tuple of:
        - Dict mapping word to list of (source, target, matched_word) tuples (selected)
        - Dict mapping word to list of backup candidates (not selected, for retries)
    """
    if max_examples <= 0 or not words:
        return {word: [] for word in words}, {word: [] for word in words}

    try:
        from tatoebatools import ParallelCorpus

        # Convert language codes
        src = TATOEBA_CODES.get(source_lang, source_lang)
        tgt = TATOEBA_CODES.get(target_lang, target_lang)

        # Compile patterns for all words
        patterns = {word: compile_word_pattern(word) for word in words}
        words_set = set(words)

        # Collect ALL valid sentences per word
        # Structure: word -> list of (source, target, length)
        candidates: dict[str, list[tuple[str, str, int]]] = defaultdict(list)

        console.print(f"[blue]Collecting examples from Tatoeba ({src}-{tgt})...[/blue]")

        corpus = ParallelCorpus(src, tgt)

        with create_progress() as progress:
            task = progress.add_task("Scanning entire corpus...", total=None)
            count = 0
            valid_count = 0

            for sentence, translation in corpus:
                text = sentence.text
                translated = translation.text if translation else ""

                # Check if sentence has enough word groups after merging particles
                tokenized = _tokenize_sentence(text)
                word_group_count = _merge_particles_count(tokenized)

                if word_group_count < min_word_groups:
                    continue

                valid_count += 1

                # Check which words this sentence contains
                for word in words_set:
                    if patterns[word].search(text):
                        candidates[word].append((text, translated, len(text)))

                count += 1
                if count % 50000 == 0:
                    found = sum(1 for w in words if candidates[w])
                    progress.update(
                        task,
                        description=f"Scanning corpus... ({found}/{len(words)} words, {valid_count} valid sentences)",
                    )

        # For each word, sort by length and take the shortest
        results: dict[str, list[tuple[str, str, str]]] = {}
        backups: dict[str, list[tuple[str, str, str]]] = {}

        for word in words:
            word_candidates = candidates.get(word, [])

            if not word_candidates:
                results[word] = []
                backups[word] = []
                continue

            # Sort by length (shortest first)
            word_candidates.sort(key=lambda x: x[2])

            # Deduplicate and take top N + extras for backups
            seen: set[str] = set()
            selected: list[tuple[str, str, str]] = []
            backup_list: list[tuple[str, str, str]] = []

            for text, trans, length in word_candidates:
                if text not in seen:
                    seen.add(text)
                    if len(selected) < max_examples:
                        selected.append((text, trans, word))
                    elif len(backup_list) < extra_candidates:
                        backup_list.append((text, trans, word))
                    else:
                        break  # Have enough

            results[word] = selected
            backups[word] = backup_list

        # Summary
        found = sum(1 for ex in results.values() if ex)
        console.print(f"[green]  Found examples for {found}/{len(words)} words[/green]")

        return results, backups

    except Exception as e:
        console.print(f"[red]Tatoeba error: {e}[/red]")
        return {word: [] for word in words}, {word: [] for word in words}


def collect_all_example_sentences(
    words: list[str],
    source_lang: str,
    target_lang: str,
    max_examples: int = 2,
) -> tuple[
    dict[str, list[tuple[str, str, str]]],
    list[str],
    dict[str, list[tuple[str, str, str]]],
]:
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
        - Dict mapping word to backup sentences (for retries if translation fails)
    """
    examples, backups = collect_examples_for_words(words, source_lang, target_lang, max_examples)

    # Collect unique source sentences
    unique_sentences: list[str] = []
    seen: set[str] = set()

    for word_examples in examples.values():
        for source, _, _ in word_examples:
            if source not in seen:
                seen.add(source)
                unique_sentences.append(source)

    return examples, unique_sentences, backups
