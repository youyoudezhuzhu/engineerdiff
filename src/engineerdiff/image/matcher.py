"""跨截图 OCR 文字匹配引擎。

算法概览
--------
1. **几何变换估计（右图 → 左图）**：优先 ORB 特征 + RANSAC 部分仿射变换
   （scale/rotation/translation）；同时用文本锚点（相同文字对）做尺度+平移的
   RANSAC 估计；按“文字锚点支持率”选择更可信的变换。都失败时用版面回退
   （文字高度比 + 中心中位数对齐）。
2. **一对一分配**：对每个候选对计算综合代价 = 文本相似度（对 OCR 常见混淆
   做轻度归一化）+ 空间位置（映射后中心距离 / IoU）+ 尺寸比例 + 邻域上下文
   （同方向邻居文字的相似度）。用匈牙利算法做全局一对一分配，规模过大时退化为
   带竞争检查的贪心分配，并保留“歧义”标记。
3. **输出差异**：匹配但文本不同 → 双方标红，并用 ``difflib`` 求字符级区间，
   按 CJK 全角 / 拉丁半角宽度比例估算 ``segment_boxes``；仅一侧文字 → 该侧
   标红；低置信度或配对歧义 → 橙色 ``UNCERTAIN`` + ``needs_review``。

坐标约定：``DiffLocation.bbox`` 始终是**该侧原图坐标**；右图坐标仅用于内部
映射与距离计算，绝不写回右侧 location。
"""

from __future__ import annotations

import difflib
import math
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from ..models import (
    BBox,
    DiffItem,
    DiffKind,
    DiffLocation,
    ImageOptions,
    OcrBox,
    OcrPage,
    Severity,
)

# ---------------------------------------------------------------------------
# 权重与阈值（集中管理，便于调参）
# ---------------------------------------------------------------------------

W_TEXT = 0.50
W_POS = 0.30
W_SIZE = 0.08
W_CONTEXT = 0.12

#: 中文/拉丁字符宽度估算权重
_CJK_WEIGHT = 1.0
_LATIN_WEIGHT = 0.55
_PUNCT_WEIGHT = 0.40
_SPACE_WEIGHT = 0.35

#: 文本锚点候选对的最低相似度
_ANCHOR_MIN_SIM = 0.72
#: 认为“同一段文字”用于几何支持的相似度
_SUPPORT_MIN_SIM = 0.55

_MAX_HUNGARIAN = 160
_NEIGHBOR_K = 6
_BIG = 1e6


# ---------------------------------------------------------------------------
# 文本相似度
# ---------------------------------------------------------------------------

_CONFUSE_TABLE = str.maketrans(
    {
        "0": "o",
        "o": "o",
        "1": "i",
        "i": "i",
        "l": "i",
        "|": "i",
    }
)


def normalize_text(text: str) -> str:
    """用于**匹配评分**的归一化：NFKC（全半角）、大小写、去空白。"""

    s = unicodedata.normalize("NFKC", text or "")
    s = s.casefold()
    return "".join(ch for ch in s if not ch.isspace())


def _confusable(text: str) -> str:
    return normalize_text(text).translate(_CONFUSE_TABLE)


@lru_cache(maxsize=16384)
def _similarity_cached(norm_a: str, norm_b: str) -> float:
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0
    ratio = difflib.SequenceMatcher(None, norm_a, norm_b, autojunk=False).ratio()
    # OCR 常见混淆 0/O、1/I/l：归一后相同则给高但非满分的相似度
    if _confusable(norm_a) == _confusable(norm_b):
        ratio = max(ratio, 0.92)
    # 一方包含另一方（OCR 在不同缩放下可能把标签和值合框/拆框）
    short, long = (norm_a, norm_b) if len(norm_a) <= len(norm_b) else (norm_b, norm_a)
    if len(short) >= 2 and (short in long) and len(long) > len(short):
        ratio = max(ratio, 0.55 + 0.35 * (len(short) / len(long)))
    return min(1.0, ratio)


def text_similarity(a: str, b: str) -> float:
    """0..1 的文本相似度；仅用于评分，不用于判定最终差异。"""
    return _similarity_cached(normalize_text(a), normalize_text(b))


def _comparable(text: str) -> str:
    """判定“文字是否相同”的文本（忽略首尾空白，保留内部空格/大小写）。"""
    return (text or "").strip()


# ---------------------------------------------------------------------------
# 几何变换
# ---------------------------------------------------------------------------


@dataclass
class _Transform:
    """右图 → 左图的 2x3 仿射矩阵。"""

    matrix: np.ndarray
    method: str
    scale: float
    tx: float
    ty: float
    rotation_deg: float = 0.0
    inliers: int = 0
    candidates: int = 0
    reliable: bool = False
    support: float = 0.0
    notes: list[str] = field(default_factory=list)

    def map_point(self, x: float, y: float) -> tuple[float, float]:
        m = self.matrix
        return (float(m[0, 0] * x + m[0, 1] * y + m[0, 2]), float(m[1, 0] * x + m[1, 1] * y + m[1, 2]))

    def map_bbox(self, bbox: BBox) -> BBox:
        pts = [
            self.map_point(bbox.x, bbox.y),
            self.map_point(bbox.right, bbox.y),
            self.map_point(bbox.x, bbox.bottom),
            self.map_point(bbox.right, bbox.bottom),
        ]
        return BBox.from_quad(pts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "reliable": bool(self.reliable),
            "scale": round(float(self.scale), 5),
            "tx": round(float(self.tx), 2),
            "ty": round(float(self.ty), 2),
            "rotation_deg": round(float(self.rotation_deg), 3),
            "inliers": int(self.inliers),
            "candidates": int(self.candidates),
            "support": round(float(self.support), 4),
            "matrix": [[round(float(v), 6) for v in row] for row in self.matrix],
        }


