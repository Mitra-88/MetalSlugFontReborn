import platform
from pathlib import Path

import pytest
from PIL import Image

import rotsprite as rs
from rotsprite import QUALITY_CLEANEDGE, QUALITY_NEAREST, QUALITY_ROTSPRITE, rotate

ALL_QUALITIES = (QUALITY_ROTSPRITE, QUALITY_NEAREST, QUALITY_CLEANEDGE)
TRANSPARENT = (0, 0, 0, 0)
GOLDEN_DIR = Path(__file__).parent / "golden"


def _gradient_sprite():
    img = Image.new("RGBA", (4, 3))
    for y in range(3):
        for x in range(4):
            img.putpixel((x, y), (x * 60, y * 80, 128, 255))
    return img


def _glyph_sprite():
    img = Image.new("RGBA", (9, 6), TRANSPARENT)
    for y in range(6):
        for x in range(9):
            if (x * 3 + y * 5) % 4:
                img.putpixel((x, y), (200, 30, 10, 255))
    return img


def _dense_sprite():
    img = Image.new("RGBA", (78, 123))
    for y in range(123):
        for x in range(78):
            img.putpixel(
                (x, y), ((x * 31) % 256, (y * 47) % 256, (x * y * 13) % 256, 255)
            )
    return img


def _pixels(image):
    return list(image.get_flattened_data())


def _use_pure_python(monkeypatch):
    monkeypatch.setattr(rs, "_NATIVE_LIB", None)
    monkeypatch.setattr(rs, "_NATIVE_RESOLVED", True)


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
        for quality in ALL_QUALITIES:
            out = rotate(image, angle, quality)
            unknown = [px for px in out.get_flattened_data() if px not in allowed]
            assert unknown == [], (angle, quality, unknown[:3])


def test_solid_image_stays_solid_at_any_angle():
    image = Image.new("RGBA", (12, 7), (10, 200, 30, 255))
    for angle in (17, 45, 90, 260):
        for quality in ALL_QUALITIES:
            out = rotate(image, angle, quality)
            colors = set(out.get_flattened_data())
            assert colors <= {(10, 200, 30, 255), TRANSPARENT}
            assert (10, 200, 30, 255) in colors
            assert all(px[3] in (0, 255) for px in colors)


def test_clockwise_rotation_moves_top_left_to_top_right():
    image = Image.new("RGBA", (6, 6), TRANSPARENT)
    image.putpixel((0, 0), (255, 0, 0, 255))
    out = rotate(image, 90, QUALITY_ROTSPRITE)
    red = [
        (x, y)
        for y in range(out.height)
        for x in range(out.width)
        if out.getpixel((x, y))[3] == 255
    ]
    assert all(x == out.width - 1 for x, _y in red)
    assert red


def test_qualities_agree_on_canvas_size():
    image = Image.new("RGBA", (10, 6), (50, 60, 70, 255))
    for angle in (20, 55, 150):
        high = rotate(image, angle, QUALITY_ROTSPRITE)
        nearest = rotate(image, angle, QUALITY_NEAREST)
        clean = rotate(image, angle, QUALITY_CLEANEDGE)
        assert high.size == nearest.size == clean.size


def test_quality_is_deterministic():
    image = _gradient_sprite()
    first = rotate(image, 33, QUALITY_ROTSPRITE)
    second = rotate(image, 33, QUALITY_ROTSPRITE)
    assert _pixels(first) == _pixels(second)


def test_unknown_quality_raises():
    with pytest.raises(ValueError, match="quality"):
        rotate(_gradient_sprite(), 45, "bilinear")


def test_transparent_input_stays_transparent():
    image = Image.new("RGBA", (5, 5), TRANSPARENT)
    for quality in ALL_QUALITIES:
        out = rotate(image, 45, quality)
        assert set(out.get_flattened_data()) == {TRANSPARENT}


