# Pi Smart Speaker

A voice assistant for a Raspberry Pi 5. The wake word, speech-to-text and text-to-speech all run
on the Pi; only the transcribed text goes to Claude Haiku 5.5 for the answer. This is the v1 build
of the PRD (*Pi Smart Speaker – Build Plan*, Oct 24 2026).

```
mic ─► openWakeWord ─► Silero VAD ─► faster-whisper ─► Claude Haiku 5.5 ─► Piper ─► speaker
       "hey Mango"     end of speech   base.en           (text only)         streamed
                                                         tools: time, timers  sentence by sentence
```

## Layout

| Path | What it is | PRD |
| --- | --- | --- |
| `speaker/wakeword.py` | openWakeWord with a custom "hey Mango" model from `wakewords/` | F1 |
| `speaker/hearing.py` | Records until 1 s of silence, 12 s cap; Silero VAD, loudness fallback | F2 |
| `speaker/stt.py` | faster-whisper `base.en`, int8, audio never written to disk | F3 |
| `speaker/brain.py` | Claude Haiku 5.5: short spoken answers, streaming, 5-minute memory | F4, F9 |
| `speaker/tts.py` | Piper `en_US-lessac-medium`, espeak-ng fallback | F5 |
| `speaker/skills.py` | Time and date, set/list/cancel timers | F6, F7 |
| `speaker/phrases.py` | What it says when things fail | F8 |
| `speaker/audio.py` | Jabra mic and speaker; mic is muted while it talks | — |
| `speaker/main.py` | One command per build phase, plus `listen` | F11 |
| `speaker/selftest.py` | Hands-free check of wake word, VAD and Whisper using Piper's voice | Testing |
| `deploy/` | systemd service, Pi setup script, `speaker` test command | F10 |
| `tools/test_questions.txt` | The fixed 20-question test script | Testing |

Volume by voice (F12) and weather (F13) were Could items and are left for v2.

## Try it on the Mac first

Typing mode needs no microphone. It uses the same brain and voice the Pi will use.

```bash
cd ~/Documents/pi-speaker
.venv/bin/pip install -r requirements.txt sounddevice piper-tts
.venv/bin/python -m speaker type           # type questions, hear answers
.venv/bin/python -m speaker type --silent  # print answers only
.venv/bin/python -m speaker type --script  # run all 20 test questions
.venv/bin/python -m unittest discover -s tests
```

For the voice, download Piper's model once: `.venv/bin/python -m piper.download_voices en_US-lessac-medium --data-dir models/piper`.

To try the listening side on the Mac too, install the rest and download the models (about 200 MB), then run the self-test:

```bash
.venv/bin/pip install faster-whisper onnxruntime scipy scikit-learn requests tqdm
.venv/bin/pip install --no-deps openwakeword
HF_HOME=$PWD/models/hf .venv/bin/python -m speaker setup-models
.venv/bin/python -m speaker self-test
```

## Your API key

