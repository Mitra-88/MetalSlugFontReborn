import ctypes
import ctypes.util
import os
import platform
import struct
import sys
from math import cos, floor, hypot, isfinite, pi, sin, sqrt
from pathlib import Path

from PIL import Image

QUALITY_ROTSPRITE = "RotSprite"
QUALITY_NEAREST = "Nearest"
QUALITY_CLEANEDGE = "CleanEdge"

NEUTRAL = 0
SCALE2X_PASSES = 3
SCALE2X_FACTOR = 1 << SCALE2X_PASSES
CLEANEDGE_FACTOR = 4
CLEANEDGE_LINE_WIDTH = 1.0

# ponytail: RotSprite degrades to Nearest on huge inputs because an 8x pass on
# a multi-megapixel image costs hundreds of MB and seconds even natively,
# while real sprites are tiny. Raise this only with fresh profiler evidence.
ROTSPRITE_MAX_PIXELS = 250_000


def _to_flat(image):
    data = image.tobytes()
    flat = []
    append = flat.append
    for i in range(0, len(data), 4):
        append((data[i] << 24) | (data[i + 1] << 16) | (data[i + 2] << 8) | data[i + 3])
    return flat, image.width, image.height


def _to_image(flat, w, h):
    buf = bytearray(len(flat) * 4)
    for i, px in enumerate(flat):
        buf[i * 4] = (px >> 24) & 255
        buf[i * 4 + 1] = (px >> 16) & 255
        buf[i * 4 + 2] = (px >> 8) & 255
        buf[i * 4 + 3] = px & 255
    return Image.frombytes("RGBA", (w, h), bytes(buf))


def _scale2x_pass(flat, w, h):
    ow = w * 2
    out = [NEUTRAL] * (ow * h * 2)
    for y in range(h):
        y_up = y - 1 if y > 0 else 0
        y_down = y + 1 if y < h - 1 else y
        row_up = y_up * w
        row = y * w
        row_down = y_down * w
        out_row = y * 2 * ow
        out_row2 = out_row + ow
        for x in range(w):
            x_left = x - 1 if x > 0 else 0
            x_right = x + 1 if x < w - 1 else x
            p = flat[row + x]
            up = flat[row_up + x]
            down = flat[row_down + x]
            left = flat[row + x_left]
            right = flat[row + x_right]

            if left == up and left != down and up != right:
                tl = up
            else:
                tl = p
            if up == right and up != left and right != down:
                tr = right
            else:
                tr = p
            if down == left and down != right and left != up:
                bl = left
            else:
                bl = p
            if right == down and right != up and down != left:
                br = down
            else:
                br = p

            out[out_row + x * 2] = tl
            out[out_row + x * 2 + 1] = tr
            out[out_row2 + x * 2] = bl
            out[out_row2 + x * 2 + 1] = br
    return out, ow, h * 2


# CleanEdge (torcado, MIT) ported from cleanEdge-shadertoy.glsl with
# SLOPE and CLEANUP enabled, lineWidth 1.0, similarThreshold 0 and
# highestColor white. It is not an Aseprite algorithm: Aseprite has no
# equivalent, so no golden test covers it. Colours are (r, g, b, a) bytes.
# With a zero threshold, "similar" is colour equality, or both transparent.


def _ce_unpack(px):
    return ((px >> 24) & 255, (px >> 16) & 255, (px >> 8) & 255, px & 255)


def _ce_pack(colour):
    return (colour[0] << 24) | (colour[1] << 16) | (colour[2] << 8) | colour[3]


def _ce_similar(a, b):
    return (a[3] == 0 and b[3] == 0) or a == b


def _ce_similar3(a, b, c):
    return _ce_similar(a, b) and _ce_similar(b, c)


def _ce_similar4(a, b, c, d):
    return _ce_similar(a, b) and _ce_similar(b, c) and _ce_similar(c, d)


def _ce_cd(a, b):
    r = (a[0] - b[0]) / 255.0
    g = (a[1] - b[1]) / 255.0
    b2 = (a[2] - b[2]) / 255.0
    al = (a[3] - b[3]) / 255.0
    return sqrt(r * r + g * g + b2 * b2 + al * al)


def _ce_higher(a, b):
    if _ce_similar(a, b):
        return False
    if a[3] == b[3]:
        da = (255 - a[0]) ** 2 + (255 - a[1]) ** 2 + (255 - a[2]) ** 2
        db = (255 - b[0]) ** 2 + (255 - b[1]) ** 2 + (255 - b[2]) ** 2
        return da < db
    return a[3] > b[3]


