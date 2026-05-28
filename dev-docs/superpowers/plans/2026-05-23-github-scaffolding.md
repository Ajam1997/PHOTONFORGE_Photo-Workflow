# GitHub Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Seed PHOTONForge's requirement hierarchy (Epics → UN → FR/NFR → KPM) into GitHub Issues and Projects boards, establish automated Markdown doc regeneration from Issue state, serve docs as a MkDocs Material site on GitHub Pages, and wire up three GitHub Actions workflows for PR automation, doc regeneration, and nightly drift detection.

**Architecture:** Five Python scripts form the core: `doc_parser.py` reads existing Markdown docs into structured dicts; `github_client.py` wraps the GitHub REST and GraphQL APIs; `seed_github.py` performs the one-time migration; `generate_docs.py` regenerates auto-managed doc sections from live Issue state; `check_drift.py` flags stale requirements nightly. `github_comment.py` is a thin CLI wrapper over `github_client.py` for agent use. Three GitHub Actions workflows tie it all together.

**Tech Stack:** Python 3.11+, `requests` (GitHub REST + GraphQL), `PyYAML` (requirement map config), MkDocs Material (static site), GitHub Actions, GitHub Projects v2 (GraphQL API), `pytest` + `responses` (mocking HTTP in tests).

---

## Environment Setup

Before starting: the scripts require a GitHub personal access token with scopes `repo`, `project`, and `read:org`. Store it as:
- Local dev: `export GITHUB_TOKEN=ghp_xxx` in your shell
- GitHub Actions: add as repo secret named `PHOTONFORGE_GITHUB_TOKEN`

The repo owner and name are `Ajam1997` / `PHOTONFORGE_Photo-Workflow`.

---

## File Map

```
scripts/
  doc_parser.py          NEW  — Parse living-user-needs.md and architecture doc into dicts
  github_client.py       NEW  — GitHub REST + GraphQL API wrapper
  github_comment.py      NEW  — Agent-safe CLI wrapper (thin; delegates to github_client.py)
  seed_github.py         NEW  — One-time idempotent Issue + board seeding
  generate_docs.py       NEW  — Regenerate auto-managed doc sections from GitHub Issues
  check_drift.py         NEW  — Nightly stale-requirement detection
  requirement_map.yml    NEW  — UN → FR/NFR/KPM mapping config (seed_github.py reads this)

docs/
  github-issue-map.json  NEW  — Written by seed_github.py; maps IDs → Issue numbers + project IDs
  index.md               NEW  — MkDocs home page
  drift-reports/         NEW  — Written by check_drift.py; one .md per drift event

mkdocs.yml               NEW  — MkDocs Material site config

.github/workflows/
  pr-close-issues.yml    NEW  — Close FR/NFR Issues on PR merge; roll up status
  regen-docs.yml         NEW  — Regenerate docs + deploy MkDocs on push / Issue change
  nightly-drift.yml      NEW  — Run check_drift.py at 02:00 UTC daily

tests/
  test_doc_parser.py     NEW
  test_github_client.py  NEW
  test_generate_docs.py  NEW
  test_drift_check.py    NEW
  fixtures/
    sample_user_needs.md     NEW  — Minimal living-user-needs.md for tests
    sample_architecture.md   NEW  — Minimal architecture doc for tests
```

**Modified:**
- `pyproject.toml` — add `docs` optional dependency group (`requests`, `PyYAML`, `responses`, `mkdocs-material`)
- `docs/living-user-needs.md` — add auto-gen header banner (done by `generate_docs.py`, not by hand)
- `docs/photonforge-architecture.md` — FR/NFR/KPM table sections replaced by auto-gen markers

---

## Task 1: Add Docs Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add optional `docs` dependency group**

In `pyproject.toml`, after the existing `[project.optional-dependencies]` `dev` block, add:

```toml
docs = [
    "requests>=2.32",
    "PyYAML>=6.0",
    "mkdocs-material>=9.5",
    "responses>=0.25",
]
```

- [ ] **Step 2: Install docs dependencies**

```bash
pip install -e ".[docs]"
```

Expected: installs requests, PyYAML, mkdocs-material, responses with no errors.

- [ ] **Step 3: Verify imports**

```bash
python -c "import requests, yaml, responses; print('OK')"
```

Expected: prints `OK`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add docs optional dependency group (requests, PyYAML, mkdocs-material, responses)"
```

---

## Task 2: Requirement Map Config

**Files:**
- Create: `scripts/requirement_map.yml`

This YAML file is the single place that defines which FRs/NFRs/KPMs belong to which UNs. The seed script reads it rather than inferring from the docs.

- [ ] **Step 1: Create `scripts/requirement_map.yml`**

```yaml
# Maps UN IDs to their FR, NFR, and KPM decompositions.
# Each UN entry lists the IDs of its child requirements.
# These IDs must match the IDs in photonforge-architecture.md exactly.

stages:
  1:
    title: "Stage 1 — Project Scaffold & Agent Roster"
    user_needs: [UN-001, UN-002]
  2:
    title: "Stage 2 — Core Analysis Engine"
    user_needs: [UN-010, UN-011, UN-012, UN-013, UN-014]
  3:
    title: "Stage 3 — Inference & Darktable Bridge"
    user_needs: [UN-020, UN-021]
  4:
    title: "Stage 4 — Host Integration"
    user_needs: [UN-030, UN-031, UN-032]
  5:
    title: "Stage 5 — Staged Pipeline CLI"
    user_needs: [UN-050, UN-051, UN-052, UN-053, UN-054]
  6:
    title: "Stage 6 — SD Staging & Safe Removal"
    user_needs: [UN-040]
  7:
    title: "Stage 7 — GUI & Full Integration"
    user_needs: [UN-041]

user_needs:
  UN-001:
    functional_requirements: []
    non_functional_requirements: []
    kpms: []
  UN-002:
    functional_requirements: []
    non_functional_requirements: []
    kpms: []
  UN-010:
    functional_requirements: [FR-1.2]
    non_functional_requirements: []
    kpms: []
  UN-011:
    functional_requirements: [FR-1.3]
    non_functional_requirements: []
    kpms: []
  UN-012:
    functional_requirements: [FR-1.4]
    non_functional_requirements: []
    kpms: []
  UN-013:
    functional_requirements: [FR-1.5]
    non_functional_requirements: []
    kpms: []
  UN-014:
    functional_requirements: [FR-1.6]
    non_functional_requirements: []
    kpms: []
  UN-020:
    functional_requirements: [FR-1.7]
    non_functional_requirements: []
    kpms: [KPM-1.2]
  UN-021:
    functional_requirements: [FR-1.8]
    non_functional_requirements: []
    kpms: []
  UN-030:
    functional_requirements: [FR-1.1]
    non_functional_requirements: [NFR-2.1, NFR-2.4]
    kpms: [KPM-1.1]
  UN-031:
    functional_requirements: [FR-1.9]
    non_functional_requirements: [NFR-2.3]
    kpms: []
  UN-032:
    functional_requirements: [FR-1.10]
    non_functional_requirements: []
    kpms: [KPM-1.4]
  UN-040:
    functional_requirements: [FR-1.1]
    non_functional_requirements: []
    kpms: [KPM-1.1]
  UN-041:
    functional_requirements: []
    non_functional_requirements: [NFR-2.4]
    kpms: []
  UN-050:
    functional_requirements: []
    non_functional_requirements: []
    kpms: []
  UN-051:
    functional_requirements: []
    non_functional_requirements: []
    kpms: []
  UN-052:
    functional_requirements: []
    non_functional_requirements: []
    kpms: []
  UN-053:
    functional_requirements: []
    non_functional_requirements: []
    kpms: []
  UN-054:
    functional_requirements: []
    non_functional_requirements: []
    kpms: []
