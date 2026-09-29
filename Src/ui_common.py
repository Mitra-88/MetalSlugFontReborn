import os
import sys
from pathlib import Path
from platform import python_version

import tomlkit
from PIL import __version__ as pillow_version
from PyInstaller import __version__ as pyinstaller_version
from PySide6 import __version__ as pyside6_version
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from tomlkit.exceptions import TOMLKitError

from image_generation import get_font_charset, get_font_colors, get_font_ids
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
        try:
            if self._path.stat().st_size > MAX_FILE_SIZE_BYTES:
                return
            self._doc = tomlkit.loads(self._path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TOMLKitError):
            pass

    def get(self, key: str, fallback=None):
        return self._doc.get(key, fallback)

    def set(self, key: str, value):
        self._doc[key] = value
        self._save()

    def _save(self):
        tmp = self._path.with_name(self._path.name + ".part")
        try:
            tmp.write_text(tomlkit.dumps(self._doc), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


config = Config()


def load_config(key, fallback=None):
    return config.get(key, fallback)


def save_config(key, value):
    config.set(key, value)


def resolve_auto_theme(scheme=None):
    if scheme is None:
        scheme = QApplication.styleHints().colorScheme()
    return "Dark" if scheme == Qt.ColorScheme.Dark else "Light"


def set_theme(theme_name=None):
    if theme_name is None:
        theme_name = load_config("theme")
        if not isinstance(theme_name, str) or theme_name not in theme_list:
            theme_name = resolve_auto_theme()
        QApplication.setPalette(theme_list[theme_name]())
        return
    if theme_name not in theme_list:
        return
    QApplication.setPalette(theme_list[theme_name]())
    save_config("theme", theme_name)


def theme_setup_needed(scheme=None):
    if scheme is None:
        scheme = QApplication.styleHints().colorScheme()
    if scheme != Qt.ColorScheme.Unknown:
        return False
    saved = load_config("theme")
    if isinstance(saved, str) and saved in theme_list:
        return False
    skip = load_config("skip_theme_prompt", fallback=False)
    return not (isinstance(skip, bool) and skip)


def build_theme_setup_dialog(parent=None):
    dialog = QMessageBox(parent)
    dialog.setWindowTitle("Choose a Theme")
    dialog.setText(
        "The system theme could not be detected.\nPick the theme you want to use:"
    )
    theme_buttons = {
        name: dialog.addButton(name, QMessageBox.AcceptRole) for name in theme_list
    }
    dialog.addButton(QMessageBox.Close)
    dont_ask = QCheckBox("Don't ask again")
    dialog.setCheckBox(dont_ask)
    return dialog, theme_buttons, dont_ask


def apply_theme_choice(dialog, theme_buttons, dont_ask_checked):
    clicked = dialog.clickedButton()
    for name, button in theme_buttons.items():
        if button is clicked:
            set_theme(name)
            if dont_ask_checked:
                save_config("skip_theme_prompt", True)
            return name
    if dont_ask_checked:
        save_config("skip_theme_prompt", True)
    return None


def show_theme_setup_dialog(parent=None):
    dialog, theme_buttons, dont_ask = build_theme_setup_dialog(parent)
    dialog.exec()
    return apply_theme_choice(dialog, theme_buttons, dont_ask.isChecked())


def create_group(title, content):
    group = QGroupBox(title)
    group.setLayout(content)
    return group


GITHUB_URL = "https://github.com/Mitra-88/MetalSlugFontReborn"
ISSUES_URL = GITHUB_URL + "/issues"


def build_info_rows():
    return [
        ("Operating System:", get_system_info()),
        ("Version:", msfr_version),
        ("Build date:", build_date),
        ("Python:", python_version()),
        ("Qt (PySide6):", pyside6_version),
        ("Pillow:", pillow_version),
        ("PyInstaller:", pyinstaller_version),
    ]


def system_diagnostics():
    return "\n".join(f"{label} {value}" for label, value in build_info_rows())


def build_about_dialog(parent=None):
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
    pixmap = QPixmap(str(PROJECT_ROOT / "Assets" / "Icons" / "Raubtier.png"))
    if not pixmap.isNull():
        icon.setPixmap(
            pixmap.scaled(
                APP_ICON_SIZE,
                APP_ICON_SIZE,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )
    header.addWidget(icon, alignment=Qt.AlignTop)

    info = QVBoxLayout()
    info.setSpacing(INFO_LAYOUT_SPACING)

    app_name = QLabel("MetalSlugFontReborn")
    name_font = app_name.font()
    name_font.setPointSize(APP_NAME_FONT_SIZE)
    name_font.setBold(True)
    app_name.setFont(name_font)

    version_label = QLabel(msfr_version)
    version_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

    license_label = QLabel("GPL-3.0 Licensed")

    links = QLabel(
        f'<a href="{GITHUB_URL}">GitHub Repository</a><br>'
        f'<a href="{ISSUES_URL}">Report an Issue</a>'
    )
    links.setOpenExternalLinks(True)

    info.addWidget(app_name)
    info.addWidget(version_label)
    info.addWidget(license_label)
    info.addWidget(links)
    header.addLayout(info)
    header.addStretch()

    about_layout.addLayout(header)

    system_grid = QGridLayout()
    system_grid.setVerticalSpacing(BUILD_INFO_V_SPACING)
    for row, (label_text, value) in enumerate(build_info_rows()):
        lbl = QLabel(f"<b>{label_text}</b>")
        val = QLabel(str(value))
        val.setTextFormat(Qt.PlainText)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        val.setWordWrap(True)
        system_grid.addWidget(lbl, row, 0, Qt.AlignTop)
        system_grid.addWidget(val, row, 1, Qt.AlignTop)
    system_grid.setColumnStretch(1, 1)

    system_layout = QVBoxLayout()
    system_layout.addLayout(system_grid)
    copy_row = QHBoxLayout()
    copy_row.addStretch()

    def _copy_diagnostics():
        text = system_diagnostics()
        QApplication.clipboard().setText(text)
        copied = QApplication.clipboard().text() == text
        copy_button.setText("Copied!" if copied else "Copy failed")

    copy_button = QPushButton("Copy for Bug Report")
    copy_button.setObjectName("copy_diagnostics_button")
    copy_button.setToolTip(
        "Copy the system and version details to the clipboard for bug reports"
    )
    copy_button.clicked.connect(_copy_diagnostics)
    copy_row.addWidget(copy_button)
    system_layout.addLayout(copy_row)

    about_layout.addWidget(create_group("System Information:", system_layout))
    about_layout.addStretch()
    tab_widget.addTab(about_tab, "About")

    license_tab = QWidget()
    license_layout = QVBoxLayout(license_tab)

    license_text_edit = QPlainTextEdit()
    license_text_edit.setPlainText(load_license_text())
    license_text_edit.setReadOnly(True)
    license_text_edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
    license_text_edit.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")

    license_layout.addWidget(license_text_edit)
    tab_widget.addTab(license_tab, "License")

    main_layout.addWidget(tab_widget)

    button_box = QDialogButtonBox(QDialogButtonBox.Ok)
    button_box.button(QDialogButtonBox.Ok).setText("Close")
    button_box.accepted.connect(dialog.accept)

    main_layout.addWidget(button_box, alignment=Qt.AlignRight)

    dialog.setLayout(main_layout)
    return dialog


def about_section(parent=None):
    build_about_dialog(parent).exec()


LICENSE_FALLBACK = (
    "MetalSlugFontReborn is distributed under the "
    "GNU General Public License v3.0. The full license text was not "
    "found in this installation."
)


def load_license_text():
    if getattr(sys, "frozen", False):
        candidates = [Path(getattr(sys, "_MEIPASS", ".")) / "LICENSE"]
    else:
        candidates = [PROJECT_ROOT / "LICENSE"]
    for candidate in candidates:
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError:
            continue
    return LICENSE_FALLBACK


def describe_letter_case(chars):
    lower = any(ch.islower() for ch in chars)
    upper = any(ch.isupper() for ch in chars)
    if lower and upper:
        return "Lowercase and Uppercase"
    if upper:
        return "Uppercase"
    return "Lowercase"


def describe_numbers(chars):
    digits = sorted(ch for ch in chars if ch.isdigit())
    if digits == list("0123456789"):
        return "0 to 9"
    return " ".join(digits) if digits else "None"


def build_supported_characters_markdown():
    lines = [
        "# MetalSlugFontReborn Character Support",
        "",
        "Here you can find which characters MetalSlugFontReborn supports.",
    ]
    for font in get_font_ids():
        chars = get_font_charset(font)
        symbols = "".join(
            sorted(ch for ch in chars if not ch.isalnum() and ch not in " \n")
        )
        lines += [
            "",
            f"## Font {font} Support",
            "",
            f"- **Letters:** {describe_letter_case(chars)}",
            f"- **Numbers:** {describe_numbers(chars)}",
            f"- **Symbols:** {symbols or 'None'}",
            f"- **Colors:** {', '.join(get_font_colors(font))}",
        ]
    return "\n".join(lines)


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
        browser.setMarkdown(build_supported_characters_markdown())
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
    def __init__(self, parent=None):
        super().__init__("View Supported Characters", parent)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._on_click)

    def reveal(self):
        self.setText("Some sprites are missing - view supported characters")

    def reset_to_normal(self):
        self.setText("View Supported Characters")

    def _on_click(self):
        self.reset_to_normal()
        open_supported_characters(self.window())
