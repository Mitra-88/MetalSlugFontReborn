from enum import IntEnum
from math import ceil, cos, radians, sin
from pathlib import Path
from time import time

from PIL import Image, ImageQt
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QIcon, QKeySequence, QPen, QPixmap,
                           QShortcut)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QFormLayout, QFrame, QGraphicsItem,
                               QGraphicsLineItem, QGraphicsPixmapItem,
                               QGraphicsRectItem, QGraphicsScene,
                               QGraphicsView, QGridLayout, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QMenu,
                               QMessageBox, QPushButton, QScrollArea,
                               QSlider, QSpinBox, QSplitter, QVBoxLayout,
                               QWidget)

from image_generation import (create_character_image, generate_filename,
                              get_font_paths, layout_characters)
from qt_utils import load_config, save_config
from utils import readable_size

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EDITOR_DEFAULT_WIDTH = 1100
EDITOR_DEFAULT_HEIGHT = 700
CANVAS_SPLIT_PERCENT = 70
PANEL_WIDTH = 330
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
SNAP_DISABLED_MODIFIER = Qt.KeyboardModifier.AltModifier

SCALE_SNAP_TOLERANCE_PCT = 4
ROTATE_SNAP_STEP = 45
GUIDE_POOL_SIZE = 8

NUDGE_STEP = 1
NUDGE_BIG_STEP = 10

SNAP_GUIDE_COLOR = "#ff00ae"
SNAP_SPACING_GUIDE_COLOR = "#ff9500"

GRID_LINE_COLOR = QColor(128, 128, 128, 60)
CANVAS_FILL_COLOR = QColor(128, 128, 128, 28)
GRID_MIN_SCREEN_PX = 7


class GuideStyle(IntEnum):
    EDGE = 0
    CENTER = 1
    SPACING = 2


class _SnapCandidate:
    __slots__ = ("delta", "coord", "guides")

    def __init__(self, delta, coord, guides):
        self.delta = delta
        self.coord = coord
        self.guides = guides


