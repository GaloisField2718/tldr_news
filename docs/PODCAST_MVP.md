# Daily Index podcast MVP

The completed blind calibration (private run `20260722T153542Z`) ranked candidate A, B, then C. The released result is:

| Candidate | Model | Host / analyst | Role |
|---|---|---|---|
| A | `x-ai/grok-voice-tts-1.0` | `eve` / `rex` | production default |
| B | `mistralai/voxtral-mini-tts-2603` | `en_paul_neutral` / `gb_jane_neutral` | episode-level fallback |
| C | `google/gemini-3.1-flash-tts-preview` | `Kore` / `Aoede` | not selected |

The fallback is disabled unless explicitly selected, or a complete default episode fails before publication. A published episode never mixes model or voice pairs.

`pipenv run python -m tools.tldr_podcast preflight --date YYYY-MM-DD` is zero-call. `generate --date YYYY-MM-DD --authorize-paid` writes only a private, resumable runtime package and never uploads. `publish --date YYYY-MM-DD --accept --authorize-publish` requires a human acceptance flag, a complete validated private MP3, and verified immutable R2 publication before it atomically writes the public artifact. Production runs the idempotent `scripts/run_podcast_daily.sh` scheduler at 01:30, 03:30, and 06:30 UTC; missing source dates and already-published dates are clean no-ops.

Published podcast artifacts will be committed below `generated/podcast/YYYY/YYYY-MM-DD.json`. Private provider diagnostics, request IDs, voice identifiers and costs never enter the public artifact.
