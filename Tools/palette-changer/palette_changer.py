import colorsys
import sys
from pathlib import Path

from color_variants import (
    MAX_PALETTE_COLORS,
    NEUTRAL_SATURATION,
    adjust_color,
    collect_palette,
    export_recolored,
    hue_shift,
    list_png_files,
    resolve_output_dir,
)
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

SWATCH_SIZE = 26
SWATCH_COLUMNS = 8
MARGIN = 16
SPACING = 12

ADJUSTMENTS = (
    ("Brightness", "brightness"),
    ("Saturation", "saturation"),
    ("Contrast", "contrast"),
)


def _section_label(text):
    label = QLabel(text)
    label.setStyleSheet("font-weight: bold;")
    return label


def _percent_slider():
    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, 300)
    slider.setValue(100)
    return slider


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Palette Changer")
        self.setMinimumWidth(560)

        self._files = []
        self._palette = []
        self._mappings = {}
        self._swatch_buttons = {}
        self._selected_rgb = None
        self._selected_button = None
        self._base_hue = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        root.setSpacing(SPACING)

        root.addWidget(_section_label("1. Input folder"))
        input_row = QHBoxLayout()
        self.input_entry = QLineEdit()
        self.input_entry.setPlaceholderText(
            "Folder with .png sprites, subfolders included"
        )
        self.input_entry.returnPressed.connect(self._load_palette)
        browse_input = QPushButton("Browse...")
        browse_input.clicked.connect(self._browse_input)
        self.load_button = QPushButton("Load Palette")
        self.load_button.clicked.connect(self._load_palette)
        input_row.addWidget(self.input_entry, 1)
        input_row.addWidget(browse_input)
        input_row.addWidget(self.load_button)
        root.addLayout(input_row)

        self.palette_label = QLabel("Load a folder to see its palette.")
        root.addWidget(self.palette_label)

        root.addWidget(
            _section_label("2. Detected palette: drag the hue to shift every color")
        )
        self.swatch_scroll = QScrollArea()
        self.swatch_scroll.setWidgetResizable(True)
        self.swatch_scroll.setStyleSheet("QScrollArea { border: none; }")
        self.swatch_container = QWidget()
        self.swatch_grid = QGridLayout(self.swatch_container)
        self.swatch_grid.setSpacing(6)
        self.swatch_scroll.setWidget(self.swatch_container)
        self.swatch_scroll.setMinimumHeight(96)
        root.addWidget(self.swatch_scroll, 1)

        hue_row = QHBoxLayout()
        hue_row.addWidget(QLabel("Hue"))
        self.hue_slider = QSlider(Qt.Horizontal)
        self.hue_slider.setRange(0, 360)
        self.hue_slider.setValue(200)
        self.hue_slider.valueChanged.connect(self._on_hue_changed)
        hue_row.addWidget(self.hue_slider, 1)
        self.hue_preview = QLabel()
        self.hue_preview.setFixedSize(22, 22)
        self.hue_preview.setToolTip("Preview of the replacement hue")
        hue_row.addWidget(self.hue_preview)
        self.hue_value_label = QLabel("200°")
        hue_row.addWidget(self.hue_value_label)
        root.addLayout(hue_row)
        self._tuning_widgets = [
            self.hue_slider,
            self.hue_preview,
            self.hue_value_label,
        ]

        root.addWidget(_section_label("3. Adjustments (optional)"))
        self.adjustment_sliders = {}
        self.adjustment_labels = {}
        adjust_grid = QGridLayout()
        adjust_grid.setHorizontalSpacing(SPACING)
        for row, (name, key) in enumerate(ADJUSTMENTS):
            adjust_grid.addWidget(QLabel(name), row, 0)
            slider = _percent_slider()
            slider.valueChanged.connect(
                lambda value, label_key=key: self._update_adjustment_label(label_key)
            )
            self.adjustment_sliders[key] = slider
            adjust_grid.addWidget(slider, row, 1)
            percent = QLabel("100%")
            percent.setFixedWidth(40)
            percent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.adjustment_labels[key] = percent
            adjust_grid.addWidget(percent, row, 2)
        self.adjustment_sliders["brightness"].setValue(100)
        reset_button = QPushButton("Reset")
        reset_button.clicked.connect(self._reset_adjustments)
        adjust_grid.addWidget(reset_button, 0, 3, len(ADJUSTMENTS), 1)
        root.addLayout(adjust_grid)
        for slider in self.adjustment_sliders.values():
            self._tuning_widgets.append(slider)
        self._tuning_widgets.append(reset_button)
        self._set_tuning_enabled(False)

        root.addWidget(_section_label("4. Output folder"))
        output_row = QHBoxLayout()
        self.output_entry = QLineEdit()
        self.output_entry.setPlaceholderText(
            "Name (created next to the input folder) or full path"
        )
        browse_output = QPushButton("Browse...")
        browse_output.clicked.connect(self._browse_output)
        output_row.addWidget(self.output_entry, 1)
        output_row.addWidget(browse_output)
        root.addLayout(output_row)

        export_row = QHBoxLayout()
        self.export_button = QPushButton("Export Recolored Copies")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)
        self.output_entry.returnPressed.connect(self._export)
        export_row.addWidget(self.export_button)
        self.status_label = QLabel()
        export_row.addWidget(self.status_label, 1)
        root.addLayout(export_row)

        self._update_hue_preview(self.hue_slider.value())

    def _on_hue_changed(self, value):
        for rgb in self._mappings:
            self._mappings[rgb] = self._rotate_hue(rgb, value)
        self._refresh_previews()
        self._update_hue_preview(value)

    @staticmethod
    def _rotate_hue(rgb, degrees):
        hue, _sat, _val = colorsys.rgb_to_hsv(
            rgb[0] / 255, rgb[1] / 255, rgb[2] / 255
        )
        return hue_shift(rgb, round((hue * 360 + degrees) % 360))

    def _detect_base_hue(self):
        for rgb in self._palette:
            hue, sat, val = colorsys.rgb_to_hsv(
                rgb[0] / 255, rgb[1] / 255, rgb[2] / 255
            )
            if sat >= 0.15 and val >= 0.15:
                return round(hue * 360)
        return None

    def _update_hue_preview(self, value):
        if self._base_hue is None:
            hue = value
        else:
            hue = (self._base_hue + value) % 360
        self.hue_preview.setStyleSheet(
            f"background-color: {QColor.fromHsv(hue, 255, 255).name()};"
            f"border: 1px solid rgba(0, 0, 0, 60); border-radius: 4px;"
        )
        self.hue_value_label.setText(f"{value}°")

    def _update_adjustment_label(self, key):
        self.adjustment_labels[key].setText(f"{self.adjustment_sliders[key].value()}%")
        self._refresh_previews()

    def _reset_adjustments(self):
        for slider in self.adjustment_sliders.values():
            slider.setValue(100)

    def _browse_input(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose the input folder")
        if folder:
            self.input_entry.setText(folder)
            self._load_palette()

    def _browse_output(self):
        output_dir = resolve_output_dir(
            self.output_entry.text(), self.input_entry.text().strip()
        )
        if output_dir is None:
            output_dir = self.input_entry.text().strip()
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the output folder", str(output_dir)
        )
        if folder:
            self.output_entry.setText(folder)

    def _reset_palette_state(self):
        self._files = []
        self._palette = []
        self._mappings = {}
        self._selected_rgb = None
        self._selected_button = None
        self._swatch_buttons = {}
        while self.swatch_grid.count():
            item = self.swatch_grid.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()
        self.export_button.setEnabled(False)
        self._base_hue = None
        self._set_tuning_enabled(False)

    def _set_tuning_enabled(self, enabled):
        for widget in self._tuning_widgets:
            widget.setEnabled(enabled)

    def _load_palette(self):
        folder = self.input_entry.text().strip()
        if not folder:
            QMessageBox.information(
                self, "Input Folder", "Choose or write the input folder first."
            )
            return
        try:
            self._files = list_png_files(folder)
            if not self._files:
                self._reset_palette_state()
                QMessageBox.warning(
                    self,
                    "No Sprites",
                    f"No .png sprites found (subfolders are scanned too):\n{folder}",
                )
                return
            self._palette = collect_palette(self._files)
        except (OSError, ValueError, Image.DecompressionBombError) as e:
            self._reset_palette_state()
            QMessageBox.critical(
                self, "Palette Changer", f"Could not read the sprites:\n{e}"
            )
            return
        self._mappings = {}
        self._selected_rgb = None
        self._selected_button = None
        self._rebuild_swatches()
        self._base_hue = self._detect_base_hue()
        self.hue_slider.blockSignals(True)
        self.hue_slider.setValue(0)
        self.hue_slider.blockSignals(False)
        for rgb in self._palette:
            self._mappings[rgb] = rgb
        self._refresh_previews()
        self.export_button.setEnabled(True)
        self._set_tuning_enabled(True)
        label = (
            f"{len(self._files)} sprites, {len(self._palette)} colors. "
            "Click a swatch to select it, click it again to change its hue."
        )
        if len(self._palette) >= MAX_PALETTE_COLORS:
            label += f" Showing the {MAX_PALETTE_COLORS} most-used colors."
        self.palette_label.setText(label)

    def _rebuild_swatches(self):
        while self.swatch_grid.count():
            item = self.swatch_grid.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()
        self._swatch_buttons = {}
        for index, rgb in enumerate(self._palette):
            button = QPushButton()
            button.setCheckable(True)
            button.setFixedSize(SWATCH_SIZE, SWATCH_SIZE)
            self._style_swatch(button, rgb, rgb)
            button.setToolTip(f"R {rgb[0]}, G {rgb[1]}, B {rgb[2]}")
            button.clicked.connect(
                lambda _=False, rgb=rgb, button=button: self._on_swatch_clicked(
                    rgb, button
                )
            )
            self.swatch_grid.addWidget(
                button, index // SWATCH_COLUMNS, index % SWATCH_COLUMNS
            )
            self._swatch_buttons[rgb] = button
        self._refresh_previews()

    @staticmethod
    def _style_swatch(button, source_rgb, fill_rgb):
        fill = "#{:02x}{:02x}{:02x}".format(*fill_rgb)
        border = "#{:02x}{:02x}{:02x}".format(*source_rgb)
        button.setStyleSheet(
            f"QPushButton {{ background-color: {fill}; border: 1px solid {border}; "
            f"border-radius: 4px; }}"
            f"QPushButton:checked {{ border: 2px solid #555; }}"
        )
        tooltip = f"R {source_rgb[0]}, G {source_rgb[1]}, B {source_rgb[2]}"
        if tuple(fill_rgb) != tuple(source_rgb):
            tooltip += f" -> R {fill_rgb[0]}, G {fill_rgb[1]}, B {fill_rgb[2]}"
        button.setToolTip(tooltip)

    def _refresh_previews(self):
        brightness = self.adjustment_sliders["brightness"].value() / 100
        saturation = self.adjustment_sliders["saturation"].value() / 100
        contrast = self.adjustment_sliders["contrast"].value() / 100
        for rgb, button in self._swatch_buttons.items():
            final = adjust_color(
                self._mappings.get(rgb, rgb), brightness, saturation, contrast
            )
            self._style_swatch(button, rgb, final)

    def _on_swatch_clicked(self, rgb, button=None):
        if self._selected_rgb != rgb:
            if self._selected_button is not None:
                self._selected_button.setChecked(False)
            self._selected_rgb = rgb
            self._selected_button = button
            if button is not None:
                button.setChecked(True)
            return
        self._add_mapping(rgb, button)

    def _add_mapping(self, rgb, button):
        delta = self.hue_slider.value()
        if self._base_hue is not None:
            delta = (self.hue_slider.value() - self._base_hue) % 360
        self._mappings[rgb] = self._rotate_hue(rgb, self.hue_slider.value())
        self._refresh_previews()
        if button is not None:
            button.setChecked(True)

    def _warn_output_is_input(self):
        QMessageBox.warning(
            self,
            "Output Folder",
            "The output folder must differ from the input folder, "
            "or exporting would overwrite the original sprites.",
        )

    def _export(self):
        if not self._files:
            QMessageBox.information(self, "Load First", "Load a palette first.")
            return
        adjustments = {
            key: self.adjustment_sliders[key].value() / 100
            for _name, key in ADJUSTMENTS
        }
        if not self._mappings and all(value == 1.0 for value in adjustments.values()):
            QMessageBox.information(
                self,
                "Nothing to Do",
                "Replace at least one color or move an adjustment off 100%.",
            )
            return
        output_dir = resolve_output_dir(
            self.output_entry.text(), self.input_entry.text().strip()
        )
        if output_dir is None:
            QMessageBox.warning(
                self,
                "Output Folder",
                "Write the output folder (name or full path) first.",
            )
            return
        input_dir = Path(self.input_entry.text().strip())
        try:
            if output_dir.resolve() == input_dir.resolve():
                self._warn_output_is_input()
                return
            saved = export_recolored(
                self._files,
                self._mappings,
                output_dir,
                brightness=adjustments["brightness"],
                saturation=adjustments["saturation"],
                contrast=adjustments["contrast"],
            )
        except (OSError, ValueError, Image.DecompressionBombError) as e:
            QMessageBox.critical(
                self, "Export Failed", f"Could not export the sprites:\n{e}"
            )
            return
        self.status_label.setText(f"Recolored {saved} sprites into {output_dir}.")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Palette Changer")
    window = MainWindow()
    window.resize(660, 660)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