def _ce_dist_to_line(test_pt, pt1, pt2, direction):
    line_x = pt2[0] - pt1[0]
    line_y = pt2[1] - pt1[1]
    perp_x = line_y
    perp_y = -line_x
    length = sqrt(perp_x * perp_x + perp_y * perp_y)
    sign = 1.0 if (perp_x * direction[0] + perp_y * direction[1]) > 0.0 else -1.0
    to_x = pt1[0] - test_pt[0]
    to_y = pt1[1] - test_pt[1]
    return sign * ((perp_x / length) * to_x + (perp_y / length) * to_y)


def _ce_add(base, offset, point_dir):
    return (
        base[0] + offset[0] * point_dir[0],
        base[1] + offset[1] * point_dir[1],
    )


def _ce_slice_dist(
    point,
    main_dir,
    point_dir,
    ub,
    u,
    uf,
    uff,
    b,
    c,
    f,
    ff,
    db,
    d,
    df,
    dff,
    ddb,
    dd,
    ddf,
):
    line_width = max(0.45, min(1.142, CLEANEDGE_LINE_WIDTH))
    point = (
        main_dir[0] * (point[0] - 0.5) + 0.5,
        main_dir[1] * (point[1] - 0.5) + 0.5,
    )
    dist_against = 4.0 * _ce_cd(f, d) + _ce_cd(uf, c) + _ce_cd(c, db) + _ce_cd(ff, df) + _ce_cd(df, dd)
    dist_towards = 4.0 * _ce_cd(c, df) + _ce_cd(u, f) + _ce_cd(f, dff) + _ce_cd(b, d) + _ce_cd(d, ddf)
    should_slice = dist_against < dist_towards or (
        dist_against < dist_towards + 0.001 and not _ce_higher(c, f)
    )
    if _ce_similar4(f, d, b, u) and _ce_similar4(uf, df, db, ub) and not _ce_similar(c, f):
        should_slice = False
    if not should_slice:
        return None

    dist = 1.0
    flip = False
    center = (0.5, 0.5)

    if _ce_similar3(f, d, db) and not _ce_similar3(f, d, b) and not _ce_similar(uf, db):
        if _ce_similar(c, df) and _ce_higher(c, f):
            pass
        else:
            if _ce_higher(c, f):
                flip = True
            if _ce_similar(u, f) and not _ce_similar(c, df) and not _ce_higher(c, u):
                flip = True
        if flip:
            dist = line_width - _ce_dist_to_line(
                point,
                _ce_add(center, (1.5, -1.0), point_dir),
                _ce_add(center, (-0.5, 0.0), point_dir),
                (-point_dir[0], -point_dir[1]),
            )
        else:
            dist = _ce_dist_to_line(
                point,
                _ce_add(center, (1.5, 0.0), point_dir),
                _ce_add(center, (-0.5, 1.0), point_dir),
                point_dir,
            )
        if not flip and _ce_similar(c, uf) and not (
            _ce_similar3(c, uf, uff) and not _ce_similar3(c, uf, ff) and not _ce_similar(d, uff)
        ):
            dist2 = _ce_dist_to_line(
                point,
                _ce_add(center, (2.0, -1.0), point_dir),
                _ce_add(center, (0.0, 1.0), point_dir),
                point_dir,
            )
            dist = min(dist, dist2)
        dist -= line_width / 2.0
        return (f if _ce_cd(c, f) <= _ce_cd(c, d) else d) if dist <= 0.0 else None

    if _ce_similar3(uf, f, d) and not _ce_similar3(u, f, d) and not _ce_similar(uf, db):
        if _ce_similar(c, df) and _ce_higher(c, d):
            pass
        else:
            if _ce_higher(c, d):
                flip = True
            if _ce_similar(b, d) and not _ce_similar(c, df) and not _ce_higher(c, d):
                flip = True
        if flip:
            dist = line_width - _ce_dist_to_line(
                point,
                _ce_add(center, (0.0, -0.5), point_dir),
                _ce_add(center, (-1.0, 1.5), point_dir),
                (-point_dir[0], -point_dir[1]),
            )
        else:
            dist = _ce_dist_to_line(
                point,
                _ce_add(center, (1.0, -0.5), point_dir),
                _ce_add(center, (0.0, 1.5), point_dir),
                point_dir,
            )
        if not flip and _ce_similar(c, db) and not (
            _ce_similar3(c, db, ddb) and not _ce_similar3(c, db, dd) and not _ce_similar(f, ddb)
        ):
            dist2 = _ce_dist_to_line(
                point,
                _ce_add(center, (1.0, 0.0), point_dir),
                _ce_add(center, (-1.0, 2.0), point_dir),
                point_dir,
            )
            dist = min(dist, dist2)
        dist -= line_width / 2.0
        return (f if _ce_cd(c, f) <= _ce_cd(c, d) else d) if dist <= 0.0 else None

    if _ce_similar(f, d):
        if _ce_similar(c, df) and _ce_higher(c, f):
            if not _ce_similar(c, dd) and not _ce_similar(c, ff):
                flip = True
        else:
            if _ce_higher(c, f):
                flip = True
            if not _ce_similar(c, b) and _ce_similar4(b, f, d, u):
                flip = True
        if (
            (_ce_similar(f, db) and _ce_similar3(u, f, df))
            or (_ce_similar(uf, d) and _ce_similar3(b, d, df))
        ) and not _ce_similar(c, df):
            flip = True
        if flip:
            dist = line_width - _ce_dist_to_line(
                point,
                _ce_add(center, (1.0, -1.0), point_dir),
                _ce_add(center, (-1.0, 1.0), point_dir),
                (-point_dir[0], -point_dir[1]),
            )
        else:
            dist = _ce_dist_to_line(
                point,
                _ce_add(center, (1.0, 0.0), point_dir),
                _ce_add(center, (0.0, 1.0), point_dir),
                point_dir,
            )
        if not flip and _ce_similar3(c, uf, uff) and not _ce_similar3(c, uf, ff) and not _ce_similar(d, uff):
            dist2 = _ce_dist_to_line(
                point,
                _ce_add(center, (1.5, 0.0), point_dir),
                _ce_add(center, (-0.5, 1.0), point_dir),
                point_dir,
            )
            dist = max(dist, dist2)
        if not flip and _ce_similar3(ddb, db, c) and not _ce_similar3(dd, db, c) and not _ce_similar(ddb, f):
            dist2 = _ce_dist_to_line(
                point,
                _ce_add(center, (1.0, -0.5), point_dir),
                _ce_add(center, (0.0, 1.5), point_dir),
                point_dir,
            )
            dist = max(dist, dist2)
        dist -= line_width / 2.0
        return (f if _ce_cd(c, f) <= _ce_cd(c, d) else d) if dist <= 0.0 else None

    if _ce_similar3(ff, df, d) and not _ce_similar3(ff, df, c) and not _ce_similar(uff, d):
        if _ce_similar(f, dff) and _ce_higher(f, ff):
            pass
        else:
            if _ce_higher(f, ff):
                flip = True
            if _ce_similar(uf, ff) and not _ce_similar(f, dff) and not _ce_higher(f, uf):
                flip = True
        if flip:
            dist = line_width - _ce_dist_to_line(
                point,
                _ce_add(center, (2.5, -1.0), point_dir),
                _ce_add(center, (0.5, 0.0), point_dir),
                (-point_dir[0], -point_dir[1]),
            )
        else:
            dist = _ce_dist_to_line(
                point,
                _ce_add(center, (2.5, 0.0), point_dir),
                _ce_add(center, (0.5, 1.0), point_dir),
                point_dir,
            )
        dist -= line_width / 2.0
        return (ff if _ce_cd(f, ff) <= _ce_cd(f, df) else df) if dist <= 0.0 else None

    if _ce_similar3(f, df, dd) and not _ce_similar3(c, df, dd) and not _ce_similar(f, ddb):
        if _ce_similar(d, ddf) and _ce_higher(d, dd):
            pass
        else:
            if _ce_higher(d, dd):
                flip = True
            if _ce_similar(db, dd) and not _ce_similar(d, ddf) and not _ce_higher(d, dd):
                flip = True
        if flip:
            dist = line_width - _ce_dist_to_line(
                point,
                _ce_add(center, (0.0, 0.5), point_dir),
                _ce_add(center, (-1.0, 2.5), point_dir),
                (-point_dir[0], -point_dir[1]),
            )
        else:
            dist = _ce_dist_to_line(
                point,
                _ce_add(center, (1.0, 0.5), point_dir),
                _ce_add(center, (0.0, 2.5), point_dir),
                point_dir,
            )
        dist -= line_width / 2.0
        return (df if _ce_cd(d, df) <= _ce_cd(d, dd) else dd) if dist <= 0.0 else None

    return None


