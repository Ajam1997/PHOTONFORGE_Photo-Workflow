#!/usr/bin/env python3
"""Migrate dev-docs/ markdown files to GitHub Wiki format.

Wiki is a flat namespace â€” all pages live at root level.
This script:
  1. Clones the wiki repo to a temp dir
  2. Copies dev-docs/ files with remapped names
  3. Rewrites internal .md links to wiki page names
  4. Generates _Sidebar.md from mkdocs.yml nav
  5. Commits and pushes
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "Ajam1997/PHOTONFORGE_Photo-Workflow"
WIKI_URL = f"https://github.com/{REPO}.wiki.git"
DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"

# Map from docs-relative path â†’ wiki page name (no .md)
PAGE_MAP: dict[str, str] = {
    "index.md": "Home",
    "roadmap.md": "Roadmap",
    "living-user-needs.md": "Living-User-Needs",
    "photonforge-architecture.md": "Architecture",
    "kpm-dashboard.md": "KPM-Dashboard",
    "Notes.md": "Notes",
    "github-integration-subprojects.md": "GitHub-Integration",
    "drift-reports/index.md": "Drift-Reports",
    "research/index.md": "Research",
    "research/scoring-redesign.md": "Research-Scoring-Redesign",
    "research/2026-05-24-genre-back-training-research.md": "Research-Genre-Back-Training",
    "superpowers/index.md": "Specs-and-Plans",
    "github-issues/genre-detection-back-training.md": "Issue-Genre-Back-Training",
    "github-issues/multi-genre-tagging.md": "Issue-Multi-Genre-Tagging",
    "architecture/scoring-module-contracts.md": "Arch-Scoring-Contracts",
    "architecture/stage-6-engineer-brief.md": "Arch-Stage6-Brief",
    "architecture/subject-enabled-subscores.md": "Arch-Subject-Subscores",
}

# Auto-map superpowers/specs, superpowers/plans, PlanningBriefs
for _subdir, _prefix in [
    ("superpowers/specs", "Spec"),
    ("superpowers/plans", "Plan"),
    ("PlanningBriefs", "Brief"),
]:
    for _f in (DOCS_DIR / _subdir.replace("/", "\\")).glob("*.md") if sys.platform == "win32" else (DOCS_DIR / _subdir).glob("*.md"):
        _rel = f"{_subdir}/{_f.name}"
        PAGE_MAP[_rel] = f"{_prefix}-{_f.stem}"


def resolve_link(source_rel: str, link_target: str) -> str | None:
    """Resolve a relative .md link to a wiki page name, or None if external."""
    if link_target.startswith(("http://", "https://", "#")):
        return None
    anchor = ""
    if "#" in link_target:
        link_target, anchor = link_target.split("#", 1)
        anchor = "#" + anchor
    # Resolve relative to the source file's directory
    source_dir = Path(source_rel).parent
    resolved = (source_dir / link_target).as_posix()
    # Normalize: remove leading ./
    resolved = re.sub(r"^\./", "", resolved)
    # Try exact match
    if resolved in PAGE_MAP:
        return PAGE_MAP[resolved] + anchor
    # Try stripping leading dev-docs/ prefix if accidentally present
    stripped = re.sub(r"^dev-docs/", "", resolved)
    if stripped in PAGE_MAP:
        return PAGE_MAP[stripped] + anchor
    return None


def rewrite_links(content: str, source_rel: str) -> str:
    """Replace all relative .md links with wiki page links."""
    def replacer(m: re.Match) -> str:
        text, target = m.group(1), m.group(2)
        wiki_name = resolve_link(source_rel, target)
        if wiki_name is not None:
            return f"[{text}]({wiki_name})"
        return m.group(0)

    return re.sub(r"\[([^\]]+)\]\(([^)]+\.md[^)]*|[^)]*#[^)]*)\)", replacer, content)


SIDEBAR = """\
## PHOTONForge

**[Home](Home)**

---

### Core Docs
- [Roadmap](Roadmap)
- [User Needs](Living-User-Needs)
- [Architecture](Architecture)
- [KPM Dashboard](KPM-Dashboard)

---

### Research
- [Overview](Research)
- [Scoring Redesign](Research-Scoring-Redesign)
- [Genre Back-Training](Research-Genre-Back-Training)

---

### Specs
- [Overview](Specs-and-Plans)
- [Multi-Genre & Back-Training](Spec-2026-05-25-multi-genre-and-back-training-design)
- [Genre-Aware Scoring](Spec-2026-05-21-genre-aware-scoring-design)
- [Agent Write-back](Spec-2026-05-23-agent-writeback-design)
- [Scheduled Automation](Spec-2026-05-23-scheduled-automation-design)
- [PR Automation](Spec-2026-05-23-pr-automation-design)
- [Pipeline v2](Spec-2026-05-20-pipeline-v2-design)
- [Darktable Lua Plugin](Spec-2026-05-13-darktable-lua-plugin-design)
- [Stage-Based CLI](Spec-2026-05-12-stage-based-cli-design)
- [Terminal Flash Bugfix](Spec-2026-05-14-terminal-flash-bugfix-design)
- [Cartridge Identity](Spec-2026-04-23-cartridge-identity-redesign)
- [Ingest Pipeline](Spec-2026-04-20-ingest-pipeline-design)
- [Cartridge Provisioning](Spec-2026-04-20-cartridge-provisioning-design)
- [Stage 7.2 Ingest](Spec-2026-04-19-stage-7-2-ingest-cartridge-design)
- [Stage 7.1 GUI](Spec-2026-04-17-stage-7-1-gui-scaffold-design)
- [SSH Key Update](Spec-2026-04-17-ssh-key-update-design)
- [Soak Test Notifications](Spec-2026-04-16-soak-test-notifications-design)
- [Doc Reorganisation](Spec-2026-05-23-doc-reorg-design)
- [GitHub Scaffolding](Spec-2026-05-23-github-scaffolding-design)

