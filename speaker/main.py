"""Command line entry point. Each build phase has its own command, so each stage can be
tested alone before the full loop (see README.md).

    python -m speaker devices        list audio devices
    python -m speaker mic-test       Phase 0: record 3 s, play it back
    python -m speaker wake-test      Phase 1: tone on every wake, logged
    python -m speaker hear-test      Phase 2: record and transcribe, scored against the script
    python -m speaker say "Hello"    Phase 3: speak typed text
    python -m speaker type           Phase 4: typed question in, spoken answer out (F11)
    python -m speaker listen         Phase 5+: the whole speaker
    python -m speaker report         timing summary from logs/turns.jsonl
    python -m speaker self-test      wake word, VAD and Whisper checked with generated speech
    python -m speaker setup-models   download every model (run once, needs internet)
"""

from __future__ import annotations

import argparse
import itertools
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Iterable, Iterator

from speaker import phrases, turnlog
from speaker.config import Settings, load_env_file

log = logging.getLogger("speaker")

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SCRIPT = PROJECT_DIR / "tools" / "test_questions.txt"


class TimedTTS:
    """Wraps a TTS engine and remembers how long each synthesis took."""

    def __init__(self, tts):
        self.tts = tts
        self.durations: list[float] = []

    def synthesize(self, text: str):
        start = time.monotonic()
        clip = self.tts.synthesize(text)
        self.durations.append(time.monotonic() - start)
        return clip


def _mark_first(sentences: Iterable[str], marks: dict, key: str) -> Iterator[str]:
    for sentence in sentences:
        marks.setdefault(key, time.monotonic())
        yield sentence


def _echo(sentences: Iterable[str]) -> Iterator[str]:
    for sentence in sentences:
        print(f"  speaker> {sentence}", flush=True)
        yield sentence


def _round(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds, 2)


# ---------------------------------------------------------------- Phase 0


def cmd_devices(settings: Settings, args) -> None:
    from speaker.audio import list_devices

    print(list_devices())


def cmd_mic_test(settings: Settings, args) -> None:
    import numpy as np

    from speaker.audio import SAMPLE_RATE, Microphone, Speaker

    speaker = Speaker(settings.audio_device)
    mic = Microphone(settings.audio_device, speaker.muted)
    mic.start()
    print(f"Recording {args.seconds:.0f} seconds... say something.")
    frames, end = [], time.monotonic() + args.seconds
    while time.monotonic() < end:
        frame = mic.read()
        if frame is not None:
            frames.append(frame)
    mic.close()
    audio = np.concatenate(frames)
    peak = int(np.abs(audio).max())
    print(f"Got {len(audio) / SAMPLE_RATE:.1f} s, peak level {peak} of 32767. Playing it back.")
    if peak < 1000:
        print("That's very quiet. Check the Jabra's mute button and `alsamixer`.")
    speaker.play(audio, SAMPLE_RATE)


# ---------------------------------------------------------------- Phase 1


def cmd_wake_test(settings: Settings, args) -> None:
    from speaker.audio import Microphone, Speaker
    from speaker.wakeword import WakeWord

    speaker = Speaker(settings.audio_device)
    mic = Microphone(settings.audio_device, speaker.muted)
    wake = WakeWord(settings)
    mic.start()
    wakes = 0
    print(f"Say '{wake.phrase}'. Threshold {settings.wake_threshold}. Ctrl-C to stop.")
    try:
        while True:
            frame = mic.read()
            if frame is None:
                continue
            score = wake.heard(frame)
            if score is None:
                continue
            wakes += 1
            print(f"{time.strftime('%H:%M:%S')}  wake #{wakes}  score {score:.2f}", flush=True)
            turnlog.write(settings.log_dir / "wakes.jsonl", {"score": round(score, 3)})
            speaker.listening_tone()
            mic.flush()
            wake.reset()
    except KeyboardInterrupt:
        print(f"\n{wakes} wakes.")


# ---------------------------------------------------------------- Phase 2


