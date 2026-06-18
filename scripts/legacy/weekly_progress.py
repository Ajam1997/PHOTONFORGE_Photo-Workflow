"""Weekly per-Epic progress summary posted to GitHub Issues.

Called by .github/workflows/weekly-progress.yml every Monday.
For each Epic Issue, counts verified vs total UNs and posts a summary comment.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.github_client import GitHubClient

REPO_ROOT = Path(__file__).parent.parent
ISSUE_MAP_PATH = REPO_ROOT / "dev-docs" / "github-issue-map.json"
REQ_MAP_PATH = REPO_ROOT / "scripts" / "requirement_map.yml"

STATUS_ICON = {
    "status: validated": "✅",
    "status: verified": "✅",
    "status: in-progress": "🔄",
    "status: defined": "🔲",
}


def get_status_label(issue: dict) -> str:
    for label in issue.get("labels", []):
        if label["name"].startswith("status:"):
            return label["name"]
    return "status: defined"


def build_progress_comment(stage_num: int, stage_data: dict, un_issues: dict[str, dict], today: str) -> str:
    un_ids = stage_data.get("user_needs", [])
    rows = []
    verified_count = 0

    for un_id in un_ids:
        issue = un_issues.get(un_id)
        if not issue:
            rows.append(f"| {un_id} | *(not found)* | ❓ |")
            continue
        title = issue["title"].split("] ", 1)[1] if "] " in issue["title"] else issue["title"]
        status = get_status_label(issue)
        icon = STATUS_ICON.get(status, "🔲")
        status_display = status.removeprefix("status: ")
        rows.append(f"| {un_id} | {title} | {icon} {status_display} |")
        if status in ("status: verified", "status: validated"):
            verified_count += 1

    total = len(un_ids)
    pct = int(verified_count / total * 100) if total else 0

    lines = [
        f"## Weekly Progress — {today}",
        "",
        f"**Stage {stage_num}** · {verified_count} / {total} user needs verified ({pct}%)",
        "",
        "| User Need | Title | Status |",
        "|:---|:---|:---|",
    ] + rows + [
        "",
        f"*Auto-posted by weekly-progress workflow · {today}*",
    ]
    return "\n".join(lines)


def main() -> None:
    issue_map = json.loads(ISSUE_MAP_PATH.read_text())
    req_map = yaml.safe_load(REQ_MAP_PATH.read_text())
    client = GitHubClient()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Fetch all UN issues once
    print("Fetching UN issues...")
    all_un_issues_list = client.list_issues(labels="type: user-need", state="all")
    # Index by UN ID extracted from title
    un_issues: dict[str, dict] = {}
    for issue in all_un_issues_list:
        title = issue.get("title", "")
        if title.startswith("[UN-"):
            un_id = title[1:title.index("]")]
            un_issues[un_id] = issue

    for stage_num, stage_data in req_map["stages"].items():
        stage_title = stage_data.get("title", f"Stage {stage_num}")
        epic_entry = issue_map["epics"].get(f"Stage {stage_num}", {})
        epic_num = epic_entry.get("number")
        if not epic_num:
            print(f"  Stage {stage_num}: no Epic Issue found, skipping")
            continue

        comment = build_progress_comment(stage_num, stage_data, un_issues, today)
        print(f"  Posting progress comment on Epic #{epic_num} ({stage_title})")
        client.post_comment(epic_num, comment)

    print("Done.")


if __name__ == "__main__":
    main()
