"""Audio retrieval and TTS fallback."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from freqanki.core.kaikki import get_audio_url_for_word
from freqanki.utils.console import console, create_progress
from freqanki.utils.http import RateLimitedClient, url_to_filename


def get_audio_urls(
    words: list[str],
    kaikki_entries: dict[str, list[dict]],
) -> dict[str, str | None]:
    """
    Get audio URLs for words from Kaikki entries.

    Only looks up the exact wordfreq word, not lemmas.

    Args:
        words: List of words to get audio for
        kaikki_entries: Pre-loaded Kaikki entries

    Returns:
        Dict mapping word to audio URL (or None)
    """
    return {word: get_audio_url_for_word(word, kaikki_entries) for word in words}


def generate_tts_audio(
    word: str,
    lang_code: str,
    audio_dir: Path,
) -> Path | None:
    """
    Generate TTS audio for a word using gTTS.

    Args:
        word: Word to generate audio for
        lang_code: Language code for TTS
        audio_dir: Directory to save audio

    Returns:
        Path to generated audio file, or None on failure
    """
    try:
        from gtts import gTTS

        audio_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        safe_word = "".join(c if c.isalnum() else "_" for c in word)
        filename = f"{safe_word}_tts.mp3"
        filepath = audio_dir / filename

        if filepath.exists():
            return filepath

        tts = gTTS(text=word, lang=lang_code, slow=False)
        tts.save(str(filepath))
        return filepath

    except Exception as e:
        console.print(f"[yellow]TTS failed for '{word}': {e}[/yellow]")
        return None


def download_audio_file(
    url: str,
    word: str,
    audio_dir: Path,
    client: RateLimitedClient | None = None,
) -> Path | None:
    """
    Download a single audio file.

    Args:
        url: URL to download from
        word: Word (for filename)
        audio_dir: Directory to save to
        client: HTTP client to use

    Returns:
        Path to downloaded file, or None on failure
    """
    if client is None:
        client = RateLimitedClient()

    audio_dir.mkdir(parents=True, exist_ok=True)
    filename = url_to_filename(url, word)
    filepath = audio_dir / filename

    if filepath.exists():
        return filepath

    result = client.download_file(url, filepath)
    return result


def download_audio_parallel(
    audio_urls: dict[str, str],
    audio_dir: Path,
    max_workers: int = 5,
) -> dict[str, Path | None]:
    """
    Download multiple audio files in parallel.

    Args:
        audio_urls: Dict mapping word to URL
        audio_dir: Directory to save audio
        max_workers: Maximum concurrent downloads

    Returns:
        Dict mapping word to downloaded file path (or None)
    """
    if not audio_urls:
        return {}

    results: dict[str, Path | None] = {}
    client = RateLimitedClient()

    def download_one(word: str, url: str) -> tuple[str, Path | None]:
        return (word, download_audio_file(url, word, audio_dir, client))

    with create_progress() as progress:
        task = progress.add_task("Downloading audio...", total=len(audio_urls))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(download_one, word, url): word
                for word, url in audio_urls.items()
            }

            for future in as_completed(futures):
                word, path = future.result()
                results[word] = path
                progress.update(task, advance=1)

    return results


def get_audio_for_words(
    words: list[str],
    lang_code: str,
    kaikki_entries: dict[str, list[dict]],
    audio_dir: Path,
    max_workers: int = 5,
    use_tts_fallback: bool = True,
) -> dict[str, Path | None]:
    """
    Get audio files for words, with TTS fallback.

    Pipeline:
    1. Try to get audio URL from Kaikki for exact word
    2. Download available audio in parallel
    3. Generate TTS for words without audio

    Args:
        words: List of words
        lang_code: Language code
        kaikki_entries: Pre-loaded Kaikki entries
        audio_dir: Directory for audio files
        max_workers: Concurrent downloads
        use_tts_fallback: Whether to use TTS for missing audio

    Returns:
        Dict mapping word to audio file path (or None)
    """
    console.print("[blue]Getting audio files...[/blue]")

    # Step 1: Get audio URLs from Kaikki
    audio_urls = get_audio_urls(words, kaikki_entries)
    urls_to_download = {w: url for w, url in audio_urls.items() if url}

    console.print(f"  Found audio URLs for {len(urls_to_download)}/{len(words)} words")

    # Step 2: Download available audio
    results: dict[str, Path | None] = {w: None for w in words}

    if urls_to_download:
        downloaded = download_audio_parallel(urls_to_download, audio_dir, max_workers)
        results.update(downloaded)

    # Step 3: TTS fallback for missing audio
    if use_tts_fallback:
        missing = [w for w in words if results.get(w) is None]
        if missing:
            console.print(f"  Generating TTS for {len(missing)} words without audio...")

            with create_progress() as progress:
                task = progress.add_task("Generating TTS...", total=len(missing))

                for word in missing:
                    tts_path = generate_tts_audio(word, lang_code, audio_dir)
                    results[word] = tts_path
                    progress.update(task, advance=1)

    # Summary
    have_audio = sum(1 for p in results.values() if p is not None)
    console.print(f"[green]  Audio ready for {have_audio}/{len(words)} words[/green]")

    return results
