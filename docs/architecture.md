# EngineerDiff 架构说明

## 1. 分层

```
┌────────────────────────────────────────────────────────────────────┐
│ Application                                                        │
│   app.py（QApplication/样式/图标/参数/自检入口）                    │
├────────────────────────────────────────────────────────────────────┤
│ UI（PySide6，仅消费 DiffModel）                                     │
│   MainWindow（文件区/差异导航/状态栏/同步/设置）                     │
│   TextView / GridView / SpreadsheetSide / ImagePane / OCR 校对      │
│   Workers：QThread 中运行比较，主线程只收信号                        │
├────────────────────────────────────────────────────────────────────┤
│ Comparison orchestration                                           │
│   compare.py：按文件类型调用引擎、汇总 warnings/elapsed              │
│   self_test.py：安装包内 8 项端到端自检                             │
├────────────────────────────────────────────────────────────────────┤
│ Engines（无 Qt 依赖，可单测）                                       │
│   textdiff/     编码识别、行对齐、字符级 span                       │
│   spreadsheet/  XLSX/XLS 读取、CSV 解析、Sheet 配对、单元格比较      │
│   ocr/          RapidOCR 懒加载、缓存、坐标/置信度/取消              │
│   image/        ORB/文字锚点几何对齐、一对一匹配、字符框估算          │
├────────────────────────────────────────────────────────────────────┤
│ DiffModel（models.py）                                             │
│   DiffItem / DiffLocation / TextComparison / WorkbookComparison /   │
│   ImageComparison / OcrPage / 设置                                  │
├────────────────────────────────────────────────────────────────────┤
│ FileLoader（file_loader.py）与资源                                   │
├────────────────────────────────────────────────────────────────────┤
│ Packaging                                                          │
│   PyInstaller onedir spec → Inno Setup → GitHub Actions Windows CI  │
└────────────────────────────────────────────────────────────────────┘
```

## 2. 关键数据流

### 文本 / CSV 文本视图

1. `read_text`：BOM → UTF-8 → GB18030 → charset-normalizer → Latin-1 回退；
2. 按物理行保留行内容与换行符；按设置构造归一化 key（大小写/空白/换行）；
3. `SequenceMatcher` 对齐行；替换块内用 DP 相似度对齐，避免把无关行硬配；
4. 对配对的每行做字符级 `SequenceMatcher`，将归一化区间映射回原文字符区间；
5. 生成两侧等长的 `DisplayLine`（缺失侧用占位行），每处差异生成 `DiffItem`；
6. `TextView` 只绘制视口内的行；差异字符背景/红色文字；同步滚动由 MainWindow 连接滚动条。

### Excel / CSV 表格视图

1. `load_workbook`：XLSX 双载（公式 / 缓存值 + 样式/合并/宽高）；XLS 用 xlrd；
2. `compare_workbooks`：按 Sheet 名称精确配对（与顺序无关），同一 Sheet 按坐标比较；
3. 值规范化：空白/文本/数值（Decimal）/布尔/日期/错误/公式；类型不同即差异；
4. 公式模式：按表达式或按缓存值；缓存缺失标橙、不判相同；
5. 合并区域不一致在锚点生成一条橙色提示；
6. 输出 `SheetComparison` 状态与单元格 `DiffItem`；`GridView` 构建差异坐标映射，
   虚拟化绘制单元格/合并格/表头，Sheet 标签红/橙，缺 Sheet 显示占位。

### 图片 OCR

1. `OcrService` 懒加载 RapidOCR（共享单例、串行推理、SHA-256 缓存、进度/取消）；
2. 保留每个文字框的四点坐标、置信度与原文；
3. `match_pages`：
   - ORB 特征 / 文字锚点 RANSAC 估计右图到左图的尺度+平移；版面比例回退；
   - 综合文本相似度、映射后位置、尺寸比、邻域上下文代价，匈牙利做一对一分配；
   - 重复文字靠上下文与几何消歧；低置信度/歧义标橙；
   - 文本不同 → `difflib` 字符区间 + CJK/拉丁宽度比例估算 `segment_boxes`；
   - 仅一侧文字 → 该侧红/橙高亮；内容相同不生成差异；
4. `ImagePane` 用 QGraphicsView 显示原图 + 覆盖层；原图不修改；支持缩放/拖动/同步；
5. `OcrCorrectionDialog` 修改文本/人工配对，重新比较时作为 `ImageOptions` 传入。

## 3. 线程与取消

- 所有文件读取/比较/OCR 都在 `CompareWorker(QThread)` 中执行，主界面保持响应；
- 进度通过 Qt Signal 回传；OCR 每个阶段检查取消标志；推理调用不可中断时返回后丢弃结果；
- `compare.run_comparison` 将 `OcrCancelled` 映射为 `ComparisonCancelled`，UI 不弹错误框；
- 关闭窗口时等待线程安全结束，避免 QThread 销毁崩溃。

## 4. 统一差异模型

`DiffItem` 包含：稳定 id、类型（改/增/删/仅一侧/不确定）、严重级别、标题、左右
`DiffLocation`（文本行号/显示行、Sheet、行列、图像 bbox、字符 spans、字符子框）、
置信度、是否需要人工复核、详情。所有视图共用该模型，差异导航只依赖 `DiffItem`，
因此文本、表格、图片的“上一处/下一处/序号/总数”行为一致。

## 5. 打包与离线

- PyInstaller onedir：`EngineerDiff.exe` + `_internal`；显式收集 RapidOCR 3 个 ONNX 模型和
  config、ONNX Runtime/OpenCV/Qt 插件与 VC++ 运行库；不收集未使用的 Qt 大模块；
- Inno Setup：per-user 安装，中文界面，离线，含 docs/许可证/OCR 模型；
- CI：Windows runner 上跑全量 pytest、打包、`--self-test`、安装/卸载冒烟测试；
- `--self-test` 不需要显示界面，验证文本/CSV/Excel/OCR/图片匹配/GUI 渲染，并输出 JSON。

## 6. 设计取舍

- 不引入 Web/Server/数据库：桌面本地工具，所有数据在内存/本地文件中；
- 不比较 Excel 样式/批注/图表：首版核心是“内容差异标红”；
- 不静默近似数值：默认严格，容差必须用户显式设置；
- OCR 失败/低置信度不当作相同：橙色并允许人工校对；
- 开源复用遵循许可证：WinMerge(GPL) 仅参考交互，xlsxDiff(AGPL) 仅参考算法，不复制代码。
