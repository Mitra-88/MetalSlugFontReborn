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
from ui_common import build_supported_document_markdown

DOC_PATH = (
    Path(__file__).resolve().parents[1] / "Docs" / "SUPPORTED.md"
)


def _parse_sections(text):
    sections = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"## Font (\d+) Support", line)
        if heading:
            current = int(heading.group(1))
            sections[current] = {}
            continue
        if line.startswith("# Unsupported"):
            current = None
            continue
        item = re.match(r"- \*\*(Letters|Numbers|Symbols|Colors):\*\* (.*)", line)
        if item and current is not None:
            sections[current][item.group(1)] = item.group(2)
    return sections


def _unsupported_symbols(text):
    tail = text.split("# Unsupported", 1)[-1]
    line = next(
        (ln for ln in tail.splitlines() if ln.startswith("- **Symbols:**")),
        "",
    )
    return line.removeprefix("- **Symbols:**").split()


def test_supported_md_matches_generator():
    generated = build_supported_document_markdown()
    actual = DOC_PATH.read_text(encoding="utf-8")
    tail = actual.split("# Unsupported", 1)[-1]
    assert tail, "SUPPORTED.md lost its Unsupported Characters section"
    assert actual.startswith(generated + "\n\n# Unsupported")


def test_supported_md_symbols_match_charset():
    sections = _parse_sections(DOC_PATH.read_text(encoding="utf-8"))
    for font in get_font_ids():
        charset = get_font_charset(font)
        expected = {
            ch for ch in charset if not ch.isalnum() and ch not in " \n"
        }
        assert set(sections[font]["Symbols"].split()) == expected, font


def test_supported_md_symbols_exist_for_every_color():
    sections = _parse_sections(DOC_PATH.read_text(encoding="utf-8"))
    for font in get_font_ids():
        for color in get_font_colors(font):
            font_paths = get_font_paths(font, color)
            for ch in sections[font]["Symbols"].split():
                path = get_character_path(ch, font_paths)
                assert path.is_file(), (font, color, ch, path)


def test_per_color_charset_matches_union():
    inverse = {name: ch for ch, name in special_characters.items()}
    for font in get_font_ids():
        union = get_font_charset(font)
        for color in get_font_colors(font):
            base = FONTS_BASE_DIR / f"Font-{font}" / f"MS-{color}"
            chars = {" ", "\n"}

            def add(directory, mapper, chars):
                if not directory.is_dir():
                    return
                for entry in directory.iterdir():
                    char = mapper(entry.stem)
                    if char is not None:
                        chars.add(char)

            add(
                base / "Letters" / "Lower-Case",
                lambda stem: stem if len(stem) == 1 and stem.islower() else None,
                chars,
            )
            add(
                base / "Letters" / "Upper-Case",
                lambda stem: stem if len(stem) == 1 and stem.isupper() else None,
                chars,
            )
            add(
                base / "Numbers",
                lambda stem: stem if len(stem) == 1 and stem.isdigit() else None,
                chars,
            )
            add(base / "Symbols", inverse.get, chars)
            assert frozenset(chars) == union, (font, color)


def test_unsupported_section_lists_only_unsupported_characters():
    symbols = _unsupported_symbols(DOC_PATH.read_text(encoding="utf-8"))
    assert symbols, "Unsupported Characters section is empty"
    for font in get_font_ids():
        charset = get_font_charset(font)
        for ch in symbols:
            assert ch not in charset, (font, ch)
