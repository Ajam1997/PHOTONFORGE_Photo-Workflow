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
    """Build list of label dicts with name, color, and description."""
    labels = [
        {"name": "type: epic", "color": "6f42c1", "description": "Roadmap stage grouping"},
        {"name": "type: user-need", "color": "0075ca", "description": "UN-XXX user need item"},
        {"name": "type: fr", "color": "2ea44f", "description": "Functional requirement"},
        {"name": "type: nfr", "color": "1d9fa6", "description": "Non-functional requirement"},
        {"name": "type: kpm", "color": "e08000", "description": "Key performance measure"},
        {
            "name": "status: defined",
            "color": "888888",
            "description": "Requirement written, not implemented",
        },
        {
            "name": "status: in-progress",
            "color": "d4a017",
            "description": "Active development",
        },
        {"name": "status: verified", "color": "a8d8a8", "description": "@verification passed"},
        {
            "name": "status: validated",
            "color": "196127",
            "description": "@validation confirmed E2E",
        },
    ]
    for i, color in enumerate(STAGE_COLORS, start=1):
        labels.append(
            {"name": f"stage: {i}", "color": color, "description": f"Roadmap stage {i}"}
        )
    return labels


def build_epic_title(stage_num: int, stage_title: str) -> str:
    """Format epic title with stage number and title."""
    return f"[Epic] {stage_title}"


def seed_labels(client: GitHubClient) -> None:
    """Create all labels via GitHubClient."""
    for label in build_label_definitions():
        client.create_label(label["name"], label["color"], label["description"])
        print(f"  label: {label['name']}")


def seed_issues(
    client: GitHubClient, req_map: dict, un_items: list[dict], arch: dict, dry_run: bool
) -> dict:
    """Create all Issues in dependency order. Returns issue_map dict."""
    issue_map: dict = {
        "epics": {},
        "user_needs": {},
        "functional_requirements": {},
        "non_functional_requirements": {},
        "kpms": {},
    }

    fr_index = {r["id"]: r for r in arch["functional_requirements"]}
    nfr_index = {r["id"]: r for r in arch["non_functional_requirements"]}
    kpm_index = {k["id"]: k for k in arch["kpms"]}
    un_index = {u["id"]: u for u in un_items}

    # 1. Epics
    for stage_num, stage_data in req_map["stages"].items():
        title = build_epic_title(stage_num, stage_data["title"])
        body = (
            f"Roadmap stage {stage_num}: {stage_data['title']}\n\n"
            f"Sub-issues: {', '.join(stage_data['user_needs'])}"
        )
        labels = ["type: epic", f"stage: {stage_num}"]
        if not dry_run:
            issue = client.get_or_create_issue(
                f"[Epic] Stage {stage_num}", title, body, labels
            )
            issue_map["epics"][f"Stage {stage_num}"] = {
                "number": issue["number"],
                "node_id": issue["node_id"],
            }
        print(f"  epic: {title}")

    # 2. User Needs
    for un_id, un_data in req_map["user_needs"].items():
        un = un_index.get(un_id)
        if not un:
            continue
        stage_num = un["stage"]
        title = f"[{un_id}] {un['title']}"
        body = (
            f"**Acceptance:** {un['acceptance']}\n\n"
            f"**KPM:** {un['kpm']}\n\n"
            f"**Stage:** {stage_num}"
        )
        labels = ["type: user-need", f"stage: {stage_num}", f"status: {un['status'].lower()}"]
        if not dry_run:
            issue = client.get_or_create_issue(un_id, title, body, labels)
            issue_map["user_needs"][un_id] = {
                "number": issue["number"],
                "node_id": issue["node_id"],
            }
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
                issue_map["functional_requirements"][fr_id] = {
                    "number": issue["number"],
                    "node_id": issue["node_id"],
                }
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
                issue_map["non_functional_requirements"][nfr_id] = {
                    "number": issue["number"],
                    "node_id": issue["node_id"],
                }
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
                (
                    fr_id
                    for fr_id in un_data["functional_requirements"]
                    if fr_id in fr_index
                ),
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
                issue_map["kpms"][kpm_id] = {
                    "number": issue["number"],
                    "node_id": issue["node_id"],
                }
                if primary_fr:
                    parent = issue_map["functional_requirements"].get(primary_fr)
                    if parent:
                        client.add_sub_issue(parent["number"], issue["number"])
            seeded_kpms.add(kpm_id)
            print(f"  kpm: {kpm_id}")

    return issue_map


def main() -> None:
    """Main entry point."""
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("DRY RUN — no GitHub API calls will be made\n")

    req_map = yaml.safe_load(REQUIREMENT_MAP_PATH.read_text())
    un_items = parse_user_needs(DOCS / "living-user-needs.md")
    arch = parse_architecture(DOCS / "photonforge-architecture.md")

    # For dry-run, use a dummy token; for real runs, let GitHubClient read from env
    client = GitHubClient(token="dry-run" if dry_run else None)

    print("Creating labels...")
    if not dry_run:
        seed_labels(client)
    else:
        # Still print label names for dry-run feedback
        for label in build_label_definitions():
            print(f"  label: {label['name']}")

    print("\nCreating Issues...")
    issue_map = seed_issues(client, req_map, un_items, arch, dry_run)

    if not dry_run:
        MAP_PATH.write_text(json.dumps(issue_map, indent=2))
        print(f"\nWrote {MAP_PATH}")

    print("\nDone.")


if __name__ == "__main__":
    main()
