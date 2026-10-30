# 仓库内置许可证文本说明

本目录保存**构建时随包分发的标准许可证原文**。`scripts/collect_licenses.py` 优先复制
各 Python wheel 自带的许可证文件；仅当 wheel 未携带原文时，才使用本目录中的文本，
并在 `LICENSES/MANIFEST.json` 中标记 `source: "vendored"`。

## 文件来源

| 文件 | SPDX | 用途 | 来源 |
|---|---|---|---|
| `LGPL-3.0-only.txt` | LGPL-3.0-only | PySide6 / Qt | <https://spdx.org/licenses/LGPL-3.0-only.html>（SPDX license-list-data，官方许可证文本） |
| `GPL-3.0-only.txt` | GPL-3.0-only | LGPL-3.0 引用文本 | <https://spdx.org/licenses/GPL-3.0-only.html> |
| `Apache-2.0.txt` | Apache-2.0 | RapidOCR、OpenCV、flatbuffers | <https://www.apache.org/licenses/LICENSE-2.0.txt> |
| `MIT.txt` | MIT | ONNX Runtime 等 | <https://spdx.org/licenses/MIT.html> |
| `BSD-3-Clause.txt` | BSD-3-Clause | numpy、xlrd、shapely、protobuf | <https://spdx.org/licenses/BSD-3-Clause.html> |
| `MPL-2.0.txt` | MPL-2.0 | tqdm（若 wheel 未带原文） | <https://spdx.org/licenses/MPL-2.0.html> |
| `PSF-2.0.txt` | PSF-2.0 | Python 3.11 运行时 | <https://raw.githubusercontent.com/python/cpython/3.11/LICENSE> |
| `Inno-Setup-LICENSE.txt` | Inno Setup License | Inno Setup 安装器 | <https://jrsoftware.org/files/is/license.txt> |
| `ChineseSimplified-Translation-MIT.txt` | MIT | Inno Setup 简体中文语言文件 | <https://github.com/kira-96/Inno-Setup-Chinese-Simplified-Translation/blob/master/LICENSE> |

PyInstaller 的许可证原文不在此目录：构建时从已安装的 `pyinstaller` 发行包
（`COPYING.txt`）复制到产物 `LICENSES/PyInstaller/`。

## 合规提示

- 这些文本仅用于合规分发，不改变各组件原有的许可证条款。
- 升级依赖版本时，请重新运行 `python scripts/collect_licenses.py --dist <dist> --strict`
  并检查 `LICENSES/MANIFEST.json` 的 `missing` 字段是否为空。
- LGPL 组件（PySide6/Qt、GEOS）必须以动态库形式保持可替换，详见
  `docs/third-party-licenses.md` 第 2、6 节。
