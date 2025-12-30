#!/usr/bin/env python3
"""
Simple Wiktionary preposition extractor (Russian example)
- Prints API/siteinfo to show what methods the MediaWiki API supports
- Fetches page wikitext and extracts the Russian Preposition section
- Returns the top-level uses (with prepositional/accusative/nominative)
  and for each use returns one example (if present). Designed to be
  generalizable to other languages and other pages.

Usage: run the script; it will parse the letter 'в' by default.
"""

import requests
import re
import json
import unicodedata
from typing import Dict, List, Optional


class WiktionaryParser:
    def __init__(self, language: str = "en", verbose: bool = False):
        self.language = language
        self.base_url = f"https://{language}.wiktionary.org/w/api.php"
        self.verbose = verbose
        # Use a persistent session and set a polite User-Agent per Wikimedia requirements
        # Replace the contact email with your own if you share frequent requests.
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "anki-wordfreq/1.0 (https://github.com/yourusername; contact: you@example.com)",
                "From": "you@example.com",
            }
        )

    def get_api_info(self) -> Optional[Dict]:
        """Fetch siteinfo/meta from the MediaWiki API and print it for debugging."""
        params = {
            "action": "query",
            "meta": "siteinfo",
            "siprop": "general|namespaces|fileextensions",
            "format": "json",
        }
        if self.verbose:
            print("\n--- API INFO REQUEST ---")
            print(f"URL: {self.base_url}")
            print(f"Params: {params}\n")

        try:
            # use session with User-Agent to avoid 403 from Wikimedia
            params["formatversion"] = 2
            r = self.session.get(self.base_url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            if self.verbose:
                print("--- API INFO RESPONSE (truncated) ---")
                # Print a small, useful subset for logs
                gen = data.get("query", {}).get("general", {})
                ns = list(data.get("query", {}).get("namespaces", {}).keys())[:10]
                print(
                    json.dumps(
                        {"general": gen, "namespaces_sample": ns},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return data
        except requests.HTTPError as e:
            # print server response body for debugging (may be large)
            try:
                print(
                    f"HTTP error fetching API info: {e} - status: {getattr(e.response, 'status_code', None)}"
                )
                print("Response body (truncated):", e.response.text[:800])
            except Exception:
                pass
            return None
        except Exception as e:
            print(f"Failed to fetch API info: {e}")
            return None

    def get_page_content(self, word: str) -> Optional[str]:
        """Fetch the wikitext content of a page from Wiktionary. Prints logs for debugging."""
        params = {
            "action": "query",
            "prop": "revisions",
            "titles": word,
            "rvprop": "content",
            "rvslots": "main",
            "format": "json",
        }

        if self.verbose:
            print("\n--- PAGE CONTENT REQUEST ---")
            print(f"URL: {self.base_url}")
            print(f"Params: {params}\n")

        try:
            params["formatversion"] = 2
            response = self.session.get(self.base_url, params=params, timeout=20)
            response.raise_for_status()
            data = response.json()

            if self.verbose:
                print("--- PAGE CONTENT RESPONSE KEYS ---")
                print(list(data.keys()))

            pages = data.get("query", {}).get("pages", {})

            # Print a truncated sample of pages for debugging to see its shape
            if self.verbose:
                try:
                    sample = json.dumps(
                        pages if isinstance(pages, (list, dict)) else str(pages),
                        ensure_ascii=False,
                    )
                    print("--- PAGES SAMPLE (truncated) ---")
                    print(sample[:800])
                except Exception:
                    pass

            if not pages:
                print("No pages in response")
                return None

            # Support both formatversion=1 (dict of pageid -> page) and formatversion=2 (list of page objects)
            if isinstance(pages, dict):
                # older format: pages is a dict keyed by pageid
                page_id = next(iter(pages))
                if page_id == "-1":
                    print(f"Page '{word}' not found (pageid -1)")
                    return None
                page_data = pages[page_id]
            elif isinstance(pages, list):
                # formatversion=2: pages is a list
                if len(pages) == 0:
                    print("Pages list empty")
                    return None
                page_data = pages[0]
                # check for missing page flag
                if page_data.get("missing"):
                    print(f"Page '{word}' not found (missing flag)")
                    return None
            else:
                print(f"Unexpected pages type: {type(pages)}")
                return None

            revisions = page_data.get("revisions", [])
            if not revisions:
                print(f"No revisions found for '{word}'")
                return None

            # revision content may be under slots->main->* or slots->main->content or directly under '*' depending on format
            rev0 = revisions[0]
            content = ""
            # Try several common locations for the wikitext content
            if isinstance(rev0, dict):
                content = (
                    rev0.get("slots", {}).get("main", {}).get("*")
                    or rev0.get("slots", {}).get("main", {}).get("content")
                    or rev0.get("*")
                    or rev0.get("content")
                )
            else:
                content = None

            if not content:
                print(
                    "Could not locate wikitext content in revision object; dumping revision snippet for debugging"
                )
                try:
                    print(json.dumps(rev0, ensure_ascii=False)[:800])
                except Exception:
                    pass
                return None

            if self.verbose:
                print(f"Fetched content length: {len(content)} characters\n")
            return content
        except requests.HTTPError as e:
            try:
                print(
                    f"HTTP error fetching page: {e} - status: {getattr(e.response, 'status_code', None)}"
                )
                print("Response body (truncated):", e.response.text[:800])
            except Exception:
                pass
            return None
        except requests.RequestException as e:
            print(f"Network error fetching page: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error parsing page response: {e}")
            return None

    def extract_russian_section(self, content: str) -> Optional[str]:
        """Extract the Russian language section from page wikitext."""
        # Find the Russian section heading (==Russian==). Use non-greedy match until next ==...==
        pattern = r"(?s)==Russian==\s*(.*?)(?:\n==[^=]|\Z)"
        m = re.search(pattern, content)
        if not m:
            print("Russian section not found in page content")
            return None
        sec = m.group(1)
        if self.verbose:
            print(f"Extracted Russian section ({len(sec)} chars)")
        return sec

    def extract_preposition_section(self, russian_section: str) -> Optional[str]:
        """Extract the Preposition subsection inside the Russian section."""
        # Match ===Preposition=== ... until next === or == or end
        m = re.search(r"(?s)===Preposition===(.*?)(?:\n===|\n==|\Z)", russian_section)
        if not m:
            print("Preposition subsection not found inside Russian section")
            return None
        prep = m.group(1)
        if self.verbose:
            print(
                f"Extracted Preposition section ({len(prep)} chars)\n--- section (first 600 chars) ---\n{prep[:600]}\n--- end ---\n"
            )
        return prep

    def parse_preposition_cases(self, prep_section: str) -> List[Dict]:
        """Parse the Preposition section and return a list of cases with one example each.
        More flexible parsing:
        - Treat any single-# line as a top-level item (unless it's a '##' line)
        - Handle templates like {{+obj|ru|acc}} or {{i|...}} as keys
        - For blocks with '##' subitems, create one result per subitem
        """
        lines = prep_section.splitlines()
        results: List[Dict] = []

        i = 0
        while i < len(lines):
            raw = lines[i]
            stripped = raw.strip()

            # Top-level item: starts with single '#' (not '##')
            if stripped.startswith("#") and not stripped.startswith("##"):
                top_line = stripped

                # collect block lines belonging to this top-level item
                block_lines: List[str] = []
                j = i + 1
                while j < len(lines):
                    s = lines[j].strip()
                    # stop when we hit the next single-# top-level item
                    if s.startswith("#") and not s.startswith("##"):
                        break
                    block_lines.append(lines[j])
                    j += 1

                # try to extract a machine key from common templates like {{+obj|ru|acc}} or {{i|with accusative}}
                key_match = re.search(r"\{\{\+?obj\|ru\|([^}\|]+)", top_line)
                if not key_match:
                    key_match = re.search(r"\{\{i\|([^}]+)\}\}", top_line)

                if key_match:
                    top_key = key_match.group(1).strip()
                else:
                    # fallback: clean the top line to a readable definition
                    top_key = re.sub(r"^#\s*", "", top_line)
                    top_key = self._clean_definition_text(top_key)

                # detect if there are '##' subitems
                has_subitems = any(
                    line.strip().startswith("##") and not line.strip().startswith("##:")
                    for line in block_lines
                )

                if not has_subitems:
                    # single item: look for example in the block
                    example = self._find_first_ux_example(block_lines)
                    definition = self._clean_definition_text(top_line)
                    results.append(
                        {
                            "use": top_key,
                            "definition": definition or "N/A",
                            "russian_example": example.get("russian")
                            if example
                            else None,
                            "english_translation": example.get("english")
                            if example
                            else None,
                        }
                    )
                else:
                    # iterate through subitems (lines starting with '##' and not '##:')
                    k = 0
                    while k < len(block_lines):
                        line_k = block_lines[k].strip()
                        if line_k.startswith("##") and not line_k.startswith("##:"):
                            # label for this subuse
                            label = re.sub(r"^##\s*", "", line_k)
                            label = re.sub(r"\{\{lb\|ru\|([^}]+)\}\}", r"\1", label)
                            label = self._clean_definition_text(label)

                            # collect lines belonging to this subitem (following lines until next '##' or end)
                            subblock: List[str] = []
                            mpos = k + 1
                            while mpos < len(block_lines):
                                nxt = block_lines[mpos].strip()
                                if nxt.startswith("##") and not nxt.startswith("##:"):
                                    break
                                subblock.append(block_lines[mpos])
                                mpos += 1

                            example = self._find_first_ux_example(subblock)
                            results.append(
                                {
                                    "use": top_key,
                                    "subuse": label or "(unspecified)",
                                    "definition": label or "N/A",
                                    "russian_example": example.get("russian")
                                    if example
                                    else None,
                                    "english_translation": example.get("english")
                                    if example
                                    else None,
                                }
                            )

                            k = mpos
                        else:
                            k += 1

                i = j
                continue

            i += 1

        return results

    def _find_first_ux_example(
        self, candidate_lines: List[str]
    ) -> Dict[str, Optional[str]]:
        """Search the provided lines for the first {{ux...|ru|RUS|ENG}} template and return parsed pieces.
        Use a small template parser to correctly handle '|' inside nested [[...]] or {{...}}.
        """

        def clean_wiki_text(s: str) -> str:
            # remove bold/italic markup
            s = re.sub(r"'''", "", s)
            s = re.sub(r"''", "", s)
            # convert [[link|text]] -> text, [[link]] -> link
            s = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", s)
            s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
            # remove simple templates like {{lang|...}} or {{uxi|...}} fallback: remove braces
            s = re.sub(r"\{\{([^\}]+)\}\}", r"\1", s)
            # collapse whitespace
            s = re.sub(r"\s+", " ", s).strip()
            return s

        # remove leading '##:' or '#:' markers from candidate lines
        cleaned_lines = [ln.lstrip() for ln in candidate_lines]
        joined = "\n".join(cleaned_lines)

        # Find first occurrence of {{ux...|ru|
        m = re.search(r"\{\{(ux[a-zA-Z0-9_-]*)\|ru\|", joined)
        if m:
            start = m.start()
            # find matching closing '}}' for this template using a simple counter
            i = start
            length = len(joined)
            if joined.startswith("{{", start):
                level = 1
                i = start + 2
            else:
                level = 0
                i = start

            end = None
            while i < length - 1:
                pair = joined[i : i + 2]
                if pair == "{{":
                    level += 1
                    i += 2
                    continue
                if pair == "}}":
                    level -= 1
                    i += 2
                    if level == 0:
                        end = i
                        break
                    continue
                i += 1

            template_text = joined[start:end] if end else joined[start:]

            # find the literal '|ru|' inside template_text
            idx = template_text.find("|ru|")
            if idx != -1:
                # scan forward to extract RU param until next top-level '|', then EN until closing
                j = idx + 4
                b_lvl = 0
                sq_lvl = 0
                ru_chars = []
                en_chars = []
                seen_sep = False
                while j < len(template_text):
                    # check two-char tokens
                    two = template_text[j : j + 2]
                    if two == "{{":
                        if not seen_sep:
                            b_lvl += 1
                        else:
                            # inside en param
                            pass
                        ru_chars.append(two) if not seen_sep else en_chars.append(two)
                        j += 2
                        continue
                    if two == "}}" and b_lvl > 0:
                        b_lvl -= 1
                        ru_chars.append(two) if not seen_sep else en_chars.append(two)
                        j += 2
                        continue
                    if two == "[[":
                        sq_lvl += 1
                        ru_chars.append(two) if not seen_sep else en_chars.append(two)
                        j += 2
                        continue
                    if two == "]]" and sq_lvl > 0:
                        sq_lvl -= 1
                        ru_chars.append(two) if not seen_sep else en_chars.append(two)
                        j += 2
                        continue

                    ch = template_text[j]
                    if ch == "|" and b_lvl == 0 and sq_lvl == 0 and not seen_sep:
                        # separator between ru and en
                        seen_sep = True
                        j += 1
                        continue
                    if not seen_sep:
                        ru_chars.append(ch)
                    else:
                        en_chars.append(ch)
                    j += 1

                ru = "".join(ru_chars).strip()
                en = "".join(en_chars).strip()
                # clean up leftover braces or markers
                ru = re.sub(r"\}\}|\{\{|##:\s*", "", ru)
                en = re.sub(r"\}\}|\{\{|##:\s*", "", en)
                ru = clean_wiki_text(ru)
                en = clean_wiki_text(en)
                ru = unicodedata.normalize("NFC", ru)
                en = unicodedata.normalize("NFC", en)
                return {"russian": ru, "english": en}

        # fallback: look for #: lines
        for ln in candidate_lines:
            if ln.strip().startswith("#:") or ln.strip().startswith("##:"):
                text = ln.strip()[2:].strip()
                if "|" in text:
                    parts = text.split("|", 1)
                    ru_part = unicodedata.normalize(
                        "NFC", clean_wiki_text(parts[0].strip())
                    )
                    en_part = unicodedata.normalize(
                        "NFC", clean_wiki_text(parts[1].strip())
                    )
                    return {"russian": ru_part, "english": en_part}
                return {
                    "russian": unicodedata.normalize("NFC", clean_wiki_text(text)),
                    "english": None,
                }

        return {"russian": None, "english": None}

    def _clean_definition_text(self, txt: str) -> str:
        t = re.sub(r"\{\{[^}]+\}\}", "", txt)
        t = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def parse_word(self, word: str) -> Dict:
        if self.verbose:
            print("\n" + "=" * 60)
            print(f"PARSING: {word} (language={self.language})")
            print("=" * 60 + "\n")

        # Print API info first (only when verbose)
        self.get_api_info()

        content = self.get_page_content(word)
        if not content:
            return {"word": word, "error": "Could not fetch content"}

        rus = self.extract_russian_section(content)
        if not rus:
            return {"word": word, "error": "Russian section not found"}

        prep = self.extract_preposition_section(rus)
        if not prep:
            return {"word": word, "error": "Preposition section not found"}

        cases = self.parse_preposition_cases(prep)
        summarized = self._summarize_cases(cases)
        return {
            "word": word,
            "cases": summarized,
            "total_cases": sum(len(v) for v in summarized.values()),
        }

    def _summarize_cases(self, cases: List[Dict]) -> Dict[str, List[Dict]]:
        """Group parsed flat case entries into a dict keyed by top use (prep/acc/nom).
        Each entry in the lists will have 'definition', 'russian_example', 'english_translation'.
        """
        groups: Dict[str, List[Dict]] = {}
        for c in cases:
            use = c.get("use")
            if not use:
                continue
            groups.setdefault(use, []).append(
                {
                    "definition": c.get("definition") or c.get("subuse") or "N/A",
                    "russian_example": c.get("russian_example"),
                    "english_translation": c.get("english_translation"),
                }
            )

        # Ensure deterministic order: prefer 'prep', 'acc', 'nom' if present
        ordered: Dict[str, List[Dict]] = {}
        for key in ["prep", "acc", "nom"]:
            if key in groups:
                ordered[key] = groups[key]
        # include any other keys after
        for k in groups:
            if k not in ordered:
                ordered[k] = groups[k]

        return ordered

    def format_output(self, result: Dict) -> str:
        # Produce only the human-readable output requested: three top-level uses with their (sub)cases
        if "error" in result:
            return f"Error: {result['error']}"

        cases = result.get("cases", {})
        # Map technical keys to display labels
        display_map = {
            "prep": "with prepositional",
            "acc": "with accusative",
            "nom": "with nominative",
        }

        out_lines: List[str] = []
        for use_key, entries in cases.items():
            header = display_map.get(use_key, f"with {use_key}")
            out_lines.append(f"[{header}]")
            # If there are multiple entries (like accusative), enumerate them
            if len(entries) > 1:
                for n, e in enumerate(entries, 1):
                    out_lines.append(f"{n}. {e.get('definition')}")
                    out_lines.append(f"   Russian: {e.get('russian_example')}")
                    out_lines.append(f"   English: {e.get('english_translation')}")
            else:
                e = entries[0]
                out_lines.append(f"{e.get('definition')}")
                out_lines.append(f"Russian: {e.get('russian_example')}")
                out_lines.append(f"English: {e.get('english_translation')}")

            out_lines.append("")

        return "\n".join(out_lines).strip()


def main():
    parser = WiktionaryParser(language="en")

    targets = ["в", "на"]
    for target in targets:
        result = parser.parse_word(target)
        print("\n--- FORMATTED OUTPUT ---\n")
        print(f"WORD: {target}\n")
        print(parser.format_output(result))
        print("\n" + "=" * 40 + "\n")


if __name__ == "__main__":
    main()
