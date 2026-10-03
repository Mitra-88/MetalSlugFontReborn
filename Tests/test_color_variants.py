import colorsys
import os
import shutil
from pathlib import Path

from color_variants import (
    adjust_color,
    apply_adjustments,
    build_hue_mapping,
    collect_palette,
    export_recolored,
    hue_shift,
    list_png_files,
    recolor_image,
    resolve_output_dir,
)
from PIL import Image

ASSET_DIR = (
    Path(__file__).resolve().parents[1] / "Assets" / "Fonts" / "Font-1" / "MS-Blue"
)
OUTLINE = (32, 32, 32, 255)
WHITE = (248, 248, 248, 255)
BLUE_SHADE = (176, 184, 224, 255)


def make_files(tmp_path):
    input_dir = tmp_path / "in"
    (input_dir / "sub").mkdir(parents=True)
    shutil.copyfile(ASSET_DIR / "Letters" / "Upper-Case" / "A.png", input_dir / "A.png")
    shutil.copyfile(ASSET_DIR / "Numbers" / "5.png", input_dir / "sub" / "5.png")
    return list_png_files(input_dir), input_dir


def test_list_png_files_is_recursive_and_keeps_relative_names(tmp_path):
    files, _input_dir = make_files(tmp_path)
    names = [(path.name, rel) for path, rel in files]
    assert ("A.png", "A.png") in names
    assert ("5.png", os.path.join("sub", "5.png")) in names


def test_collect_palette_ranks_by_frequency(tmp_path):
    files, _input_dir = make_files(tmp_path)
    palette = collect_palette(files)
    assert palette[0] == (32, 32, 32)
    assert (248, 248, 248) in palette
    assert len(palette) >= 3


def test_recolor_image_maps_exactly_and_preserves_alpha_and_others(tmp_path):
    files, _input_dir = make_files(tmp_path)
    image = Image.open(files[0][0]).convert("RGBA")
    recolored = recolor_image(image, {(32, 32, 32): (0, 255, 0)})
    pixels = set(recolored.get_flattened_data())
    assert (0, 255, 0, 255) in pixels
    assert OUTLINE not in pixels
    assert WHITE in pixels
    assert BLUE_SHADE in pixels


def test_recolor_image_does_not_chain_mappings(tmp_path):
    files, _input_dir = make_files(tmp_path)
    image = Image.open(files[0][0]).convert("RGBA")
    recolored = recolor_image(
        image,
        {
            (32, 32, 32): (255, 0, 0),
            (255, 0, 0): (0, 255, 0),
        },
    )
    pixels = set(recolored.get_flattened_data())
    assert (255, 0, 0, 255) in pixels
    assert (0, 255, 0, 255) not in pixels


def test_hue_shift_matches_colorsys_across_the_wheel():
    sources = [(176, 184, 224), (248, 168, 16), (64, 200, 120), (128, 136, 176)]
    for target_hue in range(0, 360, 30):
        for rgb in sources:
            r, g, b = hue_shift(rgb, target_hue)
            _h, s, v = colorsys.rgb_to_hsv(*[c / 255 for c in rgb])
            expected = [
                round(c * 255) for c in colorsys.hsv_to_rgb(target_hue / 360, s, v)
            ]
            for got, want in zip((r, g, b), expected):
                assert abs(got - want) <= 1


def test_hue_shift_neutrals_stay_exactly():
    assert hue_shift((32, 32, 32), 0) == (32, 32, 32)
    assert hue_shift((32, 32, 32), 359) == (32, 32, 32)
    assert hue_shift((248, 248, 248), 120) == (248, 248, 248)


def test_hue_shift_near_neutral_keeps_its_tint():
    assert hue_shift((128, 130, 132), 200) == (128, 130, 132)
    assert hue_shift((200, 199, 195), 45) == (200, 199, 195)


def test_apply_adjustments_brightness_lut_and_alpha_untouched():
    image = Image.new("RGBA", (2, 1))
    image.putpixel((0, 0), (100, 100, 100, 255))
    image.putpixel((1, 0), (200, 200, 200, 128))
    out = apply_adjustments(image, brightness=2.0)
    assert out.getpixel((0, 0)) == (200, 200, 200, 255)
    assert out.getpixel((1, 0)) == (255, 255, 255, 128)


def test_apply_adjustments_contrast_lut_around_mid_gray():
    image = Image.new("RGBA", (1, 1))
    image.putpixel((0, 0), (100, 100, 100, 255))
    out = apply_adjustments(image, contrast=2.0)
    expected = round((100 / 255 - 0.5) * 2.0 * 255 + 127.5)
    assert out.getpixel((0, 0))[:3] == (expected,) * 3
    assert out.getpixel((0, 0))[3] == 255


def test_apply_adjustments_saturation_moves_away_from_luma():
    image = Image.new("RGBA", (1, 1))
    image.putpixel((0, 0), (200, 100, 50, 255))
    base = apply_adjustments(image, saturation=1.0).getpixel((0, 0))
    boosted = apply_adjustments(image, saturation=2.0).getpixel((0, 0))
    luma = 0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2]
    base_distance = abs(base[0] - luma)
    boosted_distance = abs(boosted[0] - luma)
    assert boosted_distance > base_distance
    assert boosted[3] == 255


def test_export_refuses_to_write_into_itself(qapp, tmp_path):
    from palette_changer import MainWindow

    _files, input_dir = make_files(tmp_path)
    window = MainWindow()
    warnings = []
    try:
        window.input_entry.setText(str(input_dir))
        window._load_palette()
        window.hue_slider.setValue(120)
        outline_button = next(
            window.swatch_grid.itemAt(i).widget()
            for i in range(window.swatch_grid.count())
            if window.swatch_grid.itemAt(i)
            .widget()
            .toolTip()
            .startswith("R 32, G 32, B 32")
        )
        outline_button.click()
        outline_button.click()
        window.output_entry.setText(str(input_dir))
        window._warn_output_is_input = lambda: warnings.append(True)
        window._export()
        assert warnings == [True]
        original = Image.open(input_dir / "A.png").convert("RGBA")
        assert (32, 32, 32, 255) in set(original.get_flattened_data())
    finally:
        window.close()


