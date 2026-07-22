# Daily Index podcast MVP

The completed blind calibration (private run `20260722T153542Z`) ranked candidate A, B, then C. The released result is:

| Candidate | Model | Host / analyst | Role |
|---|---|---|---|
| A | `x-ai/grok-voice-tts-1.0` | `eve` / `rex` | production default |
| B | `mistralai/voxtral-mini-tts-2603` | `en_paul_neutral` / `gb_jane_neutral` | episode-level fallback |
| C | `google/gemini-3.1-flash-tts-preview` | `Kore` / `Aoede` | not selected |

The fallback is disabled unless explicitly selected, or a complete default episode fails before publication. A published episode never mixes model or voice pairs.

`pipenv run python -m tools.tldr_podcast preflight --date YYYY-MM-DD` is zero-call. It selects a validated Daily artifact and reports the production contract. `generate --publish` remains fail-closed until an explicit paid authorization, a validated grounded script, and publication implementation are supplied. No podcast cron is active.

Published podcast artifacts will be committed below `generated/podcast/YYYY/YYYY-MM-DD.json`. Private provider diagnostics, request IDs, voice identifiers and costs never enter the public artifact.
