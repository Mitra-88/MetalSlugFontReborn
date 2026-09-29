# Theme Detection

How MetalSlugFontReborn decides between Light, Dark, and Tokyo Night, and how
the Qt widget style is chosen per platform.

## Startup chain

1. If the user has ever picked a theme from the menu, that choice is stored in
   `config.toml` (`theme = "Dark"` etc.) and wins permanently.
2. Otherwise the app follows the system: `resolve_auto_theme()` reads
   `QStyleHints.colorScheme()` (Qt 6.5+) and maps it:
   - `ColorScheme.Dark` -> Dark theme
   - `ColorScheme.Light` or `ColorScheme.Unknown` -> Light theme
3. While the user has not picked a theme, the app stays connected to
   `QStyleHints.colorSchemeChanged` and re-applies on live system theme
   changes. Once a theme is picked from the menu, the follower disconnects for
   that session and the choice is saved.

Wrong-typed values in `config.toml` (for example `theme = {}`, which is valid
TOML but not a string) are type-guarded and fall back to the auto theme
instead of crashing.

## What Qt consults per platform

`QStyleHints.colorScheme()` is the single app-side API. Under the hood Qt
resolves it per platform:

- **Windows:** the registry value
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\AppsUseLightTheme`.
  Works on Windows 10 1903+ and Windows 11. Older Windows 10 builds report
  `Unknown`, and the app uses Light.
- **macOS:** `NSApplication.effectiveAppearance` (`Aqua` or `Dark Aqua`).
  Those NSAppearance identifiers are internal to Apple's layer and are never
  passed to Qt. The Qt widget style name for macOS is `macOS`.
- **Linux:** the platform theme queries `org.freedesktop.appearance`
  `color-scheme` over the XDG Desktop Portal (GNOME, KDE Plasma, Cinnamon,
  XFCE 4.18+, LXQt, COSMIC all ship one). Without a portal or DE support
  (LXDE, i3, headless), Qt returns `Unknown` and the app uses Light. The app
  intentionally does not read `gsettings` or the Windows registry itself:
  Qt already aggregates those sources, and a second implementation would only
  add ways to disagree with Qt.

## Un-detectable systems: the startup chooser

When `colorScheme()` reports `Unknown` (Windows 10 pre-1903, LXDE, i3,
headless), the app shows a small dialog *before* the main window is created:
"Pick the theme you want to use", with Light, Dark, and Tokyo Night buttons
and a "Don't ask again" checkbox. Picking applies and saves the theme; closing
or ticking the checkbox stores `skip_theme_prompt` and keeps the Light
default. The popup runs between `QApplication` creation and
`MainWindow()`/`show()`, so the main window never flashes with a theme the
user did not choose. It reappears on later starts until a theme is actually
picked.

## Widget style names

The Qt widget style is picked by `pick_style()` in `Src/main.py`, validated
against `QStyleFactory.keys()` so an unknown name degrades to Fusion:

| Platform | Style name |
|---|---|
| Windows 11 | `windows11` |
| Windows 10 | `Fusion` |
| macOS | `macOS` (the Qt 6 name; `macintosh` was Qt 5, and `Aqua`/`Dark Aqua` are NSAppearance names, not Qt styles) |
| Linux | `Fusion` |

Common bug this guards against: calling `setStyle()` with a name Qt does not
have (for example `FluentWinUI3` or `Aqua`) silently does nothing.

## Testing

- `Tests/test_ui_common.py`: `resolve_auto_theme` mapping (Dark/Light/Unknown),
  explicit theme persistence, auto mode never persisting, unknown names
  ignored, wrong-typed stored value tolerated.
- `Tests/test_main.py`: `pick_style` per-OS table including missing-style and
  case-insensitive fallbacks.
- `Docs/PLATFORM-COMPATIBILITY.md`: which OS/DE/protocol combinations were
  actually exercised.