def _identity_transform() -> _Transform:
    return _Transform(
        matrix=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
        method="identity",
        scale=1.0,
        tx=0.0,
        ty=0.0,
        reliable=False,
    )


def _from_matrix(matrix: np.ndarray, method: str, **kwargs: Any) -> _Transform:
    scale = float(math.hypot(float(matrix[0, 0]), float(matrix[1, 0])))
    rotation = math.degrees(math.atan2(float(matrix[1, 0]), float(matrix[0, 0])))
    return _Transform(
        matrix=matrix.astype(np.float64),
        method=method,
        scale=scale,
        tx=float(matrix[0, 2]),
        ty=float(matrix[1, 2]),
        rotation_deg=rotation,
        **kwargs,
    )


def _is_plausible(transform: _Transform, left: OcrPage, right: OcrPage) -> bool:
    if not (0.2 <= transform.scale <= 5.0):
        return False
    if abs(transform.rotation_deg) > 15.0:
        return False
    max_dim = max(left.width, left.height, right.width, right.height, 100)
    if abs(transform.tx) > 3 * max_dim or abs(transform.ty) > 3 * max_dim:
        return False
    return True


def _ref_size(left: OcrPage, right: OcrPage, mapped_right: Sequence[BBox] | None = None) -> float:
    values = [b.bbox.h for b in left.boxes]
    if mapped_right is not None:
        values.extend(b.h for b in mapped_right)
    elif right.boxes:
        values.extend(b.bbox.h for b in right.boxes)
    if not values:
        return 12.0
    return max(8.0, float(np.median(values)))


def _transform_support(transform: _Transform, left: OcrPage, right: OcrPage, ref: float | None = None) -> float:
    """文字锚点支持率：左图有多少框能在映射后附近找到相似文字。"""
    if not left.boxes or not right.boxes:
        return 0.0
    mapped = [transform.map_bbox(b.bbox) for b in right.boxes]
    if ref is None:
        ref = _ref_size(left, right, mapped)
    tol = max(8.0, 1.25 * ref)
    supported = 0
    for a in left.boxes:
        ax, ay = a.bbox.center
        for j, b in enumerate(right.boxes):
            bx, by = mapped[j].center
            if math.hypot(ax - bx, ay - by) <= tol and text_similarity(a.text, b.text) >= _SUPPORT_MIN_SIM:
                supported += 1
                break
    return supported / len(left.boxes)


def _load_gray(path: str) -> np.ndarray | None:
    try:
        import cv2  # 延迟 import，纯文字匹配不需要 OpenCV
    except Exception:
        return None
    try:
        if not path or not Path(path).is_file():
            return None
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    except Exception:
        return None
    return image


def _limit_for_orb(gray: np.ndarray, max_side: int = 1400) -> tuple[np.ndarray, float]:
    h, w = gray.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return gray, 1.0
    factor = max_side / float(longest)
    import cv2

    resized = cv2.resize(gray, (max(1, int(w * factor)), max(1, int(h * factor))), interpolation=cv2.INTER_AREA)
    return resized, factor


def _estimate_orb_transform(left: OcrPage, right: OcrPage) -> _Transform | None:
    """ORB 特征匹配 + RANSAC 估计右图→左图的部分仿射变换。"""
    try:
        import cv2
    except Exception:
        return None
    lg = _load_gray(left.path)
    rg = _load_gray(right.path)
    if lg is None or rg is None:
        return None
    try:
        lg, lf = _limit_for_orb(lg)
        rg, rf = _limit_for_orb(rg)
        orb = cv2.ORB_create(nfeatures=2500, fastThreshold=10)
        kp_l, des_l = orb.detectAndCompute(lg, None)
        kp_r, des_r = orb.detectAndCompute(rg, None)
        if des_l is None or des_r is None or len(kp_l) < 6 or len(kp_r) < 6:
            return None
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        knn = matcher.knnMatch(des_r, des_l, k=2)
        src: list[tuple[float, float]] = []
        dst: list[tuple[float, float]] = []
        for pair in knn:
            if len(pair) < 2:
                continue
            m, n = pair
            if m.distance < 0.78 * n.distance:
                src.append((kp_r[m.queryIdx].pt[0] / rf, kp_r[m.queryIdx].pt[1] / rf))
                dst.append((kp_l[m.trainIdx].pt[0] / lf, kp_l[m.trainIdx].pt[1] / lf))
        if len(src) < 8:
            return None
        src_arr = np.array(src, dtype=np.float32)
        dst_arr = np.array(dst, dtype=np.float32)
        matrix, inliers = cv2.estimateAffinePartial2D(
            src_arr,
            dst_arr,
            method=cv2.RANSAC,
            ransacReprojThreshold=3.0,
            maxIters=5000,
            confidence=0.995,
        )
        if matrix is None or inliers is None:
            return None
        inlier_count = int(np.count_nonzero(inliers))
        if inlier_count < 6:
            return None
        transform = _from_matrix(np.asarray(matrix, dtype=np.float64), "orb-affine", inliers=inlier_count)
        transform.candidates = int(len(src))
        transform.reliable = inlier_count >= 8
        if not _is_plausible(transform, left, right):
            return None
        return transform
    except Exception:
        return None


