from pathlib import Path

import pytest

from scripts.product import (
    build_evidence,
    detect_transcript_gaps,
    find_action_anchors,
    _dedupe_times,
)


def test_build_evidence_external_manual_requires_finishing_pass():
    evidence = build_evidence(
        [],
        duration_s=10,
        transcript_path="transcript.json",
        frames_path="frames/",
        candidate_frames_path=None,
        mode="external-manual",
    )
    assert evidence["mode"] == "external-manual"
    assert "finishing" in evidence["screenshot_requirements"]


def test_build_evidence_defaults_to_product_guide():
    evidence = build_evidence(
        [],
        duration_s=10,
        transcript_path="transcript.json",
        frames_path="frames/",
        candidate_frames_path=None,
    )
    assert evidence["mode"] == "product-guide"
    assert "finishing" not in evidence["screenshot_requirements"]


def test_detect_transcript_gaps_reports_internal_gap():
    cues = [
        {"t_start": 5, "t_end": 10, "text": "开始"},
        {"t_start": 90, "t_end": 95, "text": "继续"},
    ]
    gaps = detect_transcript_gaps(cues, duration_s=100, min_gap_s=60)
    assert gaps == [{"t_start": 10.0, "t_end": 90.0, "duration_s": 80.0}]


def test_detect_transcript_gaps_validates_threshold():
    with pytest.raises(ValueError):
        detect_transcript_gaps([], duration_s=10, min_gap_s=0)


def test_detect_transcript_gaps_respects_absolute_focus_start():
    cues = [{"t_start": 305, "t_end": 310, "text": "开始配置"}]
    gaps = detect_transcript_gaps(
        cues, duration_s=400, start_s=300, min_gap_s=60
    )
    assert gaps == [{"t_start": 310.0, "t_end": 400, "duration_s": 90.0}]


def test_find_action_anchors_classifies_product_language():
    cues = [
        {"t_start": 1, "text": "进入配置页面点击新增"},
        {"t_start": 12, "text": "填写以后提交审批"},
        {"t_start": 24, "text": "最后打印预览"},
        {"t_start": 36, "text": "这里没有显示，是研发问题"},
    ]
    anchors = find_action_anchors(cues, min_separation_s=0)
    categories = {item["category"] for item in anchors}
    assert categories == {"configuration", "application", "output", "issue"}


def test_dedupe_times_collapses_nearby_candidates():
    assert _dedupe_times([3.0, 3.2, 4.0, -2.0]) == [0.0, 3.0, 4.0]
