"""图片文字匹配算法与图片 UI 的单元/渲染测试（不依赖真实 OCR 引擎）。"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from engineerdiff.image.engine import ImageCompareError, compare_images
from engineerdiff.image.matcher import match_pages, normalize_text, text_similarity
from engineerdiff.models import (
    BBox,
    DiffKind,
    ImageComparison,
    ImageOptions,
    OcrBox,
    OcrPage,
    Severity,
)
from engineerdiff.ocr.engine import OcrCancelled, OcrError
from tests.assets.generate_images import (
    DEFAULT_TEXTS,
    ensure_generated_dir,
    render_ui_screenshot,
)


# ---------------------------------------------------------------------------
# 构造合成 OcrPage（坐标来自真实绘制文字的墨迹 bbox）
# ---------------------------------------------------------------------------


def _page_from_meta(
    meta: dict,
    *,
    default_confidence: float = 0.98,
    confidences: dict[str, float] | None = None,
    drop: set[str] | None = None,
    shuffle: bool = False,
    extra_boxes: list[tuple[str, str, float, BBox]] | None = None,
    path: str | None = None,
) -> tuple[OcrPage, dict[str, OcrBox]]:
    page = OcrPage(
        path=str(path) if path is not None else meta["path"],
        width=int(meta["image_size"][0]),
        height=int(meta["image_size"][1]),
    )
    items = list(meta["texts"].items())
    if shuffle:
        items = items[::2] + items[1::2]
    specs: list[tuple[str, str, float, BBox]] = []
    for key, info in items:
        if drop and key in drop:
            continue
        x0, y0, x1, y1 = info["bbox"]
        confidence = (confidences or {}).get(key, default_confidence)
        specs.append((key, info["text"], confidence, BBox(float(x0), float(y0), float(x1 - x0), float(y1 - y0))))
    for key, text, confidence, bbox in extra_boxes or []:
        specs.append((key, text, confidence, bbox))
    by_key: dict[str, OcrBox] = {}
    for index, (key, text, confidence, bbox) in enumerate(specs):
        box = OcrBox(id=index, text=text, confidence=confidence, bbox=bbox, raw_text=text)
        page.boxes.append(box)
        by_key[key] = box
    return page, by_key


def _standard_pair(tmp_path: Path):
    left_meta = render_ui_screenshot(tmp_path / "left.png")
    right_meta = render_ui_screenshot(
        tmp_path / "right.png",
        scale=1.2,
        offset=(30, 18),
        values={"version": "1.2.4", "value_in_1": "1.80"},
    )
    left_page, left_boxes = _page_from_meta(left_meta)
    right_page, right_boxes = _page_from_meta(right_meta, shuffle=True)
    return left_meta, right_meta, left_page, left_boxes, right_page, right_boxes


def _diff_for(diffs, left_text: str):
    for diff in diffs:
        if diff.left is not None and diff.left.text == left_text:
            return diff
    raise AssertionError(f"未找到左文本为 {left_text!r} 的差异：{[(d.left.text if d.left else d.right.text) for d in diffs]}")


# ---------------------------------------------------------------------------
# 匹配算法
# ---------------------------------------------------------------------------


def test_text_similarity_normalizes_confusables_and_widths():
    assert text_similarity("1.2.3", "1.2.3") == 1.0
    assert text_similarity("ＡＢＣ", "ABC") == 1.0
    assert text_similarity("abc", "ABC") == 1.0
    # 0/O、1/I/l 只用于评分归一：高相似但不是相同文本
    assert text_similarity("0.00", "O.00") >= 0.9
    assert text_similarity("1.50", "l.50") >= 0.9
    assert text_similarity("1.50", "1.80") > 0.5
    assert text_similarity("投入", "退出") < 0.5
    assert text_similarity("", "1.50") == 0.0
    assert normalize_text("　装置 版本　") == "装置版本"


def test_duplicate_fields_matched_by_context_not_order(tmp_path: Path):
    """不同分辨率 + 平移 + 右图乱序时，重复“投入/退出/0.00”仍靠上下文正确配对。"""
    _, _, left_page, left_boxes, right_page, right_boxes = _standard_pair(tmp_path)
    diffs, info = match_pages(left_page, right_page, ImageOptions())

    assert info["matched_count"] == len(left_page.boxes) == len(right_page.boxes)
    assert info["only_left"] == [] and info["only_right"] == []
    assert info["reliable"] is True
    assert abs(info["scale"] - 1.0 / 1.2) < 0.08

    # 只有版本号与小数发生变化；重复的 0.00 / 投入 / 退出 不产生假差异
    changed = sorted(
        (diff.left.text, diff.right.text)
        for diff in diffs
        if diff.left is not None and diff.right is not None
    )
    assert changed == [("1.2.3", "1.2.4"), ("1.50", "1.80")]
    assert all(diff.severity == Severity.CONFIRMED for diff in diffs)
    assert all(diff.kind == DiffKind.MODIFIED for diff in diffs)

    # 坐标必须是各自原图坐标（右侧没有被映射回左图坐标）
    version_diff = _diff_for(diffs, "1.2.3")
    assert version_diff.left.bbox == left_boxes["version"].bbox
    assert version_diff.right.bbox == right_boxes["version"].bbox
    assert version_diff.right.text == "1.2.4"

    decimal_diff = _diff_for(diffs, "1.50")
    assert decimal_diff.left.bbox == left_boxes["value_in_1"].bbox
    assert decimal_diff.right.bbox == right_boxes["value_in_1"].bbox

    # 配对列表里重复字段是按位置/上下文配对的，而不是按 OCR 顺序
    pair_ids = {tuple(pair) for pair in info["pairs"]}
    assert (left_boxes["value_in_2"].id, right_boxes["value_in_2"].id) in pair_ids
    assert (left_boxes["value_out_2"].id, right_boxes["value_out_2"].id) in pair_ids


def test_transform_direction_right_to_left(tmp_path: Path):
    _, _, left_page, left_boxes, right_page, _ = _standard_pair(tmp_path)
    diffs, info = match_pages(left_page, right_page, ImageOptions())
    matrix = info["matrix"]
    right_center = right_page.boxes[[b.text for b in right_page.boxes].index("1.2.4")].bbox.center
    mapped_x = matrix[0][0] * right_center[0] + matrix[0][1] * right_center[1] + matrix[0][2]
    mapped_y = matrix[1][0] * right_center[0] + matrix[1][1] * right_center[1] + matrix[1][2]
    left_center = left_boxes["version"].bbox.center
    assert abs(mapped_x - left_center[0]) <= 8
    assert abs(mapped_y - left_center[1]) <= 8
    assert len(diffs) == 2


def test_char_level_spans_and_segment_boxes(tmp_path: Path):
    _, _, left_page, _, right_page, _ = _standard_pair(tmp_path)
    diffs, _ = match_pages(left_page, right_page, ImageOptions())

    version_diff = _diff_for(diffs, "1.2.3")
    assert version_diff.left.spans == [(4, 5)]
    assert version_diff.right.spans == [(4, 5)]
    assert len(version_diff.left.segment_boxes) == 1
    seg = version_diff.left.segment_boxes[0]
    bbox = version_diff.left.bbox
    assert bbox.x <= seg.x < seg.right <= bbox.right + 1e-6
    assert seg.y >= bbox.y and seg.bottom <= bbox.bottom + 1e-6
    # 第 5 个字符 “3” 大致位于文字框右侧 70%~90% 处
    ratio = (seg.x - bbox.x) / bbox.w
    assert 0.68 <= ratio <= 0.88

    decimal_diff = _diff_for(diffs, "1.50")
    assert decimal_diff.left.spans == [(2, 3)]
    seg = decimal_diff.left.segment_boxes[0]
    bbox = decimal_diff.left.bbox
    ratio = (seg.x - bbox.x) / bbox.w
    assert 0.38 <= ratio <= 0.56
    # 细分的字符框必须落在原框内部
    assert bbox.x <= seg.x and seg.right <= bbox.right + 1e-6


def test_only_one_side_and_low_confidence_orange(tmp_path: Path):
    left_meta = render_ui_screenshot(tmp_path / "left.png")
    right_meta = render_ui_screenshot(
        tmp_path / "right.png",
        scale=1.2,
        offset=(30, 18),
        extra_texts=[("仅右侧新增", 16, 205)],
    )
    left_extra = [
        ("only_left", "仅左侧低置信", 0.28, BBox(210.0, 205.0, 120.0, 18.0)),
    ]
    left_page, _ = _page_from_meta(left_meta, extra_boxes=left_extra)
    right_page, right_boxes = _page_from_meta(right_meta, shuffle=True)
    diffs, info = match_pages(left_page, right_page, ImageOptions())

    right_only = [d for d in diffs if d.kind == DiffKind.ONLY_RIGHT]
    left_only = [d for d in diffs if d.kind == DiffKind.ONLY_LEFT]
    assert len(right_only) == 1 and len(left_only) == 1
    assert right_only[0].left is None and right_only[0].right is not None
    assert right_only[0].right.text == "仅右侧新增"
    assert right_only[0].severity == Severity.CONFIRMED
    assert right_only[0].needs_review is False
    assert right_only[0].right.bbox == right_boxes["extra_0"].bbox

    assert left_only[0].left is not None and left_only[0].right is None
    assert left_only[0].left.text == "仅左侧低置信"
    assert left_only[0].severity == Severity.UNCERTAIN
    assert left_only[0].needs_review is True
    assert left_only[0].left.spans == [(0, 6)]
    assert info["only_left"] == [left_only[0].left.extra["box_id"]]
    assert info["only_right"] == [right_only[0].right.extra["box_id"]]


def test_unmatched_with_unreliable_transform_is_orange():
    """几何变换不可靠时，另一侧存在高度相似文字的“单侧差异”应标橙待复核。"""
    left = OcrPage(path="", width=240, height=120)
    left.boxes.append(OcrBox(id=0, text="VALUE1", confidence=0.98, bbox=BBox(10, 10, 80, 18)))
    right = OcrPage(path="", width=240, height=120)
    right.boxes.append(OcrBox(id=0, text="VALUE1", confidence=0.98, bbox=BBox(10, 10, 80, 18)))
    right.boxes.append(OcrBox(id=1, text="VALUE2", confidence=0.98, bbox=BBox(10, 40, 80, 18)))
    diffs, info = match_pages(left, right, ImageOptions())
    assert info["reliable"] is False  # 只有一个文字锚点，无法可靠估计变换
    only_right = [d for d in diffs if d.kind == DiffKind.ONLY_RIGHT]
    assert len(only_right) == 1
    assert only_right[0].right.text == "VALUE2"
    assert only_right[0].severity == Severity.UNCERTAIN
    assert only_right[0].needs_review is True
    assert "几何变换不可靠" in only_right[0].detail


def test_matched_low_confidence_is_uncertain(tmp_path: Path):
    left_meta = render_ui_screenshot(tmp_path / "left.png")
    right_meta = render_ui_screenshot(
        tmp_path / "right.png",
        scale=1.2,
        offset=(30, 18),
        values={"version": "1.2.4", "value_in_1": "1.80"},
    )
    left_page, left_boxes = _page_from_meta(left_meta, confidences={"version": 0.30})
    right_page, _ = _page_from_meta(right_meta, shuffle=True)
    diffs, _ = match_pages(left_page, right_page, ImageOptions())

    version_diff = _diff_for(diffs, "1.2.3")
    assert version_diff.severity == Severity.UNCERTAIN
    assert version_diff.needs_review is True
    assert version_diff.confidence == pytest.approx(0.30, abs=1e-6)
    assert "低置信度" in version_diff.detail
    decimal_diff = _diff_for(diffs, "1.50")
    assert decimal_diff.severity == Severity.CONFIRMED
    assert version_diff.left.extra["box_id"] == left_boxes["version"].id


def test_match_without_images_uses_text_anchors(tmp_path: Path):
    """OcrPage.path 不存在时（纯文字锚点）仍能估计缩放+平移。"""
    left_meta = render_ui_screenshot(tmp_path / "left.png")
    right_meta = render_ui_screenshot(
        tmp_path / "right.png",
        scale=0.8,
        offset=(12, 20),
    )
    left_page, _ = _page_from_meta(left_meta, path=str(tmp_path / "missing_left.png"))
    right_page, _ = _page_from_meta(
        right_meta, shuffle=True, path=str(tmp_path / "missing_right.png")
    )
    diffs, info = match_pages(left_page, right_page, ImageOptions())
    assert info["method"] in ("text-anchor", "text-anchor+refit", "layout")
    assert info["matched_count"] == len(left_page.boxes)
    assert abs(info["scale"] - 1.25) < 0.08
    assert diffs == []


def test_ocr_confusable_only_helpers():
    from engineerdiff.image.matcher import _ocr_confusable_only

    # 0/O、1/I/l、全半角、大小写、空白：仅这些差异 → 疑似 OCR 混淆
    assert _ocr_confusable_only("CURRENT1.5OA", "CURRENT1.50A")
    assert _ocr_confusable_only("0.00", "O.00")
    assert _ocr_confusable_only("1.50", "l.50")
    assert _ocr_confusable_only("1.50", "I.50")
    assert _ocr_confusable_only("ＡＢＣ", "abc")
    assert _ocr_confusable_only("装置 版本", "装置版本")
    # 真实数值/版本差异不得被当成混淆
    assert not _ocr_confusable_only("1.50", "1.80")
    assert not _ocr_confusable_only("1.2.3", "1.2.4")
    assert not _ocr_confusable_only("投入", "退出")
    assert not _ocr_confusable_only("abc", "abd")


def test_confusable_text_diffs_are_orange_real_number_diffs_are_red(tmp_path: Path):
    """匹配后只差 0/O、1/l 的 → 橙色待复核；真实 1.50→1.80 / 1.2.3→1.2.4 → 红色。"""
    left_meta = render_ui_screenshot(tmp_path / "left.png")
    right_meta = render_ui_screenshot(
        tmp_path / "right.png",
        scale=1.2,
        offset=(30, 18),
        values={"version": "1.2.4", "value_in_1": "l.50", "value_in_2": "O.00"},
    )
    left_page, _ = _page_from_meta(left_meta)
    right_page, right_boxes = _page_from_meta(right_meta, shuffle=True)
    diffs, info = match_pages(left_page, right_page, ImageOptions())
    assert info["matched_count"] == len(left_page.boxes)

    version_diff = _diff_for(diffs, "1.2.3")
    assert version_diff.severity == Severity.CONFIRMED
    assert version_diff.needs_review is False

    decimal_diff = _diff_for(diffs, "1.50")
    assert decimal_diff.right.text == "l.50"
    assert decimal_diff.severity == Severity.UNCERTAIN
    assert decimal_diff.needs_review is True
    assert "OCR 字符混淆" in decimal_diff.detail
    assert decimal_diff.kind == DiffKind.MODIFIED

    zero_diff = _diff_for(diffs, "0.00")
    assert zero_diff.right.text == "O.00"
    assert zero_diff.severity == Severity.UNCERTAIN
    assert zero_diff.needs_review is True
    assert "OCR 字符混淆" in zero_diff.detail
    assert zero_diff.right.spans == [(0, 1)]
    # 重复的 0.00 中只有被改成 O.00 的那一处产生差异
    assert sum(1 for d in diffs if d.left and d.left.text == "0.00") == 1
    assert len(diffs) == 3
    assert right_boxes["value_in_2"].text == "O.00"


# ---------------------------------------------------------------------------
# compare_images：文字修正 / 人工对应 / 错误与警告（使用假 OCR，不跑模型）
# ---------------------------------------------------------------------------


class _FakeOcr:
    def __init__(self, pages: dict[str, OcrPage] | None = None, error: Exception | None = None) -> None:
        self.pages = pages or {}
        self.error = error
        self.progress_calls = 0

    def recognize(self, image_path: str, progress=None, cancel=None) -> OcrPage:
        if self.error is not None:
            raise self.error
        if progress is not None:
            for percent, message in ((5, "读取图片"), (30, "加载引擎"), (55, "识别文字"), (90, "整理"), (100, "完成")):
                progress(percent, message)
                self.progress_calls += 1
        if cancel is not None and cancel():
            raise OcrCancelled("OCR 识别已取消")
        return copy.deepcopy(self.pages[image_path])


def _fake_pair(tmp_path: Path):
    left_meta = render_ui_screenshot(tmp_path / "left.png")
    right_meta = render_ui_screenshot(
        tmp_path / "right.png",
        scale=1.2,
        offset=(30, 18),
        values={"version": "1.2.4", "value_in_1": "1.80"},
    )
    left_path = str(tmp_path / "fake_left.png")
    right_path = str(tmp_path / "fake_right.png")
    left_page, left_boxes = _page_from_meta(left_meta, path=left_path)
    right_page, right_boxes = _page_from_meta(right_meta, shuffle=True, path=right_path)
    return left_path, right_path, left_page, left_boxes, right_page, right_boxes


def test_compare_images_applies_text_overrides(tmp_path: Path):
    left_path, right_path, left_page, left_boxes, right_page, _ = _fake_pair(tmp_path)
    fake = _FakeOcr({left_path: left_page, right_path: right_page})
    version_id = left_boxes["version"].id
    options = ImageOptions(text_overrides={"left": {version_id: "1.2.4"}})
    comparison = compare_images(left_path, right_path, options, fake)

    # 版本号被修正后与右图一致，只剩小数差异
    assert [d.left.text for d in comparison.diffs if d.left] == ["1.50"]
    fixed_box = comparison.left.boxes[version_id]
    assert fixed_box.text == "1.2.4"
    assert fixed_box.raw_text == "1.2.3"
    assert fixed_box.overridden is True
    assert comparison.settings["text_overrides"]["left"][version_id] == "1.2.4"
    assert comparison.settings["text_overrides"].get("right", {}) == {}


def test_compare_images_manual_pairs_are_forced(tmp_path: Path):
    left_path, right_path, left_page, left_boxes, right_page, right_boxes = _fake_pair(tmp_path)
    fake = _FakeOcr({left_path: left_page, right_path: right_page})
    pair = (left_boxes["version"].id, right_boxes["version"].id)
    options = ImageOptions(manual_pairs=[pair])
    comparison = compare_images(left_path, right_path, options, fake)

    assert list(options.manual_pairs) == [pair]
    assert comparison.transform["manual_pairs"] == [[pair[0], pair[1]]]
    version_diff = _diff_for(comparison.diffs, "1.2.3")
    assert "人工指定对应" in version_diff.detail
    assert version_diff.right is not None and version_diff.right.text == "1.2.4"


def test_compare_images_warns_on_bad_override_id(tmp_path: Path):
    left_path, right_path, left_page, _, right_page, _ = _fake_pair(tmp_path)
    fake = _FakeOcr({left_path: left_page, right_path: right_page})
    options = ImageOptions(text_overrides={"left": {99999: "x"}, "right": {}})
    comparison = compare_images(left_path, right_path, options, fake)
    assert any("不存在的文字框" in warning for warning in comparison.warnings)


def test_compare_images_ocr_failure_raises(tmp_path: Path):
    left = str(tmp_path / "a.png")
    right = str(tmp_path / "b.png")
    fake = _FakeOcr(error=OcrError("模型文件缺失"))
    with pytest.raises(ImageCompareError) as excinfo:
        compare_images(left, right, ImageOptions(), fake)
    assert "OCR 识别失败" in str(excinfo.value)
    assert "模型文件缺失" in str(excinfo.value)


def test_compare_images_no_text_is_not_equal(tmp_path: Path):
    left = str(tmp_path / "a.png")
    right = str(tmp_path / "b.png")
    empty = OcrPage(path=left, width=100, height=80)
    fake = _FakeOcr({left: empty, right: copy.deepcopy(empty)})
    comparison = compare_images(left, right, ImageOptions(), fake)
    assert comparison.diffs == []
    assert any("未识别到文字" in warning for warning in comparison.warnings)


def test_compare_images_cancel_before_ocr(tmp_path: Path):
    left = str(tmp_path / "a.png")
    right = str(tmp_path / "b.png")
    fake = _FakeOcr({})
    with pytest.raises(OcrCancelled):
        compare_images(left, right, ImageOptions(), fake, cancel=lambda: True)


def test_compare_images_progress_monotonic(tmp_path: Path):
    left_path, right_path, left_page, _, right_page, _ = _fake_pair(tmp_path)
    fake = _FakeOcr({left_path: left_page, right_path: right_page})
    percents: list[int] = []
    compare_images(left_path, right_path, ImageOptions(), fake, progress=lambda p, _m: percents.append(p))
    assert percents[-1] == 100
    assert percents == sorted(percents)
    assert 70 in percents or any(p >= 70 for p in percents)


# ---------------------------------------------------------------------------
# 图片 UI（offscreen 渲染 + 像素校验）
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_image_pane_overlay_alignment(qapp, tmp_path: Path):
    from PySide6.QtCore import QPointF

    from engineerdiff.ui.image_view import ImagePane

    generated = ensure_generated_dir()
    left_meta = render_ui_screenshot(generated / "ui_left.png")
    right_meta = render_ui_screenshot(
        generated / "ui_right.png",
        scale=1.2,
        offset=(30, 18),
        values={"version": "1.2.4", "value_in_1": "1.80"},
    )
    left_page, _ = _page_from_meta(left_meta)
    right_page, _ = _page_from_meta(right_meta, shuffle=True)
    diffs, info = match_pages(left_page, right_page, ImageOptions())
    comparison = ImageComparison(
        left=left_page,
        right=right_page,
        diffs=diffs,
        transform=info,
        settings=ImageOptions().as_dict(),
    )
    assert len(diffs) == 2

    pane = ImagePane()
    pane.resize(720, 480)
    pane.show()
    qapp.processEvents()
    pane.set_comparison(left_page, comparison, "left", show_boxes=True)
    qapp.processEvents()
    pane.fit_to_window()
    qapp.processEvents()
    assert pane.zoom() > 0
    assert pane.image_size().width() == left_page.width

    screenshot = generated / "test_image_pane_left_boxes.png"
    pane.grab().save(str(screenshot))
    image = pane.grab().toImage()
    view = pane.graphics_view()
    for diff in diffs:
        location = diff.left
        segment = (location.segment_boxes or [location.bbox])[0]
        point = view.mapFromScene(QPointF(segment.x + segment.w / 2, segment.y + segment.h / 2))
        assert 0 <= point.x() < image.width() and 0 <= point.y() < image.height()
        color = image.pixelColor(point.x(), point.y())
        assert color.red() > color.green() + 25, f"差异位置未显示红色覆盖：{diff.id} {color.name()}"
        assert color.red() > color.blue() + 15, f"差异位置未显示红色覆盖：{diff.id} {color.name()}"

    # reveal 居中
    assert pane.reveal(diffs[0]) is True
    qapp.processEvents()
    assert pane.reveal(diffs[0]) is True

    # 缩放/滚动接口
    pane.set_zoom(1.0)
    assert pane.zoom() == pytest.approx(1.0, abs=1e-6)
    pane.actual_size()
    assert pane.zoom() == pytest.approx(1.0, abs=1e-6)
    pane.set_zoom(2.0)
    pane.set_scroll_ratio(0.5, 0.5)
    v, h = pane.scroll_ratio()
    assert 0.0 <= v <= 1.0 and 0.0 <= h <= 1.0
    zoom_events: list[float] = []
    pane.zoom_changed.connect(zoom_events.append)
    pane.set_zoom(1.5)
    assert zoom_events and zoom_events[-1] == pytest.approx(1.5, abs=1e-6)

    # 关闭 OCR 文字框：场景中项目数量减少
    items_with_boxes = len(pane.scene().items())
    pane.set_show_boxes(False)
    assert len(pane.scene().items()) < items_with_boxes
    plain = generated / "test_image_pane_left_plain.png"
    pane.grab().save(str(plain))
    assert screenshot.is_file() and plain.is_file()

    # 右侧也渲染一张供人工检查
    right_pane = ImagePane()
    right_pane.resize(720, 480)
    right_pane.show()
    qapp.processEvents()
    right_pane.set_comparison(right_page, comparison, "right", show_boxes=False)
    qapp.processEvents()
    right_pane.fit_to_window()
    qapp.processEvents()
    right_screenshot = generated / "test_image_pane_right.png"
    right_pane.grab().save(str(right_screenshot))
    assert right_pane.reveal(diffs[1]) is True
    pane.close()
    right_pane.close()


@pytest.mark.gui
def test_ocr_correction_dialog_edits_and_pairs(qapp, tmp_path: Path):
    from engineerdiff.ui.ocr_dialog import OcrCorrectionDialog

    left_meta = render_ui_screenshot(tmp_path / "left.png")
    right_meta = render_ui_screenshot(
        tmp_path / "right.png",
        scale=1.2,
        offset=(30, 18),
        values={"version": "1.2.4", "value_in_1": "1.80"},
    )
    left_page, left_boxes = _page_from_meta(left_meta)
    right_page, right_boxes = _page_from_meta(right_meta, shuffle=True)
    diffs, info = match_pages(left_page, right_page, ImageOptions())
    comparison = ImageComparison(
        left=left_page,
        right=right_page,
        diffs=diffs,
        transform=info,
        settings=ImageOptions().as_dict(),
    )

    dialog = OcrCorrectionDialog(None, comparison, None)
    dialog.resize(1000, 620)
    dialog.show()
    qapp.processEvents()
    assert dialog.left_table.rowCount() == len(left_page.boxes)
    assert dialog.right_table.rowCount() == len(right_page.boxes)

    # 定位左侧版本号所在行并编辑文本
    version_id = left_boxes["version"].id
    left_row = [dialog.left_table.item(r, 0).data(0x0100) for r in range(dialog.left_table.rowCount())].index(
        version_id
    )
    dialog.left_table.item(left_row, 1).setText("1.2.9")
    dialog.left_table.setCurrentCell(left_row, 0)
    right_row = [
        dialog.right_table.item(r, 0).data(0x0100) for r in range(dialog.right_table.rowCount())
    ].index(right_boxes["version"].id)
    dialog.right_table.setCurrentCell(right_row, 0)
    assert dialog.add_manual_pair() is True
    assert "已建立对应" in dialog._hint_label.text()

    options = dialog.corrected_options()
    assert options.text_overrides["left"][version_id] == "1.2.9"
    assert options.manual_pairs == [(version_id, right_boxes["version"].id)]
    assert dialog.result_options().manual_pairs == options.manual_pairs

    generated = ensure_generated_dir()
    dialog.grab().save(str(generated / "test_ocr_dialog.png"))

    # 解除对应
    dialog.pair_table.setCurrentCell(0, 0)
    assert dialog.remove_manual_pair() is True
    assert dialog.corrected_options().manual_pairs == []
    dialog.close()

    # 人工修正还原为原始 OCR 文本时，override 应被移除
    fake_page = OcrPage(path=str(tmp_path / "no.png"), width=100, height=60)
    fake_page.boxes.append(
        OcrBox(
            id=0,
            text="1.2.4",
            confidence=0.99,
            bbox=BBox(10, 10, 40, 18),
            raw_text="1.2.3",
            overridden=True,
        )
    )
    comp2 = ImageComparison(
        left=fake_page,
        right=fake_page,
        diffs=[],
        transform={},
        settings=ImageOptions(text_overrides={"left": {0: "1.2.4"}}).as_dict(),
    )
    dialog2 = OcrCorrectionDialog(None, comp2, None)
    dialog2.left_table.item(0, 1).setText("1.2.3")
    assert dialog2.corrected_options().text_overrides.get("left", {}) == {}
    dialog2.close()


@pytest.mark.gui
def test_image_pane_fits_after_show_not_thumbnail(qapp, tmp_path: Path):
    """回归：控件未显示时 set_comparison 不能把 1000×360 图片 fit 成 7% 缩略图。"""
    from PIL import Image, ImageDraw
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from engineerdiff.ui.image_view import ImagePane

    image_path = tmp_path / "wide.png"
    image = Image.new("RGB", (1000, 360), (250, 250, 250))
    draw = ImageDraw.Draw(image)
    draw.rectangle([20, 20, 300, 80], outline=(30, 60, 120), width=3)
    draw.rectangle([400, 120, 900, 300], outline=(120, 60, 30), width=3)
    image.save(image_path)

    page = OcrPage(path=str(image_path), width=1000, height=360)
    comparison = ImageComparison(left=page, right=page, diffs=[], transform={}, settings={})
    pane = ImagePane()
    pane.resize(700, 600)
    # 模拟主窗口：控件仍在布局/未显示时就调用 set_comparison
    pane.set_comparison(page, comparison, "left")
    assert pane._fit_pending is True

    pane.show()
    qapp.processEvents()
    zoom = pane.zoom()
    assert 0.4 <= zoom <= 0.8, f"初始适应窗口缩放异常：{zoom}"
    assert pane._fit_pending is False
    viewport = pane.graphics_view().viewport().size()
    assert 1000 * zoom >= viewport.width() * 0.9
    displayed_area = (1000 * zoom) * (360 * zoom)
    assert displayed_area / (viewport.width() * viewport.height()) >= 0.35

    # 手动“适应窗口”按钮：即使之前放大过也要回到合适缩放
    pane.set_zoom(2.0)
    pane.fit_to_window()
    qapp.processEvents()
    assert 0.4 <= pane.zoom() <= 0.8

    # Ctrl+滚轮缩放
    base_zoom = pane.zoom()
    wheel = QWheelEvent(
        QPointF(300, 200),
        QPointF(300, 200),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(pane.graphics_view().viewport(), wheel)
    qapp.processEvents()
    assert pane.zoom() > base_zoom
    assert pane.zoom() == pytest.approx(min(8.0, base_zoom * 1.15), rel=0.03)

    # 不按 Ctrl 的滚轮直接缩放（看图软件习惯，用户要求）
    zoom_before = pane.zoom()
    plain_wheel = QWheelEvent(
        QPointF(300, 200),
        QPointF(300, 200),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(pane.graphics_view().viewport(), plain_wheel)
    qapp.processEvents()
    assert pane.zoom() > zoom_before
    pane.close()
