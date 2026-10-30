# EngineerDiff 模块与 UI 接口契约

本文件由 Lead 维护，所有开发成员必须遵守。数据模型以 `src/engineerdiff/models.py` 为唯一来源。

## 1. 职责边界

| 模块 | 文件 | 负责人 |
|---|---|---|
| 数据模型/文件识别 | `models.py`, `file_loader.py` | Lead |
| 文本比较 | `textdiff/engine.py` | Lead |
| 表格读取/比较 | `spreadsheet/loader.py`, `csv_parser.py`, `engine.py` | spreadsheet-dev |
| 表格渲染 | `ui/grid_view.py`, `ui/spreadsheet_side.py` | spreadsheet-dev |
| OCR | `ocr/engine.py`, `ocr/cache.py` | ocr-dev |
| 图片匹配 | `image/matcher.py`, `image/engine.py` | ocr-dev |
| 图片渲染/校正 | `ui/image_view.py`, `ui/ocr_dialog.py` | ocr-dev |
| 文本渲染/主窗口/集成 | `ui/text_view.py`, `ui/main_window.py`, `ui/workers.py`, `app.py` | Lead |
| 打包/CI/文档 | `packaging/`, `.github/`, `scripts/`, `docs/` | packaging-dev（选型报告 research-scout） |

不得修改他人文件。需要通过 Lead 调整契约时先发消息，不要自行改 `models.py` 或 `file_loader.py`。

## 2. 表格模块接口

### 2.1 读取

```python
# spreadsheet/loader.py
def load_workbook(path: str | Path) -> Workbook: ...
# 支持 .xlsx/.xls；失败抛 SpreadsheetLoadError（ValueError 子类），消息为中文且可展示。
```

要求：读取全部 Sheet；按名称配对是 engine 的职责，loader 保留工作簿内顺序。`rows` 必须为矩形 `nrows x ncols`，空白单元格用 `Cell()`。XLSX 用 openpyxl 同时读取公式与缓存值（两次加载），合并单元格在锚点写 `span=(rowspan,colspan)`，其余单元格写 `merged_anchor`，并填充 `sheet.merged`。列宽/行高转为 96dpi 像素；`col_widths` 为 Excel 字符宽度换算值，默认列宽约 72px，行高约 20px。样式只要求基本还原（粗体、字号、对齐、填充色、字体色），不比较样式。

### 2.2 CSV

```python
# spreadsheet/csv_parser.py
def parse_csv(path: str | Path) -> tuple[Sheet, str, list[str]]:
    """返回 (单 Sheet, 使用的分隔符, 警告)。必须使用 csv 模块，支持引号内逗号/换行。"""
```

Sheet.name 固定为 `"CSV"`。显示文本保留原始字段内容，空字段为 BLANK，非空为 TEXT。列宽按内容估算（限制 60–360px）。

### 2.3 比较

```python
# spreadsheet/engine.py
def compare_workbooks(
    left: Workbook,
    right: Workbook,
    options: SpreadsheetOptions | None = None,
) -> WorkbookComparison: ...
```

规则：
- 按 Sheet 名称精确配对，与顺序无关。只在一侧存在的 Sheet 生成 `sheet.diffs` 中一条 `DiffKind.ONLY_LEFT/ONLY_RIGHT` 差异，`group="sheet"`，text 为 Sheet 名。顺序不同但内容相同 → 不标红。
- 内容比较：严格坐标；空白 vs 非空必须不同；类型不同（数值/文本/布尔/日期/错误）必须不同；数值按 Decimal 值比较（1.50 == 1.5），默认容差 0，若设置容差则仅对两侧均为数值且相对差/绝对差在容差内视为相同。日期按规范化 ISO 值；字符串严格区分大小写和空白。
- 公式：`formula_mode="formula"` 时，只要任一侧有公式就比较公式表达式（去除首尾空白、统一大小写？不，保持原样，仅 strip）；一侧公式一侧无公式 → 差异。`formula_mode="value"` 时比较缓存值；缓存值缺失（None 且无法确定为空白）→ 橙色 `Severity.UNCERTAIN`、`needs_review=True`，不得判为相同。附加 detail 写明公式和缓存值。
- 合并区域不一致：在锚点单元格生成一条橙色差异（如内容相同也提示），`detail="合并单元格区域不一致"`；不要对合并区域内部每个空格重复生成差异。
- 每处单元格差异生成一个 `DiffItem(group="cell", kind=MODIFIED/ADDED/REMOVED)`，`left/right` 为 `DiffLocation(kind="cell", row=..., col=..., sheet=..., text=..., bbox=None)`。对侧缺失用 None；空白单元格也生成 location（text=""）便于定位。
- `WorkbookComparison.diffs` 顺序 = 工作表顺序（左侧优先，右侧仅有的随后）、行、列。差异 id 稳定：`cell:{sheet}:{row}:{col}`、`sheet:{name}`。
- `smart_rows=True` 为实验性的整行对齐模式：用行签名序列对齐后再比较；严格模式行为不得改变。若实现风险大，先保证严格模式并报告，不得静默改变默认行为。
- 每个 SheetComparison 的 status：EQUAL / DIFFERENT / ONLY_LEFT / ONLY_RIGHT；Merge 区域不一致算 DIFFERENT。

