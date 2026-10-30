#!/usr/bin/env python3
"""收集随包分发的第三方许可证，并生成 NOTICE / 模型许可说明。

用法（构建脚本在 PyInstaller 完成后调用）：
    python scripts/collect_licenses.py --dist dist/EngineerDiff

产物（写入 <dist>/）：
    LICENSE                       项目 MIT 许可证
    THIRD-PARTY-NOTICES.md        第三方组件、许可证与分发方式汇总
    MODEL_LICENSES.md             OCR 模型来源、版本与 SHA-256
    LICENSES/MANIFEST.json        机器可读清单（组件、版本、SPDX、许可证文件）
    LICENSES/<package>/...        从各 wheel 的 dist-info 复制的许可证原文；
                                  缺失时回退到 packaging/licenses/ 下的标准许可证文本

设计原则：
* 以构建环境实际安装的发行包为准（不虚构版本）；排除仅用于构建/测试的工具。
* 优先复制上游 wheel 自带的许可证原文；只有确实缺失时才使用仓库内置文本，
  并在 MANIFEST 中标记 source=vendored。
* PySide6 / Qt 的 LGPL-3.0 合规说明固定写入 THIRD-PARTY-NOTICES.md。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGING_LICENSES = PROJECT_ROOT / "packaging" / "licenses"

# 仅构建/测试使用、不随应用分发的发行包（大小写不敏感，- 和 _ 等价）
BUILD_ONLY = {
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "altgraph",
    "pytest",
    "pluggy",
    "iniconfig",
    "pygments",
    "xlwt",
    "pip",
    "setuptools",
    "wheel",
    "engineerdiff",
}

# 实际随包的运行时组件与 SPDX 标识（以构建环境为准，未导入的包不会进入安装包）
SPDX: dict[str, str] = {
    "pyside6": "LGPL-3.0-only",
    "pyside6-essentials": "LGPL-3.0-only",
    "pyside6-addons": "LGPL-3.0-only",
    "shiboken6": "LGPL-3.0-only",
    "rapidocr-onnxruntime": "Apache-2.0",
    "onnxruntime": "MIT",
    "opencv-python": "Apache-2.0",
    "opencv-python-headless": "Apache-2.0",
    "pillow": "HPND",
    "numpy": "BSD-3-Clause",
    "openpyxl": "MIT",
    "et-xmlfile": "MIT",
    "xlrd": "BSD-3-Clause",
    "charset-normalizer": "MIT",
    "pyclipper": "MIT",
    "shapely": "BSD-3-Clause",
    "pyyaml": "MIT",
    "six": "MIT",
    "tqdm": "MPL-2.0 AND MIT",
    "protobuf": "BSD-3-Clause",
    "flatbuffers": "Apache-2.0",
    "sympy": "BSD-3-Clause",
    "mpmath": "BSD-3-Clause",
    "coloredlogs": "MIT",
    "humanfriendly": "MIT",
    "packaging": "Apache-2.0 OR BSD-2-Clause",
}

# SPDX 标识 -> 仓库内置标准许可证文本（仅在 wheel 未携带原文时回退）
VENDORED = {
    "LGPL-3.0-only": ["LGPL-3.0-only.txt", "GPL-3.0-only.txt"],
    "Apache-2.0": ["Apache-2.0.txt"],
    "MIT": ["MIT.txt"],
    "BSD-3-Clause": ["BSD-3-Clause.txt"],
    "MPL-2.0 AND MIT": ["MPL-2.0.txt", "MIT.txt"],
}

LICENSE_FILE_RE = re.compile(r"(licen[cs]e|copying|notice|copyright)", re.IGNORECASE)

QT_LGPL_STATEMENT = """\
## PySide6 / Qt（LGPL-3.0-only）合规说明

- 本软件以 **动态链接** 方式使用 PySide6（Qt for Python）与 Qt 6.8.1 共享库：
  `PySide6/Qt6*.dll`、`PySide6/plugins/**` 以独立文件随 one-dir 安装包分发，
  用户可自行替换为兼容版本的 Qt 库（见安装目录 `_internal/PySide6/`）。
- 本软件 **未修改** Qt/PySide6 源代码，也未静态链接 Qt 库。
- 许可证全文见 `LICENSES/pyside6/LGPL-3.0-only.txt`（对应 LGPL-3.0 与 GPL-3.0）。
- Qt 源码获取方式：<https://download.qt.io/official_releases/qt/>（版本 6.8.1），
  或 <https://code.qt.io/cgit/qt/>；如按 LGPL-3.0 第 6 条需要源码副本，可向
  分发者索取对应版本源码或获取方式，本项目承诺提供。
- PySide6 项目：<https://pyside.org>（LGPL-3.0 / GPL-3.0 / 商业许可三选一，
  本软件选择 LGPL-3.0 分发）。
