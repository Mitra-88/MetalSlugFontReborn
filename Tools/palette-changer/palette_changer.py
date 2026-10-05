import colorsys
import platform
import sys
from pathlib import Path

from color_variants import (
    adjust_color,
    collect_palette,
    export_recolored,
    hue_shift,
    list_png_files,
    resolve_output_dir,
)
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
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
        icon_path = Path(__file__).resolve().parents[2] / "Assets" / "Icons" / "Raubtier.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._files = []
        self._palette = []
        self._mappings = {}
        self._swatch_buttons = {}
        self._selected_rgb = None
        self._selected_button = None
        self._base_hue = None
        self._base_color = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        root.setSpacing(SPACING)

        input_group = QGroupBox("1. Choose the sprites to recolor")
        input_layout = QVBoxLayout(input_group)
        input_row = QHBoxLayout()
        self.input_entry = QLineEdit()
        self.input_entry.setPlaceholderText(
            "Folder with .png sprites, subfolders included"
        )
        self.input_entry.returnPressed.connect(self._load_palette)
        browse_input = QPushButton("Browse...")
        browse_input.setToolTip("Pick the folder that holds the sprites")
        browse_input.clicked.connect(self._browse_input)
        self.load_button = QPushButton("Load Palette")
        self.load_button.setToolTip("Detect the colors these sprites use")
        self.load_button.clicked.connect(self._load_palette)
        input_row.addWidget(self.input_entry, 1)
        input_row.addWidget(browse_input)
        input_row.addWidget(self.load_button)
        input_layout.addLayout(input_row)

        self.palette_label = QLabel("Load a folder to see its palette.")
        input_layout.addWidget(self.palette_label)
        root.addWidget(input_group)

        palette_group = QGroupBox("2. Detected palette")
        palette_layout = QVBoxLayout(palette_group)
        self.swatch_scroll = QScrollArea()
        self.swatch_scroll.setWidgetResizable(True)
        self.swatch_scroll.setStyleSheet("QScrollArea { border: none; }")
        self.swatch_container = QWidget()
        self.swatch_grid = QGridLayout(self.swatch_container)
        self.swatch_grid.setSpacing(6)
        self.swatch_scroll.setWidget(self.swatch_container)
        self.swatch_scroll.setMinimumHeight(96)
        palette_layout.addWidget(self.swatch_scroll, 1)

        hue_row = QHBoxLayout()
        hue_label = QLabel("Hue shift")
        hue_row.addWidget(hue_label)
        self.hue_slider = QSlider(Qt.Horizontal)
        self.hue_slider.setRange(0, 360)
        self.hue_slider.setValue(0)
        self.hue_slider.setToolTip(
            "Rotate every detected color around the color wheel. "
            "0 leaves the palette unchanged."
        )
        self.hue_slider.valueChanged.connect(self._on_hue_changed)
        hue_row.addWidget(self.hue_slider, 1)
        self.hue_preview = QLabel()
        self.hue_preview.setFixedSize(22, 22)
        self.hue_preview.setToolTip("The color family the palette is shifted to")
        hue_row.addWidget(self.hue_preview)
        self.hue_value_label = QLabel("0°")
        hue_row.addWidget(self.hue_value_label)
        palette_layout.addLayout(hue_row)
        root.addWidget(palette_group, 1)
        self._tuning_widgets = [
            self.hue_slider,
            self.hue_preview,
            self.hue_value_label,
        ]

        adjust_group = QGroupBox("3. Fine tuning (optional)")
        self.adjustment_sliders = {}
        self.adjustment_labels = {}
        adjust_grid = QGridLayout(adjust_group)
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
        reset_button.setToolTip("Brightness, saturation and contrast back to 100%")
        reset_button.clicked.connect(self._reset_adjustments)
        adjust_grid.addWidget(reset_button, 0, 3, len(ADJUSTMENTS), 1)
        root.addWidget(adjust_group)
        for slider in self.adjustment_sliders.values():
            self._tuning_widgets.append(slider)
        self._tuning_widgets.append(reset_button)
        self._set_tuning_enabled(False)

        export_group = QGroupBox("4. Export")
        export_layout = QVBoxLayout(export_group)
        output_row = QHBoxLayout()
        self.output_entry = QLineEdit()
        self.output_entry.setPlaceholderText(
            "Name (created next to the input folder) or full path"
        )
        browse_output = QPushButton("Browse...")
        browse_output.setToolTip("Pick where the recolored copies are written")
        browse_output.clicked.connect(self._browse_output)
        output_row.addWidget(self.output_entry, 1)
        output_row.addWidget(browse_output)
        export_layout.addLayout(output_row)

        export_row = QHBoxLayout()
        self.export_button = QPushButton("Export Recolored Copies")
        self.export_button.setEnabled(False)
        self.export_button.setToolTip(
            "Write a recolored copy of every sprite into the output folder"
        )
        self.export_button.clicked.connect(self._export)
        self.output_entry.returnPressed.connect(self._export)
        export_row.addWidget(self.export_button)
        self.status_label = QLabel()
        export_row.addWidget(self.status_label, 1)
        export_layout.addLayout(export_row)
        root.addWidget(export_group)

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

    def _detect_base_color(self):
        for rgb in self._palette:
            hue, sat, val = colorsys.rgb_to_hsv(
                rgb[0] / 255, rgb[1] / 255, rgb[2] / 255
            )
            if sat >= 0.15 and val >= 0.15:
                return round(hue * 360), rgb
        return None, None

    def _update_hue_preview(self, value):
        if self._base_color is not None:
            fill = "#{:02x}{:02x}{:02x}".format(
                *self._rotate_hue(self._base_color, value)
            )
        elif self._base_hue is not None:
            fill = QColor.fromHsv(self._base_hue, 255, 255).name()
        else:
            fill = QColor.fromHsv(value, 255, 255).name()
        self.hue_preview.setStyleSheet(
            f"background-color: {fill};"
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
        self._base_color = None
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
            self._palette = collect_palette(self._files, max_colors=None)
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
        self._base_hue, self._base_color = self._detect_base_color()
        self.hue_slider.blockSignals(True)
        self.hue_slider.setValue(0)
        self.hue_slider.blockSignals(False)
        for rgb in self._palette:
            self._mappings[rgb] = rgb
        self._refresh_previews()
        self._update_hue_preview(0)
        self.export_button.setEnabled(True)
        self._set_tuning_enabled(True)
        label = (
            f"{len(self._files)} sprites, {len(self._palette)} colors detected. "
            "Drag the hue slider to shift every color at once."
        )
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
    if platform.system() == "Windows":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Mitra88.MetalSlugFontReborn.PaletteChanger"
        )
    app = QApplication(sys.argv)
    app.setApplicationName("Palette Changer")
    icon_path = Path(__file__).resolve().parents[2] / "Assets" / "Icons" / "Raubtier.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.resize(660, 660)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
