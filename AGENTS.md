# MetalSlugFontReborn

Cross-platform PySide6 desktop app that renders text into PNG images using sprite fonts extracted from the Metal Slug series. The app never draws glyphs: every character is a pre-extracted PNG under `Assets/Fonts`, and the code only picks sprites, positions them, and composites with Pillow. Five fonts with per-font color variants, a live preview, a per-character advanced editor, three themes, adjustable PNG compression. Every release is a PyInstaller onedir bundle, one per OS.

## Commands

| Task | Command |
|---|---|
| Run from source | `.venv/Scripts/python.exe Src/main.py` |
| Tests | `.venv/Scripts/python.exe -m pytest` |
| Lint | `.venv/Scripts/python.exe -m ruff check Src Tests` |
| Build rotation library | `cargo build --release --manifest-path rust/rotsprite-rs/Cargo.toml` |
| Rotation tests | `cargo test --manifest-path rust/rotsprite-rs/Cargo.toml` |
| Package | the `pyinstaller` commands in `Docs/BUILD.md` |
| Profile generation | `.venv/Scripts/python.exe Tools/sample_profiler.py` |
| Regenerate exe version metadata | `.venv/Scripts/python.exe Tools/make_versionfile.py` |

Linux and macOS use `.venv/bin/python`. `Src` reaches `sys.path` through the script's own directory, so these work from any cwd. Rust is needed only to rebuild the native rotation engine; without the cdylib the app and the tests silently fall back to the pure-Python engine.

uv owns the interpreter: `.python-version` pins 3.15 and `uv sync` builds `.venv`. Always the GIL build, because PySide6 ships abi3 wheels only (free-threaded CPython cannot load them) and the worker/GUI design assumes the GIL. 3.15 gives default UTF-8 `open()` and `frozendict`, used for the constant tables; do not enable PEP 810 lazy imports in the frozen app.

## Layout

| Path | What lives there |
|---|---|
| `Src/main.py` | entry point, `MainWindow`, `ImageWorker`, preview widgets, unsupported-char highlighter, `pick_style` |
| `Src/editor.py` | `AdvancedEditorDialog` and its scene stack (`EditorScene`, `EditorView`, `CharItem`, `SnapEngine`, `TransformBox`, `UndoStack`, `RenderDispatcher`, `ZoomEntry`) |
| `Src/image_generation.py` | sprite-to-PNG engine, pure Pillow, no Qt, callable headless |
| `Src/rotsprite.py` | rotation engine: Rust cdylib through ctypes, pure-Python fallback |
| `rust/rotsprite-rs/` | the cdylib (`msfr_rotsprite`), one FFI function |
| `Src/ui_common.py` | `Config`/`load_config`/`save_config`, `set_theme`, About, supported-characters dialog, `create_group` |
| `Src/themes.py` | light, dark and Tokyo Night `QPalette` factories |
| `Src/system_info.py` | `get_system_info`, `msfr_version`, `build_date`, `readable_size` |
| `Src/special_characters.py` | `special_characters` dict (char to asset name), `LICENSE_TEXT` |
| `Assets/Fonts/Font-{1..5}/MS-{Color}/` | sprites under `Letters/Lower-Case`, `Letters/Upper-Case`, `Numbers`, `Symbols`; the colors differ per font |
| `Tests/` | pytest suite |
| `Tools/sample_profiler.py` | generation benchmark, also shipped as a standalone exe by CI |
| `Tools/palette-changer/` | standalone Qt tool that recolors a sprite folder into another hue |
| `Docs/` | `BUILD.md` (packaging), `INSTALL-*.md`, `SUPPORTED.md`, `EXAMPLES.md`, `PROGRESS.md` |

## How it works

