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

# Ensure project root is in path for module imports
sys.path.insert(0, str(Path(__file__).parent.parent))

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