```

- [ ] **Step 2: Verify YAML parses**

```bash
python -c "import yaml; d = yaml.safe_load(open('scripts/requirement_map.yml')); print(len(d['user_needs']), 'UNs')"
```

Expected: prints `15 UNs`.

- [ ] **Step 3: Commit**

```bash
git add scripts/requirement_map.yml
git commit -m "chore: add requirement map config (UN → FR/NFR/KPM decomposition)"
```

---

## Task 3: Document Parser

**Files:**
- Create: `scripts/doc_parser.py`
- Create: `tests/test_doc_parser.py`
- Create: `tests/fixtures/sample_user_needs.md`
- Create: `tests/fixtures/sample_architecture.md`

- [ ] **Step 1: Create fixture files**

Create `tests/fixtures/sample_user_needs.md`:

```markdown
# Living User Need Document -- PHOTONForge

## Format
UN-[ID]: [User need in plain language]
Acceptance: [Observable, measurable output]
KPM: [KPM ID or NONE]
Stage: [Roadmap stage number]
Status: [DEFINED | VERIFIED | VALIDATED]

## Requirements

UN-001: The system installs without errors.
Acceptance: pip install -e . exits 0.
KPM: NONE
Stage: 1
Status: DEFINED

UN-010: Photos are automatically grouped into sessions.
Acceptance: cluster_sessions() correctly groups fixture images.
KPM: NONE
Stage: 2
Status: VERIFIED
```

Create `tests/fixtures/sample_architecture.md`:

```markdown
# Architecture

## 3. Requirements

### 3.1 Functional Requirements

| ID | Description | Implementation |
|:---|:---|:---|
| FR-1.1 | Automated Media Ingest | udev-triggered rsync |
| FR-1.2 | Spatio-Temporal Grouping | Cluster if delta < 500ms |

### 3.2 Non-Functional Requirements

| ID | Description | Specification |
|:---|:---|:---|
| NFR-2.1 | Internet Independence | 100% offline at runtime. |
| NFR-2.2 | Resource Efficiency | RSS <= 1.5 GB. |

### 3.3 Key Performance Measures

| KPM | Metric | Target | Owner | Verified By |
|:---|:---|:---|:---|:---|
| KPM-1.1 | Ingest Latency | >= 80% USB 3.0 bandwidth | @devops | @verification |
| KPM-1.2 | Inference Speed | <= 2.5s per image | @engineer | @verification |
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_doc_parser.py`:

```python
import pytest
from pathlib import Path
from scripts.doc_parser import parse_user_needs, parse_architecture

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_user_needs_count():
    items = parse_user_needs(FIXTURES / "sample_user_needs.md")
    assert len(items) == 2


def test_parse_user_needs_fields():
    items = parse_user_needs(FIXTURES / "sample_user_needs.md")
    un001 = next(i for i in items if i["id"] == "UN-001")
    assert un001["title"] == "The system installs without errors."
    assert un001["acceptance"] == "pip install -e . exits 0."
    assert un001["kpm"] == "NONE"
    assert un001["stage"] == 1
    assert un001["status"] == "DEFINED"


def test_parse_user_needs_verified_status():
    items = parse_user_needs(FIXTURES / "sample_user_needs.md")
    un010 = next(i for i in items if i["id"] == "UN-010")
    assert un010["status"] == "VERIFIED"


def test_parse_architecture_frs():
    data = parse_architecture(FIXTURES / "sample_architecture.md")
    assert len(data["functional_requirements"]) == 2
    fr11 = next(r for r in data["functional_requirements"] if r["id"] == "FR-1.1")
    assert fr11["description"] == "Automated Media Ingest"
    assert fr11["implementation"] == "udev-triggered rsync"


def test_parse_architecture_nfrs():
    data = parse_architecture(FIXTURES / "sample_architecture.md")
    assert len(data["non_functional_requirements"]) == 2
    nfr = next(r for r in data["non_functional_requirements"] if r["id"] == "NFR-2.1")
    assert nfr["description"] == "Internet Independence"
    assert "offline" in nfr["specification"]


def test_parse_architecture_kpms():
    data = parse_architecture(FIXTURES / "sample_architecture.md")
    assert len(data["kpms"]) == 2
    kpm = next(k for k in data["kpms"] if k["id"] == "KPM-1.1")
    assert kpm["metric"] == "Ingest Latency"
    assert kpm["target"] == ">= 80% USB 3.0 bandwidth"
    assert kpm["owner"] == "@devops"
    assert kpm["verified_by"] == "@verification"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_doc_parser.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.doc_parser'`

- [ ] **Step 4: Create `scripts/__init__.py`**

```bash
touch scripts/__init__.py
```

- [ ] **Step 5: Implement `scripts/doc_parser.py`**

```python
"""Parse living-user-needs.md and photonforge-architecture.md into dicts."""
import re
from pathlib import Path


def parse_user_needs(path: Path) -> list[dict]:
    """Return list of UN dicts from living-user-needs.md."""
    text = path.read_text(encoding="utf-8")
    # Split on UN-NNN: lines
    blocks = re.split(r"(?=^UN-\d+:)", text, flags=re.MULTILINE)
    items = []
    for block in blocks:
        block = block.strip()
        if not block.startswith("UN-"):
            continue
        m_id = re.match(r"^(UN-\d+):\s*(.+)", block)
        if not m_id:
            continue
        un_id, title = m_id.group(1), m_id.group(2).strip()
        acceptance = _field(block, "Acceptance") or ""
        kpm = _field(block, "KPM") or "NONE"
        stage_str = _field(block, "Stage") or "0"
        status = _field(block, "Status") or "DEFINED"
        items.append({
            "id": un_id,
            "title": title,
            "acceptance": acceptance,
            "kpm": kpm,
            "stage": int(stage_str),
            "status": status.upper(),
        })
    return items


def parse_architecture(path: Path) -> dict:
    """Return {"functional_requirements": [...], "non_functional_requirements": [...], "kpms": [...]}."""
    text = path.read_text(encoding="utf-8")
    return {
        "functional_requirements": _parse_fr_table(text),
        "non_functional_requirements": _parse_nfr_table(text),
        "kpms": _parse_kpm_table(text),
    }


def _field(block: str, name: str) -> str | None:
    m = re.search(rf"^{name}:\s*(.+)$", block, re.MULTILINE)
    return m.group(1).strip() if m else None


def _parse_fr_table(text: str) -> list[dict]:
    """Parse the FR markdown table. Columns: ID | Description | Implementation"""
    section = _extract_section(text, "Functional Requirements", "Non-Functional Requirements")
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.match(r"FR-\d+\.\d+", cells[0]):
            rows.append({
                "id": cells[0],
                "description": cells[1],
                "implementation": cells[2],
            })
    return rows


def _parse_nfr_table(text: str) -> list[dict]:
    """Parse the NFR markdown table. Columns: ID | Description | Specification"""
    section = _extract_section(text, "Non-Functional Requirements", "Key Performance Measures")
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.match(r"NFR-\d+\.\d+", cells[0]):
            rows.append({
                "id": cells[0],
                "description": cells[1],
                "specification": cells[2],
            })
    return rows


def _parse_kpm_table(text: str) -> list[dict]:
    """Parse the KPM markdown table. Columns: KPM | Metric | Target | Owner | Verified By"""
    section = _extract_section(text, "Key Performance Measures", None)
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and re.match(r"KPM-\d+\.\d+", cells[0]):
            rows.append({
                "id": cells[0],
                "metric": cells[1],
                "target": cells[2],
                "owner": cells[3],
                "verified_by": cells[4],
            })
    return rows


def _extract_section(text: str, start_heading: str, end_heading: str | None) -> str:
    pattern = rf"###.*{re.escape(start_heading)}.*\n(.*?)"
    if end_heading:
        pattern += rf"(?=###.*{re.escape(end_heading)})"
    else:
        pattern += r"$"
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1) if m else ""
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_doc_parser.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/__init__.py scripts/doc_parser.py tests/test_doc_parser.py tests/fixtures/sample_user_needs.md tests/fixtures/sample_architecture.md
git commit -m "feat: add document parser for living-user-needs and architecture docs"
```

---

## Task 4: GitHub API Client

