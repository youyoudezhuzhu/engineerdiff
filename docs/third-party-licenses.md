# 第三方软件与许可证说明

EngineerDiff 本体以 **MIT License** 发布，版权归 EngineerDiff contributors
（见仓库根目录 `LICENSE`）。本文档整理随安装包/便携版分发的第三方软件、
许可证、分发方式与合规措施。

> 构建时 `scripts/collect_licenses.py` 会根据**实际安装的 Python 发行包**再次生成
> 随包的 `THIRD-PARTY-NOTICES.md`、`MODEL_LICENSES.md`、`LICENSES/MANIFEST.json`
> 与 `LICENSES/<package>/` 原文目录；如本文档与随包生成结果有版本细节差异，
> 以构建产物中的生成结果为准（生成结果包含实际版本与文件清单）。

---

## 1. 随包运行时组件

| 组件 | 版本基线 | 许可证（SPDX） | 随包形式 | 说明 |
|---|---|---|---|---|
| PySide6 / PySide6-Essentials / shiboken6 | 6.8.1 | LGPL-3.0-only | Qt 6.8.1 DLL + PySide6 扩展模块 + Qt 插件 | 动态链接；LGPL 合规见第 2 节 |
| rapidocr-onnxruntime | 1.4.4 | Apache-2.0 | Python 代码 + 3 个 ONNX 模型 | 模型来源/许可见第 3 节 |
| onnxruntime | 1.20.1 | MIT | `onnxruntime.dll` 等 | CPU 推理，无 GPU/CUDA 组件 |
| opencv-python | 4.10.0.84 | Apache-2.0（wheel 内含 FFmpeg LGPL-2.1 等第三方） | `cv2*.pyd`、OpenCV DLL（Windows wheel 另含 `opencv_videoio_ffmpeg*.dll`） | 仅用于缩放/灰度/ORB/几何变换；FFmpeg 合规见第 5 节 |
| Pillow | 11.1.0 | HPND | `PIL` 扩展模块 | 图像读取/测试素材生成 |
| numpy | 2.x（`>=1.26,<2.3`） | BSD-3-Clause | `numpy` 扩展模块 | OCR/OpenCV 依赖 |
| openpyxl | 3.1.5 | MIT | 纯 Python | 读取 XLSX（公式 + 缓存值） |
| et-xmlfile | 随 openpyxl 解析 | MIT | 纯 Python | openpyxl 依赖 |
| xlrd | 2.0.2 | BSD-3-Clause | 纯 Python | 读取 XLS（值/合并/列宽行高） |
| charset-normalizer | 3.x（`>=3.3,<4`） | MIT | 纯 Python | 文本编码兜底识别 |
| pyclipper | 随 RapidOCR 解析 | MIT | 扩展模块 | RapidOCR 文字框后处理 |
| shapely | 随 RapidOCR 解析 | BSD-3-Clause（wheel 内含 GEOS，LGPL-2.1） | 扩展模块 + GEOS 动态库（若被收集） | GEOS 合规见第 6 节 |
| PyYAML | 随 RapidOCR 解析 | MIT | 纯 Python | RapidOCR 配置读取 |
| six | 随 RapidOCR 解析 | MIT | 纯 Python | RapidOCR 依赖 |
| tqdm | 随 RapidOCR 解析 | MPL-2.0 AND MIT | 纯 Python | RapidOCR 进度显示 |
| protobuf | 随 onnxruntime 解析 | BSD-3-Clause | 纯 Python + 扩展 | ONNX Runtime 依赖 |
| flatbuffers | 随 onnxruntime 解析 | Apache-2.0 | 纯 Python | ONNX Runtime 依赖 |
| sympy / mpmath | 随 onnxruntime 解析 | BSD-3-Clause | 纯 Python | ONNX Runtime 符号推导依赖（若被收集） |
| coloredlogs / humanfriendly | 随 onnxruntime 解析 | MIT | 纯 Python | ONNX Runtime 日志依赖 |
| packaging | 随 onnxruntime 解析 | Apache-2.0 OR BSD-2-Clause | 纯 Python | 版本比较 |

> 上表版本为 `requirements.txt` 锁定/实测基线；传递依赖（"随 xx 解析"）以 CI 实际
> `pip` 解析结果为准，最终版本与许可证文件见随包 `LICENSES/MANIFEST.json`。
> PySide6-Addons 中未被应用使用的模块（WebEngine、Charts、Quick 等）会被 PyInstaller
> 排除，不随包；其许可证文件仍会被收集以备审计。

## 2. PySide6 / Qt（LGPL-3.0-only）合规说明

本软件选择以 **LGPL-3.0** 方式使用 Qt for Python：

1. **动态链接**：PySide6 与 Qt 6.8.1 以独立 DLL（`PySide6/Qt6*.dll`）和独立插件
   （`PySide6/plugins/**`）随 one-dir 安装包分发，未做静态链接。安装目录
   `_internal/PySide6/` 下的 Qt 库文件保持可替换。
