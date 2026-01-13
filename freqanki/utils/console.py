"""Console output utilities using Rich."""

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

# Global console instance
console = Console()


def create_progress() -> Progress:
    """Create a progress bar for tracking operations."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )


def print_header(text: str) -> None:
    """Print a section header."""
    console.print()
    console.rule(f"[bold cyan]{text}")
    console.print()


def print_success(text: str) -> None:
    """Print a success message."""
    console.print(f"[bold green]{text}")


def print_error(text: str) -> None:
    """Print an error message."""
    console.print(f"[bold red]{text}")


def print_warning(text: str) -> None:
    """Print a warning message."""
    console.print(f"[yellow]{text}")


def print_info(text: str) -> None:
    """Print an info message."""
    console.print(f"[blue]{text}")


def print_languages_table(languages: list[tuple[str, str, bool]]) -> None:
    """
    Print a table of supported languages.

    Args:
        languages: List of (code, name, has_full_support) tuples
    """
    table = Table(title="Supported Languages")
    table.add_column("Code", style="cyan")
    table.add_column("Language", style="green")
    table.add_column("Status", style="yellow")

    for code, name, full_support in sorted(languages, key=lambda x: x[1]):
        status = "Full" if full_support else "Basic"
        table.add_row(code, name, status)

    console.print(table)


def print_generation_summary(
    source: str,
    targets: list[str],
    num_words: int,
    num_examples: int,
    output: str,
) -> None:
    """Print a summary of generation settings."""
    table = Table(title="Generation Settings", show_header=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Source Language", source)
    table.add_row("Target Languages", ", ".join(targets))
    table.add_row("Number of Words", str(num_words))
    table.add_row("Examples per Word", str(num_examples))
    table.add_row("Output File", output)

    console.print(table)
