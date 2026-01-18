"""Tatoeba example sentence collection with caching."""

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from freqanki.config import TATOEBA_CODES
from freqanki.utils.console import console, create_progress

# Cache directory for corpus data
CACHE_DIR = Path.home() / ".cache" / "freqanki"


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


def _get_corpus_cache_path(source_lang: str, target_lang: str, min_word_groups: int) -> Path:
    """Get the cache file path for a language pair."""
    src = TATOEBA_CODES.get(source_lang, source_lang)
    tgt = TATOEBA_CODES.get(target_lang, target_lang)
    return CACHE_DIR / f"corpus_{src}_{tgt}_min{min_word_groups}.json"


def _load_corpus_cache(
    source_lang: str, target_lang: str, min_word_groups: int
) -> dict[str, list[tuple[str, str]]] | None:
    """
    Load cached corpus data if available.

    Returns:
        Dict mapping lowercase word to list of (source, target) sentence pairs,
        or None if cache doesn't exist.
    """
    cache_path = _get_corpus_cache_path(source_lang, target_lang, min_word_groups)
    if not cache_path.exists():
        return None

    try:
        console.print(f"[cyan]Loading cached corpus from {cache_path.name}...[/cyan]")
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Convert lists back to tuples
        result: dict[str, list[tuple[str, str]]] = {}
        for word, sentences in data.items():
            result[word] = [(s[0], s[1]) for s in sentences]

        console.print(f"[green]  Loaded {len(result)} words from cache[/green]")
        return result
    except Exception as e:
        console.print(f"[yellow]Cache load failed: {e}[/yellow]")
        return None


def _save_corpus_cache(
    source_lang: str,
    target_lang: str,
    min_word_groups: int,
    word_sentences: dict[str, list[tuple[str, str]]],
) -> None:
    """Save corpus data to cache."""
    cache_path = _get_corpus_cache_path(source_lang, target_lang, min_word_groups)

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Convert to JSON-serializable format
        data = {word: list(sentences) for word, sentences in word_sentences.items()}

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        console.print(f"[green]  Cached {len(data)} words to {cache_path.name}[/green]")
    except Exception as e:
        console.print(f"[yellow]Cache save failed: {e}[/yellow]")


def _scan_corpus_for_all_words(
    source_lang: str,
    target_lang: str,
    min_word_groups: int,
) -> dict[str, list[tuple[str, str]]]:
    """
    Scan the entire Tatoeba corpus and index ALL words.

    This is expensive (~13 min) but results are cached for reuse.

    Returns:
        Dict mapping lowercase word to list of (source, target) sentence pairs,
        sorted by sentence length (shortest first).
    """
    from tatoebatools import ParallelCorpus

    src = TATOEBA_CODES.get(source_lang, source_lang)
    tgt = TATOEBA_CODES.get(target_lang, target_lang)

    # Index: word -> list of (source, target, length)
    word_index: dict[str, list[tuple[str, str, int]]] = defaultdict(list)

    console.print(f"[blue]Scanning Tatoeba corpus ({src}-{tgt})...[/blue]")
    console.print("[yellow]  This will be cached for future runs.[/yellow]")

    corpus = ParallelCorpus(src, tgt)

    with create_progress() as progress:
        task = progress.add_task("Scanning corpus...", total=None)
        count = 0
        valid_count = 0

        for sentence, translation in corpus:
            text = sentence.text
            translated = translation.text if translation else ""

            # Check if sentence has enough word groups
            tokenized = _tokenize_sentence(text)
            word_group_count = _merge_particles_count(tokenized)

            if word_group_count < min_word_groups:
                continue

            valid_count += 1
            length = len(text)

            # Index by each word in the sentence (lowercase)
            for word in set(w.lower() for w in tokenized):
                word_index[word].append((text, translated, length))

            count += 1
            if count % 50000 == 0:
                progress.update(
                    task,
                    description=f"Scanning corpus... ({valid_count} valid sentences, {len(word_index)} unique words)",
                )

    console.print(
        f"[green]  Scanned {valid_count} valid sentences, indexed {len(word_index)} words[/green]"
    )

    # Sort each word's sentences by length and keep only (source, target)
    result: dict[str, list[tuple[str, str]]] = {}
    for word, sentences in word_index.items():
        # Sort by length, keep top sentences (limit to avoid huge cache)
        sentences.sort(key=lambda x: x[2])
        result[word] = [(s[0], s[1]) for s in sentences[:50]]  # Keep top 50 per word

    return result


