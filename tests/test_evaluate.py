import unittest
from pathlib import Path

from speaker.config import Settings
from speaker.evaluate import load_script, word_accuracy

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "test_questions.txt"


class WordAccuracyTest(unittest.TestCase):
    def test_ignores_case_punctuation_and_number_style(self):
        self.assertEqual(word_accuracy("Set a timer for ten seconds.", "set a timer for 10 seconds"), 1.0)

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