**Files:**
- Create: `scripts/github_client.py`
- Create: `tests/test_github_client.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_github_client.py`:

```python
import json
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_github_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.github_client'`

- [ ] **Step 3: Implement `scripts/github_client.py`**

```python
"""GitHub REST and GraphQL API client for PHOTONForge scaffolding scripts."""
import os
import requests
from typing import Any


class GitHubClient:
    REST_BASE = "https://api.github.com"
    GRAPHQL_URL = "https://api.github.com/graphql"

    def __init__(self, token: str | None = None, owner: str = "Ajam1997", repo: str = "PHOTONFORGE_Photo-Workflow"):
        self.token = token or os.environ["GITHUB_TOKEN"]
        self.owner = owner
        self.repo = repo
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    # --- Labels ---

    def create_label(self, name: str, color: str, description: str) -> dict:
        """Create a label; return existing label if it already exists."""
        r = self._session.post(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/labels",
            json={"name": name, "color": color, "description": description},
        )
        if r.status_code == 422:
            # Already exists — fetch it
            r2 = self._session.get(
                f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/labels/{requests.utils.quote(name, safe='')}",
            )
            r2.raise_for_status()
            return r2.json()
        r.raise_for_status()
        return r.json()

    # --- Issues ---

    def find_issue_by_title(self, search_term: str) -> dict | None:
        """Return first open Issue whose title contains search_term, or None."""
        r = self._session.get(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues",
            params={"state": "open", "per_page": 100},
        )
        r.raise_for_status()
        for issue in r.json():
            if search_term in issue.get("title", ""):
                return issue
        return None

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict:
        """Create an Issue and return the response dict (includes number and node_id)."""
        r = self._session.post(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues",
            json={"title": title, "body": body, "labels": labels},
        )
        r.raise_for_status()
        return r.json()

    def get_or_create_issue(self, search_term: str, title: str, body: str, labels: list[str]) -> dict:
        """Return existing Issue matching search_term, or create it."""
        existing = self.find_issue_by_title(search_term)
        if existing:
            return existing
        return self.create_issue(title, body, labels)

    def add_sub_issue(self, parent_number: int, child_issue_id: int) -> None:
        """Add child_issue_id as a sub-issue of parent_number."""
        r = self._session.post(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues/{parent_number}/sub_issues",
            json={"sub_issue_id": child_issue_id},
        )
        r.raise_for_status()

    def post_comment(self, issue_number: int, body: str) -> dict:
        r = self._session.post(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues/{issue_number}/comments",
            json={"body": body},
        )
        r.raise_for_status()
        return r.json()

    def set_labels(self, issue_number: int, labels: list[str]) -> None:
        r = self._session.post(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues/{issue_number}/labels",
            json={"labels": labels},
        )
        r.raise_for_status()

    def close_issue(self, issue_number: int) -> None:
        r = self._session.patch(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues/{issue_number}",
            json={"state": "closed"},
        )
        r.raise_for_status()

    def list_issues(self, labels: str | None = None, state: str = "open") -> list[dict]:
        params: dict[str, Any] = {"state": state, "per_page": 100}
        if labels:
            params["labels"] = labels
        issues = []
        page = 1
        while True:
            params["page"] = page
            r = self._session.get(
                f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues",
                params=params,
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            issues.extend(batch)
            page += 1
        return issues

    # --- GraphQL (Projects v2) ---

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        r = self._session.post(
            self.GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
        )
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            raise RuntimeError(f"GraphQL error: {data['errors']}")
        return data["data"]

    def get_owner_node_id(self) -> str:
        data = self.graphql(
            "query($login: String!) { user(login: $login) { id } }",
            {"login": self.owner},
        )
        return data["user"]["id"]

    def create_project(self, owner_id: str, title: str) -> dict:
        """Create a Projects v2 board. Returns {"id": ..., "number": ...}."""
        data = self.graphql(
            """
            mutation($ownerId: ID!, $title: String!) {
              createProjectV2(input: {ownerId: $ownerId, title: $title}) {
                projectV2 { id number }
              }
            }
            """,
            {"ownerId": owner_id, "title": title},
        )
        return data["createProjectV2"]["projectV2"]

    def add_project_item(self, project_id: str, issue_node_id: str) -> str:
        """Add an Issue to a Projects v2 board. Returns the item node ID."""
        data = self.graphql(
            """
            mutation($projectId: ID!, $contentId: ID!) {
              addProjectV2Item(input: {projectId: $projectId, contentId: $contentId}) {
                item { id }
              }
            }
            """,
            {"projectId": project_id, "contentId": issue_node_id},
        )
        return data["addProjectV2Item"]["item"]["id"]

    def create_project_field(self, project_id: str, name: str, data_type: str, options: list[str] | None = None) -> str:
        """Create a custom field on a Projects v2 board. Returns field node ID.
        data_type: TEXT | SINGLE_SELECT | NUMBER | DATE
        options: required when data_type is SINGLE_SELECT
        """
        if data_type == "SINGLE_SELECT":
            opts = [{"name": o} for o in (options or [])]
            data = self.graphql(
                """
                mutation($projectId: ID!, $name: String!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
                  createProjectV2Field(input: {projectId: $projectId, name: $name, dataType: SINGLE_SELECT, singleSelectOptions: $options}) {
                    projectV2Field { ... on ProjectV2SingleSelectField { id } }
                  }
                }
                """,
                {"projectId": project_id, "name": name, "options": opts},
            )
            return data["createProjectV2Field"]["projectV2Field"]["id"]
        else:
            data = self.graphql(
                f"""
                mutation($projectId: ID!, $name: String!) {{
                  createProjectV2Field(input: {{projectId: $projectId, name: $name, dataType: {data_type}}}) {{
                    projectV2Field {{ ... on ProjectV2Field {{ id }} }}
                  }}
                }}
                """,
                {"projectId": project_id, "name": name},
            )
            return data["createProjectV2Field"]["projectV2Field"]["id"]

    def update_project_text_field(self, project_id: str, item_id: str, field_id: str, value: str) -> None:
        self.graphql(
            """
            mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: String!) {
              updateProjectV2ItemFieldValue(input: {
                projectId: $projectId, itemId: $itemId, fieldId: $fieldId,
                value: {text: $value}
              }) { projectV2Item { id } }
            }
            """,
            {"projectId": project_id, "itemId": item_id, "fieldId": field_id, "value": value},
        )

    def update_project_select_field(self, project_id: str, item_id: str, field_id: str, option_id: str) -> None:
        self.graphql(
            """
            mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
              updateProjectV2ItemFieldValue(input: {
                projectId: $projectId, itemId: $itemId, fieldId: $fieldId,
                value: {singleSelectOptionId: $optionId}
              }) { projectV2Item { id } }
            }
            """,
            {"projectId": project_id, "itemId": item_id, "fieldId": field_id, "optionId": option_id},
        )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_github_client.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/github_client.py tests/test_github_client.py
git commit -m "feat: add GitHub REST + GraphQL client"
```

---

## Task 5: Agent Wrapper CLI

**Files:**
- Create: `scripts/github_comment.py`

No separate tests — this is a thin CLI wrapper that delegates to `GitHubClient`; tested implicitly through Task 4 tests.

- [ ] **Step 1: Implement `scripts/github_comment.py`**