class SnapEngine:
    """Document-space snapping math for the Advanced editor.

    All inputs and outputs are in canvas (document) coordinates; the
    caller converts a screen-pixel tolerance into document space using
    the current view zoom, so snapping feels identical at every zoom
    level. Detection is deterministic: candidates are resolved by the
    total order (|delta|, coordinate, delta) and statics are kept in
    sorted tables, never raw set/dict iteration order.

    Priority tiers per axis (first tier with a candidate wins):
      1. other characters' edges         (edge-to-edge only)
      2. other characters' centers       (center-to-center only)
      3. canvas/artboard edges + center
      4. equal-gap spacing between two statics (Figma-style)
      5. fixed grid fallback (no guides)
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """Drop all per-drag state so every drag starts from a clean pass."""
        self._statics = []
        self._xs = None
        self._ys = None
        self._x_by_left = []
        self._y_by_top = []

    def is_ready(self):
        return self._xs is not None

    def set_statics(self, statics, canvas_w, canvas_h):
        """Load the immutable snap sources for one drag gesture.

        statics: iterable of (key, QRectF) for every visible, non-moving
        character; key only breaks ties, coordinates drive detection.
        """
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
        self._y_by_bottom = sorted(self._statics, key=lambda kv: (kv[1].bottom(), kv[0]))

    def find_snap(self, box, threshold, grid):
        """Return (dx, dy, guides) for the moving bounding box.

        guides is a list of (axis, coord, GuideStyle) for the snaps that
        are actually active this frame; empty when only the grid matched.
        """
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
                best = min(
                    candidates, key=lambda c: (abs(c.delta), c.coord, c.delta)
                )
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
        return self._match_edges(self._moving_edges(box, horizontal), table,
                                 threshold, GuideStyle.EDGE, horizontal)

    def _tier_char_centers(self, box, threshold, horizontal):
        table = self._xs[1] if horizontal else self._ys[1]
        return self._match_edges((self._moving_center(box, horizontal),), table,
                                 threshold, GuideStyle.CENTER, horizontal)

    def _tier_canvas(self, box, threshold, horizontal):
        size = self._canvas_w if horizontal else self._canvas_h
        edge_targets = ((0.0, GuideStyle.EDGE), (size, GuideStyle.EDGE),
                        (size / 2.0, GuideStyle.CENTER))
        center_targets = ((size / 2.0, GuideStyle.CENTER),)
        out = []
        for edge in self._moving_edges(box, horizontal):
            for coord, style in edge_targets:
                delta = coord - edge
                if abs(delta) <= threshold:
                    out.append(_SnapCandidate(delta, coord,
                                              [(horizontal, coord, style)]))
        center = self._moving_center(box, horizontal)
        for coord, style in center_targets:
            delta = coord - center
            if abs(delta) <= threshold:
                out.append(_SnapCandidate(delta, coord,
                                          [(horizontal, coord, style)]))
        return out

    def _match_edges(self, moving, table, threshold, style, horizontal):
        out = []
        for edge in moving:
            for coord, key in table:
                delta = coord - edge
                if abs(delta) <= threshold:
                    out.append(_SnapCandidate(delta, coord,
                                              [(horizontal, coord, style)]))
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

        near_left = self._nearest_before(before, left_edge_of,
                                         first + threshold, perp_lo, perp_hi,
                                         threshold, horizontal)
        near_right = self._nearest_after(after, right_edge_of,
                                         first + span - threshold,
                                         perp_lo, perp_hi, threshold,
                                         horizontal)
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
                delta, target,
                [(horizontal, bound_a, GuideStyle.SPACING),
                 (horizontal, bound_b, GuideStyle.SPACING)],
            )
        ]

    def _nearest_before(self, ordered, edge_of, limit, perp_lo, perp_hi,
                        threshold, horizontal):
        best = None
        for key, rect in ordered:
            value = edge_of(rect)
            if value > limit:
                break
            if self._perpendicular_close(rect, perp_lo, perp_hi, threshold,
                                         horizontal):
                best = (key, rect)
        return best

    def _nearest_after(self, ordered, edge_of, limit, perp_lo, perp_hi,
                       threshold, horizontal):
        for key, rect in ordered:
            if edge_of(rect) < limit:
                continue
            if self._perpendicular_close(rect, perp_lo, perp_hi, threshold,
                                         horizontal):
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


def render_character(sprite, scale_pct=CHAR_SCALE_DEFAULT, rotation=0):
    img = sprite
    if scale_pct != CHAR_SCALE_DEFAULT:
        img = img.resize(
            (
                max(1, int(img.width * scale_pct / 100)),
                max(1, int(img.height * scale_pct / 100)),
            ),
            Image.Resampling.NEAREST,
        )
    if rotation:
        img = img.rotate(-rotation, expand=True, resample=Image.Resampling.NEAREST)
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
        self._pix_cache = {}
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
        return (self.scale_pct, self.rotation)

    def update_pixmap(self):
        key = self._cache_key()
        rendered = self._pix_cache.get(key)
        if rendered is None:
            rendered = render_character(self.sprite, self.scale_pct, self.rotation)
            self._pix_cache[key] = rendered
        qimage = ImageQt.ImageQt(rendered)
        self.setPixmap(QPixmap.fromImage(qimage))
        self._place()

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

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_started.emit()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        raw_translation = None
        if event.buttons() & Qt.LeftButton:
            # Absolute offset of the mouse from the grab point — the raw,
            # unsnapped drag path. Snapping must be a pure function of
            # this, never applied on top of its own previous corrections,
            # or the item drifts off the cursor and keeps re-correcting.
            raw_translation = (
                event.scenePos() - event.buttonDownScenePos(Qt.LeftButton)
            )
        self._apply_object_snap(event.modifiers(), raw_translation)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.drag_finished.emit()

    def begin_snap(self):
        """Start a fresh detection pass; nothing survives from the last drag."""
        self._snap_engine.reset()
        self._hide_guides()

    def end_snap(self):
        self._snap_engine.reset()
        self._hide_guides()

    def _item_scene_rect(self, item):
        # Visual bounds of the rendered sprite (integer edges on the pixel
        # grid). QGraphicsPixmapItem.boundingRect() is expanded by 0.5px on
        # every side, which would put all snap targets on half-pixels.
        pixmap = item.pixmap()
        return item.mapRectToScene(
            QRectF(0, 0, pixmap.width(), pixmap.height())
        )

    def _gather_movers(self):
        if not hasattr(self, "_snap_start"):
            return []
        # Dict order == scene item order (insertion order), so mover
        # selection and the reference item are deterministic.
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
        """Union rect of the movers at start + raw translation (no snapping
        applied), so detection is a pure function of the mouse path."""
        rect = None
        for item, start in movers:
            pixmap = item.pixmap()
            r = QRectF(0, 0, pixmap.width(), pixmap.height()).translated(
                start.x() + translation.x(), start.y() + translation.y()
            )
            rect = r if rect is None else rect.united(r)
        return rect

    def _apply_object_snap(self, modifiers=None, raw_translation=None):
        if (
            not self.snapping_enabled
            or (modifiers is not None and modifiers & SNAP_DISABLED_MODIFIER)
        ):
            self._hide_guides()
            return
        movers = self._gather_movers()
        if not movers:
            self._hide_guides()
            return
        if not self._snap_engine.is_ready():
            self._load_statics(movers)

        if raw_translation is None:
            # Fallback for programmatic use: derive the offset from the
            # first mover's current displacement.
            first, first_start = movers[0]
            raw_translation = first.pos() - first_start
        translation = QPointF(
            round(raw_translation.x()), round(raw_translation.y())
        )

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
                line_item.setLine(
                    coord, scene_rect.top(), coord, scene_rect.bottom()
                )
            else:
                line_item.setLine(
                    scene_rect.left(), coord, scene_rect.right(), coord
                )
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

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        canvas = QRectF(0, 0, *self.parent_dialog.canvas_size)
        exposed = rect.intersected(canvas)
        if exposed.isNull():
            return
        painter.fillRect(exposed, CANVAS_FILL_COLOR)
        if not self.snapping_enabled or self.snap_size <= 0:
            return
        views = self.views()
        zoom = abs(views[0].transform().m11()) if views else 1.0
        step = float(self.snap_size)
        while step * zoom < GRID_MIN_SCREEN_PX:
            step *= 2
        painter.setPen(QPen(GRID_LINE_COLOR, 0))
        x = ceil(exposed.left() / step) * step
        while x <= exposed.right():
            painter.drawLine(QPointF(x, exposed.top()), QPointF(x, exposed.bottom()))
            x += step
        y = ceil(exposed.top() / step) * step
        while y <= exposed.bottom():
            painter.drawLine(QPointF(exposed.left(), y), QPointF(exposed.right(), y))
            y += step

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
        target = max(ZOOM_MIN_FACTOR, min(ZOOM_MAX_FACTOR, current * factor))
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
        self._sprite_provider = self._sprite_for
        self._build_scene()
        self._build_ui()
        self._connect_selection()
        self._install_shortcuts()

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
        self.view.setToolTip(
            "Drag characters to move them (Ctrl+click or drag a box to "
            "select several). Double-click a character to replace it. "
            "Mouse wheel zooms, Shift + wheel scrolls sideways, middle "
            "button drags to pan. Characters snap to other characters' "
            "edges, centres and baselines (magenta guides); hold Alt to "
            "suspend snapping while dragging."
        )

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
        canvas_w, canvas_h = self.canvas_size
        self.scene.setSceneRect(
            -SCENE_PADDING,
            -SCENE_PADDING,
            canvas_w + 2 * SCENE_PADDING,
            canvas_h + 2 * SCENE_PADDING,
        )

    def showEvent(self, event):
        super().showEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.status_zoom_label.setText(self._zoom_text())
        self.view.setFocus()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal, self)
        outer.addWidget(splitter, 1)
        outer.addWidget(self._build_status_bar())

        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setMinimumWidth(PANEL_WIDTH)
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_scroll.setWidget(panel)
        splitter.addWidget(self.view)
        splitter.addWidget(panel_scroll)
        canvas_share = EDITOR_DEFAULT_WIDTH * CANVAS_SPLIT_PERCENT // 100
        splitter.setSizes([canvas_share, EDITOR_DEFAULT_WIDTH - canvas_share])
        splitter.setStretchFactor(0, 1)

        panel_layout.addWidget(self._build_character_group())
        panel_layout.addWidget(self._build_global_group())

        self.export_btn = QPushButton("Save Image")
        self.export_btn.setToolTip(
            "Render the edited composition and save it with the main "
            "window's compression and scale settings."
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
            (self.scale_spin, self.rotation_slider),
            (self.rotation_slider, self.rotation_spin),
            (self.rotation_spin, self.letter_spacing_spin),
            (self.letter_spacing_spin, self.line_spacing_spin),
            (self.line_spacing_spin, self.baseline_combo),
            (self.baseline_combo, self.align_combo),
            (self.align_combo, self.export_btn),
            (self.export_btn, cancel_btn),
        ):
            self.setTabOrder(first, second)

    def _build_status_bar(self):
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 2, 8, 2)
        self.status_chars_label = QLabel()
        self.status_selection_label = QLabel()
        self.status_zoom_label = QLabel()
        self.status_dirty_label = QLabel()
        for label in (
            self.status_chars_label,
            self.status_selection_label,
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
        self.zoom_out_btn.setToolTip("Zoom out (also: mouse wheel down, Ctrl+-).")
        self.zoom_out_btn.clicked.connect(lambda: self.view.zoom_by(1 / ZOOM_STEP))
        layout.addWidget(self.zoom_out_btn)

        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setFixedWidth(28)
        self.zoom_in_btn.setToolTip("Zoom in (also: mouse wheel up, Ctrl+=).")
        self.zoom_in_btn.clicked.connect(lambda: self.view.zoom_by(ZOOM_STEP))
        layout.addWidget(self.zoom_in_btn)

        self.fit_btn = QPushButton("Fit")
        self.fit_btn.setToolTip("Zoom so the whole image is visible (Ctrl+0).")
        self.fit_btn.clicked.connect(self._fit_view)
        layout.addWidget(self.fit_btn)

        self._update_status_counts()
        return bar

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
        self.status_zoom_label.setText(self._zoom_text())
        self.status_dirty_label.setText("Unsaved edits" if self._dirty else "")
        self.undo_btn.setEnabled(self.undo_stack.can_undo())
        self.redo_btn.setEnabled(self.undo_stack.can_redo())

    def _make_collapsible(self, group):
        group.setCheckable(True)
        group.setChecked(True)

        def toggle(checked):
            for child in group.findChildren(QWidget):
                child.setVisible(checked)

        group.toggled.connect(toggle)
        return group

    def _build_character_group(self):
        group = self._make_collapsible(QGroupBox("Character Controls"))
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

        form.addRow(self._build_selection_actions_row())

        return group

    def _build_selection_actions_row(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        align_label = QLabel("Align selection (needs 2+):")
        layout.addWidget(align_label)

        align_row = QHBoxLayout()
        align_row.setSpacing(4)
        for text, mode in (
            ("Left", "left"), ("Center", "center"), ("Right", "right"),
        ):
            btn = QPushButton(text)
            btn.setToolTip(f"Align selected characters to the {mode} of the selection.")
            btn.clicked.connect(lambda _, m=mode: self._align_selection(m))
            align_row.addWidget(btn)
        layout.addLayout(align_row)

        align_row2 = QHBoxLayout()
        align_row2.setSpacing(4)
        for text, mode in (
            ("Top", "top"), ("Middle", "middle"), ("Bottom", "bottom"),
        ):
            btn = QPushButton(text)
            btn.setToolTip(f"Align selected characters to the {mode} of the selection.")
            btn.clicked.connect(lambda _, m=mode: self._align_selection(m))
            align_row2.addWidget(btn)
        layout.addLayout(align_row2)

        spread_row = QHBoxLayout()
        spread_row.setSpacing(4)
        spread_h = QPushButton("Spread ↔")
        spread_h.setToolTip(
            "Distribute selected characters with even horizontal spacing."
        )
        spread_h.clicked.connect(lambda: self._distribute_selection("x"))
        spread_v = QPushButton("Spread ↕")
        spread_v.setToolTip(
            "Distribute selected characters with even vertical spacing."
        )
        spread_v.clicked.connect(lambda: self._distribute_selection("y"))
        spread_row.addWidget(spread_h)
        spread_row.addWidget(spread_v)
        layout.addLayout(spread_row)

        return widget

    def _build_global_group(self):
        group = self._make_collapsible(QGroupBox("Spacing & Alignment"))
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
            "Alt while dragging to suspend snapping temporarily."
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

        return group

    def _install_shortcuts(self):
        undo_sc = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_sc.activated.connect(self._undo)
        redo_sc = QShortcut(QKeySequence.StandardKey.Redo, self)
        redo_sc.activated.connect(self._redo)
        del_sc = QShortcut(QKeySequence.StandardKey.Delete, self.view)
        del_sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        del_sc.activated.connect(self._delete_selected)

        zoom_in_sc = QShortcut(QKeySequence("Ctrl+="), self)
        zoom_in_sc.activated.connect(lambda: self.view.zoom_by(ZOOM_STEP))
        zoom_out_sc = QShortcut(QKeySequence("Ctrl+-"), self)
        zoom_out_sc.activated.connect(lambda: self.view.zoom_by(1 / ZOOM_STEP))
        fit_sc = QShortcut(QKeySequence("Ctrl+0"), self)
        fit_sc.activated.connect(self._fit_view)

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
        selected = self._selected()
        if not selected:
            return
        before = self._snapshot_selected()
        for item in selected:
            item.dx += dx
            item.dy += dy
            item._place()
        self._push(before)
        self._sync_panel()

    def _delete_selected(self):
        selected = self._selected()
        if selected:
            self._delete_items(selected)

    def _undo(self):
        if not self.undo_stack.undo(self._apply_all):
            return
        self._sync_panel()
        self._update_status_counts()

    def _redo(self):
        if not self.undo_stack.redo(self._apply_all):
            return
        self._sync_panel()
        self._update_status_counts()

    def _connect_selection(self):
        self.scene.selectionChanged.connect(self._sync_panel)
        self._drag_before = None
        self._drag_start_pos = {}
        self.scene.drag_started.connect(self._on_drag_started)
        self.scene.drag_finished.connect(self._on_drag_finished)
        self.view.zoom_changed.connect(
            lambda _: self.status_zoom_label.setText(self._zoom_text())
        )

    def _selected(self):
        return self.scene.selectedItems()

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
                delta_x = int(round(item.pos().x() - start.x()))
                delta_y = int(round(item.pos().y() - start.y()))
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
                self.undo_stack.push(changed, {item: after[item] for item in changed})
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
        ):
            widget.blockSignals(True)
        try:
            if selected:
                first = selected[0]
                self.offset_x_spin.setValue(int(round(first.dx)))
                self.offset_y_spin.setValue(int(round(first.dy)))
                self.scale_slider.setValue(first.scale_pct)
                self.scale_spin.setValue(first.scale_pct)
                self.rotation_slider.setValue(first.rotation)
                self.rotation_spin.setValue(first.rotation)
        finally:
            for widget in (
                self.offset_x_spin,
                self.offset_y_spin,
                self.scale_slider,
                self.scale_spin,
                self.rotation_slider,
                self.rotation_spin,
            ):
                widget.blockSignals(False)

        self._update_status_counts()

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

    def _rendered_size(self, item, scale_pct):
        w = item.sprite.width * scale_pct / 100.0
        h = item.sprite.height * scale_pct / 100.0
        if item.rotation:
            rad = radians(abs(item.rotation))
            c, s = cos(rad), sin(rad)
            w, h = abs(w * c) + abs(h * s), abs(w * s) + abs(h * c)
        return w, h

    def _scale_selection(self, items, value):
        # Scale every character around the centre of the whole selection
        # so grouped characters keep their relative spacing instead of
        # piling up on each other.
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
            w, h = self._rendered_size(item, value)
            item.dx = new_cx - w / 2 - item.base_x
            item.dy = new_cy - h / 2 - item.base_y
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

    def _begin_slider_undo(self):
        # One undo entry per slider gesture, not one per tick.
        snapshot = self._snapshot_selected()
        self._slider_undo_before = snapshot or None

    def _end_slider_undo(self):
        before = getattr(self, "_slider_undo_before", None)
        self._slider_undo_before = None
        if before:
            self._push(before)
            self._update_status_counts()

    def _snap_rotation_value(self, value, shift_held=None):
        """Hard-snap to 45-degree increments while Shift is held."""
        if shift_held is None:
            shift_held = bool(
                QApplication.queryKeyboardModifiers() & Qt.ShiftModifier
            )
        if not shift_held:
            return value
        snapped = round(value / ROTATE_SNAP_STEP) * ROTATE_SNAP_STEP
        return max(ROTATION_MIN, min(ROTATION_MAX, snapped))

    def _snap_scale_value(self, value):
        """Snap the scale slider to match another character's size, or 100%."""
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
                delta = union.left() - rect.left()
                ddx, ddy = delta, 0
            elif mode == "right":
                ddx, ddy = union.right() - rect.right(), 0
            elif mode == "center":
                ddx, ddy = union.center().x() - rect.center().x(), 0
            elif mode == "top":
                ddx, ddy = 0, union.top() - rect.top()
            elif mode == "bottom":
                ddx, ddy = 0, union.bottom() - rect.bottom()
            else:  # middle
                ddx, ddy = 0, union.center().y() - rect.center().y()
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
        ordered = sorted(items, key=lambda it: rects[it].center().x() if axis == "x"
                         else rects[it].center().y())
        first = rects[ordered[0]].center()
        last = rects[ordered[-1]].center()
        span = (last.x() - first.x()) if axis == "x" else (last.y() - first.y())
        step = span / (len(ordered) - 1)
        for index, item in enumerate(ordered[1:-1], start=1):
            rect = rects[item]
            if axis == "x":
                delta = first.x() + index * step - rect.center().x()
                if delta:
                    item.dx += delta
            else:
                delta = first.y() + index * step - rect.center().y()
                if delta:
                    item.dy += delta
            item._place()
        self._push(before)
        self._sync_panel()

    def _apply_offset(self, dx=None, dy=None):
        selected = self._selected()
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
        for ch in new_text:
            if not ch.isspace() and self.valid_chars and ch not in self.valid_chars:
                upper = ch.upper()
                if upper in self.valid_chars:
                    ch = upper
                else:
                    QMessageBox.warning(
                        self,
                        "Unsupported Character",
                        f"'{ch}' is not supported by this font. "
                        "Check the supported characters list for options.",
                    )
                    return
            chars.append(ch)

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

    def _replace_with_string(self, item, chars):
        sprites = [self._sprite_for(c) for c in chars]
        before = {item: item.capture_state()}
        x = item.base_x + item.dx
        bottom = item.base_y + item.dy + item.sprite.height
        for ch, sprite in zip(chars, sprites):
            if ch.isspace():
                x += sprite.width + self.letter_spacing
                continue
            ni = CharItem(ch, sprite, x, bottom - sprite.height, self._sprite_provider)
            ni.layout_anchored = False
            ni.scale_pct = item.scale_pct
            ni.rotation = item.rotation
            self.scene.addItem(ni)
            self.items.append(ni)
            ni.setVisible(False)
            before[ni] = ni.capture_state()
            ni.setVisible(True)
            ni.update_pixmap()
            x += sprite.width + self.letter_spacing
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

    def _push(self, before):
        after = {item: item.capture_state() for item in before}
        if any(after[item] != state for item, state in before.items()):
            self.undo_stack.push(before, after)
            self._dirty = True
            self._update_status_counts()

    def _apply_all(self, snapshot):
        for item, state in snapshot.items():
            item.apply_state(state)

    def _has_unsaved_edits(self):
        return self._dirty

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
        self.letter_spacing = self.letter_spacing_spin.value()
        self.line_spacing = self.line_spacing_spin.value()
        self.baseline = self.baseline_combo.currentText().lower()
        self.align = self.align_combo.currentText().lower()

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
        self._push(before)

    def _on_snap_changed(self, value):
        self.snap_grid = value
        self.scene.snap_size = value
        if value > 0:
            self.scene.invalidate(self.scene.sceneRect(),
                                  QGraphicsScene.SceneLayer.BackgroundLayer)

    def _on_snapping_toggled(self, checked):
        self.scene.snapping_enabled = checked
        self.snap_spin.setEnabled(checked)
        self.scene.invalidate(self.scene.sceneRect(),
                              QGraphicsScene.SceneLayer.BackgroundLayer)

    def export_image(self):
        try:
            self._export_image()
        except OSError as e:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"The image could not be saved:\n{e}\n\n"
                "Check that the save location exists and is writable.",
            )
            return False
        self._dirty = False
        self.status_dirty_label.setText("")
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
                rendered = render_character(item.sprite, item.scale_pct, item.rotation)
                item._pix_cache[key] = rendered
            x = int(item.base_x + item.dx)
            y = int(item.base_y + item.dy)
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

        scale = self.params.get("scale", 100)
        if scale and scale != 100:
            canvas = canvas.resize(
                (
                    max(1, int(canvas.width * scale / 100)),
                    max(1, int(canvas.height * scale / 100)),
                ),
                Image.Resampling.NEAREST,
            )

        out_path = Path(self.params["save_path"]) / filename
        canvas.save(out_path, compress_level=self.params.get("compress_level", 6))

        elapsed = time() - start
        size = readable_size(out_path.stat().st_size)
        QMessageBox.information(
            self,
            "Image Saved",
            f"Saved {out_path}\n{canvas.width} x {canvas.height} px, "
            f"{size}, {elapsed:.2f}s",
        )