2. **未修改源代码**：未修改 Qt/PySide6 源码；所需源码可从 Qt 官方获取：
   - Qt 6.8.1 源码：<https://download.qt.io/official_releases/qt/6.8/6.8.1/>
   - Qt 代码仓库：<https://code.qt.io/cgit/qt/>
   - PySide6 源码：<https://code.qt.io/cgit/pyside/pyside-setup.git/>
3. **源码提供承诺**：如 LGPL-3.0 第 6 条适用，分发者将按用户要求提供对应版本的
   库源码或书面获取方式；欢迎通过项目 Issue 索取。
4. **未使用 GPL-only 模块**：未链接 Qt WebEngine、Qt Charts（GPL 变体）等，
   安装包中也不包含这些模块。
5. **许可证全文**：`LICENSES/pyside6/LGPL-3.0-only.txt`（随包生成时复制），
   另附 GPL-3.0 全文（LGPL-3.0 引用 GPL-3.0）。
6. **版权声明**：Qt 与 Qt 商标版权归 The Qt Company Oy 及其贡献者所有。

用户替换 Qt 库的方法：关闭 EngineerDiff，备份并用兼容版本的
`PySide6/Qt6*.dll`、插件替换安装目录 `_internal/PySide6/` 下对应文件即可（不同
Qt 小版本之间 ABI 兼容性由用户自行确认）。

## 3. OCR 模型许可与来源（RapidOCR / PaddleOCR）

- **RapidOCR**：`rapidocr-onnxruntime==1.4.4`，Apache-2.0，
  <https://github.com/RapidAI/RapidOCR>。
- **模型体系**：PP-OCR（PaddleOCR / 百度），模型版权归 PaddleOCR 项目及贡献者所有，
  以 **Apache-2.0** 发布，<https://github.com/PaddlePaddle/PaddleOCR>。
- RapidOCR 在其 wheel 中再分发 PP-OCR 模型；本软件仅通过 RapidOCR 调用模型，
  **不引入 PaddlePaddle 运行时**，不修改模型文件，运行时**不联网下载**模型。