def _clean_edge_upscale(flat, w, h, factor=CLEANEDGE_FACTOR):
    # The shader is a magnification filter: each input pixel becomes
    # factor x factor output pixels, each with its own local position
    # ((sub + 0.5) / factor) and quadrant. Neighbours are input texels.
    ow = w * factor
    oh = h * factor
    out = [NEUTRAL] * (ow * oh)
    for oy in range(oh):
        iy = oy // factor
        ly = ((factor - 1 - (oy % factor)) + 0.5) / factor
        for ox in range(ow):
            ix = ox // factor
            lx = ((ox % factor) + 0.5) / factor
            point = (lx, ly)
            point_dir = (
                1.0 if lx >= 0.5 else -1.0,
                1.0 if ly >= 0.5 else -1.0,
            )

            def sample(dx, dy, ix=ix, iy=iy, point_dir=point_dir):
                sx = min(max(ix + dx * int(point_dir[0]), 0), w - 1)
                sy = min(max(iy - dy * int(point_dir[1]), 0), h - 1)
                return _ce_unpack(flat[sy * w + sx])

            uub = sample(-1, -2)
            uu = sample(0, -2)
            uuf = sample(1, -2)
            ubb = sample(-2, -2)
            ub = sample(-1, -1)
            u = sample(0, -1)
            uf = sample(1, -1)
            uff = sample(2, -1)
            bb = sample(-2, 0)
            b = sample(-1, 0)
            c = sample(0, 0)
            f = sample(1, 0)
            ff = sample(2, 0)
            dbb = sample(-2, 1)
            db = sample(-1, 1)
            d = sample(0, 1)
            df = sample(1, 1)
            dff = sample(2, 1)
            ddb = sample(-1, 2)
            dd = sample(0, 2)
            ddf = sample(1, 2)

            colour = c
            c_col = _ce_slice_dist(
                point, (1.0, 1.0), point_dir,
                ub, u, uf, uff, b, c, f, ff, db, d, df, dff, ddb, dd, ddf,
            )
            if c_col is not None:
                colour = c_col
            b_col = _ce_slice_dist(
                point, (-1.0, 1.0), point_dir,
                uf, u, ub, ubb, f, c, b, bb, df, d, db, dbb, ddf, dd, ddb,
            )
            if b_col is not None:
                colour = b_col
            u_col = _ce_slice_dist(
                point, (1.0, -1.0), point_dir,
                db, d, df, dff, b, c, f, ff, ub, u, uf, uff, uub, uu, uuf,
            )
            if u_col is not None:
                colour = u_col
            out[oy * ow + ox] = _ce_pack(colour)
    return out, ow, oh


