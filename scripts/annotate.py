"""Finishing ops for external-facing product-manual screenshots.

Crop away desktop chrome, mask internal information, and draw reproducible
callouts (red boxes, numbered badges, arrows, labels, zoomed insets) on top of
captured screenshots.

Only Pillow is required.  Every operation is described by a JSON spec so the
same annotation can be replayed after a screenshot is re-captured.

Spec format::

    {
      "defaults": {"color": [229, 57, 46], "width": 3, "font_size": 24},
      "jobs": [
        {
          "src": "raw/01.png",
          "out": "final/01.png",
          "ops": [
            {"op": "crop", "mode": "bbox", "threshold": 24, "trim_bottom": 30},
            {"op": "box", "rect": [10, 20, 200, 80], "badge": "1"},
            {"op": "arrow", "from": [280, 60], "to": [212, 50]},
            {"op": "label", "at": [300, 60], "text": "click here"},
            {"op": "inset", "rect": [10, 20, 120, 60], "scale": 2, "at": [700, 20]},
            {"op": "mask", "rect": [0, 0, 900, 40], "mode": "blur"},
            {"op": "scale", "factor": 1.5}
          ]
        }
      ]
    }

Supported ops:

============================  =================================================
``crop``                      ``mode``: ``bbox`` (non-background bounds) or
                              ``rect``; ``trim_bottom``/``trim_top`` pixels;
                              ``pad`` pixels around the result.
``scale``                     ``factor`` (LANCZOS).
``mask``                      ``mode``: ``solid`` | ``blur`` | ``pixelate``.
``box``                       Rounded outline, optional translucent fill and a
                              numbered badge on the top-left corner.
``arrow``                     Straight arrow with a triangular head.
``label``                     Short text with an optional badge; ``bg`` adds a
                              rounded background for light screenshots.
``inset``                     Copy of a region, enlarged and pasted back as a
                              zoomed inset with a border.
============================  =================================================
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

RED = (229, 57, 46)
DEFAULT_STYLE = {
    "color": list(RED),
    "width": 3,
    "radius": 8,
    "fill_alpha": 0,
    "font_size": 24,
    "badge_radius": 13,
    "badge_font_size": 22,
}

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

_font_cache: dict[int, ImageFont.FreeTypeFont] = {}


class AnnotateError(ValueError):
    """Raised for an invalid op or spec."""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load the first available bold CJK-capable font at ``size``."""
    if size in _font_cache:
        return _font_cache[size]
    for candidate in _FONT_CANDIDATES:
        path = Path(candidate)
        if not path.is_file():
            continue
        try:
            font = ImageFont.truetype(str(path), size)
        except OSError:  # pragma: no cover - broken font file
            continue
        _font_cache[size] = font
        return font
    font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def parse_color(value, default_alpha: int = 255) -> tuple[int, int, int, int]:
    """Accept ``[r, g, b]`` or ``[r, g, b, a]`` and return an RGBA tuple."""
    if value is None:
        return (*RED, default_alpha)
    if not isinstance(value, (list, tuple)) or len(value) not in (3, 4):
        raise AnnotateError(f"color must be [r, g, b] or [r, g, b, a], got {value!r}")
    channels = [int(v) for v in value]
    if any(c < 0 or c > 255 for c in channels):
        raise AnnotateError(f"color channels must be 0..255, got {value!r}")
    if len(channels) == 3:
        channels.append(default_alpha)
    return tuple(channels)  # type: ignore[return-value]


def _clamp_rect(rect, size: tuple[int, int]) -> tuple[int, int, int, int]:
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        raise AnnotateError(f"rect must be [x1, y1, x2, y2], got {rect!r}")
    x1, y1, x2, y2 = (int(v) for v in rect)
    width, height = size
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(width, x2), min(height, y2)
    if x2 - x1 < 1 or y2 - y1 < 1:
        raise AnnotateError(f"rect {rect!r} is empty after clamping to {size}")
    return x1, y1, x2, y2


