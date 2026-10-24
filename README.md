# Pi Smart Speaker

A voice assistant for a Raspberry Pi 5. The wake word, speech-to-text and text-to-speech all run
on the Pi; only the transcribed text goes to Claude Haiku 5.5 for the answer. This is the v1 build
of the PRD (*Pi Smart Speaker – Build Plan*, Oct 24 2026).

```
mic ─► openWakeWord ─► Silero VAD ─► faster-whisper ─► Claude Haiku 5.5 ─► Piper ─► speaker
       "hey Jarvis"    end of speech   base.en           (text only)         streamed
                                                         tools: time, timers  sentence by sentence
```

## Layout

| Path | What it is | PRD |
| --- | --- | --- |
| `speaker/wakeword.py` | openWakeWord, built-in "hey Jarvis" | F1 |
| `speaker/hearing.py` | Records until 1 s of silence, 12 s cap; Silero VAD, loudness fallback | F2 |
| `speaker/stt.py` | faster-whisper `base.en`, int8, audio never written to disk | F3 |
| `speaker/brain.py` | Claude Haiku 5.5: short spoken answers, streaming, 5-minute memory | F4, F9 |
| `speaker/tts.py` | Piper `en_US-lessac-medium`, espeak-ng fallback | F5 |
| `speaker/skills.py` | Time and date, set/list/cancel timers | F6, F7 |
| `speaker/phrases.py` | What it says when things fail | F8 |
| `speaker/audio.py` | Jabra mic and speaker; mic is muted while it talks | — |
| `speaker/main.py` | One command per build phase, plus `listen` | F11 |
| `deploy/` | systemd service, Pi setup script, `speaker` test command | F10 |
| `tools/test_questions.txt` | The fixed 20-question test script | Testing |

Volume by voice (F12) and weather (F13) were Could items and are left for v2.

## Try it on the Mac first

Typing mode needs no microphone. It uses the same brain and voice the Pi will use.

```bash
cd ~/Documents/pi-speaker
.venv/bin/pip install -r requirements.txt sounddevice piper-tts
export ANTHROPIC_API_KEY=sk-ant-...        # from console.anthropic.com
.venv/bin/python -m speaker type           # type questions, hear answers
.venv/bin/python -m speaker type --silent  # print answers only
.venv/bin/python -m speaker type --script  # run all 20 test questions
.venv/bin/python -m unittest discover -s tests
```

The Piper voice goes in `models/piper/` (`.venv/bin/python -m piper.download_voices en_US-lessac-medium --data-dir models/piper`).

## Build on the Pi, phase by phase

### Phase 0: prepare the Pi

1. Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager. In its settings, turn on SSH and enter your Wi-Fi.
2. Fit the Active Cooler, use the 27 W supply, and plug in the Jabra.
3. Copy the project over and install it:
   ```bash
   rsync -av --exclude .venv --exclude models --exclude logs ~/Documents/pi-speaker/ pi@raspberrypi.local:~/pi-speaker/
   ssh pi@raspberrypi.local
   bash ~/pi-speaker/deploy/setup_pi.sh
   sudo nano /etc/pi-speaker/env        # set ANTHROPIC_API_KEY=...
   ```
   Change `pi@raspberrypi.local` to the user and host name you set in Imager. Run the same two commands again after any code change.
4. Check the hardware: `speaker devices` should list the Jabra. **Done when** `speaker mic-test` plays your voice back cleanly.

The `speaker` command runs any step with the service's settings. It stops the background service first, because only one program can use the mic at a time.

### Phase 1: ears

`speaker wake-test` plays a tone and logs each wake to `logs/wakes.jsonl`.
**Done when** 9 out of 10 tries wake it from 3 m. Then leave it running for a day with the TV on and count the false wakes.
If it wakes too easily, raise `SPEAKER_WAKE_THRESHOLD` (for example 0.6). If it misses you, lower it.

### Phase 2: hearing

`speaker hear-test --script` reads out each test question for you to say, then prints what Whisper heard, the word accuracy and the timings.
**Done when** accuracy is at least 90%. If transcription takes more than about 2 s, try `SPEAKER_WHISPER_MODEL=tiny.en`.
Use `--no-wake` to press Enter instead of saying "hey Jarvis" each time.

### Phase 3: voice

