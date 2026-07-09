#!/usr/bin/env python3
"""Regenerate auto-managed sections of docs from GitHub Issues.

Usage:
  python scripts/generate_docs.py
"""
import re
import yaml
from pathlib import Path
from scripts.github_client import GitHubClient

DOCS = Path("dev-docs")
SCRIPTS = Path("scripts")


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


# Real GitHub issue bodies use CRLF line endings; every regex below assumes
# LF. Without this, the (?=\n\n|\Z) terminator never matches mid-body and a
# lazy capture swallows everything to end-of-body (the living-user-needs
# duplication bug).
def _normalize(body: str) -> str:
    return re.sub(r"\r\n?", "\n", body or "")


# Placeholder bullets humans leave in evidence lists must not count as evidence.
_STAGE_TITLE_RE = re.compile(r"^Stage\s+(\d+)\b")
_PLACEHOLDER_RE = re.compile(r"^\(?\s*none(\s+yet)?\s*\)?$|^n/?a$", re.IGNORECASE)


def _body_field(body: str, field: str) -> str:
    """Extract field value from issue body like '**Field:** value' -> 'value'"""
    body = _normalize(body)
    m = re.search(rf"\*\*{re.escape(field)}:\*\*\s*(.+?)(?=\n\n|\n\*\*|\Z)", body, re.DOTALL)
    return m.group(1).strip() if m else ""


def _body_list_field(body: str, field: str) -> list[str]:
    """Extract a bullet-list field. Example:

        **Verified By:**
        - pytest: tests/test_sharpness.py::test_x
        - pytest: tests/test_sharpness.py::test_y

    Returns ["pytest: tests/test_sharpness.py::test_x", "pytest: tests/test_sharpness.py::test_y"].
    Blank line or next `**Field:**` heading ends the section.
    """
    body = _normalize(body)
    pattern = rf"\*\*{re.escape(field)}:\*\*\s*\n((?:[ \t]*-\s*.+\n?)+)"
    m = re.search(pattern, body)
    if not m:
        return []
    items: list[str] = []
    for line in m.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            item = stripped[2:].strip()
            if item and not _PLACEHOLDER_RE.match(item):
                items.append(item)
    return items


def _issue_stage(issue: dict) -> str:
    """Stage number from the issue body (**Stage:** N) or its milestone title.

    The old `stage: N` labels were retired in the Epics->Milestones migration;
    reading them yielded "?" for every issue.
    """
    stage = _body_field(issue.get("body") or "", "Stage")
    if stage:
        return stage.split()[0]
    ms = issue.get("milestone") or {}
    m = _STAGE_TITLE_RE.match(ms.get("title", "") or "")
    return m.group(1) if m else "?"


def render_user_needs_section(
    issues: list[dict],
    fr_issues: list[dict],
    nfr_issues: list[dict],
    req_map: dict,
) -> str:
    """Render UN-XXX list with acceptance, KPM, stage, status, and FR/NFR decomposition."""
    fr_index = {_extract_id(i["title"]): i for i in fr_issues}
    nfr_index = {_extract_id(i["title"]): i for i in nfr_issues}
    un_decomp = req_map.get("user_needs", {})

    lines = []
    for issue in sorted(issues, key=lambda i: _extract_id(i["title"])):
        un_id = _extract_id(issue["title"])
        title = issue["title"].split("] ", 1)[1] if "] " in issue["title"] else issue["title"]
        status = _get_label(issue, "status: ").upper() or "DEFINED"
        stage = _issue_stage(issue)
        acceptance = _body_field(issue["body"], "Acceptance")
        kpm = _body_field(issue["body"], "KPM") or "NONE"
        url = issue["html_url"]
        lines.append(f"[{un_id}]({url}): {title}")
        lines.append(f"Acceptance: {acceptance}")
        lines.append(f"KPM: {kpm}")
        lines.append(f"Stage: {stage}")
        lines.append(f"Status: {status}")

        decomp = un_decomp.get(un_id, {})
        parts = []
        for fr_id in decomp.get("functional_requirements", []):
            fr = fr_index.get(fr_id)
            if fr:
                parts.append(f"[{fr_id}]({fr['html_url']})")
        for nfr_id in decomp.get("non_functional_requirements", []):
            nfr = nfr_index.get(nfr_id)
            if nfr:
                parts.append(f"[{nfr_id}]({nfr['html_url']})")
        if parts:
            lines.append(f"Decomposes to: {', '.join(parts)}")

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


_KPM_COMMENT_RE = re.compile(
    r"`(?P<measured>[^`]+)`(?:\s*[-—]\s*\*\*(?P<status>\w+)\*\*)?"
)


