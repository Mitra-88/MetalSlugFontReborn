
const NEUTRAL: u32 = 0;
const SCALE2X_PASSES: usize = 3;
const FAST_UPSCALE: usize = 3;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Mode {
    Fast,
    RotSprite,
    Nearest,
}

fn pack(r: u32, g: u32, b: u32, a: u32) -> u32 {
    (r << 24) | (g << 16) | (b << 8) | a
}

fn channel(px: u32, shift: u32) -> u32 {
    (px >> shift) & 0xFF
}

fn bytes_to_pixels(src: &[u8]) -> Vec<u32> {
    src.chunks_exact(4)
        .map(|c| pack(c[0] as u32, c[1] as u32, c[2] as u32, c[3] as u32))
        .collect()
}

fn pixels_to_bytes(pixels: &[u32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(pixels.len() * 4);
    for &px in pixels {
        out.extend_from_slice(&[
            channel(px, 24) as u8,
            channel(px, 16) as u8,
            channel(px, 8) as u8,
            channel(px, 0) as u8,
        ]);
    }
    out
}

fn upscale_nn(src: &[u32], w: usize, h: usize, f: usize) -> (Vec<u32>, usize, usize) {
    let ow = w * f;
    let mut out = vec![NEUTRAL; ow * h * f];
    for y in 0..h {
        let dst_row = y * f * ow;
        for x in 0..w {
            let px = src[y * w + x];
            for dy in 0..f {
                let row = dst_row + dy * ow;
                for dx in 0..f {
                    out[row + x * f + dx] = px;
                }
            }
        }
    }
    (out, ow, h * f)
}

fn scale2x_pass(src: &[u32], w: usize, h: usize) -> (Vec<u32>, usize, usize) {
    let ow = w * 2;
    let mut out = vec![NEUTRAL; ow * h * 2];
    for y in 0..h {
        let y_up = if y > 0 { y - 1 } else { 0 };
        let y_down = if y + 1 < h { y + 1 } else { y };
        let row_up = y_up * w;
        let row = y * w;
        let row_down = y_down * w;
        let out_row = y * 2 * ow;
        let out_row2 = out_row + ow;
        for x in 0..w {
            let x_left = if x > 0 { x - 1 } else { 0 };
            let x_right = if x + 1 < w { x + 1 } else { x };
            let p = src[row + x];
            let up = src[row_up + x];
            let down = src[row_down + x];
            let left = src[row + x_left];
            let right = src[row + x_right];

            let tl = if left == up && left != down && up != right {
                up
            } else {
                p
            };
            let tr = if up == right && up != left && right != down {
                right
            } else {
                p
            };
            let bl = if down == left && down != right && left != up {
                left
            } else {
                p
            };
            let br = if right == down && right != up && down != left {
                down
            } else {
                p
            };

            out[out_row + x * 2] = tl;
            out[out_row + x * 2 + 1] = tr;
            out[out_row2 + x * 2] = bl;
            out[out_row2 + x * 2 + 1] = br;
        }
    }
    (out, ow, h * 2)
}

fn rotate_nn(
    src: &[u32],
    w: usize,
    h: usize,
    sin_t: f64,
    cos_t: f64,
    ow: usize,
    oh: usize,
) -> Vec<u32> {
    let mut out = vec![NEUTRAL; ow * oh];
    let cx_in = w as f64 / 2.0;
    let cy_in = h as f64 / 2.0;
    let cx_out = ow as f64 / 2.0;
    let cy_out = oh as f64 / 2.0;
    for y2 in 0..oh {
        let ay = y2 as f64 + 0.5 - cy_out;
        let sin_ay = sin_t * ay;
        let cos_ay = cos_t * ay;
        let row = y2 * ow;
        for x2 in 0..ow {
            let ax = x2 as f64 + 0.5 - cx_out;
            let sx = cos_t * ax + sin_ay + cx_in;
            let sy = -sin_t * ax + cos_ay + cy_in;
            if sx >= 0.0 && sx < w as f64 && sy >= 0.0 && sy < h as f64 {
                out[row + x2] = src[sy as usize * w + sx as usize];
            }
        }
    }
    out
}

fn mode_downscale(src: &[u32], w: usize, h: usize, f: usize) -> (Vec<u32>, usize, usize) {
    const MAX_BLOCK_PIXELS: usize = 64;
    debug_assert!(
        f * f <= MAX_BLOCK_PIXELS,
        "block colors overflow the fixed vote table"
    );
    let ow = -(-(w as isize) / f as isize) as usize;
    let oh = -(-(h as isize) / f as isize) as usize;
    let mut out = vec![NEUTRAL; ow * oh];
    let mut colors = [0u32; MAX_BLOCK_PIXELS];
    let mut counts = [0usize; MAX_BLOCK_PIXELS];
    for by in 0..oh {
        let y0 = by * f;
        let y1 = (y0 + f).min(h);
        for bx in 0..ow {
            let x0 = bx * f;
            let x1 = (x0 + f).min(w);
            let mut seen = 0usize;
            let mut best = NEUTRAL;
            let mut best_count = 0usize;
            for yy in y0..y1 {
                let row = yy * w;
                for xx in x0..x1 {
                    let px = src[row + xx];
                    let mut found = false;
                    for i in 0..seen {
                        if colors[i] == px {
                            counts[i] += 1;
                            if counts[i] > best_count {
                                best = px;
                                best_count = counts[i];
                            }
                            found = true;
                            break;
                        }
                    }
                    if !found && seen < MAX_BLOCK_PIXELS {
                        colors[seen] = px;
                        counts[seen] = 1;
                        if best_count == 0 {
                            best = px;
                            best_count = 1;
                        }
                        seen += 1;
                    }
                }
            }
            out[by * ow + bx] = best;
        }
    }
    (out, ow, oh)
}

fn quarter_turn_cw(src: &[u32], w: usize, h: usize) -> (Vec<u32>, usize, usize) {
    let mut out = vec![NEUTRAL; src.len()];
    for y in 0..h {
        for x in 0..w {
            out[x * h + (h - 1 - y)] = src[y * w + x];
        }
    }
    (out, h, w)
}

pub fn rotate(
    src: &[u32],
    w: usize,
    h: usize,
    angle_deg: f64,
    mode: Mode,
) -> (Vec<u32>, usize, usize) {
    let angle = angle_deg.rem_euclid(360.0);
    if angle == 0.0 {
        return (src.to_vec(), w, h);
    }
    let mut pixels = src.to_vec();
    let (mut cw, mut ch) = (w, h);
    let mut remaining = angle;
    while remaining >= 90.0 {
        let (next, nw, nh) = quarter_turn_cw(&pixels, cw, ch);
        pixels = next;
        cw = nw;
        ch = nh;
        remaining -= 90.0;
    }
    if remaining > 0.0 {
        let rad = remaining.to_radians();
        let sin_t = rad.sin();
        let cos_t = rad.cos();
        let bw = (cw as f64 * cos_t.abs() + ch as f64 * sin_t.abs()).round() as usize;
        let bh = (cw as f64 * sin_t.abs() + ch as f64 * cos_t.abs()).round() as usize;
        let factor = match mode {
            Mode::Nearest => 1,
            Mode::Fast => {
                let (up, uw, uh) = upscale_nn(&pixels, cw, ch, FAST_UPSCALE);
                pixels = up;
                cw = uw;
                ch = uh;
                FAST_UPSCALE
            }
            Mode::RotSprite => {
                for _ in 0..SCALE2X_PASSES {
                    let (up, uw, uh) = scale2x_pass(&pixels, cw, ch);
                    pixels = up;
                    cw = uw;
                    ch = uh;
                }
                1 << SCALE2X_PASSES
            }
        };
        if factor > 1 {
            let (fw, fh) = (bw * factor, bh * factor);
            pixels = rotate_nn(&pixels, cw, ch, sin_t, cos_t, fw, fh);
            let (down, dw, dh) = mode_downscale(&pixels, fw, fh, factor);
            pixels = down;
            cw = dw;
            ch = dh;
        } else {
            pixels = rotate_nn(&pixels, cw, ch, sin_t, cos_t, bw, bh);
            cw = bw;
            ch = bh;
        }
    }
    (pixels, cw, ch)
}

#[no_mangle]
// Safety: caller must keep `src` readable for `src_len` bytes and `out`
// writable for `out_cap` bytes, with all output pointers non-null, for the
// duration of the call.
pub extern "C" fn msfr_rotate(
    src: *const u8,
    src_len: usize,
    w: u32,
    h: u32,
    angle_deg: f64,
    mode: u32,
    out: *mut u8,
    out_cap: usize,
    out_len: *mut usize,
    out_w: *mut u32,
    out_h: *mut u32,
) -> i32 {
    if src.is_null() || out.is_null() || out_len.is_null() || out_w.is_null() || out_h.is_null() {
        return 1;
    }
    if src_len != w as usize * h as usize * 4 || w == 0 || h == 0 {
        return 1;
    }
    let src_bytes = unsafe { std::slice::from_raw_parts(src, src_len) };

    let pixel_mode = match mode {
        0 => Mode::Fast,
        1 => Mode::RotSprite,
        _ => Mode::Nearest,
    };

    let pixels = bytes_to_pixels(src_bytes);
    let (rotated, rw, rh) = crate::rotate(&pixels, w as usize, h as usize, angle_deg, pixel_mode);
    let rgba = pixels_to_bytes(&rotated);
    if rgba.len() > out_cap {
        return 2;
    }
    unsafe {
        std::ptr::copy_nonoverlapping(rgba.as_ptr(), out, rgba.len());
        *out_len = rgba.len();
        *out_w = rw as u32;
        *out_h = rh as u32;
    }
    0
}

#[cfg(test)]
mod tests {
    use super::*;

    const SOLID: u32 = 0x0AC81EFF; // opaque (10, 200, 30)

    #[test]
    fn solid_image_stays_solid() {
        let src = vec![SOLID; 12 * 7];
        for &angle in &[17.0, 45.0, 90.0, 260.0] {
            for &mode in &[Mode::Fast, Mode::RotSprite] {
                let (out, ow, oh) = rotate(&src, 12, 7, angle, mode);
                assert_eq!(ow * oh, out.len());
                assert!(out.iter().all(|&px| px == SOLID || px == NEUTRAL));
            }
        }
    }

    #[test]
    fn quarter_turns_are_exact() {
        let src: Vec<u32> = (0..12).collect();
        let (out, ow, oh) = quarter_turn_cw(&src, 3, 4);
        assert_eq!((ow, oh), (4, 3));
        for y in 0..4 {
            for x in 0..3 {
                assert_eq!(out[x * 4 + (4 - 1 - y)], src[y * 3 + x]);
            }
        }
    }

    #[test]
    fn rotation_never_introduces_new_colors() {
        let mut src: Vec<u32> = Vec::new();
        for i in 0..8 * 8 {
            src.push(pack((i * 37 % 256) as u32, (i * 11 % 256) as u32, 128, 255));
        }
        let allowed: std::collections::HashSet<u32> = src.iter().copied().collect();
        for &angle in &[15.0, 33.0, 77.0, 205.0, 300.0] {
            for mode in [Mode::Fast, Mode::RotSprite] {
                let (out, _ow, _oh) = rotate(&src, 8, 8, angle, mode);
                assert!(
                    out.iter().all(|px| allowed.contains(px) || *px == NEUTRAL),
                    "angle {angle} mode {mode:?}"
                );
            }
        }
    }

    #[test]
    fn modes_agree_on_output_dimensions() {
        let src = vec![SOLID; 10 * 6];
        for &angle in &[20.0, 55.0, 150.0] {
            let (fast, fw, fh) = rotate(&src, 10, 6, angle, Mode::Fast);
            let (high, hw, hh) = rotate(&src, 10, 6, angle, Mode::RotSprite);
            let (near, nw, nh) = rotate(&src, 10, 6, angle, Mode::Nearest);
            assert_eq!((fw, fh), (hw, hh));
            assert_eq!((fw, fh), (nw, nh));
            for out in [&fast, &high, &near] {
                assert!(out.iter().all(|&px| px == SOLID || px == NEUTRAL));
            }
        }
    }

    #[test]
    fn rotate_is_deterministic() {
        let src = vec![SOLID; 8 * 5];
        let a = rotate(&src, 8, 5, 33.0, Mode::Fast);
        let b = rotate(&src, 8, 5, 33.0, Mode::Fast);
        assert_eq!(a, b);
    }
}
