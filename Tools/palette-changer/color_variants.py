
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance

NEUTRAL_SATURATION = 0.08
MAX_PALETTE_COLORS = 24


def list_png_files(root):
    files = []

    def walk(directory, rel):
        for entry in sorted(Path(directory).iterdir()):
            child = f"{rel}{os.sep}{entry.name}" if rel else entry.name
            if entry.is_dir():
                walk(entry, child)
            elif entry.is_file() and entry.suffix.lower() == ".png":
                files.append((entry, child))

    walk(root, "")
    return files


def load_rgba(path):
    image = Image.open(path)
    if image.mode in ("I", "I;16", "F"):
        raise ValueError(
            f"{Path(path).name}: {image.mode} depth images are not supported"
        )
    return image.convert("RGBA")


def collect_palette(files, max_colors=MAX_PALETTE_COLORS):
    counts = {}
    for path, _rel in files:
        image = load_rgba(path)
        colors = image.getcolors(maxcolors=1 << 20)
        if colors is None:
            continue
        for count, color in colors:
            if color[3] > 0:
                key = color[:3]
                counts[key] = counts.get(key, 0) + count
    ranked = sorted(counts.items(), key=lambda item: -item[1])
    return [color for color, _count in ranked[:max_colors]]


def rgb_to_hsv(r, g, b):
    max_c = max(r, g, b)
    min_c = min(r, g, b)
    delta = max_c - min_c
    if max_c == 0 or delta == 0:
        return 0.0, 0.0, max_c
    saturation = delta / max_c
    if max_c == r:
        hue = (g - b) / delta % 6
    elif max_c == g:
        hue = (b - r) / delta + 2
    else:
        hue = (r - g) / delta + 4
    return hue * 60, saturation, max_c


def hsv_to_rgb(h, s, v):
    h = h % 360
    chroma = v * s
    x = chroma * (1 - abs(h / 60 % 2 - 1))
    m = v - chroma
    if h < 60:
        r, g, b = chroma, x, 0
    elif h < 120:
        r, g, b = x, chroma, 0
    elif h < 180:
        r, g, b = 0, chroma, x
    elif h < 240:
        r, g, b = 0, x, chroma
    elif h < 300:
        r, g, b = x, 0, chroma
    else:
        r, g, b = chroma, 0, x
    return (
        round((r + m) * 255),
        round((g + m) * 255),
        round((b + m) * 255),
    )


def hue_shift(old_rgb, target_hue):
    _h, saturation, _value = rgb_to_hsv(
        old_rgb[0] / 255, old_rgb[1] / 255, old_rgb[2] / 255
    )
    if saturation < NEUTRAL_SATURATION:
        return tuple(old_rgb)
    return hsv_to_rgb(target_hue, saturation, _value)


def build_hue_mapping(palette, target_hue):
    return {rgb: hue_shift(rgb, target_hue) for rgb in palette}


def recolor_image(image, hue_mapping):
    channels = list(image.split())
    jobs = []
    for old_rgb, new_rgb in hue_mapping.items():
        masks = []
        for band, old_component in zip(channels[:3], old_rgb):
            lut = [0] * 256
            lut[old_component] = 255
            masks.append(band.point(lut))
        mask = ImageChops.multiply(ImageChops.multiply(masks[0], masks[1]), masks[2])
        jobs.append((mask, new_rgb))

    for mask, new_rgb in jobs:
        for band, new_component in zip(channels[:3], new_rgb):
            band.paste(Image.new("L", image.size, new_component), mask=mask)

    return Image.merge("RGBA", channels)


def _clamped_lut(function):
    return [min(255, max(0, round(function(i)))) for i in range(256)]


def apply_adjustments(image, brightness=1.0, saturation=1.0, contrast=1.0):

    def tone_lut(i):
        value = i * brightness
        return (value / 255 - 0.5) * contrast * 255 + 127.5

    red, green, blue, alpha = image.split()
    lut = _clamped_lut(tone_lut)
    red = red.point(lut)
    green = green.point(lut)
    blue = blue.point(lut)
    merged = Image.merge("RGBA", (red, green, blue, alpha))
    if saturation != 1.0:
        merged = ImageEnhance.Color(merged).enhance(saturation)
    return merged


def adjust_color(rgb, brightness=1.0, saturation=1.0, contrast=1.0):
    image = Image.new("RGBA", (1, 1), (*rgb, 255))
    adjusted = apply_adjustments(image, brightness, saturation, contrast)
    return adjusted.getpixel((0, 0))[:3]


def export_recolored(
    files, hue_mapping, output_dir, brightness=1.0, saturation=1.0, contrast=1.0
):
    saved = 0
    for path, rel in files:
        out_path = Path(output_dir) / rel
        if out_path.exists() and out_path.resolve() == Path(path).resolve():
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image = load_rgba(path)
        if hue_mapping:
            image = recolor_image(image, hue_mapping)
        image = apply_adjustments(image, brightness, saturation, contrast)
        image.save(out_path)
        saved += 1
    return saved


def resolve_output_dir(text, input_dir):
    text = (text or "").strip()
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate
    return Path(input_dir).parent / text
