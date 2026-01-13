"""Word acquisition from wordfreq library."""

from wordfreq import top_n_list

from freqanki.languages import LanguageModule
from freqanki.utils.console import console, print_info


def get_frequency_words(
    lang_module: LanguageModule,
    desired_count: int,
    oversample_factor: int = 4,
) -> list[str]:
    """
    Get the most frequent words for a language.

    Uses wordfreq to get frequency-ranked words, then filters
    using the language module's validation.

    Args:
        lang_module: Language module for validation
        desired_count: Number of words to return
        oversample_factor: Initial oversampling multiplier

    Returns:
        List of validated words in frequency order
    """
    if desired_count <= 0:
        return []

    # Start with an oversampled request
    oversample = max(desired_count * oversample_factor, desired_count + 200)
    max_oversample = max(desired_count * 10, oversample)

    while True:
        raw_words = top_n_list(lang_module.wordfreq_code, oversample)
        filtered: list[str] = []
        skipped_count = 0
        skipped_samples: list[str] = []
        seen: set[str] = set()

        for token in raw_words:
            normalized = token.strip()
            if not normalized or normalized in seen:
                continue

            if not lang_module.is_valid_token(normalized):
                skipped_count += 1
                if len(skipped_samples) < 5 and normalized not in skipped_samples:
                    skipped_samples.append(normalized)
                continue

            filtered.append(normalized)
            seen.add(normalized)
            if len(filtered) >= desired_count:
                break

        if len(filtered) >= desired_count or oversample >= max_oversample:
            if skipped_count:
                sample_msg = ", ".join(skipped_samples)
                print_info(
                    f"Filtered out {skipped_count} non-{lang_module.name} tokens"
                    + (f" (e.g., {sample_msg})" if sample_msg else "")
                )
            if len(filtered) < desired_count:
                console.print(
                    f"[yellow]Only {len(filtered)} usable words found "
                    f"out of requested {desired_count}[/yellow]"
                )
            return filtered[:desired_count]

        # Need more words, increase oversample
        oversample = min(oversample * 2, max_oversample)


def get_words_with_metadata(
    lang_module: LanguageModule,
    count: int,
) -> list[dict]:
    """
    Get frequency words with basic metadata.

    Args:
        lang_module: Language module
        count: Number of words

    Returns:
        List of dicts with 'word', 'rank', and 'display_word' keys
    """
    words = get_frequency_words(lang_module, count)

    return [
        {
            "word": word,  # The wordfreq word - this is THE source of truth
            "rank": rank,
            "display_word": lang_module.get_display_word(word),
        }
        for rank, word in enumerate(words, 1)
    ]
