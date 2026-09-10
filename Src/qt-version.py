import platform
import sys
from os import environ
from pathlib import Path
from string import ascii_letters, ascii_uppercase, digits
from time import time

from PIL import Image as PILImage
from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QGradient, QIcon,
                           QLinearGradient, QPainter, QPaintEvent, QPen,
                           QPixmap, QSyntaxHighlighter, QTextCharFormat)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFrame,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSlider, QStyle,
                               QVBoxLayout, QWidget)

from editor import AdvancedEditorDialog
from image_generation import generate_filename, generate_image, get_font_paths
from qt_utils import (ViewSupportedButton, about_section,
                      load_config, save_config, set_theme)
from utils import readable_size

DEFAULT_COMPRESS_LEVEL = 6
PREVIEW_COMPRESS_LEVEL = 0
DISABLE_COMPRESSION = 0

WINDOW_MIN_WIDTH = 700
WINDOW_MIN_HEIGHT = 680
INITIAL_PROMPT_DELAY = 100

MAIN_LAYOUT_SPACING = 18
MAIN_LAYOUT_MARGIN = 22
TEXT_INPUT_MAX_HEIGHT = 55
FORM_LAYOUT_H_SPACING = 20
GENERATE_BUTTON_MIN_HEIGHT = 42

PREVIEW_MIN_HEIGHT = 140
PREVIEW_TIMER_INTERVAL = 150
PREVIEW_MAX_DIMENSION = 32768

CHAR_COUNT_TIMER_INTERVAL = 150

COMPRESS_SLIDER_MIN = 0
COMPRESS_SLIDER_MAX = 9
COMPRESS_SLIDER_TICK_INTERVAL = 1
COMPRESS_LEVEL_LABEL_WIDTH = 20

TOOLTIP_DURATION = 5000

COLOR_ICON_SIZE = 16
COLOR_ICON_MARGIN = 1

WARNING_LABEL_HEIGHT = 28

ZOOM_MIN = 10
ZOOM_MAX = 100
ZOOM_DEFAULT = 100

THREAD_WAIT_TIMEOUT_MS = 3000

FONT_COLORS = {
    1: ["Blue", "Orange", "Gold"],
    2: ["Blue", "Orange", "Gold"],
    3: ["Blue", "Orange"],
    4: ["Blue", "Orange", "Yellow"],
    5: ["Orange"],
}

COLORS = {
    "Blue": "#2596be",
    "Orange": "#f89000",
    "Gold": "#f99010",
    "Yellow": "#f8f900",
}

