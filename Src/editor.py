import colorsys
import os
import queue
import threading
from enum import IntEnum
from math import atan2, ceil, cos, degrees, floor, radians, sin
from pathlib import Path
from time import time

from PIL import Image, ImageChops, ImageQt
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QIntValidator,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QShortcut,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from image_generation import (
    create_character_image,
    generate_filename,
    get_font_colors,
    get_font_paths,
    layout_characters,
)
from rotsprite import QUALITY_FAST_ROTSPRITE, QUALITY_ROTSPRITE
from rotsprite import QUALITY_NEAREST as QUALITY_NEAREST_ROTATION
from rotsprite import rotate as rotsprite_rotate
from system_info import readable_size
from ui_common import load_config, open_supported_characters, save_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EDITOR_DEFAULT_WIDTH = 1100
EDITOR_DEFAULT_HEIGHT = 700
CANVAS_SPLIT_PERCENT = 70
PANEL_WIDTH = 330
CANVAS_MIN_WIDTH = 200
SCENE_PADDING = 150

ZOOM_SCALES = (
    1 / 64, 1 / 48, 1 / 32, 1 / 24, 1 / 16, 1 / 12, 1 / 8, 1 / 6, 1 / 5,
    1 / 4, 1 / 3, 1 / 2, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 12.0, 16.0,
    24.0, 32.0, 48.0, 64.0,
)

CHAR_SCALE_MIN = 10
CHAR_SCALE_MAX = 400
CHAR_SCALE_DEFAULT = 100

HUE_NEUTRAL_SATURATION = 0.08
HUE_MIN = -180
HUE_MAX = 180
OPACITY_MIN = 0
OPACITY_MAX = 100
OPACITY_DEFAULT = 100
DUPLICATE_OFFSET = 10

ROTATION_MIN = -180
ROTATION_MAX = 180

LETTER_SPACING_DEFAULT = 0
LETTER_SPACING_MAX = 100
LINE_SPACING_DEFAULT = 15
LINE_SPACING_MAX = 200
SNAP_GRID_DEFAULT = 10
SNAP_GRID_MAX = 100
SNAP_THRESHOLD_PX = 8
SNAP_DISABLED_MODIFIER = (
    Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ControlModifier
)

SCALE_SNAP_TOLERANCE_PCT = 4
ROTATE_SNAP_STEP = 45
GUIDE_POOL_SIZE = 8

NUDGE_STEP = 1
NUDGE_BIG_STEP = 10

SNAP_GUIDE_COLOR = "#ff00ae"
SNAP_SPACING_GUIDE_COLOR = "#ff9500"


CHECKER_PX = 8
CHECKER_MIN_SCREEN_PX = 3
CHECKER_TINT = 0.16

MARQUEE_DASH = (4.0, 3.0)
MARQUEE_ANT_MS = 120
MARQUEE_CLICK_PX = 3
BORDER_TINT = 0.35
PASTEBOARD_TINT = 0.45
GESTURE_UPDATE_MS = 16


def _blend(base, target, amount):
    return QColor(
        round(base.red() * (1 - amount) + target.red() * amount),
        round(base.green() * (1 - amount) + target.green() * amount),
        round(base.blue() * (1 - amount) + target.blue() * amount),
    )
PIX_CACHE_MAX_ENTRIES = 16

HANDLE_PX = 9
HANDLE_ROTATE_RING_PX = 24
TRANSFORM_COLOR = QColor("#39c2ff")
HANDLE_FILL = QColor(255, 255, 255, 235)
HANDLE_BORDER = QColor(30, 30, 30)


class GuideStyle(IntEnum):
    EDGE = 0
    CENTER = 1
    SPACING = 2


class _SnapCandidate:
    __slots__ = ("coord", "delta", "guides")

    def __init__(self, delta, coord, guides):
        self.delta = delta
        self.coord = coord
        self.guides = guides


class SnapEngine:
    def __init__(self):
        self.reset()

    def reset(self):
        self._statics = []
        self._xs = None
        self._ys = None
        self._x_by_left = []
        self._y_by_top = []

    def is_ready(self):
        return self._xs is not None

    def set_statics(self, statics, canvas_w, canvas_h):
        self._statics = sorted(statics, key=lambda kv: kv[0])
        self._canvas_w = float(canvas_w)
        self._canvas_h = float(canvas_h)
        xs_edges, xs_centers, ys_edges, ys_centers = [], [], [], []
        for key, rect in self._statics:
            xs_edges += [(rect.left(), key), (rect.right(), key)]
            ys_edges += [(rect.top(), key), (rect.bottom(), key)]
            xs_centers.append((rect.center().x(), key))
            ys_centers.append((rect.center().y(), key))
        self._xs = (sorted(xs_edges), sorted(xs_centers))
        self._ys = (sorted(ys_edges), sorted(ys_centers))
        self._x_by_left = sorted(self._statics, key=lambda kv: (kv[1].left(), kv[0]))
        self._x_by_right = sorted(self._statics, key=lambda kv: (kv[1].right(), kv[0]))
        self._y_by_top = sorted(self._statics, key=lambda kv: (kv[1].top(), kv[0]))
        self._y_by_bottom = sorted(
            self._statics, key=lambda kv: (kv[1].bottom(), kv[0])
        )

    def find_snap(self, box, threshold, grid):
        dx, guides_x = self._snap_one_axis(box, threshold, grid, True)
        dy, guides_y = self._snap_one_axis(box, threshold, grid, False)
        return dx, dy, guides_x + guides_y

    def _snap_one_axis(self, box, threshold, grid, horizontal):
        tiers = (
            lambda: self._tier_char_edges(box, threshold, horizontal),
            lambda: self._tier_char_centers(box, threshold, horizontal),
            lambda: self._tier_canvas(box, threshold, horizontal),
            lambda: self._tier_spacing(box, threshold, horizontal),
            lambda: self._tier_grid(box, grid, horizontal),
        )
        for tier in tiers:
            candidates = tier()
            if candidates:
                best = min(candidates, key=lambda c: (abs(c.delta), c.coord, c.delta))
                return best.delta, best.guides
        return 0.0, []

    def _moving_edges(self, box, horizontal):
        if horizontal:
            return box.left(), box.right()
        return box.top(), box.bottom()

    def _moving_center(self, box, horizontal):
        return box.center().x() if horizontal else box.center().y()

    def _tier_char_edges(self, box, threshold, horizontal):
        table = self._xs[0] if horizontal else self._ys[0]
        return self._match_edges(
            self._moving_edges(box, horizontal),
            table,
            threshold,
            GuideStyle.EDGE,
            horizontal,
        )

    def _tier_char_centers(self, box, threshold, horizontal):
        table = self._xs[1] if horizontal else self._ys[1]
        return self._match_edges(
            (self._moving_center(box, horizontal),),
            table,
            threshold,
            GuideStyle.CENTER,
            horizontal,
        )

    def _tier_canvas(self, box, threshold, horizontal):
        size = self._canvas_w if horizontal else self._canvas_h
        edge_targets = (
            (0.0, GuideStyle.EDGE),
            (size, GuideStyle.EDGE),
            (size / 2.0, GuideStyle.CENTER),
        )
        center_targets = ((size / 2.0, GuideStyle.CENTER),)
        out = []
        for edge in self._moving_edges(box, horizontal):
            for coord, style in edge_targets:
                delta = coord - edge
                if abs(delta) <= threshold:
                    out.append(
                        _SnapCandidate(delta, coord, [(horizontal, coord, style)])
                    )
        center = self._moving_center(box, horizontal)
        for coord, style in center_targets:
            delta = coord - center
            if abs(delta) <= threshold:
                out.append(_SnapCandidate(delta, coord, [(horizontal, coord, style)]))
        return out

    def _match_edges(self, moving, table, threshold, style, horizontal):
        out = []
        for edge in moving:
            for coord, key in table:
                delta = coord - edge
                if abs(delta) <= threshold:
                    out.append(
                        _SnapCandidate(delta, coord, [(horizontal, coord, style)])
                    )
        return out

    def _tier_spacing(self, box, threshold, horizontal):
        if horizontal:
            first, span = box.left(), box.width()
            perp_lo, perp_hi = box.top(), box.bottom()
            left_edge_of = lambda r: r.right()
            right_edge_of = lambda r: r.left()
            before, after = self._x_by_right, self._x_by_left
        else:
            first, span = box.top(), box.height()
            perp_lo, perp_hi = box.left(), box.right()
            left_edge_of = lambda r: r.bottom()
            right_edge_of = lambda r: r.top()
            before, after = self._y_by_bottom, self._y_by_top

        near_left = self._nearest_before(
            before,
            left_edge_of,
            first + threshold,
            perp_lo,
            perp_hi,
            threshold,
            horizontal,
        )
        near_right = self._nearest_after(
            after,
            right_edge_of,
            first + span - threshold,
            perp_lo,
            perp_hi,
            threshold,
            horizontal,
        )
        if near_left is None or near_right is None:
            return []

        bound_a = left_edge_of(near_left[1])
        bound_b = right_edge_of(near_right[1])
        gap = (bound_b - bound_a - span) / 2.0
        if gap < 0:
            return []
        target = bound_a + gap
        delta = target - first
        if abs(delta) > threshold:
            return []
        return [
            _SnapCandidate(
                delta,
                target,
                [
                    (horizontal, bound_a, GuideStyle.SPACING),
                    (horizontal, bound_b, GuideStyle.SPACING),
                ],
            )
        ]

    def _nearest_before(
        self, ordered, edge_of, limit, perp_lo, perp_hi, threshold, horizontal
    ):
        best = None
        for key, rect in ordered:
            value = edge_of(rect)
            if value > limit:
                break
            if self._perpendicular_close(rect, perp_lo, perp_hi, threshold, horizontal):
                best = (key, rect)
        return best

    def _nearest_after(
        self, ordered, edge_of, limit, perp_lo, perp_hi, threshold, horizontal
    ):
        for key, rect in ordered:
            if edge_of(rect) < limit:
                continue
            if self._perpendicular_close(rect, perp_lo, perp_hi, threshold, horizontal):
                return (key, rect)
        return None

    @staticmethod
    def _perpendicular_close(rect, perp_lo, perp_hi, threshold, horizontal):
        if horizontal:
            rect_lo, rect_hi = rect.top(), rect.bottom()
        else:
            rect_lo, rect_hi = rect.left(), rect.right()
        return rect_lo <= perp_hi + threshold and rect_hi >= perp_lo - threshold

    def _tier_grid(self, box, grid, horizontal):
        if grid <= 0:
            return []
        best = None
        for edge in self._moving_edges(box, horizontal):
            snapped = round(edge / grid) * grid
            delta = snapped - edge
            if delta == 0:
                continue
            if best is None or abs(delta) < abs(best.delta):
                best = _SnapCandidate(delta, snapped, [])
        return [best] if best is not None else []


BASELINES = ["Bottom", "Center", "Top"]
ALIGNMENTS = ["Left", "Center", "Right"]
UNDO_MAX_STEPS = 30


def shift_sprite_hue(sprite, degrees):
    if not degrees % 360:
        return sprite
    mapping = {}
    for _count, color in sprite.getcolors(1 << 20) or []:
        rgb = color[:3]
        hue, sat, val = colorsys.rgb_to_hsv(
            rgb[0] / 255, rgb[1] / 255, rgb[2] / 255
        )
        if sat < HUE_NEUTRAL_SATURATION:
            continue
        r, g, b = colorsys.hsv_to_rgb((hue + degrees / 360.0) % 1.0, sat, val)
        mapping[rgb] = (round(r * 255), round(g * 255), round(b * 255))
    if not mapping:
        return sprite
    channels = list(sprite.split())
    jobs = []
    for old_rgb, new_rgb in mapping.items():
        masks = []
        for band, component in zip(channels[:3], old_rgb):
            lut = [0] * 256
            lut[component] = 255
            masks.append(band.point(lut))
        mask = masks[0]
        for extra in masks[1:]:
            mask = ImageChops.multiply(mask, extra)
        jobs.append((mask, new_rgb))
    for mask, new_rgb in jobs:
        for band, component in zip(channels[:3], new_rgb):
            band.paste(Image.new("L", sprite.size, component), mask=mask)
    return Image.merge("RGBA", channels)