### 2.4 表格 UI

```python
# ui/grid_view.py
class GridView(QAbstractScrollArea):
    def set_sheet(self, sheet: Sheet, diffs: list[DiffItem], side: str,
                  uncertain: bool = False) -> None: ...
    def set_zoom(self, zoom: float) -> None: ...      # 0.5 .. 2.5
    def zoom(self) -> float: ...
    def set_only_diffs(self, enabled: bool) -> None: ...
    def scroll_to_cell(self, row: int, col: int) -> None: ...
    def current_cell(self) -> tuple[int, int] | None: ...
    def set_show_grid(self, show: bool) -> None: ...
```

`diffs` 传入当前 Sheet 的全部差异；GridView 根据 location 的 row/col 构建差异映射；仅左边/右边存在的单元格也要能定位。`A/B/C` 列标与行号固定表头；合并单元格跨格绘制；列宽行高和 `zoom` 相乘；只绘制视口内单元格（虚拟化，万行不卡）；差异背景浅红 `#FFD7D5`、左边框红色，橙色 `#FFE2B8`；文字使用原单元格颜色/对齐；空白单元格保持空白。`only_diffs=True` 时仅显示含差异的行 + 前后各 1 行上下文（上下文行为普通色），行号仍显示原始行号。滚动条由 QAbstractScrollArea 原生提供。

```python
# ui/spreadsheet_side.py
class SpreadsheetSide(QWidget):
    sheet_selected = Signal(str)          # 用户点击标签（左侧/右侧均会发）
    scroll_changed = Signal(float, float) # 垂直比例、水平比例
    def load(self, workbook: Workbook, comparison: WorkbookComparison,
             side: str, show_tabs: bool = True) -> None: ...
    def show_sheet(self, name: str | None) -> None: ...
    def current_sheet(self) -> str | None: ...
    def sheet_names(self) -> list[str]: ...
    def reveal(self, diff: DiffItem) -> None: ...
    def set_zoom(self, zoom: float) -> None: ...
    def set_only_diffs(self, enabled: bool) -> None: ...
    def grid(self) -> GridView: ...
```

- 标签颜色：当前 Sheet 内容有差异 / 仅本侧存在 → 标签文字红色（`#C62828`），有橙色项 → 橙红；无差异正常。当前选中标签加下划线/加粗，与红色区分（选中背景 #E3F2FD）。
- 用户点击标签发 `sheet_selected(name)`，由 MainWindow 调用另一侧 `show_sheet(name)`（同步开关开启时）；MainWindow 负责同步逻辑。
- `show_sheet(name)` 若本侧无该名称：显示居中占位“无对应工作表”，保留标签选中态，不得静默切换错误 Sheet。
- `reveal(diff)`：若 diff.sheet 存在则先切 Sheet，再 `scroll_to_cell`。工作表级差异（无 row/col）只切标签。
- 无 Sheet（空工作簿）时显示占位“工作簿中没有工作表”。
- 滚动同步：MainWindow 连接 `scroll_changed`，调用另一侧 `grid().verticalScrollBar().setValue(...)`，注意防递归。

## 3. OCR / 图片模块接口

### 3.1 OCR

```python
# ocr/engine.py
class OcrError(RuntimeError): ...
class OcrService:
    def __init__(self, cache_dir: str | Path | None = None) -> None: ...
    def recognize(self, image_path: str,
                  progress: Callable[[int, str], None] | None = None,
                  cancel: Callable[[], bool] | None = None) -> OcrPage: ...
    def clear_cache(self) -> None: ...
    def model_info(self) -> dict: ...
```

- 使用 `rapidocr_onnxruntime.RapidOCR`，CPU 推理，模型必须来自随包分发的 `rapidocr_onnxruntime/models`，禁止联网下载、禁止依赖外部 Python/Paddle。
- 延迟初始化，进程内单例；多线程串行保护；识别结果保留原图坐标（左上原点像素）、置信度、四点框。文本使用 RapidOCR 输出，保留原始空格。
- 缓存：按图片文件 SHA-256 缓存 JSON 到用户缓存目录（`QStandardPaths.AppCacheLocation` 或传入目录），只有成功结果才缓存；提供版本号，模型/算法升级后失效。禁止用缓存掩盖错误。
- 取消：每个阶段检查 `cancel()`；OCR 调用本身不可中断时，返回后若已取消则抛出 `OcrCancelled`（定义在 ocr/engine.py），结果不得显示。进度回调至少给出 5/30/90/100。
- 低置信度框保留，由 matcher 标橙。

