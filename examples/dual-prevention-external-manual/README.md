# 示例：双预防机制对外操作手册

这是一份**完整成品示例**，用来说明 claude-watch 的 `external-manual` 模式最终交付物长什么样，以及图片/文档门禁应该检查哪些项。

> 数据说明：截图来自演示环境。企业名称已做模糊处理；人员姓名、工号等为演示数据。若将本仓库公开，请按项目要求重新评估脱敏范围。

## 示例包含什么

| 内容 | 数量/说明 |
|---|---|
| 操作手册正文 | `双重预防机制操作手册.md`（10 章，19 张图） |
| 章节结构 | 功能说明 → 前置条件 → 操作步骤 → 结果查看 → 常见问题（**不含验收检查表**，验收属内部内容） |
| 截图 | `assets/images/*-v5.jpg`，19 张，1665×909 / 1719×909 / 1920×1035 |
| 标注配置 | `assets/annotations/manual.json`（20 个操作点，带 2–8 字标签和箭头） |
| 资产清单 | `assets/manifest.json`（版本、sha256、page_id、OCR 证据） |
| 页身份建议 | `assets/page-id-suggestions.csv` |
| 配套文档 | `术语表.md`、`证据缺口与发布门禁.md`、`质量自检门禁.md` |
| 门禁产物 | `gate/image-gate.json`、`gate/doc-lint.json`、`gate/titles.jpg`（标题条复核）、`gate/qa-sheet1.jpg`、`gate/qa-sheet2.jpg`（标注 QA） |

## 门禁结果

```text
check_images.py : checked=19, ok=true
doc_lint.py     : ok=true, 0 failure, 0 warning（含标注策略检查）
```

`image-gate.json` 中有 3 条 warning：`10/11/13` 三张图的文件名仍是旧页面名（绩效统计/异常上报/调整列表顺序），与 `page_id` 不一致。这是门禁在真实数据上抓到的待清理项，示例保留原样以展示 warning 长什么样。

> 说明：示例中门禁产物放在 gate/；原项目里对应 运行产物/gate/，内容与文件名不变。

## 没有包含什么（以及为什么）

| 未包含 | 原因 |
|---|---|
| 源视频（双预防上/下.mp4） | 客户内部培训素材，不随仓库分发 |
| `assets/raw/` 原始帧 | 19 张 1920 原图约 10 MB，可由源视频按时间点重新抽取 |
| `运行产物/` 中间产物 | 全片帧库、grid、scan 等约 361 MB，属过程文件 |
| 转写稿 | 含客户内部讲解内容，不随仓库分发 |

## 复现方式

拿到源视频后，按以下顺序可复现本示例：

```bash
# 1) 生成转写 + 帧 + 证据（已有转写时加 --no-whisper）
python scripts/watch.py "双预防（上）.mp4" --mode external-manual --no-whisper

# 2) 稳定帧 / 页签扫描（按需）
python scripts/stable_frame.py --video "双预防（上）.mp4" --time 00:11:40 \
  --window 4 --fps 6 --out chosen.png --report stable.json \
  --assert-region 500,340,1150,600 --assert-white-min 0.55
python scripts/find_pages.py --video "双预防（下）.mp4" --out scan/ --fps 0.1

# 3) 出图 + 门禁
python scripts/annotate.py assets/annotations/manual.json --qa
python scripts/check_images.py --doc 双重预防机制操作手册.md \
  --manifest assets/manifest.json --require-page-id \
  --min-width 1400 --report-out gate/image-gate.json --title-out gate/titles.jpg
python scripts/doc_lint.py --doc 双重预防机制操作手册.md \
  --manifest assets/manifest.json --images-dir assets/images \
  --require-versioned --require-page-id --external \
  --annotations assets/annotations/manual.json --report-out gate/doc-lint.json
```

建议阅读顺序：`SKILL.md` → `docs/使用说明与录制规范.md`（录制要求）→ 本示例（成品长什么样）。