def cmd_hear_test(settings: Settings, args) -> None:
    import statistics

    from speaker.audio import Microphone, Speaker
    from speaker.evaluate import load_script, word_accuracy
    from speaker.hearing import make_detector, record_question
    from speaker.stt import Transcriber

    speaker = Speaker(settings.audio_device)
    mic = Microphone(settings.audio_device, speaker.muted)
    detector = make_detector(settings)
    print(f"Loading Whisper {settings.whisper_model}; end of speech by {detector.name}.")
    stt = Transcriber(settings)
    stt.warm_up()
    wake = None
    if not args.no_wake:
        from speaker.wakeword import WakeWord

        wake = WakeWord(settings)
    script = load_script(Path(args.script)) if args.script else []
    mic.start()

    def capture():
        if wake:
            print(f"  (say '{wake.phrase}' first)", flush=True)
            while True:
                frame = mic.read()
                if frame is not None and wake.heard(frame) is not None:
                    break
        else:
            input("  (press Enter, then speak)")
        speaker.listening_tone()
        mic.flush()
        started = time.monotonic()
        audio = record_question(mic, detector, settings)
        recorded = time.monotonic()
        text = stt.transcribe(audio) if audio is not None else ""
        done = time.monotonic()
        if wake:
            wake.reset()
        return text, recorded - started, done - recorded

    accuracies, stt_times = [], []
    try:
        for index, (question, note) in enumerate(script or itertools.repeat(("", "")), 1):
            if question:
                print(f"\n[{index}/{len(script)}] Say: {question}" + (f"   ({note})" if note else ""))
            text, record_s, stt_s = capture()
            stt_times.append(stt_s)
            line = f"  heard: {text or '(nothing)'}\n  recording {record_s:.1f} s, transcription {stt_s:.2f} s"
            record = {"heard": text, "record_s": _round(record_s), "stt_s": _round(stt_s)}
            if question:
                accuracy = word_accuracy(question, text)
                accuracies.append(accuracy)
                line += f", word accuracy {accuracy:.0%}"
                record.update(expected=question, accuracy=round(accuracy, 3))
            print(line, flush=True)
            turnlog.write(settings.log_dir / "transcripts.jsonl", record)
    except KeyboardInterrupt:
        print()
    if stt_times:
        print(f"\nMedian transcription time {statistics.median(stt_times):.2f} s over {len(stt_times)} phrases.")
    if accuracies:
        print(f"Word accuracy {statistics.mean(accuracies):.0%} (target 90%).")


# ---------------------------------------------------------------- Phase 3


def cmd_say(settings: Settings, args) -> None:
    from speaker.audio import Speaker
    from speaker.tts import load_tts

    tts = load_tts(settings)
    text = " ".join(args.text)
    start = time.monotonic()
    clip = tts.synthesize(text)
    took = time.monotonic() - start
    if clip is None:
        print("Nothing to say.")
        return
    samples, rate = clip
    length = len(samples) / rate
    print(f"{tts.name}: {took:.2f} s to make {length:.2f} s of speech (real-time factor {took / length:.2f}).")
    Speaker(settings.audio_device).play(samples, rate)


# ---------------------------------------------------------------- Phase 4 (typing mode)


def _build_brain(settings: Settings, announce: Callable[[str], None]):
    from speaker.brain import Brain
    from speaker.skills import Skills, Timers

    return Brain(settings, Skills(Timers(on_done=announce)))


