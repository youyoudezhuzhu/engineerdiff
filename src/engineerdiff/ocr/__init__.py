"""内置离线 OCR（RapidOCR + ONNX Runtime）。"""

from __future__ import annotations

from .cache import CACHE_VERSION, OcrCache, default_cache_dir, sha256_file
from .engine import (
    CancelCallback,
    OcrCancelled,
    OcrError,
    OcrService,
    ProgressCallback,
    get_ocr_service,
    models_dir,
)

__all__ = [
    "CACHE_VERSION",
    "CancelCallback",
    "OcrCache",
    "OcrCancelled",
    "OcrError",
    "OcrService",
    "ProgressCallback",
    "default_cache_dir",
    "get_ocr_service",
    "models_dir",
    "sha256_file",
]
