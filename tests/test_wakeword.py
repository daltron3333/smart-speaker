import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from speaker import wakeword
from speaker.wakeword import phrase_for, resolve_model

HAS_OPENWAKEWORD = importlib.util.find_spec("openwakeword") is not None


class PhraseTest(unittest.TestCase):
    def test_phrase_comes_from_the_model_name(self):
        self.assertEqual(phrase_for("hey_mango"), "hey mango")
        self.assertEqual(phrase_for("/models/hey_jarvis_v0.1.onnx"), "hey jarvis")
        self.assertEqual(phrase_for("wakewords/hey_mango.onnx"), "hey mango")


@unittest.skipUnless(HAS_OPENWAKEWORD, "openwakeword is not installed")
class ResolveModelTest(unittest.TestCase):
    def test_custom_model_in_wakewords_folder_is_used(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "hey_mango.onnx").write_bytes(b"model")
            with mock.patch.object(wakeword, "WAKEWORDS_DIR", Path(folder)):
                self.assertEqual(resolve_model("hey_mango"), (str(Path(folder) / "hey_mango.onnx"), False))

    def test_missing_custom_model_falls_back_to_hey_jarvis(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(wakeword, "WAKEWORDS_DIR", Path(folder)):
                with self.assertLogs("speaker.wakeword", "WARNING"):
                    self.assertEqual(resolve_model("hey_mango"), ("hey_jarvis", True))

    def test_built_in_names_still_work(self):
        self.assertEqual(resolve_model("alexa"), ("alexa", False))


if __name__ == "__main__":
    unittest.main()