def cmd_type(settings: Settings, args) -> None:
    from speaker.evaluate import load_script

    speaker = tts = None
    if not args.silent:
        try:
            from speaker.audio import Speaker, speak_sentences
            from speaker.tts import load_tts

            tts = TimedTTS(load_tts(settings))
            speaker = Speaker(settings.audio_device)
        except Exception as e:
            print(f"No voice available ({e}); printing replies instead.")
            speaker = tts = None

    def announce(text: str) -> None:
        print(f"\n  speaker> \a{text}\nyou> ", end="", flush=True)
        if speaker:
            speaker.alarm()
            speak_sentences([text], tts, speaker)

    brain = _build_brain(settings, announce)
    questions = [q for q, _ in load_script(Path(args.script))] if args.script else None
    print(f"Typing mode with {settings.model} (effort {settings.effort}). Empty line or Ctrl-D to quit.")

    def turns() -> Iterator[str]:
        if questions is not None:
            for q in questions:
                print(f"you> {q}")
                yield q
            return
        while True:
            try:
                q = input("you> ").strip()
            except EOFError:
                return
            if not q:
                return
            yield q

    try:
        for question in turns():
            marks: dict[str, float] = {}
            start = time.monotonic()
            sentences = _echo(_mark_first(brain.reply(question), marks, "first_sentence"))
            if speaker:
                tts.durations.clear()
                speak_sentences(
                    sentences,
                    tts,
                    speaker,
                    on_first_audio=lambda: marks.setdefault("first_audio", time.monotonic()),
                )
            else:
                for _ in sentences:  # printing happens in _echo
                    pass
            end = time.monotonic()
            record = {
                "mode": "type",
                "claude_first_s": _round(marks["first_sentence"] - start) if "first_sentence" in marks else None,
                "tts_first_s": _round(tts.durations[0]) if speaker and tts.durations else None,
                "first_audio_s": _round(marks["first_audio"] - start) if "first_audio" in marks else None,
                "total_s": _round(end - start),
            }
            if settings.log_text:
                record.update(question=question)
            turnlog.write(settings.log_dir / "turns.jsonl", record)
    except KeyboardInterrupt:
        print()


# ---------------------------------------------------------------- Phase 5+ (the whole speaker)


def cmd_listen(settings: Settings, args) -> None:
    from speaker.audio import Microphone, Speaker, speak_sentences
    from speaker.hearing import make_detector
    from speaker.stt import Transcriber
    from speaker.tts import load_tts
    from speaker.wakeword import WakeWord

    speaker = Speaker(settings.audio_device)
    mic = Microphone(settings.audio_device, speaker.muted)
    tts = TimedTTS(load_tts(settings))
    log.info("voice: %s", tts.tts.name)

    def say(text: str) -> None:
        speak_sentences([text], tts, speaker)

    def announce(text: str) -> None:
        speaker.alarm()
        say(text)

    brain = _build_brain(settings, announce)
    wake = WakeWord(settings)
    detector = make_detector(settings)
    log.info("end of speech: %s; loading Whisper %s", detector.name, settings.whisper_model)
    stt = Transcriber(settings)
    stt.warm_up()

    mic.start()
    speaker.listening_tone()  # audible sign that it has finished starting up
    log.info("listening for %r", wake.phrase)
    missed_reads = 0
    while True:
        frame = mic.read()
        if frame is None:
            # The mic stops delivering audio if the Jabra is unplugged. Exit so systemd restarts us.
            if not speaker.muted.is_set():
                missed_reads += 1
                if missed_reads >= 10:
                    raise RuntimeError("no audio from the microphone for 10 seconds")
            continue
        missed_reads = 0
        score = wake.heard(frame)
        if score is None:
            continue
        log.info("wake (score %.2f)", score)
        try:
            _one_turn(settings, mic, speaker, tts, brain, detector, stt, say)
        except Exception:
            log.exception("turn failed")
            try:
                say(phrases.SOMETHING_WRONG)
            except Exception:
                log.exception("could not even say that")
        mic.flush()
        wake.reset()


def _one_turn(settings, mic, speaker, tts, brain, detector, stt, say) -> None:
    from speaker.audio import speak_sentences
    from speaker.hearing import record_question

    speaker.listening_tone()
    mic.flush()
    started = time.monotonic()
    audio = record_question(mic, detector, settings)
    recorded = time.monotonic()
    if audio is None:
        log.info("nobody spoke after the wake word")
        speaker.cancel_tone()
        return
    text = stt.transcribe(audio)
    transcribed = time.monotonic()
    del audio  # never kept past this point
    record = {
        "mode": "listen",
        "record_s": _round(recorded - started),
        "stt_s": _round(transcribed - recorded),
    }
    if not text:
        say(phrases.DIDNT_CATCH)
        turnlog.write(settings.log_dir / "turns.jsonl", {**record, "error": "empty transcript"})
        return
    log.info("heard: %s", text)

    marks: dict[str, float] = {}
    tts.durations.clear()
    spoken: list[str] = []

    def collect(sentences):
        for s in sentences:
            spoken.append(s)
            yield s

    speak_sentences(
        collect(_mark_first(brain.reply(text), marks, "first_sentence")),
        tts,
        speaker,
        on_first_audio=lambda: marks.setdefault("first_audio", time.monotonic()),
    )
    done = time.monotonic()
    # The question really ended `silence_s` before recording stopped, so that wait counts too.
    end_of_speech = recorded - settings.silence_s
    record.update(
        claude_first_s=_round(marks["first_sentence"] - transcribed) if "first_sentence" in marks else None,
        tts_first_s=_round(tts.durations[0]) if tts.durations else None,
        first_audio_s=_round(marks["first_audio"] - end_of_speech) if "first_audio" in marks else None,
        total_s=_round(done - end_of_speech),
    )
    if settings.log_text:
        record.update(heard=text, reply=" ".join(spoken))
    turnlog.write(settings.log_dir / "turns.jsonl", record)


