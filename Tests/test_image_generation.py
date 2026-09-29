from pathlib import Path

import pytest
from PIL import Image

import image_generation
from image_generation import (
    create_character_image,
    find_unsupported_characters,
    generate_filename,
    generate_image,
    get_character_path,
    get_font_paths,
    layout_characters,
    split_into_lines,
)


@pytest.fixture
def font_paths():
    return get_font_paths(1, "Blue")


def test_generate_filename_is_unique_png():
    names = {generate_filename() for _ in range(50)}
    assert len(names) == 50
    assert all(name.endswith(".png") for name in names)


def test_split_into_lines():
    assert split_into_lines("a\nb") == ["a", "b"]
    assert split_into_lines("a\n\nb") == ["a", "", "b"]
    assert split_into_lines("") == [""]


def test_get_font_paths_matches_asset_layout():
    paths = get_font_paths(2, "Gold")
    base = image_generation.FONTS_BASE_DIR / "Font-2" / "MS-Gold"
    assert paths["letters"] == base / "Letters"
    assert paths["numbers"] == base / "Numbers"
    assert paths["symbols"] == base / "Symbols"


def test_get_character_path_maps_character_classes(font_paths):
    assert (
        get_character_path("a", font_paths)
        == font_paths["letters"] / "Lower-Case" / "a.png"
    )
    assert (
        get_character_path("A", font_paths)
        == font_paths["letters"] / "Upper-Case" / "A.png"
    )
    assert get_character_path("5", font_paths) == font_paths["numbers"] / "5.png"
    assert get_character_path("!", font_paths).name == "Exclamation.png"


def test_get_character_path_rejects_unsupported_character(font_paths):
    with pytest.raises(FileNotFoundError, match="not available"):
        get_character_path("@", font_paths)


def test_find_unsupported_characters_reports_the_full_set(font_paths):
    assert find_unsupported_characters("Hiéñ@", 1) == ["@", "é", "ñ"]
    assert find_unsupported_characters("Hello!", 1) == []


def test_get_character_path_reports_missing_asset(tmp_path):
    font_paths = {key: tmp_path / key for key in ("letters", "numbers", "symbols")}
    with pytest.raises(FileNotFoundError, match="no sprite asset"):
        get_character_path("a", font_paths)


def test_whitespace_only_line_uses_placeholder_height(font_paths):
    a_h = create_character_image("a", font_paths).height
    b_h = create_character_image("b", font_paths).height
    _placements, (_width, height) = layout_characters(
        "a\n \nb", font_paths, line_spacing=0
    )
    assert height == a_h + image_generation.EMPTY_LINE_HEIGHT + b_h


def test_space_renders_as_transparent_strip(font_paths):
    img = create_character_image(" ", font_paths)
    assert (img.width, img.height) == (
        image_generation.SPACE_CHARACTER_WIDTH,
        image_generation.SPACE_CHARACTER_HEIGHT,
    )
    assert img.getpixel((0, 0))[3] == 0


def test_sprite_cache_reuses_opened_image(font_paths):
    assert create_character_image("a", font_paths) is create_character_image(
        "a", font_paths
    )


def test_layout_places_visible_characters_and_skips_spaces(font_paths):
    placements, _size = layout_characters("a b", font_paths)
    assert [char for char, _img, _x, _y in placements] == ["a", "b"]


def test_layout_right_align_pushes_short_line_right(font_paths):
    placements, (width, _height) = layout_characters("a\nii", font_paths, align="right")
    xs = [x for char, _img, x, _y in placements if char == "i"]
    a_w = create_character_image("a", font_paths).width
    i_w = create_character_image("i", font_paths).width
    assert width == max(a_w, 2 * i_w)
    assert [x for char, _img, x, _y in placements if char == "a"] == [0]
    assert xs == [width - 2 * i_w, width - i_w]


def test_layout_center_align(font_paths):
    placements, (width, _height) = layout_characters(
        "a\nii", font_paths, align="center"
    )
    a_w = create_character_image("a", font_paths).width
    i_w = create_character_image("i", font_paths).width
    assert [x for char, _img, x, _y in placements if char == "a"] == [
        (width - a_w) // 2
    ]
    left = (width - 2 * i_w) // 2
    assert [x for char, _img, x, _y in placements if char == "i"] == [
        left,
        left + i_w,
    ]