def _f32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def _load_trig():
    # Aseprite's std::cos(float) calls the platform cosf, not (float)cos(double).
    # They differ by a last ULP for some f32 angles, so use the same entry point.
    if platform.system() == "Windows":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        names = (
            os.path.join(system_root, "System32", "ucrtbase.dll"),
            "ucrtbase.dll",
            "ucrtbase",
        )
    elif platform.system() == "Darwin":
        names = ("libSystem.B.dylib", "/usr/lib/libSystem.B.dylib")
    else:
        names = (
            ctypes.util.find_library("m"),
            "libm.so.6",
            "libm.so",
            "libc.so.6",
            "libc.so",
        )
    for name in names:
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
            lib.cosf.argtypes = [ctypes.c_float]
            lib.cosf.restype = ctypes.c_float
            lib.sinf.argtypes = [ctypes.c_float]
            lib.sinf.restype = ctypes.c_float
            return lib
        except (OSError, AttributeError):
            continue
    return None


_TRIG_LIB = _load_trig()


def _cosf(value):
    if _TRIG_LIB is not None:
        return _TRIG_LIB.cosf(value)
    return cos(value)


def _sinf(value):
    if _TRIG_LIB is not None:
        return _TRIG_LIB.sinf(value)
    return sin(value)


def _round5(value):
    scaled = _f32(value * 100000.0)
    scaled = floor(scaled + 0.5) if scaled >= 0 else -floor(-scaled + 0.5)
    return _f32(scaled / 100000.0)