- 随包模型文件（来自 `rapidocr_onnxruntime/models/`，SHA-256 固定于 1.4.4 wheel）：

  | 模型 | SHA-256 |
  |---|---|
  | `ch_PP-OCRv4_det_infer.onnx` | `d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9` |
  | `ch_PP-OCRv4_rec_infer.onnx` | `48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b` |
  | `ch_ppocr_mobile_v2.0_cls_infer.onnx` | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` |

  构建时 `scripts/collect_licenses.py` 会重新计算实际随包模型的 SHA-256 并写入
  `MODEL_LICENSES.md`。
- Apache-2.0 全文：`packaging/licenses/Apache-2.0.txt`，随包复制到
  `LICENSES/rapidocr-onnxruntime/`。

## 4. ONNX Runtime（MIT）

- 版本：`onnxruntime==1.20.1`，MIT License，<https://github.com/microsoft/onnxruntime>。
- 随包为 CPU 版动态库（Windows 为 `onnxruntime.dll` 等），未修改。
- 许可证全文随包复制到 `LICENSES/onnxruntime/`（wheel 自带 `LICENSE` /
  `ThirdPartyNotices.txt`；如 wheel 未携带则回退标准 MIT 文本）。

## 5. OpenCV 与 FFmpeg

- `opencv-python==4.10.0.84` 以 **Apache-2.0** 发布；wheel 内另含第三方组件，
  原始声明见 wheel 自带 `cv2/LICENSE.txt`、`cv2/LICENSE-3RD-PARTY.txt`（随包复制到
  `LICENSES/opencv-python/`）。
- Windows wheel 内含 **FFmpeg**（`opencv_videoio_ffmpeg*.dll`）用于视频 I/O，
  FFmpeg 以 **LGPL-2.1**（可能含可选组件说明）随 OpenCV wheel 分发。本软件的
  图片比较功能不使用视频 I/O，但该 DLL 是 OpenCV wheel 的一部分，会一并随包。
  - FFmpeg 源码：<https://ffmpeg.org/download.html>；
  - OpenCV Windows wheel 的构建配置与 FFmpeg 版本说明见 OpenCV 官方文档与
    wheel 内 `LICENSE-3RD-PARTY.txt`；
  - 按照 LGPL 要求，FFmpeg 以独立 DLL 形式分发、可被用户替换；
    如需 FFmpeg 对应源码或构建配置，可通过项目 Issue 索取。
- OpenCV 还包含 Intel IPP（Intel Simplified Software License）等第三方组件，
  详见 `LICENSE-3RD-PARTY.txt` 原文。

## 6. GEOS（shapely 可选依赖，LGPL-2.1）

`shapely` 的二进制 wheel 会捆绑 GEOS（<https://libgeos.org>，LGPL-2.1）。
如果 PyInstaller 实际收集了 shapely 及其 GEOS 动态库：
- GEOS 以独立动态库分发、可替换；许可证全文见
  `LICENSES/shapely/LICENSE_GEOS`；
- GEOS 源码：<https://github.com/libgeos/geos>，对应版本以 wheel 内声明为准。

## 7. Python 运行时与 PyInstaller

- **Python 3.11**：随包由 PyInstaller 分发 Python 运行时，许可证为 **PSF-2.0**
  （<https://docs.python.org/3.11/license.html>），全文随包复制到
  `LICENSES/Python-3.11/PSF-2.0.txt`。
- **PyInstaller 6.x**：构建工具，GPL-2.0-or-later **附特例（bootloader exception）**，
  该特例明确允许使用 PyInstaller 打包并分发非自由/专有程序；产物 exe 内嵌
  PyInstaller bootloader。许可证全文随包复制到 `LICENSES/PyInstaller/COPYING.txt`。
  <https://pyinstaller.org/en/stable/license.html>

## 8. Inno Setup（安装程序）

- 安装包由 **Inno Setup 6** 生成，许可证为 **Inno Setup License**（自定义许可，
  允许商业分发，要求保留版权声明与出处）。许可证全文：
  <https://jrsoftware.org/files/is/license.txt>，随包复制到
  `LICENSES/Inno Setup/Inno-Setup-LICENSE.txt`。
- 安装程序中文界面使用的 **Inno Setup 简体中文语言文件**由
  [kira-96/Inno-Setup-Chinese-Simplified-Translation](https://github.com/kira-96/Inno-Setup-Chinese-Simplified-Translation)
  维护，以 **MIT** 许可分发（Copyright (c) 2019-2020 kirakira），
  全文见 `packaging/licenses/ChineseSimplified-Translation-MIT.txt` 与
  `LICENSES/Inno Setup Chinese Translation/`。
- Inno Setup 安装器自身不包含在 EngineerDiff 安装目录中；其生成的卸载程序与安装
  代码属于安装包的一部分。

## 9. Microsoft Visual C++ 运行库（VC++ Redistributable DLL）

- 随包 DLL：`msvcp140.dll`、`msvcp140_1.dll`、`msvcp140_2.dll`、
  `msvcp140_atomic_wait.dll`、`msvcp140_codecvt_ids.dll`、`vcruntime140.dll`、
  `vcruntime140_1.dll`、`concrt140.dll`、`vcomp140.dll`（以构建机系统实际存在、
  被收集的版本为准）。这些 DLL 是 ONNX Runtime / OpenCV 扩展模块在 Windows 上
  的正常运行依赖，干净的 Windows 可能未预装。
- 来源与许可：**Microsoft Visual Studio 2015-2022 可再发行组件**（Microsoft
  Visual C++ Redistributable）。Microsoft 的 Visual Studio 许可中的
  “Distributable Code” 条款允许将上述运行库 DLL 随应用再分发；本软件未修改这些
  DLL，并保留 Microsoft 的版权。
  - 官方下载/说明：<https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist>
  - 如企业环境策略不允许随包分发，可在目标机安装官方
    `VC_redist.x64.exe` 后删除安装目录中的对应 DLL（程序仍可运行）。
- 这些 DLL 不属于 EngineerDiff 的 MIT 许可范围。

## 10. 其他

- **Noto Sans SC 字体**：仅存在于仓库 `tests/assets/` 用于 OCR 测试合成截图，
  **不随安装包分发**（其许可证为 SIL OFL-1.1，全文见 `tests/assets/OFL-1.1.txt`；
  如需随包分发需另行附许可）。
- **Qt 翻译文件**：若 PyInstaller 收集了 Qt 自带翻译文件，其许可证随 Qt
  （LGPL-3.0）。
- **构建/测试工具**（pytest、xlwt、pip、setuptools 等）仅在构建机使用，
  不随应用分发。
- **许可证原文目录**：安装目录 `LICENSES/`（构建时生成，含 `MANIFEST.json`）；
  未在 wheel 中携带原文的组件（如 onnxruntime、PySide6、RapidOCR）使用
  `packaging/licenses/` 下的标准许可证文本，并在 MANIFEST 中标记来源。

## 11. 合规自查清单（维护者）

- [ ] `python scripts/check_deps.py` 通过（版本锁定、单一 OpenCV、OCR 模型齐全）。
- [ ] `python scripts/collect_licenses.py --dist dist/EngineerDiff --strict` 无缺失项。
- [ ] `LICENSES/MANIFEST.json` 中 `missing` 为空。
- [ ] PySide6/Qt、GEOS、FFmpeg 等 LGPL 组件的动态库在 one-dir 中保持独立可替换。
- [ ] 升级依赖或 Inno Setup 版本时，同步更新本文档、`packaging/licenses/` 与
      `packaging/languages/ChineseSimplified.isl`。

---

*本文档随版本更新；如发现许可证信息有误或缺失，请通过项目 Issue 反馈。*
