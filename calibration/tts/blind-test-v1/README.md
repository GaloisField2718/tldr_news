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

Before mass generation, every selected model must also pass its canary gate. Proven contracts are Gemini Kore/Aoede as 24 kHz mono PCM, Mistral `en_paul_neutral` as 22.05 kHz mono MP3 (with `gb_jane_neutral` validated by current official voice metadata), and lowercase xAI `eve`/`rex` as 24 kHz mono MP3. A failed or missing required canary blocks the paid gate.

Fair generation performs exactly one HTTP attempt per turn: 24 logical requests, zero retries, and a hard 24-attempt ceiling. Gemini turns are stored as raw `.pcm` and decoded explicitly with `-f s16le -ar 24000 -ac 1`; Mistral and xAI turns remain `.mp3`. Every response validates immediately, then normalizes to 24 kHz mono PCM WAV for pause insertion and concatenation. Final anonymous MP3s are encoded at 128 kbps and published from hidden temporary names only after all 24 turns validate. Model/voice/request details remain only in private `tts-reveal.json` mode 0600. Audio and reveal files remain outside Git. FFmpeg applies no music, EQ, dynamics compression, gain adjustment, or cross-candidate loudness normalization.