def _rotation_geometry(w, h, angle):
    # Aseprite stores the angle and every corner as float32 (`gfx::PointF`)
    # and rounds cos/sin to five decimals in Transformation::rotatePoint.
    rad = _f32((pi * angle) / 180.0)
    cos_t = _round5(_f32(_cosf(rad)))
    sin_t = _round5(_f32(_sinf(rad)))
    cx = _f32(w / 2.0)
    cy = _f32(h / 2.0)
    rotated = []
    for x, y in ((0.0, 0.0), (float(w), 0.0), (float(w), float(h)), (0.0, float(h))):
        dx = _f32(_f32(x) - cx)
        dy = _f32(_f32(y) - cy)
        rx = _f32(_f32(cx + _f32(dx * cos_t)) - _f32(dy * sin_t))
        ry = _f32(_f32(cy + _f32(dx * sin_t)) + _f32(dy * cos_t))
        rotated.append((rx, ry))
    min_x = min(p[0] for p in rotated)
    max_x = max(p[0] for p in rotated)
    min_y = min(p[1] for p in rotated)
    max_y = max(p[1] for p in rotated)
    left = floor(min_x)
    top = floor(min_y)
    out_w = int(_f32(_f32(max_x + 1.0) - min_x))
    out_h = int(_f32(_f32(max_y + 1.0) - min_y))
    left_f = _f32(left)
    top_f = _f32(top)
    corners = [
        (int(_f32(x - left_f)), int(_f32(y - top_f))) for x, y in rotated
    ]
    return out_w, out_h, corners


def _ftofix(value):
    if value > 32767.0:
        return 0x7FFFFFFF
    if value < -32767.0:
        return -0x7FFFFFFF
    return int(value * 65536.0 + (-0.5 if value < 0 else 0.5))


def _fixmul(a, b):
    return _ftofix((a / 65536.0) * (b / 65536.0))


def _fixdiv(a, b):
    if b == 0:
        return -0x7FFFFFFF if a < 0 else 0x7FFFFFFF
    return _ftofix((a / 65536.0) / (b / 65536.0))


def _out_of_range(fixed_value, size):
    return ((fixed_value >> 16) & 0xFFFFFFFF) >= size


def _scanline_bounds(l_bmp, r_bmp, l_spr_x, l_spr_y, spr_dx, spr_dy, sw, sh):
    if _out_of_range(l_spr_x, sw):
        if (l_spr_x < 0 and spr_dx <= 0) or (l_spr_x > 0 and spr_dx >= 0):
            return None
        while True:
            l_spr_x += spr_dx
            l_bmp += 65536
            if l_bmp > r_bmp:
                return None
            if not _out_of_range(l_spr_x, sw):
                break
    right = l_spr_x + ((r_bmp - l_bmp) >> 16) * spr_dx
    if _out_of_range(right, sw):
        if (right < 0 and spr_dx <= 0) or (right > 0 and spr_dx >= 0):
            while True:
                r_bmp -= 65536
                right -= spr_dx
                if l_bmp > r_bmp:
                    return None
                if not _out_of_range(right, sw):
                    break
        else:
            return None
    if _out_of_range(l_spr_y, sh):
        if (l_spr_y < 0 and spr_dy <= 0) or (l_spr_y > 0 and spr_dy >= 0):
            return None
        while True:
            l_spr_y += spr_dy
            l_bmp += 65536
            if l_bmp > r_bmp:
                return None
            if not _out_of_range(l_spr_y, sh):
                break
    right = l_spr_y + ((r_bmp - l_bmp) >> 16) * spr_dy
    if _out_of_range(right, sh):
        if (right < 0 and spr_dy <= 0) or (right > 0 and spr_dy >= 0):
            while True:
                r_bmp -= 65536
                right -= spr_dy
                if l_bmp > r_bmp:
                    return None
                if not _out_of_range(right, sh):
                    break
        else:
            return None
    return l_bmp, r_bmp, l_spr_x, l_spr_y


