#!/usr/bin/env python3
"""Audit all open GitHub Issues against the three project boards.

Prints a table showing which issues are missing from which boards,
then optionally adds them.

Usage:
  python scripts/audit_boards.py           # report only
  python scripts/audit_boards.py --fix     # report + add missing items
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.github_client import GitHubClient

DOCS = Path("dev-docs")
MAP_PATH = DOCS / "github-issue-map.json"

# Which board each issue type belongs on (type label -> list of board keys)
BOARD_RULES: dict[str, list[str]] = {
    "type: epic":       ["roadmap"],
    "type: user-need":  ["roadmap", "requirements"],
    "type: fr":         ["requirements"],
    "type: nfr":        ["requirements"],
    "type: kpm":        ["kpm_dashboard"],
}


def get_board_item_numbers(client: GitHubClient, project_id: str) -> set[int]:
    """Return set of issue numbers currently on a board."""
    numbers: set[int] = set()
    after = None
    while True:
        data = client.graphql(
            """
            query($projectId: ID!, $after: String) {
              node(id: $projectId) {
                ... on ProjectV2 {
                  items(first: 100, after: $after) {
                    nodes { content { ... on Issue { number } } }
                    pageInfo { hasNextPage endCursor }
                  }
                }
              }
            }
            """,
            {"projectId": project_id, "after": after},
        )
        items = data["node"]["items"]
        for node in items["nodes"]:
            content = node.get("content") or {}
            num = content.get("number")
            if num:
                numbers.add(num)
        if not items["pageInfo"]["hasNextPage"]:
            break
        after = items["pageInfo"]["endCursor"]
    return numbers


def main() -> None:
    fix = "--fix" in sys.argv
    client = GitHubClient()
    issue_map = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    projects = issue_map["projects"]

    board_ids = {
        "roadmap":      projects["roadmap"]["id"],
        "requirements": projects["requirements"]["id"],
        "kpm_dashboard": projects["kpm_dashboard"]["id"],
    }
    board_node_ids = {
        "roadmap":      {e["node_id"]: e["number"] for e in {**issue_map["epics"], **issue_map["user_needs"]}.values()},
    }

    print("Fetching current board contents...")
    on_board: dict[str, set[int]] = {}
    for board_key, project_id in board_ids.items():
        on_board[board_key] = get_board_item_numbers(client, project_id)
        print(f"  {board_key}: {len(on_board[board_key])} items")

    print("\nFetching all open issues...")
    all_issues = client.list_issues(state="open")
    print(f"  {len(all_issues)} open issues total\n")

    # Determine board assignments for each issue
    missing: list[dict] = []   # {issue, board_key, number, node_id, title}
    unassigned: list[dict] = []  # issues with no matching type label

    for issue in sorted(all_issues, key=lambda i: i["number"]):
        number = issue["number"]
        node_id = issue["node_id"]
        title = issue["title"]
        label_names = [l["name"] for l in issue.get("labels", [])]

        target_boards = []
        for type_label, boards in BOARD_RULES.items():
            if type_label in label_names:
                target_boards.extend(boards)

        if not target_boards:
            unassigned.append({"number": number, "title": title, "labels": label_names})
            continue

        for board_key in set(target_boards):
            if number not in on_board[board_key]:
                missing.append({
                    "number": number,
                    "node_id": node_id,
                    "title": title,
                    "board": board_key,
                    "project_id": board_ids[board_key],
                })

    # Report
    if missing:
        print(f"{'#':<6} {'Board':<16} Title")
        print("-" * 70)
        for m in missing:
            print(f"#{m['number']:<5} {m['board']:<16} {m['title'][:50]}")
        print(f"\n{len(missing)} issue(s) missing from their target board(s).")
    else:
        print("All typed issues are on their correct boards.")

    if unassigned:
        print(f"\nIssues with no board-type label ({len(unassigned)}):")
        for u in unassigned:
            labels_str = ", ".join(u["labels"]) if u["labels"] else "(no labels)"
            print(f"  #{u['number']:>4}  {u['title'][:50]}  [{labels_str}]")

    if missing and fix:
        print("\nAdding missing issues to boards...")
        for m in missing:
            client.add_project_item(m["project_id"], m["node_id"])
            print(f"  added #{m['number']} to {m['board']}")
        print("Done.")
    elif missing and not fix:
        print("\nRe-run with --fix to add them automatically.")


if __name__ == "__main__":
    main()