- `MainWindow` collects text, font, color, compression, scale and save dir, then emits `trigger_generation`. `ImageWorker.process` runs on one low-priority `QThread` and calls `image_generation.generate_image`, so the UI never blocks.
- Sprite lookup: `Assets/Fonts/Font-{id}/MS-{color}/{Letters|Numbers|Symbols}/...`, symbols through `special_characters`, a space as a 25x1 transparent strip. The supported set, the colors and the font list are all derived from those directories at runtime, which is what drives the highlighter, the editor's valid set and the generated document.
- The main window strips unsupported characters before rendering and lists them as skipped in the success dialog; the engine still raises `FileNotFoundError` as a backstop for direct callers. `\r\n` and lone `\r` are normalized before layout.
- Canvas math lives in exactly one place, `layout_characters`. `generate_image`, the preview and the editor scene all build from its placements, so preview, export and editor cannot drift.
- Preview renders through the same worker with compression skipped entirely, is debounced 150 ms, and rejects oversized canvases (`PREVIEW_MAX_DIMENSION`, `PREVIEW_MAX_PIXELS`) before allocating.
- `Config` wraps `config.toml` with tomlkit, next to the exe when frozen and at the repo root in dev. Four keys only: `theme`, `skip_location_prompt`, `skip_char_replace_confirm`, `skip_theme_prompt`. No schema, no migration, every reader carries its own fallback.
- The rotation engine has three qualities, RotSprite, CleanEdge and Nearest, shared by the preview and the editor. Exact 0/90/180/270 rotations are transposes; every other angle goes through the Aseprite-derived pipeline in `Src/rotsprite.py` and the Rust cdylib. CleanEdge is the exception: it is a port of torcado's CleanEdge shader, not an Aseprite algorithm.
- Themes are QPalettes. Until the user picks one, the app follows `QStyleHints.colorScheme` and re-applies on live changes; an explicit pick wins permanently. The Qt widget style comes from `pick_style`.

## Rules

- Implement only what the feature needs. No abstraction, wrapper, option or config that exists "for later", no dead helpers, no layered architecture for trivial logic.
- Keep classes small and single-purpose, names self-explanatory. Rationale, invariants and quirks live in this file, not in inline comments: one home, or it drifts.
- No em dashes anywhere, including docs, config comments and code strings. Use commas, colons or hyphens.
- Profile before optimizing: run `Tools/sample_profiler.py`, change only what it proves hot, then re-run.
- Read third-party APIs from `.venv\Lib\site-packages` (PySide6, PIL, tomlkit, PyInstaller) before using them. If a symbol is not there, it does not exist for this project.
- Keep the three `except Exception  # noqa: BLE001` guards (`ImageWorker.process`, `ImageWorker.process_preview`, and the editor open in `main.py`). Any PIL, Qt or OS failure must reach the user as a dialog, never kill the app or leave it stuck on "Generating...".
- Security posture: no network access, no eval/exec/pickle, config parsing size-capped, uuid filenames so nothing of the user's is overwritten, external links disabled in the supported-characters browser, `QDesktopServices` only on an explicit click.

## Traps worth remembering

**App**

- `PROJECT_ROOT` is the parent of `Src`. When frozen, `__file__` sits inside `_internal`, which is why the build moves `Assets` out next to the exe. Never make these paths cwd-relative.
- The default save dir is `QStandardPaths.DesktopLocation`, not `Path.home() / "Desktop"`: the naive path breaks on OneDrive-redirected Windows and on localized xdg dirs. `default_save_path` is also what the "(default)" label compares against.
- `config.toml` is best-effort by design: corrupt, oversized or unreadable files fall back to defaults and write failures are ignored, because frozen installs can live in read-only directories. Never turn those into crashes.
- Generated PNGs are written to a `.part` file and `os.replace`d, so a crash mid-write never leaves a truncated image. Do not simplify back to a direct save.
- Sprites are decoded once on cache insert (`image.load()`), because the same PIL image is pasted from both the GUI thread and the worker thread.
- `Image.MAX_IMAGE_PIXELS` is raised at `image_generation` import and only `ImageWorker` catches `DecompressionBombError`, so headless callers must handle it themselves.
- `APP_VERSION` in `Src/system_info.py` is the only version to edit. `versionfile.txt` is generated from it by `python Tools/make_versionfile.py` (the Windows build step and `Docs/BUILD.md` run it before packaging), the `pyproject.toml` version is bumped by hand, and `test_version_holders_agree_with_app_version` fails if either drifts. In packaged builds `msfr_version` is `APP_VERSION (commit)` from `build_commit.txt` and `build_date` is the exe mtime, so both stay stable across runs of one build.
- Widget style names are exactly `windows11`, `windowsvista`, `Windows`, `macOS`, `Fusion`, and app styles go through `pick_style` against `QStyleFactory.keys()`. Never hardcode an unverified name.
- Never call `setMinimumSize` on the main window: an explicit minimum disables Qt's layout-minimum tracking and crushes the preview when a section expands. Fixed UI sizes must be minimums or derive from `QFontMetrics`, since 150%+ scaling breaks hard caps.
- Transient title state lives in `_title_status` and every update goes through `_update_window_title`; clear it on failure paths. `_generating` gates both Generate and the editor, and `update_generate_button_state` must respect it.
- `preview_failed` carries a reveal flag: True only for character and asset problems, where the supported-characters button helps.
- `QDesktopServices.openUrl` returns False with no handler. The success dialog keeps its chain: `_open_externally` (Linux `LD_LIBRARY_PATH` dance included), then open the folder, then show the path.
- Color swatches are sampled from real sprite pixels (`_sample_color_palette` over the uppercase `A`, drawn as pie slices); the dominant color alone is always the dark outline.
- `Assets/Icons/Raubtier.ico` must stay a multi-size SQUARE ico (16 to 256). A single non-square frame renders in the title bar but not in the taskbar, and `--icon` embeds the same file.
- `LICENSE` is read lazily by `load_license_text` (do not lru_cache it, a test monkeypatches `PROJECT_ROOT`), and `SUPPORTED.md` is generated from the same disk scan as the charsets. Never hand-write copies of either. `Tests/test_supported_doc.py` guards the doc against the generator, per-color charsets and the unsupported list; the unsupported tail is manual but checked to stay truly unsupported.
- Symbol files with no `special_characters` mapping (accent variants like `A-1`, words like `One`) are intentional decorative variants and are skipped; `test_assets.py` guards that no other unmapped file appears. Font 5 supports only upper-case letters, digits 1-9 and `!?`.

