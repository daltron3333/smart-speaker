"""speak_sentences and tones, with a fake speaker so nothing plays."""

import contextlib
import time
import unittest
from unittest import mock

import numpy as np

from speaker.audio import SAMPLE_RATE, Speaker, make_tone, resample, speak_sentences


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


class JabraOnLinux:
    """Stands in for sounddevice on the Pi, where the Jabra plays only 8, 16 or 48 kHz."""

    def __init__(self):
        self.played = []

    def check_output_settings(self, device=None, samplerate=None, channels=None, dtype=None):
        if samplerate not in (8000, 16000, 48000):
            raise Exception("Invalid sample rate")

    def play(self, samples, rate, device=None):
        self.check_output_settings(samplerate=rate)
        self.played.append((len(samples), rate))

    def wait(self):
        pass


class SampleRateTest(unittest.TestCase):
    def setUp(self):
        self.fake = JabraOnLinux()
        self.patch = mock.patch("speaker.audio._sd", return_value=self.fake)
        self.patch.start()
        self.speaker = Speaker(device_name="")
        self.speaker.busy = lambda: contextlib.nullcontext()

    def tearDown(self):
        self.patch.stop()

    def test_piper_speech_is_converted_to_48_khz(self):
        one_second = np.zeros(22050, dtype=np.int16)
        self.speaker.play(one_second, 22050)
        self.assertEqual(self.fake.played, [(48000, 48000)])

    def test_rates_the_device_accepts_play_unchanged(self):
        self.speaker.play(make_tone(880, 0.5, 0.3), SAMPLE_RATE)
        self.assertEqual(self.fake.played, [(8000, 16000)])


class ResampleTest(unittest.TestCase):
    def test_length_and_pitch_survive(self):
        t = np.arange(22050) / 22050
        tone = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)
        out = resample(tone, 22050, 48000)
        self.assertEqual(out.dtype, np.int16)
        self.assertAlmostEqual(len(out), 48000, delta=2)
        peak_hz = np.argmax(np.abs(np.fft.rfft(out))) * 48000 / len(out)
        self.assertAlmostEqual(peak_hz, 440, delta=2)


class ToneTest(unittest.TestCase):
    def test_tone_is_int16_of_the_right_length(self):
        tone = make_tone(880, 0.15, 0.3)
        self.assertEqual(tone.dtype, np.int16)
        self.assertEqual(len(tone), int(SAMPLE_RATE * 0.15))
        self.assertLessEqual(np.abs(tone).max(), int(0.3 * 32767) + 1)


if __name__ == "__main__":
    unittest.main()
