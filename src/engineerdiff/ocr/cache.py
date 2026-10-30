"""OCR 结果磁盘缓存。

缓存只保存**成功**的识别结果（包括“成功但未识别到文字”），绝不用缓存掩盖 OCR 错误。
键为图片文件 SHA-256；缓存内容带版本号，OCR 模型/识别流程升级后自动失效。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

#: 缓存结构版本。修改 OCR 结果结构、后处理逻辑或升级模型时递增。
CACHE_VERSION = "ocr-cache-v1"

#: 缓存文件名后缀
CACHE_SUFFIX = ".json"

_CHUNK = 1024 * 1024


def default_cache_dir() -> Path:
    """返回默认缓存目录（不依赖 Qt，便于核心模块与测试使用）。

    优先读取环境变量 ``ENGINEERDIFF_CACHE_DIR``（便于测试隔离），
    其次使用各平台的标准缓存目录。
    """
    env = os.environ.get("ENGINEERDIFF_CACHE_DIR")
    if env:
        return Path(env).expanduser() / "ocr"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "EngineerDiff" / "cache" / "ocr"
        return Path(tempfile.gettempdir()) / "EngineerDiff" / "cache" / "ocr"
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "EngineerDiff" / "ocr"
    return Path.home() / ".cache" / "EngineerDiff" / "ocr"


def sha256_file(path: str | Path) -> str:
    """分块计算文件 SHA-256，大图不占内存。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class OcrCache:
    """按图片内容哈希读写 OCR JSON 缓存。

    所有 IO 失败都静默降级为“未命中”，不影响识别主流程；写入使用原子替换。
    """

    def __init__(self, cache_dir: str | Path | None = None, version: str = CACHE_VERSION) -> None:
        self._dir = Path(cache_dir).expanduser() if cache_dir else default_cache_dir()
        self.version = version

    # ------------------------------------------------------------------ 路径
    @property
    def directory(self) -> Path:
        return self._dir

    def path_for(self, key: str) -> Path:
        return self._dir / f"{key}{CACHE_SUFFIX}"

    # ------------------------------------------------------------------ 读写
    def load(self, key: str) -> dict[str, Any] | None:
        """读取缓存；不存在、损坏、版本不匹配时返回 None。"""
        path = self.path_for(key)
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("cache_version") != self.version:
            return None
        if not isinstance(payload.get("boxes"), list):
            return None
        return payload

    def store(self, key: str, payload: dict[str, Any]) -> bool:
        """写入缓存（原子替换）。失败返回 False，不抛异常。"""
        data = dict(payload)
        data["cache_version"] = self.version
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=str(self._dir))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, self.path_for(key))
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except OSError:
            return False
        return True

    def clear(self) -> int:
        """删除全部缓存文件，返回删除数量。"""
        removed = 0
        try:
            entries = list(self._dir.glob(f"*{CACHE_SUFFIX}"))
        except OSError:
            return 0
        for path in entries:
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def count(self) -> int:
        try:
            return sum(1 for _ in self._dir.glob(f"*{CACHE_SUFFIX}"))
        except OSError:
            return 0
