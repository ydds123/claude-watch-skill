"""Tests for the manual image quality gate."""
import json
from pathlib import Path

from PIL import Image

from scripts.check_images import check, collect_refs, render_title_sheet


def _make_image(path: Path, size: tuple[int, int]):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (240, 240, 240)).save(path)


def _write_doc(path: Path, refs: list[str]) -> None:
    lines = ["# Manual", ""]
    for ref in refs:
        lines += [f"![figure]({ref})", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def test_collect_refs_strips_angle_brackets(tmp_path: Path):
    doc = tmp_path / "m.md"
    doc.write_text(
        "![a](<assets/images/a.jpg>)\n![b](assets/images/b.jpg)", encoding="utf-8"
    )
    assert collect_refs(doc) == ["assets/images/a.jpg", "assets/images/b.jpg"]


def test_check_passes_for_large_images(tmp_path: Path):
    _make_image(tmp_path / "assets/images/a.jpg", (1600, 900))
    doc = tmp_path / "m.md"
    _write_doc(doc, ["assets/images/a.jpg"])
    report = check(doc, min_width=1400)
    assert report["ok"] is True
    assert report["images"][0]["width"] == 1600


def test_check_fails_for_small_and_missing_images(tmp_path: Path):
    _make_image(tmp_path / "assets/images/small.jpg", (800, 400))
    doc = tmp_path / "m.md"
    _write_doc(doc, ["assets/images/small.jpg", "assets/images/missing.jpg"])
    report = check(doc, min_width=1400)
    assert report["ok"] is False
    assert len(report["failures"]) == 2
    statuses = [item["status"] for item in report["images"]]
    assert statuses == ["fail", "missing"]


def test_render_title_sheet_writes_file(tmp_path: Path):
    _make_image(tmp_path / "assets/images/a.jpg", (1600, 900))
    doc = tmp_path / "m.md"
    _write_doc(doc, ["assets/images/a.jpg"])
    report = check(doc, min_width=1400)
    out = tmp_path / "gate" / "titles.jpg"
    render_title_sheet(report, out)
    assert out.is_file()


def _write_manifest(tmp_path: Path, ref: str, page_id: str | None) -> Path:
    entry = {"file": Path(ref).name}
    if page_id is not None:
        entry["page_id"] = page_id
    manifest = tmp_path / "assets" / "manifest.json"
    manifest.write_text(
        json.dumps({"images": [entry]}, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def _write_doc_with_caption(path: Path, caption: str, ref: str) -> None:
    path.write_text(f"# Manual\n\n![{caption}]({ref})\n", encoding="utf-8")


def test_caption_matching_page_id_has_no_warning(tmp_path: Path):
    _make_image(tmp_path / "assets/images/a.jpg", (1600, 900))
    manifest = _write_manifest(tmp_path, "assets/images/a.jpg", "风险分析对象 / 新增")
    doc = tmp_path / "m.md"
    _write_doc_with_caption(doc, "风险分析对象新增", "assets/images/a.jpg")
    report = check(doc, min_width=1400, manifest=manifest)
    assert report["ok"] is True
    assert report["warnings"] == []
    assert report["images"][0]["caption_matches_page_id"] is True


def test_caption_mismatch_warns(tmp_path: Path):
    _make_image(tmp_path / "assets/images/a.jpg", (1600, 900))
    manifest = _write_manifest(tmp_path, "assets/images/a.jpg", "风险分析单元")
    doc = tmp_path / "m.md"
    _write_doc_with_caption(doc, "隐患治理", "assets/images/a.jpg")
    report = check(doc, min_width=1400, manifest=manifest)
    assert report["ok"] is True
    assert any("caption may not match" in warning for warning in report["warnings"])


def test_ocr_evidence_mismatch_warns(tmp_path: Path):
    _make_image(tmp_path / "assets/images/a.jpg", (1600, 900))
    manifest = _write_manifest(tmp_path, "assets/images/a.jpg", "风险分析对象")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["images"][0]["ocr_text"] = "隐患治理 / 排查内容"
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    doc = tmp_path / "m.md"
    _write_doc_with_caption(doc, "风险分析对象", "assets/images/a.jpg")
    report = check(doc, min_width=1400, manifest=manifest, ocr_check=True)
    assert report["ok"] is True
    assert any("OCR evidence does not support" in warning for warning in report["warnings"])


def test_require_page_id_fails_when_missing(tmp_path: Path):
    _make_image(tmp_path / "assets/images/a.jpg", (1600, 900))
    manifest = _write_manifest(tmp_path, "assets/images/a.jpg", None)
    doc = tmp_path / "m.md"
    _write_doc_with_caption(doc, "示例", "assets/images/a.jpg")
    report = check(doc, min_width=1400, manifest=manifest, require_page_id=True)
    assert report["ok"] is False
    assert any("no page_id" in failure for failure in report["failures"])