def _parallelogram(flat, sw, sh, dw, dh, corners):
    out = [NEUTRAL] * (dw * dh)
    if dw <= 0 or dh <= 0:
        return out

    xs = [x << 16 for x, _y in corners]
    ys = [y << 16 for _x, y in corners]

    top = 0
    for i in (1, 2, 3):
        if ys[i] < ys[top]:
            top = i
    if _fixmul(xs[(top + 1) & 3] - xs[top], ys[(top - 1) & 3] - ys[top]) > _fixmul(
        xs[(top - 1) & 3] - xs[top], ys[(top + 1) & 3] - ys[top]
    ):
        right_index = 1
    else:
        right_index = -1

    corner_bmp_x = [0] * 4
    corner_bmp_y = [0] * 4
    corner_spr_x = [0] * 4
    corner_spr_y = [0] * 4
    index = top
    for i in range(4):
        corner_bmp_x[i] = xs[index]
        corner_bmp_y[i] = ys[index]
        corner_spr_y[i] = 0 if index < 2 else (sh << 16) - 1
        corner_spr_x[i] = 0 if index in (0, 3) else (sw << 16) - 1
        index = (index + right_index) & 3

    top_x, top_y = corner_bmp_x[0], corner_bmp_y[0]
    right_x, right_y = corner_bmp_x[1], corner_bmp_y[1]
    bottom_x, bottom_y = corner_bmp_x[2], corner_bmp_y[2]
    left_x, left_y = corner_bmp_x[3], corner_bmp_y[3]

    clip_left = 0
    clip_right = (dw << 16) - 1
    if left_x > clip_right and top_x > clip_right and bottom_x > clip_right:
        return out
    if right_x < clip_left and top_x < clip_left and bottom_x < clip_left:
        return out

    clip_bottom = (bottom_y + 0x8000) >> 16
    clip_bottom = min(clip_bottom, dh)
    bmp_y = (top_y + 0x8000) >> 16
    bmp_y = max(bmp_y, 0)
    if bmp_y >= clip_bottom:
        return out

    extra = (bmp_y << 16) + 0x8000 - top_y
    l_bmp_dx = _fixdiv(left_x - top_x, left_y - top_y)
    l_bmp_x = top_x + _fixmul(extra, l_bmp_dx)
    l_spr_dx = _fixdiv(corner_spr_x[3] - corner_spr_x[0], left_y - top_y)
    l_spr_x = corner_spr_x[0] + _fixmul(extra, l_spr_dx)
    l_spr_dy = _fixdiv(corner_spr_y[3] - corner_spr_y[0], left_y - top_y)
    l_spr_y = corner_spr_y[0] + _fixmul(extra, l_spr_dy)

    l_bottom = (left_y + 0x8000) >> 16
    l_bottom = min(l_bottom, clip_bottom)

    r_bmp_dx = _fixdiv(right_x - top_x, right_y - top_y)
    r_bmp_x = top_x + _fixmul(extra, r_bmp_dx)
    r_bottom = (right_y + 0x8000) >> 16

    spr_dx_den = (xs[1] - xs[0]) * float(ys[3] - ys[0]) - (xs[3] - xs[0]) * float(
        ys[1] - ys[0]
    )
    spr_dy_den = (xs[3] - xs[0]) * float(ys[1] - ys[0]) - (xs[1] - xs[0]) * float(
        ys[3] - ys[0]
    )
    if spr_dx_den == 0.0 or spr_dy_den == 0.0:
        return out
    spr_dx = int(
        (ys[3] - ys[0])
        * 65536.0
        * (65536.0 * sw)
        / spr_dx_den
    )
    spr_dy = int(
        (ys[1] - ys[0])
        * 65536.0
        * (65536.0 * sh)
        / spr_dy_den
    )

    while True:
        if bmp_y >= l_bottom:
            if bmp_y >= clip_bottom:
                break
            extra = (bmp_y << 16) + 0x8000 - left_y
            l_bmp_dx = _fixdiv(bottom_x - left_x, bottom_y - left_y)
            l_bmp_x = left_x + _fixmul(extra, l_bmp_dx)
            l_spr_dx = _fixdiv(corner_spr_x[2] - corner_spr_x[3], bottom_y - left_y)
            l_spr_x = corner_spr_x[3] + _fixmul(extra, l_spr_dx)
            l_spr_dy = _fixdiv(corner_spr_y[2] - corner_spr_y[3], bottom_y - left_y)
            l_spr_y = corner_spr_y[3] + _fixmul(extra, l_spr_dy)
            l_bottom = (bottom_y + 0x8000) >> 16
            l_bottom = min(l_bottom, clip_bottom)

        if bmp_y >= r_bottom:
            extra = (bmp_y << 16) + 0x8000 - right_y
            r_bmp_dx = _fixdiv(bottom_x - right_x, bottom_y - right_y)
            r_bmp_x = right_x + _fixmul(extra, r_bmp_dx)
            r_bottom = clip_bottom

        l_bmp_round = (l_bmp_x + 0x8000) & ~0xFFFF
        l_bmp_round = max(l_bmp_round, clip_left)
        l_spr_x_round = l_spr_x + _fixmul(l_bmp_round + 0x7FFF - l_bmp_x, spr_dx)
        l_spr_y_round = l_spr_y + _fixmul(l_bmp_round + 0x7FFF - l_bmp_x, spr_dy)

        r_bmp_round = (r_bmp_x - 0x8000) & ~0xFFFF
        r_bmp_round = min(r_bmp_round, clip_right)

        if l_bmp_round <= r_bmp_round:
            bounds = _scanline_bounds(
                l_bmp_round,
                r_bmp_round,
                l_spr_x_round,
                l_spr_y_round,
                spr_dx,
                spr_dy,
                sw,
                sh,
            )
            if bounds is not None:
                l_bmp_round, r_bmp_round, l_spr_x_round, l_spr_y_round = bounds
                x0 = l_bmp_round >> 16
                x1 = r_bmp_round >> 16
                u = l_spr_x_round
                v = l_spr_y_round
                row = bmp_y * dw
                for x in range(x0, x1 + 1):
                    su = u >> 16
                    sv = v >> 16
                    if 0 <= su < sw and 0 <= sv < sh:
                        out[row + x] = flat[sv * sw + su]
                    u += spr_dx
                    v += spr_dy

        bmp_y += 1
        l_bmp_x += l_bmp_dx
        l_spr_x += l_spr_dx
        l_spr_y += l_spr_dy
        r_bmp_x += r_bmp_dx

    return out


