# Blind TTS calibration v1

This is an isolated calibration harness, not a podcast pipeline. `dialogue.json` is the immutable factual test script and `evaluation.md` is the blind review form. Production editorial artifacts, frontend data, R2, cron, and deployment are outside its write surface.

Runtime model availability and pricing come from `GET /api/v1/models?output_modalities=speech`. The fair set requires current Gemini Flash TTS, Voxtral Mini TTS, and the first valid model in the documented challenger order. Voice pairs are restricted to a versioned registry grounded in the linked current official OpenRouter model pages and validated before request construction. Preflight blocks paid generation unless all three models remain speech-capable, priced, large enough for every turn, and have two distinct English voices.

```bash
python -m tools.tldr_tts_calibration preflight \
  --output /home/galois/tldr-tts-calibration/<timestamp>
```

After an explicit authorization only, the identical clean checkout may run:

```bash
python -m tools.tldr_tts_calibration generate \
  --authorize-paid \
  --output /home/galois/tldr-tts-calibration/<timestamp>
```

The non-ranked Gemini native-dialogue bonus is currently disabled. OpenRouter documents generic provider options but does not document the nested Gemini `multi_speaker_voice_config` payload for `/audio/speech`; the harness will not fabricate that passthrough contract.

Before mass generation, every selected model must also have a successful minimal canary recording its proven voice case, requested format, MIME type, codec, sample rate, and channels. A failed or missing canary blocks the paid gate.

Generation performs one request per turn, permits at most one bounded retry per turn, creates anonymous MP3 files, and stores model/voice/request details only in private `tts-reveal.json` mode 0600. Audio and reveal files remain outside Git. FFmpeg applies only sample-rate/channel normalization, pause insertion, concatenation, and metadata removal; it applies no music, EQ, compression, or cross-candidate loudness normalization.