def _num(value, name: str, *, minimum: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AnnotateError(f"{name} must be numeric, got {value!r}") from exc
    if number < minimum:
        raise AnnotateError(f"{name} must be >= {minimum}, got {number}")
    return number


def _composite(img: Image.Image, overlay: Image.Image) -> Image.Image:
    """Blend an RGBA overlay onto the current RGB image."""
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _draw_badge(draw: ImageDraw.ImageDraw, center, text: str, style: dict) -> None:
    radius = int(style["badge_radius"])
    cx, cy = center
    color = parse_color(style["color"])
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color)
    font = load_font(int(style["badge_font_size"]))
    draw.text((cx, cy - 1), str(text), font=font, fill="white", anchor="mm")


def _draw_arrow(
    draw: ImageDraw.ImageDraw, start, end, color, width: float, head: float
) -> None:
    draw.line([start, end], fill=color, width=int(width))
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    for direction in (0.45, -0.45):
        tip = (
            end[0] - head * math.cos(angle - direction),
            end[1] - head * math.sin(angle - direction),
        )
        draw.line([end, tip], fill=color, width=int(width))


# --------------------------------------------------------------------------- #
# ops
# --------------------------------------------------------------------------- #
def _resolve_style(op: dict, defaults: dict) -> dict:
    style = {**DEFAULT_STYLE, **defaults}
    style.update({k: v for k, v in op.items() if k in DEFAULT_STYLE})
    style["color"] = list(parse_color(style.get("color"))[:3])
    return style


def op_crop(img: Image.Image, op: dict) -> Image.Image:
    mode = op.get("mode", "bbox")
    if mode == "rect":
        box = _clamp_rect(op.get("rect"), img.size)
    elif mode == "bbox":
        threshold = int(op.get("threshold", 24))
        background = img.getpixel((0, 0))
        if isinstance(background, int):
            background = (background, background, background)
        background = tuple(background[:3])
        filled = Image.new("RGB", img.size, background)
        mask = (
            ImageChops.difference(img.convert("RGB"), filled)
            .convert("L")
            .point(lambda pixel: 255 if pixel > threshold else 0)
        )
        box = mask.getbbox()
        if box is None:
            raise AnnotateError("crop bbox: image is a single solid color")
    else:
        raise AnnotateError(f"crop mode must be 'bbox' or 'rect', got {mode!r}")

    x1, y1, x2, y2 = box
    y1 = min(y2 - 1, y1 + int(op.get("trim_top", 0)))
    y2 = max(y1 + 1, y2 - int(op.get("trim_bottom", 0)))
    pad = int(op.get("pad", 0))
    x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
    x2, y2 = min(img.width, x2 + pad), min(img.height, y2 + pad)
    return img.crop((x1, y1, x2, y2))


def op_scale(img: Image.Image, op: dict) -> Image.Image:
    factor = _num(op.get("factor"), "scale.factor", minimum=0.05)
    return img.resize(
        (max(1, round(img.width * factor)), max(1, round(img.height * factor))),
        Image.LANCZOS,
    )