def _select_diverse_examples(
    candidates: list[tuple[str, str, str]],
    target_word: str,
    max_examples: int,
) -> list[tuple[str, str, str]]:
    """
    Select diverse examples that don't share words besides the target word.

    Args:
        candidates: List of (source, target, matched_word) tuples
        target_word: The word being exemplified
        max_examples: Maximum number to select

    Returns:
        Selected diverse examples
    """
    if not candidates:
        return []

    selected: list[tuple[str, str, str]] = []
    target_lower = target_word.lower()

    for cand in candidates:
        source, target, matched = cand

        # Tokenize source sentence to get words (simple split, lowercase)
        words = set(w.lower() for w in source.split() if w.lower() != target_lower)

        # Check if this sentence shares any words with already selected sentences
        overlaps = False
        for sel_source, _, _ in selected:
            sel_words = set(w.lower() for w in sel_source.split() if w.lower() != target_lower)
            if words & sel_words:  # Intersection not empty
                overlaps = True
                break

        if not overlaps:
            selected.append(cand)
            if len(selected) >= max_examples:
                break

    return selected


def collect_examples_for_words(
    words: list[str],
    source_lang: str,
    target_lang: str,
    max_examples: int = 2,
    min_word_groups: int = 4,
) -> tuple[dict[str, list[tuple[str, str, str]]], dict[str, list[tuple[str, str, str]]]]:
    """
    Collect the shortest example sentences for each word.

    Uses a cached corpus index when available. If not cached, scans the
    ENTIRE Tatoeba corpus and caches results for future runs.

    Filtering:
    - Only sentences with min_word_groups+ word groups (after merging particles)
    - Sorted by length, shortest first

    Args:
        words: List of words to find examples for
        source_lang: Source language code
        target_lang: Target language code
        max_examples: Maximum examples per word
        min_word_groups: Minimum word groups after merging particles (default: 4)

    Returns:
        Tuple of:
        - Dict mapping word to list of (source, target, matched_word) tuples
        - Empty dict (kept for API compatibility)
    """
    if max_examples <= 0 or not words:
        return {word: [] for word in words}, {word: [] for word in words}

    try:
        # Try to load from cache first
        corpus_index = _load_corpus_cache(source_lang, target_lang, min_word_groups)

        if corpus_index is None:
            # Cache miss - scan corpus and save
            corpus_index = _scan_corpus_for_all_words(source_lang, target_lang, min_word_groups)
            _save_corpus_cache(source_lang, target_lang, min_word_groups, corpus_index)

        # Look up each word in the index
        results: dict[str, list[tuple[str, str, str]]] = {}
        backups: dict[str, list[tuple[str, str, str]]] = {}

        for word in words:
            word_lower = word.lower()
            word_sentences = corpus_index.get(word_lower, [])

            if not word_sentences:
                results[word] = []
                backups[word] = []
                continue

            # Deduplicate and take top N examples
            seen: set[str] = set()
            candidates: list[tuple[str, str, str]] = []

            for text, trans in word_sentences:
                if text not in seen:
                    seen.add(text)
                    candidates.append((text, trans, word))

            # Select diverse examples
            selected = _select_diverse_examples(candidates, word, max_examples)

            results[word] = selected

        # Summary
        found = sum(1 for ex in results.values() if ex)
        console.print(f"[green]  Found examples for {found}/{len(words)} words[/green]")

        return results, backups

    except Exception as e:
        console.print(f"[red]Tatoeba error: {e}[/red]")
        return {word: [] for word in words}, {}


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
