# EngineerDiff 开源项目调查笔记（证据版）

> 调查人：research-scout　调查日期：2026-10-30（Asia/Shanghai）
> 目标：为 Windows 本地多格式文件差异工具 EngineerDiff（Python 3.11 + PySide6，主线 MIT，安装包需随附许可证/NOTICE）做技术选型。
> 本文件记录实际执行的命令、clone 的 commit、许可证原文关键点、依赖、维护状态与可复用性判断。结论报告见 [technical-selection.md](technical-selection.md)。

## 0. 调查方法与限制

所有第三方仓库克隆到 `/tmp/engdiff-research`，**未放入项目仓库**。主要命令：

```bash
# 浅克隆（commit hash 为 2026-10-30 当时默认分支 HEAD）
git clone --depth 1 https://github.com/<org>/<repo>.git /tmp/engdiff-research/<org>_<repo>
git -C <dir> log -1 --format='%H %ad %s' --date=iso
git -C <dir> tag | tail -5

# 维护状态/发布：GitHub REST API
curl -sL https://api.github.com/repos/<org>/<repo>
curl -sL "https://api.github.com/repos/<org>/<repo>/releases?per_page=2"

# PyPI 元数据与产物检查
curl -sL https://pypi.org/pypi/<pkg>/json
python3 -c "import urllib.request; urllib.request.urlretrieve(<wheel_url>, 'x.whl')"
unzip -o x.whl -d x/ && find x -type f | sort
```

**限制（如实说明）**：
- WinMerge 未编译（需 VS2022 + MFC + 大量子模块/Externals），open-diff 未构建（Rust/Tauri/pnpm），hotdiff 未构建（Go 1.23 + Wails）；对三者的结论来自源码结构、许可证、构建配置与官方文档，而非运行截图。
- `xlsx-compare`、`xlsxDiff`、`sheet-diff` 只做源码/产物审查，未执行比较。
- RapidOCR 做了真实离线运行与 PyInstaller 打包验证，但测试图是脚本生成的英文文本（DejaVuSans 40px），**未覆盖中文小字体工程截图**；Windows 原生打包未验证（本机为 Linux）。
- PaddleOCR 未安装运行（paddlepaddle Windows wheel 单包已达 104.8MB，且模型由 paddlex 运行时下载），结论来自元数据/依赖/源码。

## 1. 必查项目逐个记录

### 1.1 WinMerge（WinMerge/winmerge）

- 证据：`/tmp/engdiff-research/WinMerge_winmerge`，HEAD `c94ac0e8e1ea2b955848c611dfdef9e986ded93e`（2026-10-29 22:14:25 +0900，"Move the manual to a separate submodule (#3746)"）。
- GitHub API：9,319 stars / 1,022 forks，`GPL-2.0`，C++，`pushed_at 2026-10-29`；最新 Release **v2.16.60（2026.10）**，published 2026-10-27，非 prerelease；open issues 497。
- 许可证：`LICENSE.md` 开头即 "GNU GENERAL PUBLIC LICENSE Version 2, June 1991"；`Src/COPYING` 同为 GPLv2 全文；`Src/WinIMergeLib.h` 文件头写 "License (GPLv2+)"。GPL 正文明确 "This General Public License does not permit incorporating your program into proprietary programs."（`LICENSE.md` 末尾）。→ **GPL-2.0 传染，不能链接进 MIT 闭源分发版**。
- 依赖/构建：C++/MFC/Windows-only，大量子模块（`.gitmodules`：winimerge、winwebdiff、7zip、xdiff、tree-sitter 等）；`Externals/versions.txt` 记录 POCO 1.15.1、boost 1.88.0、WinIMerge 1.0.60.0、LibXDiff、7-Zip 26.05、tree-sitter 等。
- 能力核查：
  - 文本双栏差异：`Src/MergeDoc*`、`DiffList*`、`CompareEngines/`；行内字符/词级差异：`Src/stringdiffs.cpp` 的 `ComputeWordDiffs(...)`，注释即 "ComputeWordDiffs"。
  - 表格：只有 CSV/TSV 等**分隔文本**的表格模式（`Src/TableProps.h` 只有 `istable/delimiter/quote/allowNewlinesInQuotes`；`OpenTableDlg.cpp` 的 CSV/DSV 选项）。
  - **没有 Excel 支持**：在 `Src/` 全部 `.cpp/.h` 中 grep `xlsx|xlsm|.xls` 无命中；即不支持 XLS/XLSX 多 Sheet、单元格标红。
  - 图片比较：`Src/ImgMergeFrm.cpp` + `Externals/winimerge`；图片 OCR 由子模块 WinIMerge 实现（`WinIMerge_winimerge/src/WinIMergeLib/Ocr.hpp` 直接 `#include <Windows.Media.Ocr.h>`，用 Windows 系统 OCR API，`ExtractTextFromImage` 暴露给 WinMerge）。即 **OCR 能力存在，但依赖 Windows 10/11 系统 OCR 与语言包**，不是自带模型的离线 OCR。
  - 组件化：`Src/WinIMergeLib.h` 是 COM 接口（`IImgMergeWindow`），但只覆盖**图片比较窗口**；文本/表格比较内嵌在 MFC 应用里，没有独立的可链接比较库。且 GPL 使“闭源分发 + 链接”不可行。
