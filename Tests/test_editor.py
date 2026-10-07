from PySide6.QtCore import QPointF, Qt

from editor import AdvancedEditorDialog
from image_generation import get_font_charset


def make_params(tmp_path):
    return {
        "text": "HI!",
        "font": 1,
        "color": "Blue",
        "save_path": str(tmp_path),
        "compress_level": 0,
        "scale": 1,
    }


def make_dialog(tmp_path):
    return AdvancedEditorDialog(None, make_params(tmp_path), get_font_charset(1))


def test_editor_reports_visible_items_and_canvas(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        assert dialog._has_visible_items()
        assert "Canvas:" in dialog.status_canvas_label.text()
        assert dialog.canvas_size[0] > 0
        for item in dialog.items:
            item.setVisible(False)
        assert not dialog._has_visible_items()
    finally:
        dialog.close()


def test_editor_blocks_export_with_nothing_visible(qapp, tmp_path, monkeypatch):
    warnings = []
    dialog = make_dialog(tmp_path)
    monkeypatch.setattr(
        dialog, "_warn_nothing_to_export", lambda: warnings.append(True)
    )
    try:
        for item in dialog.items:
            item.setVisible(False)
        assert dialog.export_image() is False
        assert len(warnings) == 1
    finally:
        dialog.close()


def test_editor_export_saves_single_png(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        assert dialog.export_image() is True
        saved = list(tmp_path.iterdir())
        assert len(saved) == 1
        assert saved[0].suffix == ".png"
        assert saved[0].stat().st_size > 0
        assert "Saved" in dialog.status_dirty_label.text()
    finally:
        dialog.close()


def test_editor_undo_restores_deleted_character(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        target = dialog.items[0]
        dialog._delete_items([target])
        assert not target.isVisible()
        assert dialog.undo_stack.can_undo()
        assert dialog._dirty is True
        dialog._undo()
        assert target.isVisible()
        assert dialog._dirty is False
    finally:
        dialog._dirty = False
        dialog.close()


def test_editor_selection_preserves_click_order(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        assert len(dialog.items) >= 3
        second, first, third = dialog.items[1], dialog.items[0], dialog.items[2]
        second.setSelected(True)
        first.setSelected(True)
        third.setSelected(True)
        assert dialog._selected() == [second, first, third]
        first.setSelected(False)
        assert dialog._selected() == [second, third]
    finally:
        dialog._dirty = False
        dialog.close()


def test_editor_binds_save_shortcut(qapp, tmp_path):
    from PySide6.QtGui import QKeySequence, QShortcut

    dialog = make_dialog(tmp_path)
    try:
        save_shortcuts = [
            shortcut
            for shortcut in dialog.findChildren(QShortcut)
            if shortcut.key() == QKeySequence(QKeySequence.StandardKey.Save)
        ]
        assert save_shortcuts
    finally:
        dialog.close()


def test_layout_undo_restores_canvas_size(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        before = dialog.canvas_size
        dialog.letter_spacing_spin.setValue(30)
        grown = dialog.canvas_size
        assert grown[0] > before[0]
        dialog._undo()
        assert dialog.canvas_size == before
        assert str(before[0]) in dialog.status_canvas_label.text()
    finally:
        dialog._dirty = False
        dialog.close()


def test_slider_release_prunes_item_cache(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        dialog._begin_slider_undo()
        dialog.scale_slider.setValue(250)
        assert item.scale_pct == 250
        dialog._end_slider_undo()
        assert list(item._pix_cache.keys()) == [
            (250, 0, 100, 100, False, False, 100, 0)
        ]
    finally:
        dialog._dirty = False
        dialog.close()


def test_layout_undo_restores_spacing_controls(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    canvas_before = dialog.canvas_size
    dialog.letter_spacing_spin.setValue(20)
    assert dialog.letter_spacing == 20
    dialog._undo()
    assert dialog.letter_spacing_spin.value() == 0
    assert dialog.letter_spacing == 0
    assert dialog.canvas_size == canvas_before
    dialog._dirty = False
    dialog.close()


def test_replace_with_string_advances_by_scaled_width(qapp, tmp_path):
    from editor import render_character

    dialog = make_dialog(tmp_path)
    item = dialog.items[0]
    item.scale_pct = 200
    dialog._replace_with_string(item, ["a", "b"])
    replacements = dialog.items[-2:]
    assert [i.char for i in replacements] == ["a", "b"]
    rendered_width = render_character(replacements[0].sprite, 200, 0).width
    assert (
        replacements[1].base_x
        == replacements[0].base_x + rendered_width + dialog.letter_spacing
    )
    dialog._dirty = False
    dialog.close()


def test_scale_slider_seeds_pix_cache(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    item = dialog.items[0]
    item.setSelected(True)
    dialog._begin_slider_undo()
    dialog.scale_slider.setValue(180)
    dialog._end_slider_undo()
    assert item.scale_pct == 180
    assert list(item._pix_cache.keys()) == [
        (180, 0, 100, 100, False, False, 100, 0)
    ]
    dialog._dirty = False
    dialog.close()


def test_character_controls_gate_on_selection(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        assert not dialog.offset_x_spin.isEnabled()
        assert not dialog.rotation_quality.isEnabled()
        assert all(not btn.isEnabled() for btn in dialog._selection_action_buttons)

        dialog.items[0].setSelected(True)
        assert dialog.offset_x_spin.isEnabled()
        assert dialog.rotation_quality.isEnabled()
        assert all(not btn.isEnabled() for btn in dialog._selection_action_buttons)

        dialog.items[1].setSelected(True)
        assert all(btn.isEnabled() for btn in dialog._selection_action_buttons)
    finally:
        dialog.close()


def test_select_all_only_selects_visible(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        dialog.items[0].setVisible(False)
        dialog._select_all()
        assert len(dialog._selected()) == len(dialog.items) - 1
    finally:
        dialog.close()


def test_render_character_stretches_per_axis(qapp, tmp_path):
    from PIL import Image

    from editor import QUALITY_FAST_ROTSPRITE, render_character

    sprite = Image.new("RGBA", (10, 6), (255, 0, 0, 255))
    assert render_character(sprite, 100, 0, QUALITY_FAST_ROTSPRITE, 200, 50).size == (
        20,
        3,
    )
    assert render_character(sprite, 150, 0, QUALITY_FAST_ROTSPRITE, 100, 100).size == (
        15,
        9,
    )
    assert render_character(sprite, 100, 0, QUALITY_FAST_ROTSPRITE, 100, 100).size == (
        10,
        6,
    )


def test_stretch_updates_item_and_undo_restores(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        base_w = item.pixmap().width()
        dialog.items[0].setSelected(True)
        dialog.stretch_x_spin.setValue(200)
        assert item.stretch_x == 200
        assert item.pixmap().width() == base_w * 2
        assert dialog.undo_stack.can_undo()
        dialog._undo()
        assert item.stretch_x == 100
        assert item.pixmap().width() == base_w
    finally:
        dialog.close()


def test_stretch_survives_capture_apply_roundtrip(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.stretch_x = 150
        item.stretch_y = 250
        item.apply_state(item.capture_state())
        assert (item.stretch_x, item.stretch_y) == (150, 250)
    finally:
        dialog.close()


def test_flip_renders_mirrored_pixels(qapp, tmp_path):
    from PIL import Image

    from editor import QUALITY_FAST_ROTSPRITE, render_character

    sprite = Image.new("RGBA", (3, 1))
    sprite.putpixel((0, 0), (255, 0, 0, 255))
    sprite.putpixel((2, 0), (0, 255, 0, 255))
    out = render_character(
        sprite, 100, 0, QUALITY_FAST_ROTSPRITE, 100, 100, True, False
    )
    assert out.getpixel((0, 0)) == (0, 255, 0, 255)
    assert out.getpixel((2, 0)) == (255, 0, 0, 255)
    both = render_character(
        sprite, 100, 0, QUALITY_FAST_ROTSPRITE, 100, 100, True, True
    )
    assert both.getpixel((0, 0)) == (0, 255, 0, 255)


def test_flip_toggles_and_undoes(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        before = bytes(item.pixmap().toImage().constBits())
        dialog._flip_selection("h")
        assert item.flip_h is True
        assert bytes(item.pixmap().toImage().constBits()) != before
        dialog._undo()
        assert item.flip_h is False
        assert bytes(item.pixmap().toImage().constBits()) == before
    finally:
        dialog._dirty = False
        dialog.close()


def test_rotate_ninety_button_is_exact(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        base_w, base_h = item.sprite.width, item.sprite.height
        dialog._rotate_selection_90(1)
        assert item.rotation == 90
        assert item.pixmap().width() == base_h
        assert item.pixmap().height() == base_w
        dialog._rotate_selection_90(-1)
        assert item.rotation == 0
        assert item.pixmap().width() == base_w
        assert item.pixmap().height() == base_h
    finally:
        dialog._dirty = False
        dialog.close()


def test_reset_transform_restores_defaults(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        item.scale_pct = 250
        item.stretch_x = 200
        item.rotation = 45
        item.flip_h = True
        dialog._reset_transform_selection()
        assert (
            item.scale_pct,
            item.stretch_x,
            item.stretch_y,
            item.rotation,
            item.flip_h,
            item.flip_v,
        ) == (100, 100, 100, 0, False, False)
        assert dialog.undo_stack.can_undo()
        dialog._undo()
        assert item.scale_pct == 250
    finally:
        dialog._dirty = False
        dialog.close()


def test_transform_box_hit_zones(qapp, tmp_path):
    from PySide6.QtCore import QPointF

    dialog = make_dialog(tmp_path)
    try:
        dialog.items[0].setSelected(True)
        box = dialog.scene.transform_box
        rect = dialog.scene._item_scene_rect(dialog.items[0])
        assert box.hit(rect.topLeft()) == ("scale", "nw")
        assert box.hit(QPointF(rect.center().x(), rect.top())) == ("stretch", "n")
        outside = rect.topLeft() + QPointF(8, -8)
        assert box.hit(outside) == ("rotate", "nw")
        far = rect.center() + QPointF(rect.width(), rect.height())
        assert box.hit(far) is None
    finally:
        dialog._dirty = False
        dialog.close()


def test_transform_box_scale_gesture(qapp, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtCore import Qt as QtCore

    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        box = dialog.scene.transform_box
        rect = dialog.scene._item_scene_rect(item)
        anchor = rect.topLeft()
        start = rect.bottomRight()
        box.start("scale", "se", start)
        end = anchor + (start - anchor) * 1.5
        box.update(QPointF(end), QtCore.KeyboardModifier.NoModifier)
        box.commit()
        assert item.scale_pct == 100
        assert item.stretch_x == 150
        assert item.stretch_y == 150
        assert box._gesture is None
        assert dialog.undo_stack.can_undo()
        dialog._undo()
        assert item.stretch_x == 100
        assert item.stretch_y == 100
    finally:
        dialog._dirty = False
        dialog.close()


def test_transform_box_stretch_gesture(qapp, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtCore import Qt as QtCore

    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        box = dialog.scene.transform_box
        rect = dialog.scene._item_scene_rect(item)
        box.start("stretch", "e", QPointF(rect.right(), rect.center().y()))
        span = rect.right() - rect.left()
        box.update(
            QPointF(rect.left() + span * 2, rect.center().y()),
            QtCore.KeyboardModifier.NoModifier,
        )
        box.commit()
        assert item.stretch_x == 200
        assert item.stretch_y == 100
        dialog._undo()
        assert item.stretch_x == 100
    finally:
        dialog._dirty = False
        dialog.close()


def test_transform_box_rotate_gesture_snaps_with_shift(qapp, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtCore import Qt as QtCore

    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        box = dialog.scene.transform_box
        rect = dialog.scene._item_scene_rect(item)
        center = rect.center()
        radius = rect.width()
        box.start("rotate", "se", center + QPointF(radius, 0))
        box.update(center + QPointF(0, radius), QtCore.KeyboardModifier.ShiftModifier)
        box.commit()
        assert item.rotation == 90
        dialog._undo()
        assert item.rotation == 0
    finally:
        dialog._dirty = False
        dialog.close()


def test_transform_box_multi_selection_scales_together(qapp, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtCore import Qt as QtCore

    dialog = make_dialog(tmp_path)
    try:
        a, b = dialog.items[0], dialog.items[1]
        a.setSelected(True)
        b.setSelected(True)
        box = dialog.scene.transform_box
        assert box._multi
        assert box._rect_item.isVisible()
        union = box._rect_item.rect()
        assert box.hit(QPointF(union.center().x(), union.top())) == (
            "stretch", "n"
        )
        assert box.hit(union.topRight()) == ("scale", "ne")
        anchor = union.topLeft()
        start = union.bottomRight()
        box.start("scale", "se", start)
        box.update(
            QPointF(anchor + (start - anchor) * 1.5),
            QtCore.KeyboardModifier.NoModifier,
        )
        box.commit()
        assert a.stretch_x == 150
        assert a.stretch_y == 150
        assert b.stretch_x == 150
        assert b.stretch_y == 150
        assert a.scale_pct == 100
        assert b.scale_pct == 100
        dialog._undo()
        assert a.stretch_x == 100
        assert b.stretch_x == 100
    finally:
        dialog._dirty = False
        dialog.close()


def test_transform_box_multi_selection_stretches_edges(qapp, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtCore import Qt as QtCore

    dialog = make_dialog(tmp_path)
    try:
        a, b = dialog.items[0], dialog.items[1]
        a.setSelected(True)
        b.setSelected(True)
        box = dialog.scene.transform_box
        union = box._rect_item.rect()
        assert box._multi
        assert box._handles["e"].isVisible()
        assert not box._rotate_zones["se"].isVisible()

        box.start("stretch", "e", QPointF(union.right(), union.center().y()))
        span = union.right() - union.left()
        box.update(
            QPointF(union.left() + span * 2, union.center().y()),
            QtCore.KeyboardModifier.NoModifier,
        )
        box.commit()
        assert a.stretch_x == 200
        assert b.stretch_x == 200
        assert a.stretch_y == 100
        assert b.stretch_y == 100
        dialog._undo()
        assert a.stretch_x == 100
        assert b.stretch_x == 100

        box.start("stretch", "n", QPointF(union.center().x(), union.top()))
        span = union.bottom() - union.top()
        box.update(
            QPointF(union.center().x(), union.bottom() - span * 0.5),
            QtCore.KeyboardModifier.NoModifier,
        )
        box.commit()
        assert a.stretch_y == 50
        assert b.stretch_y == 50
        assert a.stretch_x == 100
    finally:
        dialog._dirty = False
        dialog.close()


def test_panel_width_tracks_content(qapp, tmp_path):
    from PySide6.QtCore import Qt

    dialog = make_dialog(tmp_path)
    try:
        scroll = dialog.panel_scroll
        content = scroll.widget()
        assert scroll.minimumWidth() >= content.sizeHint().width()
        assert (
            scroll.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
    finally:
        dialog._dirty = False
        dialog.close()


def test_spacing_group_starts_collapsed(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        assert dialog.character_group.isChecked()
        assert not dialog.global_group.isChecked()
        assert dialog.letter_spacing_spin.isHidden()
        assert not dialog.offset_x_spin.isHidden()
        dialog.global_group.setChecked(True)
        assert dialog.global_group.isChecked()
        assert not dialog.letter_spacing_spin.isHidden()
    finally:
        dialog._dirty = False
        dialog.close()


def test_background_bounds_expand_with_content(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        scene = dialog.scene
        canvas_w, canvas_h = dialog.canvas_size
        base = scene._background_bounds()
        assert base.width() >= canvas_w
        assert base.height() >= canvas_h

        item = dialog.items[-1]
        item.dx += canvas_w + 50
        item.dy += canvas_h + 40
        item._place()
        grown = scene._background_bounds()
        assert grown.right() >= item.dx + item.pixmap().width()
        assert grown.bottom() >= item.dy + item.pixmap().height()

        item.dx = 0
        item.dy = 0
        item._place()
        assert scene._background_bounds().width() <= base.width() + 0.5
    finally:
        dialog._dirty = False
        dialog.close()


def test_transform_updates_coalesce_until_commit(qapp, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtCore import Qt as QtCore

    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        box = dialog.scene.transform_box
        rect = dialog.scene._item_scene_rect(item)
        anchor = rect.topLeft()
        start = rect.bottomRight()
        box.start("scale", "se", start)
        box.update(QPointF(anchor + (start - anchor) * 1.5), QtCore.KeyboardModifier.NoModifier)
        assert item.stretch_x == 100
        assert box._pending is not None
        assert box._update_timer.isActive()
        box._flush_update()
        assert item.stretch_x == 150
        assert box._pending is None
        box.commit()
        assert item.stretch_x == 150
        dialog._undo()
        assert item.stretch_x == 100
    finally:
        dialog._dirty = False
        dialog.close()


def test_multi_scale_clamps_as_one(qapp, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtCore import Qt as QtCore

    dialog = make_dialog(tmp_path)
    try:
        a, b = dialog.items[0], dialog.items[1]
        b.stretch_x = 300
        b.stretch_y = 300
        b.update_pixmap()
        a.setSelected(True)
        b.setSelected(True)
        box = dialog.scene.transform_box
        union = box._rect_item.rect()
        anchor = union.topLeft()
        start = union.bottomRight()
        box.start("scale", "se", start)
        box.update(
            QPointF(anchor + (start - anchor) * 1.5),
            QtCore.KeyboardModifier.NoModifier,
        )
        box.commit()
        limit = 400 / 300
        assert b.stretch_x == 400
        assert a.stretch_x == round(100 * limit)
        for item in (a, b):
            assert item.pos().x() == int(item.pos().x())
            assert item.pos().y() == int(item.pos().y())
        dialog._undo()
        assert a.stretch_x == 100
        assert b.stretch_x == 300
        assert b.scale_pct == 100
    finally:
        dialog._dirty = False
        dialog.close()


def test_multi_stretch_clamps_as_one(qapp, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtCore import Qt as QtCore

    dialog = make_dialog(tmp_path)
    try:
        a, b = dialog.items[0], dialog.items[1]
        b.stretch_x = 390
        b.update_pixmap()
        a.setSelected(True)
        b.setSelected(True)
        box = dialog.scene.transform_box
        union = box._rect_item.rect()
        box.start("stretch", "e", QPointF(union.right(), union.center().y()))
        span = union.right() - union.left()
        box.update(
            QPointF(union.left() + span * 2, union.center().y()),
            QtCore.KeyboardModifier.NoModifier,
        )
        box.commit()
        assert b.stretch_x == 400
        assert a.stretch_x == round(100 * (400 / 390))
        assert a.stretch_y == 100
        assert b.stretch_y == 100
    finally:
        dialog._dirty = False
        dialog.close()


def test_scene_rect_grows_with_content(qapp, tmp_path):
    from editor import SCENE_PADDING

    dialog = make_dialog(tmp_path)
    try:
        scene = dialog.scene
        canvas_w, _canvas_h = dialog.canvas_size
        assert scene.sceneRect().width() >= canvas_w + 2 * SCENE_PADDING
        item = dialog.items[-1]
        item.dx += canvas_w + 200 - (item.base_x + item.dx)
        item._place()
        dialog._update_scene_rect()
        assert scene.sceneRect().right() >= item.pos().x() + item.pixmap().width()
        assert scene.sceneRect().contains(item.sceneBoundingRect())
    finally:
        dialog._dirty = False
        dialog.close()


def test_replace_inherits_transform(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.stretch_x = 150
        item.flip_h = True
        item.update_pixmap()
        before = dialog._replace_with_string(item, ["H", "I"])
        dialog._push(before)
        replacements = [
            i for i in dialog.items if not i.layout_anchored and i.isVisible()
        ]
        assert len(replacements) == 2
        for ni in replacements:
            assert (ni.stretch_x, ni.flip_h) == (150, True)
        first, second = replacements
        assert second.base_x > first.base_x
        dialog._undo()
        assert item.isVisible()
        assert all(
            not i.isVisible() for i in dialog.items if not i.layout_anchored
        )
    finally:
        dialog._dirty = False
        dialog.close()


def test_scale_slider_positions_use_stretched_size(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        item.stretch_y = 300
        item.update_pixmap()
        stretched_h = item.pixmap().height()
        dialog._begin_slider_undo()
        dialog.scale_slider.setValue(200)
        dialog._end_slider_undo()
        assert item.scale_pct == 200
        assert item.pixmap().height() == stretched_h * 2
        assert item.pos().y() == int(item.pos().y())
        dialog._undo()
        assert item.scale_pct == 100
    finally:
        dialog._dirty = False
        dialog.close()


def test_non_quarter_rotation_renders_clockwise(qapp, tmp_path):
    from PIL import Image

    from editor import QUALITY_FAST_ROTSPRITE, render_character

    sprite = Image.new("RGBA", (20, 20))
    for y in range(8):
        for x in range(8):
            sprite.putpixel((x, y), (255, 0, 0, 255))
    out = render_character(sprite, 100, 45, QUALITY_FAST_ROTSPRITE)
    red = [
        (x, y)
        for y in range(out.height)
        for x in range(out.width)
        if out.getpixel((x, y))[3] == 255
    ]
    assert red
    center_x = (out.width - 1) / 2
    center_y = (out.height - 1) / 2
    mean_x = sum(x for x, _ in red) / len(red)
    mean_y = sum(y for _, y in red) / len(red)
    assert mean_x >= center_x
    assert mean_y <= center_y


def test_scene_rect_tracks_nudged_items(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        for _ in range(40):
            dialog._nudge(10, 0)
        dialog._sync_panel()
        right = item.pos().x() + item.pixmap().width()
        assert dialog.scene.sceneRect().right() >= right
    finally:
        dialog._dirty = False
        dialog.close()


def test_align_and_spread_keep_integer_positions(qapp, tmp_path):

    dialog = make_dialog(tmp_path)
    try:
        a, b = dialog.items[0], dialog.items[1]
        b.scale_pct = 50
        b.update_pixmap()
        a.setSelected(True)
        b.setSelected(True)
        for mode in ("left", "center", "right", "top", "middle", "bottom"):
            dialog._align_selection(mode)
            for item in (a, b):
                assert item.pos().x() == int(item.pos().x()), (mode, item.pos())
                assert item.pos().y() == int(item.pos().y()), (mode, item.pos())
        dialog._distribute_selection("x")
        dialog._distribute_selection("y")
        for item in (a, b):
            assert item.pos().x() == int(item.pos().x())
            assert item.pos().y() == int(item.pos().y())
    finally:
        dialog._dirty = False
        dialog.close()


def test_undo_blocked_during_slider_gesture(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        dialog._begin_slider_undo()
        dialog.scale_slider.setValue(250)
        dialog._undo()
        assert item.scale_pct == 250
        dialog._end_slider_undo()
        assert item.scale_pct == 250
        dialog._undo()
        assert item.scale_pct == 100
    finally:
        dialog._dirty = False
        dialog.close()


def test_view_zoom_steps_through_aseprite_ladder(qapp, tmp_path):
    from editor import ZOOM_SCALES

    dialog = make_dialog(tmp_path)
    try:
        view = dialog.view
        view.zoom_to(1.0)
        view.zoom_in()
        assert view.transform().m11() == 2.0
        view.zoom_out()
        assert view.transform().m11() == 1.0
        for _ in range(40):
            view.zoom_out()
        assert view.transform().m11() == ZOOM_SCALES[0]
        for _ in range(80):
            view.zoom_in()
        assert view.transform().m11() == ZOOM_SCALES[-1]
    finally:
        dialog._dirty = False
        dialog.close()


def test_zoom_entry_snaps_input_to_nearest_preset(qapp, tmp_path):
    from editor import ZOOM_SCALES

    dialog = make_dialog(tmp_path)
    try:
        entry = dialog.zoom_entry
        entry.setText("33%")
        entry._commit()
        assert abs(dialog.view.transform().m11() - ZOOM_SCALES[10]) < 1e-9
        entry.setText("9999")
        entry._commit()
        assert dialog.view.transform().m11() == ZOOM_SCALES[-1]
        entry.setText("nonsense")
        entry._commit()
        assert entry.text() == f"{round(ZOOM_SCALES[-1] * 100)}%"
    finally:
        dialog._dirty = False
        dialog.close()


def test_escape_clears_selection_before_closing(qapp, tmp_path, monkeypatch):
    dialog = make_dialog(tmp_path)
    try:
        dialog.items[0].setSelected(True)
        rejects = []
        monkeypatch.setattr(dialog, "reject", lambda: rejects.append(True))
        dialog._escape_pressed()
        assert rejects == []
        assert not dialog.items[0].isSelected()
        dialog._escape_pressed()
        assert rejects == [True]
    finally:
        dialog._dirty = False
        dialog.close()


def test_icon_only_buttons_have_accessible_names(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        assert dialog.zoom_in_btn.accessibleName() == "Zoom in"
        assert dialog.zoom_out_btn.accessibleName() == "Zoom out"
        assert dialog.help_btn.accessibleName() == "Editor help"
    finally:
        dialog._dirty = False
        dialog.close()


def test_rotated_render_runs_on_worker_thread(qapp, tmp_path, monkeypatch):
    import threading

    import editor as editor_module

    dialog = make_dialog(tmp_path)
    try:
        threads = []
        original = editor_module.render_character

        def spy(*args, **kwargs):
            threads.append(threading.get_ident())
            return original(*args, **kwargs)

        monkeypatch.setattr(editor_module, "render_character", spy)
        item = dialog.items[0]
        item.rotation = 45
        item.update_pixmap()
        assert item._pix_cache.get(item._cache_key()) is None
        assert not item.pixmap().isNull()
        for _ in range(500):
            if item._pix_cache.get(item._cache_key()) is not None:
                break
            qapp.processEvents()
        assert item._pix_cache.get(item._cache_key()) is not None
        assert any(t != threading.get_ident() for t in threads)
    finally:
        dialog._dirty = False
        dialog.close()


def test_dialog_destroy_under_pending_renders_does_not_abort(qapp, tmp_path):
    import gc

    dialog = make_dialog(tmp_path)
    for item in dialog.items:
        item.rotation = 217
        item.update_pixmap()
    dialog._dirty = False
    dialog.close()
    del dialog
    gc.collect()
    qapp.processEvents()


def test_space_drag_pans_the_view(qapp, tmp_path):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    dialog = make_dialog(tmp_path)
    try:
        view = dialog.view
        view.zoom_to(4.0)
        h0 = view.horizontalScrollBar().value()
        v0 = view.verticalScrollBar().value()
        QTest.keyPress(view, Qt.Key_Space)
        assert view._space_pan
        QTest.mousePress(view.viewport(), Qt.LeftButton, pos=QPoint(300, 300))
        assert view._pan_start is not None
        QTest.mouseMove(view.viewport(), QPoint(200, 200))
        QTest.mouseRelease(
            view.viewport(), Qt.LeftButton, pos=QPoint(200, 200)
        )
        QTest.keyRelease(view, Qt.Key_Space)
        assert not view._space_pan
        assert view._pan_start is None
        assert view.horizontalScrollBar().value() == h0 + 100
        assert view.verticalScrollBar().value() == v0 + 100
    finally:
        dialog._dirty = False
        dialog.close()


def test_undo_redo_buttons_colored_only_when_available(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        assert not dialog.undo_btn.isEnabled()
        assert dialog.undo_btn.styleSheet() == ""
        assert not dialog.redo_btn.isEnabled()
        assert dialog.redo_btn.styleSheet() == ""
        dialog.items[0].setSelected(True)
        dialog._nudge(2, 0)
        assert dialog.undo_btn.isEnabled()
        assert "color:" in dialog.undo_btn.styleSheet()
        assert dialog.redo_btn.styleSheet() == ""
        dialog._undo()
        assert not dialog.undo_btn.isEnabled()
        assert dialog.undo_btn.styleSheet() == ""
        assert "color:" in dialog.redo_btn.styleSheet()
    finally:
        dialog._dirty = False
        dialog.close()


def test_checker_brush_is_cached_and_scene_anchored(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        brush = dialog.scene._checker_brush(2.0)
        assert brush is dialog.scene._checker_brush(2.0)
        assert dialog.scene._checker_brush(4.0) is not brush
    finally:
        dialog._dirty = False
        dialog.close()


def test_render_character_opacity_scales_alpha():
    from PIL import Image

    from editor import render_character

    sprite = Image.new("RGBA", (2, 2), (255, 0, 0, 200))
    out = render_character(sprite, opacity=50)
    assert out.getpixel((0, 0)) == (255, 0, 0, 100)
    assert render_character(sprite).getpixel((0, 0)) == (255, 0, 0, 200)
    assert sprite.getpixel((0, 0)) == (255, 0, 0, 200)


def test_shift_sprite_hue_rotates_colors_and_keeps_neutrals():
    import colorsys

    from PIL import Image

    from editor import shift_sprite_hue

    sprite = Image.new("RGBA", (3, 1))
    sprite.putpixel((0, 0), (255, 0, 0, 255))
    sprite.putpixel((1, 0), (248, 248, 248, 255))
    sprite.putpixel((2, 0), (0, 0, 0, 255))
    out = shift_sprite_hue(sprite, 120)
    assert out.getpixel((1, 0)) == (248, 248, 248, 255)
    assert out.getpixel((2, 0)) == (0, 0, 0, 255)
    r, g, b = out.getpixel((0, 0))[:3]
    hue = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0] * 360
    assert abs(hue - 120) <= 2
    assert sprite.getpixel((0, 0)) == (255, 0, 0, 255)


def test_cache_key_includes_opacity_and_hue(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        key = item._cache_key()
        assert len(key) == 8
        assert key[6] == 100 and key[7] == 0
        item.opacity = 50
        item.hue_shift = 90
        assert item._cache_key() != key
        assert item.tinted_sprite() is not item.sprite
        item.hue_shift = 0
        assert item.tinted_sprite() is item.sprite
    finally:
        dialog._dirty = False
        dialog.close()


def test_opacity_and_hue_apply_slider_sync_and_undo(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        dialog.opacity_spin.setValue(40)
        assert item.opacity == 40
        assert dialog.opacity_slider.value() == 40
        dialog.hue_spin.setValue(120)
        assert item.hue_shift == 120
        assert dialog.hue_slider.value() == 120
        dialog._undo()
        assert item.hue_shift == 0 and item.opacity == 40
        dialog._undo()
        assert item.opacity == 100
        dialog.opacity_spin.setValue(30)
        dialog._reset_transform_selection()
        assert item.opacity == 100 and item.hue_shift == 0
    finally:
        dialog._dirty = False
        dialog.close()


def test_duplicate_selection_copies_transforms_and_undo_hides(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        item.scale_pct = 150
        item.opacity = 60
        item.hue_shift = 45
        item.rotation = 30
        count = len(dialog.items)
        dialog._duplicate_selection()
        assert len(dialog.items) == count + 1
        ni = dialog.items[-1]
        assert ni.char == item.char
        assert ni.scale_pct == 150
        assert ni.opacity == 60
        assert ni.hue_shift == 45
        assert ni.rotation == 30
        assert ni.isVisible()
        assert ni.isSelected()
        dialog._undo()
        assert not ni.isVisible()
        dialog._redo()
        assert ni.isVisible()
    finally:
        dialog._dirty = False
        dialog.close()


def test_z_order_front_back_with_undo_and_export(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        first, second = dialog.items[0], dialog.items[1]
        first.setSelected(True)
        dialog._reorder_selection(True)
        assert first.zValue() > second.zValue()
        order = [
            id(item) for item in sorted(dialog.items, key=lambda e: e.zValue())
        ]
        assert order[-1] == id(first)
        dialog._undo()
        assert first.zValue() == 0.0 and second.zValue() == 0.0
        dialog._reorder_selection(False)
        assert first.zValue() < second.zValue()
        order = [
            id(item) for item in sorted(dialog.items, key=lambda e: e.zValue())
        ]
        assert order[0] == id(first)
        dialog._undo()
        second.dx = first.dx + 5
        second.dy = first.dy + 5
        assert dialog.export_image() is True
    finally:
        dialog._dirty = False
        dialog.close()


def _rotated_offset(angle_deg, dx, dy):
    import math

    rad = math.radians(angle_deg)
    return QPointF(
        dx * math.cos(rad) - dy * math.sin(rad),
        dx * math.sin(rad) + dy * math.cos(rad),
    )


def test_transform_box_hit_works_rotated(qapp, tmp_path):

    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        item.rotation = 90
        item.update_pixmap()
        box = dialog.scene.transform_box
        rect = box._rect_item.rect()
        center = rect.center()
        corner = center + _rotated_offset(90, -rect.width() / 2, -rect.height() / 2)
        assert box.hit(corner) == ("scale", "nw")
        edge = center + _rotated_offset(90, 0, -rect.height() / 2)
        assert box.hit(edge) == ("stretch", "n")
    finally:
        dialog._dirty = False
        dialog.close()


def test_stretch_on_rotated_item_follows_item_axes(qapp, tmp_path):

    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        item.rotation = 90
        item.update_pixmap()
        box = dialog.scene.transform_box
        rect = box._rect_item.rect()
        center = rect.center()
        anchor = center + _rotated_offset(90, -rect.width() / 2, 0)
        start = center + _rotated_offset(90, rect.width() / 2, 0)
        box.start("stretch", "e", start)
        box.update(
            center + _rotated_offset(90, rect.width() * 1.5, 0), Qt.NoModifier
        )
        box.commit()
        assert item.stretch_x == 200
        new_rect = box._rect_item.rect()
        new_anchor = new_rect.center() + _rotated_offset(
            90, -new_rect.width() / 2, 0
        )
        assert abs(new_anchor.x() - anchor.x()) <= 1
        assert abs(new_anchor.y() - anchor.y()) <= 1
    finally:
        dialog._dirty = False
        dialog.close()


def test_scale_on_rotated_item_pins_opposite_corner(qapp, tmp_path):

    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        item.rotation = 90
        item.update_pixmap()
        box = dialog.scene.transform_box
        rect = box._rect_item.rect()
        center = rect.center()
        anchor = center + _rotated_offset(90, -rect.width() / 2, -rect.height() / 2)
        start = center + _rotated_offset(90, rect.width() / 2, rect.height() / 2)
        box.start("scale", "se", start)
        box.update(
            center + _rotated_offset(90, rect.width() * 1.5, rect.height() * 1.5),
            Qt.NoModifier,
        )
        box.commit()
        assert item.scale_pct == 100
        assert item.stretch_x == 200
        assert item.stretch_y == 200
        new_rect = dialog.scene._item_scene_rect(item)
        old_dist = ((center.x() - anchor.x()) ** 2 + (center.y() - anchor.y()) ** 2) ** 0.5
        new_center = new_rect.center()
        new_dist = (
            (new_center.x() - anchor.x()) ** 2 + (new_center.y() - anchor.y()) ** 2
        ) ** 0.5
        assert abs(new_dist - 2 * old_dist) <= 1.5
    finally:
        dialog._dirty = False
        dialog.close()


def test_marquee_selects_intersecting_characters(qapp, tmp_path):
    from PySide6.QtTest import QTest

    dialog = make_dialog(tmp_path)
    try:
        view = dialog.view
        first, second = dialog.items[0], dialog.items[1]
        second.dx += 200
        second._place()
        band_rect = first.sceneBoundingRect()
        press_at = view.mapFromScene(
            band_rect.topLeft() - QPointF(5, 5)
        )
        release_at = view.mapFromScene(band_rect.bottomRight() + QPointF(5, 5))
        QTest.mousePress(
            view.viewport(), Qt.LeftButton, pos=press_at
        )
        assert dialog.scene._band_start is not None
        QTest.mouseMove(view.viewport(), release_at)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=release_at)
        assert first.isSelected()
        assert not second.isSelected()
    finally:
        dialog._dirty = False
        dialog.close()


def test_marquee_shift_adds_and_alt_subtracts(qapp, tmp_path):
    from PySide6.QtTest import QTest

    dialog = make_dialog(tmp_path)
    try:
        view = dialog.view
        first, second = dialog.items[0], dialog.items[1]
        second.dx += 200
        second._place()
        first.setSelected(True)

        def drag_over(item, modifiers):
            band = item.sceneBoundingRect()
            press_at = view.mapFromScene(band.topLeft() - QPointF(5, 5))
            release_at = view.mapFromScene(band.bottomRight() + QPointF(5, 5))
            QTest.mousePress(view.viewport(), Qt.LeftButton, pos=press_at)
            QTest.mouseMove(view.viewport(), release_at)
            QTest.mouseRelease(view.viewport(), Qt.LeftButton, modifiers, release_at)

        drag_over(second, Qt.KeyboardModifier.ShiftModifier)
        assert first.isSelected() and second.isSelected()
        drag_over(second, Qt.KeyboardModifier.AltModifier)
        assert first.isSelected() and not second.isSelected()
    finally:
        dialog._dirty = False
        dialog.close()


def test_marquee_plain_click_clears_and_escape_cancels(qapp, tmp_path):
    from PySide6.QtTest import QTest

    dialog = make_dialog(tmp_path)
    try:
        view = dialog.view
        dialog.items[0].setSelected(True)
        empty = QPointF(
            dialog.scene._background_bounds().left() - 80,
            dialog.scene._background_bounds().center().y(),
        )
        pos = view.mapFromScene(empty)
        QTest.mousePress(view.viewport(), Qt.LeftButton, pos=pos)
        assert dialog.scene._band_start is not None
        dialog._escape_pressed()
        assert dialog.scene._band_start is None
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=pos)
        QTest.mousePress(view.viewport(), Qt.LeftButton, pos=pos)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=pos)
        assert not dialog.items[0].isSelected()
    finally:
        dialog._dirty = False
        dialog.close()


def test_sync_panel_clamps_huge_offsets_into_spin_range(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        item.dx = 2_470_000_000
        item.dy = -2_470_000_000
        dialog._sync_panel()
        assert dialog.offset_x_spin.value() == dialog.offset_x_spin.maximum()
        assert dialog.offset_y_spin.value() == dialog.offset_y_spin.minimum()
    finally:
        dialog._dirty = False
        dialog.close()


def test_corner_scale_is_free_per_axis(qapp, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtCore import Qt as QtCore

    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        box = dialog.scene.transform_box
        rect = dialog.scene._item_scene_rect(item)
        anchor = rect.topLeft()
        start = rect.bottomRight()
        box.start("scale", "se", start)
        end = QPointF(
            anchor.x() + (start.x() - anchor.x()) * 1.5,
            anchor.y() + (start.y() - anchor.y()) * 1.25,
        )
        box.update(end, QtCore.KeyboardModifier.NoModifier)
        box.commit()
        assert item.stretch_x == 150
        assert item.stretch_y == 125
        new_rect = dialog.scene._item_scene_rect(item)
        assert abs(new_rect.topLeft().x() - anchor.x()) <= 1
        assert abs(new_rect.topLeft().y() - anchor.y()) <= 1
    finally:
        dialog._dirty = False
        dialog.close()


def test_corner_scale_with_shift_keeps_aspect_ratio(qapp, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtCore import Qt as QtCore

    dialog = make_dialog(tmp_path)
    try:
        item = dialog.items[0]
        item.setSelected(True)
        box = dialog.scene.transform_box
        rect = dialog.scene._item_scene_rect(item)
        anchor = rect.topLeft()
        start = rect.bottomRight()
        box.start("scale", "se", start)
        end = QPointF(
            anchor.x() + (start.x() - anchor.x()) * 1.5,
            anchor.y() + (start.y() - anchor.y()) * 1.5,
        )
        box.update(end, QtCore.KeyboardModifier.ShiftModifier)
        box.commit()
        assert item.stretch_x == item.stretch_y
        assert item.stretch_x != 100
    finally:
        dialog._dirty = False
        dialog.close()
