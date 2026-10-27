import json
from pathlib import Path
from unittest.mock import patch

from scripts import bailian


def test_parse_result_converts_ms_and_sorts():
    payload = {
        "transcripts": [
            {
                "sentences": [
                    {"begin_time": 2000, "end_time": 3000, "text": "第二句"},
                    {"begin_time": 500, "end_time": 1200, "text": "第一句"},
                ]
            }
        ]
    }
    assert bailian.parse_result(payload) == [
        {"t_start": 0.5, "t_end": 1.2, "text": "第一句"},
        {"t_start": 2.0, "t_end": 3.0, "text": "第二句"},
    ]


def test_transcribe_reads_cli_output(tmp_path):
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    raw = tmp_path / "raw.json"

    def fake_run(cmd, **kwargs):
        if "auth" in cmd:
            return type("P", (), {"returncode": 0, "stdout": '{"authenticated":true}', "stderr": ""})()
        raw.write_text(json.dumps({
            "transcripts": [{"sentences": [
                {"begin_time": 1000, "end_time": 2500, "text": "测试"}
            ]}]
        }), encoding="utf-8")
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with patch.object(bailian, "cli_path", return_value="bl.cmd"), patch.object(
        bailian.subprocess, "run", side_effect=fake_run
    ):
        assert bailian.transcribe(audio, raw_result_path=raw) == [
            {"t_start": 1.0, "t_end": 2.5, "text": "测试"}
        ]