def test_oversized_input_degrades_to_nearest(monkeypatch):
    image = _gradient_sprite()
    monkeypatch.setattr(rs, "ROTSPRITE_MAX_PIXELS", 10)
    degraded = rotate(image, 30, QUALITY_ROTSPRITE)
    clean_degraded = rotate(image, 30, QUALITY_CLEANEDGE)
    monkeypatch.setattr(rs, "ROTSPRITE_MAX_PIXELS", 10**9)
    assert _pixels(degraded) == _pixels(rotate(image, 30, QUALITY_NEAREST))
    assert _pixels(clean_degraded) == _pixels(rotate(image, 30, QUALITY_NEAREST))


def test_float_ninety_multiples_are_exact_transposes():
    image = _gradient_sprite()
    for angle in (90.0, 180.0, 270.0):
        out = rotate(image, angle, QUALITY_ROTSPRITE)
        reference = (
            image.transpose(Image.Transpose.ROTATE_270)
            if angle == 90.0
            else rotate(image, int(angle), QUALITY_ROTSPRITE)
        )
        assert out.size == reference.size
        assert list(out.get_flattened_data()) == list(reference.get_flattened_data())


def test_non_finite_angles_are_rejected():
    image = _gradient_sprite()
    for angle in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite"):
            rotate(image, angle, QUALITY_ROTSPRITE)


def test_rotation_geometry_uses_float32_corners():
    # Aseprite builds the corners from gfx::PointF (float32). At 1 degree the
    # float32 result truncates one pixel left of the float64 result, so this
    # pins the precision as well as the rounding.
    assert rs._rotation_geometry(45, 115, 1) == (
        48,
        116,
        [(2, 0), (47, 1), (44, 116), (0, 115)],
    )


def test_scale_axis_maps_point_sampling():
    assert rs._scale_axis(1, 1) == [0]
    assert rs._scale_axis(8, 1) == [0]
    assert rs._scale_axis(8, 8) == [0, 1, 2, 3, 4, 5, 6, 7]
    assert rs._scale_axis(8, 3) == [0, 4, 7]
    assert rs._scale_axis(8, 4) == [0, 2, 5, 7]


def test_scale_point_from_eight_x_to_one_x():
    image = Image.new("RGBA", (8, 8))
    for y in range(8):
        for x in range(8):
            image.putpixel((x, y), (x * 30, y * 30, 1, 255))
    flat, w, h = rs._to_flat(image)
    out = rs._scale_point(flat, w, h, 1, 1)
    assert out == [flat[0]]
    assert rs._scale_point(flat, w, h, w, h) == flat


def test_parallelogram_quarter_turns_are_exact():
    w, h = 3, 2
    image = Image.new("RGBA", (w, h))
    for y in range(h):
        for x in range(w):
            image.putpixel((x, y), (x * 50, y * 60, 7, 255))
    flat, _, _ = rs._to_flat(image)
    cases = (
        ((w, h), [(0, 0), (w, 0), (w, h), (0, h)], image),
        ((h, w), [(h, 0), (h, w), (0, w), (0, 0)], image.transpose(Image.Transpose.ROTATE_270)),
        ((w, h), [(w, h), (0, h), (0, 0), (w, 0)], image.transpose(Image.Transpose.ROTATE_180)),
        ((h, w), [(0, w), (0, 0), (h, 0), (h, w)], image.transpose(Image.Transpose.ROTATE_90)),
    )
    for (dw, dh), corners, reference in cases:
        out = rs._to_image(rs._parallelogram(flat, w, h, dw, dh, corners), dw, dh)
        assert _pixels(out) == _pixels(reference)


def test_parallelogram_2x2_at_45_matches_aseprite_scanlines():
    # Aseprite's float32 corners at 45 degrees are (1, -0.41422),
    # (2.41422, 0.99999994), (0.99999994, 2.41422), (-0.41422, 1).
    # With leftTop (-1, -1), the float32 differences truncate to the integer
    # corners (2, 0), (3, 2), (2, 3), (0, 2) in a 3x3 canvas.
    # Scanline 0 spans x 1.5..2.25, so no pixel centre is covered and the
    # row stays empty. Scanline 1 spans 0.5..2.75 and scanline 2 spans
    # 1.0..2.5, both covering pixel centres 1.5 and 2.5.
    image = Image.new("RGBA", (2, 2))
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.putpixel((1, 0), (0, 255, 0, 255))
    image.putpixel((0, 1), (0, 0, 255, 255))
    image.putpixel((1, 1), (255, 255, 0, 255))
    expected = [
        TRANSPARENT, TRANSPARENT, TRANSPARENT,
        TRANSPARENT, (255, 0, 0, 255), (0, 255, 0, 255),
        TRANSPARENT, (255, 255, 0, 255), (255, 255, 0, 255),
    ]
    out = rotate(image, 45, QUALITY_NEAREST)
    assert out.size == (3, 3)
    assert _pixels(out) == expected


