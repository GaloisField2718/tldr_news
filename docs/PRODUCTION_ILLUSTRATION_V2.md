# Production illustration v2

Rendering style and story-specific editorial concept are separate. Blind cross-story review selected `print-graphic-v1`: it produced the preferred Secure Sandboxes and Hyundai images, while constructed collage was more distinctive but less reliable and produced a visible-text hard rejection. AMD concepts remain calibration-only and are never universal production concepts.

`production-v2` locks a rendering direction only: authored print language, simplified shapes, restrained palette, physical texture, hierarchy, negative space, and controlled abstraction. It excludes CGI, cyberpunk, monumental racks, pseudo-technical detail, and all text-like artifacts, without excluding legitimate people, objects, depth, or environments needed by a story.

Production visual briefs are versioned. V2 requires `schema_version: "2.0.0"`, `mode`, exact `sources`, `editorial_idea`, `central_subject`, `visual_relationship`, `composition`, ordered unique `literal_elements`, `abstraction_level` (`low`, `medium`, or `high`), ordered unique `forbidden_elements`, ordered unique `failure_modes`, and factual `alt_text`. Text fields are bounded (300–500 characters by field); literal and failure arrays cap at 12 and forbidden elements at 20. Historical v1 briefs remain readable under their old contract but cannot be silently upgraded.

The safe live migration path is **Option A**: an incompatible v1 brief forces one editorial call for a strengthened AMD v2 brief, followed by one image call, one immutable WebP upload, and a zero-call no-op proof. Never reuse an AMD concept for unrelated stories. The illustration hash includes the complete brief, exact facts, image configuration, and active prompt version.

Prompt restrictions reduce but cannot guarantee text/artifact absence. Optional second-stage OCR or visual moderation remains future work and is not invoked by this pipeline.

Rollback is a reviewed change restoring `baseline-v1` and its previous prompt version; do not overwrite historic artifacts or R2 objects.