def _scale_axis(src_n, dst_n):
    if dst_n <= 1 or src_n <= 1:
        return [0] * max(dst_n, 0)
    step = _fixdiv((src_n - 1) << 16, (dst_n - 1) << 16)
    return [((i * step) >> 16) + (((i * step) & 0x8000) >> 15) for i in range(dst_n)]


def _scale_point(flat, sw, sh, dw, dh):
    out = [NEUTRAL] * (dw * dh)
    xs = _scale_axis(sw, dw)
    ys = _scale_axis(sh, dh)
    for y in range(dh):
        sy = ys[y]
        if sy >= sh:
            continue
        src_row = sy * sw
        dst_row = y * dw
        for x in range(dw):
            sx = xs[x]
            if sx < sw:
                out[dst_row + x] = flat[src_row + sx]
    return out


def _rotate_upscaled(flat, w, h, factor, out_w, out_h, corners):
    xs = [x for x, _y in corners]
    ys = [y for _x, y in corners]
    xmin = min(xs)
    xmax = max(xs)
    ymin = min(ys)
    ymax = max(ys)
    rot_w = xmax - xmin
    rot_h = ymax - ymin
    dst_w = min(rot_w, out_w - xmin)
    dst_h = min(rot_h, out_h - ymin)
    out = [NEUTRAL] * (out_w * out_h)
    if rot_w > 0 and rot_h > 0 and dst_w > 0 and dst_h > 0:
        scaled = [((x - xmin) * factor, (y - ymin) * factor) for x, y in corners]
        rotated = _parallelogram(
            flat, w, h, rot_w * factor, rot_h * factor, scaled
        )
        content = _scale_point(
            rotated,
            rot_w * factor,
            rot_h * factor,
            dst_w,
            dst_h,
        )
        for y in range(dst_h):
            dst = (ymin + y) * out_w + xmin
            src = y * dst_w
            out[dst : dst + dst_w] = content[src : src + dst_w]
    return out


def _rotate_nearest(flat, w, h, out_w, out_h, corners):
    return _to_image(_parallelogram(flat, w, h, out_w, out_h, corners), out_w, out_h)


def _rotate_rotsprite(flat, w, h, out_w, out_h, corners):
    for _ in range(SCALE2X_PASSES):
        flat, w, h = _scale2x_pass(flat, w, h)
    return _to_image(
        _rotate_upscaled(flat, w, h, SCALE2X_FACTOR, out_w, out_h, corners),
        out_w,
        out_h,
    )


def _rotate_cleanedge(flat, w, h, out_w, out_h, corners):
    flat, w, h = _clean_edge_upscale(flat, w, h)
    return _to_image(
        _rotate_upscaled(flat, w, h, CLEANEDGE_FACTOR, out_w, out_h, corners),
        out_w,
        out_h,
    )


