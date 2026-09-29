## What this is

MetalSlugFontReborn is a cross-platform PySide6 desktop app that renders text into PNG images using sprite fonts extracted from the Metal Slug series. The app never draws glyphs: every character is a pre-extracted PNG sprite under `Assets/Fonts`, and the code only picks sprites, positions them, and composites the result with Pillow. There are 5 font variants (Font-1 to Font-5) with per-font color variants (Blue, Orange, Gold, Yellow), a live preview, an optional per-character advanced editor, three UI themes, and adjustable PNG compression. Packaging is PyInstaller, one frozen build per OS, produced by the GitHub workflows.

## Build & run

Dependencies: Python 3.12+ and `requirements.txt` (PySide6-Essentials, pillow, pyinstaller, tomlkit). The repo's `.venv` already has them installed. Rust (cargo 1.70+) is only needed to rebuild the native rotation library; without the built cdylib the app and the tests fall back to the pure-Python engine automatically.

Run from source, from any cwd (the script's dir goes on `sys.path`, so the intra-`Src` imports resolve):

```sh
.venv/Scripts/python.exe Src/main.py
```

Fresh setup: `py -m venv .venv`, activate it, `pip install -r requirements.txt`.

Packaging: the two `pyinstaller` commands in `Docs/BUILD.md` (Windows separator `;`, Linux/macOS `:`) are the source of truth, and `.github/workflows/build-*.yml` run the same commands. Every workflow first runs `cargo build --release` and ships the cdylib via `--add-binary` (`msfr_rotsprite.dll` / `libmsfr_rotsprite.so` / `libmsfr_rotsprite.dylib`), so the packaged app always rotates natively; GitHub runners have Rust preinstalled, and `rust/**` is in every workflow's path triggers. Only true data files are passed via `--add-data` (`build_commit.txt`, `LICENSE`, `Assets`); the Python modules are collected automatically by PyInstaller's static analysis and PySide6 hooks, so never add per-module `--add-data` entries. The post-build "trim unused Qt components" step (opengl32sw, Qt6Network/Qt6Svg, TLS/networkinformation/generic/iconengines plugins, translations, OpenSSL, setuptools) cut the Windows bundle from 109 MB to 73 MB and is verified by an offscreen run. The post-build step that moves `dist/.../_internal/Assets` next to the exe is load-bearing, see Gotchas. To smoke-test a bundle headlessly: set `QT_QPA_PLATFORM=offscreen`, run the exe, and confirm the process stays alive. On Linux the CI wraps the PyInstaller output into an AppImage with linuxdeploy; the AppRun wrapper and desktop file live in `Deploy/linux/`.

Tests: `.venv/Scripts/python.exe -m pytest` (headless via the offscreen QPA, no display or network needed).

## How the app works

Generation pipeline (`Src/main.py`):

1. `MainWindow` collects params: text, font id, color, compress level, scale, save dir (first run asks, defaults to the Desktop, remembered via `skip_location_prompt`).
2. It emits `trigger_generation(params)`; `ImageWorker.process` runs on a low-priority `QThread` so the UI never blocks.
3. The worker calls `image_generation.generate_image`, which composites sprites and saves a PNG named by uuid.
4. The worker emits `finished(path, w, h, start)` or `failed(message)`; `MainWindow` shows a summary box with file size and elapsed time, or an error box.

Sprite resolution (`Src/image_generation.py`): a character maps to `Assets/Fonts/Font-{id}/MS-{color}/{Letters|Numbers|Symbols}/...`. Lower-case and upper-case letters and digits go by name; symbols go through the `special_characters` dict in `Src/special_characters.py`. A space becomes a 25x1 transparent strip. An unsupported character raises `FileNotFoundError` with a user-facing message, as does a supported character whose sprite file is missing. The main window strips unsupported characters before rendering (`find_unsupported_characters`) and surfaces them as a skipped list in the success dialog instead of failing; the engine raise remains as a backstop for direct callers. `_CHAR_IMAGE_CACHE` memoizes opened sprites per path and is never invalidated (assets are static, that is fine). The supported character set, the color variants, and the font list are all derived from those directories at runtime (`get_font_charset`, `get_font_colors`, `get_font_ids`) and drive the highlighter, the editor's valid set, and the generated supported-characters document. Line splitting normalizes `\r\n` and lone `\r` to `\n` first, so pasted Windows text lays out identically.

Preview: debounced at 150 ms and rendered by the shared `ImageWorker` thread, never on the UI thread; the GUI thread only converts the finished PIL image into a pixmap. The worker pre-computes the canvas size and rejects oversized previews (`PREVIEW_MAX_DIMENSION`, `PREVIEW_MAX_PIXELS`) before any large allocation happens. Requests coalesce (`_preview_pending` / `_preview_queued`): while a render is in flight only the newest parameters are kept and a stale result is dropped. Compression never triggers a preview (a preview is temporary and uncompressed), and scale, zoom, and Fit only re-display the cached render instead of re-rendering. `UnsupportedCharHighlighter` flags characters not in the font's derived charset while typing.

Canvas layout is computed in exactly one place, `layout_characters`: `generate_image` composites from its placements and the editor scene builds from the same call, so the canvas math cannot drift between preview, export, and editor.

Advanced editor (`Src/editor.py`): `AdvancedEditorDialog` lays out one `CharItem` per character on a `QGraphicsScene` via `layout_characters`, with drag/scale/rotate/replace, snapping to edges, centers and baselines (`SnapEngine`, magenta guides, hold Alt or Ctrl to suspend), and undo/redo (`UndoStack`, Ctrl+Z/Y; Ctrl+S exports). Each item caches its rendered sprites under its own scaled-down cap, and export re-renders each visible item through `render_character` (Pillow), composites them, crops to the bounding box, upscales with NEAREST, and saves with a uuid filename.

Config (`Src/ui_common.py`): `Config` wraps `config.toml` with tomlkit. In frozen builds the file sits next to the exe, in dev at the repo root. Only four keys exist: `theme`, `skip_location_prompt`, `skip_char_replace_confirm`, `skip_theme_prompt`. There is no schema or migration, every read site carries its own fallback.

Theming: three QPalette themes live in `Src/themes.py`. Until the user picks one from the menu, the app follows the system color scheme (`QStyleHints.colorScheme`, fed by xdg-desktop-portal on Linux desktops, the registry on Windows, and native detection on macOS) and re-applies on live scheme changes. An explicit pick is saved and then wins permanently. The Qt widget style (`windows11` / `macOS` / `Fusion`) is chosen by `pick_style` in `main.py` against `QStyleFactory.keys()`, so a missing name degrades to Fusion instead of silently doing nothing.

## Codebase tour

- `Src/main.py`: entry point, `MainWindow`, `ImageWorker`, preview widgets, the unsupported-character highlighter, and `pick_style`. Color swatches are sampled from real sprite pixels, not a hex table.
- `Src/editor.py`: `AdvancedEditorDialog` plus its scene stack (`EditorScene`, `EditorView`, `CharItem`, `SnapEngine`, `TransformBox`, `UndoStack`). Non-90-degree rotations render through `Src/rotsprite.py` (Fast RotSprite 3x by default for live previews, full RotSprite selectable, Nearest for the classic look; 90-degree multiples are exact transposes). `render_character` passes the angle to `rotsprite_rotate` UNNEGATED: the engine is clockwise-positive and PIL's `rotate` is CCW-positive, so the PIL branches negate and the rotsprite branch must not; Nearest also routes through the engine so all three qualities agree on direction and canvas size. `CharItem` carries `stretch_x`/`stretch_y` percentages and `flip_h`/`flip_v` on top of the uniform `scale_pct`; `render_character` applies scale and stretch as one nearest-neighbor resize, then exact transposes for flips, then rotation (Aseprite's ordering), and the item pixmap cache key is `(scale_pct, rotation, stretch_x, stretch_y, flip_h, flip_v)`; keep every seed and test in that shape. Every transform-consuming site must pass the item's stretch and flip to `render_character` (`_scale_selection`, `_replace_with_string`, export, the box) and position from the RENDERED size, not the raw sprite; `_replace_with_string` inherits stretch and flips onto the new items and measures from the item's scene rect. Ctrl+S, Delete and arrow-key nudge are all gated by `_in_canvas_gesture()` so they cannot fire mid-drag or mid-transform. `TransformBox` is the Aseprite-style on-canvas handle overlay: with ONE visible selected item the outer ring around a corner also rotates (around the rendered center; no movable pivot, the render model is center-rotation), and all gestures share the same grammar for multi-selections: corners scale every item by its own initial scale and edges stretch every item's own stretch_x/stretch_y, both around the pinned opposite corner/edge of the union rect (Aseprite's edge rule: N/S change height only, W/E width only), so relative sizes, spacing and stretch differences survive. The gesture factor is clamped ONCE to the tightest per-item limit via `_limit_factor` (clamping items individually would leave one behind while its position keeps moving), each item is positioned with its own effective factor (`new value / initial value`, which also keeps single-selection snapping geometrically exact), and all gesture-driven dx/dy are rounded to whole pixels. Per-item snapping is skipped in multi mode; single-selection edge stretch still snaps to 100%. Gestures reuse the slider begin/commit pattern: snapshot at press, one `_push` at release, prune caches, `_sync_panel`; refresh points are `_sync_panel`, `CharItem.update_pixmap`, `EditorScene.mouseMoveEvent` and `zoom_changed`, all of which must keep the box in sync. Gesture mouse-move updates coalesce onto a single-shot `GESTURE_UPDATE_MS` (16ms) timer and `commit()` flushes the last pending movement synchronously, so high-polling mice cannot trigger multiple re-renders per display frame; don't call the gesture math directly from mouse events. The side panel sizes itself from content: `_fit_panel` derives the scroll area's minimum width from the form's sizeHint plus scrollbar chrome (horizontal scrollbar is off), the splitter gives the panel exactly that, and the Spacing & Alignment group starts collapsed, so no scrolling is needed to reach Save. The selection action buttons (align/spread/reset/flips/90-rotations) live in one QGridLayout; `_make_collapsible` connects toggled to a slot that hides children via `self.sender()`, and `_build_global_group` must re-apply visibility AFTER its children exist (setChecked at construction fires before any child exists, so the collapsed state would leak visible children). The editor dialog opts into minimize and maximize via WindowMinimize/MaximizeButtonHint. The editor canvas background is a Photoshop-style workspace: a pasteboard desk fills the viewport (Base blended `PASTEBOARD_TINT` toward Shadow), and the document on it is a transparency checkerboard drawn in scene units (`CHECKER_PX` = 8 picture pixels per square) anchored at the scene origin, so the squares scale with zoom. All tones are derived per paint from the application palette (Base, Text, Shadow via `_blend`), so it follows Light/Dark/Tokyo Night automatically, and `_on_palette_changed` invalidates the background when the app palette changes. The checker and its border cover `_background_bounds()` (canvas rect united with every visible item's rect), so they auto-expand when content grows or is dragged past the layout canvas; `_update_scene_rect` derives the scene rect from the same bounds plus `SCENE_PADDING` and is recomputed on layout changes, drags and gestures, otherwise Qt clips items and background outside the old scene rect and the expansion silently fails; below `CHECKER_MIN_SCREEN_PX` per square it degrades to a flat tone instead of moire. The snap grid is not drawn at all; the Grid size setting only drives fallback snapping. The background is editor-only: `_export_image` composites rendered sprites onto a fresh transparent image and never paints scene background, and the main generation path is pure Pillow with no scene involved. The dirty flag is computed against `_initial_signature` (the capture at construction) until the first export, then against `_exported_signature`: undoing back to the opening state must leave the dialog clean, don't regress to a sticky `_dirty`.
- `Src/rotsprite.py`: the rotation engine. Three qualities: Fast RotSprite (single 3x NN upscale), full RotSprite (three EPX/Scale2x passes with exact color equality, 8x, matching Aseprite's `rotsprite_image` in `doc/algorithm/rotate.cpp`), Nearest (raw NN, no upscale). Each is upscale, rotate by inverse-mapped nearest-neighbor sampling, then majority-vote downscale that never introduces a color absent from the source. The EPX conditions use strict `==` comparisons, NOT a similarity tolerance: Aseprite compares exactly and a tolerance melts dithered shading. Two bit-identical implementations: a Rust cdylib loaded through ctypes (what packaged builds ship) and a pure-Python fallback with the same pipeline (source runs without cargo, or `MSFR_ROTSPRITE_PURE=1`).
- `rust/rotsprite-rs/`: the Rust cdylib (`msfr_rotsprite`). Build with `cargo build --release --manifest-path rust/rotsprite-rs/Cargo.toml`. FFI is `msfr_rotate(src_bytes, src_len, w, h, angle_f64, mode, out, out_cap, out_len*, out_w*, out_h*) -> i32` with mode 0=Fast/1=RotSprite/2=Nearest and return 0 ok / 1 invalid / 2 cap too small. Pixels travel as packed RGBA bytes, one u32 per pixel, `(r<<24)|(g<<16)|(b<<8)|a`, identical packing on both sides. `cargo test` covers the quarter-turn mapping, color purity, and cross-mode dimension agreement.
- `Src/image_generation.py`: the whole sprite-to-PNG engine, pure Pillow, no Qt, callable headless.
- `Src/ui_common.py`: `Config` + `load_config`/`save_config`, `set_theme`, `about_section`, `SupportedCharactersDialog`, `ViewSupportedButton`, `create_group`.
- `Src/themes.py`: light/dark/Tokyo Night `QPalette` factories, no widgets.
- `Src/system_info.py`: `get_system_info` (the OS string in the About box), `msfr_version`, `build_date`, `readable_size`.
- `Src/special_characters.py`: the `special_characters` dict (char to asset name) and `LICENSE_TEXT`.
- `Assets/Fonts/Font-{1..5}/MS-{Color}/`: `Letters/Lower-Case`, `Letters/Upper-Case`, `Numbers`, `Symbols`.
- `Docs/BUILD.md`: exact packaging commands per OS.
- `Deploy/linux/`: the AppRun wrapper and desktop file used by the Linux AppImage packaging (CI and BUILD.md use both).
- `Tools/sample_profiler.py`: benchmark and profile harness for the generation path (cProfile hot spots, tracemalloc, RSS leak check).
- `Tools/palette-changer/`: standalone Qt6 tool, independent of the main app (run `python Tools/palette-changer/palette_changer.py`). Recolors a sprite folder and its subfolders into a new hue while keeping every color's shading level, with brightness/saturation/contrast adjustments. Hue-only is the only replace mode and the hue comes from a dedicated hue slider (saturation and brightness are preserved by design, so a full color picker would be meaningless). The engine (`color_variants.py`) is Pillow-only: per-channel LUT masks for exact-color remap, one composed LUT for brightness+contrast, Pillow's C saturation enhancer, alpha preserved per pixel. Covered by `Tests/test_color_variants.py` (hue accuracy checked against `colorsys` across the wheel; pytest's pythonpath includes `Tools/palette-changer`). The Aseprite Lua version this replaced was removed on 2026-09-27.
- `Tests/`: pytest suite (renderer layout and math, config resilience, full sprite-on-disk coverage for every valid character, config/theme behavior, style picking, color variant creation, rotation quality, native/pure rotation parity, MainWindow smoke). Tests that open the MainWindow must stub `main.ImageWorker.process` and point `window.save_path` at tmp_path: a real queued generation writes a uuid png to the actual Desktop and its finished modal hangs any later `processEvents()`. They must also set `skip_location_prompt` in the config fixture (or never `show()` the window): the save-folder prompt is modal and hangs headless runs.

## Rules that matter for edits

**Purpose:** implement only what is genuinely necessary for the requested feature.

**Core rules**

- No overengineering.
- No unnecessary abstractions.
- No generic framework-like constructs when a simple, direct solution suffices.
- No "future-proofing" without a concrete need.
- No dead helper classes, wrappers, managers, registry layers, or utility collections without a clear current use case.
- No artificially bloated architectures.

**Style guidelines**

- Write simple, direct, readable code.
- Prefer concrete implementations over unnecessary generalization.
- Keep classes small and single-purpose.
- Keep methods short and clear.
- Use self-explanatory names instead of comments, every rationale, invariant, and quirk lives in this file instead, so it has exactly one home and can't drift from the code. Don't re-add inline comments or Javadoc; put the knowledge here.
- Never use em dashes. In any file (docs, config comments, chat messages, code strings) write the sentence with commas, colons, or plain hyphens instead.
- Profile before optimizing: run `Tools/sample_profiler.py`, change only what it proves is hot, then re-run it to confirm. Don't spend complexity on code the profiler ignores.

**What to avoid**

- AI-typical "enterprise" patterns for small features.
- Excessive use of interfaces without real added value.
- Builders, factories, services, providers, adapters, etc., unless actually needed.
- Defensive abstractions for hypothetical future use cases.
- Multi-layered architecture for trivial logic.
- Duplicated helper logic in "Utils" just to make code look "cleaner".
- Complex configuration or event systems for simple flows.

# Ponytail, lazy senior dev mode

You are a lazy senior developer. Lazy means efficient, not careless. The best code is the code never written.

Before writing any code, stop at the first rung that holds:

1. Does this need to be built at all? (YAGNI)
2. Does it already exist in this codebase? Reuse the helper, util, or pattern that's already here, don't re-write it.
3. Does the standard library already do this? Use it.
4. Does a native platform feature cover it? Use it.
5. Does an already-installed dependency solve it? Use it.
6. Can this be one line? Make it one line.
7. Only then: write the minimum code that works.

The ladder runs after you understand the problem, not instead of it: read the task and the code it touches, trace the real flow end to end, then climb.

Bug fix = root cause, not symptom: a report names a symptom. Grep every caller of the function you touch and fix the shared function once, one guard there is a smaller diff than one per caller, and patching only the path the ticket names leaves a sibling caller still broken.

Rules:

- No abstractions that weren't explicitly requested.
- No new dependency if it can be avoided.
- No boilerplate nobody asked for.
- Deletion over addition. Boring over clever. Fewest files possible.
- Shortest working diff wins, but only once you understand the problem. The smallest change in the wrong place isn't lazy, it's a second bug.
- Question complex requests: "Do you actually need X, or does Y cover it?"
- Pick the edge-case-correct option when two stdlib approaches are the same size, lazy means less code, not the flimsier algorithm.
- Mark deliberate simplifications that cut a real corner with a known ceiling (global lock, O(n²) scan, naive heuristic) with a `ponytail:` comment naming the ceiling and upgrade path.

Not lazy about: understanding the problem (read it fully and trace the real flow before picking a rung, a small diff you don't understand is just laziness dressed up as efficiency), input validation at trust boundaries, error handling that prevents data loss, security, accessibility, the calibration real hardware needs (the platform is never the spec ideal, a clock drifts, a sensor reads off), anything explicitly requested. Lazy code without its check is unfinished: non-trivial logic leaves ONE runnable check behind, the smallest thing that fails if the logic breaks (an assert-based demo/self-check or one small test file; no frameworks, no fixtures). Trivial one-liners need no test.

(Yes, this file also applies to agents working on the ponytail repo itself. Especially to them.)

## Gotchas & quirks

- `PROJECT_ROOT` is the parent of `Src`. In frozen builds `__file__` sits inside `_internal`, so `PROJECT_ROOT` lands on the app folder itself, which is exactly why the build moves `Assets` out of `_internal` next to the exe. Never "simplify" these paths to cwd-relative ones.
- The default save dir comes from `QStandardPaths.DesktopLocation`, not `Path.home() / "Desktop"`. The naive path breaks on Windows when Desktop is OneDrive-redirected and on Linux with localized xdg-user-dirs (`~/Desktop` does not exist there), so don't revert it. `default_save_path` is also what the "(default)" label compares against.
- `config.toml` is best-effort by design: a corrupt, oversized, or unreadable file silently falls back to defaults at startup, and write failures are ignored because frozen installs can live in read-only dirs like Program Files. Don't turn these into crashes, the app must start and run regardless of config state.
- Generated PNGs are written to a `.part` file next to the target and atomically renamed with `os.replace`, so a crash mid-write (disk full, killed process, worker terminate) never leaves a truncated image on the user's Desktop. Don't simplify back to a direct save.
- Sprites are fully decoded once when cached (`image.load()` in `create_character_image`) because the same cached PIL image is later pasted from both the main thread (preview, editor) and the worker thread; lazy decode would defer that read to whichever thread pastes first.
- Release identity freezes automatically in packaged builds: `msfr_version` is `APP_VERSION (commit)` with the commit read from the bundled `build_commit.txt`, and `build_date` is the executable's modification time, so both stay stable across runs of one build. Dev builds show the run date and the live git commit. `APP_VERSION` in `system_info.py` must be kept in sync with `versionfile.txt`.
- `Image.MAX_IMAGE_PIXELS` is raised to 220434240 at `image_generation` import; only `ImageWorker` catches the resulting `DecompressionBombError`, so headless callers must handle it themselves.
- Character support is derived from the asset directories at runtime by `get_font_charset`, `get_font_colors`, and `get_font_ids` in `image_generation.py`; nothing about supported characters is hand-maintained anymore. Symbol files without a mapping in `special_characters` (accent variants like `A-1`, number words like `One`) are intentional decorative variants and are skipped; `Tests/test_assets.py` guards that no unmapped file escapes that pattern.
- Font 5 supports only upper-case letters, digits 1-9, and `!?`. Most text is unsupported there by design, and the disk-derived charset reproduces that automatically.
- App styles go through `pick_style` with `QStyleFactory.keys()` validation: Windows 11 gets `windows11`, macOS gets `macOS`, everything else gets `Fusion`.
- Qt widget style names are exactly `windows11`, `windowsvista`, `Windows`, `macOS`, `Fusion`. There is no `FluentWinUI3` style in Qt or PySide6, the old code asked for it and silently no-oped. `pick_style` validates the requested name against `QStyleFactory.keys()` and falls back to Fusion; never hardcode an unverified style name.
- Frozen Linux builds set `QT_IM_MODULE=compose` before QApplication via `setdefault` (an explicit user env still wins). The bundled ibus input-context plugin mismatches newer system ibus daemons and crashed the app when typing on X11, which the README used to paper over by telling users to switch to Wayland. Dev runs keep the system input method. Revisit only if CJK input ever becomes a requirement, the sprites support none of it.
- The Linux CI workflow builds on pinned `ubuntu-22.04`, keeping the bundle's glibc floor low so it runs on both older and newer systems. Don't move it to `ubuntu-latest`, it drifts upward over time and raises the floor.
- The Linux AppImage packaging runs linuxdeploy with `-d` only and never `-e`: the PyInstaller bundle is already self-contained, and `-e` would make linuxdeploy copy the runner's system libraries into it. linuxdeploy keeps an existing `AppDir/AppRun` untouched (verified in its source, `deployStandardAppRunFromDesktopFile`), which is why `Deploy/linux/AppRun` exists instead of relying on the generated symlink.
- `QDesktopServices.openUrl` returns False when the system has no handler, and it is never fire-and-forget here: `MainWindow._open_externally` checks the path exists, performs the Linux `LD_LIBRARY_PATH` dance, and returns the result, and `on_generation_finished` falls back to opening the folder, then to just showing the path. Keep that chain when touching the success dialog.
- Fixed pixel sizes in the UI are minimums or derive from `QFontMetrics` (see the preview scroll height and the label widths in `main.py`), because at 150%+ display scaling fixed caps crush widgets. Don't introduce new hard caps; scale from font metrics instead.
- Never set an explicit minimum size on the main window (`setMinimumSize`/`setMinimumHeight`): an explicit minimum disables Qt's automatic layout-minimum tracking, so expanding the Output settings section pushed the true minimum past the window's and the preview frame crushed into other elements. The layout already enforces the real minimum (it grows when sections expand), and it scales with fonts automatically.
- `SNAP_DISABLED_MODIFIER` is Alt or Ctrl, not Alt alone: GNOME and other desktops reserve Alt+drag to move the window, which made Alt-only unusable there.
- The preview coalescing contract: at most one render job is in flight, `_preview_queued` holds the newest parameters while busy, and when `_flush_preview_queue()` returns True the just-arrived result is stale and must be dropped without display. Don't apply worker results on the GUI thread except through that gate.
- Concurrency model: one worker `QObject` on one `QThread`, all coalescing state lives on the GUI thread, the shared sprite cache only performs GIL-atomic dict operations on fully decoded images, and there are no locks, so deadlock and livelock are structurally impossible. Starvation is bounded (the worker thread runs at low priority and the GUI never waits on it except the 3s shutdown join). The one accepted benign race is a double sprite decode when two threads first touch the same character; the loser's copy is discarded.
- Profiling findings from 2026-09-27 (`Tools/sample_profiler.py`): generation is PIL-paste dominated at roughly 45ms for 2000 chars with a warm sprite cache, 300 repeated renders hold RSS flat, and Python heap churn is near zero. Don't chase phantom leaks or micro-optimize the paste loop without fresh profiler evidence. The Windows RSS probe only works with `GetCurrentProcess.restype = c_void_p`, the tool shows the working invocation.
- Rotation benchmarks from 2026-09-28, native release cdylib: a 34x32 glyph rotates in 0.18ms Fast / 2.0ms full RotSprite / 0.03ms Nearest, so the editor renders rotations on the GUI thread with no worker thread and stays inside a frame budget. A 400x300 image costs 21ms Fast / 219ms RotSprite; that is why quality degrades by input area (`ROTSPRITE_MAX_PIXELS` = 250k, `FAST_MAX_PIXELS` = 4M in `Src/rotsprite.py`, marked `ponytail:`). Raise those caps only with fresh measurements.
- Rotation invariants: output dimensions are computed once at 1x from the post-quarter-turn bounding box and multiplied by the upscale factor, so all three qualities return the same canvas size for the same input and angle (both engines and both test suites pin this). The native and pure engines are bit-identical across ALL quadrants, guarded by `test_native_matches_pure` at angles including 150/205/225 (a single quadrant-I angle once hid a divergence: the Rust core decomposes quarter turns before the trig pass and the pure engine must do the same `while angle >= 90: transpose; angle -= 90` decomposition or FP trig differences flip border pixels). `rotate()` handles validation, 0 and 90-multiples (float angles included; never `range(angle // 90)` on a float), and degradation before dispatching; the native lib only ever sees a non-90 angle on a size-capped RGBA image, and a native failure code falls back to the pure engine instead of raising. The optional single-pixel detail-restoration step of the original RotSprite is not implemented, so isolated pixels thinner than the downscale block can drop out on noisy backgrounds. `rotate()` handles validation, 0 and 90-multiples, and degradation before dispatching; the native lib only ever sees a non-90 angle on a size-capped RGBA image.
- ctypes quirks that bit once: a `CDLL` function without `argtypes` rejects Python floats ("Don't know how to convert parameter 5"), so `msfr_rotate.argtypes` is declared at load time; slicing a large ctypes array (`out[:n]`) builds a Python list of boxed ints and cost 40ms per rotation, use `ctypes.string_at(out, n)`; the dev-machine candidate path is `Src/../rust/rotsprite-rs/target/release/`, frozen builds find the dll through `_MEIPASS`, and a load failure falls back to pure Python silently by design.
- `preview_failed` carries a reveal flag: True only for character and asset problems where the supported-characters button helps, False for size and unexpected errors. Don't reveal the button for every failure.
- Security posture: no network access, no eval/exec/pickle, config parsing is size-capped, generated filenames are uuid so nothing of the user's is ever overwritten, the supported-characters browser has external links disabled, and QDesktopServices runs only on an explicit user click. Keep it that way.
- linuxdeploy packaging details verified against the AppDir spec: the AppDir root icon must be named exactly like the desktop file's `Icon=` entry (hence `AppDir/MetalSlugFontReborn.png`), and `APPIMAGE_EXTRACT_AND_RUN` comes from the AppImage runtime, not from the linuxdeploy source, so don't expect to find it there.
- The three `except Exception  # noqa: BLE001` guards (`ImageWorker.process`, `ImageWorker.process_preview`, and the editor open in `main.py`) are deliberate crash guards at thread/UI boundaries: any PIL, Qt, or OS error must be relayed to the user as a dialog or signal instead of killing the app or leaving it stuck on "Generating...". Do not narrow them and do not remove the noqa.
- Startup ordering is load-bearing: the preview and char-count timers are created at the very top of `setup_ui`, before the text section connects `textChanged`. The frozen, font-less environment genuinely emits `textChanged` during construction (font substitution re-fires the document), which crashed the bundle until the timers moved up; the bundled offscreen smoke run caught it, tests on the dev machine did not. Re-run that smoke test after any packaging change.
- Title bar status: `_title_status` holds the transient state ("Generating...", "Image saved") and `_update_window_title` always routes through it; clear it on failure paths or the title sticks.
- `_generating` gates the Generate and Advanced Editor buttons for the whole run. Typing re-fires `update_generate_button_state`, so both it and `generate_image` must respect the flag or a second generation queues behind the first while the title and buttons claim the app is idle.
- The unsupported-character highlighter colors come from the palette's BrightText role and refresh via `update_theme` on every theme application, so they follow Light/Dark/Tokyo Night automatically.
- Color swatch icons show the sprite's real palette: `_sample_color_palette` takes the most frequent opaque pixels of the uppercase `A` sprite (up to 6) and `_create_color_icons` draws them as pie slices inside a circle. The dominant color alone is always the dark outline, which is why a single-color swatch looked wrong.
- Editor multi-selection preserves click order: `CharItem.itemChange` reports selection flips to `EditorScene.note_selection_change`, and `ordered_selection()` is the single source the dialog reads, so "first selected" means first clicked. Do not go back to `selectedItems()`, whose order is arbitrary.
- The GPL text is read from the repo's `LICENSE` file by `load_license_text` in `ui_common` (release builds bundle it via `--add-data`), and the supported-characters document is generated from the same disk scan as the charsets, so adding a sprite or a color updates the docs automatically. Don't reintroduce hand-written copies of either.

## Settled decisions (don't re-litigate)

- PySide6-Essentials, not the full PySide6 package.
- tomlkit for `config.toml`, so hand-written comments in the file survive saves.
- Generated files get uuid4 hex names, `generate_filename` ignores its argument. No user-facing file naming.
- One worker `QObject` moved to one `QThread` for the app's lifetime, not a thread pool.
- Pillow renders all output images (RGBA, NEAREST upscale). No QPainter in the generation path.
- Rotation is a Rust cdylib (`rust/rotsprite-rs`) loaded via ctypes, with the pure-Python engine kept as a bit-identical fallback (decided 2026-09-28 after the pure engine froze the GUI at 8x scale). The RotSprite upscale follows Aseprite's implementation (EPX, strict equality, three passes) per the user's reference code, and the final downscale is a majority vote per the original RotSprite spec rather than Aseprite's single-sample `scale_image`, because the vote keeps thin diagonal highlights connected. No third-party rotation or Rust-binding crates; the FFI surface is one function.
- Unit tests run with pytest in `Tests/` (added 2026-09-27 by explicit request, which overrides the ponytail no-framework default). They run headless on the offscreen QPA and must stay display-free and network-free.
- The Linux release artifact is an AppImage (decided 2026-09-27).
- The local Qt C++ install at `C:\Qt` is not used for anything: PySide6 wheels carry the full Qt runtime and PyInstaller bundles from those, and nothing in this repo links against the C++ build. Don't wire it in.
- Release identification (`APP_VERSION`, commit sha, build date) freezes automatically in packaged builds from the bundled `build_commit.txt` and the executable's mtime; never go back to per-run random or per-run dates for those.
- Module names settled 2026-09-27: `main`, `editor`, `image_generation`, `ui_common`, `system_info`, `themes`, `special_characters`. The old names `qt-version`, `qt_utils`, `utils` are retired, don't resurrect them.

## Project conventions

- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) 1.0.0: `type(scope): description`, lowercase imperative mood, no trailing period. Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`. Breaking changes get `!` before the colon plus a `BREAKING CHANGE:` footer.

## Where to look things up

Every third-party library this project uses is installed in `.venv\Lib\site-packages`: PySide6, PIL (Pillow), tomlkit, PyInstaller. The stdlib of the installed interpreter is there too. **This is mandatory and enforced:** never write an import or a call from memory. Before using any third-party API, open the package under `.venv\Lib\site-packages` and confirm the symbol, signature, and behavior actually exist there in the installed version. If it is not in site-packages, it does not exist for this project: do not add a dependency without asking.

- Qt APIs: `PySide6\QtCore`, `PySide6\QtGui`, `PySide6\QtWidgets` in site-packages.
- Pillow APIs: `PIL\` in site-packages.
- Packaging commands: `Docs/BUILD.md`. User-facing features: `README.md`. Project platform/theme docs: `Docs/PLATFORM-COMPATIBILITY.md` and `Docs/THEME-DETECTION.md`. The `.venv` tree is for third-party API verification only; nothing project-owned lives there.
- CLI tooling: see RTK below.

## RTK

RTK (`rtk`) is installed and available on PATH. Use RTK commands whenever an equivalent exists to reduce unnecessary CLI output and context usage.

### Rules

- Prefer `rtk` over the normal command when RTK provides an equivalent.
- Use the normal command when RTK does not provide an appropriate equivalent.
- Do not use RTK if the full/raw output is required for the task.
- Do not run both RTK and the normal command just to compare their output.
- RTK only filters/condenses output; it does not change the underlying command's intended behavior.
- If RTK hides information needed to continue, use `rtk recall` when applicable or run the normal command.

### Common replacements

- `ls` → `rtk ls`
- `tree` → `rtk tree`
- `cat` / file reading → `rtk read`
- `find` → `rtk find`
- `grep` → `rtk grep`
- `rg` → `rtk rg`
- `git ...` → `rtk git ...`
- `gh ...` → `rtk gh ...`
- `curl ...` → `rtk curl ...`
- `wget ...` → `rtk wget ...`

Maven has no RTK equivalent, run `mvn` normally.

### Useful specialized commands

- Use `rtk test` when only test failures/results are needed.
- Use `rtk err` when only errors and warnings are relevant.
- Use `rtk diff` for a compact diff when the full diff is unnecessary.
- Use `rtk json` when inspecting JSON output.
- Use `rtk summary` or `rtk smart` when a concise command summary is useful.

Do not blindly replace every command with RTK; if RTK's filtering could hide information needed to continue, run the normal command.

### Shell tools on this Windows machine

- **ripgrep (`rg`)**, real `.exe` on PATH (BurntSushi via WinGet). The default content-search tool: `rg -n "pattern" path`. `rtk rg` works; `rtk grep` does not, it spawns a `grep` binary that does not exist on Windows, so run `rg` directly instead.
- **uutils/coreutils**, Unix basics as real `.exe` shims on PATH (WinGet): `head`, `tail`, `wc`, `sort`, `tr`, `cut`, `seq`, `od`, `basename`, `dirname`, `realpath`, `touch`, `tee`, and the rest of the coreutils set. Nuance: inside Git Bash sessions the GNU coreutils 8.32 in `/usr/bin` shadow the shims; the shims win in PowerShell/CMD. Behavior-compatible for the documented basics.
- PowerShell built-ins shadow some of those names inside a PowerShell session (`ls`, `cat`, `sort`, `cp`, `mv`, `rm`, `echo`, `pwd`, `mkdir`, `sleep`, `test`), there they resolve to the PS cmdlets, whose flags differ from GNU (e.g. `cat --version` fails); spawned subprocesses and non-PowerShell contexts see the uutils `.exe`s. If a tool "is not on PATH" in a fresh shell, restart PowerShell or dot-source the profile (`. $PROFILE`).
- `find` on PATH is Windows `find.exe`, not GNU find, use `Get-ChildItem -Recurse -Filter` or `rg --files` for file discovery.
- Use UV whenever you can, An extremely fast Python package and project manager, written in Rust.
