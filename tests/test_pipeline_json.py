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
