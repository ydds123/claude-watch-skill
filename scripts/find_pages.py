"""Locate pages across a recording, and label screenshots by page.

Two modes:

1. Video scan: sample the video, crop the tab strip, tile strips into contact
   sheets, and cluster near-identical strips so unique pages (and the timestamps
   where they appear) are listed automatically.
2. Page-id assignment: OCR the tab strip of already-published screenshots and
   write ``page_id`` back into ``assets/manifest.json``.

Use the first when a chapter needs a screenshot and it is unclear whether the
page was ever opened ("缺图自查"); use the second before delivery so captions and
figures can be checked against the on-screen page identity.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

_OCR_ENGINE = None


def crop_strip(image, strip_y: tuple[int, int] = (150, 280)):
    """Crop the tab-strip band from a frame image (PIL Image)."""
    x1, y1, x2, y2 = 0, strip_y[0], image.width, min(strip_y[1], image.height)
    return image.crop((x1, y1, x2, y2))


def strip_hash(image, size: int = 8) -> int:
    """Average hash of a strip: 64-bit int, near-duplicate pages share a hash."""
    small = image.convert("L").resize((size, size))
    pixels = list(small.tobytes())
    average = sum(pixels) / len(pixels)
    bits = 0
    for index, value in enumerate(pixels):
        if value >= average:
            bits |= 1 << index
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def ocr_text(image) -> str:
    """Read the tab strip text with RapidOCR when available ("" otherwise)."""
    global _OCR_ENGINE
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:  # noqa: BLE001 - optional dependency
        return ""
    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()
    import numpy as np

    frame = np.asarray(image.convert("RGB"))
    try:
        result, _ = _OCR_ENGINE(frame)
    except Exception:  # noqa: BLE001 - OCR must never break the pipeline
        return ""
    if not result:
        return ""
    texts: list[str] = []
    for item in result:
        text = str(item[1]).strip()
        text = text.replace("×", "").replace("✕", "").strip()
        if text and text not in texts:
            texts.append(text)
    return " / ".join(texts[:4])


def _blue(r: int, g: int, b: int) -> bool:
    return b > 170 and b - r > 60 and b - g > 40


def detect_active_tab(image, search_y: tuple[int, int] = (65, 140)):
    """Find the highlighted tab inside a page-top band (avoid header buttons)."""
    width, height = image.size
    pixels = image.convert("RGB").load()
    y_start = max(0, min(search_y[0], height - 1))
    y_end = max(y_start + 1, min(search_y[1], height))
    row_counts = []
    for y in range(y_start, y_end):
        count = 0
        for x in range(0, width, 2):
            if _blue(*pixels[x, y]):
                count += 1
        row_counts.append(count * 2)
    rows: list[tuple[int, int]] = []
    start = None
    for offset, count in enumerate(row_counts):
        y = y_start + offset
        if count >= 60 and start is None:
            start = y
        elif count < 60 and start is not None:
            if y - start >= 14:
                rows.append((start, y))
            start = None
    if start is not None and y_start + len(row_counts) - start >= 14:
        rows.append((start, y_start + len(row_counts)))
    if not rows:
        return None
    y1, y2 = max(rows, key=lambda run: run[1] - run[0])
    column_counts = []
    for x in range(width):
        column_counts.append(sum(1 for y in range(y1, y2) if _blue(*pixels[x, y])))
    threshold = max(3, int((y2 - y1) * 0.25))
    columns: list[tuple[int, int]] = []
    start = None
    for x, count in enumerate(column_counts):
        if count >= threshold and start is None:
            start = x
        elif count < threshold and start is not None:
            columns.append((start, x))
            start = None
    if start is not None:
        columns.append((start, width))
    if not columns:
        return None
    left, right = max(columns, key=lambda run: run[1] - run[0])
    if right - left < 20:
        return None
    return image.crop((max(0, left - 8), max(0, y1 - 4), min(width, right + 8), min(height, y2 + 4)))


def active_tab_strip(image):
    """Return the highlighted (blue) tab segment of a tab strip, or None."""
    width, height = image.size
    pixels = image.convert("RGB").load()
    counts = [0] * width
    for x in range(width):
        blue = 0
        for y in range(height):
            r, g, b = pixels[x, y]
            if b > 170 and b - r > 60 and b - g > 40:
                blue += 1
        counts[x] = blue
    threshold = max(2, int(height * 0.2))
    runs: list[tuple[int, int]] = []
    start = None
    for x, count in enumerate(counts):
        if count >= threshold and start is None:
            start = x
        elif count < threshold and start is not None:
            runs.append((start, x))
            start = None
    if start is not None:
        runs.append((start, width))
    if not runs:
        return None
    left, right = max(runs, key=lambda run: run[1] - run[0])
    if right - left < 15:
        return None
    return image.crop((max(0, left - 14), 0, min(width, right + 14), height))


def cluster_hashes(items: list[dict], threshold: int = 6) -> list[dict]:
    """Group items {"t": float, "hash": int} into near-identical clusters."""
    clusters: list[dict] = []
    for item in items:
        for cluster in clusters:
            if hamming(item["hash"], cluster["hash"]) <= threshold:
                cluster["members"].append(item["t"])
                break
        else:
            clusters.append({"hash": item["hash"], "t": item["t"], "members": [item["t"]]})
    return clusters


def cluster_frames(paths: list[Path], *, strip_ratio: tuple[float, float] = (0.14, 0.22),
                   threshold: int = 6, with_text: bool = False) -> list[dict]:
    """Cluster already-extracted frames by tab-strip similarity (no ffmpeg)."""
    from PIL import Image

    items: list[dict] = []
    strips: list = []
    for index, path in enumerate(paths):
        with Image.open(path) as image:
            image = image.convert("RGB")
            height = image.height
            y1 = int(height * strip_ratio[0])
            y2 = max(y1 + 1, int(height * strip_ratio[1]))
            strip = crop_strip(image, (y1, y2))
        strips.append(strip)
        items.append({"t": index, "hash": strip_hash(strip)})
    clusters = cluster_hashes(items, threshold)
    pages = []
    for cluster in clusters:
        first = next(i for i, item in enumerate(items) if item["t"] == cluster["t"])
        pages.append({
            "t": cluster["t"],
            "count": len(cluster["members"]),
            "text": ocr_text(strips[first]) if with_text and strips else "",
        })
    return pages


def build_pages(video: Path, out_dir: Path, *, fps: float = 0.5, per_sheet: int = 10,
                strip_y: tuple[int, int] = (150, 280), width: int = 1280,
                cluster_threshold: int = 6) -> dict:
    """Extract tab-strip sheets, unique-page sheet and cluster CSV."""
    from PIL import Image, ImageDraw, ImageFont

    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video), "-vf", f"fps={fps}", str(Path(tmp) / "f%05d.png"),
        ]
        subprocess.run(cmd, check=True)
        frames = sorted(Path(tmp).glob("f*.png"))
        records: list[dict] = []
        strips: list = []
        for index, frame in enumerate(frames):
            strip = crop_strip(Image.open(frame).convert("RGB"), strip_y).convert("RGB")
            strip = strip.resize((width, max(1, int(strip.height * width / strip.width))), Image.LANCZOS)
            strips.append(strip)
            records.append({"t": index / fps, "hash": strip_hash(strip)})

        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except OSError:
            font = ImageFont.load_default()

        def _label(t: float) -> str:
            return f"{int(t) // 60:02d}:{int(t) % 60:02d}"

        sheets: list[Path] = []
        for start in range(0, len(strips), per_sheet):
            chunk = strips[start:start + per_sheet]
            cell_h = max(s.height for s in chunk) + 22
            sheet = Image.new("RGB", (width, cell_h * len(chunk) + 6), (15, 15, 15))
            draw = ImageDraw.Draw(sheet)
            for i, strip in enumerate(chunk):
                t = (start + i) / fps
                sheet.paste(strip, (0, i * cell_h + 20))
                draw.text((4, i * cell_h + 3), f"frame {start + i:04d}  t={_label(t)}",
                          font=font, fill=(255, 220, 0))
            target = out_dir / f"tabs-{start // per_sheet + 1}.jpg"
            sheet.save(target, quality=90)
            sheets.append(target)

        clusters = cluster_hashes(records, cluster_threshold)
        cluster_rows = []
        for number, cluster in enumerate(clusters, 1):
            first = next(i for i, r in enumerate(records) if r["t"] == cluster["t"])
            active = active_tab_strip(strips[first])
            text = ocr_text(active) if active is not None else ""
            cluster_rows.append({
                "cluster": number,
                "first_time_s": round(cluster["t"], 1),
                "frames": len(cluster["members"]),
                "text": text,
            })

        csv_path = out_dir / "unique-pages.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["cluster", "first_time_s", "frames", "text"])
            writer.writeheader()
            writer.writerows(cluster_rows)

        unique_sheet = out_dir / "unique-pages.jpg"
        cell_h = max(s.height for s in strips) + 26
        sheet = Image.new("RGB", (width, cell_h * len(clusters) + 6), (15, 15, 15))
        draw = ImageDraw.Draw(sheet)
        for i, rows in enumerate(cluster_rows):
            first = next(j for j, r in enumerate(records) if r["t"] == clusters[i]["t"])
            sheet.paste(strips[first], (0, i * cell_h + 22))
            draw.text(
                (4, i * cell_h + 4),
                f"cluster {rows['cluster']}  t={_label(rows['first_time_s'])}  "
                f"frames={rows['frames']}  {rows['text']}",
                font=font,
                fill=(255, 220, 0),
            )
        sheet.save(unique_sheet, quality=90)
        return {
            "sheets": sheets,
            "unique_sheet": unique_sheet,
            "csv": csv_path,
            "clusters": cluster_rows,
        }


def _slug_from_filename(name: str) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", name)
    stem = re.sub(r"-v\d+$", "", stem)
    stem = re.sub(r"^\d+-", "", stem)
    return stem.strip()


def _tab_candidates(image, max_candidates: int = 4) -> list:
    """Crop candidate highlight rectangles from the page top (header + tab row)."""
    width, height = image.size
    pixels = image.convert("RGB").load()
    limit = min(200, height)
    row_counts = []
    for y in range(limit):
        count = sum(1 for x in range(0, width, 2) if _blue(*pixels[x, y])) * 2
        row_counts.append(count)
    bands = []
    start = None
    for y, count in enumerate(row_counts):
        if count >= 40 and start is None:
            start = y
        elif count < 40 and start is not None:
            if y - start >= 12:
                bands.append((start, y))
            start = None
    if start is not None and limit - start >= 12:
        bands.append((start, limit))
    crops = []
    for y1, y2 in bands[:max_candidates]:
        column_counts = []
        for x in range(width):
            column_counts.append(sum(1 for y in range(y1, y2) if _blue(*pixels[x, y])))
        threshold = max(2, int((y2 - y1) * 0.3))
        runs = []
        start = None
        for x, count in enumerate(column_counts):
            if count >= threshold and start is None:
                start = x
            elif count < threshold and start is not None:
                runs.append((start, x))
                start = None
        if start is not None:
            runs.append((start, width))
        if not runs:
            continue
        left, right = max(runs, key=lambda run: run[1] - run[0])
        if right - left < 30:
            continue
        crop = image.crop((max(0, left - 6), max(0, y1 - 3), min(width, right + 6), min(height, y2 + 3)))
        crop = crop.resize((max(1, crop.width * 2), max(1, crop.height * 2)), Image.LANCZOS)
        crops.append(crop)
    return crops


BLACKLIST = {"返回门户", "切换专题", "人员定位大屏", "安全管理大屏", "人员定位", "首页", "消息", "升级"}


def assign_page_ids(manifest_path: Path, images_dir: Path, *,
                    strip_y: tuple[int, int] = (55, 110), ocr_fn=None) -> dict:
    """OCR tab strips and write page_id into the manifest.

    page_id prefers OCR text that matches the curated filename slug; otherwise it
    falls back to the slug (the intent) and keeps OCR evidence in ``ocr_text`` for
    review. Unreadable images are marked ``needs-review``.
    """
    from PIL import Image

    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    images = data.get("images", data) if isinstance(data, dict) else data
    if not isinstance(images, list):
        raise ValueError("manifest must be a list or an object with an 'images' list")
    reader = ocr_fn or ocr_text
    assigned, fallback, suggestions = 0, [], []
    for item in images:
        if not isinstance(item, dict) or not item.get("file"):
            continue
        path = Path(images_dir) / item["file"]
        slug = _slug_from_filename(item["file"])
        if not path.is_file():
            item["page_id"] = slug or "needs-review"
            item["page_id_source"] = "filename"
            fallback.append(item["file"])
            continue
        with Image.open(path) as image:
            image = image.convert("RGB")
            candidates = _tab_candidates(image)
            strip = crop_strip(image, (strip_y[0], min(strip_y[1], image.height)))
            crops = candidates + [strip]
        texts: list[str] = []
        for crop in crops:
            raw = reader(crop)
            for token in raw.split(" / "):
                token = token.strip()
                if token and token not in BLACKLIST and token not in texts and 2 <= len(token) <= 12:
                    texts.append(token)
        item["page_id"] = slug or "needs-review"
        item["ocr_text"] = " / ".join(texts[:4])
        if not texts:
            item["page_id_source"] = "filename" if slug else "needs-review"
            fallback.append(item["file"])
        else:
            item["page_id_source"] = "filename+ocr"
            assigned += 1
        suggestions.append([item["file"], item["page_id"], item["page_id_source"], item["ocr_text"]])
    Path(manifest_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"assigned": assigned, "fallback": fallback, "total": len(images),
            "suggestions": suggestions}


def build_sheets(video: Path, out_dir: Path, **kwargs) -> list[Path]:
    """Backward-compatible wrapper returning only the tab contact sheets."""
    return build_pages(video, out_dir, **kwargs)["sheets"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", help="recording to scan")
    parser.add_argument("--out", help="output directory for sheets")
    parser.add_argument("--fps", type=float, default=0.5, help="sampling rate (default 0.5 = one frame per 2 s)")
    parser.add_argument("--per-sheet", type=int, default=10)
    parser.add_argument("--strip-y", default="150,280", help="tab strip band: y1,y2")
    parser.add_argument("--cluster-threshold", type=int, default=6, help="hamming distance for near-duplicate strips")
    parser.add_argument("--manifest", help="assign page ideas: path to assets/manifest.json")
    parser.add_argument("--images-dir", help="assign page ids: published images directory")
    parser.add_argument("--assign-strip-y", default="55,110", help="tab strip band inside published images")
    args = parser.parse_args(argv)

    if args.manifest and args.images_dir:
        y1, y2 = (int(v) for v in args.assign_strip_y.split(","))
        report = assign_page_ids(Path(args.manifest), Path(args.images_dir), strip_y=(y1, y2))
        csv_path = Path(args.manifest).parent / "page-id-suggestions.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["file", "page_id", "page_id_source", "ocr_text"])
            writer.writerows(report.pop("suggestions"))
        print(json.dumps({**report, "suggestions_csv": str(csv_path)}, ensure_ascii=False, indent=2))
        return 0

    if not args.video or not args.out:
        parser.error("either --video/--out (scan) or --manifest/--images-dir (assign) is required")
    y1, y2 = (int(v) for v in args.strip_y.split(","))
    pages = build_pages(Path(args.video), Path(args.out), fps=args.fps,
                        per_sheet=args.per_sheet, strip_y=(y1, y2),
                        cluster_threshold=args.cluster_threshold)
    for sheet in pages["sheets"]:
        print(sheet)
    print(f"unique_sheet: {pages['unique_sheet']}")
    print(f"cluster_csv: {pages['csv']}")
    print(f"unique_pages: {len(pages['clusters'])}")
    for cluster in pages["clusters"]:
        print(f"  cluster {cluster['cluster']}: first={int(cluster['first_time_s']) // 60:02d}:"
              f"{int(cluster['first_time_s']) % 60:02d} frames={cluster['frames']} text={cluster['text']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