def _fit_similarity(centers_right: np.ndarray, centers_left: np.ndarray, fallback_scale: float) -> tuple[float, np.ndarray]:
    """最小二乘拟合 ``left ≈ s * right + t``（无旋转）。"""
    n = len(centers_right)
    if n == 0:
        return fallback_scale, np.zeros(2)
    if n == 1:
        return fallback_scale, centers_left[0] - fallback_scale * centers_right[0]
    cr = centers_right - centers_right.mean(axis=0)
    cl = centers_left - centers_left.mean(axis=0)
    denom = float(np.sum(cr * cr))
    if denom < 1e-6:
        return fallback_scale, centers_left.mean(axis=0) - fallback_scale * centers_right.mean(axis=0)
    scale = float(np.sum(cr * cl) / denom)
    scale = min(5.0, max(0.2, scale))
    t = centers_left.mean(axis=0) - scale * centers_right.mean(axis=0)
    return scale, t


def _text_anchor_pairs(left: OcrPage, right: OcrPage) -> list[tuple[float, int, int]]:
    """高文本相似度候选对（每框保留前 3 个），用于 RANSAC 几何估计。"""
    pairs: list[tuple[float, int, int]] = []
    for i, a in enumerate(left.boxes):
        best: list[tuple[float, int]] = []
        for j, b in enumerate(right.boxes):
            sim = text_similarity(a.text, b.text)
            if sim >= _ANCHOR_MIN_SIM:
                best.append((sim, j))
        best.sort(key=lambda item: item[0], reverse=True)
        pairs.extend((sim, i, j) for sim, j in best[:3])
    return pairs


def _estimate_anchor_transform(left: OcrPage, right: OcrPage) -> _Transform | None:
    if not left.boxes or not right.boxes:
        return None
    pairs = _text_anchor_pairs(left, right)
    if len(pairs) < 2:
        return None
    centers_l = np.array([left.boxes[i].bbox.center for _, i, _ in pairs], dtype=np.float64)
    centers_r = np.array([right.boxes[j].bbox.center for _, _, j in pairs], dtype=np.float64)
    ratios: list[float] = []
    for _, i, j in pairs:
        a, b = left.boxes[i].bbox, right.boxes[j].bbox
        if b.w > 1 and b.h > 1:
            ratios.append(math.sqrt(max(1e-6, (a.w * a.h) / (b.w * b.h))))
    seed_scale = float(np.median(ratios)) if ratios else 1.0
    seed_scale = min(5.0, max(0.2, seed_scale))
    ref = _ref_size(left, right)
    tol = max(6.0, 1.0 * ref)

    best_inliers: list[int] = []
    for seed in range(len(pairs)):
        t = centers_l[seed] - seed_scale * centers_r[seed]
        residuals = np.linalg.norm(seed_scale * centers_r + t - centers_l, axis=1)
        inliers = [idx for idx, res in enumerate(residuals) if res <= tol]
        if len(inliers) > len(best_inliers):
            best_inliers = inliers
    if len(best_inliers) < 2:
        return None

    scale, translation = _fit_similarity(centers_r[best_inliers], centers_l[best_inliers], seed_scale)
    # 用更精细的尺度再挑一次内点
    residuals = np.linalg.norm(scale * centers_r + translation - centers_l, axis=1)
    refined = [idx for idx, res in enumerate(residuals) if res <= tol * 0.75]
    if len(refined) >= 2:
        best_inliers = refined
        scale, translation = _fit_similarity(centers_r[best_inliers], centers_l[best_inliers], seed_scale)

    matrix = np.array([[scale, 0.0, float(translation[0])], [0.0, scale, float(translation[1])]])
    transform = _from_matrix(matrix, "text-anchor", inliers=len(best_inliers), candidates=len(pairs))
    transform.reliable = len(best_inliers) >= 3
    transform.notes.append(f"文本锚点 {len(best_inliers)}/{len(pairs)} 对")
    if not _is_plausible(transform, left, right):
        return None
    return transform


