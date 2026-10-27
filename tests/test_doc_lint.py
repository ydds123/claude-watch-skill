import hashlib
import json
from pathlib import Path

from scripts.doc_lint import lint, main


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path, *, versioned: bool = True, page_id: str | None = "风险分析对象"):
    from PIL import Image

    images = tmp_path / "assets" / "images"
    images.mkdir(parents=True)
    name = "01-示例-v3.jpg" if versioned else "01-示例.jpg"
    image = images / name
    Image.new("RGB", (40, 30), (200, 210, 220)).save(image, "JPEG")
    manifest = {
        "version": "v3",
        "images": [{
            "file": name,
            "sha256": _sha(image),
            "page_id": page_id,
        }],
    }
    manifest_path = tmp_path / "assets" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    doc = tmp_path / "manual.md"
    doc.write_text(f"# 手册\n\n![示例](assets/images/{name})\n", encoding="utf-8")
    return doc, manifest_path, images


def test_lint_passes_for_matching_manifest(tmp_path):
    doc, manifest, images = _fixture(tmp_path)
    report = lint(doc, manifest, images, require_versioned=True, require_page_id=True)
    assert report["ok"] is True
    assert report["checked"] == 1
    assert report["failures"] == []


def test_lint_fails_on_missing_file(tmp_path):
    doc, manifest, images = _fixture(tmp_path)
    (images / "01-示例-v3.jpg").unlink()
    report = lint(doc, manifest, images)
    assert report["ok"] is False
    assert any("missing image" in f for f in report["failures"])


def test_lint_fails_on_sha_mismatch(tmp_path):
    from PIL import Image

    doc, manifest, images = _fixture(tmp_path)
    Image.new("RGB", (40, 30), (10, 10, 10)).save(images / "01-示例-v3.jpg", "JPEG")
    report = lint(doc, manifest, images)
    assert report["ok"] is False
    assert any("sha256 mismatch" in f for f in report["failures"])


def test_lint_requires_versioned_names(tmp_path):
    doc, manifest, images = _fixture(tmp_path, versioned=False)
    report = lint(doc, manifest, images, require_versioned=True)
    assert report["ok"] is False
    assert any("not versioned" in f for f in report["failures"])


def test_lint_requires_page_id(tmp_path):
    doc, manifest, images = _fixture(tmp_path, page_id=None)
    report = lint(doc, manifest, images, require_page_id=True)
    assert report["ok"] is False
    assert any("page_id" in f for f in report["failures"])


def test_lint_warns_on_unreferenced_manifest_image(tmp_path):
    doc, manifest, images = _fixture(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["images"].append({"file": "09-未引用-v3.jpg", "sha256": "abc"})
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    report = lint(doc, manifest, images)
    assert report["ok"] is True
    assert any("not referenced" in w for w in report["warnings"])


def test_main_writes_report_and_exit_code(tmp_path):
    doc, manifest, images = _fixture(tmp_path)
    report_path = tmp_path / "doc-lint.json"
    code = main([
        "--doc", str(doc),
        "--manifest", str(manifest),
        "--images-dir", str(images),
        "--require-versioned",
        "--require-page-id",
        "--report-out", str(report_path),
    ])
    assert code == 0
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["ok"] is True


def _annotations(tmp_path: Path, ops: list[dict]) -> Path:
    path = tmp_path / "manual.json"
    path.write_text(
        json.dumps({"jobs": [{"out": "../images/01-示例-v3.jpg", "ops": ops}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_annotation_policy_passes(tmp_path):
    doc, manifest, images = _fixture(tmp_path)
    ann = _annotations(tmp_path, [
        {"op": "box", "rect": [1, 2, 3, 4], "badge": "1"},
        {"op": "label", "text": "新增对象", "badge": "1"},
    ])
    report = lint(doc, manifest, images, annotations=ann)
    assert report["ok"] is True
    assert report["failures"] == []


def test_annotation_badges_must_be_consecutive(tmp_path):
    doc, manifest, images = _fixture(tmp_path)
    ann = _annotations(tmp_path, [
        {"op": "box", "rect": [1, 2, 3, 4], "badge": "2"},
        {"op": "label", "text": "新增对象", "badge": "2"},
    ])
    report = lint(doc, manifest, images, annotations=ann)
    assert report["ok"] is False
    assert any("not consecutive" in failure for failure in report["failures"])


def test_annotation_requires_label(tmp_path):
    doc, manifest, images = _fixture(tmp_path)
    ann = _annotations(tmp_path, [{"op": "box", "rect": [1, 2, 3, 4], "badge": "1"}])
    report = lint(doc, manifest, images, annotations=ann)
    assert report["ok"] is False
    assert any("has no label" in failure for failure in report["failures"])


def test_annotation_callout_limit(tmp_path):
    doc, manifest, images = _fixture(tmp_path)
    ann = _annotations(tmp_path, [
        {"op": "box", "rect": [i, i, i + 1, i + 1], "badge": str(i)}
        for i in (1, 2, 3, 4)
    ] + [{"op": "label", "text": "新增对象", "badge": str(i)} for i in (1, 2, 3, 4)])
    report = lint(doc, manifest, images, annotations=ann)
    assert report["ok"] is False
    assert any("exceeds policy limit" in failure for failure in report["failures"])


def test_external_mode_rejects_acceptance_checklist(tmp_path):
    doc, manifest, images = _fixture(tmp_path)
    doc.write_text(
        "### 2.6 验收检查表\n\n| 验收场景 | 预期结果 |\n|---|---|\n",
        encoding="utf-8",
    )
    report = lint(doc, manifest, images, external=True)
    assert report["ok"] is False
    assert any("acceptance checklist" in failure for failure in report["failures"])
