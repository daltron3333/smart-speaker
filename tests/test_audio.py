"""speak_sentences and tones, with a fake speaker so nothing plays."""

import time
import unittest

import numpy as np

from speaker.audio import SAMPLE_RATE, Speaker, make_tone, speak_sentences


class FakeSpeaker(Speaker):
    """The real Speaker's locking and muting, with play() recording instead of making sound."""

    def __init__(self):
        super().__init__(device_name="")
        self.played = []

    def play(self, samples, rate):
        with self.busy():
            time.sleep(0.01)
            self.played.append(samples.tobytes().decode())


class FakeTTS:
    def synthesize(self, text):
        return np.frombuffer(text.encode(), dtype=np.uint8), 16000


class SpeakSentencesTest(unittest.TestCase):
    def test_plays_every_sentence_in_order_and_reports_first_audio(self):
        speaker, first = FakeSpeaker(), []
        speak_sentences(iter(["One.", "Two.", "Three."]), FakeTTS(), speaker, on_first_audio=lambda: first.append(1))
        self.assertEqual(speaker.played, ["One.", "Two.", "Three."])
        self.assertEqual(first, [1])
        self.assertFalse(speaker.muted.is_set())

    def test_mic_stays_muted_while_waiting_for_the_next_sentence(self):
        speaker = FakeSpeaker()

        def slow_sentences():
            yield "One."
            time.sleep(0.05)
            self.assertTrue(speaker.muted.is_set())
            yield "Two."

        speak_sentences(slow_sentences(), FakeTTS(), speaker)
        self.assertEqual(speaker.played, ["One.", "Two."])

    def test_a_failing_sentence_source_still_releases_the_speaker(self):
        speaker = FakeSpeaker()

        def broken():
            yield "One."
            raise RuntimeError("stream died")

        with self.assertRaises(RuntimeError):
            speak_sentences(broken(), FakeTTS(), speaker)
        self.assertEqual(speaker.played, ["One."])
        self.assertTrue(speaker._lock.acquire(blocking=False))


class ToneTest(unittest.TestCase):
    def test_tone_is_int16_of_the_right_length(self):
        tone = make_tone(880, 0.15, 0.3)
        self.assertEqual(tone.dtype, np.int16)
        self.assertEqual(len(tone), int(SAMPLE_RATE * 0.15))
        self.assertLessEqual(np.abs(tone).max(), int(0.3 * 32767) + 1)


if __name__ == "__main__":
    unittest.main()
