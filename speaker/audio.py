"""Microphone and speaker access through the Jabra, using sounddevice.

Audio is only ever held in memory. Nothing here writes sound to disk (F3).
"""

from __future__ import annotations

import contextlib
import logging
import math
import queue
import threading
import time
from typing import Callable, Iterable, Iterator

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # what openWakeWord, Silero VAD and Whisper all expect
FRAME_SAMPLES = 1280  # 80 ms, the frame size openWakeWord is built around
FRAME_S = FRAME_SAMPLES / SAMPLE_RATE


def _sd():
    import sounddevice  # imported late so typing mode works without audio libraries

    return sounddevice


def find_device(name: str, kind: str) -> int | None:
    """Index of the first device whose name contains `name`, or None for the system default."""
    if not name:
        return None
    channels = "max_input_channels" if kind == "input" else "max_output_channels"
    for index, device in enumerate(_sd().query_devices()):
        if name.lower() in device["name"].lower() and device[channels] > 0:
            return index
    log.warning("no %s device matching %r; using the system default", kind, name)
    return None


def list_devices() -> str:
    return str(_sd().query_devices())


class Microphone:
    """Streams 80 ms frames of 16 kHz mono audio into a queue. Frames are dropped while muted."""

    def __init__(self, device_name: str, muted: threading.Event):
        self._device = find_device(device_name, "input")
        self._muted = muted
        self._frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)
        self._stream = None

    def start(self) -> None:
        self._stream = _sd().InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            device=self._device,
            callback=self._callback,
        )
        self._stream.start()

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            log.debug("mic status: %s", status)
        if self._muted.is_set():
            return
        try:
            self._frames.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass  # the main loop fell behind; dropping old audio is better than lagging

    def read(self, timeout: float = 1.0) -> np.ndarray | None:
        try:
            return self._frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def flush(self) -> None:
        while not self._frames.empty():
            with contextlib.suppress(queue.Empty):
                self._frames.get_nowait()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()


class Speaker:
    """Plays audio through the Jabra and mutes the mic while it does.

    Only one thread plays at a time, so a timer going off waits for the current reply.
    """

    def __init__(self, device_name: str):
        self._device = find_device(device_name, "output")
        self.muted = threading.Event()
        self._lock = threading.RLock()
        self._depth = 0
        self._rates: dict[int, int] = {}  # clip rate -> rate the device will actually play

    @contextlib.contextmanager
    def busy(self) -> Iterator[None]:
        """Holds the speaker (and keeps the mic muted) across several clips."""
        with self._lock:
            self._depth += 1
            self.muted.set()
            try:
                yield
            finally:
                self._depth -= 1
                if self._depth == 0:
                    time.sleep(0.2)  # let the room's echo die down before listening again
                    self.muted.clear()

    def play(self, samples: np.ndarray, rate: int, mute_mic: bool = True) -> None:
        target = self._device_rate(rate)
        if target != rate:
            samples, rate = resample(samples, rate, target), target
        holder = self.busy() if mute_mic else self._lock
        with holder:
            sd = _sd()
            sd.play(samples, rate, device=self._device)
            sd.wait()

    def _device_rate(self, rate: int) -> int:
        """A rate the output device accepts, as close to `rate` as allowed.

        macOS converts any rate itself, but on the Pi ALSA hands audio straight to the
        hardware, and the Jabra plays only 8, 16 or 48 kHz, so Piper's 22.05 kHz is refused.
        """
        if rate not in self._rates:
            sd = _sd()
            choice = rate
            for candidate in (rate, 48000, 44100, 16000):
                try:
                    sd.check_output_settings(device=self._device, samplerate=candidate, channels=1, dtype="int16")
                except Exception:
                    continue
                choice = candidate
                break
            if choice != rate:
                log.info("output device can't play %d Hz; converting to %d Hz", rate, choice)
            self._rates[rate] = choice
        return self._rates[rate]

    def tone(self, freq: float = 880.0, seconds: float = 0.15, volume: float = 0.3) -> None:
        self.play(make_tone(freq, seconds, volume), SAMPLE_RATE)

    def listening_tone(self) -> None:
        """Plays without muting the mic: people say "hey Mango, what's the time" in one breath,
        and words spoken over the tone must reach the recording. The Jabra's echo
        cancellation keeps the beep itself out of the mic."""
        tone = np.concatenate([make_tone(660, 0.08, 0.3), make_tone(990, 0.12, 0.3)])
        self.play(tone, SAMPLE_RATE, mute_mic=False)

    def cancel_tone(self) -> None:
        self.tone(440, 0.15, 0.2)

    def alarm(self, rings: int = 3) -> None:
        with self.busy():
            for _ in range(rings):
                self.tone(1320, 0.2, 0.4)
                self.tone(1320, 0.2, 0.0)


def resample(samples: np.ndarray, rate: int, target: int) -> np.ndarray:
    """Converts int16 audio from `rate` to `target` Hz."""
    audio = samples.astype(np.float32)
    try:
        from scipy.signal import resample_poly

        step = math.gcd(rate, target)
        out = resample_poly(audio, target // step, rate // step)
    except ImportError:  # typing mode on a Mac may not have scipy; linear is fine for speech
        n = int(round(len(audio) * target / rate))
        out = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
    return np.clip(out, -32768, 32767).astype(np.int16)


def make_tone(freq: float, seconds: float, volume: float) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    wave = np.sin(2 * np.pi * freq * t) * volume
    fade = min(len(t) // 4, int(SAMPLE_RATE * 0.01))
    if fade:
        ramp = np.linspace(0, 1, fade)
        wave[:fade] *= ramp
        wave[-fade:] *= ramp[::-1]
    return (wave * 32767).astype(np.int16)


def speak_sentences(
    sentences: Iterable[str],
    tts,
    speaker: Speaker,
    on_first_audio: Callable[[], None] | None = None,
) -> None:
    """Speaks sentences as they arrive.

    This thread pulls sentences (which drives the Claude stream) and synthesizes them; a second
    thread plays them, so the next sentence is ready by the time the current one finishes.
    """
    clips: queue.Queue = queue.Queue()
    errors: list[BaseException] = []

    def player() -> None:
        first = True
        with speaker.busy():
            while True:
                clip = clips.get()
                if clip is None:
                    return
                if first and on_first_audio:
                    on_first_audio()
                first = False
                try:
                    speaker.play(*clip)
                except Exception as e:  # keep draining so the producer never blocks
                    errors.append(e)

    thread = threading.Thread(target=player, name="player", daemon=True)
    thread.start()
    try:
        for sentence in sentences:
            clip = tts.synthesize(sentence)
            if clip is not None:
                clips.put(clip)
    finally:
        clips.put(None)
        thread.join()
    if errors:
        raise errors[0]
