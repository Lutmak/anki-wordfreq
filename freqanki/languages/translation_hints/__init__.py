"""
Language-specific translation hints system.

This module provides a way for contributors to add language-specific
guidance that helps LLM-based translation backends produce better
dictionary translations.

The hints are NOT hardcoded answers - they provide context about
linguistic features that the LLM should consider when translating.

To add hints for a new language:
1. Create a file named <lang_code>.py (e.g., ja.py for Japanese)
2. Define a HINTS string with language-specific guidance
3. The hints will be automatically loaded when that language is used

See russian.py for an example.
"""

from freqanki.languages.translation_hints.registry import (
    get_hints,
    register_hints,
    list_available_hints,
)

__all__ = ["get_hints", "register_hints", "list_available_hints"]
