# Immutable production-v1 fixture

This fixture is the exact committed 2026-07-21 editorial artifact and manifest from immediately before the authorized production-v2 migration. It exists only for stored-contract and migration compatibility regression tests and must remain immutable.

`generated/editorial/` is the mutable current production state and now contains the accepted production-v2 artifact. Tests must not use the current official artifact as a permanent historical fixture.
