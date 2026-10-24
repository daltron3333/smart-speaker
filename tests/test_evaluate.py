import unittest
from pathlib import Path

from speaker.config import Settings
from speaker.evaluate import load_script, word_accuracy

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "test_questions.txt"


class WordAccuracyTest(unittest.TestCase):
    def test_ignores_case_punctuation_and_number_style(self):
        self.assertEqual(word_accuracy("Set a timer for ten seconds.", "set a timer for 10 seconds"), 1.0)

    def test_whisper_number_formats_match_spoken_numbers(self):
        cases = [
            ("What is fifteen percent of eighty four dollars?", "What is 15% of $84?"),
            ("How many kilometers is twenty six point two miles?", "How many kilometers is 26.2 miles?"),
            ("It is three hundred eighty four thousand kilometers", "It is 384,000 kilometers"),
            ("one hundred and five", "105"),
            ("Tell me about Tchaikovsky's Nutcracker.", "Tell me about Tchaikovskys nutcracker"),
        ]
        for expected, heard in cases:
            with self.subTest(heard=heard):
                self.assertEqual(word_accuracy(expected, heard), 1.0)

    def test_counts_wrong_and_missing_words(self):
        self.assertAlmostEqual(word_accuracy("who wrote pride and prejudice", "who wrote pride prejudice"), 0.8)
        self.assertAlmostEqual(word_accuracy("what time is it", "what dime is it"), 0.75)


class ScriptTest(unittest.TestCase):
    def test_the_test_script_has_twenty_questions(self):
        questions = load_script(SCRIPT)
        self.assertEqual(len(questions), 20)
        self.assertIn(("What is the weather like on Mars?", "say this quietly"), questions)


class SettingsTest(unittest.TestCase):
    def test_environment_overrides(self):
        settings = Settings.from_env(
            {"SPEAKER_WAKE_THRESHOLD": "0.7", "SPEAKER_HISTORY_TURNS": "6", "SPEAKER_LOG_TEXT": "no"}
        )
        self.assertEqual(settings.wake_threshold, 0.7)
        self.assertEqual(settings.history_turns, 6)
        self.assertFalse(settings.log_text)
        self.assertEqual(settings.model, "claude-haiku-5-5")


if __name__ == "__main__":
    unittest.main()
