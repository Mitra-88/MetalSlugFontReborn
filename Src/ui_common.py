import sys
from pathlib import Path
from platform import python_version

import tomlkit
from PIL import __version__ as pillow_version
from PyInstaller import __version__ as pyinstaller_version
from PySide6 import __version__ as pyside6_version
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from special_characters import LICENSE_TEXT
from system_info import build_date, get_system_info, msfr_version
from themes import dark_mode, light_mode, tokyo_night

ABOUT_DIALOG_MIN_WIDTH = 450
ABOUT_LAYOUT_SPACING = 15
INFO_LAYOUT_SPACING = 2
APP_ICON_SIZE = 64
APP_NAME_FONT_SIZE = 14
BUILD_INFO_V_SPACING = 4

theme_list = {
    "Light": light_mode,
    "Dark": dark_mode,
    "Tokyo Night": tokyo_night,
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if getattr(sys, "frozen", False):
    CONFIG_FILE = Path(sys.executable).resolve().parent / "config.toml"
else:
    CONFIG_FILE = PROJECT_ROOT / "config.toml"

MAX_FILE_SIZE_BYTES = 15 * 1024


class Config:
    def __init__(self, path: Path = CONFIG_FILE):
        self._path = path
        self._doc = tomlkit.document()
        self._load()

    def _load(self):
        if not self._path.exists():
            return
        if self._path.stat().st_size > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"Config file exceeds safety limit ({self._path.stat().st_size} bytes)."
            )
        self._doc = tomlkit.loads(self._path.read_text(encoding="utf-8"))

    def get(self, key: str, fallback=None):
        return self._doc.get(key, fallback)

    def set(self, key: str, value):
        self._doc[key] = value
        self._save()

    def _save(self):
        self._path.write_text(tomlkit.dumps(self._doc), encoding="utf-8")


config = Config()


def load_config(key, fallback=None):
    return config.get(key, fallback)


def save_config(key, value):
    config.set(key, value)


def set_theme(theme_name=None):
    theme_name = theme_name or load_config("theme")
    if theme_name not in theme_list:
        return
    palette = theme_list[theme_name]()
    QApplication.setPalette(palette)
    save_config("theme", theme_name)


def create_group(title, content):
    group = QGroupBox(title)
    group.setLayout(content)
    return group