def _layout_transform(left: OcrPage, right: OcrPage) -> _Transform:
    notes: list[str] = []
    scale = 1.0
    if right.boxes and left.boxes:
        lh = float(np.median([b.bbox.h for b in left.boxes]))
        rh = float(np.median([b.bbox.h for b in right.boxes]))
        if rh > 1:
            scale = lh / rh
        notes.append(f"文字高度比 {lh:.0f}/{rh:.0f} 估计缩放")
    elif right.width > 0:
        scale = left.width / right.width
        notes.append("按图片宽度估计缩放")
    scale = min(5.0, max(0.2, scale))
    tx = ty = 0.0
    if left.boxes and right.boxes:
        cl = np.array([b.bbox.center for b in left.boxes], dtype=np.float64)
        cr = np.array([b.bbox.center for b in right.boxes], dtype=np.float64)
        t = np.median(cl, axis=0) - scale * np.median(cr, axis=0)
        tx, ty = float(t[0]), float(t[1])
        notes.append("按文字中心中位数对齐平移")
    elif left.width and right.width and left.height and right.height:
        tx = (left.width - scale * right.width) / 2.0
        ty = (left.height - scale * right.height) / 2.0
    matrix = np.array([[scale, 0.0, tx], [0.0, scale, ty]])
    transform = _from_matrix(matrix, "layout", reliable=False)
    transform.notes.extend(notes)
    return transform


def _estimate_transform(left: OcrPage, right: OcrPage, notes: list[str]) -> _Transform:
    if not left.boxes and not right.boxes:
        notes.append("两侧均无文字框，使用单位变换")
        return _identity_transform()
    candidates: list[_Transform] = []
    orb = _estimate_orb_transform(left, right)
    if orb is not None:
        candidates.append(orb)
    anchor = _estimate_anchor_transform(left, right)
    if anchor is not None:
        candidates.append(anchor)
    if not candidates:
        transform = _layout_transform(left, right)
        notes.append("ORB 与文本锚点均不可用，使用版面回退变换")
        return transform
    ref = _ref_size(left, right)
    for candidate in candidates:
        candidate.support = _transform_support(candidate, left, right, ref)
    # 优先“可靠 + 支持率高”；同分时优先 ORB（像素级更精确）
    def rank(c: _Transform) -> tuple[float, float, float, int]:
        return (1.0 if c.reliable else 0.0, c.support, c.inliers, 1 if c.method == "orb-affine" else 0)

    chosen = max(candidates, key=rank)
    if not chosen.reliable and chosen.support < 0.15:
        layout = _layout_transform(left, right)
        layout.support = _transform_support(layout, left, right, ref)
        if layout.support >= chosen.support:
            notes.append("估计变换支持率过低，改用版面回退变换")
            chosen = layout
    notes.append(
        f"几何变换：{chosen.method}，缩放 {chosen.scale:.3f}，平移 ({chosen.tx:.1f}, {chosen.ty:.1f})，"
        f"内点 {chosen.inliers}，文字支持率 {chosen.support:.2f}"
    )
    return chosen


# ---------------------------------------------------------------------------
# 邻域上下文
# ---------------------------------------------------------------------------


@dataclass
class _Neighbor:
    text: str
    dx: float
    dy: float
    dist: float


def _neighbor_lists(
    texts: Sequence[str],
    centers: np.ndarray,
    ref: float,
    k: int = _NEIGHBOR_K,
) -> list[list[_Neighbor]]:
    n = len(texts)
    result: list[list[_Neighbor]] = []
    radius = max(6.0 * ref, 40.0)
    for i in range(n):
        c = centers[i]
        deltas = centers - c
        dists = np.linalg.norm(deltas, axis=1)
        order = np.argsort(dists)
        items: list[_Neighbor] = []
        for idx in order:
            if idx == i or dists[idx] > radius:
                continue
            items.append(
                _Neighbor(
                    text=str(texts[idx]),
                    dx=float(deltas[idx][0]),
                    dy=float(deltas[idx][1]),
                    dist=float(dists[idx]),
                )
            )
            if len(items) >= k:
                break
        result.append(items)
    return result


def _context_score(
    left_neighbors: Sequence[_Neighbor],
    right_neighbors: Sequence[_Neighbor],
    ref: float,
) -> float:
    """比较“同一相对方向上的邻居文字”的相似度；无证据返回中性 0.5。"""
    if not left_neighbors or not right_neighbors:
        return 0.5
    total = 0.0
    weight = 0.0
    for ln in left_neighbors:
        best: float | None = None
        for rn in right_neighbors:
            offset_gap = math.hypot(ln.dx - rn.dx, ln.dy - rn.dy)
            tolerance = 0.6 * ref + 0.35 * max(ln.dist, rn.dist)
            if offset_gap > tolerance:
                continue
            sim = text_similarity(ln.text, rn.text)
            if best is None or sim > best:
                best = sim
        if best is not None:
            w = 1.0 / (1.0 + ln.dist / (2.0 * ref))
            total += w * best
            weight += w
    if weight <= 0:
        return 0.5
    return max(0.0, min(1.0, total / weight))


# ---------------------------------------------------------------------------
# 一对一分配
# ---------------------------------------------------------------------------


def _position_cost(left_bbox: BBox, mapped_right: BBox, ref: float) -> float:
    ax, ay = left_bbox.center
    bx, by = mapped_right.center
    distance = math.hypot(ax - bx, ay - by)
    center_cost = min(1.0, distance / (3.5 * ref))
    iou_cost = 1.0 - max(0.0, min(1.0, left_bbox.iou(mapped_right)))
    return 0.55 * center_cost + 0.45 * iou_cost


