"""Listening for the wake phrase with openWakeWord (F1)."""

from __future__ import annotations

import logging

import numpy as np

from speaker.config import Settings

log = logging.getLogger(__name__)


def download_models(settings: Settings) -> None:
    """Fetches the wake word, its feature models and Silero VAD (setup time only)."""
    from openwakeword import utils

    utils.download_models(model_names=[settings.wake_model])


class WakeWord:
    def __init__(self, settings: Settings):
        from openwakeword.model import Model

        self.model = Model(wakeword_models=[settings.wake_model], inference_framework="onnx")
        self.threshold = settings.wake_threshold

    def score(self, frame: np.ndarray) -> float:
        """Confidence from 0 to 1 that the wake phrase just ended in this 80 ms frame."""
        scores = self.model.predict(frame)
        return float(max(scores.values())) if scores else 0.0

    def heard(self, frame: np.ndarray) -> float | None:
        score = self.score(frame)
        return score if score >= self.threshold else None

    def reset(self) -> None:
        """Clears buffered audio so the end of the last reply can't trigger a wake."""
        self.model.reset()
