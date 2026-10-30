#!/usr/bin/env bash
# EngineerDiff Linux 依赖收集自检（产物不交付，仅验证 PyInstaller spec 能真实收集依赖）
#
# 用途：
#   * 在 Linux 开发机/CI 上验证 packaging/engineerdiff.spec 可解析、RapidOCR 3 个
#     ONNX 模型与 config、ONNX Runtime/OpenCV 动态库、PySide6 Qt 插件确实进入 dist；
#   * 用 QT_QPA_PLATFORM=offscreen 运行打包产物的 --self-test；
#   * 真实 Windows 构建/安装包以 GitHub Actions windows-latest 为准。
#
# 用法：
#   scripts/build_linux_check.sh                # 完整检查（含 --self-test）
#   scripts/build_linux_check.sh --skip-self-test  # UI 尚未就绪时只验证收集
#
# 产物位于 build/linux-check/（.gitignore 已忽略 build/），不提交、不交付。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
    echo "ERROR: 找不到 Python 解释器：$PY（可用 PYTHON=... 覆盖）" >&2
    exit 1
fi

SKIP_SELF_TEST=0
if [[ "${1:-}" == "--skip-self-test" ]]; then
    SKIP_SELF_TEST=1
fi

OUT="$ROOT/build/linux-check"
DIST="$OUT/dist/EngineerDiff"
EXE="$DIST/EngineerDiff"
export QT_QPA_PLATFORM=offscreen

echo "======================================================================"
echo "EngineerDiff Linux PyInstaller 依赖收集自检"
echo "Python: $PY ($("$PY" --version 2>&1))"
echo "输出：$OUT（不交付；Windows 产物以 CI 为准）"
echo "======================================================================"

"$PY" scripts/check_spec.py
"$PY" scripts/check_deps.py

rm -rf "$OUT/dist" "$OUT/work"
mkdir -p "$OUT"

echo
echo ">>> PyInstaller one-dir 构建 ..."
"$PY" -m PyInstaller --noconfirm --clean \
    --distpath "$OUT/dist" \
    --workpath "$OUT/work" \
    --log-level INFO \
    packaging/engineerdiff.spec

if [[ ! -x "$EXE" ]]; then
    echo "ERROR: 未生成可执行文件 $EXE" >&2
    exit 1
fi

echo
echo ">>> 收集许可证与交付文档 ..."
"$PY" scripts/collect_licenses.py --dist "$DIST" || true
mkdir -p "$DIST/docs"
for f in docs/*.md; do
    [[ -f "$f" ]] && cp "$f" "$DIST/docs/"
done
[[ -d docs/screenshots ]] && cp -r docs/screenshots "$DIST/docs/"
cp LICENSE README.md "$DIST/" 2>/dev/null || true

echo
echo ">>> 运行 exe --version 冒烟 ..."
"$EXE" --version

VERIFY_ARGS=(--dist "$DIST" --exe "$EXE" --require-frozen --timeout 900
    --json-output "$OUT/verify-bundle.json"
    --self-test-report-output "$OUT/self-test-report.json")
if [[ "$SKIP_SELF_TEST" == "1" ]]; then
    VERIFY_ARGS+=(--skip-self-test)
fi
VERIFY_RC=0
"$PY" scripts/verify_bundle.py "${VERIFY_ARGS[@]}" || VERIFY_RC=$?

echo
echo ">>> 写依赖收集证据 ..."
EVIDENCE="$OUT/evidence.txt"
{
    echo "# Linux PyInstaller 依赖收集证据"
    echo "时间: $(date -Is)"
    echo "Python: $("$PY" --version 2>&1)"
    echo "PyInstaller: $("$PY" -m PyInstaller --version)"
    echo "文件类型: $(file -b "$EXE")"
    echo "dist 大小: $(du -sh "$DIST" | cut -f1)"
    echo
    echo "## OCR 模型（3 个 ONNX + config.yaml）"
    find "$DIST" -path '*rapidocr_onnxruntime*' -type f \
        \( -name '*.onnx' -o -name 'config.yaml' \) -print0 |
        sort -z | xargs -0 -r sha256sum
    echo
    echo "## ONNX Runtime 动态库"
    find "$DIST" -type f \( -iname '*onnxruntime*.so*' -o -iname 'onnxruntime*.dll' \) -print |
        sort | while read -r f; do echo "$(du -h "$f" | cut -f1)  $f"; done
    echo
    echo "## OpenCV 模块/动态库"
    find "$DIST" -type f \( -iname 'cv2*.so*' -o -iname 'libopencv*' -o -iname 'opencv_videoio*' \) -print |
        sort | head -20
    echo
    echo "## Qt 核心库与插件"
    find "$DIST" -type f \( -name 'libQt6Core.so*' -o -name 'libQt6Gui.so*' -o -name 'libQt6Widgets.so*' \) |
        sort
    find "$DIST" -path '*plugins*' -type f -name '*.so' | sort | sed -n '1,40p'
    echo
    echo "## 应用资源"
    find "$DIST" -path '*engineerdiff/resources*' -type f | sort
    echo
    echo "## 许可证与 NOTICE"
    ls -l "$DIST/LICENSE" "$DIST/THIRD-PARTY-NOTICES.md" "$DIST/MODEL_LICENSES.md" "$DIST/LICENSES/MANIFEST.json" 2>&1
    echo
    echo "## self-test 报告"
    cat "$OUT/self-test-report.json" 2>/dev/null || echo "(未生成：可能使用了 --skip-self-test 或 UI 模块未就绪)"
} > "$EVIDENCE" 2>&1 || true

echo
echo "======================================================================"
echo "Linux 依赖收集自检完成（产物仅用于验证，不交付）"
echo "  证据: $EVIDENCE"
echo "  校验: $OUT/verify-bundle.json"
echo "======================================================================"
exit "$VERIFY_RC"
