
const NEUTRAL: u32 = 0;
const SCALE2X_PASSES: usize = 3;
const SCALE2X_FACTOR: usize = 1 << SCALE2X_PASSES;
const CLEANEDGE_FACTOR: usize = 4;
const CLEANEDGE_LINE_WIDTH: f64 = 1.0;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Mode {
    RotSprite,
    Nearest,
    CleanEdge,
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

// CleanEdge (torcado, MIT) ported from cleanEdge-shadertoy.glsl with
// SLOPE and CLEANUP enabled, lineWidth 1.0, similarThreshold 0 and
// highestColor white. It is not an Aseprite algorithm, so no golden test
// covers it. Colours are (r, g, b, a) bytes. With a zero threshold,
// "similar" is colour equality, or both transparent.
type CeColour = (u8, u8, u8, u8);

fn ce_unpack(px: u32) -> CeColour {
    (
        ((px >> 24) & 0xFF) as u8,
        ((px >> 16) & 0xFF) as u8,
        ((px >> 8) & 0xFF) as u8,
        (px & 0xFF) as u8,
    )
}

fn ce_pack(c: CeColour) -> u32 {
    pack(c.0 as u32, c.1 as u32, c.2 as u32, c.3 as u32)
}

fn ce_similar(a: CeColour, b: CeColour) -> bool {
    (a.3 == 0 && b.3 == 0) || a == b
}

fn ce_similar3(a: CeColour, b: CeColour, c: CeColour) -> bool {
    ce_similar(a, b) && ce_similar(b, c)
}

fn ce_similar4(a: CeColour, b: CeColour, c: CeColour, d: CeColour) -> bool {
    ce_similar(a, b) && ce_similar(b, c) && ce_similar(c, d)
}

fn ce_cd(a: CeColour, b: CeColour) -> f64 {
    let r = (a.0 as f64 - b.0 as f64) / 255.0;
    let g = (a.1 as f64 - b.1 as f64) / 255.0;
    let bl = (a.2 as f64 - b.2 as f64) / 255.0;
    let al = (a.3 as f64 - b.3 as f64) / 255.0;
    (r * r + g * g + bl * bl + al * al).sqrt()
}

fn ce_higher(a: CeColour, b: CeColour) -> bool {
    if ce_similar(a, b) {
        return false;
    }
    if a.3 == b.3 {
        let da = (255 - a.0) as i64 * (255 - a.0) as i64
            + (255 - a.1) as i64 * (255 - a.1) as i64
            + (255 - a.2) as i64 * (255 - a.2) as i64;
        let db = (255 - b.0) as i64 * (255 - b.0) as i64
            + (255 - b.1) as i64 * (255 - b.1) as i64
            + (255 - b.2) as i64 * (255 - b.2) as i64;
        da < db
    } else {
        a.3 > b.3
    }
}

fn ce_dist_to_line(
    test_pt: (f64, f64),
    pt1: (f64, f64),
    pt2: (f64, f64),
    direction: (f64, f64),
) -> f64 {
    let line_x = pt2.0 - pt1.0;
    let line_y = pt2.1 - pt1.1;
    let perp_x = line_y;
    let perp_y = -line_x;
    let length = (perp_x * perp_x + perp_y * perp_y).sqrt();
    let sign = if perp_x * direction.0 + perp_y * direction.1 > 0.0 {
        1.0
    } else {
        -1.0
    };
    let to_x = pt1.0 - test_pt.0;
    let to_y = pt1.1 - test_pt.1;
    sign * ((perp_x / length) * to_x + (perp_y / length) * to_y)
}

fn ce_add(
    base: (f64, f64),
    offset: (f64, f64),
    point_dir: (f64, f64),
) -> (f64, f64) {
    (
        base.0 + offset.0 * point_dir.0,
        base.1 + offset.1 * point_dir.1,
    )
}

#[allow(clippy::too_many_arguments)]
fn ce_slice_dist(
    point: (f64, f64),
    main_dir: (f64, f64),
    point_dir: (f64, f64),
    ub: CeColour,
    u: CeColour,
    uf: CeColour,
    uff: CeColour,
    b: CeColour,
    c: CeColour,
    f: CeColour,
    ff: CeColour,
    db: CeColour,
    d: CeColour,
    df: CeColour,
    dff: CeColour,
    ddb: CeColour,
    dd: CeColour,
    ddf: CeColour,
) -> Option<CeColour> {
    let line_width = CLEANEDGE_LINE_WIDTH.clamp(0.45, 1.142);
    let point = (
        main_dir.0 * (point.0 - 0.5) + 0.5,
        main_dir.1 * (point.1 - 0.5) + 0.5,
    );
    let dist_against =
        4.0 * ce_cd(f, d) + ce_cd(uf, c) + ce_cd(c, db) + ce_cd(ff, df) + ce_cd(df, dd);
    let dist_towards =
        4.0 * ce_cd(c, df) + ce_cd(u, f) + ce_cd(f, dff) + ce_cd(b, d) + ce_cd(d, ddf);
    let mut should_slice = dist_against < dist_towards
        || (dist_against < dist_towards + 0.001 && !ce_higher(c, f));
    if ce_similar4(f, d, b, u) && ce_similar4(uf, df, db, ub) && !ce_similar(c, f) {
        should_slice = false;
    }
    if !should_slice {
        return None;
    }

    let mut dist: f64;
    let mut flip = false;    let center = (0.5f64, 0.5f64);
    let neg = (-point_dir.0, -point_dir.1);

    if ce_similar3(f, d, db) && !ce_similar3(f, d, b) && !ce_similar(uf, db) {
        if ce_similar(c, df) && ce_higher(c, f) {
        } else {
            if ce_higher(c, f) {
                flip = true;
            }
            if ce_similar(u, f) && !ce_similar(c, df) && !ce_higher(c, u) {
                flip = true;
            }
        }
        if flip {
            dist = line_width
                - ce_dist_to_line(
                    point,
                    ce_add(center, (1.5, -1.0), point_dir),
                    ce_add(center, (-0.5, 0.0), point_dir),
                    neg,
                );
        } else {
            dist = ce_dist_to_line(
                point,
                ce_add(center, (1.5, 0.0), point_dir),
                ce_add(center, (-0.5, 1.0), point_dir),
                point_dir,
            );
        }
        if !flip
            && ce_similar(c, uf)
            && !(ce_similar3(c, uf, uff)
                && !ce_similar3(c, uf, ff)
                && !ce_similar(d, uff))
        {
            let dist2 = ce_dist_to_line(
                point,
                ce_add(center, (2.0, -1.0), point_dir),
                ce_add(center, (0.0, 1.0), point_dir),
                point_dir,
            );
            dist = dist.min(dist2);
        }
        dist -= line_width / 2.0;
        return if dist <= 0.0 {
            Some(if ce_cd(c, f) <= ce_cd(c, d) { f } else { d })
        } else {
            None
        };
    }

    if ce_similar3(uf, f, d) && !ce_similar3(u, f, d) && !ce_similar(uf, db) {
        if ce_similar(c, df) && ce_higher(c, d) {
        } else {
            if ce_higher(c, d) {
                flip = true;
            }
            if ce_similar(b, d) && !ce_similar(c, df) && !ce_higher(c, d) {
                flip = true;
            }
        }
        if flip {
            dist = line_width
                - ce_dist_to_line(
                    point,
                    ce_add(center, (0.0, -0.5), point_dir),
                    ce_add(center, (-1.0, 1.5), point_dir),
                    neg,
                );
        } else {
            dist = ce_dist_to_line(
                point,
                ce_add(center, (1.0, -0.5), point_dir),
                ce_add(center, (0.0, 1.5), point_dir),
                point_dir,
            );
        }
        if !flip
            && ce_similar(c, db)
            && !(ce_similar3(c, db, ddb)
                && !ce_similar3(c, db, dd)
                && !ce_similar(f, ddb))
        {
            let dist2 = ce_dist_to_line(
                point,
                ce_add(center, (1.0, 0.0), point_dir),
                ce_add(center, (-1.0, 2.0), point_dir),
                point_dir,
            );
            dist = dist.min(dist2);
        }
        dist -= line_width / 2.0;
        return if dist <= 0.0 {
            Some(if ce_cd(c, f) <= ce_cd(c, d) { f } else { d })
        } else {
            None
        };
    }

    if ce_similar(f, d) {
        if ce_similar(c, df) && ce_higher(c, f) {
            if !ce_similar(c, dd) && !ce_similar(c, ff) {
                flip = true;
            }
        } else {
            if ce_higher(c, f) {
                flip = true;
            }
            if !ce_similar(c, b) && ce_similar4(b, f, d, u) {
                flip = true;
            }
        }
        if (ce_similar(f, db) && ce_similar3(u, f, df))
            || (ce_similar(uf, d) && ce_similar3(b, d, df))
        {
            if !ce_similar(c, df) {
                flip = true;
            }
        }
        if flip {
            dist = line_width
                - ce_dist_to_line(
                    point,
                    ce_add(center, (1.0, -1.0), point_dir),
                    ce_add(center, (-1.0, 1.0), point_dir),
                    neg,
                );
        } else {
            dist = ce_dist_to_line(
                point,
                ce_add(center, (1.0, 0.0), point_dir),
                ce_add(center, (0.0, 1.0), point_dir),
                point_dir,
            );
        }
        if !flip
            && ce_similar3(c, uf, uff)
            && !ce_similar3(c, uf, ff)
            && !ce_similar(d, uff)
        {
            let dist2 = ce_dist_to_line(
                point,
                ce_add(center, (1.5, 0.0), point_dir),
                ce_add(center, (-0.5, 1.0), point_dir),
                point_dir,
            );
            dist = dist.max(dist2);
        }
        if !flip
            && ce_similar3(ddb, db, c)
            && !ce_similar3(dd, db, c)
            && !ce_similar(ddb, f)
        {
            let dist2 = ce_dist_to_line(
                point,
                ce_add(center, (1.0, -0.5), point_dir),
                ce_add(center, (0.0, 1.5), point_dir),
                point_dir,
            );
            dist = dist.max(dist2);
        }
        dist -= line_width / 2.0;
        return if dist <= 0.0 {
            Some(if ce_cd(c, f) <= ce_cd(c, d) { f } else { d })
        } else {
            None
        };
    }

    if ce_similar3(ff, df, d) && !ce_similar3(ff, df, c) && !ce_similar(uff, d) {
        if ce_similar(f, dff) && ce_higher(f, ff) {
        } else {
            if ce_higher(f, ff) {
                flip = true;
            }
            if ce_similar(uf, ff) && !ce_similar(f, dff) && !ce_higher(f, uf) {
                flip = true;
            }
        }
        if flip {
            dist = line_width
                - ce_dist_to_line(
                    point,
                    ce_add(center, (2.5, -1.0), point_dir),
                    ce_add(center, (0.5, 0.0), point_dir),
                    neg,
                );
        } else {
            dist = ce_dist_to_line(
                point,
                ce_add(center, (2.5, 0.0), point_dir),
                ce_add(center, (0.5, 1.0), point_dir),
                point_dir,
            );
        }
        dist -= line_width / 2.0;
        return if dist <= 0.0 {
            Some(if ce_cd(f, ff) <= ce_cd(f, df) { ff } else { df })
        } else {
            None
        };
    }

    if ce_similar3(f, df, dd) && !ce_similar3(c, df, dd) && !ce_similar(f, ddb) {
        if ce_similar(d, ddf) && ce_higher(d, dd) {
        } else {
            if ce_higher(d, dd) {
                flip = true;
            }
            if ce_similar(db, dd) && !ce_similar(d, ddf) && !ce_higher(d, dd) {
                flip = true;
            }
        }
        if flip {
            dist = line_width
                - ce_dist_to_line(
                    point,
                    ce_add(center, (0.0, 0.5), point_dir),
                    ce_add(center, (-1.0, 2.5), point_dir),
                    neg,
                );
        } else {
            dist = ce_dist_to_line(
                point,
                ce_add(center, (1.0, 0.5), point_dir),
                ce_add(center, (0.0, 2.5), point_dir),
                point_dir,
            );
        }
        dist -= line_width / 2.0;
        return if dist <= 0.0 {
            Some(if ce_cd(d, df) <= ce_cd(d, dd) { df } else { dd })
        } else {
            None
        };
    }

    None
}

fn clean_edge_upscale(src: &[u32], w: usize, h: usize) -> (Vec<u32>, usize, usize) {
    // The shader is a magnification filter: each input pixel becomes
    // CLEANEDGE_FACTOR x CLEANEDGE_FACTOR output pixels, each with its own
    // local position ((sub + 0.5) / factor) and quadrant. Neighbours are
    // input texels.
    let ow = w * CLEANEDGE_FACTOR;
    let oh = h * CLEANEDGE_FACTOR;
    let mut out = vec![NEUTRAL; ow * oh];
    for oy in 0..oh {
        let iy = oy / CLEANEDGE_FACTOR;
        let ly = ((CLEANEDGE_FACTOR - 1 - (oy % CLEANEDGE_FACTOR)) as f64 + 0.5)
            / CLEANEDGE_FACTOR as f64;
        for ox in 0..ow {
            let ix = ox / CLEANEDGE_FACTOR;
            let lx = ((ox % CLEANEDGE_FACTOR) as f64 + 0.5) / CLEANEDGE_FACTOR as f64;
            let point = (lx, ly);
            let point_dir = (
                if lx >= 0.5 { 1.0 } else { -1.0 },
                if ly >= 0.5 { 1.0 } else { -1.0 },
            );
            let sample = |dx: i64, dy: i64| -> CeColour {
                let sx = (ix as i64 + dx * point_dir.0 as i64).clamp(0, w as i64 - 1) as usize;
                let sy = (iy as i64 - dy * point_dir.1 as i64).clamp(0, h as i64 - 1) as usize;
                ce_unpack(src[sy * w + sx])
            };
            let uub = sample(-1, -2);
            let uu = sample(0, -2);
            let uuf = sample(1, -2);
            let ubb = sample(-2, -2);
            let ub = sample(-1, -1);
            let u = sample(0, -1);
            let uf = sample(1, -1);
            let uff = sample(2, -1);
            let bb = sample(-2, 0);
            let b = sample(-1, 0);
            let c = sample(0, 0);
            let f = sample(1, 0);
            let ff = sample(2, 0);
            let dbb = sample(-2, 1);
            let db = sample(-1, 1);
            let d = sample(0, 1);
            let df = sample(1, 1);
            let dff = sample(2, 1);
            let ddb = sample(-1, 2);
            let dd = sample(0, 2);
            let ddf = sample(1, 2);

            let mut colour = c;
            if let Some(col) = ce_slice_dist(
                point,
                (1.0, 1.0),
                point_dir,
                ub, u, uf, uff, b, c, f, ff, db, d, df, dff, ddb, dd, ddf,
            ) {
                colour = col;
            }
            if let Some(col) = ce_slice_dist(
                point,
                (-1.0, 1.0),
                point_dir,
                uf, u, ub, ubb, f, c, b, bb, df, d, db, dbb, ddf, dd, ddb,
            ) {
                colour = col;
            }
            if let Some(col) = ce_slice_dist(
                point,
                (1.0, -1.0),
                point_dir,
                db, d, df, dff, b, c, f, ff, ub, u, uf, uff, uub, uu, uuf,
            ) {
                colour = col;
            }
            out[oy * ow + ox] = ce_pack(colour);
        }
    }
    (out, ow, oh)
}

fn round5(value: f32) -> f32 {
    let scaled = (value * 100000.0f32) as f64;
    let rounded = if scaled >= 0.0 {
        (scaled + 0.5).floor()
    } else {
        -((-scaled) + 0.5).floor()
    };
    (rounded / 100000.0) as f32
}

fn rotation_geometry(w: usize, h: usize, angle: f64) -> (usize, usize, [(i64, i64); 4]) {
    // Aseprite stores the angle and every corner as float32 (`gfx::PointF`)
    // and rounds cos/sin to five decimals in Transformation::rotatePoint.
    let rad = ((std::f64::consts::PI * angle) / 180.0) as f32;
    let cos_t = round5(rad.cos());
    let sin_t = round5(rad.sin());
    let cx = w as f32 / 2.0;
    let cy = h as f32 / 2.0;
    let points = [
        (0.0f32, 0.0f32),
        (w as f32, 0.0),
        (w as f32, h as f32),
        (0.0, h as f32),
    ];
    let mut rotated = [(0.0f32, 0.0f32); 4];
    for (i, &(x, y)) in points.iter().enumerate() {
        let dx = x - cx;
        let dy = y - cy;
        rotated[i] = (
            (cx + (dx * cos_t)) - (dy * sin_t),
            (cy + (dx * sin_t)) + (dy * cos_t),
        );
    }
    let min_x = rotated.iter().map(|p| p.0).fold(f32::INFINITY, f32::min);
    let max_x = rotated
        .iter()
        .map(|p| p.0)
        .fold(f32::NEG_INFINITY, f32::max);
    let min_y = rotated.iter().map(|p| p.1).fold(f32::INFINITY, f32::min);
    let max_y = rotated
        .iter()
        .map(|p| p.1)
        .fold(f32::NEG_INFINITY, f32::max);
    let left = min_x.floor();
    let top = min_y.floor();
    let out_w = ((max_x + 1.0) - min_x) as usize;
    let out_h = ((max_y + 1.0) - min_y) as usize;
    let mut corners = [(0i64, 0i64); 4];
    for (i, &(x, y)) in rotated.iter().enumerate() {
        corners[i] = ((x - left) as i64, (y - top) as i64);
    }
    (out_w, out_h, corners)
}

fn ftofix(value: f64) -> i64 {
    if value > 32767.0 {
        return 0x7FFF_FFFF;
    }
    if value < -32767.0 {
        return -0x7FFF_FFFF;
    }
    (value * 65536.0 + if value < 0.0 { -0.5 } else { 0.5 }) as i64
}

fn fixmul(a: i64, b: i64) -> i64 {
    ftofix((a as f64 / 65536.0) * (b as f64 / 65536.0))
}

fn fixdiv(a: i64, b: i64) -> i64 {
    if b == 0 {
        return if a < 0 { -0x7FFF_FFFF } else { 0x7FFF_FFFF };
    }
    ftofix((a as f64 / 65536.0) / (b as f64 / 65536.0))
}

fn out_of_range(value: i64, size: usize) -> bool {
    (((value >> 16) as i32) as u32) >= size as u32
}

fn scanline_bounds(
    mut l_bmp: i64,
    mut r_bmp: i64,
    mut l_spr_x: i64,
    mut l_spr_y: i64,
    spr_dx: i64,
    spr_dy: i64,
    sw: usize,
    sh: usize,
) -> Option<(i64, i64, i64, i64)> {
    if out_of_range(l_spr_x, sw) {
        if (l_spr_x < 0 && spr_dx <= 0) || (l_spr_x > 0 && spr_dx >= 0) {
            return None;
        }
        loop {
            l_spr_x += spr_dx;
            l_bmp += 65536;
            if l_bmp > r_bmp {
                return None;
            }
            if !out_of_range(l_spr_x, sw) {
                break;
            }
        }
    }
    let mut right = l_spr_x + ((r_bmp - l_bmp) >> 16) * spr_dx;
    if out_of_range(right, sw) {
        if (right < 0 && spr_dx <= 0) || (right > 0 && spr_dx >= 0) {
            loop {
                r_bmp -= 65536;
                right -= spr_dx;
                if l_bmp > r_bmp {
                    return None;
                }
                if !out_of_range(right, sw) {
                    break;
                }
            }
        } else {
            return None;
        }
    }
    if out_of_range(l_spr_y, sh) {
        if (l_spr_y < 0 && spr_dy <= 0) || (l_spr_y > 0 && spr_dy >= 0) {
            return None;
        }
        loop {
            l_spr_y += spr_dy;
            l_bmp += 65536;
            if l_bmp > r_bmp {
                return None;
            }
            if !out_of_range(l_spr_y, sh) {
                break;
            }
        }
    }
    right = l_spr_y + ((r_bmp - l_bmp) >> 16) * spr_dy;
    if out_of_range(right, sh) {
        if (right < 0 && spr_dy <= 0) || (right > 0 && spr_dy >= 0) {
            loop {
                r_bmp -= 65536;
                right -= spr_dy;
                if l_bmp > r_bmp {
                    return None;
                }
                if !out_of_range(right, sh) {
                    break;
                }
            }
        } else {
            return None;
        }
    }
    Some((l_bmp, r_bmp, l_spr_x, l_spr_y))
}

fn parallelogram(
    src: &[u32],
    sw: usize,
    sh: usize,
    dw: usize,
    dh: usize,
    corners: &[(i64, i64); 4],
) -> Vec<u32> {
    let mut out = vec![NEUTRAL; dw * dh];
    if dw == 0 || dh == 0 {
        return out;
    }

    let xs: [i64; 4] = [
        corners[0].0 << 16,
        corners[1].0 << 16,
        corners[2].0 << 16,
        corners[3].0 << 16,
    ];
    let ys: [i64; 4] = [
        corners[0].1 << 16,
        corners[1].1 << 16,
        corners[2].1 << 16,
        corners[3].1 << 16,
    ];

    let mut top = 0usize;
    for i in 1..4 {
        if ys[i] < ys[top] {
            top = i;
        }
    }
    let right_index: i64 =
        if fixmul(xs[(top + 1) & 3] - xs[top], ys[(top + 3) & 3] - ys[top])
            > fixmul(xs[(top + 3) & 3] - xs[top], ys[(top + 1) & 3] - ys[top])
        {
            1
        } else {
            -1
        };

    let mut corner_bmp_x = [0i64; 4];
    let mut corner_bmp_y = [0i64; 4];
    let mut corner_spr_x = [0i64; 4];
    let mut corner_spr_y = [0i64; 4];
    let mut index = top as i64;
    for i in 0..4 {
        let idx = index as usize;
        corner_bmp_x[i] = xs[idx];
        corner_bmp_y[i] = ys[idx];
        corner_spr_y[i] = if idx < 2 { 0 } else { ((sh as i64) << 16) - 1 };
        corner_spr_x[i] = if idx == 0 || idx == 3 {
            0
        } else {
            ((sw as i64) << 16) - 1
        };
        index = (index + right_index) & 3;
    }

    let (top_x, top_y) = (corner_bmp_x[0], corner_bmp_y[0]);
    let (right_x, right_y) = (corner_bmp_x[1], corner_bmp_y[1]);
    let (bottom_x, bottom_y) = (corner_bmp_x[2], corner_bmp_y[2]);
    let (left_x, left_y) = (corner_bmp_x[3], corner_bmp_y[3]);

    let clip_left = 0i64;
    let clip_right = ((dw as i64) << 16) - 1;
    if left_x > clip_right && top_x > clip_right && bottom_x > clip_right {
        return out;
    }
    if right_x < clip_left && top_x < clip_left && bottom_x < clip_left {
        return out;
    }

    let mut clip_bottom = (bottom_y + 0x8000) >> 16;
    if clip_bottom > dh as i64 {
        clip_bottom = dh as i64;
    }
    let mut bmp_y = (top_y + 0x8000) >> 16;
    if bmp_y < 0 {
        bmp_y = 0;
    }
    if bmp_y >= clip_bottom {
        return out;
    }

    let mut extra = (bmp_y << 16) + 0x8000 - top_y;
    let mut l_bmp_dx = fixdiv(left_x - top_x, left_y - top_y);
    let mut l_bmp_x = top_x + fixmul(extra, l_bmp_dx);
    let mut l_spr_dx = fixdiv(corner_spr_x[3] - corner_spr_x[0], left_y - top_y);
    let mut l_spr_x = corner_spr_x[0] + fixmul(extra, l_spr_dx);
    let mut l_spr_dy = fixdiv(corner_spr_y[3] - corner_spr_y[0], left_y - top_y);
    let mut l_spr_y = corner_spr_y[0] + fixmul(extra, l_spr_dy);

    let mut l_bottom = (left_y + 0x8000) >> 16;
    if l_bottom > clip_bottom {
        l_bottom = clip_bottom;
    }

    let mut r_bmp_dx = fixdiv(right_x - top_x, right_y - top_y);
    let mut r_bmp_x = top_x + fixmul(extra, r_bmp_dx);
    let mut r_bottom = (right_y + 0x8000) >> 16;

    let den_dx = (xs[1] - xs[0]) as f64 * (ys[3] - ys[0]) as f64
        - (xs[3] - xs[0]) as f64 * (ys[1] - ys[0]) as f64;
    let den_dy = (xs[3] - xs[0]) as f64 * (ys[1] - ys[0]) as f64
        - (xs[1] - xs[0]) as f64 * (ys[3] - ys[0]) as f64;
    if den_dx == 0.0 || den_dy == 0.0 {
        return out;
    }
    let spr_dx = ((ys[3] - ys[0]) as f64 * 65536.0 * (65536.0 * sw as f64) / den_dx) as i64;
    let spr_dy = ((ys[1] - ys[0]) as f64 * 65536.0 * (65536.0 * sh as f64) / den_dy) as i64;

    loop {
        if bmp_y >= l_bottom {
            if bmp_y >= clip_bottom {
                break;
            }
            extra = (bmp_y << 16) + 0x8000 - left_y;
            l_bmp_dx = fixdiv(bottom_x - left_x, bottom_y - left_y);
            l_bmp_x = left_x + fixmul(extra, l_bmp_dx);
            l_spr_dx = fixdiv(corner_spr_x[2] - corner_spr_x[3], bottom_y - left_y);
            l_spr_x = corner_spr_x[3] + fixmul(extra, l_spr_dx);
            l_spr_dy = fixdiv(corner_spr_y[2] - corner_spr_y[3], bottom_y - left_y);
            l_spr_y = corner_spr_y[3] + fixmul(extra, l_spr_dy);
            l_bottom = (bottom_y + 0x8000) >> 16;
            if l_bottom > clip_bottom {
                l_bottom = clip_bottom;
            }
        }

        if bmp_y >= r_bottom {
            extra = (bmp_y << 16) + 0x8000 - right_y;
            r_bmp_dx = fixdiv(bottom_x - right_x, bottom_y - right_y);
            r_bmp_x = right_x + fixmul(extra, r_bmp_dx);
            r_bottom = clip_bottom;
        }

        let mut l_bmp_round = (l_bmp_x + 0x8000) & !0xFFFF;
        if l_bmp_round < clip_left {
            l_bmp_round = clip_left;
        }
        let mut l_spr_x_round = l_spr_x + fixmul(l_bmp_round + 0x7FFF - l_bmp_x, spr_dx);
        let mut l_spr_y_round = l_spr_y + fixmul(l_bmp_round + 0x7FFF - l_bmp_x, spr_dy);

        let mut r_bmp_round = (r_bmp_x - 0x8000) & !0xFFFF;
        if r_bmp_round > clip_right {
            r_bmp_round = clip_right;
        }

        if l_bmp_round <= r_bmp_round {
            if let Some((lb, rb, lsx, lsy)) = scanline_bounds(
                l_bmp_round,
                r_bmp_round,
                l_spr_x_round,
                l_spr_y_round,
                spr_dx,
                spr_dy,
                sw,
                sh,
            ) {
                l_spr_x_round = lsx;
                l_spr_y_round = lsy;
                let x0 = lb >> 16;
                let x1 = rb >> 16;
                let mut u = l_spr_x_round;
                let mut v = l_spr_y_round;
                let row = bmp_y as usize * dw;
                for x in x0..=x1 {
                    let su = u >> 16;
                    let sv = v >> 16;
                    if su >= 0 && su < sw as i64 && sv >= 0 && sv < sh as i64 {
                        out[row + x as usize] = src[sv as usize * sw + su as usize];
                    }
                    u += spr_dx;
                    v += spr_dy;
                }
            }
        }

        bmp_y += 1;
        l_bmp_x += l_bmp_dx;
        l_spr_x += l_spr_dx;
        l_spr_y += l_spr_dy;
        r_bmp_x += r_bmp_dx;
    }

    out
}

fn scale_axis(src_n: usize, dst_n: usize) -> Vec<usize> {
    if dst_n <= 1 || src_n <= 1 {
        return vec![0; dst_n];
    }
    let step = fixdiv(((src_n - 1) as i64) << 16, ((dst_n - 1) as i64) << 16);
    (0..dst_n)
        .map(|i| {
            let x = i as i64 * step;
            ((x >> 16) + ((x & 0x8000) >> 15)) as usize
        })
        .collect()
}

fn scale_point(src: &[u32], sw: usize, sh: usize, dw: usize, dh: usize) -> Vec<u32> {
    let mut out = vec![NEUTRAL; dw * dh];
    let xs = scale_axis(sw, dw);
    let ys = scale_axis(sh, dh);
    for y in 0..dh {
        let sy = ys[y];
        if sy >= sh {
            continue;
        }
        let src_row = sy * sw;
        let dst_row = y * dw;
        for x in 0..dw {
            let sx = xs[x];
            if sx < sw {
                out[dst_row + x] = src[src_row + sx];
            }
        }
    }
    out
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
    if angle % 90.0 == 0.0 {
        let mut pixels = src.to_vec();
        let (mut cw, mut ch) = (w, h);
        for _ in 0..(angle / 90.0) as usize {
            let (next, nw, nh) = quarter_turn_cw(&pixels, cw, ch);
            pixels = next;
            cw = nw;
            ch = nh;
        }
        return (pixels, cw, ch);
    }
    let angle = if angle > 180.0 { angle - 360.0 } else { angle };

    let (out_w, out_h, corners) = rotation_geometry(w, h, angle);
    match mode {
        Mode::Nearest => rotate_nearest(src, w, h, out_w, out_h, &corners),
        Mode::CleanEdge => rotate_cleanedge(src, w, h, out_w, out_h, &corners),
        Mode::RotSprite => rotate_rotsprite(src, w, h, out_w, out_h, &corners),
    }
}

fn rotate_upscaled(
    pixels: &[u32],
    uw: usize,
    uh: usize,
    factor: usize,
    out_w: usize,
    out_h: usize,
    corners: &[(i64, i64); 4],
) -> Vec<u32> {
    let xs: Vec<i64> = corners.iter().map(|c| c.0).collect();
    let ys: Vec<i64> = corners.iter().map(|c| c.1).collect();
    let xmin = *xs.iter().min().unwrap();
    let xmax = *xs.iter().max().unwrap();
    let ymin = *ys.iter().min().unwrap();
    let ymax = *ys.iter().max().unwrap();
    let rot_w = (xmax - xmin) as usize;
    let rot_h = (ymax - ymin) as usize;
    let dst_w = rot_w.min((out_w as i64 - xmin).max(0) as usize);
    let dst_h = rot_h.min((out_h as i64 - ymin).max(0) as usize);

    let mut out = vec![NEUTRAL; out_w * out_h];
    if rot_w > 0 && rot_h > 0 && dst_w > 0 && dst_h > 0 {
        let mut scaled = [(0i64, 0i64); 4];
        for (i, &(x, y)) in corners.iter().enumerate() {
            scaled[i] = (
                (x - xmin) * factor as i64,
                (y - ymin) * factor as i64,
            );
        }
        let rotated = parallelogram(
            pixels,
            uw,
            uh,
            rot_w * factor,
            rot_h * factor,
            &scaled,
        );
        let content = scale_point(
            &rotated,
            rot_w * factor,
            rot_h * factor,
            dst_w,
            dst_h,
        );
        let xmin = xmin as usize;
        let ymin = ymin as usize;
        for y in 0..dst_h {
            let dst = (ymin + y) * out_w + xmin;
            let s = y * dst_w;
            out[dst..dst + dst_w].copy_from_slice(&content[s..s + dst_w]);
        }
    }
    out
}

fn rotate_nearest(
    src: &[u32],
    w: usize,
    h: usize,
    out_w: usize,
    out_h: usize,
    corners: &[(i64, i64); 4],
) -> (Vec<u32>, usize, usize) {
    (
        parallelogram(src, w, h, out_w, out_h, corners),
        out_w,
        out_h,
    )
}

fn rotate_rotsprite(
    src: &[u32],
    w: usize,
    h: usize,
    out_w: usize,
    out_h: usize,
    corners: &[(i64, i64); 4],
) -> (Vec<u32>, usize, usize) {
    let mut pixels = src.to_vec();
    let (mut uw, mut uh) = (w, h);
    for _ in 0..SCALE2X_PASSES {
        let (up, nw, nh) = scale2x_pass(&pixels, uw, uh);
        pixels = up;
        uw = nw;
        uh = nh;
    }
    (
        rotate_upscaled(&pixels, uw, uh, SCALE2X_FACTOR, out_w, out_h, corners),
        out_w,
        out_h,
    )
}

fn rotate_cleanedge(
    src: &[u32],
    w: usize,
    h: usize,
    out_w: usize,
    out_h: usize,
    corners: &[(i64, i64); 4],
) -> (Vec<u32>, usize, usize) {
    let (pixels, uw, uh) = clean_edge_upscale(src, w, h);
    (
        rotate_upscaled(
            &pixels,
            uw,
            uh,
            CLEANEDGE_FACTOR,
            out_w,
            out_h,
            corners,
        ),
        out_w,
        out_h,
    )
}

#[unsafe(no_mangle)]
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
        0 => Mode::RotSprite,
        1 => Mode::Nearest,
        2 => Mode::CleanEdge,
        _ => return 1,
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
            for &mode in &[Mode::RotSprite, Mode::Nearest, Mode::CleanEdge] {
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
            for mode in [Mode::RotSprite, Mode::Nearest, Mode::CleanEdge] {
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
            let (high, hw, hh) = rotate(&src, 10, 6, angle, Mode::RotSprite);
            let (near, nw, nh) = rotate(&src, 10, 6, angle, Mode::Nearest);
            let (clean, cw, ch) = rotate(&src, 10, 6, angle, Mode::CleanEdge);
            assert_eq!((hw, hh), (nw, nh));
            assert_eq!((hw, hh), (cw, ch));
            for out in [&high, &near, &clean] {
                assert!(out.iter().all(|&px| px == SOLID || px == NEUTRAL));
            }
        }
    }

    #[test]
    fn rotate_is_deterministic() {
        let src = vec![SOLID; 8 * 5];
        let a = rotate(&src, 8, 5, 33.0, Mode::RotSprite);
        let b = rotate(&src, 8, 5, 33.0, Mode::RotSprite);
        assert_eq!(a, b);
    }

    #[test]
    fn rotation_geometry_uses_float32_corners() {
        assert_eq!(
            rotation_geometry(45, 115, 1.0),
            (48, 116, [(2, 0), (47, 1), (44, 116), (0, 115)])
        );
        assert_eq!(
            rotation_geometry(2, 2, 45.0),
            (3, 3, [(2, 0), (3, 2), (2, 3), (0, 2)])
        );
    }

    #[test]
    fn scale_axis_rounds_to_nearest_index() {
        assert_eq!(scale_axis(1, 1), vec![0]);
        assert_eq!(scale_axis(8, 1), vec![0]);
        assert_eq!(scale_axis(8, 8), vec![0, 1, 2, 3, 4, 5, 6, 7]);
        assert_eq!(scale_axis(8, 3), vec![0, 4, 7]);
        assert_eq!(scale_axis(8, 4), vec![0, 2, 5, 7]);
    }

    #[test]
    fn nearest_2x2_at_45_matches_aseprite_scanlines() {
        let red = pack(255, 0, 0, 255);
        let green = pack(0, 255, 0, 255);
        let blue = pack(0, 0, 255, 255);
        let yellow = pack(255, 255, 0, 255);
        let src = vec![red, green, blue, yellow];
        let (out, ow, oh) = rotate(&src, 2, 2, 45.0, Mode::Nearest);
        assert_eq!((ow, oh), (3, 3));
        assert_eq!(
            out,
            vec![
                NEUTRAL, NEUTRAL, NEUTRAL, NEUTRAL, red, green, NEUTRAL, yellow, yellow
            ]
        );
    }

    #[test]
    fn cleanedge_2x2_at_45_matches_shader_port() {
        // CleanEdge is not Aseprite, so this differs from the Nearest 3x3.
        let red = pack(255, 0, 0, 255);
        let green = pack(0, 255, 0, 255);
        let blue = pack(0, 0, 255, 255);
        let yellow = pack(255, 255, 0, 255);
        let src = vec![red, green, blue, yellow];
        let (out, ow, oh) = rotate(&src, 2, 2, 45.0, Mode::CleanEdge);
        assert_eq!((ow, oh), (3, 3));
        assert_eq!(
            out,
            vec![
                NEUTRAL, NEUTRAL, NEUTRAL, NEUTRAL, red, NEUTRAL, NEUTRAL, NEUTRAL, NEUTRAL
            ]
        );
    }

    #[test]
    fn parallelogram_quarter_turns_are_exact() {
        let (w, h) = (3usize, 2usize);
        let src: Vec<u32> = (0..(w * h) as u32).collect();
        let cases: [((usize, usize), [(i64, i64); 4]); 4] = [
            (
                (w, h),
                [(0, 0), (w as i64, 0), (w as i64, h as i64), (0, h as i64)],
            ),
            (
                (h, w),
                [(h as i64, 0), (h as i64, w as i64), (0, w as i64), (0, 0)],
            ),
            (
                (w, h),
                [(w as i64, h as i64), (0, h as i64), (0, 0), (w as i64, 0)],
            ),
            (
                (h, w),
                [(0, w as i64), (0, 0), (h as i64, 0), (h as i64, w as i64)],
            ),
        ];
        let (q90, qw, qh) = quarter_turn_cw(&src, w, h);
        let (q180, rw, rh) = quarter_turn_cw(&q90, qw, qh);
        let (q270, ..) = quarter_turn_cw(&q180, rw, rh);
        let expected = [src.clone(), q90, q180, q270];
        for (i, ((dw, dh), corners)) in cases.iter().enumerate() {
            let out = parallelogram(&src, w, h, *dw, *dh, corners);
            assert_eq!(out, expected[i], "case {i}");
        }
    }
}
