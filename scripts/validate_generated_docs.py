"""Sanity gate for the AUTO-generated docs.

Run after scripts/generate_docs.py (regen-docs.yml does this) so corrupted
renderer output fails the workflow instead of being committed and exported to
the wiki. The corruptions this guards against all shipped at least once:
CRLF-swallowed field captures (duplicated blocks), literal "(none yet)"
counted as V&V evidence, and `Stage: ?` breaking doc_parser.

Exit code 0 = clean, 1 = findings (printed one per line).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "dev-docs"

AUTO_RE = re.compile(r"<!-- AUTO:(\w+) -->(.*?)<!-- /AUTO:\1 -->", re.DOTALL)

# One rendered UN block must contain each field exactly once; a duplicated
# "**KPM:**"-style tail means the CRLF capture bug is back.
_DUP_FIELD_RE = re.compile(r"^(Acceptance|KPM|Stage|Status): ", re.MULTILINE)


def auto_sections(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in AUTO_RE.finditer(text)]


def check() -> list[str]:
    problems: list[str] = []

    for name in (
        "living-user-needs.md",
        "photonforge-architecture.md",
        "roadmap.md",
        "kpm-dashboard.md",
    ):
        path = DOCS / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for key, content in auto_sections(text):
            if "\r" in content:
                problems.append(f"{name}: AUTO:{key} contains CR characters")
            if re.search(r"`\(?none( yet)?\)?`", content, re.IGNORECASE):
                problems.append(
                    f"{name}: AUTO:{key} renders a '(none yet)' placeholder as evidence"
                )
            if "**KPM:**" in content or "**Acceptance:**" in content:
                problems.append(
                    f"{name}: AUTO:{key} leaks raw '**Field:**' markup "
                    "(field capture ran past its terminator)"
                )

    # The living doc must stay machine-readable for @validation.
    lun = DOCS / "living-user-needs.md"
    if lun.exists():
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.doc_parser import parse_user_needs

        try:
            items = parse_user_needs(lun)
            if not items:
                problems.append("living-user-needs.md: doc_parser found zero UNs")
            else:
                dup_ids = {i["id"] for i in items if [x["id"] for x in items].count(i["id"]) > 1}
                if dup_ids:
                    problems.append(
                        f"living-user-needs.md: duplicated UN blocks: {sorted(dup_ids)}"
                    )
        except Exception as e:  # parse crash = corrupted output
            problems.append(f"living-user-needs.md: doc_parser crashed: {e}")

    return problems


def main() -> None:
    problems = check()
    for p in problems:
        print(f"DOC-VALIDATE: {p}")
    if problems:
        sys.exit(1)
    print("Generated docs validated: clean.")


if __name__ == "__main__":
    main()
