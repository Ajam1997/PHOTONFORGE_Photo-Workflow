import pytest
from scripts.generate_docs import (
    render_user_needs_section,
    render_fr_table,
    render_nfr_table,
    render_kpm_table,
    inject_auto_section,
)

MOCK_UN_ISSUES = [
    {
        "title": "[UN-001] The system installs without errors.",
        "labels": [{"name": "status: defined"}, {"name": "stage: 1"}],
        "body": "**Acceptance:** pip install -e . exits 0.\n\n**KPM:** NONE\n\n**Stage:** 1",
        "number": 3,
        "html_url": "https://github.com/test/repo/issues/3",
    },
    {
        "title": "[UN-010] Photos are automatically grouped into sessions.",
        "labels": [{"name": "status: verified"}, {"name": "stage: 2"}],
        "body": "**Acceptance:** cluster_sessions() works.\n\n**KPM:** NONE\n\n**Stage:** 2",
        "number": 4,
        "html_url": "https://github.com/test/repo/issues/4",
    },
]

MOCK_FR_ISSUES = [
    {
        "title": "[FR-1.1] Automated Media Ingest",
        "labels": [{"name": "status: verified"}, {"name": "stage: 4"}],
        "body": "**Implementation:** udev-triggered rsync",
        "number": 10,
        "html_url": "https://github.com/test/repo/issues/10",
    },
]

MOCK_NFR_ISSUES = [
    {
        "title": "[NFR-2.1] Internet Independence",
        "labels": [{"name": "status: verified"}],
        "body": "**Specification:** 100% offline at runtime",
        "number": 20,
        "html_url": "https://github.com/test/repo/issues/20",
    },
]

MOCK_KPM_ISSUES = [
    {
        "title": "[KPM-1.1] Ingest Latency",
        "labels": [{"name": "type: kpm"}],
        "body": "**Target:** >= 80% USB 3.0 bandwidth\n\n**Owner:** @devops\n\n**Verified By:** @verification\n\n**Last Measured:** 450 MB/s — 2026-05-20\n\n**Status:** passing",
        "number": 30,
        "html_url": "https://github.com/test/repo/issues/30",
    },
]


def test_render_user_needs_section_count():
    md = render_user_needs_section(MOCK_UN_ISSUES)
    assert "UN-001" in md
    assert "UN-010" in md


def test_render_user_needs_section_status():
    md = render_user_needs_section(MOCK_UN_ISSUES)
    assert "status: defined" in md or "DEFINED" in md


def test_render_fr_table_contains_fr():
    md = render_fr_table(MOCK_FR_ISSUES)
    assert "FR-1.1" in md
    assert "Automated Media Ingest" in md


def test_render_nfr_table_contains_nfr():
    md = render_nfr_table(MOCK_NFR_ISSUES)
    assert "NFR-2.1" in md
    assert "Internet Independence" in md


def test_render_kpm_table_contains_kpm():
    md = render_kpm_table(MOCK_KPM_ISSUES)
    assert "KPM-1.1" in md
    assert "Ingest Latency" in md
    assert "passing" in md.lower()


def test_inject_auto_section_replaces_markers():
    original = "# Doc\n\n<!-- AUTO:user_needs -->\nold content\n<!-- /AUTO:user_needs -->\n\n## Other"
    new_content = "new generated content"
    result = inject_auto_section(original, "user_needs", new_content)
    assert "new generated content" in result
    assert "old content" not in result
    assert "## Other" in result


def test_inject_auto_section_no_marker_raises():
    with pytest.raises(ValueError, match="AUTO:missing"):
        inject_auto_section("no markers here", "missing", "content")
