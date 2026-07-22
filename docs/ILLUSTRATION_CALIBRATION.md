# Illustration prompt calibration lab

This lab compares immutable prompt profiles against one already validated Daily visual brief. It is isolated from normal publication: it never calls the editorial model, writes official editorial JSON, or uploads to R2. Production remains pinned to `baseline-v1` and the current `ILLUSTRATION_PROMPT_VERSION` until a separate winner-locking change is reviewed.

Rendering styles are registered declaratively in `tools/tldr_editorial/illustration_prompts.py`. Editorial visual concepts are independently registered in `tools/tldr_editorial/illustration_concepts.py`. The calibration engine forms an explicit Cartesian product; neither registry depends on the other, and production still uses its validated visual brief with `baseline-v1` exactly as before. The safety policy, normalizer, gallery, and scoring format contain no profile count or ID list.

## Profiles available initially

- `baseline-v1`: byte-for-byte production direction.
- `print-graphic-v1`: restricted-palette print/relief graphic.
- `object-study-v1`: restrained, physically plausible object study.
- `constructed-collage-v1`: tactile cut-paper editorial construction.
- `ink-gouache-v1`: reduced ink and opaque-gouache drawing.
- `cinematic-editorial-v1`: coherent, source-grounded cinematic framing and atmosphere.

Only factual and safety restrictions are shared: no visible text, logos/trademarks, fabricated evidence, interfaces/screenshots, or imitation of named/living artists. Photorealism, concept art, detail, gradients, surfaces, and other aesthetic choices are style-specific.

## AMD Helios concept profiles

- `integrated-stack-v1`: distinct modules converge into one integrated system.
- `challenger-enters-v1`: a credible smaller engineered structure disrupts an established field.
- `system-to-buyer-v1`: construction connects directionally to receiving infrastructure.
- `industrial-scale-v1`: density, modularity, assembly, and human-relative infrastructure scale.
- `architecture-rivalry-v1`: contrasting system architectures without literal combat.
- `small-share-large-ambition-v1`: spatial contrast between a small footprint and credible infrastructure ambition.

Concepts may override only central subject, visual metaphor, composition, and concept-specific forbidden elements. They contain factual rationale and optional source-reference requirements, but no rendering medium, palette, lighting, or material treatment. Calibration records hashes for both the original validated brief and the experimental concept. A calibration-only anti-default clause rejects the centered heroic rack/tower idea unless a selected concept genuinely requires it.

## Safe usage

Planning mode writes blind experiment files but makes zero network calls:

```bash
python -m tools.tldr_editorial calibrate-images \
  --date 2026-07-21 \
  --style-profiles print-graphic-v1,constructed-collage-v1 \
  --concepts integrated-stack-v1,challenger-enters-v1,system-to-buyer-v1,industrial-scale-v1,architecture-rivalry-v1,small-share-large-ambition-v1 \
  --output-dir /home/galois/tldr-image-calibration/round-1b \
  --samples-per-combination 1 --max-images 12
```

A live run is accepted only with both explicit acknowledgements:

```bash
python -m tools.tldr_editorial calibrate-images \
  --date 2026-07-21 \
  --style-profiles print-graphic-v1,constructed-collage-v1 \
  --concepts integrated-stack-v1,challenger-enters-v1,system-to-buyer-v1,industrial-scale-v1,architecture-rivalry-v1,small-share-large-ambition-v1 \
  --output-dir /home/galois/tldr-image-calibration/round-1b \
  --samples-per-combination 1 \
  --require-live --acknowledge-cost --max-images 12
```

The output must be absolute, outside Git, non-symlinked, and empty. The checkout must be clean. CI live runs are forbidden. `--samples-per-combination` defaults to one and accepts one through three; `--max-images` covers styles × concepts × samples. `--profiles` and `--samples-per-profile` remain aliases for the original style-only experiment. Repeated samples receive independent anonymous IDs while using identical prompts and source facts. No candidate is automatically retried; after one failure, it and all unattempted candidates are recorded and paid calls stop.

Outputs are `manifest.json`, private `blind-map.json`, `gallery.html`, `score-template.json`, and (live only) normalized anonymous WebPs. The private map stores style, concept, and sample. The public manifest and gallery expose none. The self-contained `file://` gallery randomizes anonymous candidates, shows source facts once, uses at most three large columns (one on narrow screens), keeps identical 3:2 framing, and offers local click-to-enlarge. Keep `blind-map.json` private until scoring is complete.

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

## Round 1B protocol (documented, not executed here)

Round 1 showed that style changes alone still converged on a centered heroic rack. No image won. Based on best-sample quality, pair consistency, low obvious-AI appearance, and newspaper suitability, advance `print-graphic-v1` and `constructed-collage-v1`; baseline advances only if human ranking explicitly places it in the top two.

For concept discovery, cross the two selected styles with all six AMD concepts and use one sample per combination: twelve image calls, zero editorial calls, no R2, and no official artifact mutation. Review blindly and retain the two strongest style/concept combinations.

Then generate two additional samples for each finalist: four calls for consistency evaluation. Do not select from a single attractive sample. A later cross-story round must still verify any eventual direction on abstract software/model and human/organizational/economic technology stories.

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
