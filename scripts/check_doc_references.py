"""Reference-integrity checker: repo paths mentioned in docs must exist.

Phase 2 of the docs overhaul plan. Two failure classes this catches:

1. A doc mentions a repo file (``src/photo_workflow/manifest.py``) that no
   longer exists — the rot that accumulated invisibly when modules were
   deleted while ~15 docs kept citing them.
2. A relative markdown link points at a file that doesn't exist — today
   these silently become broken wiki pages.

Modes:
  full scan (default)      — every finding, exit 1 if any. Nightly report.
  --pr-mode BASE_REF       — diff-aware: flag only references to files that
                             THIS branch deleted/renamed relative to
                             BASE_REF. This is the PR-check mode; it never
                             blames a PR for pre-existing rot.

Dated-history directories (Archive/, SystemReviews/, drift-reports/,
superpowers/ plans) legitimately reference deleted code and are exempt
from BOTH modes: they are frozen records, so "you deleted a file they
cite" is non-actionable by design (first proven by the Phase-4 archive
PR itself, where the gate flagged archived migration notes for citing
the old paths of files the same PR archived).

Suppression: a line containing ``doc-ref: ignore`` is skipped (for
deliberately hypothetical examples).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Where doc prose lives.
DOC_GLOBS = (
    "README.md",
    "CLAUDE.md",
    "dev-docs/**/*.md",
    "requirements/**/*.md",
    "docs/**/*.md",
    "deploy/**/*.md",
    ".claude/agents/*.md",
)

# Dated history: full of legitimately dead references.
EXEMPT_DIRS = (
    "dev-docs/Archive/",
    "dev-docs/SystemReviews/",
    "dev-docs/drift-reports/",
    "dev-docs/migration/",
    "dev-docs/superpowers/",
)

# Repo-path shapes worth checking. Requires a known top-level dir and a file
# extension, so prose like "the src tree" or glob examples don't match.
# The leading (?<![\w-]) is load-bearing: plain \b still matches mid-token after
# a hyphen, so "dt-config/library.db" was read as a reference to the top-level
# "config/" dir and reported missing. Hyphenated dir names are normal here
# (dt-config is the portable-drive layout), so anchor on "not preceded by a word
# char or a hyphen" instead.
PATH_RE = re.compile(
    r"(?<![\w-])((?:src|scripts|tests|deploy|lua|tools|config|docs|dev-docs|requirements|models|prompts|artifacts)"
    r"/[\w][\w./-]*\.(?:py|sh|lua|yml|yaml|md|css|json|toml|ps1|bat|spec|onnx|db))\b"
)

# Relative markdown links: [text](target). External/anchor links excluded.
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")

IGNORE_MARKER = "doc-ref: ignore"

# Placeholder-ish path segments that mean "example, not a real file".
_PLACEHOLDER_CHARS = set("<>{}*$")


def _doc_files() -> list[Path]:
    files: list[Path] = []
    for pattern in DOC_GLOBS:
        files.extend(REPO.glob(pattern))
    out = []
    for f in sorted(set(files)):
        rel = f.relative_to(REPO).as_posix()
        if any(rel.startswith(d) for d in EXEMPT_DIRS):
            continue
        out.append(f)
    return out


def _iter_refs(doc: Path):
    """Yield (lineno, kind, target) for path mentions and relative links."""
    rel_dir = doc.parent
    for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
        if IGNORE_MARKER in line:
            continue
        for m in PATH_RE.finditer(line):
            target = m.group(1)
            if _PLACEHOLDER_CHARS & set(target):
                continue
            yield lineno, "path", target
        for m in LINK_RE.finditer(line):
            target = m.group(1)
            if "://" in target or target.startswith("mailto:") or _PLACEHOLDER_CHARS & set(target):
                continue
            # Only check link targets that look like repo files.
            if "." not in Path(target).name:
                continue
            resolved = (rel_dir / target).resolve()
            try:
                yield lineno, "link", resolved.relative_to(REPO).as_posix()
            except ValueError:
                continue  # points outside the repo


def full_scan() -> list[str]:
    problems: list[str] = []
    for doc in _doc_files():
        rel = doc.relative_to(REPO).as_posix()
        for lineno, kind, target in _iter_refs(doc):
            if not (REPO / target).exists():
                problems.append(f"{rel}:{lineno}: {kind} reference to missing file: {target}")
    return problems


def _deleted_by_branch(base_ref: str) -> set[str]:
    """Paths that exist at base_ref but not at HEAD (deleted or renamed away)."""
    out = subprocess.run(
        ["git", "diff", "--name-status", "--diff-filter=DR", f"{base_ref}...HEAD"],
        capture_output=True, text=True, check=True, cwd=REPO,
    ).stdout
    deleted: set[str] = set()
    for line in out.splitlines():
        parts = line.split("\t")
        if parts and parts[0].startswith(("D", "R")) and len(parts) >= 2:
            deleted.add(parts[1])
    return deleted


def pr_scan(base_ref: str) -> list[str]:
    deleted = _deleted_by_branch(base_ref)
    if not deleted:
        return []
    problems: list[str] = []
    for doc in _doc_files():
        rel = doc.relative_to(REPO).as_posix()
        for lineno, kind, target in _iter_refs(doc):
            if target in deleted:
                problems.append(
                    f"{rel}:{lineno}: references {target}, which this branch deletes"
                )
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pr-mode", metavar="BASE_REF", default=None,
                    help="Only flag references to files deleted by HEAD vs BASE_REF")
    args = ap.parse_args()

    problems = pr_scan(args.pr_mode) if args.pr_mode else full_scan()
    for p in problems:
        print(f"DOC-REF: {p}")
    if problems:
        print(f"\n{len(problems)} broken documentation reference(s).")
        sys.exit(1)
    print("Documentation references: clean.")


if __name__ == "__main__":
    main()