- 复用结论：**仅参考交互与差异导航（不链接、不复制代码）**。理由：GPL-2.0、C++/MFC/Windows-only、无 Excel、无可嵌入的比较内核；即便只复制 `stringdiffs` 算法实现也会构成 GPL 衍生作品。

### 1.2 open-diff（kygo8/open-diff）

- 证据：HEAD `f42cd1aec9f100b9f8db261a40f0d68e7dd47e22`（2026-10-14 17:01:01 +0800）。GitHub API：138 stars / 7 forks，`Apache-2.0`，TypeScript，pushed 2026-10-24；最新 Release **v1.3.2** published 2026-10-14；open issues 5。
- 形态：**Tauri 2 桌面应用**（`src-tauri/` + Vue 3 + Vite + naive-ui），不是 Python 库；`src-tauri/Cargo.toml` 工作区含 31 个成员 crate + 根应用包（diff-core/table-core/image-core/hex-core/merge-core…）。许可证文件为 Apache License 2.0 全文（201 行），仓库根**没有 NOTICE 文件**。
- 依赖：Rust workspace `license = "Apache-2.0"`；`table-core` 用 `calamine = "0.36.0"` 读 XLSX 多 Sheet/HTML table，`rust_xlsxwriter` 仅在 dev-dependencies；`diff-core` 实现 Myers/Patience/Histogram 行差异 + `InlineDiffSegment` 行内片段；`image` crate 做图片解码/像素比较。
- 能力核查：
  - 双栏：有（Text/Table/Image/Hex/Folder 多种会话）。
  - 字符级：文本 `InlineDiffSegments`；表格只到单元格粒度（`TableDiffStatus` per cell），未到单元格内字符级。
  - Excel 多 Sheet：`table-core` 用 calamine 遍历 `sheet_names()` 全量读入（`TableWorkbook { sheets }`），UI 侧 `TableSheets`/`TableCompareView`；项目文档 `docs/parity-acceptance-*.md` 自评 Table Compare 为 **PARTIAL**（key/ignore-column、日期边界仍待完善）。
  - 单元格标红：有（`TableCellDiff` 含 `Added/Removed/Modified` 状态，由前端渲染）。
  - OCR：全仓库 grep `ocr|tesseract|paddle` **无命中**，无 OCR、无文字匹配。
- 复用结论：**借鉴交互/表格差异建模（Apache-2.0 允许代码复用，但需 NOTICE/变更说明）；不直接依赖**。理由：技术栈是 Rust/Vue/Tauri，无法嵌入 PySide6 进程；且无 OCR。若移植 `table-core` 的行对齐/单元格 Diff 思路，需在文档中标注 Apache-2.0 来源（本项目最终选择自研、仅参考设计）。

### 1.3 hotdiff（hotdiff/hotdiff）

- 证据：HEAD `8ab4d5ea9c6aba4b6fb066402626cf39aa55b8e8`（2026-06-18 12:15:45 +0800）。GitHub API：1 star / 0 fork，`MIT`，Go，created 2026-06-17，pushed 2026-06-18；最新 Release **v0.3.0**（prerelease，2026-06-18）；commits API 显示 56 个提交，全部集中在 2026-06 中旬，之后无更新（约 4 个月停滞）。
- 形态：`app.go/main.go` + `go.mod`（Go 1.23 + Wails v2.12.0）+ `frontend/`（React 18 + Vite + Ant Design + **Monaco Editor**）+ `wails.json`；仓库仅 689KB。
- 能力：目录比较、文本双栏（Monaco diff，行/字符行内高亮由前端实现）、图片并排查看/像素比较、CSV 按文本 diff；**无 Excel 解析、无单元格标红、无 OCR**。
- 复用结论：**仅参考 UI/交互，不采用**。理由：Go+Wails 架构与 Python/PySide6 不匹配，功能覆盖不足，项目极新且单一维护者、已停滞。

