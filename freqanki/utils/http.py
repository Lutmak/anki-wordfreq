"""Rate-limited HTTP client with retry logic."""

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import requests

from freqanki.utils.console import console


class RateLimitedClient:
    """HTTP client with rate limiting and exponential backoff retry."""

    USER_AGENT = (
        "FreqAnki/2.0 (https://github.com/lutmak/anki-wordfreq; "
        "language learning flashcard generator)"
    )

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        timeout: int = 30,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})

    def get(self, url: str, **kwargs) -> requests.Response | None:
        """GET request with retry logic."""
        kwargs.setdefault("timeout", self.timeout)

        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, **kwargs)

                if response.status_code == 429:
                    # Rate limited - exponential backoff
                    wait_time = self.base_delay * (2**attempt)
                    console.log(f"[yellow]Rate limited, waiting {wait_time}s...[/yellow]")
                    time.sleep(wait_time)
                    continue

                if response.status_code == 200:
                    return response

                # Other error - log and retry
                console.log(
                    f"[yellow]HTTP {response.status_code} for {url}, "
                    f"retry {attempt + 1}/{self.max_retries}[/yellow]"
                )

            except requests.RequestException as e:
                console.log(f"[red]Request error: {e}[/red]")
                if attempt < self.max_retries - 1:
                    time.sleep(self.base_delay)

        return None

    def post(self, url: str, **kwargs) -> requests.Response | None:
        """POST request with retry logic."""
        kwargs.setdefault("timeout", self.timeout)

        for attempt in range(self.max_retries):
            try:
                response = self.session.post(url, **kwargs)

                if response.status_code == 429:
                    wait_time = self.base_delay * (2**attempt)
                    console.log(f"[yellow]Rate limited, waiting {wait_time}s...[/yellow]")
                    time.sleep(wait_time)
                    continue

                if response.ok:
                    return response

                console.log(
                    f"[yellow]HTTP {response.status_code} for POST {url}, "
                    f"retry {attempt + 1}/{self.max_retries}[/yellow]"
                )

            except requests.RequestException as e:
                console.log(f"[red]Request error: {e}[/red]")
                if attempt < self.max_retries - 1:
                    time.sleep(self.base_delay)

        return None

    def download_file(self, url: str, dest_path: Path) -> Path | None:
        """Download a file to the specified path."""
        response = self.get(url, stream=True)
        if response is None:
            return None

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return dest_path
        except IOError as e:
            console.log(f"[red]Error writing file {dest_path}: {e}[/red]")
            return None


def url_to_filename(url: str, word: str) -> str:
    """Generate a unique filename from URL and word."""
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    ext = url.split(".")[-1].split("?")[0]
    if ext not in ("mp3", "ogg", "wav"):
        ext = "mp3"
    # Sanitize word for filename
    safe_word = "".join(c if c.isalnum() else "_" for c in word)
    return f"{safe_word}_{url_hash}.{ext}"


def download_files_parallel(
    items: list[tuple[str, str, Path]],  # (url, word, dest_dir)
    max_workers: int = 5,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Path | None]:
    """
    Download multiple files in parallel.

    Args:
        items: List of (url, word, dest_dir) tuples
        max_workers: Maximum concurrent downloads
        progress_callback: Called with (completed, total) after each download

    Returns:
        Dict mapping word to downloaded file path (or None if failed)
    """
    results: dict[str, Path | None] = {}
    client = RateLimitedClient()
    total = len(items)

    def download_one(url: str, word: str, dest_dir: Path) -> tuple[str, Path | None]:
        filename = url_to_filename(url, word)
        dest_path = dest_dir / filename

        # Skip if already exists
        if dest_path.exists():
            return (word, dest_path)

        result = client.download_file(url, dest_path)
        return (word, result)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(download_one, url, word, dest_dir): word
            for url, word, dest_dir in items
        }

        completed = 0
        for future in as_completed(futures):
            word, path = future.result()
            results[word] = path
            completed += 1
            if progress_callback:
                progress_callback(completed, total)

    return results
