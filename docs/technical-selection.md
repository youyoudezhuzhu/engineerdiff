# EngineerDiff 技术选型报告

> 决策日期：2026-10-30　调查人：research-scout　详细证据：[research-notes.md](research-notes.md)
> 结论：保持 **Python 3.11 + PySide6 + 自研统一 DiffModel/渲染** 主线；OCR 采用 **RapidOCR + ONNX Runtime（模型随包、完全离线，已实测）**；Excel 用 **openpyxl（XLSX）/ xlrd（XLS）**；OpenCV 只做图片对齐/匹配辅助；**PyInstaller（onedir）+ Inno Setup** 打包。不 fork WinMerge/hotdiff/open-diff 作为主体。

## 1. 最终技术栈

| 层 | 选型（版本建议） | 许可证 | 决策依据 |
|---|---|---|---|
| 语言/运行时 | Python 3.11 | PSF-2.0 | 项目既定；RapidOCR/openpyxl/xlrd 均兼容 |
| 桌面 UI | **PySide6 == 6.8.1**（当前已装；最新 6.12.0 可评估升级） | LGPL-3.0-only（或 GPL） | 官方 Qt LGPL 说明允许闭源应用动态链接；6.8.1 与现有 venv/契约一致，先锁定版本 |
| 文本差异 | `difflib.SequenceMatcher` 自研行/字符级；长文本可选 `diff-match-patch`（20241021） | PSF-2.0 / Apache-2.0 | 零依赖、可精确控制"字符级标红"；diff-match-patch 仅在需要语义清理/性能时加入 |
| Excel 读取 | `openpyxl >=3.1.5,<3.2`（XLSX）、`xlrd >=2.0.1,<3`（XLS） | MIT / BSD-3-Clause | XLSX 需公式+缓存值两遍读取、合并/宽高/样式；XLS 仅 xlrd 支持（无公式表达式） |
| OCR | **保留 `rapidocr-onnxruntime == 1.4.4`（v1.0）**，升级路径 `rapidocr == 3.10.0` | Apache-2.0 | 1.4.4 与现有契约/venv 一致、模型随包、打包与断网均实证通过；3.10.0 为当前维护版、模型更新（PP-OCRv6 small）且依赖 headless OpenCV，列为 v1.1 升级项（见 §5） |
| 推理运行时 | `onnxruntime == 1.20.1`（CPU），后续可升 1.31.x | MIT | Windows x64 CPU wheel 可用；PyInstaller 有官方 hook；无需 CUDA |
| 图像处理 | **单一 OpenCV 提供者**：保留 1.4.4 时用 `opencv-python==4.10.0.84`，删除 headless 双装；升级 3.10 后改回 `opencv-python-headless` | Apache-2.0（wheel 内含 FFmpeg LGPL-2.1） | 仅做缩放/灰度/ORB/单应变换；**必须消除当前 venv 中 opencv-python 与 opencv-python-headless 双包冲突**（见 §5） |
| 其他 | Pillow、numpy（<2.3）、charset-normalizer | HPND/BSD/ MIT | 已在项目依赖中 |
| 差异模型/渲染 | **自研**：统一 `DiffModel`（文本/表格/图片共用 DiffItem/DiffLocation）+ 自绘虚拟化 GridView/ImageView | 本项目 MIT | 现有开源方案没有一个同时满足"严格坐标单元格比较+字符级 span+合并单元格+公式策略+OCR 文本回贴原图"；open-diff/xlsxDiff 最接近但架构/许可证不匹配（§3） |
| 打包 | **PyInstaller == 6.22.x，onedir**（非 onefile） | GPLv2+ with exception | exception 允许构建/分发非自由程序；onedir 便于 LGPL Qt 库可替换、模型路径稳定 |
| 安装包 | **Inno Setup 6**（LZMA） | Inno Setup 自定义许可 | 允许商业分发；随包附许可即可；适合 Windows 单文件安装器 |
| 字体 | 安装包如需内置中文 UI 字体，使用 **Noto Sans SC（OFL-1.1）** | SIL OFL-1.1 | 字体 name 表已确认 OFL-1.1；随包附 OFL 全文 |

**与任务给定的栈一致，未发现更优替代**：RapidOCR+ORT 是唯一"模型随 wheel、完全离线、纯 Python、可嵌入 PySide6、Apache-2.0"的组合；PaddleOCR 运行时过重（paddlepaddle Windows wheel 104.8MB 且模型由 paddlex 运行时下载），Tesseract 需外部分发二进制与语言包且中文截图精度/速度不占优。唯一值得变更的是 **OCR 包版本与 OpenCV 包消歧**（§5）。