def _latest_kpm_update(client, issue_number: int) -> tuple[str, str] | None:
    """(measurement, status) from the newest `## KPM Update` comment, if any.

    Measurements are posted as comments by github_comment.py update-kpm
    (body line: **KPM-1.2** - `1.8s on i7-7500U` - **passing**). Nothing ever
    writes the Last Measured/Status body fields, so without this fallback the
    dashboard rendered every KPM "untested" forever.
    """
    if client is None:
        return None
    try:
        r = client._session.get(
            f"{client.REST_BASE}/repos/{client.owner}/{client.repo}"
            f"/issues/{issue_number}/comments",
            params={"per_page": 100, "sort": "created", "direction": "desc"},
        )
        r.raise_for_status()
        for comment in r.json():
            body = comment.get("body") or ""
            if "KPM Update" not in body:
                continue
            m = _KPM_COMMENT_RE.search(body)
            if m:
                return m.group("measured"), (m.group("status") or "measured")
    except Exception:
        return None
    return None


def render_kpm_table(issues: list[dict], client=None) -> str:
    """Render KPM table with metric, target, owner, verified by, last measured, status."""
    rows = ["| KPM | Metric | Target | Owner | Verified By | Last Measured | Status |",
            "|:---|:---|:---|:---|:---|:---|:---|"]
    for issue in sorted(issues, key=lambda i: _extract_id(i["title"])):
        kpm_id = _extract_id(issue["title"])
        metric = issue["title"].split("] ", 1)[1] if "] " in issue["title"] else issue["title"]
        target = _body_field(issue["body"], "Target")
        owner = _body_field(issue["body"], "Owner")
        verified_by = _body_field(issue["body"], "Verified By")
        last = _body_field(issue["body"], "Last Measured")
        status = _body_field(issue["body"], "Status")
        if not last or not status:
            latest = _latest_kpm_update(client, issue.get("number"))
            if latest:
                last = last or latest[0]
                status = status or latest[1]
        last = last or "untested"
        status = status or "untested"
        url = issue["html_url"]
        rows.append(f"| [{kpm_id}]({url}) | {metric} | {target} | {owner} | {verified_by} | {last} | {status} |")
    return "\n".join(rows)


def render_vv_matrix(
    un_issues: list[dict],
    fr_issues: list[dict],
    nfr_issues: list[dict],
    kpm_issues: list[dict],
) -> str:
    """Render the V&V matrix table.

    Columns: ID · Type · Verified By · Validated By · Coverage
    Coverage flags: ✓ verified+validated, ⚠ partial, ✗ neither (unverified).
    """
    rows = [
        "| ID | Type | Verified By | Validated By | Coverage |",
        "|:---|:---|:---|:---|:---:|",
    ]

    def coverage(verified: list[str], validated: list[str], req_type: str) -> str:
        # UNs derive verification from children — no direct check here.
        # KPMs are self-validating.
        if req_type == "user-need":
            return "✓" if validated else "⚠"
        if req_type == "kpm":
            return "✓" if verified else "✗"
        if verified and validated:
            return "✓"
        if verified or validated:
            return "⚠"
        return "✗"

    def row_for(issue: dict, req_type_label: str, req_type_key: str) -> str:
        req_id = _extract_id(issue["title"])
        body = issue.get("body", "") or ""
        verified = _body_list_field(body, "Verified By")
        validated = _body_list_field(body, "Validated By")
        cov = coverage(verified, validated, req_type_key)
        v_cell = "<br>".join(f"`{x}`" for x in verified) if verified else "—"
        va_cell = "<br>".join(f"`{x}`" for x in validated) if validated else "—"
        url = issue["html_url"]
        return f"| [{req_id}]({url}) | {req_type_label} | {v_cell} | {va_cell} | {cov} |"

    grouped = (
        [(i, "UN", "user-need") for i in sorted(un_issues, key=lambda i: _extract_id(i["title"]))]
        + [(i, "FR", "fr") for i in sorted(fr_issues, key=lambda i: _extract_id(i["title"]))]
        + [(i, "NFR", "nfr") for i in sorted(nfr_issues, key=lambda i: _extract_id(i["title"]))]
        + [(i, "KPM", "kpm") for i in sorted(kpm_issues, key=lambda i: _extract_id(i["title"]))]
    )
    for issue, label, key in grouped:
        rows.append(row_for(issue, label, key))

    # Footer: coverage summary
    total = len(grouped)
    full = sum(
        1 for issue, _, key in grouped
        if coverage(_body_list_field(issue.get("body") or "", "Verified By"),
                    _body_list_field(issue.get("body") or "", "Validated By"),
                    key) == "✓"
    )
    rows.append("")
    rows.append(f"_Coverage: **{full} / {total}** requirements fully verified+validated. "
                f"Per `dev-docs/architecture/vv-matrix.md`._")
    return "\n".join(rows)




