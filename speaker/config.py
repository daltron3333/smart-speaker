"""Settings for the speaker.

Every field can be overridden with an environment variable named SPEAKER_<FIELD>
(for example SPEAKER_WAKE_THRESHOLD=0.6), so the systemd service keeps all of
its settings, and the API key, in one file: /etc/pi-speaker/env.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    # Brain
    model: str = "claude-haiku-5-5"
    effort: str = "low"  # low is fastest; raise to medium if answers get sloppy
    thinking: str = "adaptive"  # "adaptive" or "off" (off is allowed at effort high or below)
    max_tokens: int = 1024  # thinking counts toward this, so leave room above the spoken reply
    api_timeout_s: float = 15.0
    history_turns: int = 4  # exchanges kept for follow-up questions (F9)
    history_timeout_s: float = 300.0  # forget the conversation after 5 minutes of quiet

    # Ears
    audio_device: str = "Jabra"  # matched as a substring of the device name; "" = system default
    wake_model: str = "hey_mango"  # wakewords/hey_mango.onnx; falls back to hey_jarvis until trained
    wake_threshold: float = 0.5

    # Hearing
    vad_threshold: float = 0.5
    silence_s: float = 1.0  # stop recording this long after speech ends (F2)
    max_record_s: float = 12.0
    no_speech_timeout_s: float = 4.0  # give up if nobody starts talking after the wake tone
    whisper_model: str = "base.en"  # fallback: tiny.en
    whisper_threads: int = 4

    # Voice
    piper_voice: str = "en_US-lessac-medium"

    # Files
    data_dir: str = ""  # defaults to the project folder; the service uses /opt/pi-speaker
    log_text: bool = True  # write transcripts and replies to logs/turns.jsonl (text only, never audio)

    @property
    def root(self) -> Path:
        return Path(self.data_dir) if self.data_dir else Path(__file__).resolve().parent.parent

    @property
    def log_dir(self) -> Path:
        return self.root / "logs"

    @property
    def model_dir(self) -> Path:
        return self.root / "models"

    @property
    def piper_voice_path(self) -> Path:
        return self.model_dir / "piper" / f"{self.piper_voice}.onnx"

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Settings:
        environ = os.environ if environ is None else environ
        overrides = {}
        for f in dataclasses.fields(cls):
            raw = environ.get(f"SPEAKER_{f.name.upper()}")
            if raw is None:
                continue
            if f.type in ("bool", bool):
                overrides[f.name] = raw.strip().lower() in ("1", "true", "yes", "on")
            elif f.type in ("int", int):
                overrides[f.name] = int(raw)
            elif f.type in ("float", float):
                overrides[f.name] = float(raw)
            else:
                overrides[f.name] = raw
        return cls(**overrides)


def load_env_file(path: Path) -> None:
    """Loads KEY=VALUE lines (like ANTHROPIC_API_KEY) into the environment for local runs.

    Values already set in the environment win. On the Pi the service uses
    /etc/pi-speaker/env instead, and this file is never copied there.
    """
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        value = value.strip().strip("\"'")
        if key and value:
            os.environ.setdefault(key, value)
