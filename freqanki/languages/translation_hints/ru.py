"""
Russian-specific translation hints for LLM backends.

These hints help the translation model handle common pitfalls
when translating Russian → English for flashcard creation.
"""

HINTS = """
RUSSIAN-SPECIFIC GUIDANCE:

1. ЕСТЬ vs ИМЕТЬ (Existence vs Possession):
   - "есть" (3rd person of быть "to be") = "is" / "there is"
   - "есть" meaning "to eat" is rare as dictionary form for flashcards
   - Don't confuse with possession constructions

2. ЛИ (Question particle):
   - "ли" turns statements into yes/no questions
   - Translate as "whether" or "if", NOT "or"
   - "или" = "or" (different word!)

3. НИ (Emphatic negation):
   - "ни" = "neither" / "nor" (emphatic negative)
   - "не" = "not" (simple negation)
   - Common in phrases like "ни один" (not a single one)

4. CASE-DECLINED PRONOUNS:
   - него/неё/них = him/her/them (genitive/prepositional with prepositions)
   - ему/ей/им = him/her/them (dative)
   - его/её/их = his/her/their OR him/her/them (genitive/accusative)

5. ASPECT PAIRS:
   - For verbs, give the most common English equivalent
   - Don't overthink perfective vs imperfective for basic flashcards
   - "делать/сделать" → both = "to do" / "to make"

6. REFLEXIVE VERBS (-ся/-сь):
   - Often translate without explicit "oneself"
   - "находиться" = "to be located" (not "to find oneself")
   - "казаться" = "to seem" (not "to show oneself")

7. PARTICLES AND DISCOURSE MARKERS:
   - "же" = emphasis, often untranslatable → "indeed" / omit
   - "ведь" = "after all" / "you know"
   - "бы" = conditional marker → "would"

8. VERBAL PREFIXES (common meanings):
   - вы- = out
   - при- = arrival
   - у- = away
   - пере- = across/re-
"""
