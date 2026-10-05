import platform
import sys
from os import environ
from pathlib import Path
from time import time
from typing import ClassVar

from PIL import Image as PILImage
from PIL import ImageQt
from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QRectF,
    QSize,
    QStandardPaths,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QGradient,
    QIcon,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QPixmap,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QStyle,
    QStyleFactory,
    QVBoxLayout,
    QWidget,
)

from editor import AdvancedEditorDialog
from image_generation import (
    create_character_image,
    find_unsupported_characters,
    generate_filename,
    generate_image,
    get_font_charset,
    get_font_colors,
    get_font_ids,
    get_font_paths,
    layout_characters,
)
from system_info import readable_size
from ui_common import (
    ViewSupportedButton,
    about_section,
    load_config,
    open_supported_characters,
    resolve_auto_theme,
    save_config,
    set_theme,
    show_theme_setup_dialog,
    theme_list,
    theme_setup_needed,
)

DEFAULT_COMPRESS_LEVEL = 6
PREVIEW_COMPRESS_LEVEL = 0
DISABLE_COMPRESSION = 0

PREVIEW_LABEL_MARGIN = 6

MAIN_LAYOUT_SPACING = 18
MAIN_LAYOUT_MARGIN = 22
TEXT_INPUT_MAX_HEIGHT = 55
FORM_LAYOUT_H_SPACING = 20
GENERATE_BUTTON_MIN_HEIGHT = 42

PREVIEW_MIN_HEIGHT = 140
PREVIEW_TIMER_INTERVAL = 150
PREVIEW_MAX_DIMENSION = 32768
PREVIEW_MAX_PIXELS = 32 * 1024 * 1024
PREVIEW_DIM_OPACITY = 0.55
PREVIEW_PULSE_MSEC = 160

CHAR_COUNT_TIMER_INTERVAL = 150

COMPRESS_SLIDER_MIN = 0
COMPRESS_SLIDER_MAX = 9
COMPRESS_SLIDER_TICK_INTERVAL = 1
COMPRESS_LEVEL_LABEL_WIDTH = 20
COMPRESS_HINTS = (
    (0, "fastest save, largest file"),
    (2, "fast save, larger file"),
    (6, "balanced (recommended)"),
    (8, "slow save, smaller file"),
    (9, "smallest file, slowest save"),
)

TOOLTIP_DURATION = 5000

COLOR_ICON_SIZE = 16
COLOR_ICON_MARGIN = 1

WARNING_LABEL_HEIGHT = 28

ZOOM_MIN = 10
ZOOM_MAX = 100
ZOOM_DEFAULT = 100
ZOOM_SLIDER_WIDTH = 120

THREAD_WAIT_TIMEOUT_MS = 3000
TITLE_STATUS_DURATION_MS = 4000

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def normalize_text(font, text):
    return text.upper() if font == 5 else text


PLATFORM_PLUGIN_DIRS = (
    "PySide6/plugins/platforms",
    "PySide6/Qt/plugins/platforms",
)


def missing_plugin_message(frozen, plugin_base):
    if not frozen:
        return None
    base = Path(plugin_base)
    for layout in PLATFORM_PLUGIN_DIRS:
        platforms = base / layout
        if platforms.is_dir() and any(platforms.iterdir()):
            return None
    checked = "\n".join(f"  {base / layout}" for layout in PLATFORM_PLUGIN_DIRS)
    return (
        "This installation of MetalSlugFontReborn is incomplete.\n"
        "The Qt platform plugin directory is missing or empty. Checked:\n"
        f"{checked}\n"
        "The download or extraction most likely did not finish. "
        "Re-download and extract the full folder, then try again."
    )


def pick_style(os_name, release, available):
    if os_name == "Windows" and release == "11":
        wanted = "windows11"
    elif os_name == "Darwin":
        wanted = "macOS"
    else:
        wanted = "Fusion"

    lookup = {style.lower(): style for style in available}
    return lookup.get(wanted.lower(), "Fusion")


