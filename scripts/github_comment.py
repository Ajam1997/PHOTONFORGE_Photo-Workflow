#!/usr/bin/env python3
"""Agent-safe CLI for writing back to GitHub Issues.

Agents (verification, validation) use this script to post results and update
status labels. Never call the GitHub API directly — this script holds the token.

ID-based commands (preferred — agents use requirement IDs, not Issue numbers):

  verify-fr <FR-ID> <summary>
      Post pytest summary and set status: verified on the FR Issue.
      Example: python scripts/github_comment.py verify-fr FR-1.2 "5/5 passed, 1.8s"

  regress-fr <FR-ID> <reason>
      Post regression detail and revert to status: defined.
      Example: python scripts/github_comment.py regress-fr FR-1.2 "expected 0.85 got 0.72"

  update-kpm <KPM-ID> <last_measured> <passing|failing|untested>
      Post measurement result, update Last Measured and KPM Status on the KPM Dashboard board.
      Example: python scripts/github_comment.py update-kpm KPM-1.2 "1.8s on i7-7500U — 2026-05-23" passing

  validate-un <UN-ID> <summary>
      Post E2E summary and set status: validated on the UN Issue.
      Example: python scripts/github_comment.py validate-un UN-010 "all 3 scenarios passed"

  validation-failure <UN-ID> <reason>
      Post comment on UN Issue and open a new type: validation-failure Issue.
      Example: python scripts/github_comment.py validation-failure UN-010 "wrong clusters on burst"

Low-level commands (for direct Issue number access):

  comment <issue_number> <body>
  set-labels <issue_number> <label1> [<label2> ...]
  close <issue_number>
"""
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.github_client import GitHubClient

MAP_PATH = Path("docs/github-issue-map.json")


def load_map() -> dict:
    if MAP_PATH.exists():
        return json.loads(MAP_PATH.read_text())
    return {}


def lookup_req(issue_map: dict, req_id: str) -> tuple[int, str]:
    """Return (issue_number, node_id) for a FR, NFR, KPM, or UN ID. Raises KeyError if not found."""
    prefix = req_id.split("-")[0].lower()
    section_map = {
        "fr": "functional_requirements",
        "nfr": "non_functional_requirements",
        "kpm": "kpms",
        "un": "user_needs",
    }
    section = section_map.get(prefix)
    if section and req_id in issue_map.get(section, {}):
        entry = issue_map[section][req_id]
        return entry["number"], entry["node_id"]
    raise KeyError(f"{req_id} not found in github-issue-map.json")


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def cmd_verify_fr(client: GitHubClient, issue_map: dict, fr_id: str, summary: str) -> None:
    num, _ = lookup_req(issue_map, fr_id)
    body = f"## ✅ Verification Passed — {today_str()}\n\n**{fr_id}** · {summary}\n\n*Posted by @verification*"
    client.post_comment(num, body)
    client.replace_status_label(num, "status: verified")
    print(f"verified {fr_id} (#{num})")


def cmd_regress_fr(client: GitHubClient, issue_map: dict, fr_id: str, reason: str) -> None:
    num, _ = lookup_req(issue_map, fr_id)
    body = f"## ❌ Regression Detected — {today_str()}\n\n**{fr_id}** · {reason}\n\n*Posted by @verification*"
    client.post_comment(num, body)
    client.replace_status_label(num, "status: defined")
    print(f"regression on {fr_id} (#{num}) — reverted to status: defined")


