"""Answer-leakage detection.

Everything the system says back to a learner passes through here. The point of the
product is that the learner does the reasoning; a probe that contains the answer, in any
notation, has quietly turned into a tutor and given the game away.

Note that tier-1 evidence routinely contains the answer — the witness value that
separates two solution sets usually *is* the solution. That evidence is worth keeping
for audit, so it is stored, and redacted on the way out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NUMBER_WORDS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
    "10": "ten",
    "11": "eleven",
    "12": "twelve",
    "13": "thirteen",
    "14": "fourteen",
    "15": "fifteen",
    "16": "sixteen",
    "17": "seventeen",
    "18": "eighteen",
    "19": "nineteen",
    "20": "twenty",
}

REDACTION = "[withheld]"

_ANSWER = re.compile(
    r"^\s*\$*\\?\(?\s*([A-Za-z][A-Za-z_0-9]{0,2})\s*(?:=|:=|\\to|->|→|\bis\b|\bequals\b)\s*"
    r"(-?\d+(?:\.\d+)?(?:\s*/\s*-?\d+)?)\s*\)?\$*\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Answer:
    variable: str
    value: str

    @property
    def value_word(self) -> str | None:
        return NUMBER_WORDS.get(self.value.lstrip("+"))


def parse_answer(canonical_answer: str) -> Answer | None:
    """Read 'x = 3' into its parts. Returns None for answers we cannot pattern-match."""
    match = _ANSWER.match(canonical_answer or "")
    if not match:
        return None
    variable, value = match.group(1), re.sub(r"\s+", "", match.group(2))
    return Answer(variable=variable, value=value)


def _patterns(answer: Answer) -> list[re.Pattern[str]]:
    var = re.escape(answer.variable)
    val = re.escape(answer.value)
    joiners = r"(?:=|:=|==|\\to|->|→|\bis\b|\bequals\b|\bis\s+equal\s+to\b|\bmust\s+be\b)"
    forms = [
        rf"\b{var}\s*{joiners}\s*\(?\s*{val}\b",
        rf"\b{val}\s*{joiners}\s*{var}\b",
        rf"\b{var}\s*{joiners}\s*{val}\b",
    ]
    word = answer.value_word
    if word:
        forms += [
            rf"\b{var}\s*{joiners}\s*{re.escape(word)}\b",
            rf"\b{re.escape(word)}\s*{joiners}\s*{var}\b",
        ]
    # "the answer is 3", "the solution is three" — the variable need not be named.
    answerish = r"(?:answer|solution|result|value)"
    forms.append(rf"\b(?:the\s+)?{answerish}\s+(?:is|=|comes\s+to|equals)\s*\(?\s*{val}\b")
    if word:
        forms.append(rf"\b(?:the\s+)?{answerish}\s+(?:is|=|equals)\s+{re.escape(word)}\b")
    return [re.compile(f, re.IGNORECASE) for f in forms]


def leaks(text: str, canonical_answer: str) -> bool:
    """True when the text states the answer in any notation we can recognise."""
    answer = parse_answer(canonical_answer)
    if answer is None or not text:
        return False
    normalised = text.replace("−", "-").replace(" ", " ")
    return any(pattern.search(normalised) for pattern in _patterns(answer))


def redact(text: str, canonical_answer: str) -> str:
    """Blank out any statement of the answer, leaving the rest of the text intact."""
    answer = parse_answer(canonical_answer)
    if answer is None or not text:
        return text
    out = text.replace("−", "-")
    for pattern in _patterns(answer):
        out = pattern.sub(REDACTION, out)
    return out
