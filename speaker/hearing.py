"""Recording a question until the speaker stops talking (F2)."""

from __future__ import annotations

import logging
import time

import numpy as np

from speaker.audio import FRAME_S, Microphone
from speaker.config import Settings

log = logging.getLogger(__name__)


class SileroDetector:
    """Speech vs. room noise, using the Silero VAD model that ships with openWakeWord."""

    name = "Silero VAD"

    def __init__(self, threshold: float):
        from openwakeword.vad import VAD

        self.vad = VAD()
        self.threshold = threshold

    def is_speech(self, frame: np.ndarray) -> bool:
        # predict() wants a whole number of chunks; two 640-sample chunks per 80 ms frame.
        return float(self.vad.predict(frame, frame_size=640)) >= self.threshold


class LoudnessDetector:
    """Fallback: anything well above the background noise level counts as speech."""

    name = "loudness threshold"

    def __init__(self, ratio: float = 3.0, minimum_rms: float = 300.0):
        self.ratio = ratio
        self.minimum_rms = minimum_rms
        self.noise_floor = minimum_rms / ratio

    def is_speech(self, frame: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
        speech = rms > max(self.noise_floor * self.ratio, self.minimum_rms)
        if not speech:  # follow the background level slowly
            self.noise_floor = 0.95 * self.noise_floor + 0.05 * rms
        return speech


def make_detector(settings: Settings):
    try:
        return SileroDetector(settings.vad_threshold)
    except Exception as e:
        log.warning("Silero VAD unavailable (%s); using a loudness threshold", e)
        return LoudnessDetector()


def record_question(mic: Microphone, detector, settings: Settings) -> np.ndarray | None:
    """Records from the mic until `silence_s` after speech ends, or `max_record_s` in total.

    Returns None if nobody starts talking within `no_speech_timeout_s`.
    """
    frames: list[np.ndarray] = []
    heard_speech = False
    quiet_s = 0.0
    started = time.monotonic()
    while True:
        elapsed = time.monotonic() - started
        if elapsed >= settings.max_record_s:
            log.info("recording hit the %.0f s cap", settings.max_record_s)
            break
        if not heard_speech and elapsed >= settings.no_speech_timeout_s:
            return None
        frame = mic.read(timeout=1.0)
        if frame is None:
            continue
        frames.append(frame)
        if detector.is_speech(frame):
            heard_speech = True
            quiet_s = 0.0
        elif heard_speech:
            quiet_s += FRAME_S
            if quiet_s >= settings.silence_s:
                break
    return np.concatenate(frames) if heard_speech and frames else None