def _rotate_generic(image, angle, quality):
    if angle > 180.0:
        angle -= 360.0
    flat, w, h = _to_flat(image)
    out_w, out_h, corners = _rotation_geometry(w, h, angle)
    if out_w <= 0 or out_h <= 0:
        return Image.new("RGBA", (max(out_w, 1), max(out_h, 1)), (0, 0, 0, 0))

    if quality == QUALITY_NEAREST:
        return _rotate_nearest(flat, w, h, out_w, out_h, corners)
    if quality == QUALITY_CLEANEDGE:
        return _rotate_cleanedge(flat, w, h, out_w, out_h, corners)
    return _rotate_rotsprite(flat, w, h, out_w, out_h, corners)


def _rotate_pure_python(image, angle, quality):
    image = image.convert("RGBA")
    angle = angle % 360
    if not isfinite(angle):
        raise ValueError("rotation angle must be a finite number")
    if angle == 0:
        return image.copy()
    return _rotate_generic(image, angle, quality)


_NATIVE_LIB = None
_NATIVE_RESOLVED = False


def _library_candidates():
    here = Path(__file__).resolve().parent
    if platform.system() == "Windows":
        names = ["msfr_rotsprite.dll"]
    elif platform.system() == "Darwin":
        names = ["libmsfr_rotsprite.dylib"]
    else:
        names = ["libmsfr_rotsprite.so"]
    for name in names:
        yield here / name
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            yield Path(meipass) / name
        release = here.parent / "rust" / "rotsprite-rs" / "target" / "release" / name
        yield release


def _load_native():
    global _NATIVE_LIB, _NATIVE_RESOLVED
    if _NATIVE_RESOLVED:
        return _NATIVE_LIB
    _NATIVE_RESOLVED = True
    if os.environ.get("MSFR_ROTSPRITE_PURE") == "1":
        return None
    for candidate in _library_candidates():
        if candidate.exists():
            try:
                lib = ctypes.CDLL(str(candidate))
                lib.msfr_rotate.argtypes = [
                    ctypes.c_char_p,
                    ctypes.c_size_t,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.c_double,
                    ctypes.c_uint32,
                    ctypes.POINTER(ctypes.c_ubyte),
                    ctypes.c_size_t,
                    ctypes.POINTER(ctypes.c_size_t),
                    ctypes.POINTER(ctypes.c_uint32),
                    ctypes.POINTER(ctypes.c_uint32),
                ]
                lib.msfr_rotate.restype = ctypes.c_int
                _NATIVE_LIB = lib
            except (OSError, AttributeError):
                _NATIVE_LIB = None
            break
    return _NATIVE_LIB


def _rotate_native(image, angle, quality):
    lib = _load_native()
    if lib is None:
        return None
    src = image.tobytes()
    width, height = image.size
    side = int(hypot(width, height)) + 2
    cap = side * side * 4
    out = (ctypes.c_ubyte * cap)()
    out_len = ctypes.c_size_t()
    out_w = ctypes.c_uint32()
    out_h = ctypes.c_uint32()
    mode = {QUALITY_ROTSPRITE: 0, QUALITY_NEAREST: 1, QUALITY_CLEANEDGE: 2}[quality]
    rc = lib.msfr_rotate(
        src,
        len(src),
        width,
        height,
        float(angle),
        mode,
        out,
        cap,
        ctypes.byref(out_len),
        ctypes.byref(out_w),
        ctypes.byref(out_h),
    )
    if rc != 0:
        return _rotate_pure_python(image, angle, quality)
    return Image.frombytes(
        "RGBA", (out_w.value, out_h.value), ctypes.string_at(out, out_len.value)
    )


def rotate(image, angle, quality=QUALITY_ROTSPRITE):
    if quality not in (QUALITY_ROTSPRITE, QUALITY_NEAREST, QUALITY_CLEANEDGE):
        raise ValueError(f"unknown rotation quality: {quality!r}")
    image = image.convert("RGBA")
    angle = angle % 360
    if not isfinite(angle):
        raise ValueError("rotation angle must be a finite number")
    if angle == 0:
        return image.copy()
    if angle % 90 == 0:
        out = image
        for _ in range(int(angle // 90)):
            out = out.transpose(Image.Transpose.ROTATE_270)
        return out

    area = image.width * image.height
    if quality in (QUALITY_ROTSPRITE, QUALITY_CLEANEDGE) and area > ROTSPRITE_MAX_PIXELS:
        quality = QUALITY_NEAREST

    if _load_native() is not None:
        return _rotate_native(image, angle, quality)
    return _rotate_pure_python(image, angle, quality)
