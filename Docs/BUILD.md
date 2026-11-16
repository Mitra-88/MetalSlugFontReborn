# Build MetalSlugFontReborn

## Requirements
- [uv](https://astral.sh/uv)
- [Rust](https://www.rust-lang.org/) (**Highly Recommended**, for the native rotation engine)

On Linux, install the XCB utility:
```sh
# Ubuntu/Debian
sudo apt install libxcb-cursor0

# Fedora
sudo dnf install xcb-util-cursor

# Arch
sudo pacman -S xcb-util-cursor
```

## Setup
1. Clone the repository and enter the directory.
2. Initialize the environment and build the native engine.

```sh
git clone https://github.com/Mitra-88/MetalSlugFontReborn.git
cd MetalSlugFontReborn
uv sync
git rev-parse --short HEAD > Src/build_commit.txt
cargo build --release --manifest-path rust/rotsprite-rs/Cargo.toml
```

## Packaging
Generate the application bundle with PyInstaller.

### Windows (PowerShell)
```powershell
uv run python Tools/make_versionfile.py
uv run pyinstaller --noconfirm --onedir --windowed --icon "Assets/Icons/Raubtier.ico" --name "MetalSlugFontReborn" --clean --optimize "2" --version-file "versionfile.txt" --add-data "Src/build_commit.txt;." --add-data "LICENSE;." --add-data "Assets;Assets/" --add-binary "rust/rotsprite-rs/target/release/msfr_rotsprite.dll;." "Src/main.py"
Move-Item "dist/MetalSlugFontReborn/_internal/Assets" "dist/MetalSlugFontReborn"
```

### Linux
```sh
uv run pyinstaller --noconfirm --onedir --windowed --strip --name "MetalSlugFontReborn" --clean --optimize "2" --add-data "Src/build_commit.txt:." --add-data "LICENSE:." --add-data "Assets:Assets/" --add-binary "rust/rotsprite-rs/target/release/libmsfr_rotsprite.so:." "Src/main.py"
mv dist/MetalSlugFontReborn/_internal/Assets dist/MetalSlugFontReborn/
```

### macOS
```sh
uv run pyinstaller --noconfirm --onedir --windowed --strip --name "MetalSlugFontReborn" --clean --optimize "2" --add-data "Src/build_commit.txt:." --add-data "LICENSE:." --add-data "Assets:Assets/" --add-binary "rust/rotsprite-rs/target/release/libmsfr_rotsprite.dylib:." "Src/main.py"
mv dist/MetalSlugFontReborn/_internal/Assets dist/MetalSlugFontReborn/
```

## Optimization
The commands above create a functional but large build. Release artifacts are further reduced by removing unused Qt modules and Pillow codecs. The exact trim lists are in [.github/workflows/build.yml](../.github/workflows/build.yml).
