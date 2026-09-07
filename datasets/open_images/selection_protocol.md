# Frozen-case selection protocol

The representation-aligned Batch 3.2 candidate pass used the validation split
and official V7 class descriptions, human-verified labels, bounding boxes,
image metadata, and CVDF image storage through the existing adapter.

1. Resolve class display names from the official V7 class map.
2. Filter for attribution-complete urban candidates.
3. Download 120 validation images from official CVDF S3 storage: 60 regular
   facade candidates and 60 structured street/parking candidates.
4. Verify image IDs, decode dimensions, and compute SHA-256 values.
5. Build four deterministic contact sheets with labels, suitability scores,
   rejection flags, and provisional notes.
6. Shortlist five candidates per family and construct each once with minimal
   project-authored assisted annotations.
7. Record all ten visual-gate decisions for every shortlisted candidate.
8. Freeze exactly two gate-passing replacements: one regular-facade canonical
   success and one structured-street success.
9. Retain the existing Turku curved-facade limitation unchanged.

The replacement annotations were authored before final constructor output
review. They are disclosed as annotation assistance, not pixel inference.
The former Halifax and Ruta del Modernisme outputs remain archived because
their towers, rooflines, ornament, and strong projective structure are outside
the intended positive-example scope; they remain valid pipeline results.
