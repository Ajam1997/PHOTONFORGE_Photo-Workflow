"""Unit tests for scripts/check_doc_references.py — the reference-integrity
checker that blocks the docs-integrity CI gate.

Recovered from the deleted tests/test_drift_check.py (see git history at
commit 0f24233), where these two cases lived alongside now-removed tests
for scripts.check_drift and scripts.generate_docs.
"""


def test_doc_references_detects_missing_and_existing(tmp_path, monkeypatch):
    import scripts.check_doc_references as cdr

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.py").write_text("x = 1")
    (tmp_path / "dev-docs").mkdir()
    (tmp_path / "dev-docs" / "a.md").write_text(
        "See src/real.py and the deleted src/ghost.py.\n"
        "Hypothetical src/example_<name>.py is skipped.\n"
        "This one is suppressed: src/also_ghost.py <!-- doc-ref: ignore -->\n"
        "[link](missing-page.md)\n"
    )
    monkeypatch.setattr(cdr, "REPO", tmp_path)

    problems = cdr.full_scan()
    assert any("src/ghost.py" in p for p in problems)
    assert any("missing-page.md" in p for p in problems)
    assert not any("real.py" in p for p in problems)
    assert not any("also_ghost" in p for p in problems)
    assert not any("example_" in p for p in problems)


def test_doc_references_exempts_dated_history(tmp_path, monkeypatch):
    import scripts.check_doc_references as cdr

    (tmp_path / "dev-docs" / "SystemReviews").mkdir(parents=True)
    (tmp_path / "dev-docs" / "SystemReviews" / "old.md").write_text(
        "Historical mention of src/deleted_module.py.\n"
    )
    monkeypatch.setattr(cdr, "REPO", tmp_path)
    assert cdr.full_scan() == []
