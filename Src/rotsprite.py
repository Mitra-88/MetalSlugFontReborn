
import ctypes
import os
import sys
from math import cos, isfinite, radians, sin
from pathlib import Path

from PIL import Image

QUALITY_FAST_ROTSPRITE = "Fast RotSprite"
QUALITY_ROTSPRITE = "RotSprite"
QUALITY_NEAREST = "Nearest"

NEUTRAL = 0
SCALE2X_PASSES = 3
FAST_UPSCALE = 3

# ponytail: quality degrades on huge inputs because an 8x RotSprite pass on
# a multi-megapixel image costs hundreds of MB and seconds even natively,
# while real sprites are tiny. Raise these only with fresh profiler evidence.
ROTSPRITE_MAX_PIXELS = 250_000
FAST_MAX_PIXELS = 4_000_000


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


def _upscale_nn(flat, w, h, factor):
    ow = w * factor
    out = [NEUTRAL] * (ow * h * factor)
    for y in range(h):
        src_row = y * w
        dst_row = y * factor * ow
        for x in range(w):
            px = flat[src_row + x]
            dst = dst_row + x * factor
            for dy in range(factor):
                row = dst + dy * ow
                for dx in range(factor):
                    out[row + dx] = px
    return out, ow, h * factor


def _rotate_nn(flat, w, h, sin_t, cos_t, ow, oh):
    cx_in = w / 2
    cy_in = h / 2
    cx_out = ow / 2
    cy_out = oh / 2
    out = [NEUTRAL] * (ow * oh)
    for y2 in range(oh):
        ay = y2 + 0.5 - cy_out
        sin_ay = sin_t * ay
        cos_ay = cos_t * ay
        row = y2 * ow
        for x2 in range(ow):
            ax = x2 + 0.5 - cx_out
            sx = cos_t * ax + sin_ay + cx_in
            sy = -sin_t * ax + cos_ay + cy_in
            if 0.0 <= sx < w and 0.0 <= sy < h:
                out[row + x2] = flat[int(sy) * w + int(sx)]
    return out


def _mode_downscale(flat, w, h, factor):
    ow = -(-w // factor)
    oh = -(-h // factor)
    out = [NEUTRAL] * (ow * oh)
    for by in range(oh):
        y0 = by * factor
        y1 = min(h, y0 + factor)
        for bx in range(ow):
            x0 = bx * factor
            x1 = min(w, x0 + factor)
            counts = {}
            best = NEUTRAL
            best_count = 0
            for yy in range(y0, y1):
                row = yy * w
                for xx in range(x0, x1):
                    px = flat[row + xx]
                    count = counts.get(px, 0) + 1
                    counts[px] = count
                    if count > best_count:
                        best = px
                        best_count = count
            out[by * ow + bx] = best
    return out, ow, oh


def _rotate_pure_python(image, angle, quality):
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

    while angle >= 90:
        image = image.transpose(Image.Transpose.ROTATE_270)
        angle -= 90

    flat, w, h = _to_flat(image)
    rad = radians(angle)
    sin_t = sin(rad)
    cos_t = cos(rad)
    bw = round(w * abs(cos_t) + h * abs(sin_t))
    bh = round(w * abs(sin_t) + h * abs(cos_t))
    if quality == QUALITY_NEAREST:
        flat = _rotate_nn(flat, w, h, sin_t, cos_t, bw, bh)
        return _to_image(flat, bw, bh)
    if quality == QUALITY_ROTSPRITE:
        for _ in range(SCALE2X_PASSES):
            flat, w, h = _scale2x_pass(flat, w, h)
        factor = 2**SCALE2X_PASSES
    else:
        flat, w, h = _upscale_nn(flat, w, h, FAST_UPSCALE)
        factor = FAST_UPSCALE
    fw = bw * factor
    fh = bh * factor
    flat = _rotate_nn(flat, w, h, sin_t, cos_t, fw, fh)
    flat, w, h = _mode_downscale(flat, fw, fh, factor)
    return _to_image(flat, w, h)


_NATIVE_LIB = None
_NATIVE_RESOLVED = False


def _library_candidates():
    here = Path(__file__).resolve().parent
    if sys.platform == "win32":
        names = ["msfr_rotsprite.dll"]
    elif sys.platform == "darwin":
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
    rad = radians(angle)
    out_w_px = round(width * abs(cos(rad)) + height * abs(sin(rad)))
    out_h_px = round(width * abs(sin(rad)) + height * abs(cos(rad)))
    cap = out_w_px * out_h_px * 4
    out = (ctypes.c_ubyte * cap)()
    out_len = ctypes.c_size_t()
    out_w = ctypes.c_uint32()
    out_h = ctypes.c_uint32()
    mode = {
        QUALITY_FAST_ROTSPRITE: 0,
        QUALITY_ROTSPRITE: 1,
        QUALITY_NEAREST: 2,
    }[quality]
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


def rotate(image, angle, quality=QUALITY_FAST_ROTSPRITE):
    if quality not in (QUALITY_FAST_ROTSPRITE, QUALITY_ROTSPRITE, QUALITY_NEAREST):
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
    if quality == QUALITY_ROTSPRITE and area > ROTSPRITE_MAX_PIXELS:
        quality = QUALITY_FAST_ROTSPRITE
    if quality == QUALITY_FAST_ROTSPRITE and area > FAST_MAX_PIXELS:
        quality = QUALITY_NEAREST

    if _load_native() is not None:
        return _rotate_native(image, angle, quality)
    return _rotate_pure_python(image, angle, quality)
