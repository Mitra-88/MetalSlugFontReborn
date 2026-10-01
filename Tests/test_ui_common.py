from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import ui_common
from image_generation import get_font_ids
from ui_common import (
    Config,
    build_supported_characters_markdown,
    load_license_text,
    resolve_auto_theme,
    set_theme,
)


def test_config_roundtrip_persists_to_disk(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config(path)
    cfg.set("theme", "Dark")
    assert cfg.get("theme") == "Dark"
    assert Config(path).get("theme") == "Dark"


def test_config_returns_fallback_for_missing_keys(tmp_path):
    cfg = Config(tmp_path / "config.toml")
    assert cfg.get("absent", "fallback") == "fallback"


def test_config_survives_corrupt_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("not [valid @ !", encoding="utf-8")
    assert Config(path).get("theme", "Light") == "Light"


def test_config_survives_oversized_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "# padding\n" * (ui_common.MAX_FILE_SIZE_BYTES // 10 + 10),
        encoding="utf-8",
    )
    assert path.stat().st_size > ui_common.MAX_FILE_SIZE_BYTES
    assert Config(path).get("theme", "Dark") == "Dark"


def test_config_missing_file_uses_empty_document(tmp_path):
    assert Config(tmp_path / "absent.toml").get("theme") is None


def test_resolve_auto_theme(qapp):
    assert resolve_auto_theme(Qt.ColorScheme.Dark) == "Dark"
    assert resolve_auto_theme(Qt.ColorScheme.Light) == "Light"
    assert resolve_auto_theme(Qt.ColorScheme.Unknown) == "Light"


def test_set_theme_explicit_choice_persists(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(ui_common, "config", Config(tmp_path / "config.toml"))
    set_theme("Tokyo Night")
    assert ui_common.config.get("theme") == "Tokyo Night"
    set_theme()
    assert ui_common.config.get("theme") == "Tokyo Night"


def test_set_theme_auto_detection_does_not_persist(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(ui_common, "config", Config(tmp_path / "config.toml"))
    set_theme()
    assert ui_common.config.get("theme") is None
    if QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark:
        expected = ui_common.theme_list["Dark"]()
    else:
        expected = ui_common.theme_list["Light"]()
    assert QApplication.palette() == expected


def test_set_theme_ignores_unknown_name(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(ui_common, "config", Config(tmp_path / "config.toml"))
    set_theme("Neon Grid")
    assert ui_common.config.get("theme") is None


def test_markdown_covers_every_font_from_disk():
    markdown = build_supported_characters_markdown()
    for font in get_font_ids():
        assert f"## Font {font} Support" in markdown
    assert "**Colors:** Blue, Gold, Orange" in markdown
    assert "**Numbers:** 1 2 3 4 5 6 7 8 9" in markdown
    assert "**Letters:** Uppercase" in markdown


def test_license_text_comes_from_the_license_file():
    text = load_license_text()
    assert "GNU GENERAL PUBLIC LICENSE" in text


def test_license_text_falls_back_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_common, "PROJECT_ROOT", tmp_path)
    text = load_license_text()
    assert "GNU General Public License v3.0" in text


def test_about_dialog_builds_with_system_info_and_copy(qapp):
    from PySide6.QtWidgets import QLabel, QPushButton, QTabWidget

    from system_info import build_date, msfr_version
    from ui_common import build_about_dialog

    dialog = build_about_dialog()
    try:
        tabs = dialog.findChild(QTabWidget)
        assert tabs.count() == 2

        label_text = " ".join(label.text() for label in dialog.findChildren(QLabel))
        assert msfr_version in label_text
        assert build_date in label_text
        assert "Report an Issue" in label_text

        copy_button = dialog.findChild(QPushButton, "copy_diagnostics_button")
        assert copy_button is not None
        copy_button.click()
        assert "Python:" in qapp.clipboard().text()
    finally:
        dialog.close()


def test_system_diagnostics_lists_every_component():
    from ui_common import system_diagnostics

    text = system_diagnostics()
    for component in (
        "Operating System:",
        "Version:",
        "Build date:",
        "Python:",
        "Qt (PySide6):",
        "Pillow:",
        "PyInstaller:",
    ):
        assert component in text


def test_config_survives_utf8_bom(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes('﻿theme = "Dark"\n'.encode())
    assert Config(path).get("theme", "Light") == "Dark"


def test_set_theme_tolerates_wrong_typed_stored_value(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(ui_common, "config", Config(tmp_path / "config.toml"))
    ui_common.config.set("theme", {"not": "a string"})
    set_theme()
    assert QApplication.palette() is not None


def test_config_normalizes_boolean_values(tmp_path):
    from ui_common import Config

    path = tmp_path / "config.toml"
    path.write_text(
        'skip_location_prompt = "yes"\n'
        'skip_char_replace_confirm = "no"\n'
        'skip_theme_prompt = 1\n'
        'theme = "Dark"\n',
        encoding="utf-8",
    )
    cfg = Config(path)
    assert cfg.get("skip_location_prompt") is True
    assert cfg.get("skip_char_replace_confirm") is False
    assert cfg.get("skip_theme_prompt") is True
    assert cfg.get("theme") == "Dark"