Get a key at [console.anthropic.com](https://console.anthropic.com) under **API Keys**. While you're there, set a monthly spend limit under **Settings → Limits**. Keep the key out of chats, emails and the code.

**On the Mac**, put it in a file named `.env` in the project folder. Git ignores this file, and it is never copied to the Pi.

```bash
cd ~/Documents/pi-speaker
touch .env && chmod 600 .env
open -e .env
```

Add this one line, then save:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Every `python -m speaker ...` command reads it automatically.

**On the Pi**, the key goes in `/etc/pi-speaker/env`, which only root can read (see Phase 0). The service loads it at start-up.

## Wake word: training "Hey Mango"

"Hey Mango" isn't one of openWakeWord's built-in phrases, so it needs its own small model. Until `wakewords/hey_mango.onnx` exists, the speaker uses "hey Jarvis" and logs a warning, and `self-test` reports a FAIL for it.

1. Open openWakeWord's [training notebook on Google Colab](https://colab.research.google.com/drive/1q1oe2zOyZp7UsB3jJiQ1IFn8z5YfjwEb?usp=sharing) and sign in with a Google account. It's free.
2. Set the target phrase to `hey mango`. Before training, use the notebook's play button to check that its voice pronounces it right; if not, try a spelling like `hey man go`.
3. Run all the cells (**Runtime → Run all**). It generates thousands of synthetic "hey mango" clips and trains for about an hour. Leave the tab open.
4. Download the `.onnx` file it produces, rename it to `hey_mango.onnx`, and put it in this project's `wakewords/` folder.
5. Check it: `.venv/bin/python -m speaker self-test` should show PASS for "hey mango". On the Pi, run `speaker wake-test` and say it from across the room.

The model is a few hundred KB and is committed with the code, so it reaches the Pi with everything else. If it wakes too easily or misses you, adjust `SPEAKER_WAKE_THRESHOLD`. If it's still poor, retrain with the notebook's advanced version, which takes longer but makes a stronger model.

## Build on the Pi, phase by phase

### Phase 0: prepare the Pi

1. Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager. In its settings, turn on SSH and enter your Wi-Fi.
2. Fit the Active Cooler, use the 27 W supply, and plug in the Jabra.
3. Copy the code from the Mac to the Pi:
   ```bash
   rsync -av --exclude .venv --exclude .env --exclude models --exclude logs ~/Documents/pi-speaker/ pi@raspberrypi.local:~/smart-speaker/
   ```
   Once the code is pushed to GitHub, you can instead run `git clone https://github.com/daltron3333/smart-speaker.git ~/smart-speaker` on the Pi (`sudo apt-get install -y git` first).
4. Install it on the Pi:
   ```bash
   ssh pi@raspberrypi.local
   bash ~/smart-speaker/deploy/setup_pi.sh
   sudo nano /etc/pi-speaker/env        # set ANTHROPIC_API_KEY=...
   ```
   Change `pi@raspberrypi.local` to the user and host name you set in Imager. After a code change, copy it over again (or `git pull`) and rerun the setup script.
5. Check the hardware: `speaker devices` should list the Jabra. **Done when** `speaker mic-test` plays your voice back cleanly.
6. Run `speaker self-test`. Piper speaks the test questions and the real wake word, VAD and Whisper models listen, with no microphone involved. It prints PASS or FAIL for each stage, and Whisper's speed on the Pi. That speed is the PRD's biggest risk, so this tells you early whether you need `tiny.en`. On an Apple Silicon Mac, transcription took 0.23 s per question with 94% accuracy. Expect the Pi to be several times slower.

The `speaker` command runs any step with the service's settings. It stops the background service first, because only one program can use the mic at a time.

### Phase 1: ears

`speaker wake-test` plays a tone and logs each wake to `logs/wakes.jsonl`.
**Done when** 9 out of 10 tries wake it from 3 m. Then leave it running for a day with the TV on and count the false wakes.
If it wakes too easily, raise `SPEAKER_WAKE_THRESHOLD` (for example 0.6). If it misses you, lower it.

### Phase 2: hearing

`speaker hear-test --script` reads out each test question for you to say, then prints what Whisper heard, the word accuracy and the timings.
**Done when** accuracy is at least 90%. If transcription takes more than about 2 s, try `SPEAKER_WHISPER_MODEL=tiny.en`.
Use `--no-wake` to press Enter instead of saying "hey Mango" each time.

### Phase 3: voice

`speaker say "The moon is about three hundred eighty four thousand kilometers away."`
It prints how long synthesis took. Above a real-time factor of 1.0, speech is slower than real time.

### Phase 4: brain

Run `speaker type`, or `speaker type --script` for all 20 questions. **Done when** answers are short and sound natural.
Set a monthly spend limit at console.anthropic.com → Settings → Limits.

### Phase 5: full loop

`sudo systemctl start pi-speaker`, then say "hey Mango, …". Ask the 20 test questions out loud, then run `speaker report`.
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
| `ANTHROPIC_API_KEY` | — | Required. See "Your API key" above |
| `SPEAKER_MODEL` | `claude-haiku-5-5` | `claude-sonnet-5-5` for harder questions, at a higher cost |
| `SPEAKER_EFFORT` | `low` | `medium` thinks more, so answers are better but slower |
| `SPEAKER_THINKING` | `adaptive` | `off` can cut latency; compare with `speaker report` |
| `SPEAKER_WAKE_MODEL` | `hey_mango` | A file in `wakewords/` or a built-in name such as `hey_jarvis` |
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

Wake phrase: "hey Mango", a custom model (the PRD's default was the built-in "hey Jarvis"). Otherwise the PRD's suggested defaults: our own Python program rather than Home Assistant, a 4-second target with streaming built in, and weather as the next skill. Still to confirm on the hardware: the Pi's RAM (8 GB is comfortable; 4 GB works with `tiny.en`) and the Jabra model.

## Troubleshooting

- **No sound or no mic:** run `speaker devices`, then `alsamixer` (F6 picks the Jabra) to check levels and mute.
- **Logs:** `journalctl -u pi-speaker -f`. Per-turn timings are in `/opt/pi-speaker/logs/turns.jsonl`.
- **openWakeWord install errors:** the setup script installs it with `--no-deps` on purpose, to skip `tflite-runtime`.
- **Service can't write somewhere:** the service is sandboxed with `ProtectSystem=strict`; add the path to `ReadWritePaths` in the unit file.
