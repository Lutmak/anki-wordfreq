"""Migration utilities for preserving Anki scheduling data when updating decks.

When you import an Anki deck with notes that have the same GUID as existing notes,
Anki updates the content while preserving all scheduling data (intervals, ease factors,
review history). This module extracts GUIDs from old decks so new generations can
reuse them.
"""

import sqlite3
import tempfile
import zipfile
from pathlib import Path

from freqanki.utils.console import console


def _decompress_anki21b(data: bytes) -> bytes:
    """Decompress zstd-compressed Anki 2.1.50+ database."""
    import zstandard as zstd
    dctx = zstd.ZstdDecompressor()
    # Use streaming decompression for frames without content size
    reader = dctx.stream_reader(data)
    return reader.read()


def _extract_db_from_apkg(apkg_path: Path, temp_path: Path) -> Path:
    """
    Extract and prepare the SQLite database from an apkg file.

    Handles both old format (collection.anki2) and new zstd-compressed
    format (collection.anki21b) used in Anki 2.1.50+.
    """
    with zipfile.ZipFile(apkg_path, 'r') as zf:
        names = zf.namelist()

        # Try new compressed format first (Anki 2.1.50+)
        if 'collection.anki21b' in names:
            zf.extract('collection.anki21b', temp_path)
            compressed_path = temp_path / 'collection.anki21b'
            with open(compressed_path, 'rb') as f:
                decompressed = _decompress_anki21b(f.read())
            db_path = temp_path / 'collection.sqlite'
            with open(db_path, 'wb') as f:
                f.write(decompressed)
            return db_path

        # Fall back to old formats
        for db_name in ('collection.anki21', 'collection.anki2'):
            if db_name in names:
                zf.extract(db_name, temp_path)
                return temp_path / db_name

        raise ValueError(f"No Anki database found in {apkg_path}")


def extract_guids_from_apkg(apkg_path: Path) -> dict[str, str]:
    """
    Extract word -> GUID mapping from an Anki package.

    The mapping uses the first field of each note (typically the word)
    as the key, and the note's GUID as the value.

    Supports both old (.anki2) and new zstd-compressed (.anki21b) formats.

    Args:
        apkg_path: Path to the .apkg file

    Returns:
        Dictionary mapping first field content to GUID

    Raises:
        FileNotFoundError: If the apkg file doesn't exist
        ValueError: If the apkg is invalid or has no notes
    """
    if not apkg_path.exists():
        raise FileNotFoundError(f"Deck file not found: {apkg_path}")

    guid_map: dict[str, str] = {}

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        try:
            db_path = _extract_db_from_apkg(apkg_path, temp_path)
        except zipfile.BadZipFile:
            raise ValueError(f"Invalid apkg file (not a valid ZIP): {apkg_path}")

        # Read notes from the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        try:
            # Notes table: guid is the unique identifier, flds contains fields
            # Fields are separated by the unit separator character (0x1f)
            cursor.execute("SELECT guid, flds FROM notes")

            for guid, flds in cursor.fetchall():
                # First field is typically the word/identifier
                first_field = flds.split('\x1f')[0].strip()
                if first_field:
                    guid_map[first_field] = guid

        finally:
            conn.close()

    if not guid_map:
        raise ValueError(f"No notes found in {apkg_path}")

    return guid_map


def load_guid_map(apkg_path: Path | None) -> dict[str, str]:
    """
    Load GUID map from an apkg file, with user-friendly error handling.

    This is the main entry point for the migration feature.

    Args:
        apkg_path: Path to the old .apkg file, or None to skip migration

    Returns:
        Dictionary mapping word -> GUID, or empty dict if no migration
    """
    if apkg_path is None:
        return {}

    try:
        guid_map = extract_guids_from_apkg(apkg_path)
        console.print(
            f"[green]Loaded {len(guid_map)} GUIDs from:[/green] {apkg_path.name}"
        )
        return guid_map
    except FileNotFoundError as e:
        console.print(f"[red]Migration error:[/red] {e}")
        raise
    except ValueError as e:
        console.print(f"[red]Migration error:[/red] {e}")
        raise


def report_guid_coverage(guid_map: dict[str, str], words: list[str]) -> None:
    """
    Report how many words from the new generation have existing GUIDs.

    Args:
        guid_map: Dictionary of word -> GUID from old deck
        words: List of words in the new generation
    """
    if not guid_map:
        return

    matched = sum(1 for w in words if w in guid_map)
    new_words = [w for w in words if w not in guid_map]

    console.print(f"[blue]GUID coverage:[/blue]")
    console.print(f"  Matching existing: [green]{matched}[/green]")
    console.print(f"  New words: [yellow]{len(new_words)}[/yellow]")

    if new_words and len(new_words) <= 10:
        console.print(f"  New words list: {', '.join(new_words)}")
    elif new_words:
        console.print(f"  First 10 new: {', '.join(new_words[:10])}...")