## 2. 复用方案表

| 组件 | 许可证 | 复用方式 | 是否随安装包分发 | 说明 |
|---|---|---|---|---|
| PySide6 / Qt | LGPL-3.0-only | 直接依赖（动态链接） | 是（Qt DLL/插件） | 附 LGPL 全文 + Qt 源码获取说明；onedir 保持 DLL 可替换；不修改 Qt 源码 |
| RapidOCR（rapidocr-onnxruntime 1.4.4 或 rapidocr 3.10.0） | Apache-2.0 | 直接依赖（Python 包） | 是（代码+模型） | 附 `LICENSE`；**额外附模型授权/署名**（`MODEL_LICENSES.md`；旧包无该文件，需自建 NOTICE，注明 PaddleOCR/Baidu 模型 Apache-2.0） |
| ONNX Runtime | MIT | 直接依赖（DLL） | 是 | 附 `onnxruntime/LICENSE` |
| openpyxl | MIT | 直接依赖 | 是 | 附许可 |
| xlrd | BSD-3-Clause | 直接依赖 | 是 | 附许可；只读 .xls，公式不可得需 UI 提示 |
| OpenCV | Apache-2.0（wheel 另含 FFmpeg LGPL-2.1 等第三方） | 直接依赖 | 是 | 附 `cv2/LICENSE.txt` + `cv2/LICENSE-3RD-PARTY.txt`；按其中 FFmpeg 条款提供 LGPL 文本与源码获取方式 |
| Pillow / numpy / charset-normalizer | HPND/BSD/MIT | 直接依赖 | 是 | 附许可 |
| difflib | PSF-2.0（标准库） | 直接使用 | 是（随 Python） | 附 Python 许可 |
| diff-match-patch（可选） | Apache-2.0 | 可选依赖 | 若引入则分发 | 上游 google 仓库已归档，PyPI 端口仍维护；附许可 |
| Inno Setup | 自定义许可（允许商业分发） | 构建工具 | 安装器本身由它生成 | 安装包内附 Inno Setup 许可 |
| PyInstaller | GPLv2+ with exception | 构建工具 | 产物含 bootloader | 附 PyInstaller 许可 |
| Noto Sans SC（若随包） | SIL OFL-1.1 | 资源 | 是 | 附 OFL 全文，不单独售卖字体 |
| **WinMerge** | GPL-2.0 | **仅参考交互/口径，不链接、不复制代码** | 否 | GPL 禁止并入专有程序；C++/MFC/Windows-only；无 Excel |
| **open-diff** | Apache-2.0 | **借鉴表格行对齐/单元格差异建模，不直接依赖** | 否 | Rust/Tauri/Vue 架构不匹配；如复用其代码片段必须在 NOTICE 标注来源与变更 |
| **hotdiff** | MIT | **仅参考 UI，不采用** | 否 | Go/Wails/Monaco；无 Excel/OCR；项目停滞 |
| **xlsx-compare** | MIT | **借鉴公式/缓存值策略与 Sheet 配对；不直接依赖** | 否 | 报告型 CLI，无标红；pandas+mininterface 不引入 |
| **xlsxDiff** | AGPL-3.0 | **仅参考算法/呈现，不复制代码** | 否 | AGPL 传染；2023 年后停更 |
| **sheet-diff** | MIT | **借鉴 `_trim_grid` 归一化/行对齐；不直接依赖** | 否 | 早期 0.x，pandas 依赖，无标红 |
| **PaddleOCR** | Apache-2.0 | **只复用其模型体系（经 RapidOCR 分发），不引入 paddlepaddle** | 模型随 RapidOCR 分发 | 在 NOTICE 注明模型来源与 Apache-2.0 |
| Tesseract / NPOI | Apache-2.0 | **不采用** | 否 | Tesseract 需外部分发二进制+语言包；NPOI 为 .NET |

