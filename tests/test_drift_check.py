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
