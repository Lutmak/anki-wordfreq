#!/usr/bin/env python3
"""
Test the new modular backend system for FreqAnki.

This script tests all available backends with a small sample of words
to verify the implementation works correctly.

Run: python test_backends.py [--lang LANG] [--count N]
"""

import argparse
from rich.console import Console
from rich.table import Table

from freqanki.core.backends import (
    BackendType,
    get_backend,
    list_backends,
    print_backend_status,
)
from freqanki.languages.translation_hints import get_hints, list_available_hints
from freqanki.languages import get_language_module
from freqanki.core.words import get_frequency_words

console = Console()


# Sample expected translations for validation (Russian → English)
# These are the "tricky" words that often get mistranslated
VALIDATION_SET_RU = {
    "и": "and",
    "в": "in",
    "не": "not",
    "он": "he",
    "на": "on",
    "я": "I",
    "что": "what",  # or "that"
    "с": "with",
    "а": "and",  # or "but"
    "это": "this",
    "как": "how",
    "она": "she",
    "по": "by",  # or "on/along"
    "но": "but",
    "они": "they",
    "к": "to",
    "у": "at",  # or "by/near"
    "же": "indeed",  # emphatic particle
    "от": "from",
    "за": "behind",  # or "for"
    "все": "all",
    "так": "so",
    "его": "his",  # or "him"
    "ли": "whether",  # NOT "or"
    "только": "only",
    "есть": "is",  # NOT "to eat"
    "ни": "neither",  # emphatic negative
    "о": "about",
}


def test_backend(
    backend_type: BackendType,
    words: list[str],
    source_lang: str,
    target_lang: str = "en",
) -> dict[str, str]:
    """Test a specific backend with given words."""
    backend = get_backend(backend_type)
    if backend is None:
        console.print(f"[red]Backend {backend_type.value} not available[/red]")
        return {}

    console.print(f"\n[cyan]Testing {backend.name}...[/cyan]")

    # Get language hints
    hints = get_hints(source_lang)
    if hints:
        console.print(f"  Using language hints for {source_lang}")

    # Translate
    translations = backend.translate_words(
        words=words,
        source_lang=source_lang,
        target_lang=target_lang,
        hints=hints,
    )

    return dict(zip(words, translations))


def evaluate_translations(
    results: dict[str, str],
    expected: dict[str, str],
) -> tuple[int, int, list[tuple[str, str, str]]]:
    """
    Evaluate translations against expected values.

    Returns: (correct_count, total_count, list of (word, got, expected) mismatches)
    """
    correct = 0
    total = 0
    mismatches = []

    for word, translation in results.items():
        if word not in expected:
            continue

        total += 1
        exp = expected[word]
        got = translation.lower().strip()

        # Check for exact match or acceptable alternatives
        if got == exp or exp in got or got in exp:
            correct += 1
        else:
            mismatches.append((word, got, exp))

    return correct, total, mismatches


def main():
    parser = argparse.ArgumentParser(description="Test FreqAnki translation backends")
    parser.add_argument("--lang", default="ru", help="Source language code")
    parser.add_argument("--count", type=int, default=30, help="Number of words to test")
    parser.add_argument(
        "--backend",
        choices=["auto", "deepl", "qwen", "argos", "all"],
        default="all",
        help="Backend to test",
    )
    args = parser.parse_args()

    console.print("\n[bold]FreqAnki Backend Test[/bold]\n")

    # Show backend status
    print_backend_status()

    # Show available hints
    hints_available = list_available_hints()
    console.print(f"Language hints available: {', '.join(hints_available) or 'none'}")

    # Get test words
    console.print(f"\n[blue]Getting {args.count} frequency words for {args.lang}...[/blue]")
    lang_module = get_language_module(args.lang)
    words = get_frequency_words(lang_module, args.count)
    console.print(f"Got {len(words)} words: {', '.join(words[:10])}...")

    # Select validation set
    validation = VALIDATION_SET_RU if args.lang == "ru" else {}

    # Determine which backends to test
    if args.backend == "all":
        backends_to_test = [bt for bt in BackendType if bt != BackendType.AUTO]
    else:
        backends_to_test = [BackendType(args.backend)]

    # Test each backend
    results_table = Table(title="Backend Comparison")
    results_table.add_column("Backend")
    results_table.add_column("Available")
    results_table.add_column("Accuracy")
    results_table.add_column("Sample")

    for backend_type in backends_to_test:
        backend = get_backend(backend_type)
        available = "✓" if backend else "✗"

        if backend and backend.is_available():
            translations = test_backend(backend_type, words, args.lang)

            if validation:
                correct, total, mismatches = evaluate_translations(translations, validation)
                accuracy = (
                    f"{correct}/{total} ({100 * correct / total:.0f}%)" if total > 0 else "N/A"
                )

                if mismatches:
                    console.print(f"\n[yellow]Mismatches for {backend.name}:[/yellow]")
                    for word, got, exp in mismatches[:5]:
                        console.print(f"  {word}: got '{got}', expected '{exp}'")
            else:
                accuracy = "No validation set"

            # Show sample translations
            sample = ", ".join(f"{w}→{translations.get(w, '?')}" for w in words[:5])
        else:
            accuracy = "-"
            sample = "-"

        results_table.add_row(backend_type.value, available, accuracy, sample[:50])

    console.print("\n")
    console.print(results_table)

    # Test CLI command
    console.print("\n[blue]CLI test:[/blue]")
    console.print("  freqanki backends  # Show backend status")
    console.print("  freqanki generate --lang ru --backend qwen  # Use specific backend")


if __name__ == "__main__":
    main()
