"""A hands-free check of the ears and hearing: Piper speaks, the real models listen.

No microphone or person needed, so it shows whether the wake word, end-of-speech detection
and Whisper all work, and how fast Whisper is on this machine, before any room testing.
Piper's voice is clearer than a person across a room, so treat the accuracy as a best case.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import numpy as np

from speaker.audio import FRAME_SAMPLES, SAMPLE_RATE
from speaker.config import Settings
from speaker.evaluate import load_script, word_accuracy


class _ScriptedMic:
    def __init__(self, frames: list[np.ndarray]):
        self._frames = list(frames)

    def read(self, timeout: float = 1.0) -> np.ndarray | None:
        return self._frames.pop(0) if self._frames else None


def _frames(audio: np.ndarray) -> list[np.ndarray]:
    pad = (-len(audio)) % FRAME_SAMPLES
    return list(np.concatenate([audio, np.zeros(pad, dtype=np.int16)]).reshape(-1, FRAME_SAMPLES))


def run(settings: Settings, script: Path) -> bool:
    from scipy.signal import resample_poly

    from speaker.hearing import make_detector, record_question
    from speaker.stt import Transcriber
    from speaker.tts import load_tts
    from speaker.wakeword import WakeWord, phrase_for

    tts = load_tts(settings)
    noise = np.random.default_rng(0)

    def speech(text: str) -> np.ndarray:
        samples, rate = tts.synthesize(text)
        return resample_poly(samples.astype(np.float32), SAMPLE_RATE, rate).astype(np.int16)

    def quiet(seconds: float) -> np.ndarray:
        return noise.normal(0, 60, int(SAMPLE_RATE * seconds)).astype(np.int16)

    results: list[tuple[str, bool, str]] = []

    print(f"Voice: {tts.name}. Loading the wake word, VAD and Whisper {settings.whisper_model}...")
    wake = WakeWord(settings)
    detector = make_detector(settings)
    stt = Transcriber(settings)
    stt.warm_up()

    # Wake word
    phrase = speech(wake.phrase.capitalize() + ".")
    score = max(wake.score(f) for f in _frames(np.concatenate([quiet(1), phrase, quiet(1)])))
    results.append((f"Wake word hears '{wake.phrase}'", score >= settings.wake_threshold, f"score {score:.2f}"))
    if wake.is_fallback:
        results.append((
            f"Wake word is '{phrase_for(settings.wake_model)}'",
            False,
            f"no model yet; add wakewords/{settings.wake_model}.onnx (see README)",
        ))

    # End of speech
    question = speech("What time is it?")
    audio = record_question(_ScriptedMic(_frames(np.concatenate([quiet(0.4), question, quiet(3)]))), detector, settings)
    speech_ends = 0.4 + len(question) / SAMPLE_RATE
    stopped = None if audio is None else len(audio) / SAMPLE_RATE
    results.append((
        f"Recording stops after the question ({detector.name})",
        stopped is not None and speech_ends <= stopped <= speech_ends + settings.silence_s + 0.5,
        "nothing recorded" if stopped is None else f"stopped {stopped - speech_ends:.1f} s after speech",
    ))
    silent = record_question(_ScriptedMic(_frames(quiet(settings.no_speech_timeout_s + 2))), detector, settings)
    results.append(("Gives up when nobody speaks", silent is None, ""))

    # The test script through Whisper, and through the wake word to count false wakes
    questions = [q for q, _ in load_script(script)]
    accuracies, times, false_wakes = [], [], 0
    print(f"Transcribing {len(questions)} test questions...")
    for q in questions:
        audio = np.concatenate([quiet(0.4), speech(q), quiet(1)])
        wake.reset()
        false_wakes += any(wake.heard(f) is not None for f in _frames(audio))
        start = time.monotonic()
        heard = stt.transcribe(audio)
        times.append(time.monotonic() - start)
        accuracies.append(word_accuracy(q, heard))
        if accuracies[-1] < 1:
            print(f"  {accuracies[-1]:>4.0%}  said: {q}\n        heard: {heard}")
    accuracy = statistics.mean(accuracies)
    median = statistics.median(times)
    results.append(("Word accuracy at least 90%", accuracy >= 0.9, f"{accuracy:.0%} (best case: synthetic voice)"))
    # About 2 s of transcription leaves room for Claude and Piper inside the 4 s target.
    results.append(("Transcription about 2 s or less", median <= 2.0, f"median {median:.2f} s per question"))
    results.append(("No false wakes on the questions", false_wakes == 0, f"{false_wakes} of {len(questions)}"))

    print()
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    return all(ok for _, ok, _ in results)
