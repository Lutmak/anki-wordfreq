"""Factory functions for translation backends."""

from freqanki.core.backends.base import BackendType, TranslationBackend
from freqanki.core.backends.deepl import DeepLBackend
from freqanki.core.backends.qwen import QwenBackend
from freqanki.core.backends.argos import ArgosBackend
from freqanki.utils.console import console


# Default priority order: quality vs speed vs requirements tradeoff
DEFAULT_PRIORITY = [BackendType.DEEPL, BackendType.ARGOS, BackendType.QWEN]

# Singleton cache for backend instances
_backend_cache: dict[BackendType, TranslationBackend] = {}


def get_backend(
    backend_type: BackendType = BackendType.AUTO,
    priority: list[BackendType] | None = None,
) -> TranslationBackend | None:
    """
    Get a translation backend instance (cached singleton).

    Args:
        backend_type: Specific backend to use, or AUTO to pick automatically.
        priority: Order of preference for AUTO mode. Defaults to DeepL > Argos > Qwen.

    Returns:
        A TranslationBackend instance, or None if no backend available.

    Backend tradeoffs:
        - DeepL: Best quality, requires API key (free tier: 500k chars/month)
        - Argos: Fast & offline, good quality, may need language pack install
        - Qwen: Free & local, best for function words, requires Ollama running
    """
    if backend_type == BackendType.AUTO:
        return _auto_select_backend(priority or DEFAULT_PRIORITY)

    backend = _get_or_create_backend(backend_type)

    if backend and not backend.is_available():
        console.print(f"[yellow]Backend {backend.name} is not available[/yellow]")
        return None

    return backend


def _get_or_create_backend(backend_type: BackendType) -> TranslationBackend | None:
    """Get cached backend or create new one."""
    if backend_type in _backend_cache:
        return _backend_cache[backend_type]

    backend = _create_backend(backend_type)
    if backend:
        _backend_cache[backend_type] = backend
    return backend


def _create_backend(backend_type: BackendType) -> TranslationBackend | None:
    """Create a backend instance by type."""
    backends = {
        BackendType.DEEPL: DeepLBackend,
        BackendType.QWEN: QwenBackend,
        BackendType.ARGOS: ArgosBackend,
    }

    cls = backends.get(backend_type)
    return cls() if cls else None


def _auto_select_backend(priority: list[BackendType]) -> TranslationBackend | None:
    """Automatically select the best available backend."""
    for backend_type in priority:
        backend = _get_or_create_backend(backend_type)
        if backend and backend.is_available():
            console.print(f"[cyan]Auto-selected backend: {backend.name}[/cyan]")
            return backend

    console.print("[red]No translation backend available![/red]")
    console.print("[yellow]Options to fix:[/yellow]")
    console.print("  • Set DEEPL_API_KEY environment variable")
    console.print("  • Install & start Ollama with qwen3:4b-instruct model")
    console.print("  • pip install argostranslate")

    return None


def get_available_backends() -> list[TranslationBackend]:
    """
    Get all available (ready to use) backends.

    Returns:
        List of backend instances that are currently available.
    """
    available = []

    for backend_type in BackendType:
        if backend_type == BackendType.AUTO:
            continue

        backend = _get_or_create_backend(backend_type)
        if backend and backend.is_available():
            available.append(backend)

    return available


def list_backends() -> list[dict]:
    """
    List all backends with their availability status.

    Returns:
        List of dicts with 'name', 'type', 'available', 'description' keys.
    """
    result = []

    for backend_type in BackendType:
        if backend_type == BackendType.AUTO:
            continue

        backend = _get_or_create_backend(backend_type)
        if backend:
            result.append(
                {
                    "name": backend.name,
                    "type": backend_type.value,
                    "available": backend.is_available(),
                    "description": backend.get_description(),
                }
            )

    return result


def print_backend_status():
    """Print a summary of backend availability."""
    console.print("\n[bold]Translation Backend Status:[/bold]\n")

    for info in list_backends():
        status = "✓" if info["available"] else "✗"
        color = "green" if info["available"] else "red"
        console.print(f"  [{color}]{status}[/{color}] {info['name']}")
        console.print(f"      {info['description']}")

    console.print()
