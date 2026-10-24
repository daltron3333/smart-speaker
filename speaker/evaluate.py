"""Scoring transcripts against the test script (the 90% word accuracy target)."""

from __future__ import annotations

import re
from pathlib import Path

_NUMBERS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
    "thirteen": "13", "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30", "forty": "40",
    "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
}


def normalize(text: str) -> list[str]:
    """Lowercase words without punctuation, with number words as digits ("ten" == "10")."""
    text = text.lower().replace("-", " ").replace("%", " percent")
    words = re.sub(r"[^a-z0-9' ]+", " ", text).split()
    return [_NUMBERS.get(w, w) for w in words]


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