```python
#!/usr/bin/env python3
"""Agent-safe CLI for writing back to GitHub Issues.

Usage:
  python scripts/github_comment.py comment <issue_number> <body>
  python scripts/github_comment.py set-labels <issue_number> <label1> [<label2> ...]
  python scripts/github_comment.py set-kpm <issue_number> <last_measured> <status>
  python scripts/github_comment.py close <issue_number>
"""
import sys
import json
from pathlib import Path
from scripts.github_client import GitHubClient

MAP_PATH = Path("docs/github-issue-map.json")


def load_map() -> dict:
    if MAP_PATH.exists():
        return json.loads(MAP_PATH.read_text())
    return {}


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    client = GitHubClient()

    if cmd == "comment":
        issue_number = int(sys.argv[2])
        body = sys.argv[3]
        result = client.post_comment(issue_number, body)
        print(f"Posted comment {result['id']} on issue #{issue_number}")

    elif cmd == "set-labels":
        issue_number = int(sys.argv[2])
        labels = sys.argv[3:]
        client.set_labels(issue_number, labels)
        print(f"Set labels {labels} on issue #{issue_number}")

    elif cmd == "set-kpm":
        # Updates Last Measured and Status fields on the KPM Dashboard board.
        # Requires github-issue-map.json to resolve the item ID on the board.
        issue_number = int(sys.argv[2])
        last_measured = sys.argv[3]
        status = sys.argv[4]  # passing | failing | untested
        issue_map = load_map()
        projects = issue_map.get("projects", {})
        kpm_project = projects.get("kpm_dashboard", {})
        fields = kpm_project.get("fields", {})
        item_ids = issue_map.get("project_items", {}).get("kpm_dashboard", {})
        item_id = item_ids.get(str(issue_number))
        if not item_id:
            print(f"Warning: issue #{issue_number} not found in KPM board item map — skipping field update")
        else:
            client.update_project_text_field(
                kpm_project["id"], item_id, fields["last_measured_id"], last_measured
            )
            client.update_project_select_field(
                kpm_project["id"], item_id, fields["status_id"],
                fields["status_options"][status]
            )
        print(f"Updated KPM fields for issue #{issue_number}: {last_measured}, {status}")

    elif cmd == "close":
        issue_number = int(sys.argv[2])
        client.close_issue(issue_number)
        print(f"Closed issue #{issue_number}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it runs**

```bash
python scripts/github_comment.py
```

Expected: prints the docstring usage and exits 1.

- [ ] **Step 3: Commit**

```bash
git add scripts/github_comment.py
git commit -m "feat: add agent-safe github_comment.py CLI wrapper"
```

---

## Task 6: Seeding Script

**Files:**
- Create: `scripts/seed_github.py`
- Create: `tests/test_seed_github.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_seed_github.py`:

```python
import json
import pytest
import responses as resp_mock
from pathlib import Path
from unittest.mock import patch, MagicMock
from scripts.seed_github import build_label_definitions, build_epic_title, seed_labels


def test_build_label_definitions_count():
    labels = build_label_definitions()
    names = [l["name"] for l in labels]
    # 5 type + 7 stage + 4 status = 16
    assert len(labels) == 16


def test_build_label_definitions_type_epic():
    labels = build_label_definitions()
    epic_label = next(l for l in labels if l["name"] == "type: epic")
    assert epic_label["color"] == "6f42c1"


def test_build_label_definitions_stage_labels():
    labels = build_label_definitions()
    stage_labels = [l for l in labels if l["name"].startswith("stage: ")]
    assert len(stage_labels) == 7
    assert all(l["name"] in [f"stage: {i}" for i in range(1, 8)] for l in stage_labels)


def test_build_epic_title():
    title = build_epic_title(2, "Stage 2 — Core Analysis Engine")
    assert title == "[Epic] Stage 2 — Core Analysis Engine"


@resp_mock.activate
def test_seed_labels_creates_all():
    from scripts.github_client import GitHubClient
    # Mock label creation for all 16 labels
    resp_mock.add(
        resp_mock.POST,
        "https://api.github.com/repos/Ajam1997/PHOTONFORGE_Photo-Workflow/labels",
        json={"name": "type: epic", "color": "6f42c1"},
        status=201,
    )
    client = GitHubClient(token="test", owner="Ajam1997", repo="PHOTONFORGE_Photo-Workflow")
    # Patch the loop — just verify create_label is called 16 times
    with patch.object(client, "create_label", return_value={"name": "ok"}) as mock_create:
        seed_labels(client)
        assert mock_create.call_count == 16
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_seed_github.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.seed_github'`

- [ ] **Step 3: Implement `scripts/seed_github.py`**

