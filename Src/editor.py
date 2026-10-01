import os
from enum import IntEnum
from math import atan2, ceil, degrees, floor
from pathlib import Path
from time import time

from PIL import Image, ImageQt
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeySequence,
    QPalette,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
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
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from image_generation import (
    create_character_image,
    generate_filename,
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
SCENE_PADDING = 60

ZOOM_STEP = 1.15
ZOOM_MIN_FACTOR = 0.1
ZOOM_MAX_FACTOR = 8.0

CHAR_SCALE_MIN = 10
CHAR_SCALE_MAX = 400
CHAR_SCALE_DEFAULT = 100

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


def render_character(
    sprite,
    scale_pct=CHAR_SCALE_DEFAULT,
    rotation=0,
    quality=QUALITY_FAST_ROTSPRITE,
    stretch_x=CHAR_SCALE_DEFAULT,
    stretch_y=CHAR_SCALE_DEFAULT,
    flip_h=False,
    flip_v=False,
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
    if rotation:
        if rotation % 90 == 0:
            img = img.rotate(-rotation, expand=True)
        else:
            img = rotsprite_rotate(img, rotation, quality)
    return img


class CharItem(QGraphicsPixmapItem):
    def __init__(self, char, sprite, base_x, base_y, sprite_provider):
        super().__init__()
        self.char = char
        self.sprite = sprite.convert("RGBA")
        self._sprite_provider = sprite_provider
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
        self._pix_cache = {}
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
        )

    def apply_state(self, state):
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
        ) = state
        if char != self.char:
            self.set_character(char)
        self.setVisible(visible)
        self.update_pixmap()

    def set_character(self, char):
        self.char = char
        self.sprite = self._sprite_provider(char).convert("RGBA")
        self._pix_cache.clear()

    def _cache_key(self):
        return (
            self.scale_pct,
            self.rotation,
            self.stretch_x,
            self.stretch_y,
            self.flip_h,
            self.flip_v,
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
            rendered = render_character(
                self.sprite,
                self.scale_pct,
                self.rotation,
                self.rotation_quality,
                self.stretch_x,
                self.stretch_y,
                self.flip_h,
                self.flip_v,
            )
            if len(self._pix_cache) >= PIX_CACHE_MAX_ENTRIES:
                self._pix_cache.clear()
            self._pix_cache[key] = rendered
        qimage = ImageQt.ImageQt(rendered)
        self.setPixmap(QPixmap.fromImage(qimage))
        self._place()
        scene = self.scene()
        if scene is not None and scene.parent_dialog is not None:
            scene.transform_box.refresh()

    def _place(self):
        self.setPos(self.base_x + self.dx, self.base_y + self.dy)

    def set_base(self, x, y):
        self.base_x = x
        self.base_y = y
        self._place()

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
        if dialog is None or dialog._drag_before is not None:
            return []
        return [item for item in self._scene.ordered_selection() if item.isVisible()]

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
        rect = self._scene._item_scene_rect(items[0])
        for item in items[1:]:
            rect = rect.united(self._scene._item_scene_rect(item))
        self._rect_item.setRect(rect)
        self._rect_item.show()
        hs = HANDLE_PX / self._zoom()
        for name in self.NAMES:
            center = self._anchor_point(rect, name)
            self._handles[name].setRect(
                QRectF(center.x() - hs / 2, center.y() - hs / 2, hs, hs)
            )
            self._handles[name].show()
        rs = HANDLE_ROTATE_RING_PX / self._zoom()
        for name in self.CORNERS:
            center = self._anchor_point(rect, name)
            self._rotate_zones[name].setRect(
                QRectF(center.x() - rs / 2, center.y() - rs / 2, rs, rs)
            )
            self._rotate_zones[name].setVisible(not self._multi)

    def hide(self):
        self._items = []
        self._multi = False
        self._rect_item.hide()
        for handle in self._handles.values():
            handle.hide()
        for zone in self._rotate_zones.values():
            zone.hide()

    def hit(self, scene_pos):
        if not self._items or self._gesture is not None:
            return None
        rect = self._rect_item.rect()
        hs = HANDLE_PX / self._zoom() / 2
        for name in self.NAMES:
            center = self._anchor_point(rect, name)
            if (
                abs(scene_pos.x() - center.x()) <= hs
                and abs(scene_pos.y() - center.y()) <= hs
            ):
                if name in self.CORNERS:
                    return "scale", name
                return "stretch", name
        if self._multi:
            return None
        rs = HANDLE_ROTATE_RING_PX / self._zoom() / 2
        for name in self.CORNERS:
            center = self._anchor_point(rect, name)
            if (
                abs(scene_pos.x() - center.x()) <= rs
                and abs(scene_pos.y() - center.y()) <= rs
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
            self._update_stretch(scene_pos, modifiers)
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
        rect = gesture["rect"]
        anchor = self._anchor_point(rect, OPPOSITE_CORNER[gesture["name"]])
        start_dist = self._distance(gesture["start_pos"], anchor)
        if start_dist < 1e-6:
            return
        factor = self._limit_factor(
            self._distance(scene_pos, anchor) / start_dist, "scale"
        )
        single = len(gesture["items"]) == 1
        for item, initial in gesture["items"].items():
            scale = round(initial["scale"] * factor)
            if single and not (modifiers & SNAP_DISABLED_MODIFIER):
                scale = self._scene.parent_dialog._snap_scale_value(scale)
            item.scale_pct = scale
            item.update_pixmap()
            effective = scale / initial["scale"]
            top = initial["rect"].topLeft()
            item.dx = round(
                anchor.x() + (top.x() - anchor.x()) * effective - item.base_x
            )
            item.dy = round(
                anchor.y() + (top.y() - anchor.y()) * effective - item.base_y
            )
            item._place()

    def _update_stretch(self, scene_pos, modifiers):
        gesture = self._gesture
        name = gesture["name"]
        rect = gesture["rect"]
        single = len(gesture["items"]) == 1
        if name in ("e", "w"):
            anchor_x = rect.left() if name == "e" else rect.right()
            span = gesture["start_pos"].x() - anchor_x
            if abs(span) < 1e-6:
                return
            factor = self._limit_factor(
                (scene_pos.x() - anchor_x) / span, "stretch_x"
            )
            for item, initial in gesture["items"].items():
                stretch = round(initial["stretch_x"] * factor)
                if single and not (modifiers & SNAP_DISABLED_MODIFIER):
                    stretch = self._snap_stretch(stretch)
                item.stretch_x = stretch
                item.update_pixmap()
                effective = stretch / initial["stretch_x"]
                top = initial["rect"].topLeft()
                item.dx = round(
                    anchor_x + (top.x() - anchor_x) * effective - item.base_x
                )
                item._place()
        else:
            anchor_y = rect.top() if name == "s" else rect.bottom()
            span = gesture["start_pos"].y() - anchor_y
            if abs(span) < 1e-6:
                return
            factor = self._limit_factor(
                (scene_pos.y() - anchor_y) / span, "stretch_y"
            )
            for item, initial in gesture["items"].items():
                stretch = round(initial["stretch_y"] * factor)
                if single and not (modifiers & SNAP_DISABLED_MODIFIER):
                    stretch = self._snap_stretch(stretch)
                item.stretch_y = stretch
                item.update_pixmap()
                effective = stretch / initial["stretch_y"]
                top = initial["rect"].topLeft()
                item.dy = round(
                    anchor_y + (top.y() - anchor_y) * effective - item.base_y
                )
                item._place()

    @staticmethod
    def _distance(a, b):
        return ((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2) ** 0.5


OPPOSITE_CORNER = {"nw": "se", "ne": "sw", "se": "nw", "sw": "ne"}


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
        self.transform_box = TransformBox(self)

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
            self.drag_started.emit()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.transform_box._gesture is not None:
            self.transform_box.update(event.scenePos(), event.modifiers())
            event.accept()
            return
        super().mouseMoveEvent(event)
        if not (event.buttons() & Qt.LeftButton):
            self._hide_guides()
            self.transform_box.refresh()
            return
        raw_translation = event.scenePos() - event.buttonDownScenePos(Qt.LeftButton)
        self._apply_object_snap(event.modifiers(), raw_translation)
        self.transform_box.refresh()
        if self.parent_dialog is not None:
            self.parent_dialog._update_scene_rect()

    def mouseReleaseEvent(self, event):
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

    def _background_bounds(self):
        dialog = self.parent_dialog
        if dialog is None:
            return QRectF()
        bounds = QRectF(0, 0, *dialog.canvas_size)
        for item in dialog.items:
            if item.isVisible():
                bounds = bounds.united(self._item_scene_rect(item))
        return bounds

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
            s = CHECKER_PX
            i0 = ceil(exposed.left() / s)
            j0 = ceil(exposed.top() / s)
            i1 = floor(exposed.right() / s)
            j1 = floor(exposed.bottom() / s)
            for j in range(int(j0), int(j1) + 1):
                for i in range(int(i0), int(i1) + 1):
                    if (i + j) % 2 == 0:
                        continue
                    x0 = max(i * s, exposed.left())
                    y0 = max(j * s, exposed.top())
                    x1 = min((i + 1) * s, exposed.right())
                    y1 = min((j + 1) * s, exposed.bottom())
                    painter.fillRect(
                        QRectF(x0, y0, x1 - x0, y1 - y0), alt
                    )
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
        menu.addAction("Reset Scale", lambda: dialog._reset_item(item, "scale_pct"))
        menu.addAction("Reset Rotation", lambda: dialog._reset_item(item, "rotation"))
        menu.addAction("Delete Character", lambda: dialog._delete_items([item]))
        menu.exec(event.screenPos())


class EditorView(QGraphicsView):
    zoom_changed = Signal(float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._pan_start = None

    def zoom_by(self, factor):
        current = self.transform().m11()
        target = current * factor
        if current < ZOOM_MIN_FACTOR:
            target = min(target, ZOOM_MIN_FACTOR)
        elif current > ZOOM_MAX_FACTOR:
            target = max(target, ZOOM_MAX_FACTOR)
        else:
            target = max(ZOOM_MIN_FACTOR, min(ZOOM_MAX_FACTOR, target))
        if abs(target - current) < 1e-9:
            return
        self.setTransform(self.transform().scale(target / current, target / current))
        self.zoom_changed.emit(self.transform().m11())

    def wheelEvent(self, event):
        delta = event.angleDelta()
        if event.modifiers() & Qt.ShiftModifier and delta.y():
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta.y())
            event.accept()
        elif delta.y():
            self.zoom_by(ZOOM_STEP if delta.y() > 0 else 1 / ZOOM_STEP)
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._pan_start = event.position()
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
        if event.button() == Qt.MiddleButton:
            self._pan_start = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


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
        self._dirty = False
        self._exported_signature = None
        self._fitted = False
        self._sprite_provider = self._sprite_for
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
            item = CharItem(char, sprite, x, y, self._sprite_provider)
            item.update_pixmap()
            self.scene.addItem(item)
            self.items.append(item)

        self._update_scene_rect()

    def _update_scene_rect(self):
        bounds = self.scene._background_bounds()
        self.scene.setSceneRect(
            bounds.left() - SCENE_PADDING,
            bounds.top() - SCENE_PADDING,
            bounds.width() + 2 * SCENE_PADDING,
            bounds.height() + 2 * SCENE_PADDING,
        )

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted:
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            self._fitted = True
        self.status_zoom_label.setText(self._zoom_text())
        self.view.setFocus()

    def _build_ui(self):
        outer = QVBoxLayout(self)
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

        panel_layout.addWidget(self._build_character_group())
        panel_layout.addWidget(self._build_global_group())

        self.export_btn = QPushButton("Save Image")
        self.export_btn.setToolTip(
            "Render the edited composition and save it with the main "
            "window's compression and scale settings (Ctrl+S)."
        )
        self.export_btn.clicked.connect(self.export_image)
        panel_layout.addWidget(self.export_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setToolTip("Discard all changes and close the editor.")
        cancel_btn.clicked.connect(self.reject)
        panel_layout.addWidget(cancel_btn)
        panel_layout.addStretch()

        for first, second in (
            (self.offset_x_spin, self.offset_y_spin),
            (self.offset_y_spin, self.scale_slider),
            (self.scale_slider, self.scale_spin),
            (self.scale_spin, self.stretch_x_spin),
            (self.stretch_x_spin, self.stretch_y_spin),
            (self.stretch_y_spin, self.rotation_slider),
            (self.rotation_slider, self.rotation_spin),
            (self.rotation_spin, self.letter_spacing_spin),
            (self.letter_spacing_spin, self.line_spacing_spin),
            (self.line_spacing_spin, self.baseline_combo),
            (self.baseline_combo, self.align_combo),
            (self.align_combo, self.export_btn),
            (self.export_btn, cancel_btn),
        ):
            self.setTabOrder(first, second)

        self._fit_panel(splitter, panel_scroll, panel)

    def _fit_panel(self, splitter, scroll, content):
        chrome = scroll.frameWidth() * 2 + self.style().pixelMetric(
            QStyle.PixelMetric.PM_ScrollBarExtent
        )
        scroll.setMinimumWidth(max(PANEL_WIDTH, content.sizeHint().width() + chrome))
        share = min(EDITOR_DEFAULT_WIDTH - CANVAS_MIN_WIDTH, scroll.minimumWidth())
        splitter.setSizes([EDITOR_DEFAULT_WIDTH - share, share])

    def _build_status_bar(self):
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 2, 8, 2)
        self.status_chars_label = QLabel()
        self.status_selection_label = QLabel()
        self.status_canvas_label = QLabel()
        self.status_zoom_label = QLabel()
        self.status_dirty_label = QLabel()
        for label in (
            self.status_chars_label,
            self.status_selection_label,
            self.status_canvas_label,
            self.status_zoom_label,
            self.status_dirty_label,
        ):
            layout.addWidget(label)
        layout.addStretch()

        self.undo_btn = QPushButton("Undo")
        self.undo_btn.setToolTip("Undo the last edit (Ctrl+Z).")
        self.undo_btn.clicked.connect(self._undo)
        layout.addWidget(self.undo_btn)

        self.redo_btn = QPushButton("Redo")
        self.redo_btn.setToolTip("Re-apply the last undone edit (Ctrl+Y).")
        self.redo_btn.clicked.connect(self._redo)
        layout.addWidget(self.redo_btn)

        self.zoom_out_btn = QPushButton("−")
        self.zoom_out_btn.setFixedWidth(28)
        self.zoom_out_btn.setAccessibleName("Zoom out")
        self.zoom_out_btn.setToolTip("Zoom out (also: mouse wheel down, Ctrl+-).")
        self.zoom_out_btn.clicked.connect(lambda: self.view.zoom_by(1 / ZOOM_STEP))
        layout.addWidget(self.zoom_out_btn)

        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setFixedWidth(28)
        self.zoom_in_btn.setAccessibleName("Zoom in")
        self.zoom_in_btn.setToolTip("Zoom in (also: mouse wheel up, Ctrl+=).")
        self.zoom_in_btn.clicked.connect(lambda: self.view.zoom_by(ZOOM_STEP))
        layout.addWidget(self.zoom_in_btn)

        self.fit_btn = QPushButton("Fit")
        self.fit_btn.setToolTip("Zoom so the whole image is visible (Ctrl+0).")
        self.fit_btn.clicked.connect(self._fit_view)
        layout.addWidget(self.fit_btn)

        self.help_btn = QPushButton("?")
        self.help_btn.setFixedWidth(28)
        self.help_btn.setAccessibleName("Editor help")
        self.help_btn.setToolTip("How the editor works: mouse actions, keys, snapping.")
        self.help_btn.clicked.connect(self._show_help)
        layout.addWidget(self.help_btn)

        self._update_status_counts()
        return bar

    HELP_TEXT = """\
Mouse

- Select one character to show its transform box: drag the
  corner squares to scale (the opposite corner stays put), the
  edge squares to stretch one axis, and the area just outside a
  corner to rotate around the character's centre. Hold Shift
  while rotating to snap to 45 degree steps.
- Select several characters and the box wraps them all: the
  corner squares scale the whole group and the edge squares
  stretch it in one direction, each character keeping its
  relative size and spacing.
- Drag a character to move it. Snapping aligns it to other
  characters' edges, centres, baselines and the grid (magenta
  and orange guides appear while dragging).
- Hold Alt or Ctrl while dragging or transforming to suspend
  snapping.
- Drag on empty space for a rubber-band selection.
- Ctrl+click adds characters to the selection.
- Double-click a character to replace it with another one.
- Right-click a character to reset its scale/rotation or delete it.
- Mouse wheel zooms, Shift + wheel scrolls sideways,
  middle-button drag pans the view.

Keys

- Arrow keys nudge the selection, Shift + Arrow nudges by 10.
- Ctrl+A selects every visible character, Delete removes the
  selected ones.
- Ctrl+Z / Ctrl+Y undo and redo, Ctrl+S saves the image.
- Ctrl+= / Ctrl+- zoom in and out, Ctrl+0 fits the view.

Panels

- Character Controls edits the current selection. The controls
  stay disabled while nothing is selected. The quick buttons
  flip the selection, rotate it by exact 90 degrees, or reset
  scale, stretch, rotation and flips.
- Spacing & Alignment re-lays out every visible character from
  the original text (spacing, vertical align, line align).
"""

    def _show_help(self):
        QMessageBox.information(self, "Advanced Editor Help", self.HELP_TEXT)

    def _fit_view(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.status_zoom_label.setText(self._zoom_text())

    def _zoom_text(self):
        return f"Zoom: {self.view.transform().m11() * 100:.0f}%"

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
        self.status_zoom_label.setText(self._zoom_text())
        self.status_dirty_label.setText("Unsaved edits" if self._dirty else "")
        self.undo_btn.setEnabled(self.undo_stack.can_undo())
        self.redo_btn.setEnabled(self.undo_stack.can_redo())

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

        form.addRow(self._build_selection_actions_row())

        return group

    def _build_selection_actions_row(self):
        widget = QWidget()
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self._selection_action_buttons = []
        self._transform_buttons = []

        align_label = QLabel("Align selection (needs 2+):")
        grid.addWidget(align_label, 0, 0, 1, 4)

        for column, (text, mode) in enumerate(
            (
                ("Left", "left"),
                ("Center", "center"),
                ("Right", "right"),
            )
        ):
            btn = QPushButton(text)
            btn.setToolTip(f"Align selected characters to the {mode} of the selection.")
            btn.clicked.connect(lambda _, m=mode: self._align_selection(m))
            grid.addWidget(btn, 1, column)
            self._selection_action_buttons.append(btn)

        for column, (text, mode) in enumerate(
            (
                ("Top", "top"),
                ("Middle", "middle"),
                ("Bottom", "bottom"),
            )
        ):
            btn = QPushButton(text)
            btn.setToolTip(f"Align selected characters to the {mode} of the selection.")
            btn.clicked.connect(lambda _, m=mode: self._align_selection(m))
            grid.addWidget(btn, 2, column)
            self._selection_action_buttons.append(btn)

        spread_h = QPushButton("Spread ↔")
        spread_h.setToolTip(
            "Distribute selected characters with even horizontal spacing."
        )
        spread_h.clicked.connect(lambda: self._distribute_selection("x"))
        grid.addWidget(spread_h, 3, 0)
        spread_v = QPushButton("Spread ↕")
        spread_v.setToolTip(
            "Distribute selected characters with even vertical spacing."
        )
        spread_v.clicked.connect(lambda: self._distribute_selection("y"))
        grid.addWidget(spread_v, 3, 1)
        self._selection_action_buttons.append(spread_h)
        self._selection_action_buttons.append(spread_v)

        for column, (text, tip, handler) in enumerate(
            (
                (
                    "Reset",
                    "Reset scale, stretch, rotation and flips; position is kept.",
                    self._reset_transform_selection,
                ),
            )
        ):
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(handler)
            grid.addWidget(btn, 3, 2)
            self._transform_buttons.append(btn)

        for column, (text, tip, handler) in enumerate(
            (
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
                    "↺",
                    "Rotate the selection 90 degrees counter-clockwise.",
                    lambda: self._rotate_selection_90(-1),
                ),
                (
                    "↻",
                    "Rotate the selection 90 degrees clockwise.",
                    lambda: self._rotate_selection_90(1),
                ),
            )
        ):
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(handler)
            grid.addWidget(btn, 4, column)
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
        zoom_in_sc.activated.connect(lambda: self.view.zoom_by(ZOOM_STEP))
        zoom_out_sc = QShortcut(QKeySequence("Ctrl+-"), self)
        zoom_out_sc.activated.connect(lambda: self.view.zoom_by(1 / ZOOM_STEP))
        fit_sc = QShortcut(QKeySequence("Ctrl+0"), self)
        fit_sc.activated.connect(self._fit_view)

        select_all_sc = QShortcut(QKeySequence.StandardKey.SelectAll, self)
        select_all_sc.activated.connect(self._select_all)

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

    def _reset_transform_selection(self):
        selected = [item for item in self._selected() if item.isVisible()]
        if not selected:
            return
        before = self._snapshot_selected()
        for item in selected:
            item.scale_pct = CHAR_SCALE_DEFAULT
            item.stretch_x = CHAR_SCALE_DEFAULT
            item.stretch_y = CHAR_SCALE_DEFAULT
            item.rotation = 0
            item.flip_h = False
            item.flip_v = False
            item.prune_cache()
            item.update_pixmap()
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
        self.scene.invalidate(
            self.scene.sceneRect(), QGraphicsScene.SceneLayer.BackgroundLayer
        )

    def _on_zoom_changed(self, _factor):
        self.status_zoom_label.setText(self._zoom_text())
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
        ):
            widget.blockSignals(True)
        try:
            if selected:
                first = selected[0]
                self.offset_x_spin.setValue(round(first.dx))
                self.offset_y_spin.setValue(round(first.dy))
                self.scale_slider.setValue(first.scale_pct)
                self.scale_spin.setValue(first.scale_pct)
                self.rotation_slider.setValue(first.rotation)
                self.rotation_spin.setValue(first.rotation)
                self.stretch_x_spin.setValue(first.stretch_x)
                self.stretch_y_spin.setValue(first.stretch_y)
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
            self.rotation_quality,
        ):
            widget.setEnabled(has_selection)
        multi = len(selected) >= 2
        for btn in self._selection_action_buttons:
            btn.setEnabled(multi)
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
            rendered = render_character(
                item.sprite,
                value,
                item.rotation,
                item.rotation_quality,
                item.stretch_x,
                item.stretch_y,
                item.flip_h,
                item.flip_v,
            )
            item._pix_cache[item._cache_key()] = rendered
            w, h = rendered.size
            item.dx = round(new_cx - w / 2 - item.base_x)
            item.dy = round(new_cy - h / 2 - item.base_y)
            item.update_pixmap()

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

    def _align_selection(self, mode):
        items = [item for item in self._selected() if item.isVisible()]
        if len(items) < 2:
            return
        before = self._snapshot_selected()
        rects = {item: self.scene._item_scene_rect(item) for item in items}
        union = rects[items[0]]
        for rect in rects.values():
            union = union.united(rect)
        for item, rect in rects.items():
            if mode == "left":
                ddx, ddy = union.left() - rect.left(), 0
            elif mode == "right":
                ddx, ddy = union.right() - rect.right(), 0
            elif mode == "center":
                ddx, ddy = union.center().x() - rect.center().x(), 0
            elif mode == "top":
                ddx, ddy = 0, union.top() - rect.top()
            elif mode == "bottom":
                ddx, ddy = 0, union.bottom() - rect.bottom()
            else:
                ddx, ddy = 0, union.center().y() - rect.center().y()
            ddx, ddy = round(ddx), round(ddy)
            if ddx or ddy:
                item.dx += ddx
                item.dy += ddy
                item._place()
        self._push(before)
        self._sync_panel()

    def _distribute_selection(self, axis):
        items = [item for item in self._selected() if item.isVisible()]
        if len(items) < 3:
            return
        before = self._snapshot_selected()
        rects = {item: self.scene._item_scene_rect(item) for item in items}
        ordered = sorted(
            items,
            key=lambda it: (
                rects[it].center().x() if axis == "x" else rects[it].center().y()
            ),
        )
        first = rects[ordered[0]].center()
        last = rects[ordered[-1]].center()
        span = (last.x() - first.x()) if axis == "x" else (last.y() - first.y())
        step = span / (len(ordered) - 1)
        for index, item in enumerate(ordered[1:-1], start=1):
            rect = rects[item]
            if axis == "x":
                delta = round(first.x() + index * step - rect.center().x())
                if delta:
                    item.dx += delta
            else:
                delta = round(first.y() + index * step - rect.center().y())
                if delta:
                    item.dy += delta
            item._place()
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

    def _sprite_for(self, char):
        if char not in self._char_cache:
            self._char_cache[char] = create_character_image(char, self.font_paths)
        return self._char_cache[char]

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
                ch, sprite, x, bottom - rendered.height, self._sprite_provider
            )
            ni.layout_anchored = False
            ni.scale_pct = item.scale_pct
            ni.rotation = item.rotation
            ni.rotation_quality = item.rotation_quality
            ni.stretch_x = item.stretch_x
            ni.stretch_y = item.stretch_y
            ni.flip_h = item.flip_h
            ni.flip_v = item.flip_v
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
            self.canvas_size = canvas
            self.canvas_rect.setRect(0, 0, *canvas)
            self._update_scene_rect()
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
            super().reject()

    def closeEvent(self, event):
        if self._confirm_discard():
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
        self.canvas_size = (canvas_w, canvas_h)
        self.canvas_rect.setRect(0, 0, canvas_w, canvas_h)
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
        try:
            summary = self._export_image()
        except OSError as e:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"The image could not be saved:\n{e}\n\n"
                "Check that the save location exists and is writable.",
            )
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
        for item in self.items:
            if not item.isVisible():
                continue
            key = item._cache_key()
            rendered = item._pix_cache.get(key)
            if rendered is None:
                rendered = render_character(
                    item.sprite,
                    item.scale_pct,
                    item.rotation,
                    item.rotation_quality,
                    item.stretch_x,
                    item.stretch_y,
                    item.flip_h,
                    item.flip_v,
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
            canvas = Image.new("RGBA", (max_x - min_x, max_y - min_y), (0, 0, 0, 0))
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
