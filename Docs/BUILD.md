# Table of contents

- [Platforms](#platforms)
- [Get the source code](#get-the-source-code)
- [Dependencies](#dependencies)
   - [Windows dependencies](#dependencies)
   - [Linux dependencies](#linux-dependencies)
   - [macOS dependencies](#dependencies)
- [Compiling](#compiling)
   - [Windows details](#windows-details)
   - [Linux details](#linux-and-macOS-details)
   - [macOS details](#linux-and-macOS-details)

# Platforms

You should be able to compile MetalSlugFontReborn successfully on the following
platforms:

| Operating System | Supported Versions                                 | Architecture | Tested |
|------------------|----------------------------------------------------|--------------|--------|
| Windows          | 11, 10 (1809 or higher)                            | 64-Bit       |   ✅   |
| GNU/Linux        | Debian 13, Ubuntu 22.04, Fedora 44, Arch Linux     | 64-Bit       |   ✅   |
| macOS            | 14.4 (Ventura) and higher                          | ARM64        |   ❌   |

# Get the source code

You can get the source code by downloading the archive `Source code (zip)` from the [latest release](https://github.com/Mitra-88/MetalSlugFontReborn/releases/latest).

Or you can clone the repository using the following command:
```sh
git clone https://github.com/Mitra-88/MetalSlugFontReborn.git
```
Note: cloning gives you the development branch, which may be broken or unstable. For everyday use, prefer a stable release from the [releases page](https://github.com/Mitra-88/MetalSlugFontReborn/releases/latest).
To update an existing clone you can use the following commands:
```sh
cd MetalSlugFontReborn
git pull
```
# Dependencies

To compile MetalSlugFontReborn you will need the following:

- [uv](https://docs.astral.sh/uv/) to manage the Python interpreter and the Python dependencies. Install it with:
```sh
# macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```
```sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
- [Rust](https://www.rust-lang.org/tools/install) 1.85 or later (the crate uses the 2024 edition), for the native rotation library. Without it the build still works and rotation falls back to a slower pure-Python engine.

The remaining requirements are installed by `uv sync` from `pyproject.toml` and `uv.lock`, so you do not need to install them by hand:

- [Python](https://www.python.org/) 3.15 or later
- [PyInstaller](https://pyinstaller.org/en/stable/) 6.22.2 or later
- [PySide6-Essentials](https://pypi.org/project/PySide6/) 6.12.0 or later
- [Pillow](https://pillow.readthedocs.io/en/stable/) 12.3.0 or later
- [Tomlkit](https://pypi.org/project/tomlkit/) 0.15.1 or later

# Compiling

## Windows details

Open Powershell and run:

```sh
cd MetalSlugFontReborn
uv python install 3.15
uv sync --frozen
git rev-parse --short HEAD > Src\build_commit.txt
cargo build --release --manifest-path rust\rotsprite-rs\Cargo.toml
```
```sh
uv run pyinstaller --noconfirm --onedir --windowed --icon "Assets/Icons/Raubtier.ico" --name "MetalSlugFontReborn" --clean --optimize "2" --version-file "versionfile.txt" --add-data "Src/build_commit.txt;." --add-data "LICENSE;." --add-data "Assets;Assets/" --add-binary "rust/rotsprite-rs/target/release/msfr_rotsprite.dll;."  "Src/main.py"
Move-Item -Path "dist\MetalSlugFontReborn\_internal\Assets" -Destination "dist\MetalSlugFontReborn"
```
Then run the "Trim unused Qt components" step for your OS from [.github/workflows/build.yml](../.github/workflows/build.yml), which is the single source of truth for what gets removed (unused Qt modules like Network, Svg and the Wayland stack, unused image format plugins, dead Pillow codecs, and the core X11 libraries on Linux). Skip that step and the build still works, it is just 40-70% larger.

---

## Linux dependencies

You will need the following dependencies on Ubuntu/Debian:
```sh
sudo apt install -y python3 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-xinerama0 libxcb-render-util0 libxcb-image0 libxcb-shape0 libxcb-randr0 libegl1
```
With these installed, PyInstaller bundles the xcb utility libraries into the Linux
build, so end users need nothing beyond a desktop's standard X11 stack. The core
X11 libraries (libX11, libxcb, libxkbcommon) are always trimmed from the bundle
and come from the user's system, which uses the xcb backend so the window manager
provides a title bar, resizing and a close button.
On Fedora:
```sh
sudo dnf install -y python3 xcb-util-cursor
```
On Arch:
```sh
sudo pacman -Syu --noconfirm xcb-util-cursor
```

## Linux and macOS details

Open the terminal and run:

```sh
cd MetalSlugFontReborn
uv python install 3.15
uv sync --frozen
git rev-parse --short HEAD > Src/build_commit.txt
cargo build --release --manifest-path rust/rotsprite-rs/Cargo.toml
```
```sh
uv run pyinstaller --noconfirm --onedir --windowed --strip --name "MetalSlugFontReborn" --clean --optimize "2" --add-data "Src/build_commit.txt:." --add-data "LICENSE:." --add-data "Assets:Assets/" --add-binary "rust/rotsprite-rs/target/release/libmsfr_rotsprite.so:."  "Src/main.py"
mv dist/MetalSlugFontReborn/_internal/Assets dist/MetalSlugFontReborn/
```
Then run the Linux (or macOS) "Trim unused Qt components" step from [.github/workflows/build.yml](../.github/workflows/build.yml). On Linux this also deletes the bundled core X11 libraries (libX11, libxcb, libxkbcommon): they must come from the user's system, and the workflow's bundle assertions fail the build if they ever come back.

On macOS the rotation library is named `libmsfr_rotsprite.dylib`, so use that file name in the `--add-binary` flag.
