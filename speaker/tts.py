"""Text to speech on the device (F5): Piper, with espeak-ng as the fallback."""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

from speaker.config import Settings

log = logging.getLogger(__name__)


class PiperTTS:
    def __init__(self, voice_path: Path):
        from piper import PiperVoice

        self.voice = PiperVoice.load(str(voice_path))
        self.name = f"Piper ({voice_path.stem})"

    def synthesize(self, text: str) -> tuple[np.ndarray, int] | None:
        if hasattr(self.voice, "synthesize_stream_raw"):  # piper-tts 1.2
            raw = b"".join(self.voice.synthesize_stream_raw(text))
            rate = self.voice.config.sample_rate
        else:  # piper-tts 1.3+
            chunks = list(self.voice.synthesize(text))
            if not chunks:
                return None
            raw = b"".join(c.audio_int16_bytes for c in chunks)
            rate = chunks[0].sample_rate
        if not raw:
            return None
        return np.frombuffer(raw, dtype=np.int16), rate


class EspeakTTS:
    name = "espeak-ng"

    def __init__(self) -> None:
        self.binary = shutil.which("espeak-ng") or shutil.which("espeak")
        if not self.binary:
            raise RuntimeError("espeak-ng is not installed")

    def synthesize(self, text: str) -> tuple[np.ndarray, int] | None:
        wav = subprocess.run([self.binary, "--stdout", text], capture_output=True, check=True).stdout
        with wave.open(io.BytesIO(wav)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16), w.getframerate()


def load_tts(settings: Settings):
    """The best voice available: Piper if its model is downloaded, otherwise espeak-ng."""
    path = settings.piper_voice_path
    if path.exists():
        try:
            return PiperTTS(path)
        except Exception as e:
            log.warning("Piper failed to load (%s); falling back to espeak-ng", e)
    else:
        log.warning("Piper voice not found at %s; falling back to espeak-ng", path)
    return EspeakTTS()