def render_character(
    sprite,
    scale_pct=CHAR_SCALE_DEFAULT,
    rotation=0,
    quality=QUALITY_FAST_ROTSPRITE,
    stretch_x=CHAR_SCALE_DEFAULT,
    stretch_y=CHAR_SCALE_DEFAULT,
    flip_h=False,
    flip_v=False,
    opacity=OPACITY_DEFAULT,
    fast_rotate=False,
):
    img = sprite
    factor_x = scale_pct * stretch_x / 10000.0
    factor_y = scale_pct * stretch_y / 10000.0
    size = (max(1, int(img.width * factor_x)), max(1, int(img.height * factor_y)))
    if size != img.size:
        img = img.resize(size, Image.Resampling.NEAREST)
    if flip_h:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if flip_v:
        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    if opacity != OPACITY_DEFAULT:
        alpha = img.getchannel("A").point(lambda value: value * opacity // 100)
        img = Image.merge("RGBA", (*img.split()[:3], alpha))
    if rotation:
        if rotation % 90 == 0 or fast_rotate:
            img = img.rotate(-rotation, expand=True)
        else:
            img = rotsprite_rotate(img, rotation, quality)
    return img


def unrotated_render_size(sprite, scale_pct, stretch_x, stretch_y):
    return (
        max(1, int(sprite.width * scale_pct * stretch_x / 10000.0)),
        max(1, int(sprite.height * scale_pct * stretch_y / 10000.0)),
    )


def render_job(sprite, key, quality):
    try:
        if key[7] % 360:
            sprite = shift_sprite_hue(sprite, key[7])
        return render_character(
            sprite,
            key[0],
            key[1],
            quality,
            key[2],
            key[3],
            key[4],
            key[5],
            opacity=key[6],
        )
    except Exception:  # noqa: BLE001
        return None


class RenderDispatcher(QObject):
    render_ready = Signal(object, object, object, object)

    def __init__(self, parent):
        super().__init__(parent)
        self.render_ready.connect(self._on_rendered)
        self._jobs = queue.Queue()
        self._thread = threading.Thread(target=self._work, daemon=True)
        self._thread.start()

    def request(self, item, key):
        self._jobs.put((item, item.sprite, key, item.rotation_quality))

    def _work(self):
        while True:
            job = self._jobs.get()
            if job is None:
                return
            jobs = {id(job[0]): job}
            while True:
                try:
                    job = self._jobs.get_nowait()
                except queue.Empty:
                    break
                if job is None:
                    return
                jobs[id(job[0])] = job
            for item, sprite, key, quality in jobs.values():
                rendered = render_job(sprite, key, quality)
                if rendered is None:
                    continue
                try:
                    self.render_ready.emit(item, sprite, key, rendered)
                except RuntimeError:
                    return

    def _on_rendered(self, item, sprite, key, rendered):
        try:
            item.apply_rendered(sprite, key, rendered)
        except RuntimeError:
            pass

    def shutdown(self):
        self._jobs.put(None)
        self._thread.join(timeout=0.5)


class CharItem(QGraphicsPixmapItem):
    def __init__(
        self,
        char,
        sprite,
        base_x,
        base_y,
        sprite_provider,
        dispatcher=None,
        color_variant=None,
    ):
        super().__init__()
        self.char = char
        self.color_variant = color_variant
        self.sprite = sprite.convert("RGBA")
        self._sprite_provider = sprite_provider
        self._dispatcher = dispatcher
        self.layout_anchored = True
        self.base_x = base_x
        self.base_y = base_y
        self.dx = 0
        self.dy = 0
        self.scale_pct = CHAR_SCALE_DEFAULT
        self.rotation = 0
        self.stretch_x = CHAR_SCALE_DEFAULT
        self.stretch_y = CHAR_SCALE_DEFAULT
        self.flip_h = False
        self.flip_v = False
        self.opacity = OPACITY_DEFAULT
        self.hue_shift = 0
        self._pix_cache = {}
        self._hue_cache = {}
        self._pending_center = None
        self.rotation_quality = QUALITY_FAST_ROTSPRITE
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)

    def capture_state(self):
        return (
            self.dx,
            self.dy,
            self.scale_pct,
            self.rotation,
            self.base_x,
            self.base_y,
            self.isVisible(),
            self.char,
            self.stretch_x,
            self.stretch_y,
            self.flip_h,
            self.flip_v,
            self.opacity,
            self.hue_shift,
            self.zValue(),
            self.color_variant,
        )

    def apply_state(self, state):
        scene = self.scene()
        if scene is not None:
            scene.invalidate_bounds()
        self._pending_center = None
        (
            self.dx,
            self.dy,
            self.scale_pct,
            self.rotation,
            self.base_x,
            self.base_y,
            visible,
            char,
            self.stretch_x,
            self.stretch_y,
            self.flip_h,
            self.flip_v,
            self.opacity,
            self.hue_shift,
            z_value,
            color_variant,
        ) = state
        if char != self.char or color_variant != self.color_variant:
            self.color_variant = color_variant
            self.set_character(char)
        self.setZValue(z_value)
        self.setVisible(visible)
        self.update_pixmap()

    def set_character(self, char):
        self.char = char
        self.sprite = self._sprite_provider(char, self.color_variant).convert(
            "RGBA"
        )
        self._pix_cache.clear()
        self._hue_cache.clear()

    def tinted_sprite(self, compute=False):
        if not self.hue_shift % 360:
            return self.sprite
        cached = self._hue_cache.get(self.hue_shift)
        if cached is None and compute:
            cached = shift_sprite_hue(self.sprite, self.hue_shift)
            if len(self._hue_cache) >= 8:
                self._hue_cache.clear()
            self._hue_cache[self.hue_shift] = cached
        return cached if cached is not None else self.sprite

    def _cache_key(self):
        return (
            self.scale_pct,
            self.rotation,
            self.stretch_x,
            self.stretch_y,
            self.flip_h,
            self.flip_v,
            self.opacity,
            self.hue_shift,
        )

    def prune_cache(self):
        key = self._cache_key()
        rendered = self._pix_cache.get(key)
        self._pix_cache.clear()
        if rendered is not None:
            self._pix_cache[key] = rendered

    def update_pixmap(self):
        key = self._cache_key()
        rendered = self._pix_cache.get(key)
        if rendered is None:
            hue_pending = bool(self.hue_shift % 360) and (
                self.hue_shift not in self._hue_cache
            )
            if self._dispatcher is not None and (self.rotation % 90 or hue_pending):
                self.setPixmap(
                    QPixmap.fromImage(
                        ImageQt.ImageQt(
                            render_character(
                                self.tinted_sprite(),
                                key[0],
                                key[1],
                                self.rotation_quality,
                                key[2],
                                key[3],
                                key[4],
                                key[5],
                                opacity=key[6],
                                fast_rotate=True,
                            )
                        )
                    )
                )
                self._after_pixmap_change()
                self._dispatcher.request(self, key)
                return
            rendered = render_character(
                self.tinted_sprite(compute=True),
                self.scale_pct,
                self.rotation,
                self.rotation_quality,
                self.stretch_x,
                self.stretch_y,
                self.flip_h,
                self.flip_v,
                self.opacity,
            )
            if len(self._pix_cache) >= PIX_CACHE_MAX_ENTRIES:
                self._pix_cache.clear()
            self._pix_cache[key] = rendered
        qimage = ImageQt.ImageQt(rendered)
        self.setPixmap(QPixmap.fromImage(qimage))
        self._after_pixmap_change()

    def request_render(self):
        key = self._cache_key()
        rendered = self._pix_cache.get(key)
        if rendered is not None:
            self._pending_center = None
            self.setPixmap(QPixmap.fromImage(ImageQt.ImageQt(rendered)))
            self._after_pixmap_change()
            return
        if self._dispatcher is not None:
            self._dispatcher.request(self, key)
            return
        self.update_pixmap()

    def apply_rendered(self, sprite, key, rendered):
        if sprite is not self.sprite:
            return
        if len(self._pix_cache) >= PIX_CACHE_MAX_ENTRIES:
            self._pix_cache.clear()
        self._pix_cache[key] = rendered
        if key != self._cache_key():
            return
        self.setPixmap(QPixmap.fromImage(ImageQt.ImageQt(rendered)))
        scene = self.scene()
        dialog = scene.parent_dialog if scene is not None else None
        if dialog is None or (
            dialog._drag_before is None and scene.transform_box._gesture is None
        ):
            center = self._pending_center
            if center is not None:
                self._pending_center = None
                self.dx = round(center.x() - rendered.width / 2 - self.base_x)
                self.dy = round(center.y() - rendered.height / 2 - self.base_y)
            self._place()
            scene.transform_box.refresh()

    def _after_pixmap_change(self):
        scene = self.scene()
        if scene is not None:
            scene.invalidate_bounds()
        self._place()
        scene = self.scene()
        if scene is not None and scene.parent_dialog is not None:
            scene.transform_box.refresh()

    def _place(self):
        self.setPos(self.base_x + self.dx, self.base_y + self.dy)
        scene = self.scene()
        if scene is not None:
            scene.invalidate_bounds()

    def set_base(self, x, y):
        self.base_x = x
        self.base_y = y
        self._place()

    def setVisible(self, visible):
        super().setVisible(visible)
        scene = self.scene()
        if scene is not None:
            scene.invalidate_bounds()

    def hoverEnterEvent(self, event):
        self.setCursor(Qt.PointingHandCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedChange:
            scene = self.scene()
            if scene is not None:
                scene.note_selection_change(self, bool(value))
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            scene = self.scene()
            if scene is not None:
                scene.invalidate_bounds()
        return super().itemChange(change, value)


class TransformBox:

    NAMES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
    CORNERS = ("nw", "ne", "se", "sw")

    def __init__(self, scene):
        self._scene = scene
        self._items = []
        self._multi = False
        self._gesture = None
        self._pending = None
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(GESTURE_UPDATE_MS)
        self._update_timer.timeout.connect(self._flush_update)
        pen = QPen(TRANSFORM_COLOR, 0)
        pen.setCosmetic(True)
        self._rect_item = QGraphicsRectItem()
        self._rect_item.setPen(pen)
        self._rect_item.setZValue(999)
        self._rect_item.hide()
        scene.addItem(self._rect_item)
        cursors = {
            "nw": Qt.CursorShape.SizeFDiagCursor,
            "se": Qt.CursorShape.SizeFDiagCursor,
            "ne": Qt.CursorShape.SizeBDiagCursor,
            "sw": Qt.CursorShape.SizeBDiagCursor,
            "n": Qt.CursorShape.SizeVerCursor,
            "s": Qt.CursorShape.SizeVerCursor,
            "e": Qt.CursorShape.SizeHorCursor,
            "w": Qt.CursorShape.SizeHorCursor,
        }
        self._handles = {}
        for name in self.NAMES:
            handle = QGraphicsRectItem()
            handle.setBrush(HANDLE_FILL)
            handle.setPen(QPen(HANDLE_BORDER, 0))
            handle.setZValue(1001)
            handle.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            handle.setAcceptHoverEvents(True)
            handle.setCursor(cursors[name])
            handle.hide()
            scene.addItem(handle)
            self._handles[name] = handle
        self._rotate_zones = {}
        for name in self.CORNERS:
            zone = QGraphicsRectItem()
            zone.setPen(Qt.NoPen)
            zone.setBrush(Qt.NoBrush)
            zone.setZValue(1000)
            zone.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            zone.setAcceptHoverEvents(True)
            zone.setCursor(Qt.CursorShape.CrossCursor)
            zone.hide()
            scene.addItem(zone)
            self._rotate_zones[name] = zone

    def _zoom(self):
        views = self._scene.views()
        return abs(views[0].transform().m11()) if views else 1.0

    def _attached_items(self):
        dialog = self._scene.parent_dialog
        if (
            dialog is None
            or dialog._drag_before is not None
            or self._scene._band_start is not None
        ):
            return []
        return [item for item in self._scene.ordered_selection() if item.isVisible()]

    def _angle(self):
        if self._multi or not self._items:
            return 0.0
        return float(self._items[0].rotation) % 360.0

    @staticmethod
    def _rotate_about(point, origin, angle):
        rad = radians(angle)
        cos_a = cos(rad)
        sin_a = sin(rad)
        dx = point.x() - origin.x()
        dy = point.y() - origin.y()
        return QPointF(
            origin.x() + dx * cos_a - dy * sin_a,
            origin.y() + dx * sin_a + dy * cos_a,
        )

    def _anchor_scene(self, rect, name, center, angle):
        return self._rotate_about(self._anchor_point(rect, name), center, angle)

    def _local_rect(self, item):
        rect = self._scene._item_scene_rect(item)
        angle = float(item.rotation) % 360.0
        if not angle:
            return QRectF(rect)
        sprite = item.tinted_sprite()
        factor_x = item.scale_pct * item.stretch_x / 10000.0
        factor_y = item.scale_pct * item.stretch_y / 10000.0
        width = max(1.0, sprite.width * factor_x)
        height = max(1.0, sprite.height * factor_y)
        center = rect.center()
        return QRectF(center.x() - width / 2, center.y() - height / 2, width, height)

    @staticmethod
    def _anchor_point(rect, name):
        if name == "nw":
            return rect.topLeft()
        if name == "n":
            return QPointF(rect.center().x(), rect.top())
        if name == "ne":
            return rect.topRight()
        if name == "e":
            return QPointF(rect.right(), rect.center().y())
        if name == "se":
            return rect.bottomRight()
        if name == "s":
            return QPointF(rect.center().x(), rect.bottom())
        if name == "sw":
            return rect.bottomLeft()
        return QPointF(rect.left(), rect.center().y())

    def refresh(self):
        items = self._attached_items()
        if not items:
            self.hide()
            return
        self._items = items
        self._multi = len(items) > 1
        angle = self._angle()
        rect = self._scene._item_scene_rect(items[0])
        for item in items[1:]:
            rect = rect.united(self._scene._item_scene_rect(item))
        if angle:
            center = rect.center()
            rect = self._local_rect(items[0])
            rad = radians(angle)
            cos_a = cos(rad)
            sin_a = sin(rad)
            rotation = QTransform(
                cos_a, sin_a, -sin_a, cos_a, 0, 0
            )
            self._rect_item.setTransform(
                QTransform.fromTranslate(-center.x(), -center.y())
                * rotation
                * QTransform.fromTranslate(center.x(), center.y())
            )
        else:
            self._rect_item.setTransform(QTransform())
        self._rect_item.setRect(rect)
        self._rect_item.show()
        hs = HANDLE_PX / self._zoom()
        for name in self.NAMES:
            center = self._anchor_scene(rect, name, rect.center(), angle)
            self._handles[name].setRect(
                QRectF(center.x() - hs / 2, center.y() - hs / 2, hs, hs)
            )
            self._handles[name].show()
        rs = HANDLE_ROTATE_RING_PX / self._zoom()
        for name in self.CORNERS:
            center = self._anchor_scene(rect, name, rect.center(), angle)
            self._rotate_zones[name].setRect(
                QRectF(center.x() - rs / 2, center.y() - rs / 2, rs, rs)
            )
            self._rotate_zones[name].setVisible(not self._multi)

    def hide(self):
        self._items = []
        self._multi = False
        self._rect_item.setTransform(QTransform())
        self._rect_item.hide()
        for handle in self._handles.values():
            handle.hide()
        for zone in self._rotate_zones.values():
            zone.hide()

    def hit(self, scene_pos):
        if not self._items or self._gesture is not None:
            return None
        rect = self._rect_item.rect()
        center = rect.center()
        angle = self._angle()
        local_pos = (
            self._rotate_about(scene_pos, center, -angle) if angle else scene_pos
        )
        hs = HANDLE_PX / self._zoom() / 2
        for name in self.NAMES:
            center_local = self._anchor_point(rect, name)
            if (
                abs(local_pos.x() - center_local.x()) <= hs
                and abs(local_pos.y() - center_local.y()) <= hs
            ):
                if name in self.CORNERS:
                    return "scale", name
                return "stretch", name
        if self._multi:
            return None
        rs = HANDLE_ROTATE_RING_PX / self._zoom() / 2
        for name in self.CORNERS:
            center_local = self._anchor_point(rect, name)
            if (
                abs(local_pos.x() - center_local.x()) <= rs
                and abs(local_pos.y() - center_local.y()) <= rs
            ):
                return "rotate", name
        return None

    def start(self, kind, name, scene_pos):
        dialog = self._scene.parent_dialog
        if not self._items:
            self.refresh()
        if not self._items:
            return
        first = self._items[0]
        self._gesture = {
            "kind": kind,
            "name": name,
            "start_pos": QPointF(scene_pos),
            "rect": QRectF(self._rect_item.rect()),
            "angle": self._angle(),
            "items": {
                item: {
                    "scale": item.scale_pct,
                    "stretch_x": item.stretch_x,
                    "stretch_y": item.stretch_y,
                    "rect": self._scene._item_scene_rect(item),
                }
                for item in self._items
            },
            "rotation": first.rotation,
            "before": dialog._snapshot_selected(),
        }

    def update(self, scene_pos, modifiers):
        if self._gesture is None:
            return
        self._pending = (QPointF(scene_pos), modifiers)
        if not self._update_timer.isActive():
            self._update_timer.start()

    def _apply(self, pending):
        scene_pos, modifiers = pending
        gesture = self._gesture
        if gesture is None:
            return
        if gesture["kind"] == "rotate":
            self._update_rotation(scene_pos, modifiers)
        elif gesture["kind"] == "scale":
            self._update_scale(scene_pos, modifiers)
        else:
            self._update_scale(scene_pos, modifiers)
        dialog = self._scene.parent_dialog
        if dialog is not None:
            dialog._update_scene_rect()
        self.refresh()

    def _flush_update(self):
        pending = self._pending
        self._pending = None
        if pending is not None:
            self._apply(pending)

    def commit(self):
        gesture = self._gesture
        self._update_timer.stop()
        pending = self._pending
        self._pending = None
        if gesture is not None and pending is not None:
            self._apply(pending)
        self._gesture = None
        if gesture is None:
            return False
        dialog = self._scene.parent_dialog
        dialog._push(gesture["before"])
        for item in gesture["before"]:
            item.prune_cache()
        dialog._sync_panel()
        return True

    def _clamp(self, value, low, high):
        return max(low, min(high, value))

    def _snap_stretch(self, value):
        if (
            self._scene.snapping_enabled
            and abs(value - CHAR_SCALE_DEFAULT) <= SCALE_SNAP_TOLERANCE_PCT
        ):
            return CHAR_SCALE_DEFAULT
        return value

    def _limit_factor(self, factor, key):
        low = 0.0
        high = float("inf")
        for initial in self._gesture["items"].values():
            value = initial[key]
            low = max(low, CHAR_SCALE_MIN / value)
            high = min(high, CHAR_SCALE_MAX / value)
        return min(max(factor, low), high)

    def _update_rotation(self, scene_pos, modifiers):
        item = self._items[0]
        gesture = self._gesture
        center = gesture["rect"].center()
        a0 = degrees(
            atan2(
                gesture["start_pos"].y() - center.y(),
                gesture["start_pos"].x() - center.x(),
            )
        )
        a1 = degrees(atan2(scene_pos.y() - center.y(), scene_pos.x() - center.x()))
        rotation = gesture["rotation"] + a1 - a0
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            rotation = round(rotation / ROTATE_SNAP_STEP) * ROTATE_SNAP_STEP
        item.rotation = int(self._clamp(round(rotation), ROTATION_MIN, ROTATION_MAX))
        item.update_pixmap()
        self._recenter()

    def _recenter(self):
        item = self._items[0]
        center = self._gesture["rect"].center()
        item.dx = round(center.x() - item.pixmap().width() / 2 - item.base_x)
        item.dy = round(center.y() - item.pixmap().height() / 2 - item.base_y)
        item._place()

    def _update_scale(self, scene_pos, modifiers):
        gesture = self._gesture
        name = gesture["name"]
        rect = gesture["rect"]
        angle = gesture["angle"]
        handle_x, handle_y = HANDLE_FRACTIONS[name]
        pivot_local = QPointF(
            rect.x() + rect.width() * (1.0 - handle_x),
            rect.y() + rect.height() * (1.0 - handle_y),
        )
        pivot_scene = self._rotate_about(pivot_local, rect.center(), angle)
        delta = scene_pos - gesture["start_pos"]
        rad = radians(angle)
        cos_a = cos(rad)
        sin_a = sin(rad)
        dx = delta.x() * cos_a + delta.y() * sin_a
        dy = -delta.x() * sin_a + delta.y() * cos_a
        dx = floor(dx) if dx >= 0 else ceil(dx)
        dy = floor(dy) if dy >= 0 else ceil(dy)
        w = rect.width() * handle_x + rect.x() - pivot_local.x()
        h = rect.height() * handle_y + rect.y() - pivot_local.y()
        if name in ("n", "s"):
            dx = 0.0
            w = 1.0
        elif name in ("e", "w"):
            dy = 0.0
            h = 1.0

        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            u = gesture["start_pos"] - pivot_scene
            v = scene_pos - pivot_scene
            u_mag = (u.x() ** 2 + u.y() ** 2) ** 0.5
            if u_mag < 1e-6:
                return
            dot = u.x() * v.x() + u.y() * v.y()
            factor = abs(dot) / (u_mag * u_mag)
            if dot < 0:
                factor = -factor
            factor_x = factor_y = factor
        else:
            factor_x = 1.0 + dx / w if w else 1.0
            factor_y = 1.0 + dy / h if h else 1.0
        if name in ("n", "s"):
            factor_x = 1.0
        elif name in ("e", "w"):
            factor_y = 1.0
        factor_x = self._limit_factor(factor_x, "stretch_x")
        factor_y = self._limit_factor(factor_y, "stretch_y")

        single = len(gesture["items"]) == 1
        for item, initial in gesture["items"].items():
            stretch_x = round(initial["stretch_x"] * factor_x)
            stretch_y = round(initial["stretch_y"] * factor_y)
            if single and not (modifiers & SNAP_DISABLED_MODIFIER):
                stretch_x = self._snap_stretch(stretch_x)
                stretch_y = self._snap_stretch(stretch_y)
            item.stretch_x = self._clamp(
                stretch_x, CHAR_SCALE_MIN, CHAR_SCALE_MAX
            )
            item.stretch_y = self._clamp(
                stretch_y, CHAR_SCALE_MIN, CHAR_SCALE_MAX
            )
            item.update_pixmap()
            effective_x = item.stretch_x / initial["stretch_x"]
            effective_y = item.stretch_y / initial["stretch_y"]
            if angle:
                top_local = rect.topLeft()
                size_w, size_h = rect.width(), rect.height()
                new_x = pivot_local.x() + (top_local.x() - pivot_local.x()) * effective_x
                new_y = pivot_local.y() + (top_local.y() - pivot_local.y()) * effective_y
                center_local = QPointF(
                    new_x + size_w * effective_x / 2, new_y + size_h * effective_y / 2
                )
                scene_center = self._rotate_about(
                    pivot_scene + (center_local - pivot_local), pivot_scene, angle
                )
                item.dx = round(
                    scene_center.x() - item.pixmap().width() / 2 - item.base_x
                )
                item.dy = round(
                    scene_center.y() - item.pixmap().height() / 2 - item.base_y
                )
            else:
                initial_rect = initial["rect"]
                new_x = (
                    pivot_scene.x()
                    + (initial_rect.left() - pivot_scene.x()) * effective_x
                )
                new_y = (
                    pivot_scene.y()
                    + (initial_rect.top() - pivot_scene.y()) * effective_y
                )
                item.dx = round(new_x - item.base_x)
                item.dy = round(new_y - item.base_y)
            item._place()


HANDLE_FRACTIONS = frozendict({
    "nw": (0.0, 0.0),
    "n": (0.5, 0.0),
    "ne": (1.0, 0.0),
    "w": (0.0, 0.5),
    "e": (1.0, 0.5),
    "sw": (0.0, 1.0),
    "s": (0.5, 1.0),
    "se": (1.0, 1.0),
})


class EditorScene(QGraphicsScene):
    drag_started = Signal()
    drag_finished = Signal()
    snap_size = 0
    snapping_enabled = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self._snap_engine = SnapEngine()
        self._guide_pool = []
        self._guide_pens = None
        self._selection_order = []
        self._checker_key = None
        self._checker_cache = None
        self._bounds_cache = None
        self._band_start = None
        self._ant_offset = 0.0
        self._preview_pool = []
        self._preview_key = None
        self._band = QGraphicsRectItem()
        self._apply_band_palette()
        self._band.setZValue(1002)
        self._band.hide()
        self.addItem(self._band)
        self._ant_timer = QTimer(self)
        self._ant_timer.setInterval(MARQUEE_ANT_MS)
        self._ant_timer.timeout.connect(self._march_ants)
        self.transform_box = TransformBox(self)

    def _apply_band_palette(self):
        pen = QPen(QApplication.palette().color(QPalette.ColorRole.Text), 0)
        pen.setCosmetic(True)
        pen.setDashPattern(MARQUEE_DASH)
        if self._band.pen().style() == Qt.PenStyle.DashLine:
            pen.setDashOffset(self._band.pen().dashOffset())
        self._band.setPen(pen)
        fill = QApplication.palette().color(QPalette.ColorRole.Highlight)
        fill.setAlpha(40)
        self._band.setBrush(fill)
        for preview in self._preview_pool:
            preview.setPen(pen)
            preview.setBrush(fill)

    def _preview_pool_items(self, count):
        while len(self._preview_pool) < count:
            preview = QGraphicsRectItem()
            preview.setPen(self._band.pen())
            preview.setBrush(self._band.brush())
            preview.setZValue(1001.5)
            preview.hide()
            self.addItem(preview)
            self._preview_pool.append(preview)
        return self._preview_pool

    def _update_preview(self, modifiers):
        dialog = self.parent_dialog
        if dialog is None:
            return
        rect = self._band.rect()
        hits = {
            id(item)
            for item in dialog.items
            if item.isVisible() and item.sceneBoundingRect().intersects(rect)
        }
        selected_ids = {id(item) for item in dialog.items if item.isSelected()}
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            preview_ids = selected_ids | hits
        elif modifiers & Qt.KeyboardModifier.AltModifier:
            preview_ids = selected_ids - hits
        else:
            preview_ids = hits
        key = tuple(sorted(preview_ids))
        if key == self._preview_key:
            return
        self._preview_key = key
        ordered = [
            item for item in dialog.items if id(item) in preview_ids
        ]
        pool = self._preview_pool_items(len(ordered))
        for preview, item in zip(pool, ordered):
            preview.setRect(item.sceneBoundingRect())
            preview.show()
        for spare in pool[len(ordered):]:
            spare.hide()

    def _hide_preview(self):
        self._preview_key = None
        for preview in self._preview_pool:
            preview.hide()

    def _march_ants(self):
        self._ant_offset = (self._ant_offset + 1) % (MARQUEE_DASH[0] + MARQUEE_DASH[1])
        pen = self._band.pen()
        pen.setDashOffset(self._ant_offset)
        self._band.setPen(pen)

    def _marquee_target(self, scene_pos):
        for item in self.items(scene_pos):
            if isinstance(item, CharItem):
                return item if item.isVisible() else None
        return None

    def _start_marquee(self, event):
        self._band_start = QPointF(event.scenePos())
        self._band.setRect(self._band_start.x(), self._band_start.y(), 0, 0)
        self._band.show()
        self._ant_timer.start()
        self._hide_preview()
        self.transform_box.hide()
        event.accept()

    def _update_marquee(self, scene_pos, modifiers=Qt.KeyboardModifier.NoModifier):
        self._band.setRect(QRectF(self._band_start, scene_pos).normalized())
        self._update_preview(modifiers)

    def _finish_marquee(self, event):
        self._band_start = None
        rect = self._band.rect()
        self._band.hide()
        self._ant_timer.stop()
        self._hide_preview()
        dialog = self.parent_dialog
        if dialog is None:
            return
        views = self.views()
        zoom = abs(views[0].transform().m11()) if views else 1.0
        moved = (
            rect.width() * zoom > MARQUEE_CLICK_PX
            or rect.height() * zoom > MARQUEE_CLICK_PX
        )
        modifiers = event.modifiers()
        if not moved:
            if not modifiers:
                for item in dialog.items:
                    item.setSelected(False)
                    dialog._sync_panel()
            return
        hits = [
            item
            for item in dialog.items
            if item.isVisible() and item.sceneBoundingRect().intersects(rect)
        ]
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            for item in hits:
                item.setSelected(True)
        elif modifiers & Qt.KeyboardModifier.AltModifier:
            for item in hits:
                item.setSelected(False)
        else:
            for item in dialog.items:
                if item.isVisible():
                    item.setSelected(item in hits)
        dialog._sync_panel()

    def cancel_marquee(self):
        if self._band_start is None:
            return False
        self._band_start = None
        self._band.hide()
        self._hide_preview()
        self._ant_timer.stop()
        return True

    def note_selection_change(self, item, selected):
        if selected:
            if item in self._selection_order:
                self._selection_order.remove(item)
            self._selection_order.append(item)
        elif item in self._selection_order:
            self._selection_order.remove(item)

    def ordered_selection(self):
        ordered = [item for item in self._selection_order if item.isSelected()]
        self._selection_order = ordered
        return ordered

    def mousePressEvent(self, event):
        if self.transform_box._gesture is not None:
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            dialog = self.parent_dialog
            if (
                dialog is not None
                and dialog._drag_before is None
                and not dialog._in_slider_gesture()
            ):
                hit = self.transform_box.hit(event.scenePos())
                if hit is not None:
                    kind, name = hit
                    self.transform_box.start(kind, name, event.scenePos())
                    event.accept()
                    return
            if self._marquee_target(event.scenePos()) is None:
                self._start_marquee(event)
                return
            self.drag_started.emit()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._band_start is not None:
            self._update_marquee(event.scenePos(), event.modifiers())
            event.accept()
            return
        if self.transform_box._gesture is not None:
            self.transform_box.update(event.scenePos(), event.modifiers())
            event.accept()
            return
        super().mouseMoveEvent(event)
        if not (event.buttons() & Qt.LeftButton):
            if any(guide.isVisible() for guide in self._guide_pool):
                self._hide_guides()
                self.transform_box.refresh()
            return
        raw_translation = event.scenePos() - event.buttonDownScenePos(Qt.LeftButton)
        self._apply_object_snap(event.modifiers(), raw_translation)
        self.transform_box.refresh()
        if self.parent_dialog is not None:
            self.parent_dialog._update_scene_rect()

    def mouseReleaseEvent(self, event):
        if self._band_start is not None:
            self._finish_marquee(event)
            event.accept()
            return
        if self.transform_box._gesture is not None:
            if event.button() == Qt.LeftButton:
                self.transform_box.commit()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.drag_finished.emit()

    def begin_snap(self):
        self._snap_engine.reset()
        self._hide_guides()

    def end_snap(self):
        self._snap_engine.reset()
        self._hide_guides()

    def _item_scene_rect(self, item):
        pixmap = item.pixmap()
        return item.mapRectToScene(QRectF(0, 0, pixmap.width(), pixmap.height()))

    def _gather_movers(self):
        if not hasattr(self, "_snap_start"):
            return []
        return [
            (item, start)
            for item, start in self._snap_start.items()
            if item.pos() != start
        ]

    def _load_statics(self, movers):
        moving = {id(item) for item, _start in movers}
        statics = [
            (id(item), self._item_scene_rect(item))
            for item in self.parent_dialog.items
            if item.isVisible() and id(item) not in moving
        ]
        self._snap_engine.set_statics(statics, *self.parent_dialog.canvas_size)

    def _snap_threshold(self):
        views = self.views()
        zoom = abs(views[0].transform().m11()) if views else 1.0
        return SNAP_THRESHOLD_PX / max(0.05, zoom)

    def _raw_moving_rect(self, movers, translation):
        rect = None
        for item, start in movers:
            pixmap = item.pixmap()
            r = QRectF(0, 0, pixmap.width(), pixmap.height()).translated(
                start.x() + translation.x(), start.y() + translation.y()
            )
            rect = r if rect is None else rect.united(r)
        return rect

    def _apply_object_snap(self, modifiers=None, raw_translation=None):
        if raw_translation is None:
            self._hide_guides()
            return
        if not self.snapping_enabled or (
            modifiers is not None and modifiers & SNAP_DISABLED_MODIFIER
        ):
            self._hide_guides()
            return
        movers = self._gather_movers()
        if not movers:
            self._hide_guides()
            return
        if not self._snap_engine.is_ready():
            self._load_statics(movers)

        translation = QPointF(round(raw_translation.x()), round(raw_translation.y()))

        box = self._raw_moving_rect(movers, translation)
        dx, dy, guides = self._snap_engine.find_snap(
            box, self._snap_threshold(), self.snap_size
        )

        for item, start in movers:
            item.setPos(start + translation + QPointF(dx, dy))
        self._render_guides(guides)

    def _render_guides(self, guides):
        if not guides:
            self._hide_guides()
            return
        scene_rect = self.sceneRect()
        pool = self._guide_pool_items(len(guides))
        for line_item, (horizontal, coord, style) in zip(pool, guides):
            if horizontal:
                line_item.setLine(coord, scene_rect.top(), coord, scene_rect.bottom())
            else:
                line_item.setLine(scene_rect.left(), coord, scene_rect.right(), coord)
            line_item.setPen(self._guide_pen(style))
            line_item.show()

    def _guide_pen(self, style):
        if self._guide_pens is None:
            edge = QPen(QColor(SNAP_GUIDE_COLOR))
            center = QPen(QColor(SNAP_GUIDE_COLOR))
            spacing = QPen(QColor(SNAP_SPACING_GUIDE_COLOR))
            for pen in (edge, center, spacing):
                pen.setCosmetic(True)
                pen.setWidthF(1)
            center.setDashPattern([4, 4])
            spacing.setDashPattern([1, 3])
            self._guide_pens = {
                GuideStyle.EDGE: edge,
                GuideStyle.CENTER: center,
                GuideStyle.SPACING: spacing,
            }
        return self._guide_pens[style]

    def _guide_pool_items(self, count):
        while len(self._guide_pool) < min(count, GUIDE_POOL_SIZE):
            line_item = QGraphicsLineItem()
            line_item.setZValue(1000)
            line_item.hide()
            self.addItem(line_item)
            self._guide_pool.append(line_item)
        return self._guide_pool[:count]

    def _hide_guides(self):
        for line_item in self._guide_pool:
            line_item.hide()

    def invalidate_bounds(self):
        self._bounds_cache = None

    def _background_bounds(self):
        if self._bounds_cache is not None:
            return QRectF(self._bounds_cache)
        dialog = self.parent_dialog
        if dialog is None:
            return QRectF()
        bounds = QRectF(0, 0, *dialog.canvas_size)
        for item in dialog.items:
            if item.isVisible():
                bounds = bounds.united(self._item_scene_rect(item))
        self._bounds_cache = QRectF(bounds)
        return bounds

    def _checker_brush(self, zoom):
        palette = QApplication.palette()
        base = palette.color(QPalette.ColorRole.Base)
        text = palette.color(QPalette.ColorRole.Text)
        alt = _blend(base, text, CHECKER_TINT)
        px = max(1, round(CHECKER_PX * zoom))
        key = (px, base.rgba(), alt.rgba())
        if self._checker_key != key:
            tile = QPixmap(px * 2, px * 2)
            tile.fill(alt)
            tile_painter = QPainter(tile)
            tile_painter.fillRect(0, 0, px, px, base)
            tile_painter.fillRect(px, px, px, px, base)
            tile_painter.end()
            brush = QBrush(tile)
            brush.setTransform(QTransform.fromScale(1.0 / zoom, 1.0 / zoom))
            self._checker_key = key
            self._checker_cache = brush
        return self._checker_cache

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        palette = QApplication.palette()
        base = palette.color(QPalette.ColorRole.Base)
        text = palette.color(QPalette.ColorRole.Text)
        shadow = palette.color(QPalette.ColorRole.Shadow)
        painter.fillRect(rect, _blend(base, shadow, PASTEBOARD_TINT))
        bounds = self._background_bounds()
        exposed = rect.intersected(bounds)
        if exposed.isNull():
            return
        alt = _blend(base, text, CHECKER_TINT)
        painter.fillRect(exposed, base)
        views = self.views()
        zoom = abs(views[0].transform().m11()) if views else 1.0
        if CHECKER_PX * zoom >= CHECKER_MIN_SCREEN_PX:
            painter.fillRect(exposed, self._checker_brush(zoom))
        else:
            painter.fillRect(exposed, alt)
        painter.setPen(QPen(_blend(base, text, BORDER_TINT), 0))
        painter.drawRect(bounds)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.scenePos(), self.views()[0].transform())
        if isinstance(item, CharItem) and item.isVisible():
            self.parent_dialog._edit_character(item)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.scenePos(), self.views()[0].transform())
        if not isinstance(item, CharItem) or not item.isVisible():
            return
        item.setSelected(True)
        dialog = self.parent_dialog
        menu = QMenu()
        menu.addAction("Duplicate", lambda: dialog._duplicate_selection())
        menu.addAction("Reset Scale", lambda: dialog._reset_item(item, "scale_pct"))
        menu.addAction("Reset Rotation", lambda: dialog._reset_item(item, "rotation"))
        menu.addAction(
            "Rotate 90° Counter-Clockwise", lambda: dialog._rotate_selection_90(-1)
        )
        menu.addAction(
            "Rotate 90° Clockwise", lambda: dialog._rotate_selection_90(1)
        )
        menu.addAction("Bring to Front", lambda: dialog._reorder_selection(True))
        menu.addAction("Send to Back", lambda: dialog._reorder_selection(False))
        menu.addAction("Delete Character", lambda: dialog._delete_items([item]))
        menu.exec(event.screenPos())


