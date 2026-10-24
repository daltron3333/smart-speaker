"""Scoring transcripts against the test script (the 90% word accuracy target)."""

from __future__ import annotations

import re
from pathlib import Path

_UNITS = {
    w: n
    for n, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen".split()
    )
}
_TENS = {w: 10 * n for n, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)}
_SCALES = {"thousand": 1000, "million": 1000000}


def normalize(text: str) -> list[str]:
    """Lowercase words without punctuation, with numbers as digits.

    Whisper writes "15% of $84" where the script says "fifteen percent of eighty four dollars";
    both normalize to the same words, so only real mistakes count against accuracy.
    """
    text = text.lower().replace("’", "'").replace("'", "").replace("-", " ")
    text = re.sub(r"\$(\d[\d,]*(?:\.\d+)?)", r"\1 dollars", text)
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)  # 384,000 -> 384000
    text = text.replace("%", " percent")
    return _join_number_words(re.findall(r"\d+(?:\.\d+)?|[a-z]+", text))


def _join_number_words(words: list[str]) -> list[str]:
    """["twenty", "six", "point", "two"] -> ["26.2"]."""
    out, i = [], 0
    while i < len(words):
        if words[i] not in _UNITS and words[i] not in _TENS:
            out.append(words[i])
            i += 1
            continue
        total = current = 0
        j = i
        while j < len(words):
            w = words[j]
            if w in _UNITS:
                current += _UNITS[w]
            elif w in _TENS:
                current += _TENS[w]
            elif w == "hundred" and current:
                current *= 100
            elif w in _SCALES and (current or total):
                total += current * _SCALES[w]
                current = 0
            elif w == "and" and words[j - 1] == "hundred" and j + 1 < len(words) and words[j + 1] in _UNITS.keys() | _TENS.keys():
                pass  # "one hundred and five"
            else:
                break
            j += 1
        number = str(total + current)
        if j + 1 < len(words) and words[j] == "point" and _UNITS.get(words[j + 1], 10) < 10:
            j += 1
            digits = ""
            while j < len(words) and _UNITS.get(words[j], 10) < 10:
                digits += str(_UNITS[words[j]])
                j += 1
            number += "." + digits
        out.append(number)
        i = j
    return out


def word_accuracy(expected: str, heard: str) -> float:
    """1 - word error rate, floored at 0. 1.0 means every word matched."""
    ref, hyp = normalize(expected), normalize(heard)
    if not ref:
        return 1.0 if not hyp else 0.0
    # Levenshtein distance over words
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        current = [i]
        for j, h in enumerate(hyp, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h)))
        previous = current
    return max(0.0, 1 - previous[-1] / len(ref))


def load_script(path: Path) -> list[tuple[str, str]]:
    """Reads the test script: one question per line, optional '| note', '#' starts a group name.

    Returns (question, note) pairs.
    """
    questions = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        question, _, note = line.partition("|")
        questions.append((question.strip(), note.strip()))
    return questions