### 1.4 xlsx-compare（WorkOfStan/xlsx-compare）

- 证据：HEAD `3a21ddb9087c125312b87158d7289b3e150c75ff`（2026-10-22 10:04:09 +0200）。GitHub API：0 stars，`MIT`，Python，pushed 2026-10-22；最新 tag/Release **v0.2.2**（2026-10-22）。仓库结构极简：单文件 `xlsx_compare.py`（344 行）+ tests + examples。
- 依赖（`pyproject.toml`）：`pandas`、`openpyxl`、`mininterface[basic]<=1.2.2`；`requires-python = ">=3.11"`；`license = {text = "MIT"}`，`LICENSE` 为 MIT 全文（Copyright 2025-2026 WorkOfStan）。
- 能力核查：
  - 按 Sheet 名逐 Sheet 比较；公式默认比较表达式，`--cached-values` 用 `data_only=True` 比较缓存值；缺失缓存值会报错退出（README 行为说明）。
  - 单元格按原坐标比较、忽略首尾空白、缺失单元格视为空串、按最大行列补齐；不支持 `.xls`、不比较格式/合并单元格。
  - **输出是 Excel 报告**：差异写入 `df-<sheet>` Sheet，单元格内容为文本 `old -> new`，**明确"plain text without cell highlighting"**；另有 `COMPARISON` 汇总 Sheet。
- 复用结论：**借鉴其公式/缓存值策略与 Sheet 配对规则（MIT 可复用代码，但需保留版权与许可声明）；不直接依赖**。理由：依赖 pandas + mininterface，是 CLI 报告工具而非标红 UI；本项目读取层用 openpyxl 直接做，无需引入 pandas。

### 1.5 xlsxDiff（rafal-dot/xlsxDiff）

- 证据：HEAD `8927e8c4cdf74b10257a92f072f04155d2b3bd33`（2023-03-12 13:26:12 +0100），**之后无提交**；无 tag/Release。GitHub API：22 stars，`AGPL-3.0`，Python，pushed 2023-03-12。
- 形态：单文件 `xlsxDiff.py`（454 行）+ 说明 PDF + test-data；依赖 `openpyxl` 读、`xlsxwriter` 写。
- 能力核查（README + 源码）：
  - 生成**新的 XLSX 报告**：新增片段蓝色下划线、删除片段红色删除线、未变单元格灰底、变更单元格浅绿/浅红底；Tab 用颜色区分新增/删除/改动/不变 → **有单元格标红与字符级（片段级）标记**。
  - 字符级用 `difflib.SequenceMatcher`（源码 `from difflib import SequenceMatcher`）做单元格内文本片段 diff；支持 `-f` 比较公式、`-c/-r` 以列/行为主键做行/列增删识别。
  - 非 GUI、非双栏实时查看；比较逻辑是"生成静态报告"。
- 复用结论：**仅参考算法与呈现方式，不复制代码**。理由：AGPL-3.0 是最强传染性 copyleft，把代码复制进 MIT 项目会让整个分发受 AGPL 约束；其行/列主键对齐与片段级 diff 思路可自研实现。

### 1.6 sheet-diff（PyPI：sheet-diff）

- 证据：PyPI `sheet-diff` **0.2.0**，`license = MIT`（版权 "Copyright (c) 2026 Muhammad Umer"），上传时间 **2026-09-30**；wheel `sheet_diff-0.2.0-py3-none-any.whl` 28,107 字节（纯 Python）；`Requires-Python >=3.10`；`Requires-Dist: pandas>=1.5, openpyxl>=3.0`，可选 extras：flask（web）、fsspec/s3fs/adlfs（remote）。仓库：`github.com/muhammadumer0266/sheet-diff`（PyPI 项目页给出）。
- wheel 内容（解包实证）：`sheetdiff/{__init__,cli,config,core,storage,webapp}.py` + `templates/{index,diff}.html` + `dist-info/{METADATA,WHEEL,entry_points,LICENSE}`；entry point `xldiff-web`。没有二进制/模型。
- 能力核查（`core.py` 源码）：
  - `diff_sheets(left,right,key=None,sheet_name=None)`：按 key 或**行号**匹行，输出 `added_row/removed_row/modified_cell` 列表；`diff_workbook` 汇总各 Sheet；`format_unified` 文本输出；`diff_rows_full` 给 Web UI。
  - 读表用 `pandas.read_excel`（sheet 0 或指定）、`read_csv`；`_trim_grid` 去尾部空行/空列（处理 Excel used range 伪空白）。
  - **没有单元格标红**（输出是变更列表/unified 文本/网页表格），没有 `.xls`、没有公式策略、没有合并单元格、无 OCR。