class ChromaWarningLabel(QWidget):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text
        self.offset = 0

        self.warning_font = QFont()
        self.warning_font.setPointSize(10)
        self.warning_font.setItalic(True)
        self.warning_font.setBold(True)

        self._gradient_width = 300
        self._gradient = QLinearGradient(0, 0, self._gradient_width, 0)
        self._gradient.setSpread(QGradient.Spread.RepeatSpread)

        for i in range(11):
            pos = i / 10.0
            hue = int(pos * 359)
            self._gradient.setColorAt(pos, QColor.fromHsv(hue, 255, 255))

        self._pen = QPen(self._gradient, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_chroma)

        self.setMinimumHeight(WARNING_LABEL_HEIGHT)

    def sizeHint(self):
        height = max(WARNING_LABEL_HEIGHT, self.fontMetrics().height() + 8)
        return QSize(super().sizeHint().width(), height)

    def showEvent(self, event):
        self.timer.start(66)
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def _update_chroma(self):
        self.offset = (self.offset + 5) % self._gradient_width
        self.update()

    def paintEvent(self, _: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        painter.setFont(self.warning_font)
        painter.setPen(self._pen)

        painter.translate(self.offset, 0)
        text_rect = self.rect().translated(-self.offset, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.text)

        painter.end()


class ElidedLabel(QLabel):

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setFixedHeight(self.fontMetrics().height() + 2)
        self.setText(text)

    def setText(self, text):
        self._full_text = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        metrics = self.fontMetrics()
        super().setText(
            metrics.elidedText(self._full_text, Qt.ElideRight, max(1, self.width() - 4))
        )


class UnsupportedCharHighlighter(QSyntaxHighlighter):
    def __init__(self, document, font_id=1):
        super().__init__(document)
        self._valid_chars = get_font_charset(font_id)
        self._format = QTextCharFormat()
        self._format.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
        self.update_theme()

    def update_theme(self, palette=None):
        if palette is None:
            palette = QApplication.palette()
        error = palette.color(QPalette.ColorRole.BrightText)
        self._format.setUnderlineColor(error)
        self._format.setBackground(QColor(error.red(), error.green(), error.blue(), 46))
        self.rehighlight()

    def set_font_id(self, font_id):
        self._valid_chars = get_font_charset(font_id)
        self.rehighlight()

    def highlightBlock(self, text):
        for i, char in enumerate(text):
            if char not in self._valid_chars and char.upper() not in self._valid_chars:
                self.setFormat(i, 1, self._format)


class PreviewScrollArea(QScrollArea):
    zoom_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignCenter)
        self._zoom = ZOOM_DEFAULT
        self._panning = False
        self._pan_start = None

    def set_zoom(self, value):
        self.set_zoom_silent(value)
        self.zoom_changed.emit(self._zoom)

    def set_zoom_silent(self, value):
        self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, value))

    def get_zoom(self):
        return self._zoom

    def update_alignment(self):
        widget = self.widget()
        if widget is None:
            return
        vp = self.viewport().size()
        if widget.width() > vp.width() or widget.height() > vp.height():
            self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        else:
            self.setAlignment(Qt.AlignCenter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_alignment()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                return
            self.set_zoom(self._zoom + (10 if delta > 0 else -10))
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._panning = True
            self._pan_start = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start:
            delta = event.position().toPoint() - self._pan_start
            self._pan_start = event.position().toPoint()
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._panning = False
            self._pan_start = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class ImageWorker(QObject):
    finished = Signal(str, int, int, float)
    failed = Signal(str, bool)
    preview_ready = Signal(object)
    preview_failed = Signal(str, bool)

    @Slot(dict)
    def process_preview(self, params):
        font_paths = get_font_paths(params["font"], params["color"])
        try:
            _placements, (width, height) = layout_characters(params["text"], font_paths)
            if (
                max(width, height) > PREVIEW_MAX_DIMENSION
                or width * height > PREVIEW_MAX_PIXELS
            ):
                self.preview_failed.emit(
                    "Preview is too large to display!\n"
                    "The image is perfectly fine, but it exceeds the limits for "
                    "live previews. It will still generate successfully.",
                    False,
                )
                return
            image, _width, _height = generate_image(
                params["text"],
                "preview",
                font_paths,
                None,
                compress_level=PREVIEW_COMPRESS_LEVEL,
                return_image=True,
            )
            self.preview_ready.emit(image)
        except PILImage.DecompressionBombError:
            self.preview_failed.emit("Image is too large to generate!", False)
        except FileNotFoundError as e:
            self.preview_failed.emit(
                f"{e}\n\nPlease remove it to see the preview.", True
            )
        except Exception as e:  # noqa: BLE001
            self.preview_failed.emit(str(e), False)

    @Slot(dict)
    def process(self, params):
        try:
            start = time()
            filename = generate_filename(params["text"])
            font_paths = get_font_paths(params["font"], params["color"])
            compress_lvl = params["compress_level"]

            image_path, width, height = generate_image(
                params["text"],
                filename,
                font_paths,
                params["save_path"],
                compress_level=compress_lvl,
                return_image=False,
                scale=params.get("scale", 1),
            )

            self.finished.emit(image_path, width, height, start)
        except PILImage.DecompressionBombError:
            self.failed.emit(
                "Whoa, that's a massive image!\n\n"
                "The text you entered is so long that the generated image exceeds the system's maximum pixel limit. "
                "Computers have a hard cap on how wide or tall an image can be.\n\n"
                "To fix this, try shortening your text.",
                False,
            )
        except FileNotFoundError as e:
            self.failed.emit(str(e), True)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e), False)


