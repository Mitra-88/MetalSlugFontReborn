import re
from pathlib import Path

from image_generation import (
    FONTS_BASE_DIR,
    get_character_path,
    get_font_charset,
    get_font_colors,
    get_font_ids,
    get_font_paths,
)
from special_characters import special_characters

DECORATIVE_SYMBOL_STEM = re.compile(r"^([AEIOU]-\d+|One|Two|Three|Four|Five)$")


def test_font_ids_and_colors_match_disk_layout():
    assert get_font_ids() == [1, 2, 3, 4, 5]
    fonts_root = Path(__file__).resolve().parents[1] / "Assets" / "Fonts"
    for font in get_font_ids():
        expected = sorted(
            d.name[3:]
            for d in (fonts_root / f"Font-{font}").iterdir()
            if d.is_dir() and d.name.startswith("MS-")
        )
        assert expected, f"Font {font} has no color folders"
        assert get_font_colors(font) == expected


def test_every_charset_character_has_a_sprite_for_every_color():
    for font in get_font_ids():
        for color in get_font_colors(font):
            font_paths = get_font_paths(font, color)
            for ch in get_font_charset(font):
                if ch in " \n":
                    continue
                path = get_character_path(ch, font_paths)
                assert path.is_file(), (
                    f"Font {font}/{color}: sprite missing for {ch!r} at {path}"
                )


def test_charset_covers_every_letter_and_number_file_on_disk():
    inverse = {name: ch for ch, name in special_characters.items()}
    for font in get_font_ids():
        charset = get_font_charset(font)
        color_dir = FONTS_BASE_DIR / f"Font-{font}" / f"MS-{get_font_colors(font)[0]}"
        for group in ("Letters/Lower-Case", "Letters/Upper-Case", "Numbers"):
            directory = color_dir / group
            if not directory.is_dir():
                continue
            for entry in directory.iterdir():
                assert entry.stem in charset, (
                    f"Font {font}: file {entry.name} is missing from the charset"
                )
        for entry in (color_dir / "Symbols").iterdir():
            char = inverse.get(entry.stem)
            if char is None:
                assert DECORATIVE_SYMBOL_STEM.match(entry.stem), (
                    f"Font {font}: unmapped symbol file {entry.name} is not a "
                    "known decorative variant"
                )
            else:
                assert char in charset, f"Font {font}: {entry.name} missing"


def test_charset_is_uniform_across_colors():
    inverse = {name: ch for ch, name in special_characters.items()}
    for font in get_font_ids():
        color_dir = FONTS_BASE_DIR / f"Font-{font}"
        per_color = []
        for color in get_font_colors(font):
            mapped = set()
            for entry in (color_dir / f"MS-{color}" / "Symbols").iterdir():
                char = inverse.get(entry.stem)
                if char is not None:
                    mapped.add(char)
            per_color.append(frozenset(mapped))
        assert len(set(per_color)) == 1, f"Font {font}: symbol sets differ per color"


def test_font5_charset_is_uppercase_only():
    assert get_font_charset(5) == frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789 \n!?")


def test_regular_fonts_cover_alphanumerics():
    for font in (1, 2, 3, 4):
        chars = get_font_charset(font)
        assert {"a", "Z", "0", "9", "\n"} <= chars
