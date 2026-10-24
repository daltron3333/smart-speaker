"""Turning streamed reply text into clean sentences the voice can speak one at a time."""

from __future__ import annotations

import re

# A sentence ends at . ! or ? (plus any closing quote or bracket) followed by whitespace.
# Requiring the whitespace means "3.5" and a sentence still being streamed don't split early.
_SENTENCE_END = re.compile(r"[.!?]+[\"')\]]*(?=\s)")
_ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "st.", "vs.", "etc.", "approx.", "no.", "jr.", "sr."}
_INITIALISM = re.compile(r"^(?:[a-z]\.)+$")  # U.S., e.g., i.e.
_LIST_NUMBER = re.compile(r"^\d+[.)]$")  # "1." at the start of a list item


class SentenceSplitter:
    """Collects streamed text and hands back each sentence as soon as it is complete."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        sentences = []
        while True:
            cut = self._find_cut()
            if cut is None:
                return sentences
            sentence = clean_for_speech(self._buffer[:cut])
            self._buffer = self._buffer[cut:].lstrip()
            if sentence:
                sentences.append(sentence)

    def flush(self) -> list[str]:
        sentence = clean_for_speech(self._buffer)
        self._buffer = ""
        return [sentence] if sentence else []

    def _find_cut(self) -> int | None:
        newline = self._buffer.find("\n")
        for match in _SENTENCE_END.finditer(self._buffer):
            if newline != -1 and newline < match.end():
                break
            words = self._buffer[: match.end()].split()
            last_word = words[-1].lower().strip("\"')]") if words else ""
            if last_word in _ABBREVIATIONS or _INITIALISM.match(last_word):
                continue
            if len(words) == 1 and _LIST_NUMBER.match(last_word):
                continue
            return match.end()
        if newline != -1:
            return newline + 1
        return None


_MARKDOWN = [
    (re.compile(r"https?://\S+"), "the link"),
    (re.compile(r"`+"), ""),
    (re.compile(r"\*\*|__|\*"), ""),
    (re.compile(r"^\s*#+\s*", re.MULTILINE), ""),
    (re.compile(r"^\s*(?:[-•]|\d+[.)])\s+", re.MULTILINE), ""),
]


def clean_for_speech(text: str) -> str:
    """Strips markdown and links that would sound wrong read aloud."""
    for pattern, replacement in _MARKDOWN:
        text = pattern.sub(replacement, text)
    return " ".join(text.split())
