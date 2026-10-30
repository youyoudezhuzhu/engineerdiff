"""图片 OCR 比较：匹配算法与比较引擎。"""

from __future__ import annotations

from .engine import ImageCompareError, compare_images
from .matcher import match_pages, normalize_text, text_similarity

__all__ = [
    "ImageCompareError",
    "compare_images",
    "match_pages",
    "normalize_text",
    "text_similarity",
]
