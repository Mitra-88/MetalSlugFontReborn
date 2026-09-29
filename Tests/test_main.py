from PySide6.QtWidgets import QApplication

from image_generation import get_font_charset, get_font_ids
from main import (
    ImageWorker,
    MainWindow,
    UnsupportedCharHighlighter,
    pick_style,
)


def test_pick_style_selects_native_style_when_available():
    assert (
        pick_style("Windows", "11", ["windows11", "windowsvista", "Fusion"])
        == "windows11"
    )
    assert pick_style("Darwin", "24", ["macOS", "Fusion"]) == "macOS"
    assert pick_style("Linux", "6", ["windows11", "Fusion"]) == "Fusion"
    assert pick_style("Windows", "10", ["windowsvista", "Fusion"]) == "Fusion"
    assert pick_style("Haiku", "1", []) == "Fusion"


def test_pick_style_falls_back_when_native_style_missing():
    assert pick_style("Windows", "11", ["Fusion"]) == "Fusion"
    assert pick_style("Darwin", "24", ["Windows", "Fusion"]) == "Fusion"


def test_pick_style_matches_names_case_insensitively():
    assert pick_style("Darwin", "24", ["MacOS"]) == "MacOS"
    assert pick_style("Windows", "11", ["WINDOWS11"]) == "WINDOWS11"


def test_every_font_supports_multiline_input():
    for font in get_font_ids():
        assert "\n" in get_font_charset(font), f"Font {font} cannot break lines"


def test_main_window_smoke(qapp, tmp_path, monkeypatch):
    import ui_common
    from ui_common import Config

    monkeypatch.setattr("main.load_config", lambda *args, **kwargs: True)
    monkeypatch.setattr(ui_common, "config", Config(tmp_path / "config.toml"))
    monkeypatch.setattr("main.ImageWorker.process", lambda self, params: None)
    window = MainWindow()
    try:
        assert window.save_path == window.default_save_path
        assert window.default_save_path.is_absolute()
        window.save_path = tmp_path / "saves"
        assert window.default_save_path.is_absolute()
        assert not window.generate_btn.isEnabled()
        assert not window.advanced_btn.isEnabled()
        assert window.preview_label.margin() > 0
        assert window.zoom_label.width() >= 40
        window._last_preview = ("stale", 1)
        window._set_preview_error("boom")
        assert window._last_preview is None
        assert all(action.isCheckable() for action in window._theme_actions.values())
        window._apply_theme("Dark")
        assert window._theme_actions["Dark"].isChecked()
        assert window._theme_actions["Light"].isChecked() is False
        window.text_input.setPlainText("Hi")
        window.generate_image()
        assert window._title_status == "Generating..."
        assert "Generating" in window.windowTitle()
        window._clear_title_status()
        assert "Generating" in window.windowTitle()  # run still active
        window._generating = False
        window._clear_title_status()
        assert "2 characters" in window.windowTitle()
    finally:
        window.close()


def test_color_swatch_palette_is_sampled_from_sprites(qapp):
    palettes = {}
    for color in ("Blue", "Orange", "Gold", "Yellow"):
        palette = MainWindow._sample_color_palette(color)
        assert 1 <= len(palette) <= 6
        assert all(len(rgb) == 3 and all(0 <= v <= 255 for v in rgb) for rgb in palette)
        palettes[color] = palette
    assert (32, 32, 32) in palettes["Blue"]
    assert palettes["Blue"] != palettes["Orange"]


def test_highlighter_uses_theme_error_color(qapp):
    from PySide6.QtGui import QPalette, QTextDocument

    document = QTextDocument()
    highlighter = UnsupportedCharHighlighter(document, font_id=1)
    highlighter.update_theme(QApplication.palette())
    expected = QApplication.palette().color(QPalette.ColorRole.BrightText)
    assert highlighter._format.underlineColor() == expected


def test_open_externally_missing_path_returns_false(tmp_path):
    assert MainWindow._open_externally(tmp_path / "gone.png") is False