# ---------------------------------------------------------------- Utilities


def cmd_report(settings: Settings, args) -> None:
    path = settings.log_dir / "turns.jsonl"
    if not path.exists():
        print(f"No log yet at {path}.")
        return
    print(turnlog.summarize(path, field=args.field, last=args.last))


def cmd_self_test(settings: Settings, args) -> None:
    from speaker import selftest

    if not selftest.run(settings, Path(args.script)):
        sys.exit(1)


def cmd_setup_models(settings: Settings, args) -> None:
    from speaker.hearing import SileroDetector
    from speaker.stt import Transcriber
    from speaker.wakeword import download_models

    print("Wake word and VAD models...")
    download_models(settings)
    SileroDetector(settings.vad_threshold)
    print(f"Whisper {settings.whisper_model}...")
    Transcriber(settings)
    print(f"Piper voice {settings.piper_voice}...")
    voice_dir = settings.piper_voice_path.parent
    voice_dir.mkdir(parents=True, exist_ok=True)
    if not settings.piper_voice_path.exists():
        subprocess.run(
            [sys.executable, "-m", "piper.download_voices", settings.piper_voice, "--data-dir", str(voice_dir)],
            check=True,
        )
    print(f"All models ready in {settings.model_dir}.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="speaker", description="Pi smart speaker")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging (before the command)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("devices", help="list audio devices").set_defaults(func=cmd_devices)
    p = sub.add_parser("mic-test", help="Phase 0: record and play back")
    p.add_argument("--seconds", type=float, default=3.0)
    p.set_defaults(func=cmd_mic_test)
    sub.add_parser("wake-test", help="Phase 1: wake word only").set_defaults(func=cmd_wake_test)
    p = sub.add_parser("hear-test", help="Phase 2: record and transcribe")
    p.add_argument("--script", nargs="?", const=str(DEFAULT_SCRIPT), help="score against the test questions")
    p.add_argument("--no-wake", action="store_true", help="press Enter instead of saying the wake phrase")
    p.set_defaults(func=cmd_hear_test)
    p = sub.add_parser("say", help="Phase 3: speak text")
    p.add_argument("text", nargs="+")
    p.set_defaults(func=cmd_say)
    p = sub.add_parser("type", help="Phase 4: typing mode")
    p.add_argument("--silent", action="store_true", help="print replies instead of speaking them")
    p.add_argument("--script", nargs="?", const=str(DEFAULT_SCRIPT), help="run the test questions")
    p.set_defaults(func=cmd_type)
    sub.add_parser("listen", help="the whole speaker").set_defaults(func=cmd_listen)
    p = sub.add_parser("report", help="timing summary")
    p.add_argument("--field", default="first_audio_s")
    p.add_argument("--last", type=int, help="only the last N turns")
    p.set_defaults(func=cmd_report)
    p = sub.add_parser("self-test", help="check wake word, VAD and Whisper with generated speech")
    p.add_argument("--script", default=str(DEFAULT_SCRIPT))
    p.set_defaults(func=cmd_self_test)
    sub.add_parser("setup-models", help="download all models").set_defaults(func=cmd_setup_models)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for noisy in ("httpx", "httpx2", "anthropic", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    load_env_file(PROJECT_DIR / ".env")
    args.func(Settings.from_env(), args)
