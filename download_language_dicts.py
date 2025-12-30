#!/usr/bin/env python3
"""Download per-language Wiktextract dictionaries from kaikki.org.

This helper grabs the English-edition, per-language JSONL exports for
the requested languages and stores the results under
`language-dicts/<lang>.jsonl` so the lookup script can read a much
smaller, English-glossed file per language.
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sys
from pathlib import Path
from typing import Dict, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

LANGUAGE_SOURCES: Dict[str, Dict[str, str]] = {
    "ar": {
        "name": "Arabic",
        "url": "https://kaikki.org/dictionary/Arabic/kaikki.org-dictionary-Arabic.jsonl",
    },
    "cs": {
        "name": "Czech",
        "url": "https://kaikki.org/dictionary/Czech/kaikki.org-dictionary-Czech.jsonl",
    },
    "de": {
        "name": "German",
        "url": "https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl",
    },
    "el": {
        "name": "Greek",
        "url": "https://kaikki.org/dictionary/Greek/kaikki.org-dictionary-Greek.jsonl",
    },
    "en": {
        "name": "English",
        "url": "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl",
    },
    "es": {
        "name": "Spanish",
        "url": "https://kaikki.org/dictionary/Spanish/kaikki.org-dictionary-Spanish.jsonl",
    },
    "fr": {
        "name": "French",
        "url": "https://kaikki.org/dictionary/French/kaikki.org-dictionary-French.jsonl",
    },
    "he": {
        "name": "Hebrew",
        "url": "https://kaikki.org/dictionary/Hebrew/kaikki.org-dictionary-Hebrew.jsonl",
    },
    "hi": {
        "name": "Hindi",
        "url": "https://kaikki.org/dictionary/Hindi/kaikki.org-dictionary-Hindi.jsonl",
    },
    "id": {
        "name": "Indonesian",
        "url": "https://kaikki.org/dictionary/Indonesian/kaikki.org-dictionary-Indonesian.jsonl",
    },
    "it": {
        "name": "Italian",
        "url": "https://kaikki.org/dictionary/Italian/kaikki.org-dictionary-Italian.jsonl",
    },
    "ja": {
        "name": "Japanese",
        "url": "https://kaikki.org/dictionary/Japanese/kaikki.org-dictionary-Japanese.jsonl",
    },
    "ko": {
        "name": "Korean",
        "url": "https://kaikki.org/dictionary/Korean/kaikki.org-dictionary-Korean.jsonl",
    },
    "nl": {
        "name": "Dutch",
        "url": "https://kaikki.org/dictionary/Dutch/kaikki.org-dictionary-Dutch.jsonl",
    },
    "pl": {
        "name": "Polish",
        "url": "https://kaikki.org/dictionary/Polish/kaikki.org-dictionary-Polish.jsonl",
    },
    "pt": {
        "name": "Portuguese",
        "url": "https://kaikki.org/dictionary/Portuguese/kaikki.org-dictionary-Portuguese.jsonl",
    },
    "ru": {
        "name": "Russian",
        "url": "https://kaikki.org/dictionary/Russian/kaikki.org-dictionary-Russian.jsonl",
    },
    "sv": {
        "name": "Swedish",
        "url": "https://kaikki.org/dictionary/Swedish/kaikki.org-dictionary-Swedish.jsonl",
    },
    "th": {
        "name": "Thai",
        "url": "https://kaikki.org/dictionary/Thai/kaikki.org-dictionary-Thai.jsonl",
    },
    "tr": {
        "name": "Turkish",
        "url": "https://kaikki.org/dictionary/Turkish/kaikki.org-dictionary-Turkish.jsonl",
    },
    "uk": {
        "name": "Ukrainian",
        "url": "https://kaikki.org/dictionary/Ukrainian/kaikki.org-dictionary-Ukrainian.jsonl",
    },
    "vi": {
        "name": "Vietnamese",
        "url": "https://kaikki.org/dictionary/Vietnamese/kaikki.org-dictionary-Vietnamese.jsonl",
    },
    "zh": {
        "name": "Chinese",
        "url": "https://kaikki.org/dictionary/Chinese/kaikki.org-dictionary-Chinese.jsonl",
    },
}

DEFAULT_DEST = Path("language-dicts")
CHUNK_SIZE = 1024 * 1024


def _print_available_languages() -> None:
    print("Available language codes:\n")
    for code in sorted(LANGUAGE_SOURCES):
        print(f"  - {code}: {LANGUAGE_SOURCES[code]['name']}")


def _download_file(url: str, dest_path: Path) -> None:
    print(f"Downloading {url} -> {dest_path}")
    try:
        with urlopen(url) as resp, dest_path.open("wb") as target:
            while True:
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                target.write(chunk)
    except HTTPError as exc:
        raise RuntimeError(
            f"Failed to download {url}: {exc.code} {exc.reason}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Failed to download {url}: {exc.reason}") from exc


def _decompress_gz(gz_path: Path, dest_path: Path) -> None:
    print(f"Decompressing {gz_path} -> {dest_path}")
    with gzip.open(gz_path, "rb") as src, dest_path.open("wb") as dst:
        shutil.copyfileobj(src, dst)


def download_language(lang_code: str, dest_dir: Path, force: bool = False) -> Path:
    if lang_code not in LANGUAGE_SOURCES:
        raise ValueError(
            f"Language '{lang_code}' is not supported. Run with --list to see options."
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{lang_code}.jsonl"
    if dest_path.exists() and not force:
        print(
            f"Skipping {lang_code}: {dest_path} already exists (use --force to re-download)."
        )
        return dest_path

    url = LANGUAGE_SOURCES[lang_code]["url"]
    if url.endswith(".gz"):
        gz_tmp = dest_path.with_suffix(".jsonl.gz.tmp")
        _download_file(url, gz_tmp)
        _decompress_gz(gz_tmp, dest_path)
        gz_tmp.unlink(missing_ok=True)
    else:
        _download_file(url, dest_path)

    print(
        f"Saved {lang_code} dictionary ({LANGUAGE_SOURCES[lang_code]['name']}) to {dest_path}"
    )
    return dest_path


def download_languages(
    languages: Iterable[str], dest_dir: Path, force: bool = False
) -> None:
    for lang in languages:
        try:
            download_language(lang, dest_dir, force=force)
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to download {lang}: {exc}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download per-language Wiktextract JSONL dictionaries into language-dicts/"
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        help="Language codes to download. Defaults to all known codes.",
    )
    parser.add_argument(
        "--dest",
        default=str(DEFAULT_DEST),
        help="Destination directory (default: language-dicts)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if the target file already exists.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the supported language codes and exit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.list:
        _print_available_languages()
        return

    languages = args.languages or sorted(LANGUAGE_SOURCES)
    dest_dir = Path(args.dest)

    download_languages(languages, dest_dir, force=args.force)


if __name__ == "__main__":
    main()