`speaker say "The moon is about three hundred eighty four thousand kilometers away."`
It prints how long synthesis took. Above a real-time factor of 1.0, speech is slower than real time.

### Phase 4: brain

Run `speaker type`, or `speaker type --script` for all 20 questions. **Done when** answers are short and sound natural.
Set a monthly spend limit at console.anthropic.com → Settings → Limits.

### Phase 5: full loop

`sudo systemctl start pi-speaker`, then say "hey Jarvis, …". Ask the 20 test questions out loud, then run `speaker report`.
**Done when** the median `first_audio_s` is under 4 s. This time runs from the end of your question to the first sound of the answer, and it includes the 1-second silence wait.
Replies are already streamed: the first sentence is spoken while the rest is still arriving. If it's still slow, `speaker report` shows which stage is the slow one.

### Phase 6: skills

"What time is it?", "Set a pasta timer for nine minutes", "How long is left?", "Cancel it." **Done when** "set a 10 second timer" rings and announces on time.

### Phase 7: hardening

The service already starts on boot, restarts 3 s after any crash, never stops retrying, and speaks a clear error when Wi-Fi or the API fails.
- Reboot test: `sudo reboot`. You should hear the start-up tone when it is ready.
- Wi-Fi test: turn the router off, ask a question and hear "I can't reach the internet". Turn it back on and ask again.
- Soak test: leave it running for a week, then check `journalctl -u pi-speaker --since "7 days ago" | grep -c "Started Pi smart speaker"` (restarts) and `speaker report`.
- Heat: `vcgencmd get_throttled` should print `throttled=0x0` after 30 minutes of use.

## Settings

Put overrides in `/etc/pi-speaker/env` on the Pi (or export them on the Mac), then run `sudo systemctl restart pi-speaker`.

| Variable | Default | Notes |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | — | Required |
| `SPEAKER_MODEL` | `claude-haiku-5-5` | `claude-sonnet-5-5` for harder questions, at a higher cost |
| `SPEAKER_EFFORT` | `low` | `medium` thinks more, so answers are better but slower |
| `SPEAKER_THINKING` | `adaptive` | `off` can cut latency; compare with `speaker report` |
| `SPEAKER_WAKE_THRESHOLD` | `0.5` | Higher means fewer false wakes |
| `SPEAKER_SILENCE_S` | `1.0` | Pause that ends a question |
| `SPEAKER_MAX_RECORD_S` | `12` | Recording cap |
| `SPEAKER_WHISPER_MODEL` | `base.en` | `tiny.en` is faster but less accurate |
| `SPEAKER_HISTORY_TURNS` | `4` | Exchanges kept for follow-up questions |
| `SPEAKER_HISTORY_TIMEOUT_S` | `300` | Forgets the conversation after this much quiet |
| `SPEAKER_AUDIO_DEVICE` | `Jabra` | Part of the device name; empty means the system default |
| `SPEAKER_LOG_TEXT` | `true` | Log transcripts and replies locally (never audio) |

## Privacy and security

- Audio stays in memory and is never written to disk. Whisper runs on the Pi.
- Nothing is sent until the wake word fires; after that, only the transcript goes out. Models are downloaded at setup, and the service runs with `HF_HUB_OFFLINE=1`, so it makes no network calls while idle.
- The API key lives in `/etc/pi-speaker/env`, which is owned by root with mode 600. systemd reads it before switching to the unprivileged `speaker` user, which can only write to `/opt/pi-speaker/logs`.

## Decisions taken (the PRD's open questions)

The PRD's suggested defaults: "hey Jarvis", our own Python program rather than Home Assistant, a 4-second target with streaming built in, and weather as the next skill. Still to confirm on the hardware: the Pi's RAM (8 GB is comfortable; 4 GB works with `tiny.en`) and the Jabra model.

## Troubleshooting

- **No sound or no mic:** run `speaker devices`, then `alsamixer` (F6 picks the Jabra) to check levels and mute.
- **Logs:** `journalctl -u pi-speaker -f`. Per-turn timings are in `/opt/pi-speaker/logs/turns.jsonl`.
- **openWakeWord install errors:** the setup script installs it with `--no-deps` on purpose, to skip `tflite-runtime`.
- **Service can't write somewhere:** the service is sandboxed with `ProtectSystem=strict`; add the path to `ReadWritePaths` in the unit file.
