import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Src"))

from system_info import APP_VERSION

VERSION_FILE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({tuple}),
    prodvers=({tuple}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'Mitra-88'),
        StringStruct(u'FileDescription', u'MetalSlugFontReborn'),
        StringStruct(u'FileVersion', u'{dotted}'),
        StringStruct(u'InternalName', u'MetalSlugFontReborn'),
        StringStruct(u'LegalCopyright', u'GNU General Public License v3.0.'),
        StringStruct(u'OriginalFilename', u'MetalSlugFontReborn.exe'),
        StringStruct(u'ProductName', u'MetalSlugFontReborn'),
        StringStruct(u'ProductVersion', u'{dotted}')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [0, 1200, 1033, 1252])])
  ]
)
"""


def version_file_text():
    parts = APP_VERSION.split(".")
    while len(parts) < 4:
        parts.append("0")
    return VERSION_FILE.format(tuple=",".join(parts), dotted=".".join(parts))


def main():
    (ROOT / "versionfile.txt").write_text(version_file_text(), encoding="utf-8")


if __name__ == "__main__":
    main()
