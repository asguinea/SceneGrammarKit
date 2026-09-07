# Phase 2 annotation-review policy

Batch 2.2 introduces annotation-review policy `0.1`. This policy is independent
of annotation schema `0.1`, construction-config schema `0.1`, grammar schema,
renderer policy, demo policy, and the package version.

The review workflow visualizes and inventories supplied evidence only. It does
not construct a grammar, lift annotations into 3D, infer depth or splits,
estimate repeat spacing, detect objects, segment pixels, or reconstruct
geometry.

## Source-image verification

The source image path is resolved only relative to the annotation JSON file's
directory. Its resolved target must remain inside that directory, including
after symlink resolution. Missing files are not searched for elsewhere.

PNG and JPEG are the documented Batch 2.2 formats. File bytes are hashed with
SHA-256, an optional declared digest is checked, Pillow decodes the image, and
the decoded width and height must exactly equal the declared dimensions. The
image is converted to RGBA without EXIF transformation or resizing. File-backed
handles are closed before the verified in-memory image is returned.

## Output sizing and coordinates

The sole `fit_within_maximum` output-width policy preserves aspect ratio, never
upscales, and fits the longest source dimension within the configured maximum.
The default maximum is 1600 pixels. Output pixel count is bounded.

Normalized top-left-origin UV coordinates map exactly as:

```text
x = round(u * (width - 1))
y = round(v * (height - 1))
```

Rectangles use their two supplied corners. Polygons use every supplied vertex
in its original order. Rendering does not simplify, reorder, repair, or infer
annotation geometry.

## Deterministic draw order

1. source image (or transparent semantic layer);
2. region fills;
3. instance fills;
4. outlines;
5. repeat connectors;
6. optional parent links;
7. supplied split-axis hints;
8. labels;
9. legend.

The project semantic palette is reused. Known classes retain fixed project
colors; unknown classes use the existing SHA-256-derived fallback and never
Python `hash()`.

Depth-zone outlines use fixed colors: red for foreground, amber for midground,
and blue for background. Structural regions have heavier outlines, terminal
regions use the base outline, open space uses reduced opacity and a dashed
outline, and object instances use stronger fill plus a white-backed zone
outline. Labels use `S`, `T`, `O`, and `I` role prefixes.

Repeat groups use a fixed magenta connector through member centroids in supplied
member order. Markers are numbered from that order; labels say `members=N` and
`supplied axis=<axis>`. No repeat count or spacing is presented as inferred.

Supplied `x` and `y` split hints use horizontal and vertical arrows. Supplied
`z` uses a target marker plus `supplied hint=z`, avoiding a physical 3D-axis
claim. Parent links are subtle and disabled by default. The legend explicitly
says `Supplied annotation`.

Pillow's bundled default font is used. No system or external font is required.
Label candidates and collision reduction are deterministic, though dense
annotations can still overlap.

## Canonical artifacts

The integrated workflow writes:

```text
annotation.json
construction_config.json
annotation_overlay.png
annotation_summary.json
annotation_summary.txt
annotation_review_report.json
```

JSON uses sorted keys, compact separators, direct Unicode, finite numbers, and
no final newline. The text summary has exactly one final newline. Canonical
reports contain no timestamps, usernames, machine metadata, or absolute paths.

PNG output is RGBA, uses compression level 9 with optimization disabled, and
contains no timestamps or variable metadata. All files use same-directory
atomic writes, require explicit overwrite, and clean temporary files after
failure. Integrated review rejects a nonempty directory unless overwrite is
explicit; overwrite replaces only the six known artifacts and preserves
unrelated files. The success report is written last.

## Summary disclosure

The summary reports declared and verified image facts, counts and deterministic
frequencies, region hierarchy depth, regions by depth zone, ordered repeat
membership, supplied-information categories, and warnings. It explicitly says
the artifact contains no inferred depth, inferred split boundaries, inferred
repeat spacing, inferred grammar, or reconstructed geometry.

## Fixture compatibility note

The valid Batch 2.1 fixture annotations now point to confined synthetic images,
so their canonical annotation hashes intentionally changed only in
`source_image` metadata:

- `urban_minimal.annotation.json`: 3296 bytes,
  SHA-256 `294c8b0bae51d656886e4be9e51d92cbb8da66a7beb91015554ba90bf8b7976b`;
- `facade_polygon.annotation.json`: 804 bytes,
  SHA-256 `a58f3cd4fee43076435d2b47dbd292cb4c2d4ce35111514aad328733d751266c`.

Annotation schema and safe-path behavior remain unchanged.