def test_open_externally_reports_desktop_services_result(qapp, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "main.QDesktopServices.openUrl", lambda url: calls.append(url) or True
    )
    target = tmp_path / "img.png"
    target.write_bytes(b"png")
    assert MainWindow._open_externally(target) is True
    assert len(calls) == 1
    assert calls[0].toLocalFile().replace("\\", "/").endswith("img.png")


def test_open_externally_propagates_failure(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("main.QDesktopServices.openUrl", lambda url: False)
    target = tmp_path / "img.png"
    target.write_bytes(b"png")
    assert MainWindow._open_externally(target) is False


def test_worker_preview_emits_rendered_image(qapp):
    worker = ImageWorker()
    results = []
    worker.preview_ready.connect(results.append)
    worker.process_preview({"text": "Hi", "font": 1, "color": "Blue"})
    assert len(results) == 1
    assert results[0].getbbox() is not None


def test_worker_preview_emits_failure_for_unsupported_character(qapp):
    worker = ImageWorker()
    failures = []
    worker.preview_failed.connect(
        lambda message, reveal: failures.append((message, reveal))
    )
    worker.process_preview({"text": "@", "font": 1, "color": "Blue", "scale": 1})
    assert len(failures) == 1
    message, reveal = failures[0]
    assert "not available" in message
    assert reveal is True


def test_worker_preview_rejects_oversized_text_before_rendering(qapp):
    worker = ImageWorker()
    failures = []
    ready = []
    worker.preview_failed.connect(
        lambda message, reveal: failures.append((message, reveal))
    )
    worker.preview_ready.connect(lambda image, scale: ready.append(image))
    worker.process_preview({"text": "a" * 5000, "font": 1, "color": "Blue", "scale": 1})
    assert ready == []
    assert len(failures) == 1
    message, reveal = failures[0]
    assert "too large" in message
    assert reveal is False


def test_generate_ignores_requests_while_generating(qapp, tmp_path, monkeypatch):
    import ui_common
    from ui_common import Config

    monkeypatch.setattr("main.load_config", lambda *args, **kwargs: True)
    monkeypatch.setattr(ui_common, "config", Config(tmp_path / "config.toml"))
    monkeypatch.setattr("main.ImageWorker.process", lambda self, params: None)
    window = MainWindow()
    try:
        window.save_path = tmp_path / "saves"
        window.text_input.setPlainText("Hi")
        window.generate_image()
        assert window._generating is True
        assert not window.generate_btn.isEnabled()
        assert not window.advanced_btn.isEnabled()
        window.text_input.setPlainText("More")
        window.update_generate_button_state()
        assert not window.generate_btn.isEnabled()
        window.generate_image()
        assert window._title_status == "Generating..."
        window._generating = False
        window.update_generate_button_state()
        assert window.generate_btn.isEnabled()
    finally:
        window.close()


def test_expanding_output_settings_never_overlaps_sections(qapp, tmp_path, monkeypatch):
    import ui_common
    from ui_common import Config

    monkeypatch.setattr("main.load_config", lambda *args, **kwargs: True)
    monkeypatch.setattr(ui_common, "config", Config(tmp_path / "config.toml"))
    window = MainWindow()
    try:
        window.show()
        window.resize(480, 360)
        window.output_group.setChecked(True)
        qapp.processEvents()

        assert window.height() >= window.minimumSizeHint().height() - 1
        assert window.preview_group.rect().contains(window.preview_scroll.geometry()), (
            "preview scroll escapes its group when output settings expand"
        )
        assert (
            window.output_group.geometry().top()
            >= window.preview_group.geometry().bottom()
        ), "output settings overlap the preview section"
        assert (
            window.generate_btn.mapTo(window, window.generate_btn.rect().center()).y()
            < window.height()
        ), "action buttons pushed outside the window"
    finally:
        window.close()


def test_unsupported_hint_stays_single_line_and_elides(qapp, tmp_path, monkeypatch):
    import ui_common
    from ui_common import Config

    monkeypatch.setattr("main.load_config", lambda *args, **kwargs: True)
    monkeypatch.setattr(ui_common, "config", Config(tmp_path / "config.toml"))
    window = MainWindow()
    try:
        window.font_select.setCurrentIndex(0)
        long_text = "é" * 400
        window.text_input.setPlainText(long_text)
        window.update_generate_button_state()
        window._update_unsupported_hint(long_text)
        from PySide6.QtCore import Qt as QtEnum

        assert window.unsupported_hint.alignment() == QtEnum.AlignmentFlag.AlignCenter
        metrics_height = window.fontMetrics().height() + 2
        assert window.unsupported_hint.height() == metrics_height
        assert "not supported by this font" in window.unsupported_hint.toolTip()
        window.resize(900, window.height())
        assert window.unsupported_hint.height() == metrics_height
    finally:
        window.close()


def test_missing_plugin_message_diagnoses_frozen_installs(tmp_path):
    from main import missing_plugin_message

    assert missing_plugin_message(False, tmp_path) is None

    message = missing_plugin_message(True, tmp_path)
    assert message is not None
    assert "incomplete" in message
    assert str(tmp_path) in message

    platforms = tmp_path / "PySide6" / "plugins" / "platforms"
    platforms.mkdir(parents=True)
    (platforms / "qwindows.dll").write_bytes(b"x")
    assert missing_plugin_message(True, tmp_path) is None


def test_missing_plugin_message_accepts_qt_subdir_layout(tmp_path):
    from main import missing_plugin_message

    platforms = tmp_path / "PySide6" / "Qt" / "plugins" / "platforms"
    platforms.mkdir(parents=True)
    (platforms / "libqxcb.so").write_bytes(b"x")
    assert missing_plugin_message(True, tmp_path) is None


def test_linux_graphics_library_hint_lists_missing_packages(monkeypatch):
    import sys

    import main

    monkeypatch.setattr(sys, "platform", "linux")

    class FakeProbe:
        def __init__(self, missing):
            self.missing = set(missing)

        def __call__(self, soname):
            if soname in self.missing:
                raise OSError(soname)

    hint = main.linux_graphics_library_hint(
        probe=FakeProbe(["libxcb-cursor.so.0", "libxcb-xkb.so.1"])
    )
    assert hint is not None
    assert "libxcb-cursor0" in hint
    assert "libxcb-xkb1" in hint
    assert "sudo apt install" in hint
    assert "libxcb-image0" not in hint

    assert main.linux_graphics_library_hint(probe=FakeProbe([])) is None


def test_theme_follows_live_system_change(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt

    import ui_common
    from ui_common import Config

    cfg = Config(tmp_path / "config.toml")
    cfg.set("skip_location_prompt", True)
    monkeypatch.setattr(ui_common, "config", cfg)
    window = MainWindow()  # no saved theme: follows the system

    try:
        window._apply_theme("Dark")
        assert ui_common.load_config("theme") == "Dark"
        QApplication.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
        assert QApplication.palette() == ui_common.dark_mode()

        monkeypatch.setattr(ui_common, "config", Config(tmp_path / "fresh.toml"))
        QApplication.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
        assert QApplication.palette() == ui_common.light_mode()
    finally:
        window.close()


def test_close_without_follower_never_warns(qapp, tmp_path, monkeypatch, capsys):
    import ui_common
    from ui_common import Config

    cfg = Config(tmp_path / "config.toml")
    cfg.set("skip_location_prompt", True)
    cfg.set("theme", "Dark")
    monkeypatch.setattr(ui_common, "config", cfg)
    window = MainWindow()
    window.close()
    assert "Failed to disconnect" not in capsys.readouterr().err


def test_close_with_follower_disconnects_cleanly(qapp, tmp_path, monkeypatch, capsys):
    from PySide6.QtCore import Qt

    import ui_common
    from ui_common import Config

    cfg = Config(tmp_path / "config.toml")
    cfg.set("skip_location_prompt", True)
    monkeypatch.setattr(ui_common, "config", cfg)
    window = MainWindow()
    window.show()
    qapp.processEvents()
    window.close()
    assert "Failed to disconnect" not in capsys.readouterr().err
    QApplication.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    assert QApplication.palette() == ui_common.light_mode()
