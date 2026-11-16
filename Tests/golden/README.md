# Aseprite golden images

Export the rotated sprite from Aseprite into this folder as
`<sprite>_<angle>_<quality>.png` and the test suite will compare the engine
against it.

- `<sprite>` is `gradient` (the 4x3 gradient used by the rotation tests),
  `glyph` (the 9x6 binary alpha sprite) or `dense78x123` (the 78x123 dense
  pattern used by the float-angle regression).
- `<angle>` is the clockwise rotation in degrees, for example `45` or
  `28.44369954375634`.
- `<quality>` is `rotsprite` or `nearest`.

Examples: `gradient_45_rotsprite.png`, `glyph_33_nearest.png`,
`dense78x123_28.44369954375634_rotsprite.png`.

The test skips while this folder has no PNGs. Do not add synthetic images:
they must come from Aseprite's real algorithm (the app or its `doc-lib`), with
the same source sprite.

The `dense78x123_28.44369954375634_*` pair is MSVC-specific: its sine sits
within 0.003 of the five-decimal boundary, so glibc and Apple libm can round it
the other way. The test runs that pair on Windows only.