def cmd_update_kpm(client: GitHubClient, issue_map: dict, kpm_id: str, last_measured: str, status: str) -> None:
    if status not in ("passing", "failing", "untested"):
        print(f"Error: status must be passing|failing|untested, got '{status}'")
        sys.exit(1)

    num, _ = lookup_req(issue_map, kpm_id)
    icon = "✅" if status == "passing" else ("❌" if status == "failing" else "⬜")
    body = (
        f"## {icon} KPM Update — {today_str()}\n\n"
        f"**{kpm_id}** · `{last_measured}` · **{status}**\n\n"
        f"*Posted by @verification*"
    )
    client.post_comment(num, body)
    print(f"posted KPM comment on {kpm_id} (#{num})")

    # Update KPM Dashboard board fields
    projects = issue_map.get("projects", {})
    kpm_project = projects.get("kpm_dashboard", {})
    project_id = kpm_project.get("id")
    fields = kpm_project.get("fields", {})
    last_measured_field_id = fields.get("last_measured_id")
    status_field_id = fields.get("status_id")

    if not project_id or not last_measured_field_id or not status_field_id:
        print("Warning: KPM board field IDs missing from issue map — skipping board update")
        return

    item_id = client.find_project_item_by_issue_number(project_id, num)
    if not item_id:
        print(f"Warning: {kpm_id} (#{num}) not found on KPM Dashboard board — skipping board update")
        return

    client.update_project_text_field(project_id, item_id, last_measured_field_id, last_measured)

    option_id = client.get_project_select_option_id(project_id, status_field_id, status)
    if option_id:
        client.update_project_select_field(project_id, item_id, status_field_id, option_id)
        print(f"updated KPM board: last_measured='{last_measured}', status='{status}'")
    else:
        print(f"Warning: could not find option '{status}' on KPM Status field — text field updated only")


def cmd_validate_un(client: GitHubClient, issue_map: dict, un_id: str, summary: str) -> None:
    num, _ = lookup_req(issue_map, un_id)
    body = f"## ✅ Validation Passed — {today_str()}\n\n**{un_id}** · {summary}\n\n*Posted by @validation*"
    client.post_comment(num, body)
    client.replace_status_label(num, "status: validated")
    print(f"validated {un_id} (#{num})")


def cmd_validation_failure(client: GitHubClient, issue_map: dict, un_id: str, reason: str) -> None:
    num, _ = lookup_req(issue_map, un_id)
    body = (
        f"## ❌ Validation Failed — {today_str()}\n\n"
        f"**{un_id}** · {reason}\n\n"
        f"*Posted by @validation — escalating to @architect*"
    )
    client.post_comment(num, body)

    failure_body = (
        f"## Validation Failure — {un_id}\n\n"
        f"**Date:** {today_str()}\n"
        f"**User Need:** {un_id}\n"
        f"**Reason:** {reason}\n\n"
        f"Opened automatically by @validation. Assigned to @architect for requirement reassessment."
    )
    new_issue = client.create_issue(
        f"[validation-failure] {un_id} — {today_str()}",
        failure_body,
        ["type: validation-failure"],
    )
    print(f"posted failure comment on {un_id} (#{num})")
    print(f"opened validation-failure Issue #{new_issue['number']}")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    client = GitHubClient()
    issue_map = load_map()

    # --- ID-based commands ---
    if cmd == "verify-fr":
        fr_id, summary = sys.argv[2], sys.argv[3]
        cmd_verify_fr(client, issue_map, fr_id, summary)

    elif cmd == "regress-fr":
        fr_id, reason = sys.argv[2], sys.argv[3]
        cmd_regress_fr(client, issue_map, fr_id, reason)

    elif cmd == "update-kpm":
        kpm_id, last_measured, status = sys.argv[2], sys.argv[3], sys.argv[4]
        cmd_update_kpm(client, issue_map, kpm_id, last_measured, status)

    elif cmd == "validate-un":
        un_id, summary = sys.argv[2], sys.argv[3]
        cmd_validate_un(client, issue_map, un_id, summary)

    elif cmd == "validation-failure":
        un_id, reason = sys.argv[2], sys.argv[3]
        cmd_validation_failure(client, issue_map, un_id, reason)

    # --- Low-level commands ---
    elif cmd == "comment":
        issue_number = int(sys.argv[2])
        body = sys.argv[3]
        result = client.post_comment(issue_number, body)
        print(f"Posted comment {result['id']} on issue #{issue_number}")

    elif cmd == "set-labels":
        issue_number = int(sys.argv[2])
        labels = sys.argv[3:]
        client.set_labels(issue_number, labels)
        print(f"Set labels {labels} on issue #{issue_number}")

    elif cmd == "close":
        issue_number = int(sys.argv[2])
        client.close_issue(issue_number)
        print(f"Closed issue #{issue_number}")

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