**为什么不 fork WinMerge / hotdiff / open-diff 作为主体（依据）**：
- WinMerge：GPL-2.0（`LICENSE.md`/`Src/COPYING` 原文；GPL 正文明确禁止并入专有程序），C++/MFC/Windows-only，比较内核没有可链接库（`WinIMergeLib` 仅图片窗口且 GPLv2+），无 Excel 支持。fork 后必须整体 GPL 开源，且无法满足"Python + MIT 安装包"约束。
- hotdiff：MIT 但 Go 1.23 + Wails + React/Monaco，无 Excel/OCR，只有 ~56 个提交且 2026-06 后无更新；复用等于换技术栈重写。
- open-diff：Apache-2.0 较友好，但 Rust（31 个成员 crate + 根应用）+ Tauri 2 + Vue；无 OCR；Table Compare 自评 PARTIAL。可作为算法/交互参考，不是 Python 组件。

## 3. 许可证风险与合规措施

1. **WinMerge（GPL-2.0）**：不链接、不复制、不随包分发；只在文档中描述"双栏+差异导航"交互。禁止把 `stringdiffs.cpp` 等实现翻译后放入 MIT 代码库（会构成衍生作品）。
2. **PaddleOCR（Apache-2.0）**：不引入 paddlepaddle 运行时；仅通过 RapidOCR 使用 PP-OCR 模型，NOTICE 中声明模型版权归 Baidu/PaddleOCR、许可证 Apache-2.0，并附 `MODEL_LICENSES.md` 或等价说明与上游链接。
3. **RapidOCR（Apache-2.0）**：随包附 `LICENSE` 与模型授权；旧包 `rapidocr-onnxruntime==1.4.4` 的 dist-info 无模型许可文件 → 打包脚本必须自建 `THIRD-PARTY-NOTICES`（附 PaddleOCR License 链接、模型版本/哈希）。
4. **PySide6（LGPL-3.0）**：动态链接 Qt；使用 onedir，保留 Qt6*.dll/plugins 为独立文件，允许用户替换；随包附 LGPL-3.0 全文、Qt 版本与源码获取方式（Qt 官方 LGPL 说明要求提供库的完整对应源码或书面提供获取方式）；不修改 Qt 源码；不使用 GPL-only 模块（如 Qt Charts 视许可证而定，避免引入）。
5. **openpyxl（MIT）/ xlrd（BSD-3）/ ONNX Runtime（MIT）/ Pillow / numpy**：在 `THIRD-PARTY-NOTICES` 中逐项附版权与许可全文。
6. **OpenCV（Apache-2.0）**：附 `cv2/LICENSE.txt`、`cv2/LICENSE-3RD-PARTY.txt`；其中 FFmpeg 以 LGPL-2.1 随 wheel 分发，需附 LGPL 文本与源码获取说明（打包时保留 wheel 内原始 license 文件）。
7. **字体/模型**：Noto Sans SC 若随包 → 附 SIL OFL-1.1；OCR 模型 → 附模型 NOTICE（Apache-2.0 + 上游 PaddleOCR 署名）；第三方图标/翻译若引入需单独核对。
8. **构建工具**：PyInstaller（GPLv2+exception）与 Inno Setup（自定义许可）在安装包"关于/许可"页附许可文本；Inno Setup 许可允许商业分发，但需保留其版权声明与出处。
9. **主许可证**：项目保持 MIT；安装包根目录提供 `LICENSE`、`THIRD-PARTY-NOTICES.md`、`licenses/` 目录；CI 增加"NOTICE/许可文件完整性"检查。

