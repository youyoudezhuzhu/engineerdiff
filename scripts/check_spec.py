#!/usr/bin/env python3
"""打包配置静态检查（可跨平台运行，不执行 PyInstaller）。

在构建前快速发现：
* PyInstaller spec 语法错误、入口/图标/版本资源路径缺失；
* 版本号在 pyproject.toml / version.py / version_info.txt / Inno Setup 脚本间不一致；
* 关键收集项缺失（RapidOCR 模型、onnxruntime、cv2、PySide6 插件、console=False 等）；
* requirements 中的 OpenCV/Pillow 版本与实测基线一致且无双 OpenCV 发行包；
* LICENSE、交付文档、工作流文件存在。

另外打印"Windows 专属项"清单，避免把 Linux 本地验证结果误当 Windows 结果。

用法：
    python scripts/check_spec.py
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC = PROJECT_ROOT / "packaging" / "engineerdiff.spec"
ISS = PROJECT_ROOT / "packaging" / "engineerdiff.iss"
LAUNCHER = PROJECT_ROOT / "packaging" / "launcher.py"
VERSION_INFO = PROJECT_ROOT / "packaging" / "version_info.txt"
ISL = PROJECT_ROOT / "packaging" / "languages" / "ChineseSimplified.isl"
ICON = PROJECT_ROOT / "src" / "engineerdiff" / "resources" / "engineerdiff.ico"
PNG = PROJECT_ROOT / "src" / "engineerdiff" / "resources" / "engineerdiff.png"

errors: list[str] = []
warnings: list[str] = []


def ok(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def warn(condition: bool, message: str) -> None:
    if not condition:
        warnings.append(message)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def module_version() -> str:
    ns: dict = {}
    exec(compile(read(PROJECT_ROOT / "src" / "engineerdiff" / "version.py"), "version.py", "exec"), ns)
    return str(ns["__version__"])


def main() -> int:
    for path in (SPEC, ISS, LAUNCHER, VERSION_INFO, ISL, ICON, PNG):
        ok(path.is_file(), f"缺少必要文件：{path.relative_to(PROJECT_ROOT)}")
    if errors:
        return report()

    version = module_version()

    # --- pyproject / version.py / version_info.txt / iss 版本一致性 -------------
    pyproject = tomllib.loads(read(PROJECT_ROOT / "pyproject.toml"))
    ok(pyproject["project"]["version"] == version, "pyproject.toml 版本与 version.py 不一致")
    ok(pyproject["project"]["scripts"]["engineerdiff"] == "engineerdiff.app:main", "pyproject 入口契约不是 engineerdiff.app:main")

    vi = read(VERSION_INFO)
    match = re.search(r"filevers=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)", vi)
    ok(match is not None, "version_info.txt 缺少 filevers")
    if match:
        ok(".".join(match.groups()[:3]) == version, f"version_info.txt 版本 {match.groups()[:3]} != {version}")

    iss = read(ISS)
    iss_version = re.search(r'#define APP_VERSION "([^"]+)"', iss)
    ok(iss_version is not None and iss_version.group(1) == version, "Inno Setup APP_VERSION 与 version.py 不一致")
    ok("245CB9EB-4ABF-4388-BCAB-0DF568AED985" in iss, "Inno Setup AppId 不是预期稳定 GUID")
    ok("AppId={#APP_GUID}" in iss, "Inno Setup AppId 未使用稳定 GUID 定义")
    ok("PrivilegesRequired=lowest" in iss, "安装包未设置 per-user 安装（PrivilegesRequired=lowest）")
    ok("{localappdata}\\Programs\\EngineerDiff" in iss, "安装目录不是 {localappdata}\\Programs\\EngineerDiff")
    ok("EngineerDiff-{#APP_VERSION}-Setup-x64" in iss, "安装包输出文件名不符合约定")
    ok("ChineseSimplified.isl" in iss, "安装包未引用简体中文语言文件")
    ok("LicenseFile=" in iss, "安装包缺少许可页（LicenseFile）")
    ok("desktopicon" in iss, "安装包缺少可选桌面快捷方式任务")
    ok("uninstallexe" in iss, "安装包缺少卸载入口")

    # --- spec 内容 ------------------------------------------------------------
    spec = read(SPEC)
    for needle, message in (
        ("collect_data_files(", "spec 未收集 RapidOCR 数据文件"),
        ('includes=["config.yaml", "models/*.onnx"]', "spec 未显式收集 config.yaml + models/*.onnx"),
        ("collect_dynamic_libs(\"onnxruntime\")", "spec 未收集 onnxruntime 动态库"),
        ("collect_dynamic_libs(\"cv2\")", "spec 未收集 OpenCV 动态库"),
        ("plugins", "spec 未显式收集 Qt 插件"),
        ("console=False", "spec 未生成窗口版 exe（console=False）"),
        ('name="EngineerDiff"', "spec 输出名不是 EngineerDiff"),
        ("contents_directory=\"_internal\"", "spec 未固定 one-dir _internal 布局"),
        ("COLLECT(", "spec 不是 one-dir（缺少 COLLECT）"),
        ("QtWebEngineCore", "spec 未排除 QtWebEngine"),
        ("ENGINEERDIFF_LAUNCHER", "spec 缺少本地依赖收集检查入口覆盖说明"),
    ):
        ok(needle in spec, message)
    ok("ONNX" in spec and "len(onnx_models) < 3" in spec, "spec 未在构建期校验 3 个 ONNX 模型")

    # launcher 必须调用约定入口
    launcher = read(LAUNCHER)
    ok("from engineerdiff.app import main" in launcher, "launcher.py 未调用 engineerdiff.app:main")
    app_py = PROJECT_ROOT / "src" / "engineerdiff" / "app.py"
    ok(app_py.is_file(), "缺少 src/engineerdiff/app.py（入口约定）")
    if app_py.is_file():
        app_src = read(app_py)
        ok("def main(" in app_src, "app.py 未定义 main()")
        ok("--self-test" in app_src, "app.py 未实现 --self-test")
        ok("--self-test-report" in app_src, "app.py 未实现 --self-test-report")

    # --- requirements ---------------------------------------------------------
    req = read(PROJECT_ROOT / "requirements.txt")
    ok("opencv-python==4.10.0.84" in req, "requirements.txt 未锁定 opencv-python==4.10.0.84")
    req_lines = [line.split("#", 1)[0].strip().lower() for line in req.splitlines()]
    ok(
        not any(line.startswith("opencv-python-headless") for line in req_lines),
        "requirements.txt 仍包含 opencv-python-headless（会与 opencv-python 重叠）",
    )
    ok("Pillow==11.1.0" in req, "requirements.txt 未锁定 Pillow==11.1.0")
    ok("PySide6==6.8.1" in req, "requirements.txt 未锁定 PySide6==6.8.1")
    ok("rapidocr-onnxruntime==1.4.4" in req, "requirements.txt 未锁定 rapidocr-onnxruntime==1.4.4")
    ok("onnxruntime==1.20.1" in req, "requirements.txt 未锁定 onnxruntime==1.20.1")
    req_dev = read(PROJECT_ROOT / "requirements-dev.txt")
    ok("pyinstaller>=6.11,<7" in req_dev, "requirements-dev.txt 未包含 pyinstaller 版本区间")
    ok("pytest>=8.3,<9" in req_dev, "requirements-dev.txt 未包含 pytest 版本区间")

    # --- 交付文件 -------------------------------------------------------------
    for rel in (
        "LICENSE",
        "docs/user-guide.md",
        "docs/known-limitations.md",
        "docs/third-party-licenses.md",
        ".github/workflows/build-windows.yml",
        "scripts/collect_licenses.py",
        "scripts/verify_bundle.py",
        "scripts/build_windows.ps1",
        "scripts/build_linux_check.sh",
        "scripts/find_iscc.ps1",
        "scripts/install_inno.ps1",
        "scripts/make_icons.py",
        "packaging/licenses/LGPL-3.0-only.txt",
        "packaging/licenses/Apache-2.0.txt",
        "packaging/licenses/PSF-2.0.txt",
        "packaging/languages/README.md",
    ):
        ok((PROJECT_ROOT / rel).is_file(), f"缺少交付文件：{rel}")

    if "mit license" not in read(PROJECT_ROOT / "LICENSE").lower():
        errors.append("LICENSE 不是 MIT 许可证")

    # --- .gitignore -----------------------------------------------------------
    gitignore = read(PROJECT_ROOT / ".gitignore")
    for pattern in ("dist/", "build/", "release/"):
        ok(pattern in gitignore, f".gitignore 未忽略 {pattern}")

    print("\nWindows 专属项（Linux 本地构建无法验证，以 GitHub Actions windows-latest 为准）：")
    for item in (
        "EXE(icon=resources/engineerdiff.ico, version=packaging/version_info.txt) 仅在 win32 生效",
        "Qt 平台插件为 qwindows.dll（Linux 本地为 libqxcb.so）",
        "onnxruntime 为 onnxruntime.dll / onnxruntime_providers_shared.dll（Linux 为 .so）",
        "Inno Setup 安装包只能在 Windows 上由 ISCC.exe 生成",
        "窗口版 exe 的 --self-test 退出码与报告需在 Windows 上复核",
    ):
        print(f"  - {item}")
    return report()


def report() -> int:
    if warnings:
        print("\n警告：")
        for item in warnings:
            print(f"  - {item}")
    if errors:
        print("\n错误：")
        for item in errors:
            print(f"  - {item}")
        print(f"\n静态检查失败：{len(errors)} 项错误，{len(warnings)} 项警告")
        return 1
    print(f"\n静态检查通过（{len(warnings)} 项警告）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