```python
#!/usr/bin/env python3
"""One-time idempotent seeding of GitHub Issues and Projects boards from Markdown docs.

Usage:
  python scripts/seed_github.py [--dry-run]
"""
import json
import sys
import yaml
from pathlib import Path
from scripts.doc_parser import parse_user_needs, parse_architecture
from scripts.github_client import GitHubClient

DOCS = Path("docs")
SCRIPTS = Path("scripts")
MAP_PATH = DOCS / "github-issue-map.json"
REQUIREMENT_MAP_PATH = SCRIPTS / "requirement_map.yml"

STAGE_COLORS = ["c0dfff", "93c5fd", "60a5fa", "3b82f6", "2563eb", "1d4ed8", "1e3a8a"]


def build_label_definitions() -> list[dict]:
    labels = [
        {"name": "type: epic",       "color": "6f42c1", "description": "Roadmap stage grouping"},
        {"name": "type: user-need",  "color": "0075ca", "description": "UN-XXX user need item"},
        {"name": "type: fr",         "color": "2ea44f", "description": "Functional requirement"},
        {"name": "type: nfr",        "color": "1d9fa6", "description": "Non-functional requirement"},
        {"name": "type: kpm",        "color": "e08000", "description": "Key performance measure"},
        {"name": "status: defined",      "color": "888888", "description": "Requirement written, not implemented"},
        {"name": "status: in-progress",  "color": "d4a017", "description": "Active development"},
        {"name": "status: verified",     "color": "a8d8a8", "description": "@verification passed"},
        {"name": "status: validated",    "color": "196127", "description": "@validation confirmed E2E"},
    ]
    for i, color in enumerate(STAGE_COLORS, start=1):
        labels.append({"name": f"stage: {i}", "color": color, "description": f"Roadmap stage {i}"})
    return labels


def build_epic_title(stage_num: int, stage_title: str) -> str:
    return f"[Epic] {stage_title}"


def seed_labels(client: GitHubClient) -> None:
    for label in build_label_definitions():
        client.create_label(label["name"], label["color"], label["description"])
        print(f"  label: {label['name']}")


def seed_issues(client: GitHubClient, req_map: dict, un_items: list[dict], arch: dict, dry_run: bool) -> dict:
    """Create all Issues in dependency order. Returns issue_map dict."""
    issue_map: dict = {"epics": {}, "user_needs": {}, "functional_requirements": {},
                       "non_functional_requirements": {}, "kpms": {}}

    fr_index = {r["id"]: r for r in arch["functional_requirements"]}
    nfr_index = {r["id"]: r for r in arch["non_functional_requirements"]}
    kpm_index = {k["id"]: k for k in arch["kpms"]}
    un_index = {u["id"]: u for u in un_items}

    # 1. Epics
    for stage_num, stage_data in req_map["stages"].items():
        title = build_epic_title(stage_num, stage_data["title"])
        body = f"Roadmap stage {stage_num}: {stage_data['title']}\n\nSub-issues: " + ", ".join(stage_data["user_needs"])
        labels = ["type: epic", f"stage: {stage_num}"]
        if not dry_run:
            issue = client.get_or_create_issue(f"[Epic] Stage {stage_num}", title, body, labels)
            issue_map["epics"][f"Stage {stage_num}"] = {"number": issue["number"], "node_id": issue["node_id"]}
        print(f"  epic: {title}")

    # 2. User Needs
    for un_id, un_data in req_map["user_needs"].items():
        un = un_index.get(un_id)
        if not un:
            continue
        stage_num = un["stage"]
        title = f"[{un_id}] {un['title']}"
        body = f"**Acceptance:** {un['acceptance']}\n\n**KPM:** {un['kpm']}\n\n**Stage:** {stage_num}"
        labels = ["type: user-need", f"stage: {stage_num}", f"status: {un['status'].lower()}"]
        if not dry_run:
            issue = client.get_or_create_issue(un_id, title, body, labels)
            issue_map["user_needs"][un_id] = {"number": issue["number"], "node_id": issue["node_id"]}
            # Link as sub-issue of Epic
            epic_entry = issue_map["epics"].get(f"Stage {stage_num}")
            if epic_entry:
                client.add_sub_issue(epic_entry["number"], issue["number"])
        print(f"  user-need: {un_id}")

    # 3. FRs
    for un_id, un_data in req_map["user_needs"].items():
        un = un_index.get(un_id)
        stage_num = un["stage"] if un else 0
        for fr_id in un_data["functional_requirements"]:
            fr = fr_index.get(fr_id)
            if not fr:
                continue
            title = f"[{fr_id}] {fr['description']}"
            body = f"**Implementation:** {fr['implementation']}\n\n**Parent UN:** {un_id}"
            labels = ["type: fr", f"stage: {stage_num}", "status: defined"]
            if not dry_run:
                issue = client.get_or_create_issue(fr_id, title, body, labels)
                issue_map["functional_requirements"][fr_id] = {"number": issue["number"], "node_id": issue["node_id"]}
                parent = issue_map["user_needs"].get(un_id)
                if parent:
                    client.add_sub_issue(parent["number"], issue["number"])
            print(f"  fr: {fr_id}")

    # 4. NFRs
    for un_id, un_data in req_map["user_needs"].items():
        un = un_index.get(un_id)
        stage_num = un["stage"] if un else 0
        for nfr_id in un_data["non_functional_requirements"]:
            nfr = nfr_index.get(nfr_id)
            if not nfr:
                continue
            title = f"[{nfr_id}] {nfr['description']}"
            body = f"**Specification:** {nfr['specification']}\n\n**Parent UN:** {un_id}"
            labels = ["type: nfr", f"stage: {stage_num}", "status: defined"]
            if not dry_run:
                issue = client.get_or_create_issue(nfr_id, title, body, labels)
                issue_map["non_functional_requirements"][nfr_id] = {"number": issue["number"], "node_id": issue["node_id"]}
                parent = issue_map["user_needs"].get(un_id)
                if parent:
                    client.add_sub_issue(parent["number"], issue["number"])
            print(f"  nfr: {nfr_id}")

    # 5. KPMs
    seeded_kpms: set[str] = set()
    for un_id, un_data in req_map["user_needs"].items():
        for kpm_id in un_data["kpms"]:
            if kpm_id in seeded_kpms:
                continue
            kpm = kpm_index.get(kpm_id)
            if not kpm:
                continue
            # Find primary parent FR
            primary_fr = next(
                (fr_id for fr_id in un_data["functional_requirements"] if fr_id in fr_index),
                None,
            )
            title = f"[{kpm_id}] {kpm['metric']}"
            body = (
                f"**Target:** {kpm['target']}\n\n"
                f"**Owner:** {kpm['owner']}\n\n"
                f"**Verified By:** {kpm['verified_by']}\n\n"
                f"**Last Measured:** untested\n\n"
                f"**Status:** untested"
            )
            labels = ["type: kpm"]
            if not dry_run:
                issue = client.get_or_create_issue(kpm_id, title, body, labels)
                issue_map["kpms"][kpm_id] = {"number": issue["number"], "node_id": issue["node_id"]}
                if primary_fr:
                    parent = issue_map["functional_requirements"].get(primary_fr)
                    if parent:
                        client.add_sub_issue(parent["number"], issue["number"])
            seeded_kpms.add(kpm_id)
            print(f"  kpm: {kpm_id}")

    return issue_map


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("DRY RUN — no GitHub API calls will be made\n")

    req_map = yaml.safe_load(REQUIREMENT_MAP_PATH.read_text())
    un_items = parse_user_needs(DOCS / "living-user-needs.md")
    arch = parse_architecture(DOCS / "photonforge-architecture.md")

    client = GitHubClient()

    print("Creating labels...")
    if not dry_run:
        seed_labels(client)

    print("\nCreating Issues...")
    issue_map = seed_issues(client, req_map, un_items, arch, dry_run)

    if not dry_run:
        MAP_PATH.write_text(json.dumps(issue_map, indent=2))
        print(f"\nWrote {MAP_PATH}")

    print("\nDone.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_seed_github.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Dry-run to verify output (no GitHub token needed)**

```bash
python scripts/seed_github.py --dry-run 2>&1 | head -40
```

Expected: prints `DRY RUN` header followed by label and Issue names without errors.

- [ ] **Step 6: Commit**

```bash
git add scripts/seed_github.py tests/test_seed_github.py
git commit -m "feat: add idempotent GitHub Issue seeding script"
```

---

## Task 6b: Board Creation

**Files:**
- Modify: `scripts/seed_github.py` — add `seed_boards()` function

The seed script must create the three Projects v2 boards before adding Issues to them. This task adds `seed_boards()` and wires it into `main()`.

- [ ] **Step 1: Add `seed_boards()` to `scripts/seed_github.py`**

Add the following function and update `main()`:

```python
def seed_boards(client: GitHubClient) -> dict:
    """Create the three Projects v2 boards with custom fields. Returns board metadata dict."""
    owner_id = client.get_owner_node_id()
    boards: dict = {}

    # Roadmap board
    roadmap = client.create_project(owner_id, "PHOTONForge Roadmap")
    stage_field_id = client.create_project_field(
        roadmap["id"], "Stage", "SINGLE_SELECT",
        options=[str(i) for i in range(1, 8)]
    )
    owner_field_id = client.create_project_field(
        roadmap["id"], "Owner", "SINGLE_SELECT",
        options=["architect", "engineer", "devops"]
    )
    boards["roadmap"] = {
        "id": roadmap["id"],
        "number": roadmap["number"],
        "fields": {"stage_id": stage_field_id, "owner_id": owner_field_id},
    }
    print(f"  board: PHOTONForge Roadmap (#{roadmap['number']})")

    # Requirements board
    reqs = client.create_project(owner_id, "PHOTONForge Requirements")
    un_id_field = client.create_project_field(reqs["id"], "UN ID", "TEXT")
    fr_id_field = client.create_project_field(reqs["id"], "FR ID", "TEXT")
    acceptance_field = client.create_project_field(reqs["id"], "Acceptance Criteria", "TEXT")
    req_owner_field = client.create_project_field(
        reqs["id"], "Owner", "SINGLE_SELECT",
        options=["architect", "engineer", "devops"]
    )
    boards["requirements"] = {
        "id": reqs["id"],
        "number": reqs["number"],
        "fields": {
            "un_id_id": un_id_field,
            "fr_id_id": fr_id_field,
            "acceptance_id": acceptance_field,
            "owner_id": req_owner_field,
        },
    }
    print(f"  board: PHOTONForge Requirements (#{reqs['number']})")

    # KPM Dashboard
    kpm_board = client.create_project(owner_id, "PHOTONForge KPM Dashboard")
    kpm_id_field = client.create_project_field(kpm_board["id"], "KPM ID", "TEXT")
    target_field = client.create_project_field(kpm_board["id"], "Target", "TEXT")
    last_measured_field = client.create_project_field(kpm_board["id"], "Last Measured", "TEXT")
    status_field_id = client.create_project_field(
        kpm_board["id"], "Status", "SINGLE_SELECT",
        options=["passing", "failing", "untested"]
    )
    measured_by_field = client.create_project_field(kpm_board["id"], "Measured By", "TEXT")
    boards["kpm_dashboard"] = {
        "id": kpm_board["id"],
        "number": kpm_board["number"],
        "fields": {
            "kpm_id_id": kpm_id_field,
            "target_id": target_field,
            "last_measured_id": last_measured_field,
            "status_id": status_field_id,
            "measured_by_id": measured_by_field,
        },
    }
    print(f"  board: PHOTONForge KPM Dashboard (#{kpm_board['number']})")

    return boards