def about_section(parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle("About MetalSlugFontReborn")
    dialog.setMinimumWidth(ABOUT_DIALOG_MIN_WIDTH)

    main_layout = QVBoxLayout()
    tab_widget = QTabWidget()

    about_tab = QWidget()
    about_layout = QVBoxLayout(about_tab)
    about_layout.setSpacing(ABOUT_LAYOUT_SPACING)

    header = QHBoxLayout()

    icon = QLabel()
    pixmap = QPixmap("Assets/Icons/Raubtier.png")
    if not pixmap.isNull():
        icon.setPixmap(
            pixmap.scaled(
                APP_ICON_SIZE,
                APP_ICON_SIZE,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    info = QVBoxLayout()
    info.setSpacing(INFO_LAYOUT_SPACING)

    app_name = QLabel("MetalSlugFontReborn")
    font = app_name.font()
    font.setPointSize(APP_NAME_FONT_SIZE)
    font.setBold(True)
    app_name.setFont(font)

    license_label = QLabel("GPL-3.0 Licensed")

    github = QLabel(
        '<a href="https://github.com/Mitra-88/MetalSlugFontReborn">GitHub Repository</a>'
    )
    github.setOpenExternalLinks(True)

    info.addWidget(app_name)
    info.addWidget(license_label)
    info.addWidget(github)

    header.addWidget(icon, alignment=Qt.AlignTop)
    header.addLayout(info)
    header.addStretch()

    about_layout.addLayout(header)

    os_layout = QVBoxLayout()
    os_label = QLabel(f"OS: {get_system_info()}")
    os_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    os_label.setWordWrap(True)
    os_layout.addWidget(os_label)

    about_layout.addWidget(create_group("Operating System:", os_layout))
    build_info = QGridLayout()
    build_info.setVerticalSpacing(BUILD_INFO_V_SPACING)

    build_items = [
        ("Version:", msfr_version),
        ("Python:", python_version()),
        ("PyInstaller:", pyinstaller_version),
        ("PySide6:", pyside6_version),
        ("Pillow:", pillow_version),
        ("Build date:", build_date),
    ]

    for row, (label_text, value) in enumerate(build_items):
        lbl = QLabel(f"<b>{label_text}</b>")
        val = QLabel(str(value))

        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        val.setTextInteractionFlags(Qt.TextSelectableByMouse)

        build_info.addWidget(lbl, row, 0)
        build_info.addWidget(val, row, 1)

    build_group = create_group("Build Information:", build_info)
    about_layout.addWidget(build_group)

    about_layout.addStretch()
    tab_widget.addTab(about_tab, "About")

    license_tab = QWidget()
    license_layout = QVBoxLayout(license_tab)

    license_text_edit = QPlainTextEdit()
    license_text_edit.setPlainText(LICENSE_TEXT)
    license_text_edit.setReadOnly(True)
    license_text_edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)

    license_layout.addWidget(license_text_edit)
    tab_widget.addTab(license_tab, "License")

    main_layout.addWidget(tab_widget)

    button_box = QDialogButtonBox(QDialogButtonBox.Ok)
    button_box.button(QDialogButtonBox.Ok).setText("Close")
    button_box.accepted.connect(dialog.accept)

    main_layout.addWidget(button_box, alignment=Qt.AlignRight)

    dialog.setLayout(main_layout)
    dialog.exec()


MARKDOWN_CONTENT = """\
# MetalSlugFontReborn Character Support

Here you can find which characters MetalSlugFontReborn supports.

## Font 1 Support

- **Letters:** Lowercase and Uppercase
- **Numbers:** 0 to 9
- **Symbols:** , * {} () ^ : $ = ! > - ∞ < # % . + & ? " ; / ~ _ | ¥ ⛶ © ♥ ▲ ▼ ◀ ▶ ⋆ ★ ☞ ✖
- **Colors:** Blue, Orange and Gold

## Font 2 Support

- **Letters:** Lowercase and Uppercase
- **Numbers:** 0 to 9
- **Symbols:** , = ︷ ! - . + & ? / ♪ ✖
- **Colors:** Blue, Orange and Gold

## Font 3 Support

- **Letters:** Lowercase and Uppercase
- **Numbers:** 0 to 9
- **Symbols:** ' {} () : , = ! > - < . + ? " ; / _ | ¥ ⛶ © ♥ ▲ ▼ ◀ ▶ ✖
- **Colors:** Blue and Orange

## Font 4 Support

- **Letters:** Lowercase and Uppercase
- **Numbers:** 0 to 9
- **Symbols:** ' * {} () ^ : $ = ! > - < # % . + & ? " ; / ~ _ ¥ ⛶ © ♥ ▲ ▼ ◀ ▶ | ✖
- **Colors:** Blue, Orange and Yellow

## Font 5 Support

- **Letters:** Uppercase
- **Numbers:** 1 to 9
- **Symbols:** ! ?
- **Colors:** Orange

# Unsupported Characters (Unused)

- **Symbols:** ȧ ä ā á à â ã í ü ū ú ė ë é ê ö ō ó ô Ⅰ Ⅱ Ⅲ Ⅳ Ⅴ
"""


class SupportedCharactersDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Supported Characters")
        self.setMinimumSize(580, 640)
        self.resize(620, 720)
        self.setWindowIcon(
            QIcon(str(PROJECT_ROOT / "Assets" / "Icons" / "Raubtier.ico"))
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        header = QLabel("Character Support Reference")
        header.setAlignment(Qt.AlignCenter)
        font = header.font()
        font.setPointSize(14)
        font.setBold(True)
        header.setFont(font)
        root.addWidget(header)

        sub = QLabel("Check below to see which characters your font can render.")
        sub.setAlignment(Qt.AlignCenter)
        root.addWidget(sub)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setMarkdown(MARKDOWN_CONTENT)
        root.addWidget(browser, 1)

        row = QHBoxLayout()
        row.addStretch()
        close_btn = QPushButton("Got it!")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        row.addStretch()
        root.addLayout(row)


def open_supported_characters(parent=None):
    dlg = SupportedCharactersDialog(parent)
    dlg.exec()


class ViewSupportedButton(QPushButton):
    clicked_open = Signal()

    def __init__(self, parent=None):
        super().__init__("View Supported Characters", parent)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._on_click)

    def reveal(self):
        self.setText("Unsupported character! Click here to view supported")

    def reset_to_normal(self):
        self.setText("View Supported Characters")

    def _on_click(self):
        self.reset_to_normal()
        self.clicked_open.emit()
        open_supported_characters(self.window())
