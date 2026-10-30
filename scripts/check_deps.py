#!/usr/bin/env python3
"""构建环境依赖断言（CI 与本地构建前运行）。

检查项：
* 只有一个 OpenCV 发行包（opencv-python），且 cv2.__version__ 为 4.10.0；
* PySide6 / rapidocr-onnxruntime / onnxruntime / Pillow 版本符合锁定基线；
* RapidOCR 的 3 个 ONNX 模型与 config.yaml 实际存在且非空；
* `pip check` 无依赖冲突。

用法：
    python scripts/check_deps.py
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EXPECTED = {
    "PySide6": "6.8.1",
    "rapidocr-onnxruntime": "1.4.4",
    "onnxruntime": "1.20.1",
    "Pillow": "11.1.0",
    "opencv-python": "4.10.0.84",
}
MODELS = {
    "ch_PP-OCRv4_det_infer.onnx",
    "ch_PP-OCRv4_rec_infer.onnx",
    "ch_ppocr_mobile_v2.0_cls_infer.onnx",
}

errors: list[str] = []
warnings: list[str] = []


def version_of(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def main() -> int:
    print("=" * 72)
    print("依赖版本")
    print("=" * 72)
    for name, expected in EXPECTED.items():
        actual = version_of(name)
        status = "OK" if actual == expected else "MISMATCH"
        print(f"  {status:8s} {name:24s} 期望 {expected:12s} 实际 {actual}")
        if actual != expected:
            errors.append(f"{name} 版本应为 {expected}，实际 {actual}")

    # 单一 OpenCV 发行包
    opencv_dists = [
        dist.metadata["Name"]
        for dist in importlib.metadata.distributions()
        if dist.metadata["Name"] and "opencv" in dist.metadata["Name"].lower()
    ]
    print(f"\nOpenCV 发行包：{sorted(opencv_dists)}")
    if len(opencv_dists) != 1:
        errors.append(f"应只有 1 个 OpenCV 发行包，实际 {sorted(opencv_dists)}")
    if any(name.lower() == "opencv-python-headless" for name in opencv_dists):
        errors.append("检测到 opencv-python-headless，与 opencv-python 冲突，请 pip uninstall")

    import cv2  # noqa: PLC0415

    print(f"cv2.__version__ = {cv2.__version__}  ({cv2.__file__})")
    if not cv2.__version__.startswith("4.10.0"):
        errors.append(f"cv2.__version__ 应为 4.10.0.x，实际 {cv2.__version__}")

    # OCR 模型完整性
    print("\nOCR 模型：")
    spec = importlib.util.find_spec("rapidocr_onnxruntime")
    if spec is None or not spec.submodule_search_locations:
        errors.append("未找到 rapidocr_onnxruntime 包")
    else:
        root = Path(list(spec.submodule_search_locations)[0])
        model_dir = root / "models"
        actual_models = {p.name for p in model_dir.glob("*.onnx")} if model_dir.is_dir() else set()
        missing = MODELS - actual_models
        for name in sorted(actual_models):
            print(f"  OK  {name:44s} {(model_dir / name).stat().st_size:>10,} bytes")
        if missing:
            errors.append(f"缺少 OCR 模型：{sorted(missing)}")
        config = root / "config.yaml"
        print(f"  {'OK' if config.is_file() else 'MISSING'}  config.yaml")
        if not config.is_file():
            errors.append("缺少 rapidocr_onnxruntime/config.yaml")

    # pip check
    print("\npip check：")
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        capture_output=True,
        text=True,
    )
    print(proc.stdout.strip() or "(无输出)")
    if proc.returncode != 0:
        errors.append(f"pip check 失败：{proc.stdout.strip() or proc.stderr.strip()}")

    print()
    if errors:
        print("依赖断言失败：")
        for item in errors:
            print(f"  - {item}")
        return 1
    print("依赖断言通过：版本锁定一致、单一 OpenCV、OCR 模型齐全、pip check 无冲突。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
