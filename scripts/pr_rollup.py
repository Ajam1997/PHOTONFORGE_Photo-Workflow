"""PR merge → Issue status rollup.

Called by .github/workflows/pr-close-issues.yml after a PR is merged.
Parses closed Issue numbers from the PR body, applies status: verified to
FR/NFR Issues, rolls up to parent UNs when all siblings are verified, and
promotes parent Epics to Done when all UNs in a stage are verified.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.github_client import GitHubClient

REPO_ROOT = Path(__file__).parent.parent
REQ_MAP_PATH = REPO_ROOT / "requirements" / "requirement-map.yml"


def _synthesize_issue_map(req_map: dict) -> dict:
    """Build the legacy issue_map shape ({section: {id: {number: N}}})
    from requirement-map.yml's `issue:` fields.

    Migration Phase 10: requirement-map.yml is now the single source of
    truth for ID→issue# resolution. This shim lets the existing rollup
    logic keep working without the deleted dev-docs/github-issue-map.json.
    `epics` is empty — Epics were superseded by Milestones, and the
    milestone close path (build_stage_to_milestone) is already primary.
    """
    sections = ("user_needs", "functional_requirements",
                "non_functional_requirements", "interface_requirements", "kpms")
    out: dict = {"epics": {}}
    for sec in sections:
        out[sec] = {
            rid: {"number": e["issue"]}
            for rid, e in (req_map.get(sec) or {}).items()
            if e.get("issue")
        }
    return out


def load_maps() -> tuple[dict, dict]:
    req_map = yaml.safe_load(REQ_MAP_PATH.read_text())
    issue_map = _synthesize_issue_map(req_map)
    return issue_map, req_map


def build_reverse_maps(issue_map: dict, req_map: dict) -> tuple[dict, dict, dict, dict]:
    """Return (fr_to_uns, nfr_to_uns, un_to_stage, stage_to_epic_num).

    A single FR/NFR may legitimately decompose more than one UN (e.g. FR-1.1
    "ingest from SD" is a building block for both UN-030 "auto-ingest on
    insertion" and UN-040 "SD→SSD staging for safe SD removal"). The reverse
    map therefore returns *all* parent UNs for each FR/NFR, not just the last
    one written.
    """
    fr_to_uns: dict[str, list[str]] = {}
    nfr_to_uns: dict[str, list[str]] = {}
    un_to_stage: dict[str, int] = {}
    stage_to_epic_num: dict[int, int] = {}

    for stage_num, stage_data in req_map["stages"].items():
        # Epic number lookup: issue_map["epics"] is keyed by "Stage N" short form
        epic_entry = issue_map["epics"].get(f"Stage {stage_num}", {})
        if epic_entry:
            stage_to_epic_num[stage_num] = epic_entry["number"]

        for un_id in stage_data.get("user_needs", []):
            un_to_stage[un_id] = stage_num
            un_entry = req_map["user_needs"].get(un_id, {})
            for fr_id in un_entry.get("functional_requirements", []):
                fr_to_uns.setdefault(fr_id, []).append(un_id)
            for nfr_id in un_entry.get("non_functional_requirements", []):
                nfr_to_uns.setdefault(nfr_id, []).append(un_id)

    return fr_to_uns, nfr_to_uns, un_to_stage, stage_to_epic_num


def build_num_to_req_id(issue_map: dict) -> dict[int, str]:
    """Map GitHub Issue number → requirement ID for all FR/NFR entries."""
    result: dict[int, str] = {}
    for section in ("functional_requirements", "non_functional_requirements"):
        for req_id, data in issue_map.get(section, {}).items():
            result[data["number"]] = req_id
    return result


def is_verified(issue: dict) -> bool:
    return any(l["name"] == "status: verified" for l in issue.get("labels", []))


def get_req_issue_num(issue_map: dict, req_id: str) -> int | None:
    for section in ("functional_requirements", "non_functional_requirements"):
        entry = issue_map.get(section, {}).get(req_id)
        if entry:
            return entry["number"]
    return None


def build_stage_to_milestone(client: GitHubClient) -> dict[int, int]:
    """Map stage number → milestone number by parsing milestone titles.

    Titles must start with "Stage N" (e.g. "Stage 4 — Host Integration").
    Stages without a matching milestone are absent from the map; the
    Epic-closure fallback handles those.
    """
    result: dict[int, int] = {}
    pattern = re.compile(r"^Stage\s+(\d+)\b")
    for ms in client.list_milestones(state="all"):
        m = pattern.match(ms.get("title", ""))
        if m:
            result[int(m.group(1))] = ms["number"]
    return result


def rollup(pr_body: str, dry_run: bool = False) -> None:
    issue_map, req_map = load_maps()
    fr_to_uns, nfr_to_uns, un_to_stage, stage_to_epic_num = build_reverse_maps(issue_map, req_map)
    num_to_req_id = build_num_to_req_id(issue_map)

    client = GitHubClient()
    stage_to_milestone_num = build_stage_to_milestone(client)

    # Fetch all issues once to avoid repeated list API calls
    all_issues_list = client.list_issues(state="all")
    all_issues: dict[int, dict] = {i["number"]: i for i in all_issues_list}

    closed_nums = [
        int(m)
        for m in re.findall(r"(?:Closes|Fixes|Resolves)\s+#(\d+)", pr_body, re.IGNORECASE)
    ]
    print(f"Closed issue numbers from PR body: {closed_nums}")

    newly_verified_uns: set[str] = set()

    for num in closed_nums:
        req_id = num_to_req_id.get(num)
        if not req_id:
            print(f"  #{num}: not a tracked FR/NFR — skipping")
            continue

        print(f"  #{num} ({req_id}): applying status: verified")
        if not dry_run:
            client.replace_status_label(num, "status: verified")
        # Update local cache so sibling checks see this as verified
        if num in all_issues:
            labels = [l for l in all_issues[num].get("labels", []) if not l["name"].startswith("status:")]
            labels.append({"name": "status: verified"})
            all_issues[num]["labels"] = labels

        parent_uns = fr_to_uns.get(req_id, []) + nfr_to_uns.get(req_id, [])
        if not parent_uns:
            print(f"    no parent UN for {req_id} — skipping rollup")
            continue

        for parent_un in parent_uns:
            # Check all FR/NFR siblings under this parent
            un_entry = req_map["user_needs"].get(parent_un, {})
            sibling_ids = (
                un_entry.get("functional_requirements", []) +
                un_entry.get("non_functional_requirements", [])
            )

            unverified = []
            for sib_id in sibling_ids:
                sib_num = get_req_issue_num(issue_map, sib_id)
                if not sib_num:
                    continue
                sib_issue = all_issues.get(sib_num, {})
                if not is_verified(sib_issue):
                    unverified.append(f"{sib_id} (#{sib_num})")

            if unverified:
                print(f"    {parent_un}: siblings not yet verified: {', '.join(unverified)}")
                continue

            un_num = issue_map["user_needs"].get(parent_un, {}).get("number")
            if not un_num:
                continue
            if parent_un in newly_verified_uns:
                # Already promoted via another sibling FR in this same PR
                continue
            print(f"    all siblings verified → {parent_un} (#{un_num}): applying status: verified")
            if not dry_run:
                client.replace_status_label(un_num, "status: verified")
            if un_num in all_issues:
                labels = [l for l in all_issues[un_num].get("labels", []) if not l["name"].startswith("status:")]
                labels.append({"name": "status: verified"})
                all_issues[un_num]["labels"] = labels
            newly_verified_uns.add(parent_un)

    # Epic rollup
    for un_id in newly_verified_uns:
        stage_num = un_to_stage.get(un_id)
        if stage_num is None:
            continue

        stage_data = req_map["stages"].get(stage_num, {})
        all_uns_in_stage = stage_data.get("user_needs", [])

        unverified_uns = []
        for un in all_uns_in_stage:
            un_num = issue_map["user_needs"].get(un, {}).get("number")
            if not un_num:
                continue
            un_issue = all_issues.get(un_num, {})
            if not is_verified(un_issue):
                unverified_uns.append(f"{un} (#{un_num})")

        if unverified_uns:
            print(f"  Stage {stage_num}: UNs not yet verified: {', '.join(unverified_uns)}")
            continue

        # All UNs in this stage are verified — close the Milestone (primary)
        # and the Epic Issue if one exists (backward compat; Epics are being retired).
        milestone_num = stage_to_milestone_num.get(stage_num)
        if milestone_num:
            print(f"  Stage {stage_num}: all UNs verified → closing Milestone #{milestone_num}")
            if not dry_run:
                client.close_milestone(milestone_num)
        else:
            print(f"  Stage {stage_num}: all UNs verified but no matching Milestone found")

        epic_num = stage_to_epic_num.get(stage_num)
        if epic_num:
            print(f"  Stage {stage_num}: closing legacy Epic #{epic_num} (backward compat)")
            if not dry_run:
                try:
                    client.replace_status_label(epic_num, "status: validated")
                    client.close_issue(epic_num)
                except Exception as e:  # noqa: BLE001 — best-effort cleanup
                    # Epic may have been deleted during the Milestone migration.
                    # Milestone closure (above) is the canonical action; this is cleanup.
                    print(f"    note: Epic #{epic_num} not reachable ({type(e).__name__}); "
                          f"likely deleted during Milestone migration. Skipping.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Roll up PR Issue status after merge")
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without touching GitHub")
    args = parser.parse_args()

    pr_body = os.environ.get("PR_BODY", "")
    if not pr_body:
        print("PR_BODY env var is empty — nothing to process")
        sys.exit(0)

    rollup(pr_body, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
