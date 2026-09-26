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
- [PyInstaller](https://pyinstaller.org/en/stable/) 6.22.2 or later
- [PySide6-Essentials](https://pypi.org/project/PySide6/) 6.11.2 or later
- [Pillow](https://pillow.readthedocs.io/en/stable/) 12.3.0 or later
- [Tomlkit](https://pypi.org/project/tomlkit/) 0.15.1 or later

# Compiling

## Windows details

Open Powershell and run:

```sh
cd MetalSlugFontReborn
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
```sh
pyinstaller --noconfirm --onedir --windowed --icon "Assets/Icons/Raubtier.ico" --name "MetalSlugFontReborn" --clean --optimize "2" --version-file "versionfile.txt" --add-data "Src/image_generation.py;." --add-data "Src/ui_common.py;." --add-data "Src/special_characters.py;." --add-data "Src/themes.py;." --add-data "Src/system_info.py;." --add-data "Src/editor.py;." --add-data "Assets;Assets/"  "Src/main.py"
Move-Item -Path "dist\MetalSlugFontReborn\_internal\Assets" -Destination "dist\MetalSlugFontReborn"
```

---

## Linux dependencies

You will need the following dependencies on Ubuntu/Debian:
```sh
sudo apt install -y python3 python3-pip python3-venv libxcb-cursor0
```
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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
```sh
pyinstaller --noconfirm --onedir --windowed --strip --name "MetalSlugFontReborn" --clean --optimize "2" --add-data "Src/image_generation.py:." --add-data "Src/ui_common.py:." --add-data "Src/special_characters.py:." --add-data "Src/themes.py:." --add-data "Src/system_info.py:." --add-data "Src/editor.py:." --add-data "Assets:Assets/"  "Src/main.py"
mv dist/MetalSlugFontReborn/_internal/Assets dist/MetalSlugFontReborn/
```
