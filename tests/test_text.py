import unittest

from speaker.text import SentenceSplitter, clean_for_speech


def split(*chunks):
    splitter = SentenceSplitter()
    out = []
    for chunk in chunks:
        out += splitter.feed(chunk)
    return out + splitter.flush()


class SentenceSplitterTest(unittest.TestCase):
    def test_hands_back_each_sentence_once_it_is_complete(self):
        splitter = SentenceSplitter()
        self.assertEqual(splitter.feed("Paris is the capital"), [])
        self.assertEqual(splitter.feed(" of France. It has"), ["Paris is the capital of France."])
        self.assertEqual(splitter.flush(), ["It has"])

    def test_waits_for_whitespace_so_decimals_stay_whole(self):
        self.assertEqual(split("Pi is about 3", ".14 overall."), ["Pi is about 3.14 overall."])

    def test_keeps_abbreviations_and_initialisms_together(self):
        self.assertEqual(
            split("Dr. Smith moved to the U.S. in 1990. Then he left!"),
            ["Dr. Smith moved to the U.S. in 1990.", "Then he left!"],
        )

    def test_question_and_exclamation_marks_end_sentences(self):
        self.assertEqual(split("Really? Yes! Okay."), ["Really?", "Yes!", "Okay."])

    def test_newlines_end_sentences(self):
        self.assertEqual(split("First line\nSecond line"), ["First line", "Second line"])

    def test_list_numbers_are_not_sentences(self):
        self.assertEqual(split("1. Boil water. 2. Add pasta."), ["Boil water.", "Add pasta."])


class CleanForSpeechTest(unittest.TestCase):
    def test_strips_markdown_and_links(self):
        self.assertEqual(clean_for_speech("**Bold** and `code`"), "Bold and code")
        self.assertEqual(clean_for_speech("## Heading"), "Heading")
        self.assertEqual(clean_for_speech("- a bullet"), "a bullet")
        self.assertEqual(clean_for_speech("See https://example.com now"), "See the link now")


if __name__ == "__main__":
    unittest.main()