**Threading**

- One worker `QObject` on one `QThread` for the app's lifetime, coalescing state on the GUI thread, no locks. Deadlock is structurally impossible and the one accepted race is a double sprite decode. The GUI waits on the worker only for the 3 s shutdown join.
- Preview contract: at most one job in flight, `_preview_queued` holds the newest parameters, and when `_flush_preview_queue()` returns True the arriving result is stale and must be dropped without display.
- Startup order is load-bearing: the preview and char-count timers are created at the top of `setup_ui`, before `textChanged` is connected. A font-less frozen environment fires `textChanged` during construction, which crashed the bundle until the timers moved up.

**Editor**

- `RenderDispatcher` is a daemon Python thread over a `queue.Queue`, never a QThread: a dialog-owned QThread destroyed mid-run aborts the process. `CharItem.request_render` is the single entry and falls back to `update_pixmap` when there is no dispatcher.
- `render_character` order is scale and stretch as one nearest resize, then flips as exact transposes, then the opacity alpha multiply, then rotation. The pixmap cache key is `(scale_pct, rotation, stretch_x, stretch_y, flip_h, flip_v, opacity, hue_shift, saturation, brightness, contrast)`, keep seeds and tests in that shape. Every transform-consuming site passes stretch and flip and measures the RENDERED size.
- Rotation angles go to `rotsprite_rotate` UNNEGATED (the engine is clockwise-positive, PIL is counter-clockwise), and Nearest routes through the engine too so both qualities agree on direction and canvas size.
- Corner handles drive `stretch_x`/`stretch_y`, not `scale_pct` (the slider owns uniform scale). All eight handles share one `_update_scale` path ported from Aseprite's `PixelsMovement::moveImage`. Gesture factors are clamped once through `_limit_factor`, never per item.
- The tilted selection outline is `T(-center) * R * T(center)`: in Qt `A * B` applies A first, and the textbook order flings it to a mirrored position.
- The scale slider maps absolutely from the `sliderPressed` snapshot, so intermediate ticks cannot compound quantization error; uncached non-90-rotated items stash `_pending_center` for `apply_rendered`.
- `item.pixmap()` lags `scale_pct` while a render is pending, so every size estimate for a non-90-rotated item scales the pixmap by `scale_pct / _pixmap_scale`. `_pixmap_scale` is written only by `_set_pixmap`, never by a property change; reading `pixmap()` as the current scale drifts the item's centre on every slider tick.
- Gesture mouse moves coalesce on a 16 ms timer (`commit()` flushes the last one); non-gesture slider input is debounced 25 ms. Tests that drive the slider handlers directly must call `_flush_all_debounced()` first.
- Hue and tone adjustments run in the worker, never on the GUI thread. `render_job` applies `apply_adjustments`, a line-for-line mirror of `Tools/palette-changer/color_variants.py:apply_adjustments`; change both together.
- `SNAP_DISABLED_MODIFIER` is Alt or Ctrl, never Alt alone: GNOME and other desktops reserve Alt+drag to move the window.
- `_sync_panel` writes offset spins through `_set_spin_clamped`: `QSpinBox.setValue` overflows shiboken's 32-bit bridge before Qt clamps, crashing the gesture commit.
- Every `QPushButton` gets `setAutoDefault(False)`: in a `QDialog` the first push button becomes the default, so Enter would click Cancel and close the editor.
- The checkerboard is ONE fill with a cached texture brush, never per-square rects (they shimmered). Background bounds are memoized in `_bounds_cache` and must be invalidated by `CharItem.itemChange` on `ItemPositionHasChanged`, `_after_pixmap_change`, `apply_state` and `setVisible`; `_update_scene_rect` also repaints the grown union, because `setSceneRect` alone leaves it stale at high zoom.
- Canvas edits go through `_set_canvas_size` only, and the editor dialog needs the full `Qt.WindowType.Window` flag to be maximizable on Linux. `_build_global_group` must re-apply collapsed visibility after its children exist.
- Ctrl+S, Delete and arrow nudges are gated by `_in_canvas_gesture()`, so they cannot fire mid-drag or mid-transform.
- Export pre-checks the composition bounds against `Image.MAX_IMAGE_PIXELS` (DecompressionBombError is not an OSError, the generic handler never sees it) and shares the `skip_location_prompt` welcome dialog, parented to the editor.
- The dirty flag compares against `_initial_signature` until the first export, then `_exported_signature`: undoing back to the opening state must leave the dialog clean.
- `ordered_selection()` is the only selection source, so "first selected" means first clicked.