```

- [ ] **Step 2: Update `main()` in `scripts/seed_github.py`**

Replace the existing `main()` function with:

```python
def main() -> None:
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("DRY RUN — no GitHub API calls will be made\n")

    req_map = yaml.safe_load(REQUIREMENT_MAP_PATH.read_text())
    un_items = parse_user_needs(DOCS / "living-user-needs.md")
    arch = parse_architecture(DOCS / "photonforge-architecture.md")

    client = GitHubClient()

    print("Creating labels...")
    if not dry_run:
        seed_labels(client)

    print("\nCreating Projects boards...")
    if not dry_run:
        boards = seed_boards(client)
    else:
        boards = {}

    print("\nCreating Issues...")
    issue_map = seed_issues(client, req_map, un_items, arch, dry_run)
    issue_map["projects"] = boards
    issue_map["project_items"] = {"kpm_dashboard": {}}

    if not dry_run:
        MAP_PATH.write_text(json.dumps(issue_map, indent=2))
        print(f"\nWrote {MAP_PATH}")

    print("\nDone.")
```

- [ ] **Step 3: Test dry-run still works**

```bash
python scripts/seed_github.py --dry-run 2>&1 | head -20
```

Expected: prints `DRY RUN` header and then labels/epics/UNs without error.

- [ ] **Step 4: Commit**

```bash
git add scripts/seed_github.py
git commit -m "feat: add Projects board creation to seed_github.py"
```

---

## Task 7: Doc Generation Script

**Files:**
- Create: `scripts/generate_docs.py`
- Create: `tests/test_generate_docs.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_generate_docs.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_generate_docs.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.generate_docs'`

- [ ] **Step 3: Add auto-section markers to `docs/living-user-needs.md`**

Open `docs/living-user-needs.md` and add these markers around the requirements section. The content between markers will be overwritten by `generate_docs.py`:

```markdown
> **Source of truth:** [GitHub Projects — Requirements Board](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/projects).
> This file is auto-generated from GitHub Issues — do not edit the section below manually.

## Format
UN-[ID]: [User need in plain language]
...

## Requirements

<!-- AUTO:user_needs -->
<!-- /AUTO:user_needs -->
```

Replace the existing `## Requirements` section content (all UN-XXX blocks) with the markers — the generator will fill them in on first run.

- [ ] **Step 4: Add auto-section markers to `docs/photonforge-architecture.md`**

In `docs/photonforge-architecture.md`, find sections `### 3.1 Functional Requirements`, `### 3.2 Non-Functional Requirements`, and `### 3.3 Key Performance Measures`. Wrap each table with markers:

```markdown
### 3.1 Functional Requirements

<!-- AUTO:fr_table -->
<!-- /AUTO:fr_table -->

### 3.2 Non-Functional Requirements

<!-- AUTO:nfr_table -->
<!-- /AUTO:nfr_table -->

### 3.3 Key Performance Measures

<!-- AUTO:kpm_table -->
<!-- /AUTO:kpm_table -->
```

- [ ] **Step 5: Implement `scripts/generate_docs.py`**

```python
#!/usr/bin/env python3
"""Regenerate auto-managed sections of docs from GitHub Issues.

Usage:
  python scripts/generate_docs.py
"""
import re
from pathlib import Path
from scripts.github_client import GitHubClient

DOCS = Path("docs")


def _extract_id(title: str) -> str:
    m = re.match(r"\[([A-Z]+-[\d.]+)\]", title)
    return m.group(1) if m else title


def _get_label(issue: dict, prefix: str) -> str:
    for label in issue.get("labels", []):
        if label["name"].startswith(prefix):
            return label["name"].removeprefix(prefix)
    return ""


def _body_field(body: str, field: str) -> str:
    m = re.search(rf"\*\*{re.escape(field)}:\*\*\s*(.+?)(?=\n\n|\Z)", body, re.DOTALL)
    return m.group(1).strip() if m else ""


def render_user_needs_section(issues: list[dict]) -> str:
    lines = []
    for issue in sorted(issues, key=lambda i: _extract_id(i["title"])):
        un_id = _extract_id(issue["title"])
        title = issue["title"].split("] ", 1)[1] if "] " in issue["title"] else issue["title"]
        status = _get_label(issue, "status: ").upper() or "DEFINED"
        stage = _get_label(issue, "stage: ") or "?"
        acceptance = _body_field(issue["body"], "Acceptance")
        kpm = _body_field(issue["body"], "KPM") or "NONE"
        url = issue["html_url"]
        lines.append(f"[{un_id}]({url}): {title}")
        lines.append(f"Acceptance: {acceptance}")
        lines.append(f"KPM: {kpm}")
        lines.append(f"Stage: {stage}")
        lines.append(f"Status: {status}")
        lines.append("")
    return "\n".join(lines)


def render_fr_table(issues: list[dict]) -> str:
    rows = ["| ID | Description | Implementation | Status |",
            "|:---|:---|:---|:---|"]
    for issue in sorted(issues, key=lambda i: _extract_id(i["title"])):
        fr_id = _extract_id(issue["title"])
        desc = issue["title"].split("] ", 1)[1] if "] " in issue["title"] else issue["title"]
        impl = _body_field(issue["body"], "Implementation")
        status = _get_label(issue, "status: ").upper() or "DEFINED"
        url = issue["html_url"]
        rows.append(f"| [{fr_id}]({url}) | {desc} | {impl} | {status} |")
    return "\n".join(rows)


def render_nfr_table(issues: list[dict]) -> str:
    rows = ["| ID | Description | Specification | Status |",
            "|:---|:---|:---|:---|"]
    for issue in sorted(issues, key=lambda i: _extract_id(i["title"])):
        nfr_id = _extract_id(issue["title"])
        desc = issue["title"].split("] ", 1)[1] if "] " in issue["title"] else issue["title"]
        spec = _body_field(issue["body"], "Specification")
        status = _get_label(issue, "status: ").upper() or "DEFINED"
        url = issue["html_url"]
        rows.append(f"| [{nfr_id}]({url}) | {desc} | {spec} | {status} |")
    return "\n".join(rows)


def render_kpm_table(issues: list[dict]) -> str:
    rows = ["| KPM | Metric | Target | Owner | Verified By | Last Measured | Status |",
            "|:---|:---|:---|:---|:---|:---|:---|"]
    for issue in sorted(issues, key=lambda i: _extract_id(i["title"])):
        kpm_id = _extract_id(issue["title"])
        metric = issue["title"].split("] ", 1)[1] if "] " in issue["title"] else issue["title"]
        target = _body_field(issue["body"], "Target")
        owner = _body_field(issue["body"], "Owner")
        verified_by = _body_field(issue["body"], "Verified By")
        last = _body_field(issue["body"], "Last Measured") or "untested"
        status = _body_field(issue["body"], "Status") or "untested"
        url = issue["html_url"]
        rows.append(f"| [{kpm_id}]({url}) | {metric} | {target} | {owner} | {verified_by} | {last} | {status} |")
    return "\n".join(rows)


def inject_auto_section(text: str, key: str, content: str) -> str:
    pattern = rf"(<!-- AUTO:{re.escape(key)} -->)(.*?)(<!-- /AUTO:{re.escape(key)} -->)"
    if not re.search(pattern, text, re.DOTALL):
        raise ValueError(f"Markers AUTO:{key} not found in document")
    return re.sub(pattern, rf"\1\n{content}\n\3", text, flags=re.DOTALL)


def main() -> None:
    client = GitHubClient()

    print("Fetching Issues from GitHub...")
    un_issues = client.list_issues(labels="type: user-need")
    fr_issues = client.list_issues(labels="type: fr")
    nfr_issues = client.list_issues(labels="type: nfr")
    kpm_issues = client.list_issues(labels="type: kpm")

    # Regenerate living-user-needs.md
    un_path = DOCS / "living-user-needs.md"
    text = un_path.read_text(encoding="utf-8")
    text = inject_auto_section(text, "user_needs", render_user_needs_section(un_issues))
    un_path.write_text(text, encoding="utf-8")
    print(f"Updated {un_path}")

    # Regenerate architecture doc
    arch_path = DOCS / "photonforge-architecture.md"
    text = arch_path.read_text(encoding="utf-8")
    text = inject_auto_section(text, "fr_table", render_fr_table(fr_issues))
    text = inject_auto_section(text, "nfr_table", render_nfr_table(nfr_issues))
    text = inject_auto_section(text, "kpm_table", render_kpm_table(kpm_issues))
    arch_path.write_text(text, encoding="utf-8")
    print(f"Updated {arch_path}")

    print("Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_generate_docs.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/generate_docs.py tests/test_generate_docs.py docs/living-user-needs.md docs/photonforge-architecture.md
git commit -m "feat: add generate_docs.py and inject auto-section markers into living docs"
```

