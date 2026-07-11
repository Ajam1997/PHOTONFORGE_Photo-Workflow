"""Tests for scripts/pr_rollup.py — PR merge → Issue status rollup.

Focus: Interface Requirement (IF-x.y) recognition. IF Issues live in
requirement-map.yml's `interface_requirements` section (e.g. IF-1.1, the
Darktable Lua Plugin <-> CLI Orchestrator boundary) and must be treated
exactly like FR/NFR siblings: verified on PR close, counted in the
all-siblings-verified check, and rolled up to their parent UN.
"""
import pytest

from scripts.pr_rollup import (
    _synthesize_issue_map,
    build_num_to_req_id,
    build_reverse_maps,
    build_stage_to_milestone,
    get_req_issue_num,
    rollup,
)

# Synthetic requirement map mirroring the real shape. UN-050's only child
# requirement is IF-1.1 (matches production: the Lua plugin interface).
# UN-060 has a mixed FR + IF sibling set to exercise the sibling check.
REQ_MAP = {
    "stages": {
        6: {
            "title": "Stage 6 — Pipeline UX",
            "user_needs": ["UN-050", "UN-060"],
        },
    },
    "user_needs": {
        "UN-050": {
            "title": "The pipeline CLI supports staged execution.",
            "issue": 44,
            "functional_requirements": [],
            "non_functional_requirements": [],
            "interface_requirements": ["IF-1.1"],
            "kpms": [],
        },
        "UN-060": {
            "title": "Mixed FR + IF user need.",
            "issue": 60,
            "functional_requirements": ["FR-9.1"],
            "non_functional_requirements": [],
            "interface_requirements": ["IF-9.1"],
            "kpms": [],
        },
    },
    "functional_requirements": {
        "FR-9.1": {"title": "Some feature", "issue": 70},
    },
    "non_functional_requirements": {},
    "interface_requirements": {
        "IF-1.1": {
            "title": "Darktable Lua Plugin <-> CLI Orchestrator",
            "issue": 89,
            "parent_uns": ["UN-050"],
        },
        "IF-9.1": {"title": "Some interface", "issue": 71},
    },
    "kpms": {},
}


def _issue(num: int, status: str | None = None) -> dict:
    labels = [{"name": status}] if status else []
    return {"number": num, "labels": labels}


class FakeClient:
    """Records GitHub mutations; serves canned issue/milestone lists."""

    def __init__(self, issues: list[dict], milestones: list[dict] | None = None):
        self._issues = issues
        self._milestones = milestones or []
        self.status_labels: list[tuple[int, str]] = []
        self.closed_issues: list[int] = []
        self.closed_milestones: list[int] = []

    def list_issues(self, labels=None, state="open"):
        return self._issues

    def list_milestones(self, state="open"):
        return self._milestones

    def replace_status_label(self, issue_number, new_status):
        self.status_labels.append((issue_number, new_status))

    def close_issue(self, issue_number):
        self.closed_issues.append(issue_number)

    def close_milestone(self, milestone_number):
        self.closed_milestones.append(milestone_number)


@pytest.fixture
def issue_map():
    return _synthesize_issue_map(REQ_MAP)


def _patch_rollup(monkeypatch, issue_map, client):
    import scripts.pr_rollup as mod
    monkeypatch.setattr(mod, "load_maps", lambda: (issue_map, REQ_MAP))
    monkeypatch.setattr(mod, "GitHubClient", lambda: client)


# --- unit: map builders recognize interface_requirements -------------------

def test_num_to_req_id_includes_interface_requirements(issue_map):
    mapping = build_num_to_req_id(issue_map)
    assert mapping[89] == "IF-1.1"
    assert mapping[70] == "FR-9.1"


def test_get_req_issue_num_resolves_if(issue_map):
    assert get_req_issue_num(issue_map, "IF-1.1") == 89
    assert get_req_issue_num(issue_map, "FR-9.1") == 70
    assert get_req_issue_num(issue_map, "FR-nope") is None