**Rotation**

- `EPX` comparisons are strict `==`, matching Aseprite; a similarity tolerance melts dithered shading.
- RotSprite is Aseprite's pipeline: EPX three times (8x), the parallelogram map at 8x, then point sampling from 8x down to the integer corner extent. Nearest is the same parallelogram map at 1x. The angle is first wrapped to `(-180, 180]`, like `base::fmod_radians`. The geometry follows `Transformation::transformedCorners` (`src/app/transformation.cpp`): the four `gfx::PointF` (float32) corners of `(0,0,w,h)` rotate about the centre with cos/sin rounded to five decimals, `Corners::bounds(1.0)` unions `RectF(cx, cy, 1, 1)`, the origin is floored, and the canvas is the truncated `max + 1 - min` extent. `drawParallelogram` (`src/app/ui/editor/pixels_movement.cpp`) then passes `int(corner - leftTop)`, a float32 subtraction, to `rotsprite_image`. A non-integer extent keeps one transparent pixel of margin, so the canvas is `floor(extent) + 1`, not `round(extent)`.
- `ase_parallelogram_map` (`src/doc/algorithm/rotate.cpp`) is ported, not re-derived: its half-up scanline rounding drops pixels whose centres fall exactly on the left or top edge, which a closed-form inverse map would include. `spr_dx`/`spr_dy` keep the 16.16 fixed-point arithmetic and the `0x7fff` centre offset.
- Aseprite's `std::cos(float)`/`std::sin(float)` call the platform `cosf`/`sinf` through the MSVC STL and UCRT. `(float)cos(double)` differs in the last ULP for rare f32 angles and changes the integer corners at some sizes, so both engines call the platform `cosf`/`sinf`: Rust `f32::cos`/`f32::sin`, Python through ctypes with a `math` fallback. All 361 integer degrees are unaffected; float angles are not, and the `dense78x123` golden covers it. Guarantee levels: Python's `struct` `"f"` promises IEEE binary32 but not the rounding mode, and Rust's std docs say `f32::cos`/`sin` precision is unspecified, so both match the platform on Windows by measurement (204k narrowing cases, 400k trig cases), not by language guarantee. CleanEdge's `sqrt` is guaranteed correctly rounded in Rust but only described as "square root" in the Python docs, so the two engines rely on the platform C `sqrt` agreeing.
- CleanEdge's `round(0.5)` in the shader is implementation-defined in GLSL (docs.gl). At the 4x magnification the port uses, locals are .125 steps and never hit 0.5, so both engines agree regardless of the GPU's choice. The port uses f64 distances instead of the GPU's float precision, so Rust and Python agree with each other; the WebGL2 check on ANGLE found no decision flips from that difference.
- PyInstaller's frozen ctypes wrapper redirects `CDLL("ucrtbase.dll")` to an app-local copy in `_internal`, which can come from an unrelated PATH entry. `_load_trig` loads `%SystemRoot%\System32\ucrtbase.dll` explicitly on Windows, so the engine uses the same system UCRT as Aseprite instead of a bundled copy.
- `scale_image` (`image_scale_tpl` in `rotate.cpp`) downscales by point sampling with `fixdiv(itofix(src - 1), itofix(dst - 1))` and `fixtoi` (round to nearest), not by flooring `i * step`. It runs from the 8x canvas to `rot_width x rot_height`, clamped to the destination canvas, and is placed at `(xmin, ymin)`. The clamp is a mirror of `rotsprite_image` even though the computed canvas is normally large enough.
- `rotate()` owns validation, exact 0/90/180/270 transposes (floats included) and the RotSprite/CleanEdge over-cap fallback to Nearest; a native failure code falls back to pure Python. The pixel cap `ROTSPRITE_MAX_PIXELS` moves only with fresh measurements.
- CleanEdge is a non-Aseprite quality. It is a 4x magnification filter ported from torcado's CleanEdge shader (`SLOPE` and `CLEANUP` on, `lineWidth` 1.0, `similarThreshold` 0, `highestColor` white): each input pixel becomes a 4x4 block whose subpixels carry their own local position and quadrant, neighbours are input texels sampled with edge clamping and mirrored by `pointDir`. It then runs the same parallelogram rotation and point-sampled downscale at 4x. It shares the Aseprite geometry and canvas size but no golden test covers it, and the MIT license attribution lives on `_clean_edge_upscale` in `Src/rotsprite.py`. At 4x the locals are .125 steps, so `round()` never hits its implementation-defined 0.5 case. The port matches a WebGL2 GPU render of the Godot wrapper on the tested patterns.
- Aseprite forces FAST within 0.01 degrees of a multiple of 90 unless `forceRotsprite` is set. We shortcut only exact multiples: the near-multiple rule is a `PixelsMovement` UI policy tied to an unmodified selection, not part of the algorithm, and our callers choose the quality explicitly.
- ctypes needs `argtypes` declared at load (a bare CDLL rejects Python floats) and `ctypes.string_at(out, n)` for the result slice (`out[:n]` boxed a list and cost 40 ms).

