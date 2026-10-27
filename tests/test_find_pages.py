from PIL import Image

from scripts.find_pages import (
    active_tab_strip,
    assign_page_ids,
    cluster_frames,
    cluster_hashes,
    crop_strip,
    detect_active_tab,
    hamming,
    strip_hash,
)


def test_crop_strip_returns_tab_band():
    image = Image.new("RGB", (640, 400), (255, 255, 255))
    strip = crop_strip(image, (100, 180))
    assert strip.size == (640, 80)


def test_crop_strip_clamps_to_image_height():
    image = Image.new("RGB", (320, 120), (255, 255, 255))
    strip = crop_strip(image, (100, 300))
    assert strip.size == (320, 20)


def test_strip_hash_identical_images_match():
    image = Image.new("RGB", (640, 80), (120, 140, 160))
    assert strip_hash(image) == strip_hash(image.copy())


def test_strip_hash_distinguishes_layouts():
    from PIL import ImageDraw

    left = Image.new("RGB", (640, 80), (255, 255, 255))
    ImageDraw.Draw(left).rectangle((0, 0, 320, 80), fill=(0, 0, 0))
    right = Image.new("RGB", (640, 80), (255, 255, 255))
    ImageDraw.Draw(right).rectangle((320, 0, 640, 80), fill=(0, 0, 0))
    assert strip_hash(left) != strip_hash(right)


def test_cluster_groups_near_duplicates():
    items = [
        {"t": 0.0, "hash": 0b1111},
        {"t": 2.0, "hash": 0b1111},
        {"t": 4.0, "hash": 0b0000},
    ]
    clusters = cluster_hashes(items, threshold=2)
    assert len(clusters) == 2
    assert clusters[0]["members"] == [0.0, 2.0]
    assert clusters[1]["members"] == [4.0]


def test_hamming_counts_differing_bits():
    assert hamming(0b1010, 0b0011) == 2


def test_active_tab_strip_finds_blue_segment():
    from PIL import ImageDraw

    image = Image.new("RGB", (640, 40), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((200, 2, 360, 38), fill=(64, 110, 245))
    strip = active_tab_strip(image)
    assert strip is not None
    assert 150 <= strip.width <= 200


def test_active_tab_strip_returns_none_without_highlight():
    image = Image.new("RGB", (640, 40), (255, 255, 255))
    assert active_tab_strip(image) is None


def test_detect_active_tab_finds_tab_in_page_top():
    from PIL import ImageDraw

    image = Image.new("RGB", (1000, 400), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((300, 120, 520, 160), fill=(64, 110, 245))
    tab = detect_active_tab(image)
    assert tab is not None
    assert 190 <= tab.width <= 250


def test_cluster_frames_groups_identical_tab_strips(tmp_path):
    from PIL import ImageDraw

    paths = []
    for index in range(3):
        image = Image.new("RGB", (320, 180), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        if index < 2:
            draw.rectangle((0, 0, 160, 180), fill=(20, 20, 20))
        else:
            draw.rectangle((160, 0, 320, 180), fill=(20, 20, 20))
        path = tmp_path / f"f{index}.png"
        image.save(path)
        paths.append(path)
    pages = cluster_frames(paths, strip_ratio=(0, 1))
    assert len(pages) == 2


def test_assign_page_ids_writes_ocr_text(tmp_path):
    import json

    from PIL import ImageDraw

    images = tmp_path / "images"
    images.mkdir()
    image = Image.new("RGB", (400, 300), (250, 250, 250))
    ImageDraw.Draw(image).rectangle((120, 80, 260, 105), fill=(64, 110, 245))
    image.save(images / "01-风险分析对象-v1.jpg")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"images": [{"file": "01-风险分析对象-v1.jpg", "sha256": "abc"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    report = assign_page_ids(manifest, images, ocr_fn=lambda strip: "风险分析对象")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert report["assigned"] == 1
    assert data["images"][0]["page_id"] == "风险分析对象"
    assert data["images"][0]["page_id_source"] == "filename+ocr"


def test_assign_page_ids_falls_back_when_unreadable(tmp_path):
    import json

    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGB", (400, 300), (250, 250, 250)).save(images / "02-示例-v1.jpg")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"images": [{"file": "02-示例-v1.jpg"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    report = assign_page_ids(manifest, images, ocr_fn=lambda strip: "")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert report["fallback"] == ["02-示例-v1.jpg"]
    assert data["images"][0]["page_id"] == "示例"