---

## Task 8: MkDocs Setup

**Files:**
- Create: `mkdocs.yml`
- Create: `docs/index.md`

- [ ] **Step 1: Create `docs/roadmap.md`**

```markdown
# Roadmap

> Auto-generated from GitHub Issues. Source of truth: [PHOTONForge Roadmap board](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/projects).

<!-- AUTO:roadmap -->
<!-- /AUTO:roadmap -->
```

- [ ] **Step 2: Create `docs/kpm-dashboard.md`**

```markdown
# KPM Dashboard

> Auto-generated from GitHub Issues. Source of truth: [PHOTONForge KPM Dashboard board](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/projects).

<!-- AUTO:kpm_table -->
<!-- /AUTO:kpm_table -->
```

Then add `generate_roadmap_page()` and `generate_kpm_page()` calls to `scripts/generate_docs.py`'s `main()`, using the same `inject_auto_section()` helper already defined in Task 7:

```python
# In generate_docs.py main(), after existing regeneration calls:
roadmap_path = DOCS / "roadmap.md"
text = roadmap_path.read_text(encoding="utf-8")
epic_issues = client.list_issues(labels="type: epic")
roadmap_md = render_roadmap_section(epic_issues)
text = inject_auto_section(text, "roadmap", roadmap_md)
roadmap_path.write_text(text, encoding="utf-8")
print(f"Updated {roadmap_path}")

kpm_page_path = DOCS / "kpm-dashboard.md"
text = kpm_page_path.read_text(encoding="utf-8")
text = inject_auto_section(text, "kpm_table", render_kpm_table(kpm_issues))
kpm_page_path.write_text(text, encoding="utf-8")
print(f"Updated {kpm_page_path}")
```

Add `render_roadmap_section()` to `scripts/generate_docs.py`:

```python
def render_roadmap_section(epic_issues: list[dict]) -> str:
    lines = ["| Stage | Title | Status |", "|:---|:---|:---|"]
    for issue in sorted(epic_issues, key=lambda i: i["title"]):
        title = issue["title"].removeprefix("[Epic] ")
        labels = [l["name"] for l in issue.get("labels", [])]
        stage = next((l.removeprefix("stage: ") for l in labels if l.startswith("stage: ")), "?")
        state = "Done" if issue.get("state") == "closed" else "In Progress"
        url = issue["html_url"]
        lines.append(f"| {stage} | [{title}]({url}) | {state} |")
    return "\n".join(lines)
```

- [ ] **Step 3: Create `docs/index.md`**

```markdown
# PHOTONForge

Autonomous ingest-to-edit photography pipeline for the Lenovo Yoga 910.

Ingests from SD cards, analyzes and scores images with local ONNX models,
generates semantic filenames via Florence-2, and syncs to Darktable — all
offline, all local.

## Quick Links

- [Roadmap](roadmap.md)
- [User Needs](living-user-needs.md)
- [Architecture](photonforge-architecture.md)
- [KPM Dashboard](kpm-dashboard.md)
- [Specs & Plans](specs/index.md)
- [Source Repository](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow)
```

- [ ] **Step 2: Create `mkdocs.yml`**

```yaml
site_name: PHOTONForge
site_description: Autonomous ingest-to-edit photography pipeline
site_url: https://Ajam1997.github.io/PHOTONFORGE_Photo-Workflow
repo_url: https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow
repo_name: Ajam1997/PHOTONFORGE_Photo-Workflow
edit_uri: edit/main/docs/

theme:
  name: material
  palette:
    - scheme: default
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - scheme: slate
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
  features:
    - navigation.tabs
    - navigation.sections
    - toc.integrate
    - search.suggest
    - search.highlight
    - content.code.copy

nav:
  - Home: index.md
  - Roadmap: roadmap.md
  - User Needs: living-user-needs.md
  - Architecture: photonforge-architecture.md
  - KPM Dashboard: kpm-dashboard.md
  - Specs & Plans:
    - Overview: superpowers/index.md

plugins:
  - search

markdown_extensions:
  - tables
  - fenced_code
  - toc:
      permalink: true
```

- [ ] **Step 3: Create `docs/superpowers/index.md`**

```markdown
# Specs & Plans

Design specs and implementation plans for each PHOTONForge sub-project.

## Specs

{% for f in ["specs/2026-05-23-github-scaffolding-design.md"] %}
- [{{ f }}]({{ f }})
{% endfor %}
```

Since MkDocs doesn't support Jinja in Markdown by default, replace the templated section with a static list:

```markdown
# Specs & Plans

Design specs and implementation plans for each PHOTONForge sub-project.

## Specs
- [GitHub Scaffolding (2026-05-23)](specs/2026-05-23-github-scaffolding-design.md)

## Plans
- [GitHub Scaffolding Plan (2026-05-23)](plans/2026-05-23-github-scaffolding.md)
```

- [ ] **Step 4: Test MkDocs build**

```bash
mkdocs build --strict 2>&1
```

Expected: `INFO - Documentation built in X.X seconds` with no errors. A `site/` directory is created.

- [ ] **Step 5: Add `site/` to `.gitignore`**

Add to `.gitignore`:
```
site/
```

- [ ] **Step 6: Commit**

```bash
git add mkdocs.yml docs/index.md docs/superpowers/index.md .gitignore
git commit -m "feat: add MkDocs Material site config and home page"
```

---

## Task 9: Drift Check Script

**Files:**
- Create: `scripts/check_drift.py`
- Create: `tests/test_drift_check.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_drift_check.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import MagicMock
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
    stale = [{"id": "FR-1.1", "title": "Automated Media Ingest", "url": "http://x"}]
    report = render_drift_report(stale, "2026-05-23")
    assert "FR-1.1" in report
    assert "2026-05-23" in report
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_drift_check.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.check_drift'`

- [ ] **Step 3: Implement `scripts/check_drift.py`**

```python
#!/usr/bin/env python3
"""Nightly stale-requirement drift detection.

Usage:
  python scripts/check_drift.py
"""
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from scripts.github_client import GitHubClient

DOCS = Path("docs")
SRC = Path("src")
DRIFT_DIR = DOCS / "drift-reports"


def _extract_id(title: str) -> str:
    m = re.match(r"\[([A-Z]+-[\d.]+)\]", title)
    return m.group(1) if m else ""


def _get_label_names(issue: dict) -> list[str]:
    return [l["name"] for l in issue.get("labels", [])]


def find_stale_frs(fr_issues: list[dict], src_path: Path, days_threshold: int = 90) -> list[dict]:
    """Return FR Issues that are unverified, old, and have no src/ reference."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_threshold)
    stale = []
    for issue in fr_issues:
        labels = _get_label_names(issue)
        if "status: verified" in labels or "status: validated" in labels:
            continue
        updated = datetime.fromisoformat(issue["updated_at"].replace("Z", "+00:00"))
        if updated > cutoff:
            continue
        fr_id = _extract_id(issue["title"])
        if not fr_id:
            continue
        # Check if any src file references this FR ID
        referenced = any(
            fr_id in f.read_text(encoding="utf-8", errors="ignore")
            for f in src_path.rglob("*.py")
        )
        if not referenced:
            stale.append({
                "id": fr_id,
                "title": issue["title"].split("] ", 1)[1] if "] " in issue["title"] else issue["title"],
                "url": issue["html_url"],
                "last_updated": issue["updated_at"][:10],
            })
    return stale


def render_drift_report(stale: list[dict], date: str) -> str:
    lines = [
        f"# Drift Report — {date}",
        "",
        f"{len(stale)} stale FR(s) detected: unverified, no source reference, no update in 90+ days.",
        "",
        "| FR ID | Description | Last Updated | Issue |",
        "|:---|:---|:---|:---|",
    ]
    for item in stale:
        lines.append(f"| {item['id']} | {item['title']} | {item['last_updated']} | [#{item['id']}]({item['url']}) |")
    return "\n".join(lines) + "\n"


def main() -> None:
    client = GitHubClient()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print("Fetching FR Issues...")
    fr_issues = client.list_issues(labels="type: fr")
    nfr_issues = client.list_issues(labels="type: nfr")

    stale = find_stale_frs(fr_issues + nfr_issues, SRC)

    if stale:
        DRIFT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = DRIFT_DIR / f"{today}.md"
        report = render_drift_report(stale, today)
        report_path.write_text(report, encoding="utf-8")
        print(f"Wrote drift report: {report_path}")

        drift_issue_body = (
            f"## Drift Detected — {today}\n\n"
            f"{len(stale)} FR/NFR items are unverified with no source reference and no activity in 90+ days.\n\n"
            f"See `docs/drift-reports/{today}.md` for details.\n\n"
            + "\n".join(f"- [{s['id']}]({s['url']}): {s['title']}" for s in stale)
        )
        client.create_issue(
            f"[drift] Stale requirements detected — {today}",
            drift_issue_body,
            ["type: drift-report"],
        )
        print(f"Opened drift Issue on GitHub")
        sys.exit(1)  # Non-zero exit flags CI as needing attention
    else:
        print("No drift detected.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_drift_check.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_drift.py tests/test_drift_check.py
git commit -m "feat: add nightly drift detection script"
```

