"""Document-level lint for evidence-backed manuals.

Checks a Markdown document against its image manifest:
- every referenced image exists;
- every referenced image has a manifest entry with a matching sha256;
- references are versioned (filename carries `-vN`) when required;
- manifest entries carry `page_id` when required;
- manifest images that are never referenced are reported as warnings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

IMAGE_REF = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
VERSIONED = re.compile(r"-v\d+\.[A-Za-z0-9]+$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest(path: Path | None) -> dict[str, dict]:
    if path is None or not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    images = data.get("images", data) if isinstance(data, dict) else data
    if not isinstance(images, list):
        raise ValueError("manifest must be a list or an object with an 'images' list")
    entries: dict[str, dict] = {}
    for item in images:
        if isinstance(item, dict) and item.get("file"):
            entries[Path(str(item["file"])).name] = item
    return entries


def _load_annotations(path: Path | None) -> dict[str, dict]:
    if path is None or not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    entries: dict[str, dict] = {}
    for job in jobs:
        if not isinstance(job, dict) or not job.get("out"):
            continue
        entries[Path(str(job["out"])).name] = job
    return entries


def lint_annotations(entries: dict[str, dict], referenced: set[str]) -> tuple[list[str], list[str]]:
    """Validate callout policy: consecutive badges, ≤3 boxes, 2–8 char labels."""
    failures: list[str] = []
    warnings: list[str] = []
    for name, job in entries.items():
        ops = job.get("ops", [])
        badges = []
        labels: dict[str, str] = {}
        for op in ops:
            if not isinstance(op, dict):
                continue
            if op.get("op") == "box" and op.get("badge") is not None:
                badges.append(str(op["badge"]))
            if op.get("op") == "label" and op.get("badge") is not None:
                labels[str(op["badge"])] = str(op.get("text", "")).strip()
        if name not in referenced:
            warnings.append(f"annotation job not referenced in document: {name}")
        if badges:
            numbers = sorted(int(b) for b in badges if str(b).isdigit())
            if numbers != list(range(1, len(numbers) + 1)):
                failures.append(f"{name}: callout badges are not consecutive from 1 ({numbers})")
            if len(badges) > 3:
                failures.append(f"{name}: {len(badges)} callouts exceeds policy limit of 3")
            elif len(badges) > 2:
                warnings.append(f"{name}: more than 2 callouts ({len(badges)})")
            for badge in badges:
                text = labels.get(badge, "")
                if not text:
                    failures.append(f"{name}: callout {badge} has no label")
                elif not (2 <= len(text) <= 8):
                    failures.append(f"{name}: callout {badge} label length {len(text)} not in 2–8")
    for name in referenced - set(entries):
        warnings.append(f"no annotation job for referenced image: {name}")
    return failures, warnings


def lint(
    doc: Path,
    manifest: Path | None,
    images_dir: Path | None,
    *,
    require_versioned: bool = False,
    require_page_id: bool = False,
    annotations: Path | None = None,
    external: bool = False,
) -> dict:
    doc_dir = doc.parent
    text = doc.read_text(encoding="utf-8")
    refs = [ref.strip() for ref in IMAGE_REF.findall(text) if not ref.startswith(("http://", "https://"))]
    entries = _load_manifest(manifest)
    failures: list[str] = []
    warnings: list[str] = []

    if external:
        for number, line in enumerate(text.splitlines(), 1):
            if re.match(r"^#{1,6}\s*.*验收检查表", line) or "验收场景" in line:
                failures.append(
                    f"external manual must not include acceptance checklist content (line {number})"
                )

    seen: dict[str, int] = {}
    for ref in refs:
        path = (doc_dir / ref.replace("\\", "/")).resolve()
        name = path.name
        seen[name] = seen.get(name, 0) + 1
        if not path.is_file():
            failures.append(f"missing image: {ref}")
            continue
        if require_versioned and not VERSIONED.search(name):
            failures.append(f"image not versioned: {ref}")
        entry = entries.get(name)
        if manifest is not None:
            if entry is None:
                warnings.append(f"not in manifest: {ref}")
            else:
                digest = _sha256(path)
                if entry.get("sha256") and not digest.startswith(str(entry["sha256"])):
                    failures.append(f"sha256 mismatch: {ref}")
                if require_page_id and not entry.get("page_id"):
                    failures.append(f"missing page_id in manifest: {ref}")
    for name, count in seen.items():
        if count > 1:
            warnings.append(f"referenced {count} times: {name}")

    if manifest is not None:
        for name in entries:
            if name not in seen:
                warnings.append(f"manifest image not referenced: {name}")

    if images_dir is not None and images_dir.is_dir():
        versioned_files = {p.name for p in images_dir.glob("*") if p.is_file() and "-v" in p.name}
        for name in versioned_files - set(seen):
            warnings.append(f"unreferenced versioned image on disk: {name}")

    if annotations is not None:
        ann_failures, ann_warnings = lint_annotations(
            _load_annotations(annotations), {Path(ref).name for ref in refs}
        )
        failures.extend(ann_failures)
        warnings.extend(ann_warnings)

    return {
        "ok": not failures,
        "doc": str(doc),
        "checked": len(refs),
        "failures": failures,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint a manual document against its image manifest.")
    parser.add_argument("--doc", required=True, help="Markdown document")
    parser.add_argument("--manifest", default=None, help="assets/manifest.json")
    parser.add_argument("--images-dir", default=None, help="assets/images directory")
    parser.add_argument("--require-versioned", action="store_true", help="filename must carry -vN")
    parser.add_argument("--require-page-id", action="store_true", help="manifest must carry page_id")
    parser.add_argument("--annotations", default=None, help="annotation spec JSON (assets/annotations/*.json)")
    parser.add_argument("--external", action="store_true", help="enforce external-manual structure (no acceptance checklists)")
    parser.add_argument("--report-out", default=None, help="write JSON report")
    args = parser.parse_args(argv)

    report = lint(
        Path(args.doc),
        Path(args.manifest) if args.manifest else None,
        Path(args.images_dir) if args.images_dir else None,
        require_versioned=args.require_versioned,
        require_page_id=args.require_page_id,
        annotations=Path(args.annotations) if args.annotations else None,
        external=args.external,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report_out:
        Path(args.report_out).write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
