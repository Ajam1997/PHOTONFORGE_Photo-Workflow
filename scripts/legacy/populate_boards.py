#!/usr/bin/env python3
"""Populate the three GitHub Projects boards with Issues and set custom field values.

This is idempotent — re-running it is safe. GitHub silently returns the existing
item ID when the same Issue is added to a board more than once.

Usage:
  python scripts/populate_boards.py
"""
import json
import re
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.github_client import GitHubClient

DOCS = Path("docs")
SCRIPTS = Path("scripts")
MAP_PATH = DOCS / "github-issue-map.json"


def _body_field(body: str, field: str) -> str:
    """Extract '**Field:** value' from an issue body."""
    m = re.search(rf"\*\*{re.escape(field)}:\*\*\s*(.+?)(?=\n\n|\Z)", body or "", re.DOTALL)
    return m.group(1).strip() if m else ""


def populate_roadmap(client: GitHubClient, issue_map: dict) -> None:
    """Add Epics and UNs to the Roadmap board; set Stage field for each."""
    board = issue_map["projects"]["roadmap"]
    project_id = board["id"]
    stage_field_id = board["fields"]["stage_id"]

    # Pre-fetch stage option IDs (values "1"–"7")
    stage_options: dict[str, str] = {}
    for s in range(1, 8):
        opt_id = client.get_project_select_option_id(project_id, stage_field_id, str(s))
        if opt_id:
            stage_options[str(s)] = opt_id

    req_map = yaml.safe_load((SCRIPTS / "requirement_map.yml").read_text(encoding="utf-8"))

    un_stage: dict[str, int] = {}
    for stage_num, stage_data in req_map["stages"].items():
        for un_id in stage_data["user_needs"]:
            un_stage[un_id] = int(stage_num)

    # Epics
    for stage_num, stage_data in req_map["stages"].items():
        key = f"Stage {stage_num}"
        entry = issue_map["epics"].get(key)
        if not entry:
            continue
        node_id = entry["node_id"]
        item_id = client.add_project_item(project_id, node_id)
        opt = stage_options.get(str(stage_num))
        if opt:
            client.update_project_select_field(project_id, item_id, stage_field_id, opt)
        print(f"  roadmap ← [Epic] Stage {stage_num}")

    # User Needs
    for un_id, entry in issue_map["user_needs"].items():
        node_id = entry["node_id"]
        stage = un_stage.get(un_id, 0)
        item_id = client.add_project_item(project_id, node_id)
        opt = stage_options.get(str(stage))
        if opt:
            client.update_project_select_field(project_id, item_id, stage_field_id, opt)
        print(f"  roadmap ← {un_id}")


def populate_requirements(client: GitHubClient, issue_map: dict) -> None:
    """Add UNs, FRs, and NFRs to the Requirements board; set ID and acceptance fields."""
    board = issue_map["projects"]["requirements"]
    project_id = board["id"]
    un_id_field = board["fields"]["un_id_id"]
    fr_id_field = board["fields"]["fr_id_id"]
    acceptance_field = board["fields"]["acceptance_id"]

    req_map = yaml.safe_load((SCRIPTS / "requirement_map.yml").read_text(encoding="utf-8"))

    # Fetch UN acceptance criteria from GitHub Issue bodies (markdown is auto-generated, not parseable)
    un_acceptance: dict[str, str] = {}
    for un_id, entry in issue_map["user_needs"].items():
        issue = client.get_issue(entry["number"])
        un_acceptance[un_id] = _body_field(issue.get("body", ""), "Acceptance")

    # Build UN → FR/NFR mapping for setting FR ID on child items
    un_for_fr: dict[str, str] = {}
    un_for_nfr: dict[str, str] = {}
    for un_id, un_data in req_map["user_needs"].items():
        for fr_id in un_data["functional_requirements"]:
            un_for_fr[fr_id] = un_id
        for nfr_id in un_data["non_functional_requirements"]:
            un_for_nfr[nfr_id] = un_id

    # User Needs
    for un_id, entry in issue_map["user_needs"].items():
        item_id = client.add_project_item(project_id, entry["node_id"])
        client.update_project_text_field(project_id, item_id, un_id_field, un_id)
        acc = un_acceptance.get(un_id, "")
        if acc:
            client.update_project_text_field(project_id, item_id, acceptance_field, acc)
        print(f"  requirements ← {un_id}")

    # Functional Requirements
    for fr_id, entry in issue_map["functional_requirements"].items():
        item_id = client.add_project_item(project_id, entry["node_id"])
        client.update_project_text_field(project_id, item_id, fr_id_field, fr_id)
        parent_un = un_for_fr.get(fr_id, "")
        if parent_un:
            client.update_project_text_field(project_id, item_id, un_id_field, parent_un)
        print(f"  requirements ← {fr_id}")

    # Non-Functional Requirements
    for nfr_id, entry in issue_map["non_functional_requirements"].items():
        item_id = client.add_project_item(project_id, entry["node_id"])
        client.update_project_text_field(project_id, item_id, fr_id_field, nfr_id)
        parent_un = un_for_nfr.get(nfr_id, "")
        if parent_un:
            client.update_project_text_field(project_id, item_id, un_id_field, parent_un)
        print(f"  requirements ← {nfr_id}")


def populate_kpm_dashboard(client: GitHubClient, issue_map: dict) -> None:
    """Add KPM Issues to the KPM Dashboard board and set all custom fields."""
    board = issue_map["projects"]["kpm_dashboard"]
    project_id = board["id"]
    fields = board["fields"]

    kpm_id_field = fields["kpm_id_id"]
    target_field = fields["target_id"]
    last_measured_field = fields["last_measured_id"]
    status_field = fields["status_id"]
    measured_by_field = fields["measured_by_id"]

    untested_opt = client.get_project_select_option_id(project_id, status_field, "untested")

    for kpm_id, entry in issue_map["kpms"].items():
        issue = client.get_issue(entry["number"])
        body = issue.get("body", "")
        target = _body_field(body, "Target")
        measured_by = _body_field(body, "Verified By")

        item_id = client.add_project_item(project_id, entry["node_id"])
        client.update_project_text_field(project_id, item_id, kpm_id_field, kpm_id)
        if target:
            client.update_project_text_field(project_id, item_id, target_field, target)
        client.update_project_text_field(project_id, item_id, last_measured_field, "untested")
        if measured_by:
            client.update_project_text_field(project_id, item_id, measured_by_field, measured_by)
        if untested_opt:
            client.update_project_select_field(project_id, item_id, status_field, untested_opt)
        print(f"  kpm_dashboard ← {kpm_id}")


def main() -> None:
    issue_map = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    client = GitHubClient()

    print("Populating Roadmap board...")
    populate_roadmap(client, issue_map)

    print("\nPopulating Requirements board...")
    populate_requirements(client, issue_map)

    print("\nPopulating KPM Dashboard...")
    populate_kpm_dashboard(client, issue_map)

    print("\nDone.")


if __name__ == "__main__":
    main()
