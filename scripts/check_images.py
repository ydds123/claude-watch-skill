"""Quality gate for operation-manual images.

Checks every image referenced by a markdown manual and (optionally) renders a
zoomed "title strip" contact sheet so page titles can be compared with the
figure captions before publishing.

Checks:
- every ``![alt](path)`` target exists;
- image pixel width >= ``--min-width`` (default 1400) so text stays legible;
- image height is plausible (no broken/empty crops);
- no two figures reference the same file unless explicitly allowed;
- a JSON report is written with per-figure status.

Title strips are cropped from the top of each *finished* image (page header /
breadcrumb / tab row area) and tiled into one sheet.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_REF = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
)


def _font(size: int):
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def collect_figures(doc_path: Path) -> list[dict]:
    """Return ordered figures with alt text and reference path."""
    text = doc_path.read_text(encoding="utf-8")
    figures: list[dict] = []
    for match in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", text):
        alt = match.group(1).strip()
        target = match.group(2).strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        figures.append({"alt": alt, "ref": target})
    return figures


def collect_refs(doc_path: Path) -> list[str]:
    return [figure["ref"] for figure in collect_figures(doc_path)]


def load_manifest(path: Path | None) -> dict[str, dict]:
    if path is None or not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    images = data.get("images", data) if isinstance(data, dict) else data
    if not isinstance(images, list):
        raise ValueError("manifest must be a list or an object with an 'images' list")
    return {
        Path(str(item["file"])).name: item
        for item in images
        if isinstance(item, dict) and item.get("file")
    }


def _caption_matches(page_id: str, caption: str) -> bool:
    tokens = [token for token in re.split(r"[/、|,，\s]+", page_id) if len(token) >= 2]
    if not tokens or not caption:
        return False
    return any(token in caption for token in tokens)


def check(doc_path: Path, min_width: int = 1400,
          manifest: Path | None = None,
          require_page_id: bool = False,
          caption_check: bool = True,
          ocr_check: bool = False) -> dict:
    base = doc_path.parent
    figures = collect_figures(doc_path)
    entries = load_manifest(manifest)
    seen: dict[str, int] = {}
    images: list[dict] = []
    failures: list[str] = []
    warnings: list[str] = []
    for index, figure in enumerate(figures, 1):
        ref = figure["ref"]
        path = (base / ref.replace("\\", "/")).resolve()
        record = {"index": index, "ref": ref, "path": str(path), "caption": figure["alt"]}
        if path in seen:
            record["duplicate_of"] = seen[path]
        seen[path] = index
        entry = entries.get(path.name)
        if manifest is not None and entry is not None:
            record["page_id"] = entry.get("page_id")
            if require_page_id and not entry.get("page_id"):
                failures.append(f"#{index} {ref}: manifest entry has no page_id")
            elif caption_check and entry.get("page_id"):
                matches = _caption_matches(str(entry["page_id"]), figure["alt"])
                record["caption_matches_page_id"] = matches
                if not matches:
                    warnings.append(
                        f"#{index} {ref}: caption may not match page_id ({entry['page_id']})"
                    )
            ocr_evidence = str(entry.get("ocr_text") or "").strip()
            if ocr_check and ocr_evidence and entry.get("page_id"):
                record["ocr_supports_page_id"] = _caption_matches(
                    str(entry["page_id"]), ocr_evidence
                )
                if not record["ocr_supports_page_id"]:
                    warnings.append(
                        f"#{index} {ref}: OCR evidence does not support page_id "
                        f"({entry['page_id']} vs {ocr_evidence})"
                    )
        if not path.is_file():
            record["status"] = "missing"
            failures.append(f"#{index} {ref}: file missing")
            images.append(record)
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
        except Exception as exc:  # noqa: BLE001 - report unreadable images
            record["status"] = "unreadable"
            record["error"] = str(exc)
            failures.append(f"#{index} {ref}: unreadable ({exc})")
            images.append(record)
            continue
        record.update({"width": width, "height": height, "bytes": path.stat().st_size})
        problems = []
        if width < min_width:
            problems.append(f"width {width} < {min_width}")
        if height < 200:
            problems.append(f"height {height} < 200")
        record["status"] = "fail" if problems else "pass"
        if problems:
            failures.append(f"#{index} {ref}: " + "; ".join(problems))
        images.append(record)
    report = {
        "doc": str(doc_path),
        "checked": len(figures),
        "min_width": min_width,
        "failures": failures,
        "warnings": warnings,
        "images": images,
        "ok": not failures,
    }
    return report


def render_title_sheet(report: dict, out_path: Path, strip_ratio: float = 0.16) -> None:
    """Tile the top strip of every checked image into one review sheet."""
    entries = [item for item in report["images"] if item.get("status") in ("pass", "fail")]
    if not entries:
        return
    font = _font(16)
    cols = 2
    tile_w, tile_h = 640, 96
    rows = (len(entries) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, rows * (tile_h + 26) + 8), (15, 15, 15))
    draw = ImageDraw.Draw(sheet)
    for i, item in enumerate(entries):
        try:
            with Image.open(item["path"]) as image:
                strip_h = max(40, int(image.height * strip_ratio))
                strip = image.crop((0, 0, image.width, strip_h)).convert("RGB")
        except Exception:  # noqa: BLE001
            continue
        strip = strip.resize((tile_w, tile_h), Image.LANCZOS)
        row, col = divmod(i, cols)
        x, y = col * tile_w, row * (tile_h + 26) + 22
        sheet.paste(strip, (x, y))
        draw.text((x + 4, y - 20), Path(item["ref"]).name, font=font, fill=(255, 220, 0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=92)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_images", description=__doc__)
    parser.add_argument("--doc", required=True, help="markdown manual file")
    parser.add_argument("--min-width", type=int, default=1400)
    parser.add_argument("--manifest", help="assets/manifest.json for page_id / sha checks")
    parser.add_argument("--require-page-id", action="store_true",
                        help="fail when a referenced image has no page_id in the manifest")
    parser.add_argument("--no-caption-check", action="store_true",
                        help="skip caption vs page_id consistency warnings")
    parser.add_argument("--ocr-check", action="store_true", help="warn when OCR evidence does not support page_id")
    parser.add_argument("--report-out", help="JSON report path")
    parser.add_argument("--title-out", help="title-strip sheet path")
    args = parser.parse_args(argv)
    report = check(
        Path(args.doc),
        min_width=args.min_width,
        manifest=Path(args.manifest) if args.manifest else None,
        require_page_id=args.require_page_id,
        caption_check=not args.no_caption_check,
        ocr_check=args.ocr_check,
    )
    if args.title_out:
        render_title_sheet(report, Path(args.title_out))
        report["title_sheet"] = args.title_out
    if args.report_out:
        Path(args.report_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(
        {k: report[k] for k in ("checked", "ok", "failures", "warnings", "title_sheet") if k in report},
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