- 复用结论：**借鉴 `_trim_grid` 归一化与"按行号/主键"两种对齐模式；不直接依赖**。理由：依赖 pandas，且没有标红渲染；MIT 代码可复用但价值有限，自研引擎更可控。

### 1.7 RapidOCR（RapidAI/RapidOCR）

- 证据：HEAD `80b427d69bfc5b91a12913394875910296c6f315`（2026-10-25 20:17:58 +0530）。GitHub API：8,384 stars / 763 forks，`Apache-2.0`，Python，pushed 2026-10-29；最新 Release **v3.10.0** published 2026-10-08。
- PyPI 实证（关键）：
  - 包名 `rapidocr`，**3.10.0**，`License-Expression: Apache-2.0`，`License-File: LICENSE, MODEL_LICENSES.md`；`Requires-Python >=3.8,<4`；wheel 27,288,134 字节（27.3MB）。
  - **模型随 wheel 分发（实证）**：解包 `rapidocr-3.10.0-py3-none-any.whl` 后存在
    `rapidocr/models/PP-OCRv6_det_small.onnx`（9,929,594 字节）、
    `rapidocr/models/PP-OCRv6_rec_small.onnx`（21,234,383 字节）、
    `rapidocr/models/ch_ppocr_mobile_v2.0_cls_mobile.onnx`（585,532 字节）。
    `python/rapidocr/main.py` 中 `root_dir = Path(__file__).resolve().parent`、默认 `model_root_dir = root_dir / "models"`，即从包内目录加载；只有模型缺失时才走 `utils/download_file.py` 从 ModelScope 下载。
  - 依赖（METADATA `Requires-Dist`）：`pyclipper`、`opencv-python-headless>=4.5.1.48`、`numpy<3`、`six`、`Shapely`、`PyYAML`、`Pillow`、`tqdm`、`omegaconf`、`requests`、`colorlog`；**ONNX Runtime 不在强制依赖里**，README 安装命令为 `pip install rapidocr onnxruntime`，onnxruntime 是独立 MIT 包（见 2.3）。
  - `python/MODEL_LICENSES.md` 明确模型版权归 Baidu/PaddleOCR，按 Apache-2.0 分发，并列出上游 HuggingFace/ModelScope 模型卡与 PaddleOCR License 链接 → 作为安装包 NOTICE 的依据。
- 真实离线验证（在 `/tmp/engdiff-research/ocrvenv` 安装 `rapidocr onnxruntime`，用死代理模拟断网）：

```bash
python3 -m venv /tmp/engdiff-research/ocrvenv
./ocrvenv/bin/pip install rapidocr onnxruntime pillow
# 关键环境变量：http_proxy/https_proxy 指向 127.0.0.1:9（无可达服务）
http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 ./ocrvenv/bin/python - <<'PY'
from rapidocr import RapidOCR
engine = RapidOCR()
res = engine('/tmp/engdiff-research/ocr-test2.png')
print(res.txts, [round(s,3) for s in res.scores])
PY
```

  输出：`txts=('Part No. AX-2024-001', 'Quantity: 12 Price: 3.50')`，scores `(0.996, 0.988)`；日志显示 `File exists and is valid: .../site-packages/rapidocr/models/PP-OCRv6_det_small.onnx`，**全程无下载请求**。首次推理冷启动约 15.8–21.4s（模型加载），后续复用 engine 才快。
- PyInstaller 实证（Linux onedir，rc=0）：
  `pyinstaller --noconfirm --onedir --collect-data rapidocr app.py` →
  `dist/ocrtest/_internal/rapidocr/models/{PP-OCRv6_det_small,PP-OCRv6_rec_small,ch_ppocr_mobile_v2.0_cls_mobile}.onnx` 均被收录；`dist` 310MB；断网运行输出 `PACKAGED_OK ('Part No. AX-2024-001', 'Quantity: 12 Price: 3.50') [0.996, 0.988]`。结论：**运行期模型路径 = 打包资源目录，`--collect-data rapidocr` 必需**；`pyinstaller_hooks_contrib` 只有 `hook-onnxruntime.py`，没有 rapidocr hook。
