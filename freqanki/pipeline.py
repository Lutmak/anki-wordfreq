"""Main pipeline orchestration for FreqAnki deck generation."""

from pathlib import Path

from freqanki.config import FreqAnkiConfig
from freqanki.core.audio import get_audio_for_words
from freqanki.core.deck import WordData, create_deck
from freqanki.core.examples import collect_all_example_sentences
from freqanki.core.kaikki import (
    ensure_dictionary,
    get_romanization_for_word,
    get_transliteration_for_word,
    load_entries_for_words,
)
from freqanki.core.migration import load_guid_map, report_guid_coverage
from freqanki.core.translations import (
    translate_glosses_to_targets,
    translate_words_literal,
)
from freqanki.core.words import get_frequency_words
from freqanki.languages import get_language_module
from freqanki.preview import create_preview_html, open_preview
from freqanki.utils.console import (
    console,
    create_progress,
    print_header,
    print_success,
)


def generate_deck(config: FreqAnkiConfig) -> str | None:
    """
    Generate an Anki deck using the configured settings.

    This is the main pipeline that orchestrates all steps:
    1. Word acquisition from wordfreq
    2. Kaikki dictionary loading
    3. Translation of glosses
    4. Example sentence collection
    5. Audio retrieval with TTS fallback
    6. Card assembly
    7. Preview and export

    Args:
        config: Configuration for generation

    Returns:
        Path to generated .apkg file, or None if cancelled
    """
    gen = config.generation
    api = config.api
    dl = config.download

    # Get language module
    print_header("FreqAnki Deck Generator")
    lang_module = get_language_module(gen.source_lang)
    console.print(f"Language: [cyan]{lang_module.name}[/cyan] ({lang_module.code})")
    console.print(f"Targets: [cyan]{', '.join(gen.target_langs)}[/cyan]")
    console.print(f"Words: [cyan]{gen.num_words}[/cyan]")

    # Load GUID map for migration (if specified)
    guid_map: dict[str, str] = {}
    if gen.migrate_from:
        console.print(f"Migration: [cyan]{gen.migrate_from.name}[/cyan]")
        guid_map = load_guid_map(gen.migrate_from)

    # Phase 1: Word Acquisition
    print_header("Phase 1: Word Acquisition")
    words = get_frequency_words(lang_module, gen.num_words)
    console.print(f"[green]Got {len(words)} frequency words[/green]")

    # Report migration coverage if applicable
    if guid_map:
        report_guid_coverage(guid_map, words)

    # Phase 2: Dictionary Loading
    print_header("Phase 2: Loading Dictionary")
    dict_path = ensure_dictionary(gen.source_lang, dl.dict_dir)
    kaikki_entries = load_entries_for_words(dict_path, words, gen.source_lang)

    # Phase 3: Translation
    print_header("Phase 3: Translating Glosses")
    all_translations = translate_glosses_to_targets(
        words,
        gen.source_lang,
        gen.target_langs,
        kaikki_entries,
        api.deepl_api_key,
        api.deepl_endpoint,
    )

    # Phase 4: Example Collection
    print_header("Phase 4: Collecting Examples")
    examples_by_word: dict[str, list[tuple[str, str, str]]] = {}
    word_translations: dict[str, list[tuple[str, str]]] = {}

    if gen.num_examples > 0 and gen.target_langs:
        examples_by_word, unique_sentences = collect_all_example_sentences(
            words,
            gen.source_lang,
            gen.target_langs[0],
            gen.num_examples,
        )

        # Word-by-word literal translations if enabled
        if gen.include_literal and unique_sentences and api.deepl_api_key:
            word_translations = translate_words_literal(
                unique_sentences,
                gen.source_lang,
                gen.target_langs[0],
                api.deepl_api_key,
                api.deepl_endpoint,
            )

    # Phase 5: Audio Retrieval
    print_header("Phase 5: Getting Audio")
    audio_paths = get_audio_for_words(
        words,
        gen.source_lang,
        kaikki_entries,
        dl.audio_dir,
        dl.max_workers,
        use_tts_fallback=True,
    )

    # Phase 6: Card Assembly
    print_header("Phase 6: Assembling Cards")
    words_data: list[WordData] = []

    with create_progress() as progress:
        task = progress.add_task("Building cards...", total=len(words))

        for rank, word in enumerate(words, 1):
            # Get romanization from Kaikki or language module
            romanization = get_romanization_for_word(word, kaikki_entries)
            if not romanization:
                romanization = lang_module.get_romanization(word)

            # Get transliteration from Kaikki (may include stress marks)
            transliteration = get_transliteration_for_word(word, kaikki_entries)

            # Get morphology
            morph = lang_module.get_morphology(word)
            morph_dict = morph.to_dict() if morph else None

            # Collect translations for this word
            translations = {
                lang: trans[rank - 1]
                for lang, trans in all_translations.items()
                if rank - 1 < len(trans) and trans[rank - 1]
            }

            # Get examples
            examples = examples_by_word.get(word, [])

            words_data.append(
                WordData(
                    word=word,
                    rank=rank,
                    display_word=lang_module.get_display_word(word),
                    romanization=romanization,
                    transliteration=transliteration,
                    morphology=morph_dict,
                    translations=translations,
                    examples=examples,
                    word_translations=word_translations if examples else None,
                    audio_path=audio_paths.get(word),
                )
            )

            progress.update(task, advance=1)

    print_success(f"Assembled {len(words_data)} cards")

    # Phase 7: Preview & Export
    print_header("Phase 7: Preview & Export")

    if gen.show_preview:
        preview_path = create_preview_html(words_data, gen.target_langs)
        open_preview(preview_path)
        console.print("\n[yellow]Preview opened in browser.[/yellow]")
        response = console.input("[cyan]Generate Anki deck? (y/n): [/cyan]").strip().lower()
        if response != "y":
            console.print("[yellow]Cancelled[/yellow]")
            return None

    # Generate deck
    deck_name = f"FreqAnki_{gen.source_lang}_Top_{gen.num_words}"
    if gen.output_path:
        deck_name = gen.output_path.stem

    output_path = create_deck(words_data, deck_name, gen.target_langs, guid_map)

    print_success(f"Done! Import {output_path} into Anki Desktop")

    return output_path