ALPHANUMERIC = ascii_letters + digits
FONT_VALID_CHARS = {
    1: frozenset(ALPHANUMERIC + " \n" + ',*{}()^:$=!>-∞<#%.+&?";/~_|¥⛶©♥▲▼◀▶⋆★☞✖'),
    2: frozenset(ALPHANUMERIC + " \n" + ",=︷!-.+&?/♪✖"),
    3: frozenset(ALPHANUMERIC + " \n" + "'{}():,=!>-<.+?\";/_|¥⛶©♥▲▼◀▶✖"),
    4: frozenset(ALPHANUMERIC + " \n" + "'*{}()^:$=!>-<#%.+&?\";/~_¥⛶©♥▲▼◀▶|✖"),
    5: frozenset(ascii_uppercase + digits[1:] + " \n" + "!?"),
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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

        self.setFixedHeight(WARNING_LABEL_HEIGHT)

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


class UnsupportedCharHighlighter(QSyntaxHighlighter):
    def __init__(self, document, font_id=1):
        super().__init__(document)
        self._valid_chars = FONT_VALID_CHARS.get(font_id, set())
        self._format = QTextCharFormat()
        self._format.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
        self._format.setUnderlineColor(QColor(255, 0, 0))
        self._format.setBackground(QColor(255, 0, 0, 40))

    def set_font_id(self, font_id):
        self._valid_chars = FONT_VALID_CHARS.get(font_id, set())
        self.rehighlight()

    def highlightBlock(self, text):
        for i, char in enumerate(text):
            if char not in self._valid_chars:
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
        self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, value))
        self.zoom_changed.emit(self._zoom)

    def get_zoom(self):
        return self._zoom

    def update_alignment(self):
        widget = self.widget()
        if widget is None:
            return
        vp = self.viewport().size()
        if (
            widget.width() > vp.width() or widget.height() > vp.height()
        ):
            self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        else:
            self.setAlignment(Qt.AlignCenter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_alignment()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            step = 10 if delta > 0 else -10
            self.set_zoom(self._zoom + step)
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
    failed = Signal(str)

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
                "To fix this, try shortening your text."
            )
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    trigger_generation = Signal(dict)

    _color_icons: dict[str, QIcon] = {}

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MetalSlugFontReborn")
        self.setWindowIcon(
            QIcon(str(PROJECT_ROOT / "Assets" / "Icons" / "Raubtier.ico"))
        )
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.save_path = Path.home() / "Desktop"

        self._create_color_icons()
        self.setup_thread()
        self.setup_ui()
        set_theme()

        QTimer.singleShot(INITIAL_PROMPT_DELAY, self.prompt_save_location)

    @classmethod
    def _create_color_icons(cls):
        if cls._color_icons:
            return

        for color_name, hex_color in COLORS.items():
            size = COLOR_ICON_SIZE
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.transparent)

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(hex_color))

            margin = COLOR_ICON_MARGIN
            painter.drawEllipse(margin, margin, size - 2 * margin, size - 2 * margin)
            painter.end()

            cls._color_icons[color_name] = QIcon(pixmap)

    def setup_thread(self):
        self._thread = QThread()
        self._worker = ImageWorker()
        self._worker.moveToThread(self._thread)

        self._worker.finished.connect(self.on_generation_finished)
        self._worker.failed.connect(self.on_generation_failed)
        self.trigger_generation.connect(self._worker.process)

        self._thread.start(QThread.Priority.LowPriority)

    def closeEvent(self, event):
        self._thread.quit()
        if not self._thread.wait(THREAD_WAIT_TIMEOUT_MS):
            self._thread.terminate()
            self._thread.wait(1000)
        super().closeEvent(event)

    def setup_ui(self):
        self._preview_user_zoomed = False
        self._last_preview = None

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

        self.text_info_layout = QHBoxLayout()
        self.char_count_label = QLabel("Characters: 0")
        self.text_info_layout.addWidget(self.char_count_label)
        self.text_info_layout.addStretch()

        self.dimensions_label = QLabel("Resolution: -")
        self.text_info_layout.addWidget(self.dimensions_label)

        text_layout.addLayout(self.text_info_layout)
        main_layout.addWidget(text_group)

        preview_group = QGroupBox("Font & Preview")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setSpacing(12)

        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Font:"))
        self.font_select = QComboBox()
        self.font_select.addItems(map(str, sorted(FONT_COLORS)))
        self.font_select.setToolTip(
            "Metal Slug font style. Font 5 supports uppercase only."
        )
        self.font_select.currentIndexChanged.connect(self.update_colors)
        self._populate_font_preview_icons()
        picker_row.addWidget(self.font_select)

        picker_row.addWidget(QLabel("Colour:"))
        self.color_select = QComboBox()
        self.color_select.setToolTip("Colour variant of the selected font.")
        picker_row.addWidget(self.color_select)
        picker_row.addStretch()
        preview_layout.addLayout(picker_row)

        self.font5_warning = ChromaWarningLabel(
            "Font 5 only supports uppercase letters. "
            "Your text will be automatically converted to UPPERCASE."
        )
        self.font5_warning.setVisible(False)
        preview_layout.addWidget(self.font5_warning)

        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel("Zoom:"))
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(ZOOM_MIN, ZOOM_MAX)
        self.zoom_slider.setValue(ZOOM_DEFAULT)
        self.zoom_slider.setTickPosition(QSlider.TicksBelow)
        self.zoom_slider.setTickInterval(10)
        self.zoom_slider.setToolTip("Preview zoom (Ctrl + mouse wheel works too).")
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        zoom_layout.addWidget(self.zoom_slider)
        self.zoom_label = QLabel(f"{ZOOM_DEFAULT}%")
        self.zoom_label.setFixedWidth(40)
        zoom_layout.addWidget(self.zoom_label)
        zoom_layout.addStretch()
        self.zoom_fit_btn = QPushButton("Fit")
        self.zoom_fit_btn.setToolTip(
            "Scale the preview so the whole image fits the available space."
        )
        self.zoom_fit_btn.clicked.connect(self.fit_preview)
        zoom_layout.addWidget(self.zoom_fit_btn)
        preview_layout.addLayout(zoom_layout)

        self.preview_scroll = PreviewScrollArea()
        self.preview_scroll.setMinimumHeight(PREVIEW_MIN_HEIGHT)
        self.preview_scroll.setToolTip(
            "Live preview. Ctrl + mouse wheel to zoom, drag to pan."
        )
        self.preview_scroll.zoom_changed.connect(self._on_zoom_changed_external)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setText("Loading preview...")
        self.preview_scroll.setWidget(self.preview_label)

        preview_layout.addWidget(self.preview_scroll)

        self.supported_btn = ViewSupportedButton(self)
        self.supported_btn.setToolTip(
            "Shows exactly which characters and symbols the selected font supports."
        )
        preview_layout.addWidget(self.supported_btn)

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(PREVIEW_TIMER_INTERVAL)
        self.preview_timer.timeout.connect(self.update_preview)

        self.char_count_timer = QTimer(self)
        self.char_count_timer.setSingleShot(True)
        self.char_count_timer.setInterval(CHAR_COUNT_TIMER_INTERVAL)
        self.char_count_timer.timeout.connect(self.update_character_count)

        main_layout.addWidget(preview_group, 1)

        options_group = QGroupBox("Output")
        options_grid = QGridLayout(options_group)
        options_grid.setHorizontalSpacing(FORM_LAYOUT_H_SPACING)

        options_grid.addWidget(QLabel("Scale:"), 0, 0)
        self.scale_select = QComboBox()
        self.scale_select.addItems(["1x (Native)", "2x", "3x", "4x"])
        self.scale_select.setToolTip("Multiply the output image size.")
        self.scale_select.currentIndexChanged.connect(self.schedule_preview_update)
        options_grid.addWidget(self.scale_select, 0, 1)

        self.advanced_mode_cb = QCheckBox("Advanced Mode (Beta)")
        self.advanced_mode_cb.setToolTip(
            "BETA: generate into a per-character editor where you can "
            "drag, scale, rotate, and replace each character "
            "before exporting. Still experimental"
        )
        self.advanced_mode_cb.toggled.connect(self.toggle_advanced_mode)
        options_grid.addWidget(self.advanced_mode_cb, 0, 2, 1, 2)

        self.compress_option = QCheckBox("Compression")
        self.compress_option.setChecked(True)
        self.compress_option.setToolTip(
            "Make PNG files smaller. Turn off to save images faster."
        )
        self.compress_option.toggled.connect(self.toggle_compression_options)

        self.level_layout = QHBoxLayout()
        self.level_layout.setSpacing(8)
        self.level_layout.addWidget(QLabel("Level:"))
        self.compress_level_slider = QSlider(Qt.Horizontal)
        self.compress_level_slider.setRange(COMPRESS_SLIDER_MIN, COMPRESS_SLIDER_MAX)
        self.compress_level_slider.setValue(DEFAULT_COMPRESS_LEVEL)
        self.compress_level_slider.setTickPosition(QSlider.TicksBelow)
        self.compress_level_slider.setTickInterval(COMPRESS_SLIDER_TICK_INTERVAL)
        self.compress_level_slider.setToolTip(
            "0 = fastest, larger file; 9 = smallest file."
        )
        self.compress_level_slider.valueChanged.connect(
            self.update_compress_level_label
        )

        self.compress_level_label = QLabel(str(DEFAULT_COMPRESS_LEVEL))
        self.compress_level_label.setFixedWidth(COMPRESS_LEVEL_LABEL_WIDTH)

        self.level_layout.addWidget(self.compress_level_slider)
        self.level_layout.addWidget(self.compress_level_label)
        self.level_layout.addStretch()

        compress_row = QHBoxLayout()
        compress_row.addWidget(self.compress_option)
        compress_row.addSpacing(12)
        compress_row.addLayout(self.level_layout, 1)
        options_grid.addLayout(compress_row, 1, 0, 1, 4)

        main_layout.addWidget(options_group)

        save_row = QHBoxLayout()
        self.save_location_label = QLabel("Save location: Desktop (default)")
        self.update_save_location_display()
        save_row.addWidget(self.save_location_label, 1)

        self.browse_btn = QPushButton("Change…")
        self.browse_btn.setToolTip("Choose where generated images are saved.")
        self.browse_btn.clicked.connect(self.select_save_path)
        save_row.addWidget(self.browse_btn)
        main_layout.addLayout(save_row)

        self.generate_btn = QPushButton("Generate Image")
        self.generate_btn.setToolTip(
            "Render the text and save it as a PNG to the save location."
        )
        self.generate_btn.setMinimumHeight(GENERATE_BUTTON_MIN_HEIGHT)
        self.generate_btn.clicked.connect(self.generate_image)
        self.generate_btn.setEnabled(False)
        main_layout.addWidget(self.generate_btn)

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
            (self.color_select, self.zoom_slider),
            (self.zoom_slider, self.supported_btn),
            (self.supported_btn, self.scale_select),
            (self.scale_select, self.advanced_mode_cb),
            (self.advanced_mode_cb, self.compress_option),
            (self.compress_option, self.compress_level_slider),
            (self.compress_level_slider, self.browse_btn),
            (self.browse_btn, self.generate_btn),
        ):
            self.setTabOrder(first, second)

        self.create_menubar()

    def _populate_font_preview_icons(self):
        for font_id in sorted(FONT_COLORS):
            color = FONT_COLORS[font_id][0]
            font_paths = get_font_paths(font_id, color)
            pil_img, _, _ = generate_image(
                "ABC",
                "thumbnail",
                font_paths,
                None,
                compress_level=0,
                return_image=True,
                scale=1,
            )
            pil_img.thumbnail((48, 24), PILImage.Resampling.NEAREST)
            from PIL import ImageQt

            qimg = ImageQt.ImageQt(pil_img)
            pixmap = QPixmap.fromImage(qimg)
            self.font_select.setItemIcon(
                self.font_select.findText(str(font_id)), QIcon(pixmap)
            )

    def _on_font_changed(self, _):
        font_id = int(self.font_select.currentText())
        self.highlighter.set_font_id(font_id)

    def _on_zoom_changed(self, value):
        self._preview_user_zoomed = True
        self.zoom_label.setText(f"{value}%")
        self._apply_zoom_to_preview()

    def _on_zoom_changed_external(self, value):
        self._preview_user_zoomed = True
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(value)
        self.zoom_slider.blockSignals(False)
        self.zoom_label.setText(f"{value}%")
        self._apply_zoom_to_preview()

    def _apply_zoom_to_preview(self):
        self.update_preview()

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._preview_user_zoomed and self._last_preview is not None:
            self.preview_timer.start()

    def update_generate_button_state(self):
        has_text = bool(self.text_input.toPlainText().strip())
        self.generate_btn.setEnabled(has_text)
        self._update_window_title()

    def _update_window_title(self):
        text = self.text_input.toPlainText().strip()
        char_count = len(text)
        self.setWindowTitle(f"MetalSlugFontReborn - {char_count} characters")

    def schedule_preview_update(self):
        self.preview_timer.start()
        self.supported_btn.reset_to_normal()

    def schedule_char_count_update(self):
        self.char_count_timer.start()

    def _set_preview_error(self, message):
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText(message)
        self.dimensions_label.setText("Resolution: -")

    def _display_preview_image(self, pil_image, scale):
        self._last_preview = (pil_image, scale)

        out_w = pil_image.width * scale
        out_h = pil_image.height * scale
        self.dimensions_label.setText(f"Resolution: {out_w} x {out_h}")

        zoom_factor = self._get_preview_zoom_factor()
        if not self._preview_user_zoomed:
            zoom_factor = self._fit_zoom_factor(out_w, out_h)
            pct = max(1, int(round(zoom_factor * 100)))
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(max(ZOOM_MIN, min(ZOOM_MAX, pct)))
            self.zoom_slider.blockSignals(False)
            self.zoom_label.setText(f"{pct}%")

        width = int(out_w * zoom_factor)
        height = int(out_h * zoom_factor)

        if width > PREVIEW_MAX_DIMENSION or height > PREVIEW_MAX_DIMENSION:
            self._set_preview_error(
                "Preview is too large to display!\n"
                "The image is perfectly fine, but it exceeds the 32,000 pixel limit for live previews.\n"
                "It will still generate successfully."
            )
            return

        preview_image = pil_image.copy()

        if width != pil_image.width or height != pil_image.height:
            preview_image = preview_image.resize(
                (max(1, width), max(1, height)), PILImage.Resampling.NEAREST
            )

        from PIL import ImageQt

        qimage = ImageQt.ImageQt(preview_image)
        pixmap = QPixmap.fromImage(qimage)
        self.preview_label.setPixmap(pixmap)
        self.preview_label.adjustSize()
        self.preview_scroll.update_alignment()

        if pixmap.isNull():
            self._set_preview_error("Preview unavailable")

    def update_preview(self):
        font = int(self.font_select.currentText())
        color = self.color_select.currentText()
        text = self.text_input.toPlainText().strip() or "METAL SLUG IS PEAK!"

        if font == 5:
            text = text.upper()

        try:
            font_paths = get_font_paths(font, color)
            pil_image, _, _ = generate_image(
                text,
                "preview",
                font_paths,
                None,
                compress_level=PREVIEW_COMPRESS_LEVEL,
                return_image=True,
            )

            if pil_image is None:
                self._set_preview_error("Preview unavailable")
                return

            scale = self.scale_select.currentIndex() + 1
            self._display_preview_image(pil_image, scale)

        except PILImage.DecompressionBombError:
            self._set_preview_error("Image is too large to generate!")
        except FileNotFoundError as e:
            self._set_preview_error(f"{e}\n\nPlease remove it to see the preview.")
            self.supported_btn.reveal()
        except Exception as e:
            self._set_preview_error(f"Preview unavailable.\n\nError: {str(e)}")
            self.supported_btn.reveal()

    def update_character_count(self):
        text = self.text_input.toPlainText()
        char_count = len(text)
        self.char_count_label.setText(f"Characters: {char_count}")
        self._update_window_title()

    def update_save_location_display(self):
        folder_name = self.save_path.name
        display_text = f"Save location: {folder_name}"
        if self.save_path == Path.home() / "Desktop":
            display_text += " (default)"

        self.save_location_label.setText(display_text)
        self.save_location_label.setToolTip(f"Full path: {self.save_path}")
        self.save_location_label.setToolTipDuration(TOOLTIP_DURATION)

    def prompt_save_location(self):
        if load_config("skip_location_prompt", fallback=False):
            return

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

        if cb.isChecked():
            save_config("skip_location_prompt", True)

        if reply == QMessageBox.Yes:
            self.select_save_path()

    def create_menubar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        file_menu.addAction("Exit").triggered.connect(self.close)

        theme_menu = menubar.addMenu("Themes")
        for theme in ["Light", "Dark", "Tokyo Night"]:
            theme_menu.addAction(f"{theme} Mode").triggered.connect(
                lambda _, t=theme: set_theme(t)
            )

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
        font = int(self.font_select.currentText())

        self.font5_warning.setVisible(font == 5)

        for color_name in FONT_COLORS[font]:
            self.color_select.addItem(self._color_icons[color_name], color_name)

    def toggle_compression_options(self, checked):
        for i in range(self.level_layout.count()):
            widget = self.level_layout.itemAt(i).widget()
            if widget:
                widget.setVisible(checked)

    def toggle_advanced_mode(self, checked):
        self.generate_btn.setText("Generate & Edit" if checked else "Generate Image")

    def update_compress_level_label(self, value):
        self.compress_level_label.setText(str(value))

    def select_save_path(self):
        if path := QFileDialog.getExistingDirectory(
            self, "Select Save Location", str(self.save_path)
        ):
            self.save_path = Path(path)
            self.update_save_location_display()
            QMessageBox.information(
                self, "Save Location Updated", f"Images will now be saved to:\n{path}"
            )

    def generate_image(self):
        text = self.text_input.toPlainText().strip()
        if not text:
            return

        font = int(self.font_select.currentText())
        if font == 5:
            text = text.upper()

        compress_enabled = self.compress_option.isChecked()
        compress_level = (
            self.compress_level_slider.value()
            if compress_enabled
            else DISABLE_COMPRESSION
        )

        params = {
            "text": text,
            "font": font,
            "color": self.color_select.currentText(),
            "save_path": str(self.save_path),
            "compress": compress_enabled,
            "compress_level": compress_level,
            "scale": self.scale_select.currentIndex() + 1,
        }

        if self.advanced_mode_cb.isChecked():
            self.open_advanced_editor(params)
            return

        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("Generating...")
        self.setWindowTitle("MetalSlugFontReborn - Generating...")

        self.trigger_generation.emit(params)

    def open_advanced_editor(self, params):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            dialog = AdvancedEditorDialog(
                self, params, FONT_VALID_CHARS[params["font"]]
            )
        except FileNotFoundError as e:
            QMessageBox.critical(self, "Missing Asset", str(e))
            self.supported_btn.reveal()
            return
        except Exception as e:
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

    @Slot(str, int, int, float)
    def on_generation_finished(self, image_path, width, height, start_time):
        self.generate_btn.setText("Generate Image")
        self.update_generate_button_state()
        self.supported_btn.reset_to_normal()

        path = Path(image_path)
        try:
            size = readable_size(path.stat().st_size)
            message = (
                "Successfully generated image!\n\n"
                "Image saved at: {}\n"
                "Dimensions: {} x {} pixels\n"
                "File size: {}\n"
                "Time taken: {:.3f} seconds"
            ).format(path, width, height, size, time() - start_time)

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Success")
            msg_box.setText(message)
            msg_box.setIcon(QMessageBox.Information)

            ok_button = msg_box.addButton(QMessageBox.Ok)
            open_button = msg_box.addButton("Open Image", QMessageBox.AcceptRole)
            msg_box.setDefaultButton(ok_button)

            msg_box.exec()

            if msg_box.clickedButton() != open_button:
                return

            url = QUrl.fromLocalFile(str(path))

            if platform.system() == "Linux":
                current_ld = environ.get("LD_LIBRARY_PATH")
                MainWindow._set_env(
                    "LD_LIBRARY_PATH", environ.get("LD_LIBRARY_PATH_ORIG")
                )
                try:
                    QDesktopServices.openUrl(url)
                finally:
                    MainWindow._set_env("LD_LIBRARY_PATH", current_ld)
            else:
                QDesktopServices.openUrl(url)

        except OSError as e:
            QMessageBox.critical(
                self, "Error", f"Failed to read generated image metadata:\n{str(e)}"
            )

    @Slot(str)
    def on_generation_failed(self, error_msg):
        self.generate_btn.setText("Generate Image")
        self.update_generate_button_state()
        QMessageBox.critical(self, "Error", error_msg)
        self.supported_btn.reveal()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    os_name = platform.system()
    release = platform.release()
    if os_name == "Windows" and release == "11":
        app.setStyle("FluentWinUI3")
    elif os_name == "Windows" and release == "10":
        app.setStyle("Fusion")
    elif os_name == "Linux":
        app.setStyle("Fusion")
    elif os_name == "Darwin":
        app.setStyle("macOS")
    else:
        app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
