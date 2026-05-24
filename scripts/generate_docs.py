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
    """Extract ID from title like '[UN-001] Title' -> 'UN-001'"""
    m = re.match(r"\[([A-Z]+-[\d.]+)\]", title)
    return m.group(1) if m else title


def _get_label(issue: dict, prefix: str) -> str:
    """Get label value by prefix, e.g. 'status: ' -> 'defined'"""
    for label in issue.get("labels", []):
        if label["name"].startswith(prefix):
            return label["name"].removeprefix(prefix)
    return ""


def _body_field(body: str, field: str) -> str:
    """Extract field value from issue body like '**Field:** value' -> 'value'"""
    m = re.search(rf"\*\*{re.escape(field)}:\*\*\s*(.+?)(?=\n\n|\Z)", body, re.DOTALL)
    return m.group(1).strip() if m else ""


def render_user_needs_section(issues: list[dict]) -> str:
    """Render UN-XXX list with acceptance, KPM, stage, status."""
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
    """Render FR table with ID, description, implementation, status."""
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
    """Render NFR table with ID, description, specification, status."""
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
    """Render KPM table with metric, target, owner, verified by, last measured, status."""
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


def render_roadmap_section(epic_issues: list[dict]) -> str:
    """Render roadmap table with stage, title, status."""
    lines = ["| Stage | Title | Status |", "|:---|:---|:---|"]
    for issue in sorted(epic_issues, key=lambda i: i["title"]):
        title = issue["title"].removeprefix("[Epic] ")
        labels = [l["name"] for l in issue.get("labels", [])]
        stage = next((l.removeprefix("stage: ") for l in labels if l.startswith("stage: ")), "?")
        state = "Done" if issue.get("state") == "closed" else "In Progress"
        url = issue["html_url"]
        lines.append(f"| {stage} | [{title}]({url}) | {state} |")
    return "\n".join(lines)


def inject_auto_section(text: str, key: str, content: str) -> str:
    """Replace content between AUTO markers with new content."""
    pattern = rf"(<!-- AUTO:{re.escape(key)} -->)(.*?)(<!-- /AUTO:{re.escape(key)} -->)"
    if not re.search(pattern, text, re.DOTALL):
        raise ValueError(f"Markers AUTO:{key} not found in document")
    return re.sub(pattern, rf"\1\n{content}\n\3", text, flags=re.DOTALL)


def main() -> None:
    """Fetch issues from GitHub and regenerate living docs."""
    client = GitHubClient()

    print("Fetching Issues from GitHub...")
    un_issues = client.list_issues(labels="type: user-need")
    fr_issues = client.list_issues(labels="type: fr")
    nfr_issues = client.list_issues(labels="type: nfr")
    kpm_issues = client.list_issues(labels="type: kpm")
    epic_issues = client.list_issues(labels="type: epic")

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

    # Regenerate roadmap page
    roadmap_path = DOCS / "roadmap.md"
    if roadmap_path.exists():
        text = roadmap_path.read_text(encoding="utf-8")
        text = inject_auto_section(text, "roadmap", render_roadmap_section(epic_issues))
        roadmap_path.write_text(text, encoding="utf-8")
        print(f"Updated {roadmap_path}")

    # Regenerate KPM dashboard page
    kpm_page_path = DOCS / "kpm-dashboard.md"
    if kpm_page_path.exists():
        text = kpm_page_path.read_text(encoding="utf-8")
        text = inject_auto_section(text, "kpm_table", render_kpm_table(kpm_issues))
        kpm_page_path.write_text(text, encoding="utf-8")
        print(f"Updated {kpm_page_path}")

    print("Done.")


if __name__ == "__main__":
    main()