def test_build_reverse_maps_includes_if_to_uns(issue_map):
    fr_to_uns, nfr_to_uns, if_to_uns, un_to_stage, _ = build_reverse_maps(
        issue_map, REQ_MAP
    )
    assert if_to_uns["IF-1.1"] == ["UN-050"]
    assert if_to_uns["IF-9.1"] == ["UN-060"]
    assert fr_to_uns["FR-9.1"] == ["UN-060"]
    assert un_to_stage["UN-050"] == 6


# --- integration: rollup() end-to-end with a fake client -------------------

def test_closing_if_issue_verifies_and_rolls_up_to_un(monkeypatch, capsys):
    """PR closing IF-1.1 (#89): the IF gets status: verified, and UN-050 —
    whose only child requirement is IF-1.1 — is promoted too."""
    client = FakeClient(issues=[_issue(89), _issue(44), _issue(60), _issue(70), _issue(71)])
    _patch_rollup(monkeypatch, _synthesize_issue_map(REQ_MAP), client)

    rollup("Closes #89")

    assert (89, "status: verified") in client.status_labels
    assert (44, "status: verified") in client.status_labels
    out = capsys.readouterr().out
    assert "not a tracked" not in out


def test_unverified_if_sibling_blocks_un_rollup(monkeypatch):
    """Closing FR-9.1 (#70) must NOT promote UN-060 while its IF sibling
    IF-9.1 (#71) is still unverified."""
    client = FakeClient(issues=[_issue(70), _issue(71), _issue(60)])
    _patch_rollup(monkeypatch, _synthesize_issue_map(REQ_MAP), client)

    rollup("Closes #70")

    assert (70, "status: verified") in client.status_labels
    assert (60, "status: verified") not in client.status_labels


def test_verified_if_sibling_allows_un_rollup(monkeypatch):
    """Closing FR-9.1 (#70) promotes UN-060 once IF-9.1 is already verified."""
    client = FakeClient(
        issues=[_issue(70), _issue(71, "status: verified"), _issue(60)]
    )
    _patch_rollup(monkeypatch, _synthesize_issue_map(REQ_MAP), client)

    rollup("Closes #70")

    assert (70, "status: verified") in client.status_labels
    assert (60, "status: verified") in client.status_labels


def test_dry_run_makes_no_mutations(monkeypatch):
    client = FakeClient(issues=[_issue(89), _issue(44)])
    _patch_rollup(monkeypatch, _synthesize_issue_map(REQ_MAP), client)

    rollup("Closes #89", dry_run=True)

    assert client.status_labels == []
    assert client.closed_issues == []
    assert client.closed_milestones == []


# --- regression guards for photo-workflow-specific behavior ----------------

def test_milestone_title_drift_warning_preserved(capsys):
    """D2 three-registries guard: warn when the GitHub milestone title
    drifts from requirement-map.yml's canonical stage title."""
    client = FakeClient(
        issues=[],
        milestones=[{"number": 12, "title": "Stage 6 — Renamed On GitHub"}],
    )
    result = build_stage_to_milestone(client, REQ_MAP)
    assert result == {6: 12}
    assert "milestone title drift" in capsys.readouterr().out


def test_epic_closure_backward_compat_preserved(monkeypatch):
    """Legacy Epic path: when every UN in a stage verifies, the stage Epic
    (if still present in the issue map) is validated and closed."""
    issue_map = _synthesize_issue_map(REQ_MAP)
    issue_map["epics"] = {"Stage 6": {"number": 99}}
    client = FakeClient(
        issues=[
            _issue(89),
            _issue(44),
            _issue(60, "status: verified"),
            _issue(70, "status: verified"),
            _issue(71, "status: verified"),
        ],
        milestones=[{"number": 12, "title": "Stage 6 — Pipeline UX"}],
    )
    _patch_rollup(monkeypatch, issue_map, client)

    rollup("Closes #89")

    # UN-050 promoted, stage complete → milestone closed + legacy Epic closed
    assert (44, "status: verified") in client.status_labels
    assert client.closed_milestones == [12]
    assert (99, "status: validated") in client.status_labels
    assert client.closed_issues == [99]