- 项目当前实际使用的旧包 `rapidocr-onnxruntime` 1.4.4（见 §3.1 环境实证）：PyPI 最新仍为 1.4.4，上传 2025-01-17，`License: Apache-2.0`，依赖 `onnxruntime>=1.7.0`、`opencv-python`（**非 headless**）、pyclipper/numpy/Shapely/PyYAML/Pillow/tqdm；模型同样随包（`rapidocr_onnxruntime/models/ch_PP-OCRv4_det_infer.onnx` 4.7MB、`ch_PP-OCRv4_rec_infer.onnx` 10.9MB、`ch_ppocr_mobile_v2.0_cls_infer.onnx` 0.59MB）。其 dist-info 只有 METADATA/RECORD/WHEEL/entry_points/top_level，**没有模型授权文件**（需自行补 PaddleOCR 模型署名）。
- PyInstaller 实证（旧包 1.4.4，Linux onedir，rc=0）：`--collect-data rapidocr_onnxruntime` 后 `_internal/rapidocr_onnxruntime/models/*.onnx` 全部收录，dist 319MB；断网运行 `PACKAGED_PINNED_OK ['Part No.AX-2024-001', 'Quantity: 12', 'Price: 3.50'] [0.984,0.997,0.964]`，耗时 4.6s（比 v3.10 快）。
- 复用结论：**直接依赖（Apache-2.0，可闭源分发）**。推荐同时固定模型版本并在安装包内附带 `rapidocr/LICENSE` + `MODEL_LICENSES.md`（或等价 NOTICE）。

### 1.8 PaddleOCR（PaddlePaddle/PaddleOCR）

- 证据：HEAD `dab3fe35379033fdcb2d0e9572fac0b36c9a9ebf`（2026-09-16 11:30:53 +0800）。GitHub API：91,959 stars / 11,587 forks，`Apache-2.0`，pushed 2026-09-16；最新 Release **v3.7.0**（2026-06-11）。
- 依赖实证（PyPI）：
  - `paddleocr` 3.7.0 wheel 仅 **0.1MB**（纯 Python 包装），依赖 `paddlex[ocr-core]>=3.7.0,<3.8.0`、PyYAML、requests、aiohttp、typing-extensions。
  - `paddlex` 3.7.2 wheel 2.2MB，依赖包含 `huggingface-hub`、`modelscope`、numpy 等 → **模型在运行时从 HF/ModelScope 下载**。
  - `paddlepaddle` 3.3.1 Windows CPU wheel **104.8MB**（Linux 194.8MB）；整个 paddle 运行时+模型会显著增大安装包。
- 能力：PP-OCRv6 模型体系、多语言、版面/文档解析；Windows 可运行但依赖重、首次运行要联网拉模型，嵌入桌面离线安装包需要自行预置模型并改 paddlex 缓存路径，工程复杂度高。
- 复用结论：**不采用其运行时；仅间接复用其模型体系**。RapidOCR 的模型即脱胎于 PaddleOCR PP-OCR，`MODEL_LICENSES.md` 已做上游署名；本项目通过 RapidOCR 获得 PaddleOCR 模型能力，而不引入 paddlepaddle。

## 2. 主动补充调查

### 2.1 PySide6（LGPL）

- 项目已安装 **PySide6 6.8.1**（`.venv/.../PySide6-6.8.1.dist-info`，METADATA `License: LGPL`），PyPI 最新 6.12.0。
- PyPI 元数据（PySide6 / PySide6-Essentials / PySide6-Addons / shiboken6 6.12.0）均声明：
  `license = "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"`。
