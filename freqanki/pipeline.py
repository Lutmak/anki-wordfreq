"""Main pipeline orchestration for FreqAnki deck generation."""

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
    translate_sentences_batch,
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
    literal_translations: dict[str, str] = {}
    word_translations: dict[str, list[tuple[str, str]]] = {}
    backup_sentences: dict[str, list[tuple[str, str, str]]] = {}

    if gen.num_examples > 0 and gen.target_langs:
        examples_by_word, unique_sentences, backup_sentences = collect_all_example_sentences(
            words,
            gen.source_lang,
            gen.target_langs[0],
            gen.num_examples,
        )

        # Word-by-word translations if enabled and API key available
        if gen.include_literal and unique_sentences and api.deepl_api_key:
            console.print("[blue]Getting word-by-word translations...[/blue]")
            word_translations, failed_sentences = translate_words_literal(
                unique_sentences,
                gen.source_lang,
                gen.target_langs[0],
                api.deepl_api_key,
                api.deepl_endpoint,
            )

            # Retry failed sentences with backup candidates
            if failed_sentences:
                console.print(
                    f"[yellow]{len(failed_sentences)} sentences had untranslated words, trying backups...[/yellow]"
                )

                # Find which words need replacement sentences
                retry_sentences: list[str] = []
                for word, word_examples in examples_by_word.items():
                    for i, (source, target, matched) in enumerate(word_examples):
                        if source in failed_sentences:
                            # Try to swap with a backup
                            if backup_sentences.get(word):
                                backup = backup_sentences[word].pop(0)
                                examples_by_word[word][i] = backup
                                if backup[0] not in word_translations:
                                    retry_sentences.append(backup[0])

                # Translate retry sentences
                if retry_sentences:
                    console.print(
                        f"[blue]Translating {len(retry_sentences)} replacement sentences...[/blue]"
                    )
                    retry_translations, retry_failed = translate_words_literal(
                        retry_sentences,
                        gen.source_lang,
                        gen.target_langs[0],
                        api.deepl_api_key,
                        api.deepl_endpoint,
                    )
                    word_translations.update(retry_translations)
                    if retry_failed:
                        console.print(
                            f"[yellow]  {len(retry_failed)} replacement sentences also failed[/yellow]"
                        )

            # Fallback: sentence-level translations for sentences not covered
            # (e.g., those with fewer than min_words)
            all_current_sentences = set()
            for word_examples in examples_by_word.values():
                for source, _, _ in word_examples:
                    all_current_sentences.add(source)

            sentences_needing_fallback = [
                s for s in all_current_sentences if s not in word_translations
            ]
            if sentences_needing_fallback:
                console.print(
                    f"[blue]Getting fallback translations for {len(sentences_needing_fallback)} shorter sentences...[/blue]"
                )
                literal_translations = translate_sentences_batch(
                    sentences_needing_fallback,
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

            # Get IPA/transliteration from Kaikki
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

            # Get word translations for this word's examples
            word_trans_for_word: dict[str, list[tuple[str, str]]] | None = None
            if word_translations and examples:
                word_trans_for_word = {
                    src: word_translations[src]
                    for src, _, _ in examples
                    if src in word_translations
                }
                if not word_trans_for_word:
                    word_trans_for_word = None

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
                    literal_translations=literal_translations if examples else None,
                    word_translations=word_trans_for_word,
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
