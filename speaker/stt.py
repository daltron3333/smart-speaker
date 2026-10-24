"""Speech to text on the device with faster-whisper (F3)."""

from __future__ import annotations

import logging
import os

import numpy as np

from speaker.config import Settings

log = logging.getLogger(__name__)

# Whisper sometimes invents these on near-silent audio.
_HALLUCINATIONS = {"", "you", "thank you", "thanks for watching", "bye"}


class Transcriber:
    def __init__(self, settings: Settings):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(
            settings.whisper_model,
            device="cpu",
            compute_type="int8",
            cpu_threads=settings.whisper_threads,
            download_root=str(settings.model_dir / "whisper"),
            local_files_only=os.environ.get("HF_HUB_OFFLINE") == "1",
        )

    def transcribe(self, audio: np.ndarray) -> str:
        """audio is 16 kHz mono int16. Returns "" when nothing intelligible was said."""
        samples = audio.astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(
            samples,
            language="en",
            beam_size=1,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        if text.lower().strip(" .!?,") in _HALLUCINATIONS:
            return ""
        return text

    def warm_up(self) -> None:
        """The first transcription is slow; do it at startup rather than on the first question."""
        self.transcribe(np.zeros(16000, dtype=np.int16))
