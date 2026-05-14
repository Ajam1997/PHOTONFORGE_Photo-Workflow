import json
from photo_workflow.pipeline import emit


def test_emit_json_mode(capsys):
    emit("score", "DSC001.ARW", "ok", json_progress=True, sharpness=0.82, stars=3)
    out = capsys.readouterr().out
    line = json.loads(out.strip())
    assert line["step"] == "score"
    assert line["file"] == "DSC001.ARW"
    assert line["status"] == "ok"
    assert line["sharpness"] == 0.82
    assert line["stars"] == 3


def test_emit_human_mode(capsys):
    emit("score", "DSC001.ARW", "ok", json_progress=False, sharpness=0.82, stars=3)
    out = capsys.readouterr().out
    assert "DSC001.ARW" in out
    try:
        json.loads(out.strip())
        assert False, "Should not be JSON in human mode"
    except json.JSONDecodeError:
        pass


def test_emit_error_status(capsys):
    emit("score", "DSC002.ARW", "error", json_progress=True, message="decode failed")
    out = capsys.readouterr().out
    line = json.loads(out.strip())
    assert line["status"] == "error"
    assert line["message"] == "decode failed"


def test_ingest_json_progress(tmp_path, monkeypatch):
    """Test ingest command with --json-progress flag."""
    from pathlib import Path
    from click.testing import CliRunner
    from photo_workflow.pipeline import cli

    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    (src / "DSC001.ARW").write_bytes(b"fake")

    # Mock ingest_volume to return the destination file
    def mock_ingest_volume(source, destination, dry_run=False):
        result_file = destination / "DSC001.ARW"
        result_file.write_bytes(b"fake")
        return [result_file]

    monkeypatch.setattr("photo_workflow.ingest.ingest_volume", mock_ingest_volume)

    runner = CliRunner()
    result = runner.invoke(cli, [
        "ingest", "--source", str(src), "--dest", str(dest), "--json-progress"
    ])
    assert result.exit_code == 0
    lines = [l for l in result.output.strip().splitlines() if l.startswith("{")]
    assert len(lines) >= 1
    rec = json.loads(lines[0])
    assert rec["step"] == "ingest"
    assert rec["status"] == "ok"
    assert "DSC001.ARW" in rec["file"]


def test_scan_json_progress(tmp_path):
    from click.testing import CliRunner
    from photo_workflow.pipeline import cli

    src = tmp_path / "photos"
    src.mkdir()
    (src / "DSC001.ARW").write_bytes(b"fake")
    (src / "DSC002.ARW").write_bytes(b"fake")
    manifest = tmp_path / "manifest.jsonl"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "scan", "--source", str(src), "--manifest", str(manifest), "--json-progress"
    ])
    assert result.exit_code == 0
    lines = [l for l in result.output.strip().splitlines() if l.startswith("{")]
    assert len(lines) >= 2
    for line in lines:
        rec = json.loads(line)
        if rec["step"] == "scan":
            assert rec["status"] == "ok"
            assert rec["file"].endswith(".ARW")