def test_cleanedge_2x2_at_45_matches_shader_port():
    # CleanEdge is not Aseprite, so this differs from the Nearest 3x3.
    image = Image.new("RGBA", (2, 2))
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.putpixel((1, 0), (0, 255, 0, 255))
    image.putpixel((0, 1), (0, 0, 255, 255))
    image.putpixel((1, 1), (255, 255, 0, 255))
    expected = [
        TRANSPARENT, TRANSPARENT, TRANSPARENT,
        TRANSPARENT, (255, 0, 0, 255), TRANSPARENT,
        TRANSPARENT, TRANSPARENT, TRANSPARENT,
    ]
    out = rotate(image, 45, QUALITY_CLEANEDGE)
    assert out.size == (3, 3)
    assert _pixels(out) == expected


def _closed_form(flat, sw, sh, dw, dh, corners):
    c0, c1, _c2, c3 = corners
    e1x, e1y = c1[0] - c0[0], c1[1] - c0[1]
    e2x, e2y = c3[0] - c0[0], c3[1] - c0[1]
    det = e1x * e2y - e2x * e1y
    out = [TRANSPARENT] * (dw * dh)
    for y in range(dh):
        for x in range(dw):
            d2x = 2 * x + 1 - 2 * c0[0]
            d2y = 2 * y + 1 - 2 * c0[1]
            num_u = sw * (d2x * e2y - d2y * e2x)
            num_v = sh * (e1x * d2y - e1y * d2x)
            den = 2 * det
            if den < 0:
                num_u, num_v, den = -num_u, -num_v, -den
            u, v = num_u // den, num_v // den
            if 0 <= u < sw and 0 <= v < sh:
                out[y * dw + x] = flat[v * sw + u]
    return out


def test_closed_form_differs_at_a_covered_edge():
    # Pixel (1, 0) has its centre exactly on the top-left edge, so the closed
    # form maps it to source u=0 and draws it. Aseprite's half-up scanline
    # start rounds past the edge and leaves row 0 empty. That difference is
    # why the engine ports the scanlines instead of using the inverse map.
    image = Image.new("RGBA", (2, 2))
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.putpixel((1, 0), (0, 255, 0, 255))
    image.putpixel((0, 1), (0, 0, 255, 255))
    image.putpixel((1, 1), (255, 255, 0, 255))
    flat, w, h = rs._to_flat(image)
    corners = rs._rotation_geometry(w, h, 45)[2]
    scanlines = rs._parallelogram(flat, w, h, 3, 3, corners)
    closed = _closed_form(flat, w, h, 3, 3, corners)
    assert closed[1] == flat[0]
    assert scanlines[1] == rs.NEUTRAL


