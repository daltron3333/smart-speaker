"""Listening for the wake phrase with openWakeWord (F1).

Built-in phrases (hey_jarvis, alexa, hey_mycroft...) are downloaded by setup-models. Custom
phrases are small ONNX models trained with openWakeWord's Colab notebook and saved in the
project's wakewords/ folder, e.g. wakewords/hey_mango.onnx (see README.md).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np

from speaker.config import Settings

log = logging.getLogger(__name__)

WAKEWORDS_DIR = Path(__file__).resolve().parent.parent / "wakewords"
FALLBACK_MODEL = "hey_jarvis"


def phrase_for(model: str) -> str:
    """'hey_mango' or 'wakewords/hey_mango_v0.1.onnx' -> 'hey mango'."""
    stem = Path(model).stem if model.endswith((".onnx", ".tflite")) else model
    return re.sub(r"_v\d+(\.\d+)*$", "", stem).replace("_", " ")


def resolve_model(name: str) -> tuple[str, bool]:
    """What to load for the configured wake word: (model name or path, is_fallback).

    `name` can be a path to an .onnx file, a custom model in wakewords/, or a built-in name.
    """
    import openwakeword

    candidates = [Path(name)] if name.endswith((".onnx", ".tflite")) else [WAKEWORDS_DIR / f"{name}.onnx"]
    for path in candidates:
        if path.exists():
            return str(path), False
    if name in openwakeword.MODELS:
        return name, False
    log.warning(
        "wake word model %r not found (looked for %s); using %r until it is trained",
        name, candidates[0], phrase_for(FALLBACK_MODEL),
    )
    return FALLBACK_MODEL, True


def download_models(settings: Settings) -> None:
    """Fetches the feature models, Silero VAD and any built-in wake word (setup time only)."""
    from openwakeword import utils

    model, _ = resolve_model(settings.wake_model)
    built_in = [] if model.endswith((".onnx", ".tflite")) else [model]
    utils.download_models(model_names=built_in)


class WakeWord:
    def __init__(self, settings: Settings):
        from openwakeword.model import Model

        model, self.is_fallback = resolve_model(settings.wake_model)
        self.phrase = phrase_for(model)
        self.model = Model(wakeword_models=[model], inference_framework="onnx")
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
