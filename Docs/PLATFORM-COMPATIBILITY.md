# Platform Compatibility

Cross-platform notes for MetalSlugFontReborn (PySide6, Pillow, PyInstaller
one-dir builds). Last verified: 2026-09-27.

## Build environment vs user systems

The bundles are built on pinned CI images so the shipped libraries are never
newer than what a reasonable user system provides:

- **Linux:** built on `ubuntu-22.04` (glibc 2.35 floor). The bundle runs on
  that glibc and anything newer, including rolling distributions.
- **Windows:** built on `windows-latest`; the complete CRT set ships app-local
  (`VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`, `MSVCP140.dll`,
  `MSVCP140_1.dll`, `MSVCP140_2.dll`, `ucrtbase.dll`). No separate VC++
  redistributable install is required on clean Windows 10 or 11 machines;
  a missing-DLL or "entry point not found" error there means the bundle was
  damaged, not a runtime conflict.
- **macOS:** built on `macos-15` (Apple Silicon) with the Python 3.14
  universal2 build. The minimum macOS version follows that interpreter's
  deployment target, so the bundle opens on the macOS versions that Python
  3.14 supports and newer.

**Why we exclude system libraries instead of shipping them:** on Linux the
bundle deliberately does not ship OpenSSL, libxcb, or the host's X/Wayland
libraries. Qt loads those from the user's system at runtime, which means
newer host versions are used instead of stale bundled copies. Shipping older
copies is the classic cause of "undefined symbol" and plugin-initialization
crashes on machines newer than the build machine.

## Qt platform plugins

PyInstaller's PySide6 hooks collect the platform plugins (`platforms/`,
`styles/`, `imageformats/`, `platforminputcontexts/`) from the same PySide6
wheel as the linked Qt libraries, so plugin and Qt versions match by
construction. The post-build trim step keeps:

- `plugins/platforms` (qwindows, libqxcb, libqwayland-egl, libqwayland-generic)
- `plugins/styles` (windows11 / macOS / Fusion)
- `plugins/imageformats` (PNG and ICO support)
- `plugins/platforminputcontexts` (compose input on Linux)

**Missing-plugin diagnostic:** frozen builds run a pre-flight check
(`missing_plugin_message` in `Src/main.py`) before Qt starts. If
`plugins/platforms` is missing or empty, the app exits with a clear message
(a dialog on Windows, stderr elsewhere) that names the expected path, instead
of Qt's raw "could not load the Qt platform plugin" abort.

## Trimmed components and why

| Component | Reason |
|---|---|
| `opengl32sw.dll` | Software OpenGL fallback; the app is raster-only |
| `Qt6Network` / TLS / `networkinformation` plugin | The app makes no network connections |
| `Qt6Svg` / `iconengines` | No SVG assets or icons (PNG and ICO come from `imageformats`) |
| `translations/` | Qt's own translator catalogs; the app is English-only |
| `libcrypto-3` / `libssl-3` | No TLS clients |
| `setuptools` | PyInstaller leftover, unused at runtime |

These live as the "Trim unused Qt components" step in the CI workflows and
`Docs/BUILD.md`, so the exclusion list and its reasons are version-controlled
next to the code. We deliberately do not use `.spec` files: the CLI commands
in the workflows are the single source of truth, and a spec file would just
duplicate the same list in a third place.

## Linux desktop environments

| Environment | Protocol | Notes |
|---|---|---|
| GNOME | Wayland / X11 | Theme and file dialogs via xdg-desktop-portal |
| KDE Plasma | Wayland / X11 | Portal theme query; Qt native dialogs |
| Cinnamon | X11 | Portal where available, Qt fallback otherwise |
| XFCE | X11 | Same as Cinnamon |
| LXQt | X11 | Qt-based DE; generic Qt theme fallback |
| LXDE | X11 | No portal; generic theme fallback, Light theme default |
| COSMIC | Wayland | Portal-based theming; Wayland plugin bundled |

- **File dialogs:** Qt talks to the XDG Desktop Portal through the platform
  theme when one is present; without a portal (LXDE, minimal setups) Qt falls
  back to its own dialog automatically. No code needed for either path.
- **Input methods:** frozen Linux builds force `QT_IM_MODULE=compose` because
  the bundled IBus plugin crashes against newer system IBus daemons on X11.
  Consequence: no CJK input method support in frozen Linux builds (the sprite
  fonts contain no CJK glyphs anyway). Dev builds keep the system IM.
- **HiDPI:** Qt 6 handles integer and fractional scaling automatically, per
  screen, on both protocols. Mixed-DPI multi-monitor setups are handled by Qt's
  per-screen scale factors; all window minimums in the app are layout-driven
  and font-metric derived, so they scale.

## Windows

- Windows 10 and 11 are both supported from one build. The widget style is
  `windows11` on Windows 11 and Fusion on Windows 10, validated against
  `QStyleFactory.keys()` at startup.
- Dark mode is read through `QStyleHints.colorScheme()`, which resolves the
  registry `AppsUseLightTheme` value on both Windows versions; live dark-mode
  toggles are followed (see `Docs/THEME-DETECTION.md`).
- Mixed-DPI multi-monitor setups use Qt 6's per-screen scale factors; window
  minimums are layout-driven, so they hold on any monitor.
- File dialogs, taskbar icon, and window snapping are standard Qt behaviors
  over the native Win32 window; no custom window chrome is used.
- Text handling is UTF-8 internally end to end (Qt strings, explicit
  encodings on file reads, Unicode-safe pathlib), so system locale or codepage
  does not affect rendering or file names.

## macOS

- The Qt style name for macOS is `macOS` (Qt 6 renamed the legacy
  `macintosh` style). The app validates it against `QStyleFactory.keys()`.
  NSAppearance identifiers (`Aqua`, `Dark Aqua`) belong to Apple's layer and
  are never passed to Qt.
- Dark/light detection uses `QStyleHints.colorScheme()`, which maps to
  `NSApplication.effectiveAppearance` internally.
- **Gatekeeper:** the bundle is unsigned, so a clean machine blocks first
  launch. Workaround: right-click the app and choose Open, or run
  `xattr -cr MetalSlugFontReborn.app`. Proper fix requires an Apple Developer
  ID for signing and notarization, which the project does not currently have.

## Tested matrix

| Combination | Status |
|---|---|
| Windows 11, GUI use (dev machine) | Tested every release |
| Windows CI build + offscreen smoke run | Tested every release |
| Linux CI build (ubuntu-22.04) + offscreen smoke run | Tested every release |
| macOS CI build | Build-tested, launch not verified (no hardware) |
| Real Wayland sessions (GNOME/KDE/COSMIC) by hand | Not exercised by the maintainer; covered by bundled Wayland plugin + portal design |
| Windows on a clean VM without VC++ installed | Not run; CRT DLLs verified present in the bundle |

Known remaining limitations: macOS launch is unverified on real hardware and
blocked by Gatekeeper until signed; CJK input is unavailable in frozen Linux
builds (compose IM workaround); no distribution-wide Linux packages (deb/rpm),
the release artifact is the PyInstaller folder.