## Tests

- pytest runs headless: `conftest.py` sets `QT_QPA_PLATFORM=offscreen`, `pytest.ini` sets `testpaths` and puts `Src` and `Tools/palette-changer` on the path. The suite must stay display-free and network-free.
- `Tests/golden` holds real Aseprite `doc-lib` exports generated by a small MSVC harness around `rotsprite_image`, `parallelogram` and `Transformation`. `test_aseprite_golden_images` runs them; the `dense78x123` float-angle pair covers the `cosf`/`sinf` difference and runs on Windows only because that golden is MSVC-specific.
- A test that opens `MainWindow` stubs `main.ImageWorker.process`, points `window.save_path` at `tmp_path` and sets `skip_location_prompt`: a real generation writes a uuid PNG to the Desktop and its modal hangs later `processEvents()`.
- Editor tests use `make_dialog`, which strips each item's `_dispatcher` for synchronous rendering (`worker_renders=True` for the real thread) and stubs `_prompt_save_location`; reattach the method from the class to test the prompt.

## Packaging and CI

`Docs/BUILD.md` and `.github/workflows/build.yml` are the source of truth for the exact commands, trim globs and cache steps. What must not be undone:

- `--add-data` carries data only (`build_commit.txt`, `LICENSE`, `Assets`); PyInstaller's analysis collects the modules, so never add per-module entries.
- PySide6 lands at `PySide6/plugins` on Windows and `PySide6/Qt/plugins` on Linux and macOS. Trim globs and `missing_plugin_message` must cover both layouts.
- Trim only what nothing references: the app imports QtCore, QtGui and QtWidgets. Keep Pillow's real codecs (`libtiff`, `libjpeg`, `libwebp`, `libopenjp2`, `libzstd`, `liblzma` are linked into `_imaging`); only `_avif` and `libavif` are safe to delete.
- Keep Qt6DBus on Linux and macOS: macOS QtGui hard-links it, and Linux runs the portal colorScheme detection and the compose input method through it. Network and Svg are the trimmable ones.
- Linux dedupe deletes the top-level Qt SYMLINKS only, never the real `PySide6/Qt/lib` files. Core X11 libraries come from the system (`libxkbcommon*`, `libX11*`, `libXau*`, `libXdmcp*`, plus `libxcb.so.*` only): a bundled libxkbcommon segfaults on newer keymaps. The glob must stay `libxcb.so.*`, because `libxcb*` deletes the utility libraries `libQt6XcbQpa` hard-links. Those utilities stay bundled and the trim asserts `libxcb-cursor*` exists.
- macOS trims keep `Versions/A` and drop the root binary and `Versions/Current`; per-library globs need the `.framework` form.
- The Linux "Headless smoke test" guards all of it: Xvfb, launch the frozen exe, `xdotool type "HELLO"`, assert the process is alive. It also replays the startup-order trap, so keep it in sync with `setup_ui`.