class EditorView(QGraphicsView):
    zoom_changed = Signal(float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._pan_start = None
        self._pan_button = None
        self._space_pan = False

    def zoom_to(self, scale):
        current = self.transform().m11()
        scale = max(ZOOM_SCALES[0], min(ZOOM_SCALES[-1], scale))
        if abs(scale - current) < 1e-9:
            return
        self.setTransform(self.transform().scale(scale / current, scale / current))
        self.zoom_changed.emit(self.transform().m11())

    def zoom_in(self):
        current = self.transform().m11()
        for scale in ZOOM_SCALES:
            if scale > current + 1e-9:
                self.zoom_to(scale)
                return

    def zoom_out(self):
        current = self.transform().m11()
        for scale in reversed(ZOOM_SCALES):
            if scale < current - 1e-9:
                self.zoom_to(scale)
                return

    def wheelEvent(self, event):
        delta = event.angleDelta()
        if event.modifiers() & Qt.ShiftModifier and delta.y():
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta.y())
            event.accept()
        elif delta.y():
            if delta.y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key.Key_Space
            and not event.modifiers()
            and not self._space_pan
        ):
            self._space_pan = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and self._space_pan:
            self._space_pan = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor if self._pan_start is not None else Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        if self._pan_start is None and (
            event.button() == Qt.MiddleButton
            or (event.button() == Qt.LeftButton and self._space_pan)
        ):
            self._pan_start = event.position()
            self._pan_button = event.button()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_start is not None:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pan_start is not None and event.button() == self._pan_button:
            self._pan_start = None
            self._pan_button = None
            self.setCursor(
                Qt.OpenHandCursor if self._space_pan else Qt.ArrowCursor
            )
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class ZoomEntry(QLineEdit):
    zoom_committed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ZoomEntry")
        self.setReadOnly(False)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setToolTip("Zoom level: type a percentage and press Enter.")
        self.setAccessibleName("Zoom level")
        self.setValidator(QIntValidator(1, round(ZOOM_SCALES[-1] * 100), self))
        self.editingFinished.connect(self._commit)
        self.textChanged.connect(self._sync_width)
        self._last = 1.0
        self.set_zoom(1.0)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()

    def _sync_width(self):
        metrics = self.fontMetrics()
        text = self.text() or "100"
        reference = max(
            metrics.horizontalAdvance("100"), metrics.horizontalAdvance(text)
        )
        self.setMinimumWidth(reference + 20)

    def restore_zoom(self):
        self.setText(str(round(self._last * 100)))
        self.setModified(False)
        self._sync_width()

    def set_zoom(self, scale):
        self._last = scale
        if self.hasFocus() and self.isModified():
            return
        self.setText(str(round(scale * 100)))
        self.setModified(False)
        self._sync_width()

    def _commit(self):
        text = self.text().strip()
        try:
            percent = int(text)
        except ValueError:
            self.restore_zoom()
            return
        scale = max(ZOOM_SCALES[0], min(ZOOM_SCALES[-1], percent / 100))
        nearest = min(ZOOM_SCALES, key=lambda entry: abs(entry - scale))
        self.zoom_committed.emit(nearest)
        self.setText(str(round(nearest * 100)))
        self.setModified(False)
        self._sync_width()


