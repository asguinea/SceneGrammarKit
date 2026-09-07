# System contract

The reference implementation targets Python 3.11 or newer and runs on CPU
without a display server or GPU. Inputs use strict versioned JSON schemas.
Generated canonical JSON is sorted, compact, UTF-8 encoded, and excludes
absolute paths, timestamps, and machine-specific runtime values.

Grammar execution is bounded by explicit depth and primitive limits. Output
directories reject accidental overwrite unless the caller opts in. Repeated
runs with identical inputs must produce identical canonical JSON, PNG bytes and
pixels, and GLB bytes and reopened geometry on the same supported environment.