```python
# image/engine.py
class ImageCompareError(RuntimeError): ...
def compare_images(left_path: str, right_path: str,
                   options: ImageOptions, ocr: OcrService,
                   progress: Callable[[int, str], None] | None = None,
                   cancel: Callable[[], bool] | None = None) -> ImageComparison: ...
```

- 依次 OCR 左右图；对 `options.text_overrides` 应用人工修正（记录 raw_text/overridden）；对 manual_pairs 强制配对。
- 匹配必须在 matcher 中完成，坐标保留在各侧原图坐标系；输出统一 `ImageComparison.diffs`。
- 任何一侧 OCR 无文字/失败不得判为一致：加 warning，整体状态由 UI 显示；失败抛异常，UI 显示错误。

### 3.2 匹配

```python
# image/matcher.py
def match_pages(left: OcrPage, right: OcrPage, options: ImageOptions) -> tuple[list[DiffItem], dict]: ...
```

- 不得仅按 OCR 输出顺序匹配，不得仅按相同字符串匹配。
- 结合：文本相似度（对 OCR 常见混淆做轻度归一：全半角、大小写用于匹配评分但保留原文比较；0/O、1/I/l 高相似）、坐标几何变换、相邻文字、行列结构。用 ORB/OpenCV 或文字锚点估计缩放+平移（可选相似变换），将右图坐标映射到左图；再以文本+空间+邻域代价做一对一分配（重复文字必须靠上下文消歧）。
- 不同分辨率/窗口位置/边缘范围/UI 缩放下尽可能匹配；无法可靠配对 → 橙色 UNCERTAIN，不能当相同。
- 字符/片段级高亮：匹配但文本不同 → 双方标红，`DiffLocation.spans` 为字符区间，`segment_boxes` 为原图坐标子框（按字符宽高比例估算，CJK 按 1 个全角宽度，拉丁按 0.55 半角宽度；必须限制在 box 内）。若无法估算则整框；整框时 spans=[(0,len(text))] 且 segment_boxes=[bbox]。
- 仅一侧文字 → 该侧红色高亮，另一侧 location=None；低置信度（< options.confidence_threshold）→ 橙色 + needs_review。匹配但内容相同 → 不生成 diff。
- confidence 取两框较低者；detail 说明 OCR 置信度和匹配依据。id 稳定：`img:{left_id}:{right_id}` 或 `img:l:{id}`。
- 返回 (diffs, transform_info)，transform_info 记录方法/inlier 数量/估计缩放，供状态栏和调试。

### 3.3 图片 UI

```python
# ui/image_view.py
class ImagePane(QWidget):
    def set_comparison(self, page: OcrPage, comparison: ImageComparison,
                       side: str, show_boxes: bool = False) -> None: ...
    def reveal(self, diff: DiffItem) -> None: ...
    def fit_to_window(self) -> None: ...
    def actual_size(self) -> None: ...
    def zoom_in(self) -> None: ...
    def zoom_out(self) -> None: ...
    def zoom(self) -> float: ...
    def set_zoom(self, zoom: float) -> None: ...
    def set_show_boxes(self, show: bool) -> None: ...
    def set_sync_zoom(self, enabled: bool) -> None: ...
    def scroll_ratio(self) -> tuple[float, float]: ...
    def set_scroll_ratio(self, v: float, h: float) -> None: ...
```

- QGraphicsView 显示原图（不可修改原图），叠加透明红/橙色块与边框；相同文字不叠加；低置信度橙色；仅一侧文字红/橙。框位置必须与原图文字对齐（验证截图）。
- Ctrl+滚轮缩放、拖动、适应窗口、原始尺寸；多分辨率并排显示，默认各自适应窗口；支持同步缩放开关。
- “显示 OCR 文字框”模式：所有文字框细蓝边 + 置信度列表，便于核对。
- `OcrCorrectionDialog(parent, comparison, ocr_service)`：显示左右 OCR 结果表格（文本、置信度、坐标），可编辑文本、建立/解除左右对应、重新比较；返回修正后的 ImageOptions（text_overrides/manual_pairs）。MainWindow 捕获后重新运行图片比较。
- 校正只影响当前比较，不修改原文件。

## 4. 集成约定

- MainWindow 在 worker 线程执行 `compare`（文本/CSV/Excel/OCR），不得阻塞 UI。进度/取消通过信号。
- 统一导航按钮调用当前视图的 `reveal(diff)`；差异列表由 `ComparisonResult.diffs_for_view(view)` 提供。
- 同步滚动/缩放由 MainWindow 连接两侧信号；切换时用 guard 防递归。
- 任何异常必须转成中文用户提示 + 状态栏，不得静默。
