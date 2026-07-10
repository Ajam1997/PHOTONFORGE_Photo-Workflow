from scripts.check_drift import find_stale_frs, render_drift_report


MOCK_FR_ISSUES = [
    {
        "number": 10,
        "title": "[FR-1.1] Automated Media Ingest",
        "labels": [{"name": "status: defined"}],
        "html_url": "https://github.com/test/repo/issues/10",
        "updated_at": "2025-11-01T00:00:00Z",  # >90 days ago from 2026-05-23
    },
    {
        "number": 11,
        "title": "[FR-1.2] Spatio-Temporal Grouping",
        "labels": [{"name": "status: verified"}],
        "html_url": "https://github.com/test/repo/issues/11",
        "updated_at": "2026-05-01T00:00:00Z",
    },
    {
        "number": 12,
        "title": "[FR-1.3] Deduplication",
        "labels": [{"name": "status: in-progress"}],
        "html_url": "https://github.com/test/repo/issues/12",
        "updated_at": "2025-10-01T00:00:00Z",  # >90 days ago
    },
]


def test_find_stale_frs_returns_unverified_old(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "ingest.py").write_text("# implements something else")
    stale = find_stale_frs(MOCK_FR_ISSUES, src, days_threshold=90)
    # FR-1.1 is old + defined, no src reference → stale
    # FR-1.2 is verified → not stale
    # FR-1.3 is old + in-progress, no src reference → stale
    ids = [f["id"] for f in stale]
    assert "FR-1.1" in ids
    assert "FR-1.3" in ids
    assert "FR-1.2" not in ids


def test_find_stale_frs_skips_if_src_references(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "ingest.py").write_text("# FR-1.1: implemented here")
    stale = find_stale_frs(MOCK_FR_ISSUES, src, days_threshold=90)
    ids = [f["id"] for f in stale]
    assert "FR-1.1" not in ids


def test_render_drift_report_contains_ids():
    stale = [{"id": "FR-1.1", "title": "Automated Media Ingest", "url": "http://x", "last_updated": "2025-11-01"}]
    report = render_drift_report(stale, "2026-05-23")
    assert "FR-1.1" in report
    assert "2026-05-23" in report


# ---------------------------------------------------------------------------
# Reference-integrity checker (scripts/check_doc_references.py)
# ---------------------------------------------------------------------------


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


def test_kpm_untested_body_placeholder_does_not_block_fallback():
    """Rider from the live regen run: a literal 'untested' body value defeated
    the comment fallback for that field."""
    from scripts.generate_docs import render_kpm_table

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"body": "## KPM Update\n**KPM-1.1** - `450 MB/s` - **passing**"}]

    class _Client:
        REST_BASE = "https://api.github.test"
        owner, repo = "o", "r"

        class _S:
            def get(self, *a, **k):
                return _Resp()

        _session = _S()

    issue = {
        "title": "[KPM-1.1] Ingest Latency",
        "labels": [],
        "body": "**Target:** x\n\n**Last Measured:** untested\n\n**Status:** untested",
        "number": 30,
        "html_url": "u",
    }
    md = render_kpm_table([issue], client=_Client())
    assert "450 MB/s" in md and "passing" in md
