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

DOCS = Path("dev-docs")
SRC = Path("src")
DRIFT_DIR = DOCS / "drift-reports"


def _extract_id(title: str) -> str:
    """Extract FR/NFR ID from issue title (e.g., '[FR-1.1]' -> 'FR-1.1')."""
    m = re.match(r"\[([A-Z]+-[\d.]+)\]", title)
    return m.group(1) if m else ""


def _get_label_names(issue: dict) -> list[str]:
    """Extract label names from issue object."""
    return [label["name"] for label in issue.get("labels", [])]


def find_stale_frs(fr_issues: list[dict], src_path: Path, days_threshold: int = 90) -> list[dict]:
    """Return FR Issues that are unverified, old, and have no src/ reference.

    Args:
        fr_issues: List of GitHub Issue dicts with 'title', 'labels', 'updated_at', 'html_url'.
        src_path: Path to src/ directory to search for FR references.
        days_threshold: Minimum age (days) to flag as stale.

    Returns:
        List of stale FR dicts with keys: 'id', 'title', 'url', 'last_updated'.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_threshold)
    stale = []
    for issue in fr_issues:
        labels = _get_label_names(issue)
        # Skip if already verified or validated
        if "status: verified" in labels or "status: validated" in labels:
            continue
        # Skip if recently updated
        updated = datetime.fromisoformat(issue["updated_at"].replace("Z", "+00:00"))
        if updated > cutoff:
            continue
        # Extract FR ID
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
    """Render Markdown drift report.

    Args:
        stale: List of stale FR dicts.
        date: Date string (YYYY-MM-DD) for report header.

    Returns:
        Markdown string.
    """
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


def update_drift_index(drift_dir: Path) -> None:
    """Regenerate dev-docs/drift-reports/index.md listing all reports newest-first."""
    reports = sorted(
        [f for f in drift_dir.glob("*.md") if f.name != "index.md"],
        reverse=True,
    )
    lines = [
        "# Drift Reports",
        "",
        "Nightly stale-requirement reports. Generated automatically by `check_drift.py`.",
        "",
    ]
    if reports:
        lines += ["| Date | Report |", "|:---|:---|"]
        for r in reports:
            date = r.stem
            lines.append(f"| {date} | [View]({r.name}) |")
    else:
        lines.append("No drift reports yet — all requirements are current.")
    (drift_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """Fetch FR/NFR issues, detect stale items, and open GitHub Issue if any found."""
    client = GitHubClient()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print("Fetching FR Issues...")
    fr_issues = client.list_issues(labels="type: fr")
    nfr_issues = client.list_issues(labels="type: nfr")

    stale = find_stale_frs(fr_issues + nfr_issues, SRC)

    # Reference integrity (docs -> repo files). Informational in the report
    # until the Phase 3/4 content backlog is cleared; does not affect the
    # exit code yet (see docs overhaul plan, decision D5 staging).
    from scripts.check_doc_references import full_scan

    broken_refs = full_scan()

    DRIFT_DIR.mkdir(parents=True, exist_ok=True)

    if stale or broken_refs:
        report_path = DRIFT_DIR / f"{today}.md"
        report = render_drift_report(stale, today)
        if broken_refs:
            report += (
                "\n\n## Broken documentation references\n\n"
                f"{len(broken_refs)} repo paths/links cited in docs do not exist "
                "(`scripts/check_doc_references.py`):\n\n"
                + "\n".join(f"- `{r}`" for r in broken_refs)
                + "\n"
            )
        report_path.write_text(report, encoding="utf-8")
        print(f"Wrote drift report: {report_path}")

        if stale:
            drift_issue_body = (
                f"## Drift Detected — {today}\n\n"
                f"{len(stale)} FR/NFR items are unverified with no source reference and no activity in 90+ days.\n\n"
                f"See `dev-docs/drift-reports/{today}.md` for details.\n\n"
                + "\n".join(f"- [{s['id']}]({s['url']}): {s['title']}" for s in stale)
            )
            client.create_issue(
                f"[drift] Stale requirements detected — {today}",
                drift_issue_body,
                ["type: drift-report"],
            )
            print("Opened drift Issue on GitHub")

    update_drift_index(DRIFT_DIR)
    print(f"Updated drift index: {DRIFT_DIR / 'index.md'}")

    if stale:
        sys.exit(1)  # Non-zero exit flags CI as needing attention
    else:
        print("No drift detected.")


if __name__ == "__main__":
    main()