## 4. 未覆盖功能与风险

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| **XLS 公式表达式不可得** | xlrd 2.0.2 只能读缓存值，XLS 无法按公式文本比较 | 明确 UI 提示"该 XLS 只能比较值"；公式模式对 XLS 降级为值比较并标 warning；文档列为已知限制 |
| **OCR 小字体/低对比/反色/倾斜** | 工程截图小字漏识别或错字，导致误报差异 | 预处理（放大、灰度、二值化、对比度）；置信度阈值 + 橙色"待复核"；提供 OCR 文本人工校正对话框；用真实样本集评估，必要时换更大模型（PP-OCRv6 更大变体） |
| **不同截图的分辨率/窗口位置/缩放** | 文字框无法一一对应，误判新增/删除 | OpenCV ORB/单应变换估计缩放+平移；文本相似度（含 0/O、1/I/l 混淆归一）+ 坐标几何 + 邻域上下文做一对一分配；无法可靠配对标橙并允许手动配对 |
| **PyInstaller 模型路径** | 打包后模型找不到，运行期触发联网下载或失败 | onedir；`--collect-data rapidocr(_onnxruntime)`；启动时校验模型文件存在并给出中文错误；禁止联网回退；Windows CI 做冒烟测试（本机仅验证 Linux onedir） |
| **OCR 冷启动 15–21s（v3.10）/ 4.6–6.6s（v1.4.4）** | 首次图片比较卡顿 | 后台线程预热 OCR 单例；进度条/取消；首屏不阻塞 |
| **OpenCV 双包冲突（当前实际环境）** | `cv2` 实际为 5.0.0，与 pyproject 的 4.10.0.84 不一致，ABI/行为不可预测 | 立即修正 pyproject（见 §5），打包前 `pip check` + 断言 `cv2.__version__`；CI 校验只有一个 opencv 发行包 |
| **安装包体积** | 纯 OCR 测试 onedir 已 310–319MB（未含 Qt），完整包更大 | 只装 PySide6-Essentials（避免 Addons）；排除 QtWebEngine/3D/翻译/无用插件；Inno Setup LZMA；目标安装包 <250MB 并实测 |
| **PyInstaller + LGPL** | onefile 会隐藏 Qt DLL，不利于"可替换库"合规 | 选择 onedir；文档说明如何替换 Qt DLL |
| **Excel 渲染保真度** | 自绘 GridView 无法 100% 还原 Excel（主题、条件格式、公式栏） | 契约已限定"基本样式还原、不比较样式"；明确已知限制，重要视图提供单元格详情 |
| **大文件/大表性能** | 十万行表格、超大截图 OCR | GridView 虚拟化；OCR 分块/缩放；后台线程 + 取消；性能预算测试 |
| **安全/杀软误报** | PyInstaller bootloader 常见误报 | 代码签名（如有证书）、提交误报、提供 onedir 版本 |

## 5. 对当前项目依赖/打包的两条明确修正建议

1. **OCR 版本**：v1.0 保留 `rapidocr-onnxruntime==1.4.4`（与 `docs/ui-contracts.md` 的 `rapidocr_onnxruntime.RapidOCR` 契约一致，已装、模型随包、打包/断网实证通过，且推理更快）。同时登记升级项：`rapidocr==3.10.0`（当前维护版，模型更新为 PP-OCRv6 small，依赖 `opencv-python-headless`），升级需改 `ocr/engine.py` 的 API 适配并在 v1.1 回归。若 Lead 决定立刻升级，则同步修改契约文档，避免 ocr-dev 返工。
2. **OpenCV 消歧**：当前 `.venv` 同时存在 `opencv-python-headless 4.10.0.84` 与 `opencv-python 5.0.0.93`（后者由 `rapidocr-onnxruntime` 传递引入），实测 `cv2.__version__ == 5.0.0`。保留 1.4.4 时，将 pyproject 的 `opencv-python-headless==4.10.0.84` 改为 `opencv-python==4.10.0.84` 并卸载另一个包；或迁移到 `rapidocr 3.10` 后继续用 headless。打包流水线需断言只有一个 OpenCV 发行包。

## 6. 依据证据备注

- commit/发布/许可证原文：见 [research-notes.md §1](research-notes.md)，含各仓库 HEAD hash（WinMerge `c94ac0e8`、open-diff `f42cd1ae`、hotdiff `8ab4d5ea`、xlsx-compare `3a21ddb9`、xlsxDiff `8927e8c4`、RapidOCR `80b427d6`、PaddleOCR `dab3fe35`）与 Release 日期。
- RapidOCR 模型随 wheel 分发、断网 OCR、PyInstaller 打包实证：见 [research-notes.md §1.7、§3.2、§3.3](research-notes.md)。
- Python 依赖许可证与 PyInstaller/Inno Setup 条款：见 [research-notes.md §2.3](research-notes.md)。
- 能力矩阵与复用决策：见 [research-notes.md §4、§5](research-notes.md)。
- 外部一手来源：[Qt LGPL 义务](https://www.qt.io/licensing/open-source-lgpl-obligations)、[Inno Setup License](https://jrsoftware.org/files/is/license.txt)、[PyPI sheet-diff](https://pypi.org/project/sheet-diff/)、[RapidOCR Releases](https://github.com/RapidAI/RapidOCR/releases)、[WinMerge Releases](https://github.com/WinMerge/winmerge/releases)、[open-diff Releases](https://github.com/kygo8/open-diff/releases)、[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)。
- 注意：WinMerge/open-diff/hotdiff 未构建运行；RapidOCR 仅在合成英文图验证，中文工程截图效果需 ocr-dev 用真实样本回归；Windows 打包链路需在 Windows CI 上复验。