---

### Plans
- [Genre-Aware Scoring](Plan-2026-05-21-genre-aware-scoring)
- [Pipeline v2](Plan-2026-05-20-pipeline-v2)
- [Lua Plugin](Plan-2026-05-13-lua-plugin)
- [Python Engine Changes](Plan-2026-05-13-python-engine-changes)
- [Stage-Based CLI](Plan-2026-05-12-stage-based-cli)
- [Terminal Flash Bugfix](Plan-2026-05-14-terminal-flash-bugfix)
- [Cartridge Identity](Plan-2026-04-23-cartridge-identity-redesign)
- [Ingest Pipeline](Plan-2026-04-20-ingest-pipeline)
- [Cartridge Provisioning](Plan-2026-04-20-cartridge-provisioning)
- [Stage 7.2 Ingest](Plan-2026-04-19-stage-7-2-ingest-cartridge)
- [Stage 7.1 GUI](Plan-2026-04-17-stage-7-1-gui-scaffold)
- [SSH Key Update](Plan-2026-04-17-ssh-key-update)
- [Soak Test Notifications](Plan-2026-04-16-soak-test-notifications)
- [Doc Reorg](Plan-2026-05-23-doc-reorg)
- [GitHub Scaffolding](Plan-2026-05-23-github-scaffolding)

---

### Briefs & Build Logs
- [2026-04-17 Brief](Brief-2026-04-17-planning-brief)
- [2026-04-17 Build Log](Brief-2026-04-17-build-log)
- [2026-04-16 Build Log](Brief-2026-04-16-build-log)
- [2026-04-15 Brief](Brief-2026-04-15-planning-brief)
- [2026-04-15 Build Log](Brief-2026-04-15-build-log)

---

### Architecture Notes
- [Scoring Contracts](Arch-Scoring-Contracts)
- [Stage 6 Brief](Arch-Stage6-Brief)
- [Subject Subscores](Arch-Subject-Subscores)

---

### GitHub Issues
- [Genre Back-Training](Issue-Genre-Back-Training)
- [Multi-Genre Tagging](Issue-Multi-Genre-Tagging)

---

### Other
- [Drift Reports](Drift-Reports)
- [GitHub Integration](GitHub-Integration)
- [Notes](Notes)
"""


def run(cmd: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}")
        print(result.stderr)
        sys.exit(1)


def main() -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="photonforge-wiki-"))
    print(f"Working in {tmpdir}")

    # Configure gh as git credential helper so HTTPS pushes are authenticated
    subprocess.run(["gh", "auth", "setup-git"], capture_output=True)

    # The wiki is a separate git repo at <repo>.wiki.git
    print("Cloning wiki repo...")
    clone_result = subprocess.run(
        ["git", "clone", WIKI_URL, str(tmpdir / "wiki")],
        capture_output=True, text=True,
    )
    wiki_dir = tmpdir / "wiki"
    if clone_result.returncode != 0:
        # Wiki repo may be empty on first use â€” init it manually
        print("Wiki appears empty, initialising...")
        wiki_dir.mkdir(exist_ok=True)
        run(["git", "init"], cwd=wiki_dir)
        run(["git", "remote", "add", "origin", WIKI_URL], cwd=wiki_dir)

    # Clear existing wiki content (keep .git)
    for f in wiki_dir.glob("*.md"):
        f.unlink()

    # Copy and transform each doc file
    print("Copying pages...")
    for rel_path, wiki_name in PAGE_MAP.items():
        src = DOCS_DIR / Path(rel_path)
        if not src.exists():
            print(f"  SKIP (not found): {rel_path}")
            continue
        content = src.read_text(encoding="utf-8")
        content = rewrite_links(content, rel_path)
        dest = wiki_dir / f"{wiki_name}.md"
        dest.write_text(content, encoding="utf-8")
        print(f"  {rel_path} -> {wiki_name}.md")

    # Write sidebar and footer
    (wiki_dir / "_Sidebar.md").write_text(SIDEBAR, encoding="utf-8")
    (wiki_dir / "_Footer.md").write_text(
        "_PHOTONForge â€” private repo, collaborators only. "
        f"[Source](https://github.com/{REPO})_\n",
        encoding="utf-8",
    )

    # Commit and push
    print("Committing...")
    run(["git", "config", "user.email", "alex.ajam.97@gmail.com"], cwd=wiki_dir)
    run(["git", "config", "user.name", "Alex Meyer"], cwd=wiki_dir)
    run(["git", "add", "-A"], cwd=wiki_dir)
    run(
        ["git", "commit", "-m", "docs: migrate from gh-pages to wiki"],
        cwd=wiki_dir,
    )

    print("Pushing...")
    push_result = subprocess.run(
        ["git", "push", "--set-upstream", "origin", "master"],
        cwd=wiki_dir, capture_output=True, text=True,
    )
    if push_result.returncode != 0:
        # Try 'main' branch name
        push_result2 = subprocess.run(
            ["git", "push", "--set-upstream", "origin", "main"],
            cwd=wiki_dir, capture_output=True, text=True,
        )
        if push_result2.returncode != 0:
            print("Push failed:")
            print(push_result.stderr)
            print(push_result2.stderr)
            sys.exit(1)

    print(f"\nDone. Wiki: https://github.com/{REPO}/wiki")
    shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