def op_mask(img: Image.Image, op: dict) -> Image.Image:
    x1, y1, x2, y2 = _clamp_rect(op.get("rect"), img.size)
    region = img.crop((x1, y1, x2, y2))
    mode = op.get("mode", "solid")
    if mode == "solid":
        color = parse_color(op.get("color"), default_alpha=255)
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rectangle([x1, y1, x2, y2], fill=color)
        return _composite(img, overlay)
    if mode == "blur":
        radius = _num(op.get("radius", 12), "mask.radius", minimum=0.1)
        img.paste(region.filter(ImageFilter.GaussianBlur(radius)), (x1, y1))
        return img
    if mode == "pixelate":
        block = max(2, int(op.get("block", 8)))
        tiny = region.resize(
            (max(1, region.width // block), max(1, region.height // block)), Image.NEAREST
        )
        img.paste(tiny.resize(region.size, Image.NEAREST), (x1, y1))
        return img
    raise AnnotateError(f"mask mode must be solid|blur|pixelate, got {mode!r}")


def op_box(img: Image.Image, op: dict, defaults: dict) -> Image.Image:
    style = _resolve_style(op, defaults)
    x1, y1, x2, y2 = _clamp_rect(op.get("rect"), img.size)
    offset = int(op.get("offset", 4))
    rect = [x1 - offset, y1 - offset, x2 + offset, y2 + offset]
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    color = parse_color(style["color"])
    fill_alpha = int(op.get("fill_alpha", style.get("fill_alpha", 0)))
    if fill_alpha:
        draw.rounded_rectangle(
            rect, radius=int(style["radius"]), fill=(*color[:3], fill_alpha)
        )
    draw.rounded_rectangle(
        rect,
        radius=int(style["radius"]),
        outline=color,
        width=int(style["width"]),
    )
    img = _composite(img, overlay)
    if op.get("badge") is not None:
        _draw_badge(ImageDraw.Draw(img), (rect[0], rect[1]), str(op["badge"]), style)
    return img


def op_arrow(img: Image.Image, op: dict, defaults: dict) -> Image.Image:
    style = _resolve_style(op, defaults)
    color = parse_color(op.get("color"))
    start, end = op.get("from"), op.get("to")
    if not start or not end or len(start) != 2 or len(end) != 2:
        raise AnnotateError("arrow needs 'from' and 'to' as [x, y]")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    _draw_arrow(
        ImageDraw.Draw(overlay),
        (int(start[0]), int(start[1])),
        (int(end[0]), int(end[1])),
        color,
        _num(op.get("width", style["width"]), "arrow.width", minimum=1),
        _num(op.get("head", 14), "arrow.head", minimum=1),
    )
    return _composite(img, overlay)


def op_label(img: Image.Image, op: dict, defaults: dict) -> Image.Image:
    style = _resolve_style(op, defaults)
    text = str(op.get("text", "")).strip()
    if not text:
        raise AnnotateError("label needs non-empty 'text'")
    at = op.get("at")
    if not at or len(at) != 2:
        raise AnnotateError("label needs 'at' as [x, y]")
    size = int(op.get("size", style["font_size"]))
    font = load_font(size)
    color = parse_color(op.get("color"), default_alpha=255)
    x, y = int(at[0]), int(at[1])
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    text_x = x
    if op.get("badge") is not None:
        _draw_badge(draw, (x + int(style["badge_radius"]), y), str(op["badge"]), style)
        text_x = x + int(style["badge_radius"]) * 2 + 6
    bbox = draw.textbbox((text_x, y), text, font=font, anchor="lm")
    pad = int(op.get("bg_pad", 8))
    bg = op.get("bg")
    if bg:
        draw.rounded_rectangle(
            [bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad],
            radius=6,
            fill=parse_color(bg),
        )
    draw.text((text_x, y), text, font=font, fill=color, anchor="lm")
    return _composite(img, overlay)


def op_inset(img: Image.Image, op: dict, defaults: dict) -> Image.Image:
    style = _resolve_style(op, defaults)
    x1, y1, x2, y2 = _clamp_rect(op.get("rect"), img.size)
    factor = _num(op.get("scale", 2.0), "inset.scale", minimum=0.1)
    zoomed = img.crop((x1, y1, x2, y2)).resize(
        (max(1, round((x2 - x1) * factor)), max(1, round((y2 - y1) * factor))),
        Image.LANCZOS,
    )
    at = op.get("at")
    if not at or len(at) != 2:
        raise AnnotateError("inset needs 'at' as [x, y]")
    ax, ay = int(at[0]), int(at[1])
    border = int(op.get("border", 3))
    color = parse_color(op.get("color", style["color"]))
    canvas = img.convert("RGBA")
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [ax - 4, ay - 4, ax + zoomed.width + 4, ay + zoomed.height + 4],
        radius=8,
        fill=(0, 0, 0, 70),
    )
    canvas.alpha_composite(shadow)
    canvas.paste(zoomed.convert("RGBA"), (ax, ay))
    ImageDraw.Draw(canvas).rounded_rectangle(
        [ax - border, ay - border, ax + zoomed.width + border, ay + zoomed.height + border],
        radius=6,
        outline=color,
        width=border,
    )
    return canvas.convert("RGB")


_OPS = {
    "crop": op_crop,
    "scale": op_scale,
    "mask": op_mask,
}


def apply_ops(img: Image.Image, ops: list[dict], defaults: dict | None = None) -> Image.Image:
    """Apply every op in order and return the finished image."""
    defaults = {**DEFAULT_STYLE, **(defaults or {})}
    if not isinstance(ops, list):
        raise AnnotateError("ops must be a list")
    current = img.convert("RGB")
    for index, op in enumerate(ops, 1):
        if not isinstance(op, dict) or "op" not in op:
            raise AnnotateError(f"op #{index} must be an object with an 'op' key")
        name = op["op"]
        try:
            if name in _OPS:
                current = _OPS[name](current, op)
            elif name == "box":
                current = op_box(current, op, defaults)
            elif name == "arrow":
                current = op_arrow(current, op, defaults)
            elif name == "label":
                current = op_label(current, op, defaults)
            elif name == "inset":
                current = op_inset(current, op, defaults)
            else:
                raise AnnotateError(f"unknown op {name!r}")
        except AnnotateError as exc:
            raise AnnotateError(f"op #{index} ({name}): {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - surface a usable message
            raise AnnotateError(f"op #{index} ({name}) failed: {exc}") from exc
    return current


def _write_qa_crops(image: Image.Image, ops: list[dict], out_path: Path) -> list[str]:
    """Zoom every ``box`` op so a human/model can verify the callout alignment."""
    boxes = [
        op
        for op in ops
        if isinstance(op, dict) and op.get("op") == "box" and op.get("rect")
    ]
    if not boxes:
        return []
    qa_dir = out_path.parent / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for index, op in enumerate(boxes, 1):
        x1, y1, x2, y2 = _clamp_rect(op["rect"], image.size)
        pad = 40
        region = (
            max(0, x1 - pad),
            max(0, y1 - pad),
            min(image.width, x2 + pad),
            min(image.height, y2 + pad),
        )
        crop = image.crop(region)
        scale = min(4.0, 1000 / crop.width)
        if scale > 1:
            crop = crop.resize(
                (max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
                Image.LANCZOS,
            )
        target = qa_dir / f"{out_path.stem}-qa{index}.png"
        crop.save(target)
        written.append(str(target))
    return written


def run_spec(
    spec: dict, base_dir: Path | None = None, qa: bool = False
) -> list[dict]:
    """Apply a full spec and write every job's output. Returns a summary list.

    With ``qa=True`` every ``box`` callout also produces a zoomed crop under
    ``<output-dir>/qa/`` so the annotation alignment can be checked before the
    image is published.
    """
    base = Path(base_dir) if base_dir else Path.cwd()
    defaults = spec.get("defaults") or {}
    jobs = spec.get("jobs")
    if not jobs:
        raise AnnotateError("spec has no 'jobs'")
    results: list[dict] = []
    for index, job in enumerate(jobs, 1):
        src = (base / job["src"]) if not Path(job["src"]).is_absolute() else Path(job["src"])
        out = (base / job["out"]) if not Path(job["out"]).is_absolute() else Path(job["out"])
        if not src.is_file():
            raise AnnotateError(f"job #{index}: source not found: {src}")
        image = Image.open(src)
        ops = job.get("ops") or []
        finished = apply_ops(image, ops, defaults)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix.lower() in (".jpg", ".jpeg"):
            finished.save(out, quality=92, subsampling=1)
        else:
            finished.save(out)
        record = {"job": index, "src": str(src), "out": str(out), "size": list(finished.size)}
        if qa:
            record["qa"] = _write_qa_crops(finished, ops, out)
        results.append(record)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="annotate",
        description="Crop, mask and annotate product-manual screenshots from a JSON spec.",
    )
    parser.add_argument("spec", help="path to the JSON spec")
    parser.add_argument(
        "--qa",
        action="store_true",
        help="also write zoomed crops of every box callout under <out>/qa/ for alignment review",
    )
    args = parser.parse_args(argv)
    spec_path = Path(args.spec).resolve()
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        results = run_spec(spec, base_dir=spec_path.parent, qa=args.qa)
    except (OSError, json.JSONDecodeError, AnnotateError) as exc:
        print(f"annotate: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "jobs": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