def test_export_recolored_applies_hue_and_keeps_neutrals_and_alpha(tmp_path):
    files, _input_dir = make_files(tmp_path)
    out_dir = tmp_path / "out"
    mapping = build_hue_mapping(collect_palette(files), 120)
    saved = export_recolored(files, mapping, out_dir, saturation=1.5)
    assert saved == len(files)
    for path, rel in files:
        original = Image.open(path).convert("RGBA")
        recolored = Image.open(out_dir / rel).convert("RGBA")
        for y in range(original.height):
            for x in range(original.width):
                old_pixel = original.getpixel((x, y))
                new_pixel = recolored.getpixel((x, y))
                assert new_pixel[3] == old_pixel[3]
                if old_pixel[:3] in ((32, 32, 32), (248, 248, 248)):
                    assert new_pixel[:3] == old_pixel[:3]
                else:
                    hue, saturation, _value = colorsys.rgb_to_hsv(
                        *[c / 255 for c in new_pixel[:3]]
                    )
                    if saturation >= 0.08:
                        assert abs(hue * 360 - 120) <= 2, (x, y, old_pixel, new_pixel)


def test_resolve_output_dir(tmp_path):
    input_dir = tmp_path / "in" / "MS-Blue"
    assert resolve_output_dir("MS-Pink", input_dir) == tmp_path / "in" / "MS-Pink"
    elsewhere = tmp_path / "elsewhere"
    assert resolve_output_dir(str(elsewhere), input_dir) == elsewhere
    assert resolve_output_dir("", input_dir) is None
    assert resolve_output_dir(None, input_dir) is None


def test_standalone_gui_smoke(qapp, tmp_path):
    from palette_changer import MainWindow

    _files, input_dir = make_files(tmp_path)
    window = MainWindow()
    try:
        window.input_entry.setText(str(input_dir))
        window._load_palette()
        assert window.swatch_grid.count() > 0
        window.hue_slider.setValue(200)
        outline_button = next(
            button
            for button in (
                window.swatch_grid.itemAt(i).widget()
                for i in range(window.swatch_grid.count())
            )
            if button.toolTip() == "R 32, G 32, B 32"
        )
        outline_button.click()
        outline_button.click()
        assert window._mappings[(32, 32, 32)] == (32, 32, 32)
        out_dir = tmp_path / "out"
        window.output_entry.setText(str(out_dir))
        window._export()
        exported = out_dir / "A.png"
        assert exported.is_file()
        assert (32, 32, 32, 255) in set(
            Image.open(exported).convert("RGBA").get_flattened_data()
        )
    finally:
        window.close()


def test_adjust_color_matches_export_pipeline_exactly():
    from color_variants import adjust_color

    for rgb in [(100, 100, 100), (200, 100, 50), (250, 240, 3), (32, 32, 32)]:
        for brightness, saturation, contrast in [
            (1.5, 1.0, 1.0),
            (1.0, 2.0, 1.0),
            (1.0, 1.0, 0.5),
            (1.3, 1.7, 0.8),
            (1.0, 1.0, 1.0),
        ]:
            image = Image.new("RGBA", (1, 1), (*rgb, 255))
            through_pipeline = apply_adjustments(
                image, brightness, saturation, contrast
            ).getpixel((0, 0))[:3]
            assert (
                adjust_color(rgb, brightness, saturation, contrast) == through_pipeline
            )


def test_swatch_preview_shows_adjusted_color(qapp, tmp_path):
    from palette_changer import MainWindow

    _files, input_dir = make_files(tmp_path)
    window = MainWindow()
    try:
        window.input_entry.setText(str(input_dir))
        window._load_palette()
        blue_shade_button = next(
            window.swatch_grid.itemAt(i).widget()
            for i in range(window.swatch_grid.count())
            if window.swatch_grid.itemAt(i)
            .widget()
            .toolTip()
            .startswith("R 176, G 184")
        )
        window.hue_slider.setValue(120)
        blue_shade_button.click()
        blue_shade_button.click()
        delta = (120 - window._base_hue) % 360
        mapped = hue_shift((176, 184, 224), delta)
        window.adjustment_sliders["brightness"].setValue(50)
        shown = adjust_color(mapped, 0.5, 1.0, 1.0)
        fill = "#{:02x}{:02x}{:02x}".format(*shown)
        assert f"background-color: {fill}" in blue_shade_button.styleSheet()
    finally:
        window.close()


def test_hue_slider_drives_whole_detected_palette(qapp, tmp_path):
    from color_variants import hue_shift
    from palette_changer import MainWindow

    _files, input_dir = make_files(tmp_path)
    window = MainWindow()
    try:
        window.input_entry.setText(str(input_dir))
        window._load_palette()
        palette = list(window._mappings.keys())
        assert len(palette) >= 2
        assert window._base_hue is not None
        assert window.hue_slider.value() == window._base_hue
        assert all(window._mappings[rgb] == rgb for rgb in palette)
        window.hue_slider.setValue(90)
        delta = (90 - window._base_hue) % 360
        for rgb in palette:
            assert window._mappings[rgb] == hue_shift(rgb, delta)
        window.hue_slider.setValue(45)
        delta = (45 - window._base_hue) % 360
        for rgb in palette:
            assert window._mappings[rgb] == hue_shift(rgb, delta)
    finally:
        window.close()
