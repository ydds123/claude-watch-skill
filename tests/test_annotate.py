"""Tests for the screenshot finishing ops used by external manuals."""
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from scripts.annotate import (
    AnnotateError,
    apply_ops,
    op_crop,
    op_mask,
    run_spec,
)

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
BLUE = (0, 0, 255)


def _blank(size=(120, 100), color=WHITE):
    return Image.new("RGB", size, color)


def _is_red(pixel, tolerance=40):
    r, g, b = pixel[:3]
    return r > 180 and g < 120 and b < 120


def test_crop_bbox_removes_uniform_border():
    img = _blank(color=BLACK)
    img.paste(BLUE, (20, 10, 80, 60))
    cropped = op_crop(img, {"op": "crop", "mode": "bbox"})
    assert cropped.size == (60, 50)


def test_crop_bbox_trims_bottom_chrome():
    img = _blank(color=BLACK)
    img.paste(BLUE, (20, 10, 80, 60))
    cropped = op_crop(img, {"op": "crop", "mode": "bbox", "trim_bottom": 10})
    assert cropped.size == (60, 40)


def test_crop_rect_mode_uses_explicit_box():
    cropped = op_crop(_blank(), {"op": "crop", "mode": "rect", "rect": [10, 20, 60, 70], "pad": 2})
    assert cropped.size == (54, 54)


def test_mask_solid_covers_region_exactly():
    img = _blank(color=WHITE)
    out = op_mask(img, {"op": "mask", "rect": [10, 10, 30, 30], "mode": "solid", "color": [0, 0, 255]})
    assert out.getpixel((20, 20)) == BLUE
    assert out.getpixel((5, 40)) == WHITE


def test_mask_blur_changes_region_but_keeps_size():
    img = Image.new("RGB", (80, 80), WHITE)
    img.paste(BLACK, (20, 30, 60, 40))
    out = op_mask(img, {"op": "mask", "rect": [20, 20, 60, 50], "mode": "blur", "radius": 6})
    assert out.size == img.size
    # Near the black stripe the blurred pixel is a grey blend, neither pure colour.
    assert out.getpixel((40, 24)) not in (WHITE, BLACK)


def test_box_draws_callout_border():
    img = _blank(color=WHITE)
    out = apply_ops(img, [{"op": "box", "rect": [20, 20, 60, 60]}])
    assert _is_red(out.getpixel((17, 40)))
    assert out.size == img.size


def test_arrow_changes_pixels_near_line():
    img = _blank(size=(100, 60))
    out = apply_ops(img, [{"op": "arrow", "from": [10, 30], "to": [80, 30]}])
    assert any(_is_red(out.getpixel((x, 30))) for x in range(30, 70))


def test_label_with_badge_renders():
    img = _blank(size=(200, 80))
    out = apply_ops(
        img,
        [{"op": "label", "at": [20, 40], "text": "click here", "badge": "1", "size": 20}],
    )
    assert ImageChops.difference(img, out).getbbox() is not None


def test_inset_pastes_enlarged_region():
    img = _blank(color=WHITE)
    img.paste(BLUE, (10, 10, 20, 20))
    out = apply_ops(
        img, [{"op": "inset", "rect": [10, 10, 20, 20], "scale": 3, "at": [50, 50]}]
    )
    assert out.size == img.size
    assert out.getpixel((55, 55)) == BLUE


def test_scale_op_resizes_canvas():
    out = apply_ops(_blank(size=(40, 20)), [{"op": "scale", "factor": 2}])
    assert out.size == (80, 40)


def test_unknown_op_is_rejected_with_context():
    with pytest.raises(AnnotateError, match="unknown op"):
        apply_ops(_blank(), [{"op": "sparkle"}])


def test_invalid_rect_is_rejected():
    with pytest.raises(AnnotateError, match="rect"):
        apply_ops(_blank(), [{"op": "crop", "mode": "rect", "rect": [500, 500, 600, 600]}])


def test_run_spec_writes_qa_crops_for_boxes(tmp_path: Path):
    src = tmp_path / "raw.png"
    image = _blank(color=WHITE)
    image.save(src)
    spec = {
        "jobs": [
            {
                "src": "raw.png",
                "out": "final/out.png",
                "ops": [{"op": "box", "rect": [20, 20, 60, 60], "badge": "1"}],
            }
        ]
    }
    results = run_spec(spec, base_dir=tmp_path, qa=True)
    qa_files = list((tmp_path / "final" / "qa").glob("*-qa1.png"))
    assert qa_files and results[0]["qa"] == [str(qa_files[0])]


def test_run_spec_writes_output_files(tmp_path: Path):
    src = tmp_path / "raw.png"
    image = _blank(color=BLACK)
    image.paste(BLUE, (5, 5, 25, 25))
    image.save(src)
    spec = {
        "defaults": {"color": [229, 57, 46], "width": 2},
        "jobs": [
            {
                "src": "raw.png",
                "out": "final/out.png",
                "ops": [
                    {"op": "crop", "mode": "bbox"},
                    {"op": "box", "rect": [0, 0, 10, 10], "badge": "1"},
                ],
            }
        ],
    }
    results = run_spec(spec, base_dir=tmp_path)
    out = tmp_path / "final" / "out.png"
    assert out.is_file()
    assert results[0]["size"] == [20, 20]
