"""后台比较线程。UI 线程只接收信号。"""

from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QThread, Signal

from ..compare import ComparisonCancelled, run_comparison
from ..models import AppSettings, CompareMode


class CompareWorker(QThread):
    progress = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        mode: CompareMode,
        left_path: str,
        right_path: str,
        settings: AppSettings,
        ocr_service=None,
        parent=None,
    ):
        super().__init__(parent)
        self._mode = mode
        self._left = left_path
        self._right = right_path
        self._settings = settings
        self._ocr = ocr_service
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def run(self) -> None:  # noqa: D401
        try:
            result = run_comparison(
                self._mode,
                self._left,
                self._right,
                self._settings,
                progress=lambda p, m: self.progress.emit(p, m),
                cancel=self._cancel_event.is_set,
                ocr_service=self._ocr,
            )
            if self._cancel_event.is_set():
                self.cancelled.emit()
                return
            self.succeeded.emit(result)
        except ComparisonCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001
            detail = traceback.format_exc(limit=8)
            try:
                from pathlib import Path

                log = Path.home() / ".engineerdiff-error.log"
                log.write_text(detail, encoding="utf-8")
            except Exception:
                pass
            self.failed.emit(f"{exc}\n\n详细堆栈已写入 ~/.engineerdiff-error.log")