class MainWindow(QMainWindow):
    trigger_generation = Signal(dict)
    trigger_preview = Signal(dict)

    _color_icons: ClassVar[dict[str, QIcon]] = {}

    def __init__(self):
        super().__init__()
        self._title_status = None
        self._generating = False
        self._closed = False
        self._last_skipped = []
        self._theme_actions = {}
        self._theme_follower_connected = False
        self._title_timer = QTimer(self)
        self._title_timer.setSingleShot(True)
        self._title_timer.setInterval(TITLE_STATUS_DURATION_MS)
        self._title_timer.timeout.connect(self._clear_title_status)
        self.setWindowTitle("MetalSlugFontReborn")
        self.setWindowIcon(
            QIcon(str(PROJECT_ROOT / "Assets" / "Icons" / "Raubtier.ico"))
        )
        self.resize(760, 720)
        desktop = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DesktopLocation
        )
        self.default_save_path = Path(desktop) if desktop else Path.home()
        self.save_path = self.default_save_path

        self._create_color_icons()
        self.setup_thread()
        self.setup_ui()
        set_theme()
        saved_theme = load_config("theme")
        if not isinstance(saved_theme, str) or saved_theme not in theme_list:
            saved_theme = None
        self._sync_theme_menu(saved_theme or resolve_auto_theme())
        self.highlighter.update_theme(QApplication.palette())
        self._update_native_chrome()
        if saved_theme is None:
            QApplication.styleHints().colorSchemeChanged.connect(
                self._on_system_theme_changed
            )
            self._theme_follower_connected = True


    def _on_system_theme_changed(self, _scheme):
        saved = load_config("theme")
        if self._closed or (isinstance(saved, str) and saved in theme_list):
            return
        set_theme()
        self._sync_theme_menu(resolve_auto_theme())
        self.highlighter.update_theme(QApplication.palette())
        self._update_native_chrome()

    def _apply_theme(self, name):
        set_theme(name)
        self._sync_theme_menu(name)
        self.highlighter.update_theme(QApplication.palette())
        self._update_native_chrome()

    def _sync_theme_menu(self, active_name):
        for theme, action in self._theme_actions.items():
            action.setChecked(theme == active_name)

    def _update_native_chrome(self):
        if platform.system() != "Windows":
            return
        dark = QApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128
        try:
            import ctypes

            hwnd = int(self.winId())
            value = ctypes.c_int(1 if dark else 0)
            for attribute in (20, 19):
                if (
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
                    )
                    == 0
                ):
                    break
        except (OSError, AttributeError):
            pass

    @classmethod
    def _create_color_icons(cls):
        color_names = sorted(
            {name for font in get_font_ids() for name in get_font_colors(font)}
        )
        for color_name in color_names:
            if color_name in cls._color_icons:
                continue
            palette = cls._sample_color_palette(color_name)
            size = COLOR_ICON_SIZE
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.transparent)

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            margin = COLOR_ICON_MARGIN
            rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
            slice_span = 360 * 16 // len(palette)
            start_angle = 90 * 16
            for rgb in palette:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(*rgb))
                painter.drawPie(rect, start_angle, -slice_span)
                start_angle -= slice_span
            painter.setPen(QPen(QColor(*palette[0]).darker(160), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect)
            painter.end()

            cls._color_icons[color_name] = QIcon(pixmap)

    @staticmethod
    def _sample_color_palette(color_name, max_colors=6):
        for font in get_font_ids():
            if color_name not in get_font_colors(font):
                continue
            try:
                sprite = create_character_image("A", get_font_paths(font, color_name))
                ranked = sorted(
                    sprite.convert("RGBA").getcolors(65536) or [],
                    key=lambda item: -item[0],
                )
                palette = [color[:3] for _count, color in ranked if color[3] > 127]
                if palette:
                    return palette[:max_colors]
            except (OSError, ValueError):
                continue
        return [(128, 128, 128)]

    def setup_thread(self):
        self._thread = QThread()
        self._worker = ImageWorker()
        self._worker.moveToThread(self._thread)

        self._worker.finished.connect(self.on_generation_finished)
        self._worker.failed.connect(self.on_generation_failed)
        self._worker.preview_ready.connect(self._on_preview_ready)
        self._worker.preview_failed.connect(self._on_preview_failed)
        self.trigger_generation.connect(self._worker.process)
        self.trigger_preview.connect(self._worker.process_preview)

        self._thread.start(QThread.Priority.LowPriority)

    def closeEvent(self, event):
        self._closed = True
        if self._theme_follower_connected:
            QApplication.styleHints().colorSchemeChanged.disconnect(
                self._on_system_theme_changed
            )
            self._theme_follower_connected = False
        self._thread.quit()
        if not self._thread.wait(THREAD_WAIT_TIMEOUT_MS):
            self._thread.terminate()
            self._thread.wait(1000)
        super().closeEvent(event)

    def setup_ui(self):
        self._preview_user_zoomed = False
        self._last_preview = None
        self._preview_pending = False
        self._preview_queued = None

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(PREVIEW_TIMER_INTERVAL)
        self.preview_timer.timeout.connect(self.update_preview)

        self.char_count_timer = QTimer(self)
        self.char_count_timer.setSingleShot(True)
        self.char_count_timer.setInterval(CHAR_COUNT_TIMER_INTERVAL)
        self.char_count_timer.timeout.connect(self.update_character_count)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(MAIN_LAYOUT_SPACING)
        main_layout.setContentsMargins(
            MAIN_LAYOUT_MARGIN,
            MAIN_LAYOUT_MARGIN,
            MAIN_LAYOUT_MARGIN,
            MAIN_LAYOUT_MARGIN,
        )

        self._build_text_section(main_layout)
        self._build_preview_section(main_layout)
        self._build_output_section(main_layout)
        self._build_save_row(main_layout)
        self._build_action_row(main_layout)

        self.update_colors()
        self.toggle_compression_options(True)

        self.text_input.textChanged.connect(self.schedule_preview_update)
        self.text_input.textChanged.connect(self.update_generate_button_state)
        self.font_select.currentIndexChanged.connect(self.schedule_preview_update)
        self.font_select.currentIndexChanged.connect(self._on_font_changed)
        self.color_select.currentTextChanged.connect(self.schedule_preview_update)
        self.schedule_preview_update()

        for first, second in (
            (self.text_input, self.font_select),
            (self.font_select, self.color_select),
            (self.color_select, self.supported_btn),
            (self.supported_btn, self.scale_select),
            (self.scale_select, self.compress_option),
            (self.compress_option, self.compress_level_slider),
            (self.compress_level_slider, self.browse_btn),
            (self.browse_btn, self.generate_btn),
            (self.generate_btn, self.advanced_btn),
        ):
            self.setTabOrder(first, second)

        self.create_menubar()

    def _build_text_section(self, main_layout):
        text_group = QGroupBox("Text")
        text_layout = QVBoxLayout(text_group)

        self.text_input = QPlainTextEdit()
        self.text_input.setPlaceholderText("Enter your text here...")
        self.text_input.setMaximumHeight(TEXT_INPUT_MAX_HEIGHT)
        self.text_input.setToolTip(
            "Type the text to render. Press Enter for a new line."
        )
        self.text_input.textChanged.connect(self.schedule_char_count_update)
        text_layout.addWidget(self.text_input)

        self.highlighter = UnsupportedCharHighlighter(
            self.text_input.document(), font_id=1
        )

        self.unsupported_hint = ElidedLabel()
        self.unsupported_hint.setAlignment(Qt.AlignCenter)
        self.unsupported_hint.setStyleSheet(
            "color: palette(bright-text); font-style: italic;"
        )

        self.text_info_layout = QHBoxLayout()
        self.char_count_label = QLabel("Characters: 0")
        self.text_info_layout.addWidget(self.char_count_label)
        self.text_info_layout.addStretch()
        self.text_info_layout.addWidget(self.unsupported_hint, 1)

        self.dimensions_label = QLabel("Resolution: -")
        self.text_info_layout.addWidget(self.dimensions_label)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setToolTip("Clear the text.")
        self.clear_button.clicked.connect(self.text_input.clear)
        self.clear_button.setEnabled(False)
        self.text_info_layout.addWidget(self.clear_button)

        text_layout.addLayout(self.text_info_layout)
        main_layout.addWidget(text_group)

    def _build_preview_section(self, main_layout):
        self.preview_group = preview_group = QGroupBox("Font & Preview")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setSpacing(12)

        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Font:"))
        self.font_select = QComboBox()
        self.font_select.addItems(map(str, get_font_ids()))
        self.font_select.setToolTip(
            "Metal Slug font style. Font 5 supports uppercase letters only."
        )
        self.font_select.currentIndexChanged.connect(self.update_colors)
        self._populate_font_preview_icons()
        picker_row.addWidget(self.font_select)

        picker_row.addWidget(QLabel("Color:"))
        self.color_select = QComboBox()
        self.color_select.setToolTip("Color variant of the selected font.")
        picker_row.addWidget(self.color_select)
        picker_row.addStretch()
        preview_layout.addLayout(picker_row)

        self.font5_warning = ChromaWarningLabel(
            "Font 5 only supports uppercase letters. "
            "Your text will be automatically converted to UPPERCASE."
        )
        self.font5_warning.setVisible(False)
        preview_layout.addWidget(self.font5_warning)

        self.preview_scroll = PreviewScrollArea()
        self.preview_scroll.setMinimumHeight(
            max(PREVIEW_MIN_HEIGHT, self.fontMetrics().height() * 8)
        )
        self.preview_scroll.setToolTip(
            "Live preview. Ctrl + mouse wheel to zoom, drag to pan."
        )
        self.preview_scroll.zoom_changed.connect(self._on_zoom_changed_external)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMargin(PREVIEW_LABEL_MARGIN)
        self.preview_label.setText("Loading preview...")
        self.preview_scroll.setWidget(self.preview_label)

        self.preview_effect = QGraphicsOpacityEffect(self.preview_label)
        self.preview_effect.setOpacity(1.0)
        self.preview_label.setGraphicsEffect(self.preview_effect)

        self.preview_pulse = QPropertyAnimation(self.preview_effect, b"opacity", self)
        self.preview_pulse.setDuration(PREVIEW_PULSE_MSEC)
        self.preview_pulse.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.preview_pulse.setStartValue(PREVIEW_DIM_OPACITY)
        self.preview_pulse.setEndValue(1.0)

        preview_layout.addWidget(self.preview_scroll)

        status_row = QHBoxLayout()
        self.supported_btn = ViewSupportedButton(self)
        self.supported_btn.setToolTip(
            "Shows exactly which characters and symbols the selected font supports."
        )
        status_row.addWidget(self.supported_btn)
        status_row.addStretch()

        status_row.addWidget(QLabel("Zoom:"))
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(ZOOM_MIN, ZOOM_MAX)
        self.zoom_slider.setValue(ZOOM_DEFAULT)
        self.zoom_slider.setFixedWidth(ZOOM_SLIDER_WIDTH)
        self.zoom_slider.setToolTip(
            "Preview zoom. Ctrl + mouse wheel over the preview works too."
        )
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        status_row.addWidget(self.zoom_slider)

        self.zoom_label = QLabel(f"{ZOOM_DEFAULT}%")
        self.zoom_label.setFixedWidth(
            max(40, self.fontMetrics().horizontalAdvance("100%") + 12)
        )
        status_row.addWidget(self.zoom_label)

        self.zoom_fit_btn = QPushButton("Fit")
        self.zoom_fit_btn.setToolTip(
            "Scale the preview so the whole image fits the available space."
        )
        self.zoom_fit_btn.clicked.connect(self.fit_preview)
        status_row.addWidget(self.zoom_fit_btn)

        self.zoom_native_btn = QPushButton("1:1")
        self.zoom_native_btn.setToolTip("Reset the preview to native size (1:1).")
        self.zoom_native_btn.clicked.connect(self._reset_zoom_native)
        status_row.addWidget(self.zoom_native_btn)

        preview_layout.addLayout(status_row)

        main_layout.addWidget(preview_group, 1)

    def _build_output_section(self, main_layout):
        self.output_group = QGroupBox("Output settings")
        self.output_group.setCheckable(True)
        self.output_group.setChecked(False)
        self.output_group.setToolTip(
            "Image size and PNG compression. The defaults are recommended "
            "for most users."
        )
        self.output_group.toggled.connect(self._on_output_group_toggled)

        group_layout = QVBoxLayout(self.output_group)
        self.output_content = QWidget()
        group_layout.addWidget(self.output_content)

        grid = QGridLayout(self.output_content)
        grid.setHorizontalSpacing(FORM_LAYOUT_H_SPACING)

        grid.addWidget(QLabel("Image size:"), 0, 0)
        self.scale_select = QComboBox()
        self.scale_select.addItems(["1x (Native)", "2x", "3x", "4x"])
        self.scale_select.setToolTip(
            "Make the exported image larger. 1x matches the game's native resolution."
        )
        self.scale_select.currentIndexChanged.connect(self._apply_zoom_to_preview)
        grid.addWidget(self.scale_select, 0, 1)

        self.compress_option = QCheckBox("Compress PNG")
        self.compress_option.setChecked(True)
        self.compress_option.setToolTip(
            "Recommended. Shrinks the PNG file size with no visible quality "
            "loss. Turn off to save images faster."
        )
        self.compress_option.toggled.connect(self.toggle_compression_options)
        grid.addWidget(self.compress_option, 1, 0)

        self.level_layout = QHBoxLayout()
        self.level_layout.setSpacing(8)
        self.level_layout.addWidget(QLabel("Amount:"))
        self.compress_level_slider = QSlider(Qt.Horizontal)
        self.compress_level_slider.setRange(COMPRESS_SLIDER_MIN, COMPRESS_SLIDER_MAX)
        self.compress_level_slider.setValue(DEFAULT_COMPRESS_LEVEL)
        self.compress_level_slider.setTickPosition(QSlider.TicksBelow)
        self.compress_level_slider.setTickInterval(COMPRESS_SLIDER_TICK_INTERVAL)
        self.compress_level_slider.setToolTip(
            "Slide left for faster saving and a larger file, right for a "
            "smaller file and slower saving. 6 (balanced) is recommended."
        )
        self.compress_level_slider.valueChanged.connect(
            self.update_compress_level_label
        )

        self.compress_level_label = QLabel(str(DEFAULT_COMPRESS_LEVEL))
        self.compress_level_label.setFixedWidth(
            max(
                COMPRESS_LEVEL_LABEL_WIDTH,
                self.fontMetrics().horizontalAdvance("9") + 8,
            )
        )

        self.compress_hint_label = QLabel()
        self.compress_hint_label.setStyleSheet("font-style: italic;")
        self.update_compress_level_label(DEFAULT_COMPRESS_LEVEL)

        self.level_layout.addWidget(self.compress_level_slider)
        self.level_layout.addWidget(self.compress_level_label)
        self.level_layout.addWidget(self.compress_hint_label)
        self.level_layout.addStretch()

        grid.addLayout(self.level_layout, 1, 1)

        self.output_content.setVisible(False)
        main_layout.addWidget(self.output_group)

    def _build_save_row(self, main_layout):
        save_row = QHBoxLayout()
        self.save_location_label = QLabel("Save location: Desktop (default)")
        self.update_save_location_display()
        save_row.addWidget(self.save_location_label, 1)

        self.browse_btn = QPushButton("Change…")
        self.browse_btn.setToolTip("Choose where generated images are saved.")
        self.browse_btn.clicked.connect(self.select_save_path)
        save_row.addWidget(self.browse_btn)
        main_layout.addLayout(save_row)

    def _build_action_row(self, main_layout):
        self.generate_btn = QPushButton("Generate Image")
        self.generate_btn.setToolTip(
            "Render the text and save it as a PNG to the save location."
        )
        self.generate_btn.setMinimumHeight(GENERATE_BUTTON_MIN_HEIGHT)
        self.generate_btn.clicked.connect(self.generate_image)
        self.generate_btn.setEnabled(False)
        self.generate_btn.setDefault(True)

        self.advanced_btn = QPushButton("Advanced Editor…")
        self.advanced_btn.setToolTip(
            "Fine-tune the image before saving: drag, scale, rotate and "
            "replace individual characters."
        )
        self.advanced_btn.setMinimumHeight(GENERATE_BUTTON_MIN_HEIGHT)
        self.advanced_btn.clicked.connect(self.open_advanced_editor)
        self.advanced_btn.setEnabled(False)

        action_row = QHBoxLayout()
        action_row.addWidget(self.generate_btn, 1)
        action_row.addWidget(self.advanced_btn)
        main_layout.addLayout(action_row)

    def _on_output_group_toggled(self, checked):
        self.output_content.setVisible(checked)

    def _populate_font_preview_icons(self):
        for font_id in get_font_ids():
            colors = get_font_colors(font_id)
            if not colors:
                continue
            try:
                font_paths = get_font_paths(font_id, colors[0])
                pil_img, _, _ = generate_image(
                    "ABC",
                    "thumbnail",
                    font_paths,
                    None,
                    compress_level=0,
                    return_image=True,
                    scale=1,
                )
            except (OSError, ValueError):
                continue
            pil_img.thumbnail((48, 24), PILImage.Resampling.NEAREST)
            qimg = ImageQt.ImageQt(pil_img)
            pixmap = QPixmap.fromImage(qimg)
            self.font_select.setItemIcon(
                self.font_select.findText(str(font_id)), QIcon(pixmap)
            )

    def _on_font_changed(self, _):
        font_id = int(self.font_select.currentText())
        self.highlighter.set_font_id(font_id)
        self._update_unsupported_hint(self.text_input.toPlainText())

    def _on_zoom_changed(self, value):
        self._preview_user_zoomed = True
        self.preview_scroll.set_zoom_silent(value)
        self.zoom_label.setText(f"{value}%")
        self._apply_zoom_to_preview()

    def _on_zoom_changed_external(self, value):
        clamped = max(ZOOM_MIN, min(ZOOM_MAX, value))
        if clamped != self.zoom_slider.value():
            self._preview_user_zoomed = True
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(clamped)
        self.zoom_slider.blockSignals(False)
        self.preview_scroll.set_zoom_silent(clamped)
        self.zoom_label.setText(f"{clamped}%")
        self._apply_zoom_to_preview()

    def _apply_zoom_to_preview(self):
        if self._last_preview is not None:
            self._display_preview_image(*self._last_preview)
        else:
            self.preview_timer.start()

    def _get_preview_zoom_factor(self):
        return self.zoom_slider.value() / 100.0

    def _fit_zoom_factor(self, img_w, img_h):
        vp = self.preview_scroll.viewport().size()
        avail_w, avail_h = vp.width(), vp.height()
        if img_w > avail_w or img_h > avail_h:
            extent = QApplication.style().pixelMetric(QStyle.PM_ScrollBarExtent)
            avail_w = max(50, avail_w - extent)
            avail_h = max(50, avail_h - extent)
        return min(1.0, avail_w / img_w, avail_h / img_h)

    def fit_preview(self):
        self._preview_user_zoomed = False
        if self._last_preview is not None:
            self._display_preview_image(*self._last_preview)
        else:
            self.schedule_preview_update()

    def _reset_zoom_native(self):
        self._preview_user_zoomed = True
        self.zoom_slider.setValue(100)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._preview_user_zoomed:
            self._apply_zoom_to_preview()

    def update_generate_button_state(self):
        has_text = bool(self.text_input.toPlainText().strip()) and not self._generating
        self.generate_btn.setEnabled(has_text)
        self.advanced_btn.setEnabled(has_text)
        self.clear_button.setEnabled(bool(self.text_input.toPlainText()))
        self._update_window_title()

    def _update_window_title(self):
        if self._title_status:
            self.setWindowTitle(f"MetalSlugFontReborn - {self._title_status}")
            return
        char_count = len(self.text_input.toPlainText().strip())
        self.setWindowTitle(f"MetalSlugFontReborn - {char_count} characters")

    def schedule_preview_update(self):
        self.preview_pulse.stop()
        self.preview_effect.setOpacity(PREVIEW_DIM_OPACITY)
        self.preview_timer.start()
        self.supported_btn.reset_to_normal()

    def schedule_char_count_update(self):
        self.char_count_timer.start()

    def _settle_preview_pulse(self):
        if self.preview_effect.opacity() < 1.0:
            self.preview_pulse.setStartValue(self.preview_effect.opacity())
            self.preview_pulse.start()

    def _set_preview_error(self, message):
        self._last_preview = None
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText(message)
        self.dimensions_label.setText("Resolution: -")
        self._settle_preview_pulse()

    def _display_preview_image(self, pil_image, scale):
        self._last_preview = (pil_image, scale)

        out_w = pil_image.width * scale
        out_h = pil_image.height * scale
        self.dimensions_label.setText(f"Resolution: {out_w} x {out_h}")

        zoom_factor = self._get_preview_zoom_factor()
        if not self._preview_user_zoomed:
            zoom_factor = self._fit_zoom_factor(out_w, out_h)
            pct = max(ZOOM_MIN, min(ZOOM_MAX, round(zoom_factor * 100)))
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(pct)
            self.zoom_slider.blockSignals(False)
            self.preview_scroll.set_zoom_silent(pct)
            self.zoom_label.setText(f"{pct}%")

        width = int(out_w * zoom_factor)
        height = int(out_h * zoom_factor)

        if (
            width > PREVIEW_MAX_DIMENSION
            or height > PREVIEW_MAX_DIMENSION
            or width * height > PREVIEW_MAX_PIXELS
        ):
            self._set_preview_error(
                "Preview is too large to display!\n"
                "The image is perfectly fine, but it exceeds the limits for live previews.\n"
                "It will still generate successfully."
            )
            return

        if width != pil_image.width or height != pil_image.height:
            preview_image = pil_image.resize(
                (max(1, width), max(1, height)), PILImage.Resampling.NEAREST
            )
        else:
            preview_image = pil_image

        qimage = ImageQt.ImageQt(preview_image)
        pixmap = QPixmap.fromImage(qimage)
        self.preview_label.setPixmap(pixmap)
        self.preview_label.adjustSize()
        self.preview_scroll.update_alignment()
        self._settle_preview_pulse()

        if pixmap.isNull():
            self._set_preview_error("Preview unavailable")

    def _clean_text(self):
        font = int(self.font_select.currentText())
        text = self.text_input.toPlainText().replace("\r\n", "\n").replace("\r", "\n")
        text = normalize_text(font, text.strip())
        skipped = find_unsupported_characters(text, font)
        if skipped:
            text = "".join(ch for ch in text if ch not in set(skipped))
        return font, text, skipped

    def update_preview(self):
        if not self.font_select.currentText():
            return
        font, text, _skipped = self._clean_text()
        params = {
            "text": text or "METAL SLUG IS PEAK!",
            "font": font,
            "color": self.color_select.currentText(),
        }
        self._request_preview(params)

    def _request_preview(self, params):
        if self._preview_pending:
            self._preview_queued = params
            return
        self._preview_pending = True
        self.trigger_preview.emit(params)

    def _flush_preview_queue(self):
        if not self._preview_pending:
            return False
        queued = self._preview_queued
        self._preview_queued = None
        if queued is None:
            self._preview_pending = False
            return False
        self.trigger_preview.emit(queued)
        return True

    @Slot(object)
    def _on_preview_ready(self, image):
        if self._closed:
            return
        if not self._flush_preview_queue():
            scale = self.scale_select.currentIndex() + 1
            self._display_preview_image(image, scale)

    @Slot(str, bool)
    def _on_preview_failed(self, message, reveal_supported_button):
        if self._closed:
            return
        if not self._flush_preview_queue():
            self._set_preview_error(f"Preview unavailable.\n\nError: {message}")
            if reveal_supported_button:
                self.supported_btn.reveal()

    def update_character_count(self):
        text = self.text_input.toPlainText()
        self.char_count_label.setText(f"Characters: {len(text)}")
        self._update_unsupported_hint(text)
        self._update_window_title()

    def _update_unsupported_hint(self, text):
        valid = get_font_charset(int(self.font_select.currentText()))
        bad = sum(1 for ch in text if ch not in valid and ch.upper() not in valid)
        if bad:
            noun = "character is" if bad == 1 else "characters are"
            self.unsupported_hint.setText(
                f"{bad} {noun} not supported by this font and will be skipped"
            )
        else:
            self.unsupported_hint.setText("")

    def update_save_location_display(self):
        folder_name = self.save_path.name
        display_text = f"Save location: {folder_name}"
        if str(self.save_path).casefold() == str(self.default_save_path).casefold():
            display_text += " (default)"

        self.save_location_label.setText(display_text)
        self.save_location_label.setToolTip(f"Full path: {self.save_path}")
        self.save_location_label.setToolTipDuration(TOOLTIP_DURATION)

    def prompt_save_location(self):
        if self._closed or load_config("skip_location_prompt", fallback=False):
            return
        choose, remember = self._ask_save_location()
        if remember:
            save_config("skip_location_prompt", True)
        if choose:
            self.select_save_path()

    def _ask_save_location(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Welcome to MetalSlugFontReborn!")
        msg_box.setText(
            "Your images will be saved to your Desktop by default.\n\n"
            "Would you like to choose a different folder?"
        )
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setDefaultButton(QMessageBox.No)

        cb = QCheckBox("Don't ask me again")
        msg_box.setCheckBox(cb)

        reply = msg_box.exec()
        return reply == QMessageBox.Yes, cb.isChecked()

    def create_menubar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        file_menu.addAction("Exit").triggered.connect(self.close)

        theme_menu = menubar.addMenu("Themes")
        saved_theme = load_config("theme")
        if not isinstance(saved_theme, str) or saved_theme not in theme_list:
            saved_theme = None
        active_theme = saved_theme or resolve_auto_theme()
        for theme in theme_list:
            action = theme_menu.addAction(f"{theme} Mode")
            action.setCheckable(True)
            action.setChecked(theme == active_theme)
            action.triggered.connect(lambda _, t=theme: self._apply_theme(t))
            self._theme_actions[theme] = action

        help_menu = menubar.addMenu("Help")
        help_menu.addAction("About MetalSlugFontReborn").triggered.connect(
            lambda: about_section(self)
        )
        help_menu.addAction("About Qt").triggered.connect(QApplication.aboutQt)
        help_menu.addSeparator()
        help_menu.addAction("Keyboard Shortcuts").triggered.connect(
            self._show_shortcuts_dialog
        )

    def _show_shortcuts_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Keyboard Shortcuts")
        dialog.setMinimumWidth(420)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title = QLabel("Keyboard Shortcuts")
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 3)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        shortcuts = [
            ("Enter / Return", "Insert a new line in the text area"),
            ("Ctrl + Mouse Wheel", "Zoom in/out on the preview"),
            ("Mouse Drag", "Pan the image in the preview"),
        ]

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        for row, (keys, desc) in enumerate(shortcuts):
            key_label = QLabel(keys)
            key_font = key_label.font()
            key_font.setBold(True)
            key_label.setFont(key_font)
            key_label.setStyleSheet(
                "background-color: rgba(127, 127, 127, 0.15);"
                "border-radius: 4px;"
                "padding: 4px 8px;"
            )
            key_label.setAlignment(Qt.AlignCenter)

            desc_label = QLabel(desc)
            desc_label.setWordWrap(True)

            grid.addWidget(key_label, row, 0)
            grid.addWidget(desc_label, row, 1)

        layout.addLayout(grid)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        note = QLabel(
            "Note: Enter inserts a newline in the text field. "
            'Use the "Generate Image" button to create your image.'
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(link); font-style: italic;")
        layout.addWidget(note)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.accept)
        button_box.button(QDialogButtonBox.Ok).setDefault(True)
        layout.addWidget(button_box)

        dialog.exec()

    def update_colors(self):
        self.color_select.clear()
        if not self.font_select.currentText():
            return
        font = int(self.font_select.currentText())

        self.font5_warning.setVisible(font == 5)
        self._create_color_icons()

        for color_name in get_font_colors(font):
            self.color_select.addItem(self._color_icons[color_name], color_name)

    def toggle_compression_options(self, checked):
        for i in range(self.level_layout.count()):
            widget = self.level_layout.itemAt(i).widget()
            if widget:
                widget.setVisible(checked)

    def update_compress_level_label(self, value):
        self.compress_level_label.setText(str(value))
        for top, hint in COMPRESS_HINTS:
            if value <= top:
                self.compress_hint_label.setText(hint)
                break

    def select_save_path(self):
        if path := QFileDialog.getExistingDirectory(
            self, "Select Save Location", str(self.save_path)
        ):
            self.save_path = Path(path)
            self.update_save_location_display()
            QMessageBox.information(
                self, "Save Location Updated", f"Images will now be saved to:\n{path}"
            )

    def _collect_params(self):
        if not self.font_select.currentText():
            return {}
        font, text, skipped = self._clean_text()

        compress_enabled = self.compress_option.isChecked()
        return {
            "text": text,
            "font": font,
            "color": self.color_select.currentText(),
            "save_path": str(self.save_path),
            "compress_level": (
                self.compress_level_slider.value()
                if compress_enabled
                else DISABLE_COMPRESSION
            ),
            "scale": self.scale_select.currentIndex() + 1,
            "skipped": skipped,
        }

    def _show_not_supported_dialog(self):
        box = QMessageBox(self)
        box.setWindowTitle("Not Supported by This Font")
        box.setText(
            "None of the characters you typed are supported by this font. "
            "Open the supported characters list to see what it can render."
        )
        view_button = box.addButton("View Supported Characters", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is view_button:
            open_supported_characters(self)

    def generate_image(self):
        if self._generating:
            return
        self.prompt_save_location()
        params = self._collect_params()
        self._last_skipped = params.get("skipped", [])
        if not params.get("text", ""):
            if self._last_skipped:
                self._show_not_supported_dialog()
            return

        self._generating = True
        self.generate_btn.setText("Generating...")
        self._title_status = "Generating..."
        self.update_generate_button_state()

        self.trigger_generation.emit(params)

    def open_advanced_editor(self):
        params = self._collect_params()
        if not params.get("text", ""):
            if params.get("skipped"):
                self._show_not_supported_dialog()
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            dialog = AdvancedEditorDialog(
                self, params, get_font_charset(params["font"])
            )
        except FileNotFoundError as e:
            QMessageBox.critical(self, "Missing Asset", str(e))
            self.supported_btn.reveal()
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, "Editor Error", f"The editor could not be opened:\n{e}"
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
        dialog.exec()

    @staticmethod
    def _set_env(key, value):
        if value is not None:
            environ[key] = value
        else:
            environ.pop(key, None)

    @staticmethod
    def _open_externally(path):
        if not path.exists():
            return False
        url = QUrl.fromLocalFile(str(path))
        if platform.system() != "Linux":
            return QDesktopServices.openUrl(url)
        current_ld = environ.get("LD_LIBRARY_PATH")
        MainWindow._set_env("LD_LIBRARY_PATH", environ.get("LD_LIBRARY_PATH_ORIG"))
        try:
            return QDesktopServices.openUrl(url)
        finally:
            MainWindow._set_env("LD_LIBRARY_PATH", current_ld)

    def _clear_title_status(self):
        if self._generating:
            self._title_timer.start()
            return
        self._title_status = None
        self._update_window_title()

    @Slot(str, int, int, float)
    def on_generation_finished(self, image_path, width, height, start_time):
        if self._closed:
            return
        self._generating = False
        self.generate_btn.setText("Generate Image")
        self.update_generate_button_state()
        self.supported_btn.reset_to_normal()
        self._title_status = "Image saved"
        self._update_window_title()
        self._title_timer.start()

        path = Path(image_path)
        try:
            size = readable_size(path.stat().st_size)
            message = (
                "Successfully generated image!\n\n"
                f"Image saved at: {path}\n"
                f"Dimensions: {width} x {height} pixels\n"
                f"File size: {size}\n"
                f"Time taken: {time() - start_time:.3f} seconds"
            )
            if self._last_skipped:
                message += "\n\nSkipped, not supported by this font: " + " ".join(
                    self._last_skipped
                )

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Success")
            msg_box.setText(message)
            msg_box.setIcon(QMessageBox.Information)

            ok_button = msg_box.addButton(QMessageBox.Ok)
            open_button = msg_box.addButton("Open Image", QMessageBox.AcceptRole)
            folder_button = msg_box.addButton("Open Folder", QMessageBox.AcceptRole)
            msg_box.setDefaultButton(ok_button)

            msg_box.exec()

            clicked = msg_box.clickedButton()
            if clicked not in (open_button, folder_button):
                return

            target = path if clicked == open_button else path.parent
            if self._open_externally(target):
                return

            if clicked == folder_button:
                QMessageBox.information(
                    self, "Save Location", f"The image is located at:\n{path}"
                )
                return

            retry = QMessageBox(self)
            retry.setWindowTitle("Could not open image")
            retry.setText(
                f"The system could not display:\n{path}\n\n"
                "Open the folder that contains it instead?"
            )
            retry.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            retry.setDefaultButton(QMessageBox.Yes)
            if retry.exec() == QMessageBox.Yes and not self._open_externally(
                path.parent
            ):
                QMessageBox.information(
                    self, "Save Location", f"The image is located at:\n{path}"
                )

        except OSError as e:
            QMessageBox.critical(
                self, "Error", f"Failed to read generated image metadata:\n{e!s}"
            )

    @Slot(str, bool)
    def on_generation_failed(self, error_msg, reveal_supported_button):
        if self._closed:
            return
        self._generating = False
        self.generate_btn.setText("Generate Image")
        self.update_generate_button_state()
        self._title_status = None
        self._update_window_title()
        QMessageBox.critical(self, "Error", error_msg)
        if reveal_supported_button:
            self.supported_btn.reveal()


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Mitra88.MetalSlugFontReborn"
        )
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        environ.setdefault("QT_IM_MODULE", "compose")
        environ.setdefault("QT_QPA_PLATFORM", "xcb")

    plugin_hint = missing_plugin_message(
        getattr(sys, "frozen", False),
        Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)),
    )
    if plugin_hint:
        print(plugin_hint, file=sys.stderr)
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, plugin_hint, "MetalSlugFontReborn", 0x10
            )
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("MetalSlugFontReborn")
    app.setOrganizationName("MetalSlugFontReborn")
    app.setWindowIcon(QIcon(str(PROJECT_ROOT / "Assets" / "Icons" / "Raubtier.ico")))
    if sys.platform.startswith("linux"):
        app.setDesktopFileName("MetalSlugFontReborn")
    app.setStyle(
        pick_style(platform.system(), platform.release(), QStyleFactory.keys())
    )

    if theme_setup_needed() or environ.get("MSFR_SHOW_THEME_PROMPT") == "1":
        show_theme_setup_dialog()

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
