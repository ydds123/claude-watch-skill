# Frame integrity — 取帧、版本、页面身份与发布门禁

Screenshots 反复出问题（过渡帧、半透明弹窗、旧图、页面错配、缺图）的根因都在“抽帧只取单点 + 图片同名覆盖 + 门禁不校验状态”。按下面规则执行。

## 1. 稳定帧：连拍 + 平台期 + 状态断言

产物模式（`product-guide` / `external-manual`）默认在 `watch.py` 里对每个动作锚点做连拍择优，输出到 `frame-stable/`，证据写入 `product-evidence.json` 的 `stable_frames`；`--no-stable-frames` 可关闭。单点补抽或需要断言时再用脚本：

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/stable_frame.py" \
  --video <video> --time HH:MM:SS --window 4 --fps 6 \
  --out chosen.png --report stable.json \
  --reference current.png \
  --assert-region x1,y1,x2,y2 --assert-white-min 0.55
```

- 平台期 = 连续帧差 ≤ 阈值（默认 1.2）；取平台中段帧。
- 状态断言：目标 UI 区域必须满足期望（如弹窗区域近白占比 ≥ 0.55）；断言失败 → 扩窗重抽或标记“需重录”，不进入后续流程。
- 报告字段必须落入 manifest：`plateau_frames`、`plateau_mean_diff`、`state_assert_passed`。
- 禁止：black / blank / loading / transition / duplicate 帧。

## 2. 浮窗（弹窗、抽屉、气泡）决策树

1. 浮窗是正文讲解对象 → 必须完整展示：完整展开、不透明、文字可读；不能换成“没有浮窗的帧”。
2. 浮窗只是遮挡、与讲解无关 → 优先换更干净的帧；仍无法避免时裁掉浮窗区域。
3. 浮窗半透明 / 加载中 / 动画中间态 → 视为不合格帧：扩窗重抽；仍不行则记录“需重录”。
4. 直接弃用：无关浮窗遮挡主体、鼠标/通知遮挡关键字段、“暂无数据”且空态不是讲解对象、页面切换过渡帧。

## 3. 资产版本化与 manifest

- 文件名带版本：`NN-<slug>-v5.jpg`；文档引用带版本；每次重生成升版本并删除旧文件，避免同名缓存看到旧图。
- `assets/manifest.json` 每张图记录：`file`、`sha256`、`bytes`、`raw`（原图）、`ops`、`page_id`、`generated_at`、可选的 `frame_evidence`。
- 交付前必须能回答：这张图来自哪个视频的哪一秒、经过哪些处理、当前文件是不是最新。

## 4. 页面身份（page_id）一致性

- 每张图登记 `page_id`：当前 tab 标题或弹窗标题（如“风险分析对象 / 新增”“巡检点管理 / 新增巡检点”）。
- 图注必须与 `page_id` 一致；不一致即门禁失败。
- 抽帧后先核对页签条：tab 名、弹窗标题、列表列名三者至少两项吻合，才可用于正文。

## 5. 标注策略（上下文驱动）

- 只标操作点：按钮、输入框、下拉、tab、提交入口。
- 结果页、报表页、清单页、四色图等“展示型”截图不标注。
- 每图 ≤ 2 个标注；标签 2–8 字；箭头从标签指向目标；编号与正文步骤编号一致。
- 已标内容与正文步骤不一致 → 删标注或改正文，不允许“为标而标”。

## 6. 脱敏默认口径

- 默认只模糊企业名称（页面头部 + 组织树）；内网地址、手机号、共享屏幕水印如出现也必须遮挡。
- 项目另有约定（如姓名/工号/整表）从其约定，并在门禁记录写明口径。
- 脱敏后逐张复核：企业名不再可读、遮罩未盖住关键操作内容。

## 7. 缺图自查（不等用户）

1. 页签条是否出现过该页面名？
2. 左侧菜单是否打开过？
3. 转写是否提到？视频区间内是否有空白段？

有 → 用全片 1fps 帧库或 `scripts/find_pages.py` 定位补帧；脚本会按 aHash 聚类输出 `unique-pages.jpg` 与 `unique-pages.csv`（去重后的页面及其首次出现时间）。确实没有 → 记入“证据缺口与发布门禁”，注明“视频未演示”，不得留空引用或伪造截图。

## 8. 交付契约（输入 / 输出 / 边界）

- 输入：视频 URL 或本地路径；可选主题、模式、已有转写、工作区约束。
- 输出：库目录（转写、帧、证据）、正文 Markdown、版本化截图（`assets/images`）、原图（`assets/raw`）、标注 JSON、`assets/manifest.json`、门禁报告。
- 边界外：视频剪辑/转码交付、一次性转写摘要、幻灯片或营销文案。
- 停止条件：源无法下载/解码；无转写且用户接受纯帧笔记；所需截图全片不存在 → 记缺口，不伪造。

## 9. 门禁

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/annotate.py" <spec.json> --qa
python3 "${CLAUDE_SKILL_DIR}/scripts/check_images.py" --doc <doc.md> --min-width 1400 --report-out gate/image-gate.json --title-out gate/titles.jpg
python3 "${CLAUDE_SKILL_DIR}/scripts/doc_lint.py" --doc <doc.md> --manifest <assets/manifest.json> --images-dir <assets/images> --report-out gate/doc-lint.json   # 对外手册追加 --external（禁止验收检查表等内部内容）
```

三项全过才可交付；任何失败回到对应工序，不允许只补单项。
