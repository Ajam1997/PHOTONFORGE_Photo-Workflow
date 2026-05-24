import pytest
import responses as resp_mock
from scripts.github_client import GitHubClient

OWNER = "test-owner"
REPO = "test-repo"
TOKEN = "ghp_test"


@pytest.fixture
def client():
    return GitHubClient(token=TOKEN, owner=OWNER, repo=REPO)


@resp_mock.activate
def test_create_label(client):
    resp_mock.add(
        resp_mock.POST,
        f"https://api.github.com/repos/{OWNER}/{REPO}/labels",
        json={"id": 1, "name": "type: epic", "color": "6f42c1"},
        status=201,
    )
    label = client.create_label("type: epic", "6f42c1", "Roadmap stage grouping")
    assert label["name"] == "type: epic"


@resp_mock.activate
def test_create_label_skips_existing(client):
    resp_mock.add(
        resp_mock.POST,
        f"https://api.github.com/repos/{OWNER}/{REPO}/labels",
        json={"message": "Validation Failed"},
        status=422,
    )
    resp_mock.add(
        resp_mock.GET,
        f"https://api.github.com/repos/{OWNER}/{REPO}/labels/type%3A%20epic",
        json={"id": 1, "name": "type: epic", "color": "6f42c1"},
        status=200,
    )
    label = client.create_label("type: epic", "6f42c1", "Roadmap stage grouping")
    assert label["name"] == "type: epic"


@resp_mock.activate
def test_create_issue(client):
    resp_mock.add(
        resp_mock.POST,
        f"https://api.github.com/repos/{OWNER}/{REPO}/issues",
        json={"number": 42, "title": "Stage 1 Epic", "node_id": "I_abc"},
        status=201,
    )
    issue = client.create_issue("Stage 1 Epic", "body text", ["type: epic"])
    assert issue["number"] == 42
    assert issue["node_id"] == "I_abc"


@resp_mock.activate
def test_find_issue_by_title_found(client):
    resp_mock.add(
        resp_mock.GET,
        f"https://api.github.com/repos/{OWNER}/{REPO}/issues",
        json=[{"number": 5, "title": "[UN-010] Photos grouped", "node_id": "I_xyz"}],
        status=200,
    )
    issue = client.find_issue_by_title("UN-010")
    assert issue["number"] == 5


@resp_mock.activate
def test_find_issue_by_title_not_found(client):
    resp_mock.add(
        resp_mock.GET,
        f"https://api.github.com/repos/{OWNER}/{REPO}/issues",
        json=[],
        status=200,
    )
    issue = client.find_issue_by_title("UN-999")
    assert issue is None


@resp_mock.activate
def test_post_comment(client):
    resp_mock.add(
        resp_mock.POST,
        f"https://api.github.com/repos/{OWNER}/{REPO}/issues/42/comments",
        json={"id": 100, "body": "test comment"},
        status=201,
    )
    result = client.post_comment(42, "test comment")
    assert result["id"] == 100


@resp_mock.activate
def test_set_labels(client):
    resp_mock.add(
        resp_mock.POST,
        f"https://api.github.com/repos/{OWNER}/{REPO}/issues/42/labels",
        json=[{"name": "status: verified"}],
        status=200,
    )
    client.set_labels(42, ["status: verified"])