_COMPLETE_STATUSES = {"verified", "validated"}


def render_roadmap_section(milestones: list[dict], req_issues: list[dict]) -> str:
    """Render roadmap table from GitHub Milestones + requirement status labels.

    Each milestone titled like "Stage N — Title" becomes one row. Progress is
    the count of the milestone's requirement issues carrying a
    `status: verified` / `status: validated` label — the signal the pipeline
    actually writes (pr_rollup). Issue open/closed state is NOT used: nothing
    in the pipeline closes requirement issues, so counting closures rendered
    shipped stages as "Not Started".
    """
    per_ms: dict[str, tuple[int, int]] = {}
    for issue in req_issues:
        ms_title = (issue.get("milestone") or {}).get("title")
        if not ms_title:
            continue
        done, total = per_ms.get(ms_title, (0, 0))
        status = _get_label(issue, "status: ").lower()
        per_ms[ms_title] = (done + (1 if status in _COMPLETE_STATUSES else 0), total + 1)

    lines = ["| Stage | Title | Status | Progress |", "|:---|:---|:---|:---|"]
    stage_entries: list[tuple[int, str]] = []
    for ms in milestones:
        m = _STAGE_TITLE_RE.match(ms.get("title", ""))
        if not m:
            continue
        stage_num = int(m.group(1))
        title = ms["title"]
        url = ms["html_url"]
        done, total = per_ms.get(title, (0, 0))
        if ms.get("state") == "closed" or (total and done == total):
            status = "Done"
        elif done > 0:
            status = "In Progress"
        else:
            status = "Not Started"
        progress = f"{done}/{total}" if total else "—"
        stage_entries.append(
            (stage_num, f"| {stage_num} | [{title}]({url}) | {status} | {progress} |")
        )
    for _, row in sorted(stage_entries):
        lines.append(row)
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

    req_map = yaml.safe_load(
        Path("requirements/requirement-map.yml").read_text(encoding="utf-8"))

    print("Fetching Issues from GitHub...")
    un_issues = client.list_issues(labels="type: user-need", state="all")
    fr_issues = client.list_issues(labels="type: fr", state="all")
    nfr_issues = client.list_issues(labels="type: nfr", state="all")
    kpm_issues = client.list_issues(labels="type: kpm", state="all")
    milestones = client.list_milestones(state="all")

    # Regenerate living-user-needs.md
    un_path = DOCS / "living-user-needs.md"
    text = un_path.read_text(encoding="utf-8")
    text = inject_auto_section(
        text, "user_needs",
        render_user_needs_section(un_issues, fr_issues, nfr_issues, req_map),
    )
    un_path.write_text(text, encoding="utf-8")
    print(f"Updated {un_path}")

    # Regenerate architecture doc
    arch_path = DOCS / "photonforge-architecture.md"
    text = arch_path.read_text(encoding="utf-8")
    text = inject_auto_section(text, "fr_table", render_fr_table(fr_issues))
    text = inject_auto_section(text, "nfr_table", render_nfr_table(nfr_issues))
    text = inject_auto_section(text, "kpm_table", render_kpm_table(kpm_issues, client))
    text = inject_auto_section(
        text, "vv_matrix",
        render_vv_matrix(un_issues, fr_issues, nfr_issues, kpm_issues),
    )
    arch_path.write_text(text, encoding="utf-8")
    print(f"Updated {arch_path}")

    # Regenerate roadmap page
    roadmap_path = DOCS / "roadmap.md"
    if roadmap_path.exists():
        text = roadmap_path.read_text(encoding="utf-8")
        text = inject_auto_section(
            text, "roadmap",
            render_roadmap_section(milestones, un_issues + fr_issues + nfr_issues),
        )
        roadmap_path.write_text(text, encoding="utf-8")
        print(f"Updated {roadmap_path}")

    # Regenerate KPM dashboard page
    kpm_page_path = DOCS / "kpm-dashboard.md"
    if kpm_page_path.exists():
        text = kpm_page_path.read_text(encoding="utf-8")
        text = inject_auto_section(text, "kpm_table", render_kpm_table(kpm_issues, client))
        kpm_page_path.write_text(text, encoding="utf-8")
        print(f"Updated {kpm_page_path}")

    print("Done.")


if __name__ == "__main__":
    main()