- Qt 商标与版权归 The Qt Company Oy 及其贡献者所有。
"""


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dist_license_files(dist: importlib.metadata.Distribution) -> list[importlib.metadata.PackagePath]:
    files = dist.files or []
    result = []
    for f in files:
        name = Path(str(f)).name
        if not LICENSE_FILE_RE.search(name):
            continue
        if name.lower().endswith((".py", ".pyc", ".pyi", ".so", ".dll", ".pyd")):
            continue
        if "dist-info" not in str(f) and "LICENSE" not in name.upper():
            # 只从 dist-info 或包内明确的 LICENSE/COPYING/NOTICE 文件复制
            if not re.search(r"(LICEN[CS]E|COPYING|NOTICE)", name, re.IGNORECASE):
                continue
        result.append(f)
    return result


def copy_license_file(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / src.name
    if target.exists():
        target = dest_dir / f"{src.parent.name}__{src.name}"
    shutil.copyfile(src, target)
    return target


def find_models() -> list[Path]:
    spec = importlib.util.find_spec("rapidocr_onnxruntime")
    if spec is None or not spec.submodule_search_locations:
        return []
    root = Path(list(spec.submodule_search_locations)[0])
    return sorted((root / "models").glob("*.onnx"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_notices(dist_dir: Path, manifest: list[dict]) -> None:
    lines: list[str] = []
    lines.append("# EngineerDiff 第三方软件与许可证（随包生成）\n")
    lines.append(
        "本文件由 `scripts/collect_licenses.py` 在构建时根据实际安装的 Python 发行包自动生成。\n"
        "EngineerDiff 本体以 MIT 许可证发布（见 `LICENSE`）。\n"
    )
    lines.append(
        "> 说明：PyInstaller 按实际 import 收集模块，未导入的包不会进入安装包；"
        "下表为构建环境中的运行时依赖，便于合规审计。\n"
    )
    lines.append("## 组件清单\n")
    lines.append("| 组件 | 版本 | SPDX 许可证 | 许可证文件 |\n|---|---|---|---|")
    for item in manifest:
        if item["license_files"]:
            files = "<br>".join(f"`{p}`" for p in item["license_files"])
        elif item["spdx"]:
            files = "（SPDX 标识，见许可证全文目录）"
        else:
            files = "**缺失，请人工核对**"
        lines.append(f"| {item['name']} | {item['version']} | {item['spdx'] or '未标注'} | {files} |")
    lines.append("")
    lines.append(QT_LGPL_STATEMENT)
    lines.append(
        "## 其他随包分发内容\n\n"
        "- **OpenCV（opencv-python）**：Apache-2.0。wheel 内含第三方组件"
        "（含 FFmpeg，LGPL-2.1 等），原始声明见 `LICENSES/opencv-python/LICENSE-3RD-PARTY.txt`。\n"
        "- **RapidOCR（rapidocr-onnxruntime）**：Apache-2.0，许可证见 "
        "`LICENSES/rapidocr-onnxruntime/`；模型授权见 `MODEL_LICENSES.md`。\n"
        "- **ONNX Runtime**：MIT，许可证见 `LICENSES/onnxruntime/`（wheel 自带或标准 MIT 文本）。\n"
        "- **Python 运行时**（PyInstaller 随包分发）：PSF-2.0，见 `LICENSES/Python-3.11/PSF-2.0.txt`。\n"
        "- **PyInstaller bootloader**：GPL-2.0-or-later，附带允许分发非自由程序产物的特例；"
        "许可证见 `LICENSES/PyInstaller/COPYING.txt`。\n"
        "- **Inno Setup**：安装程序由 Inno Setup 6 生成，其许可证见 "
        "`LICENSES/Inno Setup/Inno-Setup-LICENSE.txt`；允许商业分发并要求保留版权声明。\n"
        "- **Inno Setup 简体中文语言文件**：MIT，见 "
        "`LICENSES/Inno Setup Chinese Translation/ChineseSimplified-Translation-MIT.txt`。\n"
        "- **字体**：应用界面使用系统字体；测试素材中的 Noto Sans SC（SIL OFL-1.1）"
        "不随安装包分发。\n"
    )
    (dist_dir / "THIRD-PARTY-NOTICES.md").write_text("\n".join(lines), encoding="utf-8")


def write_model_licenses(dist_dir: Path) -> None:
    models = find_models()
    lines = [
        "# OCR 模型许可与来源\n",
        "EngineerDiff 内置的 OCR 模型来自 RapidOCR 发行包，随安装包离线分发，"
        "运行时不联网下载。\n",
        "## 引擎与模型来源\n",
        "- 推理引擎：`rapidocr-onnxruntime==1.4.4`（Apache-2.0，"
        "<https://github.com/RapidAI/RapidOCR>）。",
        "- 模型体系：PP-OCR（PaddleOCR / 百度），模型版权归 PaddleOCR 项目及贡献者所有，",
        "  以 Apache-2.0 许可证发布：<https://github.com/PaddlePaddle/PaddleOCR>。",
        "- RapidOCR 在其发行包中再分发上述 PP-OCR 模型；本软件仅通过 RapidOCR 使用模型，",
        "  不引入 PaddlePaddle 运行时，也不修改模型文件。",
        "- Apache-2.0 许可证全文：`LICENSES/rapidocr-onnxruntime/Apache-2.0.txt`。\n",
        "## 随包模型文件与 SHA-256\n",
        "| 模型文件 | 大小（字节） | SHA-256 |",
        "|---|---|---|",
    ]
    for model in models:
        lines.append(f"| `{model.name}` | {model.stat().st_size} | `{sha256(model)}` |")
    lines.append("")
    lines.append(
        "## 免责说明\n\n"
        "OCR 识别结果可能存在误差（见 `docs/known-limitations.md`）；本软件允许用户"
        "在“OCR 校对”对话框中修正文本，并以修正结果重新比较。\n"
    )
    (dist_dir / "MODEL_LICENSES.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="收集并生成 EngineerDiff 第三方许可证")
    parser.add_argument("--dist", required=True, type=Path, help="PyInstaller one-dir 输出目录")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="运行时包缺少可识别许可证时返回非 0（CI 建议开启）",
    )
    args = parser.parse_args()

    dist_dir: Path = args.dist
    if not dist_dir.is_dir():
        print(f"ERROR: dist 目录不存在：{dist_dir}", file=sys.stderr)
        return 2
    licenses_dir = dist_dir / "LICENSES"
    if licenses_dir.exists():
        shutil.rmtree(licenses_dir)
    licenses_dir.mkdir(parents=True)

    site_packages = Path(sys.prefix) / ("Lib/site-packages" if sys.platform == "win32" else "lib/python3.11/site-packages")
    # 更可靠的方式：以安装的 dist 定位 site-packages
    try:
        sample = importlib.metadata.distribution("PySide6")
        site_packages = Path(sample.locate_file(""))
    except importlib.metadata.PackageNotFoundError:
        pass

    manifest: list[dict] = []
    missing: list[str] = []
    for dist in sorted(importlib.metadata.distributions(), key=lambda d: _norm(d.metadata["Name"])):
        name = dist.metadata["Name"]
        key = _norm(name)
        if key in BUILD_ONLY:
            continue
        version = dist.version
        spdx = SPDX.get(key, "")
        copied: list[str] = []
        used_dist_info = False
        dest_dir = licenses_dir / key

        for rel in dist_license_files(dist):
            src = Path(dist.locate_file(rel))
            if not src.is_file():
                continue
            try:
                target = copy_license_file(src, dest_dir)
                copied.append(str(target.relative_to(dist_dir)).replace("\\", "/"))
                used_dist_info = True
            except OSError as exc:
                print(f"WARN: 复制许可证失败 {src}: {exc}", file=sys.stderr)

        if not copied and spdx:
            for vendored_name in VENDORED.get(spdx, []):
                src = PACKAGING_LICENSES / vendored_name
                if src.is_file():
                    target = copy_license_file(src, dest_dir)
                    copied.append(str(target.relative_to(dist_dir)).replace("\\", "/"))

        if not copied:
            missing.append(f"{name} {version} (SPDX: {spdx or 'unknown'})")

        manifest.append(
            {
                "name": name,
                "version": version,
                "spdx": spdx,
                "license_files": copied,
                "source": "dist-info" if used_dist_info else ("vendored" if copied else "missing"),
            }
        )

    # 构建工具 / Python 运行时 / 翻译文件等固定条目（随产物分发或与产物直接相关）
    pyinstaller_license: Path | None = None
    try:
        pyi_dist = importlib.metadata.distribution("pyinstaller")
        for rel in pyi_dist.files or []:
            if Path(str(rel)).name.upper() == "COPYING.TXT":
                candidate = Path(pyi_dist.locate_file(rel))
                if candidate.is_file():
                    pyinstaller_license = candidate
                    break
    except importlib.metadata.PackageNotFoundError:
        pass

    extra_files: list[tuple[Path, str]] = [
        (PACKAGING_LICENSES / "PSF-2.0.txt", "Python-3.11/PSF-2.0.txt"),
        (pyinstaller_license or Path("__missing__"), "PyInstaller/COPYING.txt"),
        (PACKAGING_LICENSES / "Inno-Setup-LICENSE.txt", "Inno Setup/Inno-Setup-LICENSE.txt"),
        (
            PACKAGING_LICENSES / "ChineseSimplified-Translation-MIT.txt",
            "Inno Setup Chinese Translation/ChineseSimplified-Translation-MIT.txt",
        ),
    ]
    for src, rel in extra_files:
        if src.is_file():
            target = licenses_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)

    # 项目 LICENSE（根目录，便于直接阅读）
    project_license = PROJECT_ROOT / "LICENSE"
    if project_license.is_file():
        shutil.copyfile(project_license, dist_dir / "LICENSE")

    (licenses_dir / "MANIFEST.json").write_text(
        json.dumps(
            {
                "generated_by": "scripts/collect_licenses.py",
                "python": sys.version.split()[0],
                "packages": manifest,
                "missing": missing,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_notices(dist_dir, manifest)
    write_model_licenses(dist_dir)

    print(f"licenses -> {licenses_dir}")
    print(f"notice   -> {dist_dir / 'THIRD-PARTY-NOTICES.md'}")
    print(f"models   -> {dist_dir / 'MODEL_LICENSES.md'}")
    if missing:
        print("WARN: 以下组件未找到许可证原文，请人工补充：", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        if args.strict:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