def test_layout_baseline_center_vertical_centering(font_paths):
    sprites = {ch: create_character_image(ch, font_paths) for ch in "ail"}
    if len({s.height for s in sprites.values()}) < 2:
        pytest.skip("sprites share the same height, nothing to center")
    tallest = max(s.height for s in sprites.values())
    placements, _size = layout_characters("ail", font_paths, baseline="center")
    for char, img, _x, y in placements:
        assert y == (tallest - img.height) // 2, char


def test_layout_letter_spacing_separates_characters(font_paths):
    a_w = create_character_image("a", font_paths).width
    b_w = create_character_image("b", font_paths).width
    _placements, (width, _height) = layout_characters(
        "ab", font_paths, letter_spacing=7
    )
    assert width == a_w + 7 + b_w


def test_layout_empty_line_gets_placeholder_height(font_paths):
    a_h = create_character_image("a", font_paths).height
    _placements, (_width, height) = layout_characters(
        "a\n\nb", font_paths, line_spacing=0
    )
    b_h = create_character_image("b", font_paths).height
    assert height == a_h + image_generation.EMPTY_LINE_HEIGHT + b_h


def test_generate_image_returns_rendered_image(font_paths):
    img, w, h = generate_image("Hi!", "preview", font_paths, None, return_image=True)
    assert (w, h) == (img.width, img.height)
    assert img.getbbox() is not None


def test_generate_image_pixels_match_layout_composition(font_paths):
    text = "Hi!\nOK"
    placements, (width, height) = layout_characters(text, font_paths)
    expected = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for _char, sprite, x, y in placements:
        expected.paste(sprite, (x, y), sprite)
    img, w, h = generate_image(text, "preview", font_paths, None, return_image=True)
    assert (w, h) == (width, height)
    assert img.tobytes() == expected.tobytes()


def test_generate_image_blank_lines_still_renders_canvas(font_paths):
    _img, w, h = generate_image("\n", "preview", font_paths, None, return_image=True)
    assert (w, h) == (
        1,
        2 * image_generation.EMPTY_LINE_HEIGHT + image_generation.LINE_SPACING,
    )


def test_generate_image_rejects_unsupported_character(font_paths):
    with pytest.raises(FileNotFoundError):
        generate_image("héllo", "preview", font_paths, None, return_image=True)


def test_generate_image_scale_multiplies_dimensions(font_paths):
    _base, base_w, base_h = generate_image(
        "OK", "preview", font_paths, None, return_image=True
    )
    _img, w, h = generate_image(
        "OK", "preview", font_paths, None, return_image=True, scale=2
    )
    assert (w, h) == (base_w * 2, base_h * 2)


def test_generate_image_saves_atomically(font_paths, tmp_path):
    out_path, _w, _h = generate_image(
        "OK", "out.png", font_paths, tmp_path, compress_level=0
    )
    saved = Path(out_path)
    assert saved.exists() and saved.stat().st_size > 0
    assert saved.name == "out.png"
    assert not list(tmp_path.glob("*.part*"))


def test_synthetic_font_compositing_is_pixel_exact(tmp_path):
    letters = tmp_path / "Letters" / "Lower-Case"
    letters.mkdir(parents=True)
    (tmp_path / "Numbers").mkdir()
    (tmp_path / "Symbols").mkdir()
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(letters / "a.png")
    Image.new("RGBA", (3, 1), (0, 0, 255, 255)).save(letters / "b.png")
    font_paths = {
        "letters": tmp_path / "Letters",
        "numbers": tmp_path / "Numbers",
        "symbols": tmp_path / "Symbols",
    }

    image, width, height = generate_image(
        "ab", "out.png", font_paths, None, compress_level=0, return_image=True
    )

    assert (width, height) == (5, 2)
    assert image.getpixel((0, 0)) == (255, 0, 0, 255)
    assert image.getpixel((1, 0)) == (255, 0, 0, 255)
    assert image.getpixel((0, 1)) == (255, 0, 0, 255)
    assert image.getpixel((1, 1)) == (255, 0, 0, 255)
    assert image.getpixel((2, 0)) == (0, 0, 0, 0)
    assert image.getpixel((2, 1)) == (0, 0, 255, 255)
    assert image.getpixel((4, 0)) == (0, 0, 0, 0)
    assert image.getpixel((2, 1)) == (0, 0, 255, 255)
    assert image.getpixel((4, 1)) == (0, 0, 255, 255)


def test_png_compression_levels_produce_valid_output(tmp_path, font_paths):
    for level in (0, 6, 9):
        out_path, width, height = generate_image(
            "Hi!", f"c{level}.png", font_paths, tmp_path, compress_level=level
        )
        with Image.open(out_path) as saved:
            assert (saved.width, saved.height) == (width, height)
