"""Parse living-user-needs.md and photonforge-architecture.md into dicts."""
import re
from pathlib import Path


def parse_user_needs(path: Path) -> list[dict]:
    """Return list of UN dicts from living-user-needs.md."""
    text = path.read_text(encoding="utf-8")
    # Split on UN-NNN: lines
    blocks = re.split(r"(?=^UN-\d+:)", text, flags=re.MULTILINE)
    items = []
    for block in blocks:
        block = block.strip()
        if not block.startswith("UN-"):
            continue
        m_id = re.match(r"^(UN-\d+):\s*(.+)", block)
        if not m_id:
            continue
        un_id, title = m_id.group(1), m_id.group(2).strip()
        acceptance = _field(block, "Acceptance") or ""
        kpm = _field(block, "KPM") or "NONE"
        stage_str = _field(block, "Stage") or "0"
        status = _field(block, "Status") or "DEFINED"
        items.append({
            "id": un_id,
            "title": title,
            "acceptance": acceptance,
            "kpm": kpm,
            "stage": int(stage_str),
            "status": status.upper(),
        })
    return items


def parse_architecture(path: Path) -> dict:
    """Return {"functional_requirements": [...], "non_functional_requirements": [...], "kpms": [...]}."""
    text = path.read_text(encoding="utf-8")
    return {
        "functional_requirements": _parse_fr_table(text),
        "non_functional_requirements": _parse_nfr_table(text),
        "kpms": _parse_kpm_table(text),
    }


def _field(block: str, name: str) -> str | None:
    m = re.search(rf"^{name}:\s*(.+)$", block, re.MULTILINE)
    return m.group(1).strip() if m else None


def _parse_fr_table(text: str) -> list[dict]:
    """Parse the FR markdown table. Columns: ID | Description | Implementation"""
    section = _extract_section(text, "Functional Requirements", "Non-Functional Requirements")
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.match(r"FR-\d+\.\d+", cells[0]):
            rows.append({
                "id": cells[0],
                "description": cells[1],
                "implementation": cells[2],
            })
    return rows


def _parse_nfr_table(text: str) -> list[dict]:
    """Parse the NFR markdown table. Columns: ID | Description | Specification"""
    section = _extract_section(text, "Non-Functional Requirements", "Key Performance Measures")
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.match(r"NFR-\d+\.\d+", cells[0]):
            rows.append({
                "id": cells[0],
                "description": cells[1],
                "specification": cells[2],
            })
    return rows


def _parse_kpm_table(text: str) -> list[dict]:
    """Parse the KPM markdown table. Columns: KPM | Metric | Target | Owner | Verified By"""
    section = _extract_section(text, "Key Performance Measures", None)
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and re.match(r"KPM-\d+\.\d+", cells[0]):
            rows.append({
                "id": cells[0],
                "metric": cells[1],
                "target": cells[2],
                "owner": cells[3],
                "verified_by": cells[4],
            })
    return rows


def _extract_section(text: str, start_heading: str, end_heading: str | None) -> str:
    pattern = rf"###.*{re.escape(start_heading)}[^\n]*\n([\s\S]*?)"
    if end_heading:
        pattern += rf"(?=\n###.*{re.escape(end_heading)})"
    else:
        pattern += r"$"
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1) if m else ""
