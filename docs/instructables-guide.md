# Build Your Own AI Smart Speaker With a Raspberry Pi 5 (Meet "Mango")

> **Notes for you before posting (delete this box):**
> - **Push the code first.** Readers download it from GitHub in Step 7. The repo link used below is `https://github.com/daltron3333/smart-speaker`, and it has to be public with the code pushed before you post.
> - **Add photos** wherever you see `[PHOTO: …]`. Instructables ranks guides with a photo on every step much higher.
> - **Licence for the wake word.** The Colab notebook says models trained with its sample data are for personal, non-commercial use. Sharing the "hey Mango" model for other people's home builds fits that, but don't sell kits that include it.
> - **Keep these out of photos and screenshots:** your Anthropic API key, your Wi-Fi password, your Pi password and the contents of `/etc/pi-speaker/env`.

---

## Intro

[PHOTO: the finished speaker, ideally next to the stuffed animal it's named after]

This is a voice assistant you build yourself on a Raspberry Pi 5. Say **"Hey Mango"**, ask a question, and it answers out loud in a second or two. It can tell you the time and date, set kitchen timers ("set a pasta timer for nine minutes"), and answer general questions the way a knowledgeable friend would.

Ours is named after my daughter's stuffed-animal dog, Mango, and answers with a little of his personality: cheerful and loyal, with the occasional "woof". You can give yours any name and personality you like (Step 13).

**How it works:**

```
microphone → wake word → records your question → speech-to-text → Claude AI → text-to-speech → speaker
             "Hey Mango"  stops when you stop     (on the Pi)       (text only)   (on the Pi)
```

- **Private by design.** Listening for the wake word, turning speech into text, and the speaking voice all run on the Pi. No audio ever leaves the device. Only the text of your question goes to the internet.
- **Fast.** On a Pi 5 it starts answering about 4 seconds after you stop talking. That includes the second of silence it waits for, to be sure you've finished.
- **Cheap to run.** The answers come from Anthropic's Claude Haiku model, which you pay for as you go. A question costs a small fraction of a cent.

**Time needed:** about 3 hours, mostly waiting on downloads and training. **Skill level:** beginner to intermediate. You'll copy and paste commands into a terminal, but you don't need to write any code.

---

## Supplies

[PHOTO: all the parts laid out]

**Hardware**
- **Raspberry Pi 5.** The 8 GB model is what we used; 4 GB should also work.
- **Official Raspberry Pi 27 W USB-C power supply.** Speech-to-text keeps the processor busy, and a weaker supply makes the Pi slow down or drop USB devices.
- **Raspberry Pi Active Cooler.** Stops the processor slowing itself down when it gets hot.
- **microSD card, 32 GB or larger,** rated A2 for speed.
- **microSD card reader** for your computer.
- **USB speakerphone.** We used a **Jabra SPEAK 410**. A speakerphone is ideal because it has a good microphone, a loud speaker and built-in echo cancellation in one box. Other USB speakerphones should work too.
- **Wi-Fi** (or an Ethernet cable).

**Software and accounts (all free to sign up)**
- A computer to set things up from. These steps use a Mac; notes for Windows are included where they differ.
- **Raspberry Pi Imager** (Step 2).
- **A Google account** for Google Colab, only if you want to train your own wake word (Steps 4–6).
- **An Anthropic account** for the Claude API, with a few dollars of credit (Step 8).

---

## Step 1: Assemble the Pi

[PHOTO: Active Cooler fitted to the Pi]

1. Peel the backing off the Active Cooler's thermal pads and press it onto the Pi 5. Push its two spring pins through the mounting holes until they click.
2. Plug the cooler's small fan cable into the **FAN** connector on the Pi.
3. Don't connect power yet. The microSD card goes in first (Step 3).

---

## Step 2: Make an SSH Key and Install Raspberry Pi Imager

[PHOTO or SCREENSHOT: Raspberry Pi Imager's first screen]

You'll control the Pi from your computer over **SSH**, so it doesn't need its own keyboard or screen. An SSH key lets your computer log in without typing a password each time.

**1. Make an SSH key (skip this if you already have one).** Open **Terminal** on a Mac (Cmd+Space, type "Terminal") or **PowerShell** on Windows, and run:

```bash
ssh-keygen -t ed25519
```

Press Enter at each question to accept the defaults. You can leave the passphrase empty or set one.

**2. Copy your public key to the clipboard.** You'll paste it into Imager in the next step.

Mac:
```bash
pbcopy < ~/.ssh/id_ed25519.pub
```

Windows (PowerShell):
```bash
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | Set-Clipboard
```

It's one long line starting with `ssh-ed25519`. This is the **public** half of the key, which is safe to share. Never share the file without `.pub` on the end.

**3. Install Raspberry Pi Imager** from [raspberrypi.com/software](https://www.raspberrypi.com/software/). On a Mac, open the `.dmg` and drag Imager into Applications.

---

## Step 3: Flash the microSD Card

[SCREENSHOT: Imager's OS menu with "Raspberry Pi OS (other)" highlighted]

Put the microSD card in your card reader, plug it into your computer, and open Raspberry Pi Imager.

**Choose what to write**
1. **Device:** Raspberry Pi 5.
2. **Operating system:** click **Raspberry Pi OS (other)**, then choose **Raspberry Pi OS Lite (64-bit)**. Its description says it has no desktop environment. Don't pick the top "Raspberry Pi OS (64-bit)" entry, which is the desktop version. The speaker doesn't need a desktop, and leaving it out frees up memory and processor time for speech.
3. **Storage:** your microSD card. **Check the size carefully, because Imager erases whatever you pick.**

**Customise the settings.** Imager then walks you through some settings (on some versions they're behind **Edit settings**). Fill them in like this:

| Setting | What to enter |
| --- | --- |
| **Hostname** | `mango` (or any name). The Pi will then be reachable as `mango.local`. |
| **Locale** | Your **time zone**. This matters: it's how the speaker knows the local time. |
| **Keyboard layout** | `us` is fine. It only matters if you ever plug a keyboard into the Pi. |
| **User** | A username and password of your choice. Write the username down; you'll need it to log in. |
| **Wi-Fi** | Your network name and password, and your country. |
| **SSH / Remote access** | Turn it on and choose **public-key authentication only**. Click **SHOW**, paste your key (Cmd+V or Ctrl+V), and check that "No SSH keys configured" changes to show one key. |
| **Raspberry Pi Connect** | Leave it **off**. We use SSH instead. |

[SCREENSHOT: the SSH key screen with a key added]

**Write the card**
1. Click **Write** and confirm. It erases the card, writes the system and checks it, which takes a few minutes. Your computer may ask for its password.
2. When it's done, eject the card and put it in the slot under the Pi.
3. Plug in the USB speakerphone, then the **27 W power supply last**.
4. Wait about 2 minutes. The first boot takes longer, because it's setting up Wi-Fi and SSH.

---

## Step 4: (Optional) Train Your Own Wake Word in Google Colab

[SCREENSHOT: the Colab notebook with target_word set]

**You can skip Steps 4–6** if you're happy saying "Hey Mango": the trained model is already included with the code. Do them if you want a different name, such as "Hey Biscuit".

The wake word is detected by **openWakeWord**, which can learn a new phrase from computer-generated speech. Training runs for free on Google's computers in **Google Colab** and takes about an hour, mostly waiting.

**1. Open the notebook.** Go to openWakeWord's [training notebook](https://colab.research.google.com/drive/1q1oe2zOyZp7UsB3jJiQ1IFn8z5YfjwEb?usp=sharing) and sign in with your Google account (top right). Choose **File → Save a copy in Drive** so you have your own editable copy, and work in that copy. If Colab warns that the notebook isn't from Google, choose **Run anyway**.

**2. Switch to an older runtime. Do this first, or the notebook fails.** Colab's newest runtime uses Python 3.13, and one of the notebook's speech packages (`piper-phonemize`) only installs on Python 3.12 or older. Without this step you get the error `ModuleNotFoundError: No module named 'piper_phonemize'`.
- Open **Runtime → Change runtime type**.
- Under **Runtime version**, choose **2026.01**, which has Python 3.12.
- Click **Save**.

You can check it worked by adding a code cell (**Insert → Code cell**) containing `!python --version` and clicking ▶. It should say Python 3.12.

> These fixes were needed in October 2026. Colab changes over time, so if the menus look different, pick whichever runtime version uses Python 3.12.

---

## Step 5: Check the Pronunciation, Then Train

[SCREENSHOT: the audio player with the test clip]

**1. Listen to a sample.** In section **1. Test Example Training Clip Generation**, type your phrase into the `target_word` box, for example `hey mango`. Click the ▶ button next to the section title. The first run installs things for about 5 minutes, then a short audio clip appears just above section 2. Play it.

If the name sounds wrong, try a phonetic spelling with underscores, such as `hey_man_go`, and run the section again.

**2. Start training.** Leave the settings in section **3. Train the Model** at their defaults (`number_of_examples` 1000, `number_of_training_steps` 10000). Choose **Runtime → Run all**.

**3. Fix the NumPy error if it appears.** Section 2 may fail with **"Numba needs NumPy 2.0 or less"**, because one install upgrades NumPy further than that runtime's Numba supports. To fix it:
- Add a code cell containing this line and click ▶:
  ```
  !pip install -q -U numba llvmlite
  ```
- Then choose **Runtime → Restart session and run all**.

**4. Ignore extra restart prompts.** After that one restart, if Colab keeps asking you to **restart the session**, click **Cancel**. The packages now match, and restarting again only starts the loop over.

**5. Wait.** Section 2 downloads background noise and music (about 15 minutes), then section 3 trains (about 40 minutes). Keep the tab open; you can do other things in the meantime.

> **Expected error:** one of the background-noise downloads (AudioSet) currently fails with a "404" error. That's fine: training carries on using the music clips as background noise.

---

## Step 6: Download the Wake Word Model

[SCREENSHOT: Colab's file browser showing my_custom_model]

When training finishes, your browser downloads the model automatically, usually to your Downloads folder. If nothing downloads, click the **folder icon** on Colab's left side, open `my_custom_model`, and download the **`.onnx`** file. You don't need the `.tflite` file.

The file is named after your phrase, for example `hey_biscuit.onnx`. Hold on to it; you'll add it to the code in Step 7.

**Tips:**
- Our "hey Mango" model scored about 0.88 on "hey mango", where 0.5 is enough to wake it, and ignored ordinary sentences, even "I bought a mango smoothie". The one near miss it reacts to is "hey man, go", which sounds almost the same.
- If it misses you in a noisy room or wakes up for the TV, retrain with more data. Before **Run all**, choose **Runtime → Change runtime type → T4 GPU**, then raise `number_of_examples` to 10,000–30,000 and `number_of_training_steps` to about 20,000.

---

## Step 7: Log In to the Pi and Download the Code

[SCREENSHOT: Terminal logged in to the Pi]

**1. Log in.** On your computer, open Terminal (or PowerShell) and run the following, using the username you chose in Imager in place of `yourname`:

```bash
ssh yourname@mango.local
```

The first time, it asks whether you trust this computer. Type `yes`. You're now typing commands on the Pi. The prompt changes to something like `yourname@mango:~ $`.

> **Mac tip:** if `mango.local` can't be found, make sure your Mac is on the same Wi-Fi as the Pi. If macOS asks whether Terminal may find devices on your local network, click **Allow**.

**2. Download the code** onto the Pi:

```bash
sudo apt-get install -y git
git clone https://github.com/daltron3333/smart-speaker.git ~/smart-speaker
```

When `sudo` asks for a password, type the Pi password you set in Imager. Nothing shows as you type; that's normal.

**3. (Optional) Add your own wake word from Step 6.** Copy the `.onnx` file into the code's `wakewords` folder. Run this on your computer, in a new Terminal window, not on the Pi:

```bash
scp ~/Downloads/hey_biscuit.onnx yourname@mango.local:~/smart-speaker/wakewords/
```

Then tell the speaker to use it in Step 9 with `SPEAKER_WAKE_MODEL=hey_biscuit`, which is the file's name without `.onnx`.

---

## Step 8: Get a Claude API Key

[SCREENSHOT: the Claude Console's API Keys page, with the key itself hidden]

The answers come from Claude, through Anthropic's API.

1. Sign up at [console.anthropic.com](https://console.anthropic.com).
2. Under **Settings → Billing**, add some credit. The API is pay-as-you-go and is billed separately from a Claude.ai subscription. A few dollars lasts a long time with the Haiku model.
3. Under **Settings → Limits**, set a **monthly spend limit**, so the cost can never surprise you.
4. Under **API Keys**, create a key and copy it. It starts with `sk-ant-`.

**Treat the key like a password.** Don't paste it into chats, emails, photos or the code. You'll put it in a protected file on the Pi in the next step.

---

## Step 9: Install the Speaker Software

[SCREENSHOT: the end of the setup script's output]

**1. Run the setup script** on the Pi (in your SSH window):

```bash
bash ~/smart-speaker/deploy/setup_pi.sh
```

It asks for your Pi password, then runs on its own for 10–20 minutes. It:
- installs the system and Python packages it needs,
- downloads the speech models (the wake word, the Whisper speech-to-text model and the Piper voice),
- creates a locked-down `speaker` user and a background service that starts when the Pi boots,
- creates a protected file for your API key, which only the administrator can read.

A warning about "unauthenticated requests" to Hugging Face is harmless. It ends with **"Almost done. Add your API key"**.

**2. Add your API key.** Open the key file:

```bash
sudo nano /etc/pi-speaker/env
```

Paste your key straight after the `=` on the first line, with no spaces or quotes, like `ANTHROPIC_API_KEY=sk-ant-...`. You can add settings on the lines below it. We used these two:

```
SPEAKER_WHISPER_MODEL=base.en
SPEAKER_SILENCE_S=0.7
```

The second one makes it answer a little sooner after you stop talking. If you trained your own wake word in Steps 4–6, also add a line like `SPEAKER_WAKE_MODEL=hey_biscuit`.

Save with **Ctrl+O**, then **Enter**, and exit with **Ctrl+X**.

**3. Start the speaker:**

```bash
sudo systemctl restart pi-speaker
```

---

## Step 10: Test Each Part

[PHOTO: someone talking to the speaker]

The setup installs a `speaker` command for testing each part on its own. While you test, it pauses the background service, because only one program can use the microphone at a time.

1. **Sound:** `speaker devices` should list your speakerphone. Then `speaker mic-test` records a few seconds and plays them back.
2. **Self-test:** `speaker self-test` has the speaker's own voice say the wake word and 20 test questions, and checks that the wake word, the end-of-question detection and speech-to-text all work. It prints PASS or FAIL for each part. On our Pi 5, speech-to-text was 96% accurate and took about 2 seconds per question.
3. **Wake word:** `speaker wake-test` beeps every time it hears "Hey Mango". Try it from across the room. Press Ctrl+C to stop.
4. **The brain:** `speaker type` lets you type questions and hear the answers. This checks your API key.

When you're done, start the service again:

```bash
sudo systemctl start pi-speaker
```

---

## Step 11: Talk to It!

[VIDEO: asking a few questions]

Say **"Hey Mango"**, wait for the short tone, then ask your question. Things to try:
- "What time is it?" or "What's the date today?"
- "Set a pasta timer for nine minutes." Then "How long is left?" and "Cancel it."
- "How far away is the moon?"
- "Bark for me!"
- Follow-ups such as "Who was the first person on the moon?" then "What year was that?" It remembers the last few questions for five minutes.

To see how fast it's answering, run `speaker report` on the Pi. Ours started speaking a median of **3.9 seconds** after we stopped talking: about 2 seconds for speech-to-text, under 1 second for Claude, and a fraction of a second to start speaking.

It starts by itself whenever the Pi powers up, so you can unplug the screen-less Pi, put it on a shelf and forget about it.

---

## Step 12: Tuning and Troubleshooting

Change settings by editing `/etc/pi-speaker/env` (`sudo nano /etc/pi-speaker/env`), then run `sudo systemctl restart pi-speaker`.

| Problem | Fix |
| --- | --- |
| It wakes up too easily (TV, conversation) | Add `SPEAKER_WAKE_THRESHOLD=0.6`, or higher |
| It doesn't hear the wake word | Lower it to `0.4`, or retrain on a GPU (Step 6 tips) |
| Answers are too slow | `SPEAKER_WHISPER_MODEL=tiny.en` is about 1 second faster but mishears more often |
| It cuts you off mid-question | Raise `SPEAKER_SILENCE_S` to `1.0` |
| It says it can't reach the internet | Check the Pi's Wi-Fi; it recovers by itself when the connection is back |
| It says the Claude account is out of credit | Top up at console.anthropic.com → Settings → Billing |
| No sound, or it can't hear you | Run `speaker devices`, then `alsamixer` (press F6 to pick the speakerphone) to check volume and mute |
| Something else | See the live log with `journalctl -u pi-speaker -f` |

**Notes from our build:**
- Sometimes the first word of a question gets clipped ("…time is it?") because the wake word triggers just after "Mango". Claude usually works out the meaning anyway. Pausing for the tone before speaking helps.
- The Jabra only plays audio at certain sample rates, so the software converts its voice to 48 kHz automatically. If you use a different speakerphone and get an "Invalid sample rate" error, please let me know in the comments.
- **Check heat** after 30 minutes of use with `vcgencmd get_throttled`. It should print `throttled=0x0`. Ours stayed below 75 °C with the Active Cooler.

---

## Step 13: Make It Your Own

The personality lives in one place: the `SYSTEM_PROMPT` at the top of `speaker/brain.py`. It's plain English instructions to Claude. Ours tells it that it's Mango, the family's stuffed-animal dog: helpful and accurate for adults first, with a doggy touch in about one answer in three, and happy to bark on request.

To change it, edit the file on the Pi, then rerun the setup script, which copies the code into place and restarts the service:

```bash
nano ~/smart-speaker/speaker/brain.py
bash ~/smart-speaker/deploy/setup_pi.sh
```

Ideas:
- Give it the name and personality of your own pet, toy or favourite character.
- Use `SPEAKER_MODEL=claude-sonnet-5-5` for harder questions. It's smarter, but slower and costs more.
- Add new skills, such as weather, as tools in `speaker/skills.py`.

---

## Privacy and Safety

- **Audio never leaves the Pi** and is never saved to disk. The wake word, speech-to-text and the voice all run locally.
- Nothing is sent anywhere until the wake word is heard, and then only the text of your question goes to Claude.
- Your API key sits in a file only the administrator can read. The speaker itself runs as a restricted user that can only write to its own log folder.
- Questions and answers (text only) are logged on the Pi so you can check timings. Turn this off with `SPEAKER_LOG_TEXT=false`.

Happy building! If you make one, post a photo of yours in the comments, and tell us who it's named after.
