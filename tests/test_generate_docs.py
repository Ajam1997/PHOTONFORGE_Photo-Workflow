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
    md = render_user_needs_section(MOCK_UN_ISSUES, [], [], {})
    assert "UN-001" in md
    assert "UN-010" in md


def test_render_user_needs_section_status():
    md = render_user_needs_section(MOCK_UN_ISSUES, [], [], {})
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


# ---------------------------------------------------------------------------
# Real-payload regressions: GitHub issue bodies are CRLF and carry placeholder
# bullets; the LF-only mocks above stayed green while live output corrupted.
# ---------------------------------------------------------------------------

CRLF_UN_ISSUE = {
    "title": "[UN-002] Agents are configured per roster.",
    "labels": [{"name": "status: defined"}],
    # exactly the \r\r\n blank-line shape observed in committed output
    "body": (
        "**Acceptance:** roster lists four agents.\r\r\n\r\r\n"
        "**KPM:** NONE\r\r\n\r\r\n"
        "**Stage:** 1\r\r\n\r\r\n"
        "**Validated By:**\r\r\n- (none yet)\r\r\n"
    ),
    "number": 5,
    "html_url": "https://github.com/test/repo/issues/5",
    "milestone": {"title": "Stage 1 — Project Scaffold"},
}


def test_crlf_body_fields_do_not_bleed():
    """Regression: CRLF bodies made the field capture run to end-of-body,
    duplicating every following field in the rendered block."""
    md = render_user_needs_section([CRLF_UN_ISSUE], [], [], {})
    assert md.count("KPM: NONE") == 1
    assert "**KPM:**" not in md  # raw markup leaking = capture overran
    assert "Stage: 1" in md
    assert "Stage: ?" not in md


def test_stage_from_body_not_retired_label():
    """Regression: stage came from a 'stage: N' label deleted in the label
    migration, rendering 'Stage: ?' for every UN."""
    issue = dict(CRLF_UN_ISSUE, body="**Acceptance:** x.\r\r\n", labels=[])
    md = render_user_needs_section([issue], [], [], {})
    assert "Stage: 1" in md  # falls back to the milestone title


def test_placeholder_evidence_not_counted():
    """Regression: literal '(none yet)' bullets counted as V&V evidence,
    inflating coverage to 38/48 while nothing was validated."""
    from scripts.generate_docs import _body_list_field, render_vv_matrix

    assert _body_list_field(CRLF_UN_ISSUE["body"], "Validated By") == []

    md = render_vv_matrix([CRLF_UN_ISSUE], [], [], [])
    assert "(none yet)" not in md
    assert "**0 / 1**" in md


def test_roadmap_progress_from_status_labels():
    """Regression: progress used issue open/closed counts, which no automation
    writes — shipped stages rendered 'Not Started' / 'Done 0/10'."""
    from scripts.generate_docs import render_roadmap_section

    milestones = [
        {"title": "Stage 2 — Core Analysis Engine", "html_url": "u", "state": "open",
         "open_issues": 10, "closed_issues": 0},
    ]
    issues = [
        {"title": f"[FR-1.{i}] x", "labels": [{"name": "status: verified"}],
         "body": "", "number": i, "html_url": "u",
         "milestone": {"title": "Stage 2 — Core Analysis Engine"}}
        for i in range(1, 4)
    ] + [
        {"title": "[FR-1.9] y", "labels": [{"name": "status: defined"}],
         "body": "", "number": 9, "html_url": "u",
         "milestone": {"title": "Stage 2 — Core Analysis Engine"}},
    ]
    md = render_roadmap_section(milestones, issues)
    assert "| 3/4 |" in md
    assert "In Progress" in md


def test_kpm_table_falls_back_to_update_comment():
    """Regression: dashboard read body fields nothing writes -> 'untested'
    forever despite measurements existing as '## KPM Update' comments."""

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"body": "## KPM Update\n**KPM-1.1** - `450 MB/s on i7-7500U` - **passing**"}]

    class _Session:
        def get(self, *a, **k):
            return _Resp()

    class _Client:
        REST_BASE = "https://api.github.test"
        owner, repo = "o", "r"
        _session = _Session()

    issue = {
        "title": "[KPM-1.1] Ingest Latency",
        "labels": [],
        "body": "**Target:** >= 80% USB 3.0 bandwidth\n\n**Owner:** @software_lead",
        "number": 30,
        "html_url": "u",
    }
    md = render_kpm_table([issue], client=_Client())
    assert "450 MB/s on i7-7500U" in md
    assert "passing" in md
    assert "untested" not in md
