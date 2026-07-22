# Illustration prompt calibration lab

This lab compares immutable prompt profiles against one already validated Daily visual brief. It is isolated from normal publication: it never calls the editorial model, writes official editorial JSON, or uploads to R2. Production remains pinned to `baseline-v1` and the current `ILLUSTRATION_PROMPT_VERSION` until a separate winner-locking change is reviewed.

Profiles are registered declaratively in `tools/tldr_editorial/illustration_prompts.py`. The calibration engine, safety policy, normalizer, gallery, and scoring format do not contain a profile count or list. Adding a direction requires registering another immutable profile; callers still explicitly choose profiles and cap the candidate count.

## Profiles available initially

- `baseline-v1`: byte-for-byte production direction.
- `print-graphic-v1`: restricted-palette print/relief graphic.
- `object-study-v1`: restrained, physically plausible object study.
- `constructed-collage-v1`: tactile cut-paper editorial construction.
- `ink-gouache-v1`: reduced ink and opaque-gouache drawing.
- `cinematic-editorial-v1`: coherent, source-grounded cinematic framing and atmosphere.

Only factual and safety restrictions are shared: no visible text, logos/trademarks, fabricated evidence, interfaces/screenshots, or imitation of named/living artists. Photorealism, concept art, detail, gradients, surfaces, and other aesthetic choices are profile-specific.

## Safe usage

Planning mode writes blind experiment files but makes zero network calls:

```bash
python -m tools.tldr_editorial calibrate-images \
  --date 2026-07-21 \
  --profiles baseline-v1,print-graphic-v1,object-study-v1,constructed-collage-v1,ink-gouache-v1,cinematic-editorial-v1 \
  --output-dir /home/galois/tldr-image-calibration/round-1 \
  --samples-per-profile 2 --max-images 12
```

A live run is accepted only with both explicit acknowledgements:

```bash
python -m tools.tldr_editorial calibrate-images \
  --date 2026-07-21 \
  --profiles baseline-v1,print-graphic-v1,object-study-v1,constructed-collage-v1,ink-gouache-v1,cinematic-editorial-v1 \
  --output-dir /home/galois/tldr-image-calibration/round-1 \
  --samples-per-profile 2 \
  --require-live --acknowledge-cost --max-images 12
```

The output must be absolute, outside Git, non-symlinked, and empty. The checkout must be clean. CI live runs are forbidden. `--samples-per-profile` defaults to one and accepts one through five; the explicit `--max-images` ceiling applies to profiles multiplied by samples. Repeated samples receive independent anonymous IDs while using identical prompts and source facts. No candidate is automatically retried; after one failure, it and all unattempted candidates are recorded and paid calls stop.

Outputs are `manifest.json`, private `blind-map.json`, `gallery.html`, `score-template.json`, and (live only) normalized anonymous WebPs. The gallery works through `file://`, randomizes anonymous candidates, uses identical framing, repeats identical source facts, and never includes profile IDs. Keep `blind-map.json` private until scoring is complete.

## Human scoring rubric

Score every criterion from 1 (poor) to 5 (excellent):

| Weight | Criterion |
|---:|---|
| 30% | Absence of obvious AI visual clichés |
| 20% | Sense of intentional editorial authorship |
| 15% | Factual grounding and absence of invented detail |
| 15% | Composition and immediate readability |
| 10% | Fit with the TLDR Index newspaper design |
| 10% | Readability at column/social-card size |

Hard reject visible text/malformed lettering, logos/trademarks, invented evidence, generic neon/circuit-board/futuristic imagery, stock 3D-render aesthetics, incoherent geometry, unusable crops, or severe artifacts.

For each image also record a one-sentence first impression, strongest quality, strongest weakness, whether it feels human-directed, and whether it should advance. Human judgment is authoritative; this version does not ask another model to score aesthetics.

## Two-round protocol (documented, not executed here)

### Round 1

Use the existing AMD Helios visual brief. Generate two independent anonymous samples for each of the six initial profiles, rank blindly on both quality and consistency, and retain two profiles. Both samples for a profile use the exact same prompt and facts. This is twelve paid image calls and zero editorial calls.

### Round 2

Select two additional validated briefs with different visual problems: one abstract software/model story and one human, organizational, or economic technology story. Generate both finalists against both briefs, then rank blindly. This is four paid image calls and zero editorial calls.

The initial repeated-sampling experiment therefore uses sixteen image calls total, zero editorial calls, no R2 uploads, and no official artifact mutation. Registry growth or sampling changes the total only when the operator explicitly selects profiles, chooses a sample count, and raises `--max-images`. A winner must perform well across all three story types; the AMD result alone cannot select production direction.

## Later winner lock (not part of calibration)

After human selection, a separate PR must:

1. register the winner as `production-v2`;
2. increment `ILLUSTRATION_PROMPT_VERSION`;
3. update prompt-hash tests;
4. merge through normal CI;
5. perform one controlled live image regeneration for `2026-07-21`;
6. reuse the resolved editorial plan and make zero editorial-model calls;
7. generate exactly one replacement image;
8. validate R2 and public delivery;
9. prove a second invocation is a zero-call no-op;
10. commit the new official artifact.

The existing stale-illustration path must continue to reuse the resolved editorial plan when only the illustration prompt hash changes.