def _size_cost(left_bbox: BBox, mapped_right: BBox) -> float:
    def rel(a: float, b: float) -> float:
        return min(1.0, abs(math.log((a + 1.0) / (b + 1.0))) / math.log(2.0))

    return 0.6 * rel(left_bbox.w, mapped_right.w) + 0.4 * rel(left_bbox.h, mapped_right.h)


def _hungarian(cost: np.ndarray) -> list[tuple[int, int]]:
    """最小代价二分图匹配（e-maxx 算法，O(n^2 m)，n,m <= 160）。"""
    n, m = cost.shape
    if n == 0 or m == 0:
        return []
    transposed = False
    if n > m:
        cost = cost.T
        n, m = m, n
        transposed = True
    inf = 1e15
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            row = cost[i0 - 1]
            delta = inf
            j1 = 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = float(row[j - 1]) - u[i0] - v[j]
                if cur < minv[j] - 1e-12:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta - 1e-12:
                    delta = minv[j]
                    j1 = j
            for j in range(0, m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    pairs: list[tuple[int, int]] = []
    for j in range(1, m + 1):
        if p[j]:
            i, jj = p[j] - 1, j - 1
            pairs.append((jj, i) if transposed else (i, jj))
    return pairs


def _greedy_assign(
    scores: np.ndarray, eligible: np.ndarray
) -> list[tuple[int, int]]:
    candidates = [
        (float(scores[i, j]), i, j) for i, j in zip(*np.nonzero(eligible))
    ]
    candidates.sort(key=lambda item: item[0], reverse=True)
    used_left: set[int] = set()
    used_right: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _score, i, j in candidates:
        if i in used_left or j in used_right:
            continue
        used_left.add(i)
        used_right.add(j)
        pairs.append((i, j))
    return pairs


def _assign(
    scores: np.ndarray, eligible: np.ndarray
) -> list[tuple[int, int]]:
    n, m = scores.shape
    if n == 0 or m == 0:
        return []
    if n <= _MAX_HUNGARIAN and m <= _MAX_HUNGARIAN:
        cost = np.where(eligible, 1.0 - scores, _BIG)
        pairs = _hungarian(cost)
        return [(i, j) for i, j in pairs if eligible[i, j]]
    return _greedy_assign(scores, eligible)


# ---------------------------------------------------------------------------
# 字符级差异与片段框
# ---------------------------------------------------------------------------


def _char_weight(ch: str) -> float:
    if ch in (" ", "\t"):
        return _SPACE_WEIGHT
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return _CJK_WEIGHT
    if ch.isalnum():
        return _LATIN_WEIGHT
    return _PUNCT_WEIGHT


def _merge_spans(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _change_spans(text_a: str, text_b: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    matcher = difflib.SequenceMatcher(None, text_a, text_b, autojunk=False)
    spans_a: list[tuple[int, int]] = []
    spans_b: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            spans_a.append((i1, i2))
        if j2 > j1:
            spans_b.append((j1, j2))
    return _merge_spans(spans_a), _merge_spans(spans_b)


def _segment_box(bbox: BBox, text: str, start: int, end: int) -> BBox:
    """按字符宽高比例估算字符区间子框；结果严格限制在原 box 内。"""
    start = max(0, min(len(text), start))
    end = max(start, min(len(text), end))
    if "\n" in text or "\r" in text or bbox.w <= 0 or bbox.h <= 0:
        return bbox
    weights = [_char_weight(ch) for ch in text]
    total = sum(weights)
    if total <= 0 or end <= start:
        return bbox
    prefix = sum(weights[:start])
    width_ratio = sum(weights[start:end]) / total
    x0 = bbox.x + bbox.w * (prefix / total)
    width = max(1.0, bbox.w * width_ratio)
    x0 = max(bbox.x, min(bbox.right - 1.0, x0))
    x1 = min(bbox.right, x0 + width)
    if x1 - x0 < 1.0:
        x1 = min(bbox.right, x0 + 1.0)
    return BBox(x0, bbox.y, max(1.0, x1 - x0), bbox.h)


def _side_segments(
    text: str, other_text: str, bbox: BBox, own_spans: list[tuple[int, int]]
) -> tuple[list[tuple[int, int]], list[BBox]]:
    if not text:
        return [], []
    if own_spans:
        return own_spans, [_segment_box(bbox, text, s, e) for s, e in own_spans]
    # 该侧整段被删除/另一侧纯插入：无法定位具体字符，整框高亮
    return [(0, len(text))], [bbox]


# ---------------------------------------------------------------------------
# 主匹配流程
# ---------------------------------------------------------------------------


@dataclass
class _Pair:
    i: int
    j: int
    sim: float
    score: float
    manual: bool = False
    ambiguous: bool = False


def _valid_manual_pairs(
    manual: Sequence[Sequence[int]] | None,
    left: OcrPage,
    right: OcrPage,
    notes: list[str],
) -> dict[int, int]:
    """把 (box_id, box_id) 转换为 (left_index, right_index)，非法项产生警告。"""
    if not manual:
        return {}
    left_by_id = {box.id: idx for idx, box in enumerate(left.boxes)}
    right_by_id = {box.id: idx for idx, box in enumerate(right.boxes)}
    mapping: dict[int, int] = {}
    used_right: set[int] = set()
    for item in manual:
        try:
            lid, rid = int(item[0]), int(item[1])
        except (TypeError, ValueError, IndexError):
            notes.append(f"忽略非法人工对应：{item!r}")
            continue
        if lid not in left_by_id or rid not in right_by_id:
            notes.append(f"人工对应引用了不存在的文字框：{lid} ↔ {rid}")
            continue
        li, rj = left_by_id[lid], right_by_id[rid]
        if li in mapping:
            notes.append(f"左图文字框 {lid} 重复人工对应，保留首次设置")
            continue
        if rj in used_right:
            notes.append(f"右图文字框 {rid} 重复人工对应，保留首次设置")
            continue
        mapping[li] = rj
        used_right.add(rj)
    return mapping


def _core_match(
    left: OcrPage,
    right: OcrPage,
    transform: _Transform,
    options: ImageOptions,
    manual: dict[int, int],
) -> dict[str, Any]:
    n, m = len(left.boxes), len(right.boxes)
    mapped_right = [transform.map_bbox(b.bbox) for b in right.boxes]
    ref = _ref_size(left, right, mapped_right)
    left_centers = np.array([b.bbox.center for b in left.boxes], dtype=np.float64).reshape(-1, 2)
    right_centers_orig = np.array([b.bbox.center for b in right.boxes], dtype=np.float64).reshape(-1, 2)
    if m:
        right_centers_mapped = np.array([b.center for b in mapped_right], dtype=np.float64)
    else:
        right_centers_mapped = np.zeros((0, 2))
    left_neighbors = _neighbor_lists([b.text for b in left.boxes], left_centers, ref)
    right_neighbors = _neighbor_lists([b.text for b in right.boxes], right_centers_mapped, ref)

    manual_right = set(manual.values())
    row_ids = [i for i in range(n) if i not in manual]
    col_ids = [j for j in range(m) if j not in manual_right]
    scores = np.zeros((len(row_ids), len(col_ids)), dtype=np.float64)
    eligible = np.zeros((len(row_ids), len(col_ids)), dtype=bool)
    sims = np.zeros((len(row_ids), len(col_ids)), dtype=np.float64)

    threshold = float(options.match_threshold)
    for ri, i in enumerate(row_ids):
        a = left.boxes[i]
        for cj, j in enumerate(col_ids):
            b = right.boxes[j]
            sim = text_similarity(a.text, b.text)
            pos_cost = _position_cost(a.bbox, mapped_right[j], ref)
            size_cost = _size_cost(a.bbox, mapped_right[j])
            ctx = _context_score(left_neighbors[i], right_neighbors[j], ref)
            score = (
                W_TEXT * sim
                + W_POS * (1.0 - pos_cost)
                + W_SIZE * (1.0 - size_cost)
                + W_CONTEXT * ctx
            )
            sims[ri, cj] = sim
            scores[ri, cj] = score
            strong_geometry = pos_cost <= 0.18 and size_cost <= 0.50
            eligible[ri, cj] = bool(
                score >= threshold
                and (sim >= 0.30 or strong_geometry or sim >= 0.75)
            )
    auto_pairs = _assign(scores, eligible)
    pairs: list[_Pair] = []
    # 人工对应优先
    for i, j in manual.items():
        sim = text_similarity(left.boxes[i].text, right.boxes[j].text)
        pairs.append(_Pair(i=i, j=j, sim=sim, score=1.0, manual=True))
    for ri, cj in auto_pairs:
        i, j = row_ids[ri], col_ids[cj]
        score = float(scores[ri, cj])
        ambiguous = False
        if sims[ri, cj] < 0.88:
            alternatives = []
            if scores.shape[1] > 1:
                mask = np.ones(scores.shape[1], dtype=bool)
                mask[cj] = False
                alternatives.append(float(scores[ri, mask].max(initial=0.0)))
            if scores.shape[0] > 1:
                mask = np.ones(scores.shape[0], dtype=bool)
                mask[ri] = False
                alternatives.append(float(scores[mask, cj].max(initial=0.0)))
            margin = score - max(alternatives) if alternatives else 1.0
            ambiguous = margin < 0.035
        pairs.append(
            _Pair(i=i, j=j, sim=float(sims[ri, cj]), score=score, ambiguous=ambiguous)
        )
    matched_left = {p.i for p in pairs}
    matched_right = {p.j for p in pairs}
    unmatched_left = [i for i in range(n) if i not in matched_left]
    unmatched_right = [j for j in range(m) if j not in matched_right]
    return {
        "pairs": pairs,
        "unmatched_left": unmatched_left,
        "unmatched_right": unmatched_right,
        "scores": scores,
        "eligible": eligible,
        "row_ids": row_ids,
        "col_ids": col_ids,
        "mapped_right": mapped_right,
        "left_neighbors": left_neighbors,
        "right_neighbors": right_neighbors,
        "ref": ref,
    }


def _refit_from_pairs(
    left: OcrPage,
    right: OcrPage,
    pairs: Sequence[_Pair],
    current: _Transform,
) -> _Transform | None:
    usable = [p for p in pairs if not p.manual and p.sim >= 0.55 and p.score >= 0.55]
    if len(usable) < 2:
        return None
    centers_r = np.array([right.boxes[p.j].bbox.center for p in usable], dtype=np.float64)
    centers_l = np.array([left.boxes[p.i].bbox.center for p in usable], dtype=np.float64)
    scale, t = _fit_similarity(centers_r, centers_l, current.scale)
    if scale <= 0:
        return None
    matrix = np.array([[scale, 0.0, float(t[0])], [0.0, scale, float(t[1])]])
    refined = _from_matrix(matrix, "text-anchor+refit" if current.method != "orb-affine" else "orb-affine+refit")
    refined.inliers = len(usable)
    refined.candidates = len(usable)
    refined.reliable = len(usable) >= 3
    refined.notes.append(f"用 {len(usable)} 对已匹配文字精化变换")
    if not _is_plausible(refined, left, right):
        return None
    return refined


def _transform_delta(a: _Transform, b: _Transform) -> float:
    """尺度相对变化 + 平移变化的归一化度量。"""
    scale_delta = abs(a.scale - b.scale) / max(1e-6, a.scale)
    shift = math.hypot(a.tx - b.tx, a.ty - b.ty)
    return max(scale_delta, shift / 8.0)


def _side_location(
    box: OcrBox,
    text: str,
    spans: list[tuple[int, int]],
    segment_boxes: list[BBox],
    extra: dict[str, Any] | None = None,
) -> DiffLocation:
    data: dict[str, Any] = {"box_id": box.id, "ocr_confidence": round(float(box.confidence), 4)}
    if box.quad:
        data["quad"] = [[round(float(x), 2), round(float(y), 2)] for x, y in box.quad]
    if extra:
        data.update(extra)
    return DiffLocation(
        kind="image",
        bbox=box.bbox,
        text=text,
        spans=spans,
        segment_boxes=segment_boxes,
        extra=data,
    )


def _matched_diff(a: OcrBox, b: OcrBox, pair: _Pair, options: ImageOptions) -> DiffItem:
    spans_a, spans_b = _change_spans(a.text, b.text)
    seg_a = _side_segments(a.text, b.text, a.bbox, spans_a)
    seg_b = _side_segments(b.text, a.text, b.bbox, spans_b)
    low_confidence = min(a.confidence, b.confidence) < float(options.confidence_threshold)
    uncertain = low_confidence or pair.ambiguous
    reasons: list[str] = []
    if low_confidence:
        reasons.append("低置信度")
    if pair.ambiguous:
        reasons.append("配对存在歧义，建议人工复核")
    if pair.manual:
        reasons.append("人工指定对应")
    detail = (
        f"OCR 置信度 左 {a.confidence:.2f} / 右 {b.confidence:.2f}；"
        f"文本相似度 {pair.sim:.2f}；匹配得分 {pair.score:.2f}"
    )
    if reasons:
        detail += "；" + "；".join(reasons)
    if a.overridden or b.overridden:
        detail += "；包含人工修正文本"
    title = f"文字不同：{_short(a.text)} → {_short(b.text)}"
    return DiffItem(
        id=f"img:{a.id}:{b.id}",
        kind=DiffKind.MODIFIED,
        severity=Severity.UNCERTAIN if uncertain else Severity.CONFIRMED,
        title=title,
        left=_side_location(a, a.text, seg_a[0], seg_a[1], {"text_similarity": round(pair.sim, 4)}),
        right=_side_location(b, b.text, seg_b[0], seg_b[1], {"text_similarity": round(pair.sim, 4)}),
        confidence=float(min(a.confidence, b.confidence)),
        needs_review=uncertain,
        detail=detail,
        group="image",
    )


def _one_sided_diff(
    box: OcrBox,
    side: str,
    options: ImageOptions,
    *,
    best_other_sim: float,
    transform_reliable: bool,
    is_manual_conflict: bool = False,
) -> DiffItem:
    low_confidence = box.confidence < float(options.confidence_threshold)
    unreliable_presence = (best_other_sim >= 0.70) and not transform_reliable
    uncertain = low_confidence or unreliable_presence
    reasons: list[str] = []
    if low_confidence:
        reasons.append("OCR 置信度低")
    if unreliable_presence:
        reasons.append("另一侧存在相似文字但几何变换不可靠，可能为配对失败")
    if is_manual_conflict:
        reasons.append("人工对应冲突")
    text = box.text
    spans = [(0, len(text))] if text else []
    segments = [box.bbox] if text else []
    location = _side_location(box, text, spans, segments)
    kind = DiffKind.ONLY_LEFT if side == "left" else DiffKind.ONLY_RIGHT
    side_label = "左图" if side == "left" else "右图"
    detail = f"仅{side_label}有该文字（OCR 置信度 {box.confidence:.2f}）"
    if reasons:
        detail += "；" + "；".join(reasons)
    return DiffItem(
        id=f"img:{'l' if side == 'left' else 'r'}:{box.id}",
        kind=kind,
        severity=Severity.UNCERTAIN if uncertain else Severity.CONFIRMED,
        title=f"仅{side_label}有：{_short(text)}",
        left=location if side == "left" else None,
        right=location if side == "right" else None,
        confidence=float(box.confidence),
        needs_review=uncertain,
        detail=detail,
        group="image",
    )


def _short(text: str, limit: int = 40) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _best_other_similarity(box: OcrBox, other_boxes: Sequence[OcrBox]) -> float:
    best = 0.0
    for other in other_boxes:
        sim = text_similarity(box.text, other.text)
        if sim > best:
            best = sim
            if best >= 0.999:
                break
    return best


def _build_diffs(
    left: OcrPage,
    right: OcrPage,
    pairs: Sequence[_Pair],
    unmatched_left: Sequence[int],
    unmatched_right: Sequence[int],
    transform: _Transform,
    options: ImageOptions,
    notes: list[str],
) -> list[DiffItem]:
    diffs: list[DiffItem] = []
    for pair in pairs:
        a = left.boxes[pair.i]
        b = right.boxes[pair.j]
        if _comparable(a.text) == _comparable(b.text):
            continue
        diffs.append(_matched_diff(a, b, pair, options))
    for i in unmatched_left:
        box = left.boxes[i]
        diffs.append(
            _one_sided_diff(
                box,
                "left",
                options,
                best_other_sim=_best_other_similarity(box, right.boxes),
                transform_reliable=transform.reliable,
            )
        )
    for j in unmatched_right:
        box = right.boxes[j]
        diffs.append(
            _one_sided_diff(
                box,
                "right",
                options,
                best_other_sim=_best_other_similarity(box, left.boxes),
                transform_reliable=transform.reliable,
            )
        )

    def sort_key(diff: DiffItem) -> tuple[float, float]:
        if diff.left is not None and diff.left.bbox is not None:
            y, x = diff.left.bbox.center
            return (float(y), float(x))
        if diff.right is not None and diff.right.bbox is not None:
            y, x = diff.right.bbox.center
            my, mx = transform.map_point(x, y)
            return (float(my), float(mx))
        return (1e9, 1e9)

    diffs.sort(key=sort_key)
    return diffs


def match_pages(
    left: OcrPage,
    right: OcrPage,
    options: ImageOptions | None = None,
) -> tuple[list[DiffItem], dict[str, Any]]:
    """匹配左右 OCR 结果并生成统一 ``DiffItem`` 列表。

    返回 ``(diffs, transform_info)``。``transform_info`` 记录几何估计方法、内点、
    缩放、平移以及配对/单侧统计，供状态栏、调试和校正对话框使用。
    """
    options = options or ImageOptions()
    notes: list[str] = []
    manual = _valid_manual_pairs(options.manual_pairs, left, right, notes)
    transform = _estimate_transform(left, right, notes)
    result = _core_match(left, right, transform, options, manual)
    pairs: list[_Pair] = list(result["pairs"])
    unmatched_left: list[int] = list(result["unmatched_left"])
    unmatched_right: list[int] = list(result["unmatched_right"])

    # 用已匹配文字精化几何变换后重新分配一次（提高不同缩放/位置下的匹配率）
    refined = _refit_from_pairs(left, right, pairs, transform)
    if refined is not None and _transform_delta(transform, refined) > 0.005:
        refined.support = _transform_support(refined, left, right)
        second = _core_match(left, right, refined, options, manual)
        second_pairs: list[_Pair] = list(second["pairs"])
        auto_first = [p for p in pairs if not p.manual]
        auto_second = [p for p in second_pairs if not p.manual]
        better = len(auto_second) > len(auto_first) or (
            len(auto_second) == len(auto_first)
            and sum(p.score for p in auto_second) >= sum(p.score for p in auto_first) - 1e-6
        )
        if better:
            notes.append("匹配后精化几何变换并重新分配")
            transform = refined
            pairs = second_pairs
            unmatched_left = list(second["unmatched_left"])
            unmatched_right = list(second["unmatched_right"])

    diffs = _build_diffs(
        left,
        right,
        pairs,
        unmatched_left,
        unmatched_right,
        transform,
        options,
        notes,
    )
    auto_pairs = [p for p in pairs if not p.manual]
    transform_info: dict[str, Any] = transform.as_dict()
    transform_info.update(
        {
            "pairs": [[int(left.boxes[p.i].id), int(right.boxes[p.j].id)] for p in pairs],
            "manual_pairs": [
                [int(left.boxes[p.i].id), int(right.boxes[p.j].id)] for p in pairs if p.manual
            ],
            "matched_count": len(pairs),
            "auto_matched_count": len(auto_pairs),
            "only_left": [int(left.boxes[i].id) for i in unmatched_left],
            "only_right": [int(right.boxes[j].id) for j in unmatched_right],
            "uncertain_count": sum(1 for diff in diffs if diff.is_uncertain),
            "notes": notes,
        }
    )
    return diffs, transform_info


__all__ = ["match_pages", "text_similarity", "normalize_text"]
