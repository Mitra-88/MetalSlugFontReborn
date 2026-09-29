
import pytest
from PIL import Image

import rotsprite as rs
from rotsprite import (
    QUALITY_FAST_ROTSPRITE,
    QUALITY_NEAREST,
    QUALITY_ROTSPRITE,
    rotate,
)

ALL_QUALITIES = (QUALITY_FAST_ROTSPRITE, QUALITY_ROTSPRITE, QUALITY_NEAREST)
TRANSPARENT = (0, 0, 0, 0)


def _gradient_sprite():
    img = Image.new("RGBA", (4, 3))
    for y in range(3):
        for x in range(4):
            img.putpixel((x, y), (x * 60, y * 80, 128, 255))
    return img


def _pixels(image):
    return list(image.get_flattened_data())


def test_zero_angle_is_identity_for_all_qualities():
    image = _gradient_sprite()
    for quality in ALL_QUALITIES:
        out = rotate(image, 0, quality)
        assert out.size == image.size
        assert _pixels(out) == _pixels(image)


def test_90_degree_multiples_are_exact_transposes():
    image = _gradient_sprite()
    expected = {
        90: image.transpose(Image.Transpose.ROTATE_270),
        180: image.transpose(Image.Transpose.ROTATE_180),
        270: image.transpose(Image.Transpose.ROTATE_90),
    }
    for angle, reference in expected.items():
        for quality in ALL_QUALITIES:
            out = rotate(image, angle, quality)
            assert _pixels(out) == _pixels(reference), (angle, quality)


def test_rotation_never_introduces_new_colors():
    image = Image.new("RGBA", (8, 8), TRANSPARENT)
    for x, color in (
        (0, (255, 0, 0, 255)),
        (3, (0, 255, 0, 255)),
        (7, (32, 32, 32, 255)),
    ):
        for y in range(8):
            image.putpixel((x, y), color)
    allowed = set(_pixels(image))
    for angle in (15, 33, 77, 205, 300):
        for quality in (QUALITY_FAST_ROTSPRITE, QUALITY_ROTSPRITE):
            out = rotate(image, angle, quality)
            unknown = [px for px in out.get_flattened_data() if px not in allowed]
            assert unknown == [], (angle, quality, unknown[:3])


def test_solid_image_stays_solid_at_any_angle():
    image = Image.new("RGBA", (12, 7), (10, 200, 30, 255))
    for angle in (17, 45, 90, 260):
        for quality in (QUALITY_FAST_ROTSPRITE, QUALITY_ROTSPRITE):
            out = rotate(image, angle, quality)
            colors = set(out.get_flattened_data())
            assert colors <= {(10, 200, 30, 255), TRANSPARENT}
            assert (10, 200, 30, 255) in colors
            assert all(px[3] in (0, 255) for px in colors)


def test_clockwise_rotation_moves_top_left_to_top_right():
    image = Image.new("RGBA", (6, 6), TRANSPARENT)
    image.putpixel((0, 0), (255, 0, 0, 255))
    out = rotate(image, 90, QUALITY_FAST_ROTSPRITE)
    red = [
        (x, y)
        for y in range(out.height)
        for x in range(out.width)
        if out.getpixel((x, y))[3] == 255
    ]
    assert all(x == out.width - 1 for x, _y in red)
    assert red


def test_rotsprite_and_fast_agree_on_solid_shapes():
    image = Image.new("RGBA", (10, 6), (50, 60, 70, 255))
    for angle in (20, 55, 150):
        fast = rotate(image, angle, QUALITY_FAST_ROTSPRITE)
        high = rotate(image, angle, QUALITY_ROTSPRITE)
        nearest = rotate(image, angle, QUALITY_NEAREST)
        assert fast.size == high.size == nearest.size
        assert set(fast.get_flattened_data()) == set(high.get_flattened_data())


def test_quality_is_deterministic():
    image = _gradient_sprite()
    first = rotate(image, 33, QUALITY_FAST_ROTSPRITE)
    second = rotate(image, 33, QUALITY_FAST_ROTSPRITE)
    assert _pixels(first) == _pixels(second)


def test_unknown_quality_raises():
    with pytest.raises(ValueError, match="quality"):
        rotate(_gradient_sprite(), 45, "bilinear")


def test_transparent_input_stays_transparent():
    image = Image.new("RGBA", (5, 5), TRANSPARENT)
    for quality in ALL_QUALITIES:
        out = rotate(image, 45, quality)
        assert set(out.get_flattened_data()) == {TRANSPARENT}


def test_oversized_input_degrades_quality(monkeypatch):
    image = _gradient_sprite()
    monkeypatch.setattr(rs, "ROTSPRITE_MAX_PIXELS", 10)
    degraded = rotate(image, 30, QUALITY_ROTSPRITE)
    monkeypatch.setattr(rs, "ROTSPRITE_MAX_PIXELS", 10**9)
    assert _pixels(degraded) == _pixels(rotate(image, 30, QUALITY_FAST_ROTSPRITE))

    monkeypatch.setattr(rs, "FAST_MAX_PIXELS", 5)
    degraded = rotate(image, 30, QUALITY_FAST_ROTSPRITE)
    monkeypatch.setattr(rs, "FAST_MAX_PIXELS", 10**9)
    assert _pixels(degraded) == _pixels(rotate(image, 30, QUALITY_NEAREST))


def test_native_matches_pure(monkeypatch):
    if rs._load_native() is None:
        pytest.skip("native rotsprite library not built")
    image = _gradient_sprite()
    for quality in ALL_QUALITIES:
        native = rs.rotate(image, 30, quality)
        monkeypatch.setattr(rs, "_NATIVE_LIB", None)
        monkeypatch.setattr(rs, "_NATIVE_RESOLVED", True)
        pure = rs.rotate(image, 30, quality)
        assert native.size == pure.size, quality
        assert native.tobytes() == pure.tobytes(), quality


def test_float_ninety_multiples_are_exact_transposes():
    image = _gradient_sprite()
    for angle in (90.0, 180.0, 270.0):
        out = rotate(image, angle, QUALITY_FAST_ROTSPRITE)
        reference = image.transpose(
            Image.Transpose.ROTATE_270
        ) if angle == 90.0 else rotate(image, int(angle), QUALITY_FAST_ROTSPRITE)
        assert out.size == reference.size
        assert list(out.get_flattened_data()) == list(
            reference.get_flattened_data()
        )


def test_native_matches_pure_across_quadrants(monkeypatch):
    if rs._load_native() is None:
        pytest.skip("native rotsprite library not built")
    image = _gradient_sprite()
    for angle in (30, 118.5, 150, 205, 225, 270, 359.75):
        for quality in ALL_QUALITIES:
            native = rs.rotate(image, angle, quality)
            monkeypatch.setattr(rs, "_NATIVE_LIB", None)
            monkeypatch.setattr(rs, "_NATIVE_RESOLVED", True)
            pure = rs.rotate(image, angle, quality)
            assert native.size == pure.size, (angle, quality)
            assert native.tobytes() == pure.tobytes(), (angle, quality)
            monkeypatch.setattr(rs, "_NATIVE_RESOLVED", False)
            monkeypatch.setattr(rs, "_NATIVE_LIB", None)
            assert rs._load_native() is not None