def test_scale2x_each_output_pixel():
    p = (1, 1, 1, 255)
    x = (200, 0, 0, 255)
    y = (0, 200, 0, 255)
    z = (0, 0, 200, 255)
    packed_x = rs._to_flat(Image.new("RGBA", (1, 1), x))[0][0]
    cases = (
        # TL: left equals up, and differs from down and right.
        (((p, x, p), (x, p, z), (p, y, p)), 0),
        # TR: up equals right, and differs from left and down.
        (((p, x, p), (y, p, x), (p, z, p)), 1),
        # BL: down equals left, and differs from right and up.
        (((p, y, p), (x, p, z), (p, x, p)), 2),
        # BR: right equals down, and differs from up and left.
        (((p, z, p), (y, p, x), (p, x, p)), 3),
    )
    for rows, slot in cases:
        image = Image.new("RGBA", (3, 3))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                image.putpixel((column, row), value)
        flat, w, h = rs._to_flat(image)
        out, ow, _oh = rs._scale2x_pass(flat, w, h)
        index = (2 + slot // 2) * ow + 2 + slot % 2
        assert out[index] == packed_x

    all_same = Image.new("RGBA", (3, 3), x)
    flat, w, h = rs._to_flat(all_same)
    out, ow, _oh = rs._scale2x_pass(flat, w, h)
    assert out == [packed_x] * (ow * h * 2)


def test_native_matches_pure(monkeypatch):
    if rs._load_native() is None:
        pytest.skip("native rotsprite library not built")
    image = _gradient_sprite()
    for quality in ALL_QUALITIES:
        native = rs.rotate(image, 30, quality)
        _use_pure_python(monkeypatch)
        pure = rs.rotate(image, 30, quality)
        assert native.size == pure.size, quality
        assert native.tobytes() == pure.tobytes(), quality


def test_native_matches_pure_across_quadrants(monkeypatch):
    if rs._load_native() is None:
        pytest.skip("native rotsprite library not built")
    image = _gradient_sprite()
    for source in (image, _glyph_sprite()):
        for angle in (15, 30, 33, 77, 118.5, 150, 205, 225, 270, 300, 359.75):
            for quality in ALL_QUALITIES:
                native = rs.rotate(source, angle, quality)
                _use_pure_python(monkeypatch)
                pure = rs.rotate(source, angle, quality)
                monkeypatch.setattr(rs, "_NATIVE_RESOLVED", False)
                monkeypatch.setattr(rs, "_NATIVE_LIB", None)
                assert rs._load_native() is not None
                assert native.size == pure.size, (source.size, angle, quality)
                assert native.tobytes() == pure.tobytes(), (source.size, angle, quality)


def test_native_matches_pure_at_a_float_angle(monkeypatch):
    if rs._load_native() is None:
        pytest.skip("native rotsprite library not built")
    source = _dense_sprite()
    for quality in ALL_QUALITIES:
        native = rs.rotate(source, 28.44369954375634, quality)
        _use_pure_python(monkeypatch)
        pure = rs.rotate(source, 28.44369954375634, quality)
        monkeypatch.setattr(rs, "_NATIVE_RESOLVED", False)
        monkeypatch.setattr(rs, "_NATIVE_LIB", None)
        assert rs._load_native() is not None
        assert native.size == pure.size, quality
        assert native.tobytes() == pure.tobytes(), quality


def test_platform_trig_loader_is_available():
    assert rs._TRIG_LIB is not None


def _golden_source(name):
    sources = {
        "gradient": _gradient_sprite,
        "glyph": _glyph_sprite,
        "dense78x123": _dense_sprite,
    }
    return sources[name]()


def test_aseprite_golden_images():
    if not GOLDEN_DIR.exists():
        pytest.skip("Tests/golden is empty")
    paths = sorted(GOLDEN_DIR.glob("*.png"))
    if not paths:
        pytest.skip("Tests/golden is empty")
    qualities = {"rotsprite": QUALITY_ROTSPRITE, "nearest": QUALITY_NEAREST}
    for path in paths:
        # The dense78x123 float-angle golden was produced with MSVC cosf/sinf.
        # glibc and Apple libm can differ by one ULP at that near-midpoint angle.
        if path.stem.startswith("dense78x123_") and platform.system() != "Windows":
            continue
        try:
            sprite_name, angle, quality_name = path.stem.split("_")
            source = _golden_source(sprite_name)
            quality = qualities[quality_name]
        except (ValueError, KeyError) as error:
            raise AssertionError(
                f"{path.name}: name must be <sprite>_<angle>_<rotsprite|nearest>.png"
            ) from error
        expected = Image.open(path).convert("RGBA")
        out = rotate(source, float(angle), quality)
        assert out.size == expected.size, path.name
        assert out.tobytes() == expected.tobytes(), path.name
