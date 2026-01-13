"""Russian language module with pymorphy3 morphological analysis."""

import re
from functools import lru_cache

from freqanki.languages.base import LanguageModule, MorphologyInfo

# Regex patterns for Russian text
CYRILLIC_PATTERN = re.compile(r"[А-Яа-яЁё]")
DIGIT_PATTERN = re.compile(r"^\d+$")

# Russian number words
RUS_NUMBER_WORDS = {
    "0": "ноль",
    "1": "один",
    "2": "два",
    "3": "три",
    "4": "четыре",
    "5": "пять",
    "6": "шесть",
    "7": "семь",
    "8": "восемь",
    "9": "девять",
}

# Common Russian abbreviations
SPECIAL_CANONICAL_MAP = {
    "млн": "миллион",
    "тыс": "тысяча",
    "руб": "рубль",
    "ул": "улица",
    "млрд": "миллиард",
    "блн": "миллиард",
}

# Morphological tag mappings
CASE_NAMES = {
    "nomn": "Nominative",
    "gent": "Genitive",
    "datv": "Dative",
    "accs": "Accusative",
    "ablt": "Instrumental",
    "loct": "Prepositional",
}

GENDER_NAMES = {
    "masc": "Masculine",
    "femn": "Feminine",
    "neut": "Neuter",
}

NUMBER_NAMES = {
    "sing": "Singular",
    "plur": "Plural",
}

POS_NAMES = {
    "NOUN": "Noun",
    "VERB": "Verb",
    "ADJF": "Adjective",
    "ADJS": "Short Adjective",
    "ADVB": "Adverb",
    "PREP": "Preposition",
    "CONJ": "Conjunction",
    "PRCL": "Particle",
    "NPRO": "Pronoun",
    "NUMR": "Numeral",
    "INFN": "Infinitive",
}

ANIMACY_NAMES = {"anim": "Animate", "inan": "Inanimate"}
ASPECT_NAMES = {"perf": "Perfective", "impf": "Imperfective"}
TENSE_NAMES = {"past": "Past", "pres": "Present", "futr": "Future"}
PERSON_NAMES = {"1per": "First Person", "2per": "Second Person", "3per": "Third Person"}
MOOD_NAMES = {"indc": "Indicative", "impr": "Imperative"}


class RussianModule(LanguageModule):
    """Russian language support with full morphological analysis."""

    code = "ru"
    name = "Russian"
    wordfreq_code = "ru"
    tatoeba_code = "rus"
    deepl_code = "RU"
    has_full_support = True

    def __init__(self) -> None:
        self._analyzer = None

    def _get_analyzer(self):
        """Lazily load the morphological analyzer."""
        if self._analyzer is None:
            import pymorphy3

            self._analyzer = pymorphy3.MorphAnalyzer()
        return self._analyzer

    def is_valid_token(self, word: str) -> bool:
        """Check if token is a valid Russian word or number."""
        text = (word or "").strip()
        if not text:
            return False

        # Allow numeric tokens (will be expanded to word form)
        if DIGIT_PATTERN.fullmatch(text):
            return True

        # Must contain at least one Cyrillic character
        return bool(CYRILLIC_PATTERN.search(text))

    def get_romanization(self, word: str) -> str | None:
        """
        Romanize Russian text using transliterate library.

        Falls back to None if transliterate is not available.
        """
        try:
            from transliterate import translit

            return translit(word, "ru", reversed=True)
        except ImportError:
            return None
        except Exception:
            return None

    @lru_cache(maxsize=4096)
    def get_morphology(self, word: str) -> MorphologyInfo | None:
        """Get morphological analysis using pymorphy3."""
        try:
            analyzer = self._get_analyzer()
            parsed = analyzer.parse(word)[0]

            return MorphologyInfo(
                lemma=parsed.normal_form,
                part_of_speech=POS_NAMES.get(str(parsed.tag.POS), str(parsed.tag.POS))
                if parsed.tag.POS
                else None,
                case=CASE_NAMES.get(str(parsed.tag.case)) if parsed.tag.case else None,
                gender=GENDER_NAMES.get(str(parsed.tag.gender))
                if parsed.tag.gender
                else None,
                number=NUMBER_NAMES.get(str(parsed.tag.number))
                if parsed.tag.number
                else None,
                animacy=ANIMACY_NAMES.get(str(parsed.tag.animacy))
                if parsed.tag.animacy
                else None,
                aspect=ASPECT_NAMES.get(str(parsed.tag.aspect))
                if parsed.tag.aspect
                else None,
                tense=TENSE_NAMES.get(str(parsed.tag.tense))
                if parsed.tag.tense
                else None,
                person=PERSON_NAMES.get(str(parsed.tag.person))
                if parsed.tag.person
                else None,
                mood=MOOD_NAMES.get(str(parsed.tag.mood)) if parsed.tag.mood else None,
            )
        except Exception:
            return None

    def expand_special_word(self, word: str) -> str | None:
        """Expand Russian abbreviations and number digits."""
        if not word:
            return None

        normalized = word.strip()

        # Expand single digit to word
        if DIGIT_PATTERN.fullmatch(normalized):
            return RUS_NUMBER_WORDS.get(normalized)

        # Expand abbreviations
        lower = normalized.lower()
        if lower in SPECIAL_CANONICAL_MAP:
            return SPECIAL_CANONICAL_MAP[lower]

        return None

    def get_lemma(self, word: str) -> str:
        """Get the lemma, with special handling for abbreviations and numbers."""
        # Check special expansions first
        expanded = self.expand_special_word(word)
        if expanded:
            return expanded

        # Use morphological analysis
        morph = self.get_morphology(word)
        if morph and morph.lemma:
            return morph.lemma

        return word

    def get_display_word(self, word: str) -> str:
        """Format word for display, showing expansion for special words."""
        expanded = self.expand_special_word(word)
        if expanded:
            return f"{word} · {expanded}"
        return word
