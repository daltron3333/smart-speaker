# Custom wake words

Put trained openWakeWord models here, named after the phrase: `hey_mango.onnx`.
The speaker loads `wakewords/<SPEAKER_WAKE_MODEL>.onnx` (default `hey_mango`) and
falls back to the built-in "hey Jarvis" until the file exists.

These files are small (a few hundred KB) and are committed with the code, so they
reach the Pi with everything else. See "Wake word" in the main README for training.
