from unittest.mock import patch

import responses as resp_mock

from scripts.seed_github import build_epic_title, build_label_definitions, seed_labels


def test_build_label_definitions_count():
    labels = build_label_definitions()
    # 5 type + 4 status + 7 stage = 16
    assert len(labels) == 16


def test_build_label_definitions_type_epic():
    labels = build_label_definitions()
    epic_label = next(label for label in labels if label["name"] == "type: epic")
    assert epic_label["color"] == "6f42c1"


def test_build_label_definitions_stage_labels():
    labels = build_label_definitions()
    stage_labels = [label for label in labels if label["name"].startswith("stage: ")]
    assert len(stage_labels) == 7
    assert all(
        label["name"] in [f"stage: {i}" for i in range(1, 8)] for label in stage_labels
    )


def test_build_epic_title():
    title = build_epic_title(2, "Stage 2 — Core Analysis Engine")
    assert title == "[Epic] Stage 2 — Core Analysis Engine"


@resp_mock.activate
def test_seed_labels_creates_all():
    from scripts.github_client import GitHubClient

    # Patch all create_label calls to return successfully
    with patch.object(
        GitHubClient, "create_label", return_value={"name": "ok"}
    ) as mock_create:
        client = GitHubClient(token="test-token", owner="test", repo="test")
        seed_labels(client)
        assert mock_create.call_count == 16