## Platform notes

- Linux artifacts are built on `ubuntu-22.04` for the glibc 2.35 floor. GitHub retired those images (unsupported 2027-04-17), so migrating to `ubuntu-24.04` either raises the floor to 2.39 or needs an `ubuntu:22.04` container.
- Windows bundles keep the VC++ runtime app-local (`VCRUNTIME140*.dll`, `MSVCP140*.dll`), so no VC++ redistributable is needed. The UCRT set (`ucrtbase.dll`, `api-ms-win-crt-*.dll`) is stripped because Windows 10 1809 and later provide it as an OS component. macOS builds are unsigned: Gatekeeper blocks the first launch, right-click Open or `xattr -cr` works.
- Frozen Linux builds force `QT_QPA_PLATFORM=xcb` and `QT_IM_MODULE=compose` through `setdefault`. xcb gives real window decorations under XWayland but makes `libxcb-cursor0` a runtime requirement; compose means no CJK input, which the sprites cannot render anyway.
- The `atk-bridge` and `libgvfsdbus.so` lines printed on Linux consoles come from the system's GTK bridge and a stale gvfs module, not from the app. Never silence them with `NO_AT_BRIDGE=1` or an empty `GIO_MODULE_DIR`.
- Tested matrix: Windows 11 GUI by hand each release, Windows and Linux CI builds per release, macOS build-only (no hardware), Wayland hand runs unexercised.

## Settled decisions

- PySide6-Essentials, not the full package. tomlkit for `config.toml`, so hand-written comments survive saves.
- uuid4 hex filenames; `generate_filename` ignores its argument, there is no user-facing naming.
- One worker `QObject` on one `QThread` for the app's lifetime, not a thread pool. Pillow renders every output image (RGBA, NEAREST upscale), no QPainter in the generation path.
- Rotation is a Rust cdylib loaded through ctypes with a bit-identical pure-Python fallback. Both follow Aseprite exactly for RotSprite and Nearest: EPX (strict equality, three passes), `ase_parallelogram_map` with its fixed-point scanlines, and point-sampled downscaling. CleanEdge is the deliberate exception: a torcado CleanEdge port at 4x with `lineWidth` 1.0 and `similarThreshold` 0, no Aseprite equivalent and no golden. The old majority-vote downscale is gone, so no part of the pipeline follows the original RotSprite spec over Aseprite. No third-party rotation or binding crates.
- pytest in `Tests/`, headless and offline.
- The Linux artifact is the plain PyInstaller onedir folder, the same shape as Windows; an AppImage failed to load Qt platform plugins on target systems.
- Module names: `main`, `editor`, `image_generation`, `ui_common`, `system_info`, `themes`, `special_characters`. The old `qt-version`, `qt_utils` and `utils` are retired, do not resurrect them.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/) 1.0.0: `type(scope): description`, lowercase imperative, no trailing period. Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`. Breaking changes get `!` before the colon and a `BREAKING CHANGE:` footer.
