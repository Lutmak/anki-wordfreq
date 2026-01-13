"""Click CLI for FreqAnki."""

from pathlib import Path

import click
from dotenv import load_dotenv

from freqanki import __version__
from freqanki.config import FreqAnkiConfig
from freqanki.languages import list_supported_languages
from freqanki.pipeline import generate_deck
from freqanki.utils.console import console, print_header, print_languages_table


@click.group()
@click.version_option(__version__, prog_name="freqanki")
def main() -> None:
    """FreqAnki - Frequency-based Anki flashcard generator for 40+ languages."""
    load_dotenv()


@main.command()
@click.option(
    "--lang", "-l",
    required=True,
    help="Source language code (e.g., ru, zh, ja)",
)
@click.option(
    "--targets", "-t",
    default="en",
    help="Target language codes, comma-separated (default: en)",
)
@click.option(
    "--words", "-w",
    default=2000,
    type=int,
    help="Number of words to include (default: 2000)",
)
@click.option(
    "--examples", "-e",
    default=2,
    type=int,
    help="Example sentences per word (default: 2)",
)
@click.option(
    "--literal",
    is_flag=True,
    help="Include literal word-by-word translations",
)
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    help="Output .apkg file path",
)
@click.option(
    "--no-preview",
    is_flag=True,
    help="Skip HTML preview",
)
def generate(
    lang: str,
    targets: str,
    words: int,
    examples: int,
    literal: bool,
    output: Path | None,
    no_preview: bool,
) -> None:
    """Generate an Anki flashcard deck."""
    target_list = [t.strip() for t in targets.split(",") if t.strip()]

    config = FreqAnkiConfig.from_cli_args(
        lang=lang,
        targets=target_list,
        words=words,
        examples=examples,
        literal=literal,
        output=output,
        preview=not no_preview,
    )

    try:
        result = generate_deck(config)
        if result:
            console.print(f"\n[bold green]Success![/bold green] Created: {result}")
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@main.command()
def languages() -> None:
    """List all supported languages."""
    print_header("Supported Languages")
    langs = list_supported_languages()
    print_languages_table(langs)
    console.print(f"\n[green]Total: {len(langs)} languages[/green]")


@main.command("download-dict")
@click.argument("lang_code")
def download_dict(lang_code: str) -> None:
    """Download dictionary for a language."""
    from freqanki.config import DownloadConfig
    from freqanki.core.kaikki import download_dictionary

    dl_config = DownloadConfig()

    try:
        path = download_dictionary(lang_code, dl_config.dict_dir)
        console.print(f"[green]Downloaded: {path}[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort()


@main.command()
@click.argument("lang_code")
def validate(lang_code: str) -> None:
    """Validate a language module."""
    from freqanki.languages import get_language_module

    print_header(f"Validating: {lang_code}")

    try:
        module = get_language_module(lang_code)
        console.print(f"[green]Module loaded: {module}[/green]")
        console.print(f"  Code: {module.code}")
        console.print(f"  Name: {module.name}")
        console.print(f"  Tatoeba: {module.tatoeba_code}")
        console.print(f"  DeepL: {module.deepl_code}")
        console.print(f"  Full support: {module.has_full_support}")

        # Test token validation
        test_words = ["test", "123", "hello"]
        console.print("\n[blue]Token validation:[/blue]")
        for word in test_words:
            valid = module.is_valid_token(word)
            status = "[green]valid[/green]" if valid else "[red]invalid[/red]"
            console.print(f"  '{word}': {status}")

        console.print("\n[green]Validation passed![/green]")

    except Exception as e:
        console.print(f"[red]Validation failed: {e}[/red]")
        raise click.Abort()


if __name__ == "__main__":
    main()
