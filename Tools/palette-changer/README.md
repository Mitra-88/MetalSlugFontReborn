# MSFR Palette Changer

A standalone Qt6 tool that recolors a folder of sprites into a new hue while
keeping every color's shading level exactly, with optional brightness,
saturation, and contrast adjustments. It has no dependency on the
MetalSlugFontReborn app and works on any folder of RGBA PNG sprites.

## Run

```sh
python Tools/palette-changer/palette_changer.py
```

(uses the same PySide6 and Pillow already installed for the app)

## Use

1. **Input folder**: browse for it or paste the path. The folder and every
   subdirectory are scanned for `.png` sprites.
2. Press **Load Palette**. The exact colors used by all sprites appear as
   swatches, most used first.
3. **Pick a replacement hue** on the hue slider. Click a swatch to select
   it, then click it again to remap that color: it keeps its own saturation
   and brightness and takes only your hue. The outline and other neutrals
   map to the gray of their own level, so shading stays put. Repeat per
   color.
4. **Adjustments** (optional): move Brightness, Saturation, or Contrast
   away from 100% to tune every sprite. 100% leaves them untouched.
5. **Output folder**: type a name (created next to the input folder) or a
   full path, or browse for it. The folder is created if missing.
6. Press **Export Recolored Copies**. Every sprite is written to the output
   folder with the same relative names and subfolders as the input.

For MetalSlugFontReborn: point the input at `Assets\Fonts\Font-1\MS-Blue`,
name the output `MS-<YourColor>`, export, and restart the app. The new
color appears for that font automatically.

## Precision

Hue remapping converts once from the exact source RGB to HSV, applies the
target hue, and quantizes to 8-bit a single time on write. Brightness and
contrast are a single composed per-channel lookup table (also one
quantization); saturation is Pillow's C enhancer blending toward ITU-R 601
luma. Alpha is never adjusted.

The engine is covered by `Tests/test_color_variants.py`: hue accuracy is
checked against Python's `colorsys` across the hue wheel, and exports are
verified pixel by pixel.