class UndoStack:
    def __init__(self, max_steps=UNDO_MAX_STEPS):
        self._max = max_steps
        self._undo = []
        self._redo = []

    def push(self, before, after):
        self._undo.append((before, after))
        self._redo.clear()
        if len(self._undo) > self._max:
            self._undo.pop(0)

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self, apply):
        if not self._undo:
            return False
        before, _ = self._undo.pop()
        self._redo.append((before, _))
        apply(before)
        return True

    def redo(self, apply):
        if not self._redo:
            return False
        before, after = self._redo.pop()
        self._undo.append((before, after))
        apply(after)
        return True


class AdvancedEditorDialog(QDialog):
    def __init__(self, parent, params, valid_chars=None):
        super().__init__(parent)
        self.params = params
        self.valid_chars = valid_chars
        self.font_paths = get_font_paths(params["font"], params["color"])

        self.letter_spacing = LETTER_SPACING_DEFAULT
        self.line_spacing = LINE_SPACING_DEFAULT
        self.baseline = "bottom"
        self.align = "left"
        self.snap_grid = SNAP_GRID_DEFAULT

        self.undo_stack = UndoStack()
        self._char_cache = {}
        self._color_paths = {params["color"]: self.font_paths}
        self._dirty = False
        self._exported_signature = None
        self._fitted = False
        self._sprite_provider = self._sprite_for
        self._render_dispatcher = RenderDispatcher(self)
        self._build_scene()
        self._build_ui()
        self._connect_selection()
        self._install_shortcuts()
        self._sync_panel()
        self._initial_signature = self._capture_all()

        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowTitle("MetalSlugFontReborn - Advanced Editor (Beta)")
        self.setWindowIcon(
            QIcon(str(PROJECT_ROOT / "Assets" / "Icons" / "Raubtier.ico"))
        )
        self.resize(EDITOR_DEFAULT_WIDTH, EDITOR_DEFAULT_HEIGHT)

    def _build_scene(self):
        self.scene = EditorScene(self)
        self.scene.parent_dialog = self
        self.scene.snap_size = SNAP_GRID_DEFAULT
        self.scene.snapping_enabled = True
        self.view = EditorView(self.scene)

        placements, (canvas_w, canvas_h) = layout_characters(
            self.params["text"],
            self.font_paths,
            char_images=self._char_cache,
            letter_spacing=self.letter_spacing,
            line_spacing=self.line_spacing,
            baseline=self.baseline,
            align=self.align,
        )
        self.canvas_size = (canvas_w, canvas_h)

        self.canvas_rect = QGraphicsRectItem(0, 0, canvas_w, canvas_h)
        self.canvas_rect.setPen(Qt.NoPen)
        self.canvas_rect.setZValue(-1)
        self.scene.addItem(self.canvas_rect)

        self.items = []
        for char, sprite, x, y in placements:
            item = CharItem(
                char,
                sprite,
                x,
                y,
                self._sprite_provider,
                self._render_dispatcher,
                self.params["color"],
            )
            item.update_pixmap()
            self.scene.addItem(item)
            self.items.append(item)

        self._update_scene_rect()

    def _update_scene_rect(self):
        bounds = self.scene._background_bounds()
        rect = QRectF(
            bounds.left() - SCENE_PADDING,
            bounds.top() - SCENE_PADDING,
            bounds.width() + 2 * SCENE_PADDING,
            bounds.height() + 2 * SCENE_PADDING,
        )
        old = self.scene.sceneRect()
        if old == rect:
            return
        self.scene.setSceneRect(rect)
        self.scene.update(old.united(rect))

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted:
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            self._fitted = True
        self.zoom_entry.set_zoom(self.view.transform().m11())
        self.view.setFocus()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_toolbar())
        splitter = QSplitter(Qt.Horizontal, self)
        outer.addWidget(splitter, 1)
        outer.addWidget(self._build_status_bar())

        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_scroll.setWidget(panel)
        self.panel_scroll = panel_scroll
        splitter.addWidget(self.view)
        splitter.addWidget(panel_scroll)
        splitter.setStretchFactor(0, 1)

        color_row = QHBoxLayout()
        color_label = QLabel("Font color:")
        self.font_color_combo = QComboBox()
        colors = get_font_colors(self.params["font"])
        self.font_color_combo.blockSignals(True)
        self.font_color_combo.addItems(colors)
        if self.params.get("color") in colors:
            self.font_color_combo.setCurrentText(self.params["color"])
        self.font_color_combo.blockSignals(False)
        self.font_color_combo.setToolTip(
            "Switch every character to another color palette of this font."
        )
        self.font_color_combo.currentTextChanged.connect(
            self._on_font_color_changed
        )
        color_row.addWidget(color_label)
        color_row.addWidget(self.font_color_combo, 1)
        panel_layout.addLayout(color_row)

        panel_layout.addWidget(self._build_character_group())
        panel_layout.addWidget(self._build_global_group())

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setToolTip("Discard all changes and close the editor.")
        cancel_btn.clicked.connect(self.reject)
        panel_layout.addWidget(cancel_btn)
        panel_layout.addStretch()

        for first, second in (
            (self.item_color_combo, self.offset_x_spin),
            (self.offset_x_spin, self.offset_y_spin),
            (self.offset_y_spin, self.scale_slider),
            (self.scale_slider, self.scale_spin),
            (self.scale_spin, self.stretch_x_spin),
            (self.stretch_x_spin, self.stretch_y_spin),
            (self.stretch_y_spin, self.rotation_slider),
            (self.rotation_slider, self.rotation_spin),
            (self.rotation_spin, self.rotation_quality),
            (self.rotation_quality, self.opacity_slider),
            (self.opacity_slider, self.opacity_spin),
            (self.opacity_spin, self.hue_slider),
            (self.hue_slider, self.hue_spin),
            (self.hue_spin, self.letter_spacing_spin),
            (self.letter_spacing_spin, self.line_spacing_spin),
            (self.line_spacing_spin, self.baseline_combo),
            (self.baseline_combo, self.align_combo),
            (self.align_combo, cancel_btn),
        ):
            self.setTabOrder(first, second)

        self._fit_panel(splitter, panel_scroll, panel)
        self._apply_chrome_style()

    def _fit_panel(self, splitter, scroll, content):
        chrome = scroll.frameWidth() * 2 + self.style().pixelMetric(
            QStyle.PixelMetric.PM_ScrollBarExtent
        )
        scroll.setMinimumWidth(max(PANEL_WIDTH, content.sizeHint().width() + chrome))
        share = min(EDITOR_DEFAULT_WIDTH - CANVAS_MIN_WIDTH, scroll.minimumWidth())
        splitter.setSizes([EDITOR_DEFAULT_WIDTH - share, share])

    def _toolbar_button(self, layout, text, tip, slot, accessible=None):
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tip)
        button.clicked.connect(slot)
        if accessible:
            button.setAccessibleName(accessible)
        layout.addWidget(button)
        return button

    def _toolbar_separator(self, layout):
        line = QFrame()
        line.setObjectName("ToolbarSeparator")
        line.setFixedWidth(1)
        line.setStyleSheet("background: rgba(128, 128, 128, 90); border: none;")
        layout.addWidget(line)

    def _build_toolbar(self):
        bar = QWidget()
        bar.setObjectName("EditorToolbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        self.undo_btn = self._toolbar_button(
            layout, "Undo", "Undo the last edit (Ctrl+Z).", self._undo
        )
        self.redo_btn = self._toolbar_button(
            layout, "Redo", "Re-apply the last undone edit (Ctrl+Y).", self._redo
        )
        self._toolbar_separator(layout)
        self.zoom_out_btn = self._toolbar_button(
            layout,
            "−",
            "Zoom out (also: mouse wheel down, Ctrl+-).",
            self.view.zoom_out,
            "Zoom out",
        )
        self.zoom_out_btn.setFixedWidth(28)
        self.zoom_in_btn = self._toolbar_button(
            layout,
            "+",
            "Zoom in (also: mouse wheel up, Ctrl+=).",
            self.view.zoom_in,
            "Zoom in",
        )
        self.zoom_in_btn.setFixedWidth(28)
        self.fit_btn = self._toolbar_button(
            layout, "Fit", "Zoom so the whole image is visible (Ctrl+0).", self._fit_view
        )
        self.actual_size_btn = self._toolbar_button(
            layout, "1:1", "Reset the zoom to 100% (Ctrl+1).", self._zoom_actual
        )
        layout.addStretch()
        self.help_btn = self._toolbar_button(
            layout,
            "?",
            "How the editor works: mouse actions, keys, snapping.",
            self._show_help,
            "Editor help",
        )
        self.help_btn.setFixedWidth(28)
        self.export_btn = self._toolbar_button(
            layout,
            "Save Image",
            "Render the edited composition and save it with the main "
            "window's compression and scale settings (Ctrl+S).",
            self.export_image,
        )
        self.undo_btn.setEnabled(False)
        self.redo_btn.setEnabled(False)
        return bar

    def _build_status_bar(self):
        bar = QWidget()
        bar.setObjectName("EditorStatusBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(10)
        self.status_selection_label = QLabel()
        self.status_chars_label = QLabel()
        self.status_dirty_label = QLabel()
        for label in (
            self.status_selection_label,
            self.status_chars_label,
            self.status_dirty_label,
        ):
            layout.addWidget(label)
        layout.addStretch()
        self.status_canvas_label = QLabel()
        layout.addWidget(self.status_canvas_label)
        self.zoom_entry = ZoomEntry()
        self.zoom_entry.zoom_committed.connect(self.view.zoom_to)
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(2)
        zoom_row.addWidget(self.zoom_entry)
        self.zoom_suffix_label = QLabel("%")
        self.zoom_suffix_label.setObjectName("ZoomSuffix")
        zoom_row.addWidget(self.zoom_suffix_label)
        layout.addLayout(zoom_row)
        self._update_status_counts()
        return bar

    def _apply_chrome_style(self):
        palette = QApplication.palette()
        base = palette.color(QPalette.ColorRole.Window)
        field = palette.color(QPalette.ColorRole.Base)
        text = palette.color(QPalette.ColorRole.Text)
        shadow = palette.color(QPalette.ColorRole.Shadow)
        hover = _blend(base, text, 0.12).name()
        pressed = _blend(base, text, 0.22).name()
        border = _blend(base, shadow, 0.4).name()
        self.setStyleSheet(
            f"""
            QWidget#EditorToolbar {{
                background: {base.name()};
                border-bottom: 1px solid {border};
            }}
            QWidget#EditorStatusBar {{
                background: {base.name()};
                border-top: 1px solid {border};
            }}
            QWidget#EditorToolbar QToolButton {{
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                background: transparent;
            }}
            QWidget#EditorToolbar QToolButton:hover {{
                background: {hover};
            }}
            QWidget#EditorToolbar QToolButton:pressed {{
                background: {pressed};
            }}
            QWidget#EditorToolbar QToolButton:disabled {{
                color: {shadow.name()};
            }}
            QLineEdit#ZoomEntry {{
                background: {field.name()};
                color: {text.name()};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 1px 6px;
            }}
            QLabel#ZoomSuffix {{
                color: {text.name()};
            }}
            """
        )

    HELP_TEXT = """\
Mouse

- Drag a character to move it. Guides snap it to other
  characters' edges, centres and baselines; hold Alt or Ctrl
  to suspend snapping.
- Drag the corner squares of the selection box to resize and
  the edge squares to stretch one axis. The opposite corner
  stays put, Shift keeps the aspect ratio, and the ring just
  outside a corner rotates (Shift snaps to 45 degree steps).
  With several characters selected the box scales or stretches
  the whole group.
- Drag on empty space for a marquee: it selects everything it
  touches and highlights characters while you drag. Shift adds,
  Alt subtracts, a plain click on empty space clears, Escape
  cancels. Ctrl+click adds single characters.
- Wheel zooms, Shift + wheel scrolls sideways, middle-button
  drag or Space pans. Double-click a character to replace it,
  right-click for duplicate, resets, 90 degree rotations, draw
  order and delete.

Keys

- Arrow keys nudge, Shift + Arrow nudges by 10.
- Ctrl+A selects all, Escape clears the selection (and closes
  the editor when nothing is selected), Delete removes, Ctrl+D
  duplicates.
- Ctrl+Z / Ctrl+Y undo and redo, Ctrl+S saves the image.
- Ctrl+= / Ctrl+- zoom, Ctrl+0 fits the view, Ctrl+1 resets to
  100%. You can also type a number into the zoom box and press
  Enter.

Panel

- Color recolors the selection, Font color recolors every
  character, Reset brings back their original colors.
- The quick buttons act on the selection: Middle centers it on
  the canvas, Reset restores how it looked when the editor
  opened, Flip mirrors it, Duplicate copies it.
- Opacity blends the selection over what is behind it, Hue
  rotates its colors while keeping white and black readable.
- Spacing & Alignment re-lays out the whole text; Canvas size
  sets an exact image size and Crop to Content shrinks it
  around the visible characters. Everything is undoable.
"""

    def _show_help(self):
        QMessageBox.information(self, "Advanced Editor Help", self.HELP_TEXT)

    def _fit_view(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.zoom_entry.set_zoom(self.view.transform().m11())

    def _zoom_actual(self):
        self.view.zoom_to(1.0)

    def _update_status_counts(self):
        visible = sum(1 for it in self.items if it.isVisible())
        self.status_chars_label.setText(f"Characters: {visible}")
        selected = len(self._selected())
        self.status_selection_label.setText(
            f"Selected: {selected}" if selected else "No selection"
        )
        canvas_w, canvas_h = self.canvas_size
        self.status_canvas_label.setText(
            f"Canvas: {round(canvas_w)} x {round(canvas_h)}"
        )
        self.zoom_entry.set_zoom(self.view.transform().m11())
        self.status_dirty_label.setText("Unsaved edits" if self._dirty else "")
        self._sync_state_button(
            self.undo_btn, self.undo_stack.can_undo(), QPalette.ColorRole.Link
        )
        self._sync_state_button(
            self.redo_btn, self.undo_stack.can_redo(), QPalette.ColorRole.LinkVisited
        )

    def _sync_state_button(self, button, enabled, role):
        button.setEnabled(enabled)
        if not enabled:
            button.setStyleSheet("")
            return
        color = QApplication.palette().color(QPalette.ColorGroup.Active, role)
        button.setStyleSheet(
            f"QToolButton {{ color: {color.name()}; font-weight: bold; }}"
        )

    def _make_collapsible(self, group, expanded=True):
        group.setCheckable(True)
        group.setChecked(expanded)
        group.toggled.connect(self._on_group_toggled)
        return group

    def _on_group_toggled(self, checked):
        self._set_group_children_visible(self.sender(), checked)

    @staticmethod
    def _set_group_children_visible(group, visible):
        for child in group.findChildren(QWidget):
            child.setVisible(visible)

    def _build_character_group(self):
        group = self._make_collapsible(QGroupBox("Character Controls"))
        self.character_group = group
        form = QFormLayout(group)

        self.selection_label = QLabel("Nothing selected")
        self.selection_label.setWordWrap(True)
        form.addRow(self.selection_label)

        self.item_color_combo = QComboBox()
        colors = get_font_colors(self.params["font"])
        self.item_color_combo.blockSignals(True)
        self.item_color_combo.addItems(colors)
        if self.params.get("color") in colors:
            self.item_color_combo.setCurrentText(self.params["color"])
        self.item_color_combo.blockSignals(False)
        self.item_color_combo.setToolTip(
            "Switch the selected characters to another color palette "
            "of this font."
        )
        self.item_color_combo.currentTextChanged.connect(
            self._on_item_color_changed
        )
        form.addRow("Color:", self.item_color_combo)

        self.offset_x_spin = QSpinBox()
        self.offset_x_spin.setRange(-5000, 5000)
        self.offset_x_spin.setToolTip(
            "Horizontal position of the selected character(s)."
        )
        self.offset_x_spin.valueChanged.connect(
            lambda value: self._apply_offset(dx=value)
        )
        form.addRow("Offset X:", self.offset_x_spin)

        self.offset_y_spin = QSpinBox()
        self.offset_y_spin.setRange(-5000, 5000)
        self.offset_y_spin.setToolTip("Vertical position of the selected character(s).")
        self.offset_y_spin.valueChanged.connect(
            lambda value: self._apply_offset(dy=value)
        )
        form.addRow("Offset Y:", self.offset_y_spin)

        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(CHAR_SCALE_MIN, CHAR_SCALE_MAX)
        self.scale_slider.setValue(CHAR_SCALE_DEFAULT)
        self.scale_slider.setToolTip(
            "Size as a percentage of the original sprite. With several "
            "characters selected they scale together around the "
            "selection, keeping their spacing. Snaps to 100% or to "
            "match another character's size while dragging."
        )
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(CHAR_SCALE_MIN, CHAR_SCALE_MAX)
        self.scale_spin.setValue(CHAR_SCALE_DEFAULT)
        self.scale_spin.setSuffix("%")
        self.scale_spin.setToolTip("Type an exact size percentage.")
        self.scale_slider.valueChanged.connect(self._on_scale_slider_changed)
        self.scale_spin.valueChanged.connect(self._on_scale_spin_changed)
        self.scale_slider.sliderPressed.connect(self._begin_slider_undo)
        self.scale_slider.sliderReleased.connect(self._end_slider_undo)
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.scale_slider, 1)
        scale_row.addWidget(self.scale_spin)
        form.addRow("Scale %:", scale_row)

        self.stretch_x_spin = QSpinBox()
        self.stretch_x_spin.setRange(CHAR_SCALE_MIN, CHAR_SCALE_MAX)
        self.stretch_x_spin.setValue(CHAR_SCALE_DEFAULT)
        self.stretch_x_spin.setSuffix("%")
        self.stretch_x_spin.setToolTip(
            "Horizontal stretch of the selected character(s), on top of "
            "the uniform scale. 100% keeps the sprite's own width. "
            "Stretches use nearest-neighbor sampling so pixels stay sharp."
        )
        self.stretch_x_spin.valueChanged.connect(
            lambda value: self._apply_char_property("stretch_x", value)
        )
        self.stretch_y_spin = QSpinBox()
        self.stretch_y_spin.setRange(CHAR_SCALE_MIN, CHAR_SCALE_MAX)
        self.stretch_y_spin.setValue(CHAR_SCALE_DEFAULT)
        self.stretch_y_spin.setSuffix("%")
        self.stretch_y_spin.setToolTip(
            "Vertical stretch of the selected character(s), on top of "
            "the uniform scale. 100% keeps the sprite's own height. "
            "Stretches use nearest-neighbor sampling so pixels stay sharp."
        )
        self.stretch_y_spin.valueChanged.connect(
            lambda value: self._apply_char_property("stretch_y", value)
        )
        stretch_row = QHBoxLayout()
        stretch_row.setSpacing(4)
        stretch_row.addWidget(QLabel("X:"))
        stretch_row.addWidget(self.stretch_x_spin, 1)
        stretch_row.addWidget(QLabel("Y:"))
        stretch_row.addWidget(self.stretch_y_spin, 1)
        form.addRow("Stretch:", stretch_row)

        self.rotation_slider = QSlider(Qt.Horizontal)
        self.rotation_slider.setRange(ROTATION_MIN, ROTATION_MAX)
        self.rotation_slider.setValue(0)
        self.rotation_slider.setTickPosition(QSlider.TicksBelow)
        self.rotation_slider.setTickInterval(45)
        self.rotation_slider.setToolTip(
            "Clockwise rotation of the selected character(s). Hold Shift "
            "while dragging to snap to 45° increments."
        )
        self.rotation_spin = QSpinBox()
        self.rotation_spin.setRange(ROTATION_MIN, ROTATION_MAX)
        self.rotation_spin.setSuffix("°")
        self.rotation_spin.setToolTip("Type an exact rotation angle.")
        self.rotation_slider.valueChanged.connect(self._on_rotation_slider_changed)
        self.rotation_spin.valueChanged.connect(self._on_rotation_spin_changed)
        self.rotation_slider.sliderPressed.connect(self._begin_slider_undo)
        self.rotation_slider.sliderReleased.connect(self._end_slider_undo)
        rotation_row = QHBoxLayout()
        rotation_row.addWidget(self.rotation_slider, 1)
        rotation_row.addWidget(self.rotation_spin)
        form.addRow("Rotation:", rotation_row)

        self.rotation_quality = QComboBox()
        self.rotation_quality.addItems(
            [
                QUALITY_FAST_ROTSPRITE,
                QUALITY_ROTSPRITE,
                QUALITY_NEAREST_ROTATION,
            ]
        )
        self.rotation_quality.setToolTip(
            "RotSprite and Fast RotSprite keep sharp pixel edges when "
            "rotating; Nearest is the classic jagged method. Rotations in "
            "multiples of 90 degrees are always pixel-exact. Higher quality "
            "is slower on large images."
        )
        self.rotation_quality.currentTextChanged.connect(
            self._on_rotation_quality_changed
        )
        form.addRow("Rotation quality:", self.rotation_quality)

        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(OPACITY_MIN, OPACITY_MAX)
        self.opacity_slider.setValue(OPACITY_DEFAULT)
        self.opacity_slider.setToolTip(
            "Opacity of the selected character(s): 100% is fully solid, "
            "lower values blend the character over what is behind it."
        )
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(OPACITY_MIN, OPACITY_MAX)
        self.opacity_spin.setValue(OPACITY_DEFAULT)
        self.opacity_spin.setSuffix("%")
        self.opacity_spin.setToolTip("Type an exact opacity percentage.")
        self.opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)
        self.opacity_spin.valueChanged.connect(self._on_opacity_spin_changed)
        self.opacity_slider.sliderPressed.connect(self._begin_slider_undo)
        self.opacity_slider.sliderReleased.connect(self._end_slider_undo)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self.opacity_slider, 1)
        opacity_row.addWidget(self.opacity_spin)
        form.addRow("Opacity:", opacity_row)

        self.hue_slider = QSlider(Qt.Horizontal)
        self.hue_slider.setRange(HUE_MIN, HUE_MAX)
        self.hue_slider.setValue(0)
        self.hue_slider.setTickPosition(QSlider.TicksBelow)
        self.hue_slider.setTickInterval(45)
        self.hue_slider.setToolTip(
            "Rotate the colors of the selected character(s) around the "
            "color wheel. White and black pixels keep their shade; only "
            "colored pixels change, so the sprite stays readable."
        )
        self.hue_spin = QSpinBox()
        self.hue_spin.setRange(HUE_MIN, HUE_MAX)
        self.hue_spin.setSuffix("°")
        self.hue_spin.setToolTip("Type an exact hue rotation in degrees.")
        self.hue_slider.valueChanged.connect(self._on_hue_slider_changed)
        self.hue_spin.valueChanged.connect(self._on_hue_spin_changed)
        self.hue_slider.sliderPressed.connect(self._begin_slider_undo)
        self.hue_slider.sliderReleased.connect(self._end_slider_undo)
        hue_row = QHBoxLayout()
        hue_row.addWidget(self.hue_slider, 1)
        hue_row.addWidget(self.hue_spin)
        form.addRow("Hue shift:", hue_row)

        form.addRow(self._build_selection_actions_row())

        return group

    def _build_selection_actions_row(self):
        widget = QWidget()
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self._transform_buttons = []

        for column, (text, tip, handler) in enumerate(
            (
                (
                    "Middle",
                    "Move the selected characters to the middle of the image.",
                    self._center_selection_on_canvas,
                ),
                (
                    "Reset",
                    ("Restore the selected characters to how they were "
                     "when the editor opened: position, size, rotation, "
                     "flips, opacity and hue."),
                    self._reset_to_original,
                ),
                (
                    "Flip ↔",
                    "Mirror the selected characters horizontally (exact pixels).",
                    lambda: self._flip_selection("h"),
                ),
                (
                    "Flip ↕",
                    "Mirror the selected characters vertically (exact pixels).",
                    lambda: self._flip_selection("v"),
                ),
                (
                    "Duplicate",
                    ("Copy the selected characters next to the originals "
                     "(Ctrl+D)."),
                    self._duplicate_selection,
                ),
            )
        ):
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(handler)
            grid.addWidget(btn, 0, column)
            self._transform_buttons.append(btn)

        return widget

    def _build_global_group(self):
        group = self._make_collapsible(
            QGroupBox("Spacing & Alignment"), expanded=False
        )
        self.global_group = group
        form = QFormLayout(group)

        self.letter_spacing_spin = QSpinBox()
        self.letter_spacing_spin.setRange(0, LETTER_SPACING_MAX)
        self.letter_spacing_spin.setValue(self.letter_spacing)
        self.letter_spacing_spin.setToolTip(
            "Extra gap between characters within each line (pixels)."
        )
        self.letter_spacing_spin.valueChanged.connect(self._on_layout_changed)
        form.addRow("Letter spacing:", self.letter_spacing_spin)

        self.line_spacing_spin = QSpinBox()
        self.line_spacing_spin.setRange(0, LINE_SPACING_MAX)
        self.line_spacing_spin.setValue(self.line_spacing)
        self.line_spacing_spin.setToolTip("Gap between lines (pixels).")
        self.line_spacing_spin.valueChanged.connect(self._on_layout_changed)
        form.addRow("Line spacing:", self.line_spacing_spin)

        self.baseline_combo = QComboBox()
        self.baseline_combo.addItems(BASELINES)
        self.baseline_combo.setToolTip(
            "How characters sit vertically inside each line."
        )
        self.baseline_combo.currentTextChanged.connect(self._on_layout_changed)
        form.addRow("Vertical align:", self.baseline_combo)

        self.align_combo = QComboBox()
        self.align_combo.addItems(ALIGNMENTS)
        self.align_combo.setToolTip("Where each line sits horizontally on the canvas.")
        self.align_combo.currentTextChanged.connect(self._on_layout_changed)
        form.addRow("Line align:", self.align_combo)

        self.snap_enable_cb = QCheckBox("Enabled")
        self.snap_enable_cb.setChecked(True)
        self.snap_enable_cb.setToolTip(
            "Snap characters to other characters' edges and centres, to "
            "even spacing between two characters, to the canvas edges "
            "and centre, and to the grid below (lowest priority). Hold "
            "Alt or Ctrl while dragging to suspend snapping temporarily."
        )
        self.snap_enable_cb.toggled.connect(self._on_snapping_toggled)
        form.addRow("Snapping:", self.snap_enable_cb)

        self.snap_spin = QSpinBox()
        self.snap_spin.setRange(0, SNAP_GRID_MAX)
        self.snap_spin.setValue(SNAP_GRID_DEFAULT)
        self.snap_spin.setSpecialValueText("Off")
        self.snap_spin.setToolTip(
            "Fallback grid used when no character, edge or centre is "
            "nearby. 0 disables grid snapping (smart snapping to other "
            "characters still works)."
        )
        self.snap_spin.valueChanged.connect(self._on_snap_changed)
        form.addRow("Grid size:", self.snap_spin)

        canvas_w, canvas_h = (round(value) for value in self.canvas_size)
        self.canvas_w_spin = QSpinBox()
        self.canvas_w_spin.setRange(1, 10000)
        self.canvas_w_spin.setValue(canvas_w)
        self.canvas_w_spin.setToolTip("Image width in pixels.")
        self.canvas_h_spin = QSpinBox()
        self.canvas_h_spin.setRange(1, 10000)
        self.canvas_h_spin.setValue(canvas_h)
        self.canvas_h_spin.setToolTip("Image height in pixels.")
        apply_canvas_btn = QPushButton("Apply")
        apply_canvas_btn.setToolTip("Resize the image to the given size.")
        apply_canvas_btn.clicked.connect(self._apply_canvas_size)
        crop_btn = QPushButton("Crop to Content")
        crop_btn.setToolTip(
            "Shrink the image so it tightly fits the visible "
            "characters, cutting empty margins."
        )
        crop_btn.clicked.connect(self._crop_to_content)
        canvas_row = QHBoxLayout()
        canvas_row.setSpacing(4)
        canvas_row.addWidget(self.canvas_w_spin, 1)
        canvas_row.addWidget(QLabel("x"))
        canvas_row.addWidget(self.canvas_h_spin, 1)
        canvas_row.addWidget(apply_canvas_btn)
        canvas_row.addWidget(crop_btn)
        form.addRow("Canvas size:", canvas_row)

        self._set_group_children_visible(group, group.isChecked())
        return group

    def _install_shortcuts(self):
        undo_sc = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_sc.activated.connect(self._undo)
        redo_sc = QShortcut(QKeySequence.StandardKey.Redo, self)
        redo_sc.activated.connect(self._redo)
        save_sc = QShortcut(QKeySequence.StandardKey.Save, self)
        save_sc.activated.connect(self.export_image)
        del_sc = QShortcut(QKeySequence.StandardKey.Delete, self.view)
        del_sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        del_sc.activated.connect(self._delete_selected)

        zoom_in_sc = QShortcut(QKeySequence("Ctrl+="), self)
        zoom_in_sc.activated.connect(self.view.zoom_in)
        zoom_out_sc = QShortcut(QKeySequence("Ctrl+-"), self)
        zoom_out_sc.activated.connect(self.view.zoom_out)
        fit_sc = QShortcut(QKeySequence("Ctrl+0"), self)
        fit_sc.activated.connect(self._fit_view)
        actual_sc = QShortcut(QKeySequence("Ctrl+1"), self)
        actual_sc.activated.connect(self._zoom_actual)
        escape_sc = QShortcut(QKeySequence("Escape"), self.view)
        escape_sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        escape_sc.activated.connect(self._escape_pressed)

        select_all_sc = QShortcut(QKeySequence.StandardKey.SelectAll, self)
        select_all_sc.activated.connect(self._select_all)
        duplicate_sc = QShortcut(QKeySequence("Ctrl+D"), self)
        duplicate_sc.activated.connect(self._duplicate_selection)

        for key, (ddx, ddy) in (
            ("Left", (-NUDGE_STEP, 0)),
            ("Right", (NUDGE_STEP, 0)),
            ("Up", (0, -NUDGE_STEP)),
            ("Down", (0, NUDGE_STEP)),
            ("Shift+Left", (-NUDGE_BIG_STEP, 0)),
            ("Shift+Right", (NUDGE_BIG_STEP, 0)),
            ("Shift+Up", (0, -NUDGE_BIG_STEP)),
            ("Shift+Down", (0, NUDGE_BIG_STEP)),
        ):
            sc = QShortcut(QKeySequence(key), self.view)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(lambda ddx=ddx, ddy=ddy: self._nudge(ddx, ddy))

    def _nudge(self, dx, dy):
        if self._in_canvas_gesture():
            return
        selected = [item for item in self._selected() if item.isVisible()]
        if not selected:
            return
        before = self._snapshot_selected()
        for item in selected:
            item.dx += dx
            item.dy += dy
            item._place()
        self._push(before)
        self._sync_panel()

    def _select_all(self):
        for item in self.items:
            if item.isVisible():
                item.setSelected(True)

    def _escape_pressed(self):
        if self.scene.cancel_marquee():
            return
        selected = self._selected()
        if selected:
            for item in selected:
                item.setSelected(False)
        else:
            self.reject()

    def _flip_selection(self, axis):
        selected = [item for item in self._selected() if item.isVisible()]
        if not selected:
            return
        before = self._snapshot_selected()
        for item in selected:
            if axis == "h":
                item.flip_h = not item.flip_h
            else:
                item.flip_v = not item.flip_v
            item.update_pixmap()
        self._push(before)
        self._sync_panel()

    def _rotate_selection_90(self, turns):
        selected = [item for item in self._selected() if item.isVisible()]
        if not selected:
            return
        before = self._snapshot_selected()
        span = ROTATION_MAX - ROTATION_MIN
        for item in selected:
            item.rotation = (
                item.rotation + 90 * turns - ROTATION_MIN
            ) % span + ROTATION_MIN
            item.update_pixmap()
        self._push(before)
        self._sync_panel()

    def _duplicate_selection(self):
        if self._in_canvas_gesture():
            return
        selected = [item for item in self._selected() if item.isVisible()]
        if not selected:
            return
        before = self._capture_all()
        for item in selected:
            ni = CharItem(
                item.char,
                item.sprite,
                item.base_x + DUPLICATE_OFFSET,
                item.base_y + DUPLICATE_OFFSET,
                self._sprite_provider,
                self._render_dispatcher,
                item.color_variant,
            )
            ni.layout_anchored = False
            ni.dx = item.dx
            ni.dy = item.dy
            ni.scale_pct = item.scale_pct
            ni.rotation = item.rotation
            ni.rotation_quality = item.rotation_quality
            ni.stretch_x = item.stretch_x
            ni.stretch_y = item.stretch_y
            ni.flip_h = item.flip_h
            ni.flip_v = item.flip_v
            ni.opacity = item.opacity
            ni.hue_shift = item.hue_shift
            ni.setZValue(item.zValue())
            self.scene.addItem(ni)
            self.items.append(ni)
            ni.update_pixmap()
            ni.setVisible(False)
            before[ni] = ni.capture_state()
            ni.setVisible(True)
            item.setSelected(False)
            ni.setSelected(True)
        self._push(before)
        self._sync_panel()

    def _reorder_selection(self, to_front):
        selected = [item for item in self._selected() if item.isVisible()]
        if not selected:
            return
        before = self._snapshot_selected()
        zs = [item.zValue() for item in self.items]
        if to_front:
            target = max(zs) if zs else 0
            for item in selected:
                target += 1
                item.setZValue(target)
        else:
            target = min(zs) if zs else 0
            for item in selected:
                target -= 1
                item.setZValue(target)
        self._push(before)
        self._sync_panel()

    def _delete_selected(self):
        if self._in_canvas_gesture():
            return
        selected = self._selected()
        if selected:
            self._delete_items(selected)

    def _undo(self):
        if self._in_canvas_gesture() or self._in_slider_gesture():
            return
        if not self.undo_stack.undo(self._apply_all):
            return
        self._refresh_dirty_state()
        self._sync_panel()
        self._update_status_counts()
        self._update_scene_rect()

    def _redo(self):
        if self._in_canvas_gesture() or self._in_slider_gesture():
            return
        if not self.undo_stack.redo(self._apply_all):
            return
        self._refresh_dirty_state()
        self._sync_panel()
        self._update_status_counts()
        self._update_scene_rect()

    def _refresh_dirty_state(self):
        if self._exported_signature is None:
            initial = self._initial_signature
            visible = {
                item: state
                for item, state in self._capture_all().items()
                if item in initial
            }
            self._dirty = visible != initial
            return
        capture = self._capture_all()
        exported_items = set(self._exported_signature)
        visible = {
            item: state for item, state in capture.items() if item in exported_items
        }
        self._dirty = visible != self._exported_signature

    def _connect_selection(self):
        self.scene.selectionChanged.connect(self._sync_panel)
        self._drag_before = None
        self._drag_start_pos = {}
        self.scene.drag_started.connect(self._on_drag_started)
        self.scene.drag_finished.connect(self._on_drag_finished)
        self.view.zoom_changed.connect(self._on_zoom_changed)
        QApplication.instance().paletteChanged.connect(self._on_palette_changed)

    def _on_palette_changed(self, _palette):
        self._apply_chrome_style()
        self.scene._apply_band_palette()
        self.scene.invalidate(
            self.scene.sceneRect(), QGraphicsScene.SceneLayer.BackgroundLayer
        )

    def _on_zoom_changed(self, _factor):
        self.zoom_entry.set_zoom(self.view.transform().m11())
        self.scene.transform_box.refresh()

    def _selected(self):
        return self.scene.ordered_selection()

    def _snapshot_selected(self):
        return {item: item.capture_state() for item in self._selected()}

    def _on_drag_started(self):
        self._drag_before = self._capture_all()
        self._drag_start_pos = {item: item.pos() for item in self.items}
        self.scene._snap_start = dict(self._drag_start_pos)
        self.scene.begin_snap()

    def _on_drag_finished(self):
        if self._drag_before is not None:
            for item, start in self._drag_start_pos.items():
                delta_x = round(item.pos().x() - start.x())
                delta_y = round(item.pos().y() - start.y())
                if delta_x or delta_y:
                    item.dx += delta_x
                    item.dy += delta_y
                    item._place()
            after = self._capture_all()
            changed = {
                item: self._drag_before[item]
                for item in after
                if after[item] != self._drag_before[item]
            }
            if changed:
                before_changed = {item: self._drag_before[item] for item in changed}
                after_changed = {item: after[item] for item in changed}
                layout = self._layout_params()
                self.undo_stack.push(
                    (before_changed, self.canvas_size, layout),
                    (after_changed, self.canvas_size, layout),
                )
                self._dirty = True
                self._update_status_counts()
            self._drag_before = None
            self._drag_start_pos = None
            self.scene.end_snap()
        self._sync_panel()

    def _sync_panel(self):
        selected = self._selected()
        if selected:
            names = ", ".join(repr(item.char) for item in selected[:20])
            if len(selected) > 20:
                names += f" … (+{len(selected) - 20} more)"
            self.selection_label.setText(names)
        else:
            self.selection_label.setText("Nothing selected")

        for widget in (
            self.offset_x_spin,
            self.offset_y_spin,
            self.scale_slider,
            self.scale_spin,
            self.rotation_slider,
            self.rotation_spin,
            self.stretch_x_spin,
            self.stretch_y_spin,
            self.opacity_slider,
            self.opacity_spin,
            self.hue_slider,
            self.hue_spin,
            self.item_color_combo,
        ):
            widget.blockSignals(True)
        try:
            if selected:
                first = selected[0]
                self.item_color_combo.setCurrentText(
                    first.color_variant or self.params["color"]
                )
                self._set_spin_clamped(self.offset_x_spin, round(first.dx))
                self._set_spin_clamped(self.offset_y_spin, round(first.dy))
                self.scale_slider.setValue(first.scale_pct)
                self.scale_spin.setValue(first.scale_pct)
                self.rotation_slider.setValue(first.rotation)
                self.rotation_spin.setValue(first.rotation)
                self.stretch_x_spin.setValue(first.stretch_x)
                self.stretch_y_spin.setValue(first.stretch_y)
                self.opacity_slider.setValue(first.opacity)
                self.opacity_spin.setValue(first.opacity)
                self.hue_slider.setValue(first.hue_shift)
                self.hue_spin.setValue(first.hue_shift)
        finally:
            for widget in (
                self.offset_x_spin,
                self.offset_y_spin,
                self.scale_slider,
                self.scale_spin,
                self.rotation_slider,
                self.rotation_spin,
                self.stretch_x_spin,
                self.stretch_y_spin,
                self.opacity_slider,
                self.opacity_spin,
                self.hue_slider,
                self.hue_spin,
                self.item_color_combo,
            ):
                widget.blockSignals(False)

        has_selection = bool(selected)
        for widget in (
            self.offset_x_spin,
            self.offset_y_spin,
            self.scale_slider,
            self.scale_spin,
            self.rotation_slider,
            self.rotation_spin,
            self.stretch_x_spin,
            self.stretch_y_spin,
            self.opacity_slider,
            self.opacity_spin,
            self.hue_slider,
            self.hue_spin,
            self.item_color_combo,
            self.rotation_quality,
        ):
            widget.setEnabled(has_selection)
        for btn in self._transform_buttons:
            btn.setEnabled(has_selection)

        self._update_status_counts()
        self._update_scene_rect()
        self.scene.transform_box.refresh()

    def _apply_char_property(self, attr, value, push=True):
        selected = [item for item in self._selected() if item.isVisible()]
        if not selected:
            return
        before = self._snapshot_selected()
        if attr == "scale_pct":
            self._scale_selection(selected, value)
        else:
            for item in selected:
                setattr(item, attr, value)
                item.update_pixmap()
        if push:
            self._push(before)
        if self._in_slider_gesture():
            self._update_scene_rect()
            self._update_status_counts()
            self.scene.transform_box.refresh()
        else:
            self._sync_panel()

    def _scale_selection(self, items, value):
        rects = {item: self.scene._item_scene_rect(item) for item in items}
        union = rects[items[0]]
        for rect in rects.values():
            union = union.united(rect)
        cx, cy = union.center().x(), union.center().y()
        for item in items:
            old_scale = item.scale_pct or CHAR_SCALE_DEFAULT
            factor = value / old_scale
            rect = rects[item]
            new_cx = cx + (rect.center().x() - cx) * factor
            new_cy = cy + (rect.center().y() - cy) * factor
            item.scale_pct = value
            cached = item._pix_cache.get(item._cache_key())
            w = h = None
            if cached is not None:
                w, h = cached.size
            elif item.rotation % 90 == 0:
                w, h = unrotated_render_size(
                    item.sprite, value, item.stretch_x, item.stretch_y
                )
                if item.rotation % 180:
                    w, h = h, w
            if w is None:
                w = rect.width() * factor
                h = rect.height() * factor
                item._pending_center = QPointF(new_cx, new_cy)
            else:
                item._pending_center = None
            item.dx = round(new_cx - w / 2 - item.base_x)
            item.dy = round(new_cy - h / 2 - item.base_y)
            item.request_render()

    def _on_scale_slider_changed(self, value):
        snapped = self._snap_scale_value(value)
        for widget in (self.scale_slider, self.scale_spin):
            widget.blockSignals(True)
            widget.setValue(snapped)
            widget.blockSignals(False)
        self._apply_char_property(
            "scale_pct", snapped, push=not self._in_slider_gesture()
        )

    def _on_scale_spin_changed(self, value):
        self.scale_slider.blockSignals(True)
        self.scale_slider.setValue(value)
        self.scale_slider.blockSignals(False)
        self._apply_char_property("scale_pct", value)

    def _on_rotation_slider_changed(self, value):
        snapped = self._snap_rotation_value(value)
        for widget in (self.rotation_slider, self.rotation_spin):
            widget.blockSignals(True)
            widget.setValue(snapped)
            widget.blockSignals(False)
        self._apply_char_property(
            "rotation", snapped, push=not self._in_slider_gesture()
        )

    def _on_rotation_spin_changed(self, value):
        self.rotation_slider.blockSignals(True)
        self.rotation_slider.setValue(value)
        self.rotation_slider.blockSignals(False)
        self._apply_char_property("rotation", value)

    def _on_opacity_slider_changed(self, value):
        for widget in (self.opacity_slider, self.opacity_spin):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self._apply_char_property(
            "opacity", value, push=not self._in_slider_gesture()
        )

    def _on_opacity_spin_changed(self, value):
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(value)
        self.opacity_slider.blockSignals(False)
        self._apply_char_property("opacity", value)

    def _on_hue_slider_changed(self, value):
        for widget in (self.hue_slider, self.hue_spin):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self._apply_char_property(
            "hue_shift", value, push=not self._in_slider_gesture()
        )

    def _on_hue_spin_changed(self, value):
        self.hue_slider.blockSignals(True)
        self.hue_slider.setValue(value)
        self.hue_slider.blockSignals(False)
        self._apply_char_property("hue_shift", value)

    def _set_spin_clamped(self, spin, value):
        spin.setValue(max(spin.minimum(), min(spin.maximum(), value)))

    def _in_slider_gesture(self):
        return getattr(self, "_slider_undo_before", None) is not None

    def _in_canvas_gesture(self):
        return (
            self._drag_before is not None
            or self.scene.transform_box._gesture is not None
        )

    def _begin_slider_undo(self):
        snapshot = self._snapshot_selected()
        self._slider_undo_before = snapshot or None

    def _end_slider_undo(self):
        before = getattr(self, "_slider_undo_before", None)
        self._slider_undo_before = None
        if before:
            self._push(before)
            for item in before:
                item.prune_cache()
            self._update_status_counts()

    def _snap_rotation_value(self, value, shift_held=None):
        if shift_held is None:
            shift_held = bool(QApplication.queryKeyboardModifiers() & Qt.ShiftModifier)
        if not shift_held:
            return value
        snapped = round(value / ROTATE_SNAP_STEP) * ROTATE_SNAP_STEP
        return max(ROTATION_MIN, min(ROTATION_MAX, snapped))

    def _snap_scale_value(self, value):
        if not self.scene.snapping_enabled:
            return value
        candidates = {CHAR_SCALE_DEFAULT}
        selected = {id(item) for item in self._selected()}
        for item in self.items:
            if item.isVisible() and id(item) not in selected:
                candidates.add(item.scale_pct)
        for candidate in sorted(candidates):
            if abs(value - candidate) <= SCALE_SNAP_TOLERANCE_PCT:
                return candidate
        return value

    def _center_selection_on_canvas(self):
        items = [item for item in self._selected() if item.isVisible()]
        if not items:
            return
        before = self._snapshot_selected()
        union = self.scene._item_scene_rect(items[0])
        for item in items[1:]:
            union = union.united(self.scene._item_scene_rect(item))
        canvas_w, canvas_h = self.canvas_size
        ddx = round(canvas_w / 2 - union.center().x())
        ddy = round(canvas_h / 2 - union.center().y())
        if not ddx and not ddy:
            return
        for item in items:
            item.dx += ddx
            item.dy += ddy
            item._place()
        self._push(before)
        self._sync_panel()

    def _reset_to_original(self):
        items = [
            item
            for item in self._selected()
            if item.isVisible() and item in self._initial_signature
        ]
        if not items:
            return
        before = self._snapshot_selected()
        for item in items:
            item.apply_state(self._initial_signature[item])
        self._push(before)
        self._sync_panel()

    def _apply_offset(self, dx=None, dy=None):
        if self._drag_before is not None:
            return
        selected = [item for item in self._selected() if item.isVisible()]
        if not selected:
            return
        before = self._snapshot_selected()
        for item in selected:
            if dx is not None:
                item.dx = dx
            if dy is not None:
                item.dy = dy
            item._place()
        self._push(before)
        self._sync_panel()

    def _sprite_for(self, char, color_variant=None):
        color = color_variant or self.params["color"]
        cache_key = (char, color)
        if cache_key not in self._char_cache:
            paths = self._color_paths.get(color)
            if paths is None:
                paths = get_font_paths(self.params["font"], color)
                self._color_paths[color] = paths
            self._char_cache[cache_key] = create_character_image(char, paths)
        return self._char_cache[cache_key]

    def _on_font_color_changed(self, color):
        self.params["color"] = color
        if color not in self._color_paths:
            self._color_paths[color] = get_font_paths(self.params["font"], color)
        self.font_paths = self._color_paths[color]
        for item in self.items:
            item.color_variant = color
            item.set_character(item.char)
            item.update_pixmap()
        self._sync_panel()

    def _on_item_color_changed(self, color):
        selected = [item for item in self._selected() if item.isVisible()]
        if not selected:
            return
        before = self._snapshot_selected()
        if color not in self._color_paths:
            self._color_paths[color] = get_font_paths(self.params["font"], color)
        for item in selected:
            if item.color_variant == color:
                continue
            item.color_variant = color
            item.set_character(item.char)
            item.update_pixmap()
        self._push(before)
        self._sync_panel()

    def _edit_character(self, item):
        new_text, ok = QInputDialog.getText(
            self, "Edit Character", f"Replace '{item.char}' with:", text=item.char
        )
        if not ok:
            return
        new_text = new_text.strip()
        if not new_text or new_text == item.char:
            return

        chars = []
        unsupported = set()
        for ch in new_text:
            if ch.isspace():
                chars.append(ch)
                continue
            if self.valid_chars and ch not in self.valid_chars:
                if ch.upper() in self.valid_chars:
                    ch = ch.upper()
                else:
                    unsupported.add(ch)
                    continue
            chars.append(ch)

        if unsupported:
            self._warn_unsupported_characters(sorted(unsupported))
            return
        if not chars:
            return

        if not self._confirm_replace(item.char, "".join(chars)):
            return
        try:
            if len(chars) == 1:
                before = {item: item.capture_state()}
                item.set_character(chars[0])
                item.update_pixmap()
            else:
                before = self._replace_with_string(item, chars)
        except FileNotFoundError as e:
            QMessageBox.warning(self, "Missing Asset", str(e))
            return
        self._push(before)
        self._sync_panel()

    def _warn_unsupported_characters(self, characters):
        box = QMessageBox(self)
        box.setWindowTitle("Characters Not Available")
        box.setText(
            "These characters aren't available in the selected font:\n\n"
            + " ".join(characters)
            + "\n\nPick different characters, or check what the font supports."
        )
        view_button = box.addButton("View Supported Characters", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is view_button:
            open_supported_characters(self)

    def _replace_with_string(self, item, chars):
        sprites = [self._sprite_for(c) for c in chars]
        before = {item: item.capture_state()}
        item_rect = self.scene._item_scene_rect(item)
        x = item_rect.left()
        bottom = item_rect.bottom()
        for ch, sprite in zip(chars, sprites):
            rendered = render_character(
                sprite,
                item.scale_pct,
                item.rotation,
                item.rotation_quality,
                item.stretch_x,
                item.stretch_y,
                item.flip_h,
                item.flip_v,
            )
            if ch.isspace():
                x += rendered.width + self.letter_spacing
                continue
            ni = CharItem(
                ch,
                sprite,
                x,
                bottom - rendered.height,
                self._sprite_provider,
                self._render_dispatcher,
                item.color_variant,
            )
            ni.layout_anchored = False
            ni.scale_pct = item.scale_pct
            ni.rotation = item.rotation
            ni.rotation_quality = item.rotation_quality
            ni.stretch_x = item.stretch_x
            ni.stretch_y = item.stretch_y
            ni.flip_h = item.flip_h
            ni.flip_v = item.flip_v
            ni.opacity = item.opacity
            ni.hue_shift = item.hue_shift
            self.scene.addItem(ni)
            self.items.append(ni)
            ni.setVisible(False)
            before[ni] = ni.capture_state()
            ni.setVisible(True)
            ni.update_pixmap()
            x += rendered.width + self.letter_spacing
        item.setVisible(False)
        item.setSelected(False)
        return before

    def _confirm_replace(self, old, new):
        if load_config("skip_char_replace_confirm", fallback=False):
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Replace Character")
        box.setText(f"Replace '{old}' with '{new}'?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        cb = QCheckBox("Don't ask me again")
        box.setCheckBox(cb)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return False
        if cb.isChecked():
            save_config("skip_char_replace_confirm", True)
        return True

    def _reset_item(self, item, attr):
        before = {item: item.capture_state()}
        if attr == "scale_pct":
            self._scale_selection([item], CHAR_SCALE_DEFAULT)
        else:
            item.rotation = 0
            item.update_pixmap()
        self._push(before)
        self._sync_panel()

    def _delete_items(self, items):
        before = {item: item.capture_state() for item in items}
        for item in items:
            item.setVisible(False)
            item.setSelected(False)
        self._push(before)
        self._sync_panel()

    def _layout_params(self):
        return (
            self.letter_spacing,
            self.line_spacing,
            self.baseline,
            self.align,
        )

    def _push(
        self,
        before,
        canvas_before=None,
        canvas_after=None,
        layout_before=None,
        layout_after=None,
    ):
        after = {item: item.capture_state() for item in before}
        changed = any(after[item] != state for item, state in before.items())
        canvas_before = self.canvas_size if canvas_before is None else canvas_before
        canvas_after = self.canvas_size if canvas_after is None else canvas_after
        layout_before = (
            self._layout_params() if layout_before is None else layout_before
        )
        layout_after = self._layout_params() if layout_after is None else layout_after
        if canvas_before != canvas_after or layout_before != layout_after:
            changed = True
        if changed:
            self.undo_stack.push(
                (before, canvas_before, layout_before),
                (after, canvas_after, layout_after),
            )
            if self._exported_signature is None:
                self._dirty = True
            else:
                self._refresh_dirty_state()
            self._update_status_counts()

    def _apply_all(self, entry):
        snapshot, canvas, layout = entry
        if layout != self._layout_params():
            (self.letter_spacing, self.line_spacing, self.baseline, self.align) = layout
            for widget, value in (
                (self.letter_spacing_spin, self.letter_spacing),
                (self.line_spacing_spin, self.line_spacing),
                (self.baseline_combo, self.baseline.capitalize()),
                (self.align_combo, self.align.capitalize()),
            ):
                widget.blockSignals(True)
                if hasattr(widget, "setValue"):
                    widget.setValue(value)
                else:
                    widget.setCurrentText(value)
                widget.blockSignals(False)
        if canvas != self.canvas_size:
            self._set_canvas_size(*canvas)
        for item, state in snapshot.items():
            item.apply_state(state)
            if not state[6] and item.isSelected():
                item.setSelected(False)

    def _confirm_discard(self):
        if not self._dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved Edits")
        box.setText("You have unsaved edits. What would you like to do?")
        save_btn = box.addButton("Save Image", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = box.addButton(
            "Discard Edits", QMessageBox.ButtonRole.DestructiveRole
        )
        keep_btn = box.addButton("Keep Editing", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep_btn)
        box.exec()
        if box.clickedButton() is save_btn:
            return self.export_image()
        if box.clickedButton() is discard_btn:
            self._dirty = False
            self.status_dirty_label.setText("")
            return True
        return False

    def reject(self):
        if self._confirm_discard():
            self._render_dispatcher.shutdown()
            super().reject()

    def closeEvent(self, event):
        if self._confirm_discard():
            self._render_dispatcher.shutdown()
            super().closeEvent(event)
        else:
            event.ignore()

    def _capture_all(self):
        return {item: item.capture_state() for item in self.items}

    def _on_layout_changed(self, _=None):
        layout_before = self._layout_params()
        self.letter_spacing = self.letter_spacing_spin.value()
        self.line_spacing = self.line_spacing_spin.value()
        self.baseline = self.baseline_combo.currentText().lower()
        self.align = self.align_combo.currentText().lower()

        canvas_before = self.canvas_size
        before = self._capture_all()
        placements, (canvas_w, canvas_h) = layout_characters(
            self.params["text"],
            self.font_paths,
            char_images=self._char_cache,
            letter_spacing=self.letter_spacing,
            line_spacing=self.line_spacing,
            baseline=self.baseline,
            align=self.align,
        )
        self._set_canvas_size(canvas_w, canvas_h)
        layout_items = [it for it in self.items if it.layout_anchored]
        for item, (_char, _sprite, x, y) in zip(layout_items, placements):
            item.set_base(x, y)
        self._update_scene_rect()
        self._push(
            before,
            canvas_before=canvas_before,
            canvas_after=(canvas_w, canvas_h),
            layout_before=layout_before,
            layout_after=self._layout_params(),
        )
        self._update_status_counts()

    def _set_canvas_size(self, width, height):
        self.canvas_size = (width, height)
        self.canvas_rect.setRect(0, 0, width, height)
        for spin, value in (
            (self.canvas_w_spin, width),
            (self.canvas_h_spin, height),
        ):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.scene.invalidate_bounds()
        self._update_scene_rect()
        self._update_status_counts()

    def _apply_canvas_size(self):
        width = self.canvas_w_spin.value()
        height = self.canvas_h_spin.value()
        if (width, height) == (round(self.canvas_size[0]), round(self.canvas_size[1])):
            return
        before = self._capture_all()
        canvas_before = tuple(self.canvas_size)
        self._set_canvas_size(width, height)
        self._push(
            before,
            canvas_before=canvas_before,
            canvas_after=(width, height),
        )

    def _crop_to_content(self):
        items = [item for item in self.items if item.isVisible()]
        if not items:
            QMessageBox.information(
                self,
                "Nothing to Crop To",
                "Every character is hidden, so there is no content to "
                "crop the image to.",
            )
            return
        union = self.scene._item_scene_rect(items[0])
        for item in items[1:]:
            union = union.united(self.scene._item_scene_rect(item))
        left = max(0, floor(union.left()))
        top = max(0, floor(union.top()))
        width = max(1, ceil(union.right()) - left)
        height = max(1, ceil(union.bottom()) - top)
        canvas_before = tuple(self.canvas_size)
        if (width, height, left, top) == (
            round(canvas_before[0]),
            round(canvas_before[1]),
            0,
            0,
        ):
            return
        before = self._capture_all()
        for item in self.items:
            item.base_x -= left
            item.base_y -= top
            item._place()
        self._set_canvas_size(width, height)
        self._push(
            before,
            canvas_before=canvas_before,
            canvas_after=(width, height),
        )

    def _on_snap_changed(self, value):
        self.snap_grid = value
        self.scene.snap_size = value
        self.scene.invalidate(
            self.scene.sceneRect(), QGraphicsScene.SceneLayer.BackgroundLayer
        )

    def _on_rotation_quality_changed(self, quality):
        for item in self.items:
            if item.rotation_quality != quality:
                item.rotation_quality = quality
                item.prune_cache()
                if item.rotation:
                    item.update_pixmap()

    def _on_snapping_toggled(self, checked):
        self.scene.snapping_enabled = checked
        self.snap_spin.setEnabled(checked)
        self.scene.invalidate(
            self.scene.sceneRect(), QGraphicsScene.SceneLayer.BackgroundLayer
        )

    def _has_visible_items(self):
        return any(item.isVisible() for item in self.items)

    def _prompt_save_location(self):
        if load_config("skip_location_prompt", fallback=False):
            return
        box = QMessageBox(self)
        box.setWindowTitle("Welcome to MetalSlugFontReborn!")
        box.setText(
            "Your images will be saved to your Desktop by default.\n\n"
            "Would you like to choose a different folder?"
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        remember = QCheckBox("Don't ask me again")
        box.setCheckBox(remember)
        if box.exec() == QMessageBox.StandardButton.Yes:
            path = QFileDialog.getExistingDirectory(
                self, "Choose Save Folder", str(self.params["save_path"])
            )
            if path:
                self.params["save_path"] = path
        if remember.isChecked():
            save_config("skip_location_prompt", True)

    def _warn_nothing_to_export(self):
        QMessageBox.warning(
            self,
            "Nothing to Export",
            "All characters are hidden. Make at least one character "
            "visible before saving the image.",
        )

    def export_image(self):
        if self._in_canvas_gesture():
            return False
        if not self._has_visible_items():
            self._warn_nothing_to_export()
            return False
        self._prompt_save_location()
        try:
            summary = self._export_image()
        except Image.DecompressionBombError as e:
            QMessageBox.critical(
                self,
                "Export Too Large",
                f"The edited composition is too large to export:\n{e}",
            )
            return False
        except OSError as e:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"The image could not be saved:\n{e}\n\n"
                "Check that the save location exists and is writable.",
            )
            return False
        if not summary:
            return False
        self._dirty = False
        self._exported_signature = self._capture_all()
        self.status_dirty_label.setText(summary)
        return True

    def _export_image(self):
        start = time()
        filename = generate_filename(self.params["text"])

        placed = []
        min_x = min_y = None
        max_x = max_y = None
        for item in sorted(self.items, key=lambda entry: entry.zValue()):
            if not item.isVisible():
                continue
            key = item._cache_key()
            rendered = item._pix_cache.get(key)
            if rendered is None:
                rendered = render_character(
                    item.tinted_sprite(compute=True),
                    item.scale_pct,
                    item.rotation,
                    item.rotation_quality,
                    item.stretch_x,
                    item.stretch_y,
                    item.flip_h,
                    item.flip_v,
                    item.opacity,
                )
                item._pix_cache[key] = rendered
            x = round(item.base_x + item.dx)
            y = round(item.base_y + item.dy)
            placed.append((rendered, x, y))
            if min_x is None or x < min_x:
                min_x = x
            if min_y is None or y < min_y:
                min_y = y
            if max_x is None or x + rendered.width > max_x:
                max_x = x + rendered.width
            if max_y is None or y + rendered.height > max_y:
                max_y = y + rendered.height

        if not placed:
            canvas = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        else:
            width = max_x - min_x
            height = max_y - min_y
            scale = self.params.get("scale", 1) or 1
            if width * height * scale * scale > Image.MAX_IMAGE_PIXELS:
                QMessageBox.warning(
                    self,
                    "Export Too Large",
                    f"The composition spans {width} x {height} pixels "
                    f"({width * scale} x {height * scale} after scaling), "
                    "which is beyond what an image may hold. Move the "
                    "characters closer together or lower the scale.",
                )
                return ""
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            for pil_img, x, y in placed:
                canvas.alpha_composite(pil_img, (x - min_x, y - min_y))
            bbox = canvas.getbbox()
            if bbox:
                canvas = canvas.crop(bbox)

        scale = self.params.get("scale", 1)
        if scale and scale != 1:
            canvas = canvas.resize(
                (
                    max(1, canvas.width * scale),
                    max(1, canvas.height * scale),
                ),
                Image.Resampling.NEAREST,
            )

        out_path = Path(self.params["save_path"]) / filename
        part_path = out_path.with_name(f"{out_path.stem}.part.png")
        try:
            canvas.save(part_path, compress_level=self.params.get("compress_level", 6))
            os.replace(part_path, out_path)
        finally:
            part_path.unlink(missing_ok=True)

        elapsed = time() - start
        size = readable_size(out_path.stat().st_size)
        self.status_dirty_label.setToolTip(f"Saved to {out_path}")
        self.export_btn.setText("Saved")
        QTimer.singleShot(2000, lambda: self.export_btn.setText("Save Image"))
        return f"Saved: {canvas.width} x {canvas.height} px, {size}, {elapsed:.2f}s"