- Qt 官方 [Obligations of the GPL and LGPL](https://www.qt.io/licensing/open-source-lgpl-obligations) 原文关键点：
  - "The primary open-source license is the GNU Lesser General Public License v. 3 (LGPL). With the LGPL license option ... This allows for keeping your application source code closed as long as all the requirements of LGPLv3 are met."
  - 使用 LGPL 时要求随应用提供所用库的完整对应源码（或书面提供获取方式），即使是未修改的库；动态链接下应用可保持专有（"work that uses the library"）。
- 安装体量旁证：本机 Linux 环境 `site-packages/PySide6` 643MB（含 Qt 库/插件，Windows 版不同但同量级）；打包时需裁剪未用模块。
- 复用结论：**直接依赖，按 LGPL-3.0 动态链接合规**（见选型报告合规措施）。避免 onefile，推荐 onedir 以保持 Qt DLL 可替换。

### 2.2 difflib / Google diff-match-patch

- `difflib` 为 Python 标准库（PSF-2.0），无额外分发义务；`SequenceMatcher` 足以做单元格内字符级 diff。
- `diff-match-patch`：PyPI 版本 **20241021**，Apache-2.0（classifier `License :: OSI Approved :: Apache Software License`），上传 2024-10-21；上游 `github.com/google/diff-match-patch` 已 **archived**（pushed 2024-05-22，Apache-2.0），PyPI 包由 `diff-match-patch-python` 组织继续维护。
- 结论：**可用但非必需**。本项目优先 `difflib`（零依赖）；diff-match-patch 仅在需要语义清理/长文本性能时作为 Apache-2.0 可选依赖，随包附许可。

### 2.3 ONNX Runtime / OpenCV / openpyxl / xlrd / NPOI / Tesseract / 打包工具

| 组件 | 实际版本 | 许可证证据 | 结论/备注 |
|---|---|---|---|
| ONNX Runtime | 项目装 1.20.1；PyPI 最新 1.31.1 | METADATA `License: MIT License`；wheel 内 `onnxruntime/LICENSE` 为 MIT 全文（Microsoft） | Windows x64 CPU wheel 14.9MB，`onnxruntime/capi/onnxruntime.dll`；`_pyinstaller_hooks_contrib/stdhooks/hook-onnxruntime.py` 已存在 |
| openpyxl | 3.1.5 | METADATA `License: MIT`，`LICENCE.rst` | 读 XLSX 值/公式/缓存值（两次加载）、合并、宽高、基本样式 |
| xlrd | 2.0.2 | METADATA `License: BSD`，`LICENSE` | 只支持 `.xls`（2.x 起移除 xlsx）；**读不到公式表达式**，只有缓存值/类型 → XLS 公式差异需降级+警告 |
| NPOI | 未安装（.NET） | Apache-2.0 | **不适用**：.NET 库，无法在 Python/PySide6 进程内复用；除非整体换 C# 技术栈 |
| Tesseract | 未安装 | Apache-2.0（tesseract），pytesseract 0.3.13 Apache-2.0 | 需额外分发 `tesseract.exe` + `tessdata` 语言包（体积/路径/语言包管理复杂），中文截图精度与速度不如 RapidOCR；**不采用** |
| OpenCV | 项目装 headless 4.10.0.84；另有 opencv-python 5.0.0.93（见 §3.1） | METADATA `License: Apache 2.0`；wheel 内 `cv2/LICENSE.txt`、`cv2/LICENSE-3RD-PARTY.txt` | Apache-2.0 可闭源分发；**注意 wheel 内 `LICENSE-3RD-PARTY.txt` 写明 "FFmpeg is redistributed within all opencv-python packages."**（FFmpeg LGPL-2.1），安装包需附该第三方许可与源码获取说明 |
| PyInstaller | 6.22.3 | METADATA：`GPLv2-or-later with a special exception which allows to use PyInstaller to build and distribute non-free programs (including commercial ones)` | 该 exception 使 MIT 闭源分发合法；需随包附 PyInstaller 许可 |
| Inno Setup | 计划使用 | 官方 [license.txt](https://jrsoftware.org/files/is/license.txt)："Permission is granted to anyone to use this software for any purpose, including commercial applications, and to alter and redistribute it"（需保留版权/出处，致谢非强制） | 可免费分发商业安装包；随包附其许可 |
| Noto Sans SC | 项目 `tests/assets/NotoSansSC-Regular.otf` | 字体 name 表：nameID 13 为 "SIL Open Font License, Version 1.1"，nameID 0 版权 "© 2014-2021 Adobe"，nameID 1 "Noto Sans CJK SC" | 若安装包分发该字体，需附 OFL-1.1 全文；测试用字体 |

## 3. 关键环境实证（项目 .venv，只读检查）

### 3.1 旧 OCR 包与 OpenCV 双包冲突

项目 `pyproject.toml` 固定 `rapidocr-onnxruntime==1.4.4` + `onnxruntime==1.20.1` + `opencv-python-headless==4.10.0.84`。实际 `.venv/lib/python3.11/site-packages` 中同时存在：

- `rapidocr_onnxruntime` 1.4.4，且 `rapidocr_onnxruntime/models/` 内有三个 ONNX 模型（见 §1.7）→ 旧包同样"模型随包"。
- `opencv_python_headless-4.10.0.84.dist-info` **和** `opencv_python-5.0.0.93.dist-info` 同时存在（后者是 `rapidocr-onnxruntime==1.4.4` 的 `Requires-Dist: opencv-python` 传递依赖）。
- 实测 `python -c "import cv2; print(cv2.__version__, cv2.__file__)"` → `cv2 5.0.0 .../site-packages/cv2/__init__.py`，即 **cv2 实际解析到 5.0.0，与 pyproject 期望的 4.10.0.84 不一致**。两个发行包共享 `cv2/` 命名空间，安装器"后装者覆盖"，存在 ABI/行为不可预测风险。
- 结论：打包前必须消歧——要么统一用 `opencv-python`（接受其 GUI/FFmpeg 体积），要么迁移到 `rapidocr>=3.10`（其依赖是 `opencv-python-headless`，与项目目标一致）。这是选型报告中的**待修正项**。

### 3.2 离线 OCR（项目固定栈，断网代理）

`http_proxy/https_proxy=http://127.0.0.1:9` 下运行项目的 `rapidocr_onnxruntime` 1.4.4：

```
import 0.9s / init 0.9s / ocr 6.6s wall
txts: ['Part No.AX-2024-001', 'Quantity: 12', 'Price: 3.50']
scores: [0.984, 0.997, 0.964]
```

确认：固定栈**无需联网即可识别**（模型来自 venv 包内），英文合成图可识别；但 "Part No." 后空格丢失、单行文本被拆成多框（属 OCR 后处理/匹配模块需要处理的真实问题，不能假设 OCR 输出与原文逐字一致）。

### 3.3 PyInstaller 可行性与体积

- 两个 OCR 包分别用 `--onedir --collect-data <pkg>` 打包**均成功**，模型进入 `_internal/<pkg>/models/`，断网运行成功（见 §1.7）。
- 纯 OCR 测试程序 dist 体积：`rapidocr` 3.10 → **310MB**；`rapidocr-onnxruntime` 1.4.4 → **319MB**（未含 PySide6）。加入 Qt 后安装包会更大，必须裁剪 `PySide6-Addons` 未用模块、剔除无用 Qt 插件/翻译，并在 Inno Setup 用 LZMA 压缩；`onefile` 不解压可运行但体积/启动/杀软误报更差，且不利于 LGPL"可替换 Qt 库"，**建议 onedir**。
- 冷启动：v3.10 首次推理 15.8–21.4s、v1.4.4 4.6–6.6s（本机 Linux 虚拟机）。必须在后台线程预热，不能阻塞首屏。

## 4. 能力对比矩阵

图例：✔ 支持；◐ 部分/有前提；✖ 不支持或不可用。

| 项目 | Windows | 完全离线 | 双栏差异 | 字符级标红 | Excel 多 Sheet | 单元格标红 | 图片 OCR | OCR 可嵌入桌面 | 二次开发适配 | 许可证/闭源分发 |
|---|---|---|---|---|---|---|---|---|---|---|
| WinMerge 2.16.60 | ✔（仅 Windows） | ✔ | ✔ | ✔（word/inline diff） | ✖（仅 CSV/TSV 表格） | ✖ | ✔（Windows.Media.Ocr） | ◐（仅 Windows 系统 OCR） | ✖（C++/MFC，无比较内核库） | GPL-2.0 ✖ 不可链接/复制 |
| open-diff 1.3.2 | ✔（Tauri） | ✔ | ✔ | ◐（文本 inline；表格到单元格） | ✔（calamine，文档自评 PARTIAL） | ✔ | ✖ | ✖ | ◐（Apache-2.0 可复用，Rust/Vue 移植成本高） | Apache-2.0 ✔（需 NOTICE/变更声明） |
| hotdiff 0.3.0 | ✔（Wails） | ✔ | ✔ | ◐（Monaco 前端行内） | ✖ | ✖ | ✖ | ✖ | ✖（Go/Wails） | MIT ✔ |
| xlsx-compare 0.2.2 | ✔（Python） | ✔ | ✖（CLI 报告） | ✖ | ✔ | ✖（纯文本 old->new） | ✖ | ✖ | ◐（MIT；pandas/mininterface 依赖） | MIT ✔ |
| xlsxDiff（2023） | ✔（Python） | ✔ | ✖（生成报告 xlsx） | ✔（difflib） | ✔ | ✔（输出 xlsx 高亮） | ✖ | ✖ | ✖（AGPL 传染） | AGPL-3.0 ✖ 不可复制 |
| sheet-diff 0.2.0 | ✔（Python） | ✔（核心） | ✖（CLI/网页） | ✖ | ✔ | ✖ | ✖ | ✖ | ◐（MIT；pandas，无标红） | MIT ✔ |
| RapidOCR 3.10.0 | ✔（纯 Python+ORT） | ✔（模型随 wheel，实测断网） | — | — | — | — | ✔ | ✔ | ✔（直接依赖） | Apache-2.0 ✔（含模型 NOTICE） |
| PaddleOCR 3.7.0 | ✔ 但重（paddlepaddle 104.8MB） | ◐（需预下载模型） | — | — | — | — | ✔ | ✖/困难 | ✖（运行时重，paddlex 拉模型） | Apache-2.0 ✔（但不采用运行时） |

## 5. 复用决策与理由

| 项目 | 决策 | 理由（证据） |
|---|---|---|
| WinMerge | **仅参考交互/差异导航；不链接、不复制** | GPL-2.0 原文禁止并入专有程序；C++/MFC/Windows-only；无 Excel；`WinIMergeLib` 仅图片窗口且 GPLv2+ |
| open-diff | **借鉴表格差异建模/行对齐思路；不直接依赖** | Apache-2.0 可复用但 Rust/Tauri 与 PySide6 不匹配；无 OCR；表格字符级不足 |
| hotdiff | **仅参考 UI；不采用** | MIT 但 Go/Wails + Monaco；无 Excel/OCR；维护停滞 |
| xlsx-compare | **借鉴公式/缓存值与 Sheet 配对规则；可少量复用 MIT 代码但需署名；不直接依赖** | 报告型工具，无标红；pandas+mininterface 依赖与桌面栈不匹配 |
| xlsxDiff | **仅参考行/列主键对齐与片段级呈现；不复制代码** | AGPL-3.0 传染，无法进入 MIT 安装包；2023 后停更 |
| sheet-diff | **借鉴 `_trim_grid`/行对齐归一化；不直接依赖** | MIT 但 pandas 依赖、无标红、0.x 早期项目 |
| RapidOCR | **直接依赖（首选，随安装包分发）** | Apache-2.0；模型随 wheel；离线与 PyInstaller 双实证 |
| PaddleOCR | **仅复用模型体系（经 RapidOCR），不引入 paddlepaddle** | Apache-2.0 但 paddlepaddle 104.8MB + paddlex 运行时模型下载，嵌入离线安装包成本高 |
| ONNX Runtime | **直接依赖** | MIT；Windows x64 CPU wheel 可用；PyInstaller 有官方 hook |
| PySide6 | **直接依赖，LGPL 动态链接合规** | Qt 官方 LGPL 义务说明；onedir 保持 Qt 库可替换 |
| difflib / diff-match-patch | difflib 首选；diff-match-patch 可选 | PSF-2.0 / Apache-2.0；长文本语义清理时再引入 |
| Tesseract / NPOI | **不采用** | Tesseract 需外部二进制+语言包、中文精度弱；NPOI 是 .NET 库 |

## 6. 尚未/无法确认的事项

1. WinMerge、open-diff、hotdiff 未实际构建运行；对 UI 交互的借鉴以 README/源码/截图为准。
2. RapidOCR 只在合成英文图上验证；**中文工程截图的小字体、反色、低对比、倾斜**需要 ocr-dev 用真实样本调参与评估（可换更大模型/放大预处理）。
3. RapidOCR 3.10 与 1.4.4 的 API 不同：3.10 返回 `RapidOCROutput`（`.txts/.boxes/.scores`），1.4.4 返回 `(result_list, elapse)`；若迁移需改 `ocr/engine.py`，属 Lead/契约变更。
4. Windows 下 PyInstaller 产物、Inno Setup 安装包、Qt 插件裁剪、杀软误报均未在本机验证（本机为 Linux fnOS）。
5. `.xls` 公式表达式不可得（xlrd 2.0.2 限制）；只能比较缓存值并提示，需在 UI 明确 warning。
6. 字体/模型/FFmpeg 的 NOTICE 清单需要在打包流水线中自动生成并实测安装包内文件齐全。
