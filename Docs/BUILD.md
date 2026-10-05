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

| Operating System | Supported Versions                             | Architecture |
|------------------|------------------------------------------------|--------------|
| Windows          | 11, 10 (1809 or later)                         | 64-Bit       |
| GNU/Linux        | Debian 13, Ubuntu 26.04, Fedora 44, Arch Linux | 64-Bit       |
| macOS            | 13 (Ventura) and later                         | ARM64        |

# Get the source code

You can get the source code by downloading the archive `Source code (zip)` from the [latest release](https://github.com/Mitra-88/MetalSlugFontReborn/releases/latest).

Or you can clone the repository using the following command:
```sh
git clone https://github.com/Mitra-88/MetalSlugFontReborn.git
```
To update an existing clone you can use the following commands:
```sh
cd MetalSlugFontReborn
git pull
```
# Dependencies

To compile MetalSlugFontReborn you will need the following:

- [Python](https://www.python.org/) 3.12 or later
- [Rust](https://www.rust-lang.org/tools/install) 1.85 or later (the crate uses the 2024 edition), for the native rotation library. Without it the build still works and rotation falls back to a slower pure-Python engine.
- [PyInstaller](https://pyinstaller.org/en/stable/) 6.22.2 or later
- [PySide6-Essentials](https://pypi.org/project/PySide6/) 6.11.2 or later
- [Pillow](https://pillow.readthedocs.io/en/stable/) 12.3.0 or later
- [Tomlkit](https://pypi.org/project/tomlkit/) 0.15.1 or later

# Compiling

## Windows details

Open Powershell and run:

```sh
cd MetalSlugFontReborn
uv python install 3.14.8
uv sync --frozen
git rev-parse --short HEAD > Src\build_commit.txt
cargo build --release --manifest-path rust\rotsprite-rs\Cargo.toml
```
```sh
pyinstaller --noconfirm --onedir --windowed --icon "Assets/Icons/Raubtier.ico" --name "MetalSlugFontReborn" --clean --optimize "2" --version-file "versionfile.txt" --add-data "Src/build_commit.txt;." --add-data "LICENSE;." --add-data "Assets;Assets/" --add-binary "rust/rotsprite-rs/target/release/msfr_rotsprite.dll;."  "Src/main.py"
Move-Item -Path "dist\MetalSlugFontReborn\_internal\Assets" -Destination "dist\MetalSlugFontReborn"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "dist\MetalSlugFontReborn\_internal\PySide6\translations", "dist\MetalSlugFontReborn\_internal\PySide6\plugins\tls", "dist\MetalSlugFontReborn\_internal\PySide6\plugins\networkinformation", "dist\MetalSlugFontReborn\_internal\PySide6\plugins\generic", "dist\MetalSlugFontReborn\_internal\PySide6\plugins\iconengines", "dist\MetalSlugFontReborn\_internal\setuptools"
Remove-Item -Force -ErrorAction SilentlyContinue "dist\MetalSlugFontReborn\_internal\PySide6\opengl32sw.dll", "dist\MetalSlugFontReborn\_internal\PySide6\Qt6Network.dll", "dist\MetalSlugFontReborn\_internal\PySide6\Qt6Svg.dll", "dist\MetalSlugFontReborn\_internal\libcrypto-3-x64.dll", "dist\MetalSlugFontReborn\_internal\libssl-3-x64.dll"
```

---

## Linux dependencies

You will need the following dependencies on Ubuntu/Debian:
```sh
sudo apt install -y python3 python3-pip python3-venv libxcb-cursor0
```
`libxcb-cursor0` is also required at runtime by the packaged build, which
uses the xcb backend on Linux so the window manager provides a title bar,
resizing and a close button.
On Fedora:
```sh
sudo dnf install -y python3 python3-pip python3-virtualenv xcb-util-cursor
```
On Arch:
```sh
sudo pacman -Syu --noconfirm python-pip python-virtualenv xcb-util-cursor
```

## Linux and macOS details

Open the terminal and run:

```sh
cd MetalSlugFontReborn
uv python install 3.14.8
uv sync --frozen
git rev-parse --short HEAD > Src/build_commit.txt
cargo build --release --manifest-path rust/rotsprite-rs/Cargo.toml
```
```sh
pyinstaller --noconfirm --onedir --windowed --strip --name "MetalSlugFontReborn" --clean --optimize "2" --add-data "Src/build_commit.txt:." --add-data "LICENSE:." --add-data "Assets:Assets/" --add-binary "rust/rotsprite-rs/target/release/libmsfr_rotsprite.so:."  "Src/main.py"
mv dist/MetalSlugFontReborn/_internal/Assets dist/MetalSlugFontReborn/
rm -rf dist/MetalSlugFontReborn/_internal/PySide6/translations dist/MetalSlugFontReborn/_internal/PySide6/plugins/tls dist/MetalSlugFontReborn/_internal/PySide6/plugins/networkinformation dist/MetalSlugFontReborn/_internal/PySide6/plugins/generic dist/MetalSlugFontReborn/_internal/PySide6/plugins/iconengines dist/MetalSlugFontReborn/_internal/setuptools
rm -f dist/MetalSlugFontReborn/_internal/PySide6/Qt6Network* dist/MetalSlugFontReborn/_internal/PySide6/Qt6Svg* dist/MetalSlugFontReborn/_internal/libcrypto* dist/MetalSlugFontReborn/_internal/libssl*
rm -rf dist/MetalSlugFontReborn/_internal/PySide6/Qt/translations dist/MetalSlugFontReborn/_internal/PySide6/Qt/plugins/tls dist/MetalSlugFontReborn/_internal/PySide6/Qt/plugins/networkinformation dist/MetalSlugFontReborn/_internal/PySide6/Qt/plugins/generic dist/MetalSlugFontReborn/_internal/PySide6/Qt/plugins/iconengines
rm -f dist/MetalSlugFontReborn/_internal/PySide6/Qt/lib/libQt6Network* dist/MetalSlugFontReborn/_internal/PySide6/Qt/lib/libQt6Svg* dist/MetalSlugFontReborn/_internal/PySide6/Qt/lib/libcrypto* dist/MetalSlugFontReborn/_internal/PySide6/Qt/lib/libssl*
```

On macOS the rotation library is named `libmsfr_rotsprite.dylib`, so use that file name in the `--add-binary` flag.