---

## Task 10: GitHub Actions Workflows

**Files:**
- Create: `.github/workflows/pr-close-issues.yml`
- Create: `.github/workflows/regen-docs.yml`
- Create: `.github/workflows/nightly-drift.yml`

- [ ] **Step 1: Create `.github/workflows/pr-close-issues.yml`**

```yaml
name: PR — Close Issues and Roll Up Status

on:
  pull_request:
    types: [closed]

jobs:
  roll-up-status:
    if: github.event.pull_request.merged == true
    runs-on: ubuntu-latest
    permissions:
      issues: write
      contents: read

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install requests PyYAML

      - name: Roll up Issue status
        env:
          GITHUB_TOKEN: ${{ secrets.PHOTONFORGE_GITHUB_TOKEN }}
        run: |
          python - <<'EOF'
          import os, re, json, sys
          from pathlib import Path
          sys.path.insert(0, ".")
          from scripts.github_client import GitHubClient

          client = GitHubClient()
          pr_body = os.environ.get("PR_BODY", "")
          pr_body = """${{ github.event.pull_request.body }}"""

          # Find all referenced Issue numbers
          closed_nums = [int(m) for m in re.findall(r"(?:Closes|Fixes|Resolves)\s+#(\d+)", pr_body, re.IGNORECASE)]

          issue_map = json.loads(Path("docs/github-issue-map.json").read_text()) if Path("docs/github-issue-map.json").exists() else {}

          for num in closed_nums:
              issues = client.list_issues(state="all")
              issue = next((i for i in issues if i["number"] == num), None)
              if not issue:
                  continue
              labels = [l["name"] for l in issue.get("labels", [])]
              if "type: fr" in labels or "type: nfr" in labels:
                  client.set_labels(num, ["status: verified"])
                  print(f"Set status: verified on #{num}")
          EOF
        env:
          PR_BODY: ${{ github.event.pull_request.body }}
```

- [ ] **Step 2: Create `.github/workflows/regen-docs.yml`**

```yaml
name: Regenerate Docs and Deploy MkDocs

on:
  push:
    branches: [main]
  issues:
    types: [labeled, unlabeled, closed, reopened, edited]
  workflow_dispatch:

jobs:
  regen-and-deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      issues: read

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.PHOTONFORGE_GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install requests PyYAML mkdocs-material

      - name: Regenerate docs from GitHub Issues
        env:
          GITHUB_TOKEN: ${{ secrets.PHOTONFORGE_GITHUB_TOKEN }}
        run: python scripts/generate_docs.py

      - name: Commit regenerated docs
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/living-user-needs.md docs/photonforge-architecture.md
          git diff --staged --quiet || git commit -m "docs: auto-regenerate from GitHub Issues [skip ci]"
          git push

      - name: Deploy MkDocs to GitHub Pages
        run: mkdocs gh-deploy --force
```

- [ ] **Step 3: Create `.github/workflows/nightly-drift.yml`**

```yaml
name: Nightly Drift Check

on:
  schedule:
    - cron: "0 2 * * *"
  workflow_dispatch:

jobs:
  drift-check:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      issues: write

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.PHOTONFORGE_GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install requests PyYAML mkdocs-material

      - name: Run drift check
        env:
          GITHUB_TOKEN: ${{ secrets.PHOTONFORGE_GITHUB_TOKEN }}
        run: python scripts/check_drift.py || true

      - name: Commit drift reports
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/drift-reports/ || true
          git diff --staged --quiet || git commit -m "docs: add nightly drift report [skip ci]"
          git push || true

      - name: Rebuild and deploy MkDocs
        run: mkdocs gh-deploy --force
```

- [ ] **Step 4: Validate YAML syntax**

```bash
python -c "
import yaml, pathlib
for f in pathlib.Path('.github/workflows').glob('*.yml'):
    yaml.safe_load(f.read_text())
    print(f'OK: {f}')
"
```

Expected:
```
OK: .github/workflows/nightly-drift.yml
OK: .github/workflows/pr-close-issues.yml
OK: .github/workflows/regen-docs.yml
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/
git commit -m "feat: add GitHub Actions workflows for PR status rollup, doc regen, and nightly drift"
```

---

## Task 11: Add GITHUB_TOKEN Secret and Run Seed

This task requires access to GitHub — do it once the above code is merged.

- [ ] **Step 1: Add the GitHub token secret**

Go to `https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/settings/secrets/actions` and create a new secret:
- Name: `PHOTONFORGE_GITHUB_TOKEN`
- Value: a GitHub personal access token with scopes `repo`, `project`

- [ ] **Step 2: Enable GitHub Pages**

Go to `https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/settings/pages`:
- Source: Deploy from a branch
- Branch: `gh-pages` / `/ (root)`

- [ ] **Step 3: Dry-run the seed script to preview what will be created**

```bash
GITHUB_TOKEN=your_token python scripts/seed_github.py --dry-run
```

Expected: full printout of labels, epics, UNs, FRs, NFRs, and KPMs that will be created — no API calls.

- [ ] **Step 4: Run the seed script**

```bash
GITHUB_TOKEN=your_token python scripts/seed_github.py
```

Expected: creates all labels, Issues, and boards in order. Writes `docs/github-issue-map.json`.

- [ ] **Step 5: Commit the issue map**

```bash
git add docs/github-issue-map.json
git commit -m "chore: add github-issue-map.json after initial seed run"
git push
```

- [ ] **Step 6: Trigger a manual doc regen run**

Go to `https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/actions/workflows/regen-docs.yml` and click "Run workflow". This regenerates the docs from the freshly created Issues and deploys the MkDocs site.

- [ ] **Step 7: Verify the GitHub Pages site loads**

Open `https://Ajam1997.github.io/PHOTONFORGE_Photo-Workflow`. Expected: MkDocs Material site with Home, Architecture, User Needs navigation visible.

---

## Task 12: Full Test Suite Pass

- [ ] **Step 1: Run all new tests**

```bash
pytest tests/test_doc_parser.py tests/test_github_client.py tests/test_generate_docs.py tests/test_drift_check.py tests/test_seed_github.py -v
```

Expected: all tests PASS. No existing tests broken.

- [ ] **Step 2: Run full test suite to check for regressions**

```bash
pytest -v -m "not slow and not integration"
```

Expected: all existing tests still PASS.

- [ ] **Step 3: Final commit**

```bash
git add .
git commit -m "chore: all github scaffolding tests passing"
git push
```
