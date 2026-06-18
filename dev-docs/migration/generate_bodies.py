#!/usr/bin/env python3
"""Phase 4 migration tool — normalize Issue bodies to template form.

Strategy: PRESERVE the original body verbatim, surgically update only
the fields the requirement-map improves, and APPEND the missing
template V&V sections. Nothing is rebuilt from scratch — rich bodies
(e.g. FR-1.7.1/1.7.2 design proposals, KPM measurement notes) are kept
intact.

Reads:
  - dev-docs/migration/issue-bodies-original/_snapshot.json
  - requirements/requirement-map.yml
Writes:
  - dev-docs/migration/issue-bodies-new/<NNN>.md

One-shot migration tool; delete with dev-docs/migration/ after apply.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "dev-docs/migration/issue-bodies-original/_snapshot.json"
RMAP = ROOT / "requirements/requirement-map.yml"
OUT = ROOT / "dev-docs/migration/issue-bodies-new"
OUT.mkdir(parents=True, exist_ok=True)

issues = json.load(open(SNAP, encoding="utf-8"))
rmap = yaml.safe_load(open(RMAP, encoding="utf-8"))
un, fr, nfr, kpm = (rmap[k] for k in (
    "user_needs", "functional_requirements",
    "non_functional_requirements", "kpms"))

issue_to_rid: dict[int, str] = {}
for table in (un, fr, nfr, kpm):
    for rid, e in table.items():
        if e.get("issue"):
            issue_to_rid[e["issue"]] = rid

un_stage = {u: sn for sn, sd in rmap["stages"].items()
            for u in (sd.get("user_needs") or [])}

FR_TEST = {
    "FR-1.1": "tests/test_ingest.py", "FR-1.2": "tests/test_grouping.py",
    "FR-1.3": "tests/test_dedup.py", "FR-1.4": "tests/test_sharpness.py",
    "FR-1.5": "tests/test_composition.py", "FR-1.6": "tests/test_exposure.py",
    "FR-1.7": "tests/test_naming.py", "FR-1.7.1": "tests/test_genre_trainer.py",
    "FR-1.7.2": "tests/test_genre_router.py", "FR-1.8": "tests/test_darktable.py",
    "FR-1.9": "tests/test_cartridge_manager.py", "FR-1.10": "tests/test_cartridge.py",
}

# Measurement methods for the 3 KPMs whose original body lacks a Notes block.
KPM_METHOD = {
    "KPM-1.2": "Time Florence-2 INT8 single-image inference on the i7-7500U "
               "target over the fixture corpus; report mean seconds per image.",
    "KPM-1.1": "Benchmark sustained ingest throughput against the USB 3.0 "
               "theoretical maximum on the i7-7500U; report achieved MB/s as "
               "a percentage of the bus ceiling.",
    "KPM-1.4": "Run 50 cartridge eject cycles through the safe-eject path; "
               "after each cycle run SQLite `PRAGMA integrity_check` on "
               "library.db; pass = zero corruption across all 50 cycles.",
}


def fix_paths(b: str) -> str:
    return b.replace("docs/architecture/", "dev-docs/architecture/") \
            .replace("docs/research/", "dev-docs/research/")


def has(body: str, label: str) -> bool:
    return re.search(rf"^\*\*{re.escape(label)}:\*\*", body, re.M) is not None


def set_line(body: str, label: str, value: str) -> str:
    """Replace a single-line `**Label:** ...` value in place."""
    return re.sub(rf"^(\*\*{re.escape(label)}:\*\*)\s*.*$",
                  rf"\1 {value}", body, count=1, flags=re.M)


def rename_label(body: str, old: str, new: str) -> str:
    return re.sub(rf"^\*\*{re.escape(old)}:\*\*", f"**{new}:**", body, count=1, flags=re.M)


def status_of(it) -> str:
    for l in it["labels"]:
        if l["name"].startswith("status:"):
            return l["name"].split(":", 1)[1].strip()
    return ""


def labels_of(it):
    return {l["name"] for l in it["labels"]}


def append_sections(body: str, *sections: str) -> str:
    body = body.rstrip()
    return body + "\n\n" + "\n\n".join(s.strip() for s in sections) + "\n"


def do_un(it, rid, body):
    e = un[rid]
    kpms = e.get("kpms") or []
    # Update KPM field if the map knows a KPM the body recorded as NONE.
    if kpms and has(body, "KPM"):
        cur = re.search(r"^\*\*KPM:\*\*\s*(.+)$", body, re.M)
        if cur and cur.group(1).strip().upper() in ("NONE", ""):
            body = set_line(body, "KPM", ", ".join(kpms))
    if not has(body, "Validated By"):
        stage = un_stage.get(rid) or "?"
        line = (f"- e2e: Stage {stage} milestone — {rid} demonstrated end-to-end"
                if status_of(it) == "verified" else "- (none yet)")
        body = append_sections(body, f"**Validated By:**\n{line}")
    return body


def do_fr(it, rid, body):
    parts = []
    if not has(body, "Verified By"):
        test = FR_TEST.get(rid)
        parts.append(f"**Verified By:**\n- pytest: {test}" if test
                     else "**Verified By:**\n- (none yet)")
    if not has(body, "Validated By"):
        parents = fr[rid].get("fr_to_uns") or []
        stage = un_stage.get(parents[0]) if parents else None
        line = (f"- e2e: Stage {stage} milestone — {parents[0]} demonstrated end-to-end"
                if status_of(it) == "verified" and stage else "- (none yet)")
        parts.append(f"**Validated By:**\n{line}")
    return append_sections(body, *parts) if parts else body


def do_nfr(it, rid, body):
    parts = []
    if not has(body, "Linked Budget"):
        parts.append("**Linked Budget:** NONE")
    if not has(body, "Verified By"):
        parts.append("**Verified By:**\n- (none yet)")
    if not has(body, "Validated By"):
        parts.append("**Validated By:**\n- (none yet)")
    return append_sections(body, *parts) if parts else body


def do_kpm(it, rid, body):
    # Notes (rich measurement detail) -> Measurement Method
    if has(body, "Notes") and not has(body, "Measurement Method"):
        body = rename_label(body, "Notes", "Measurement Method")
    # Status -> KPM Status (template field name)
    if has(body, "Status") and not has(body, "KPM Status"):
        body = rename_label(body, "Status", "KPM Status")
    parts = []
    if not has(body, "Measurement Method"):
        m = KPM_METHOD.get(rid)
        if m:
            parts.append(f"**Measurement Method:** {m}")
    if not has(body, "Linked Requirements"):
        e = kpm[rid]
        linked = ((e.get("parent_uns") or []) + (e.get("parent_nfrs") or [])
                  + (e.get("parent_frs") or []))
        parts.append(f"**Linked Requirements:** {', '.join(linked) if linked else 'NONE'}")
    return append_sections(body, *parts) if parts else body


def do_out(it, body):
    lbls = labels_of(it)
    kind = ("Bug" if "bug" in lbls else
            "Enhancement" if "enhancement" in lbls else "Engineering task")
    if not body.strip():
        body = "_(original body was empty)_"
    return f"**Type:** {kind} ({it['state'].capitalize()})\n\n" + body.strip() + "\n"


for it in issues:
    n = it["number"]
    body = fix_paths(it["body"] or "")
    rid = issue_to_rid.get(n)

    # ── Phase-4 structural decisions (special cases) ──
    if n == 62:
        # Renumbered NFR-2.4 dup -> NFR-2.5; spec refined to match UN-041.
        body = set_line(body, "Specification",
                        "User-visible notification (zenity/desktop) when the SD "
                        "card is safe to remove after photos transfer to the SSD. "
                        "Distinct from NFR-2.4 (SD-inserted-without-SSD dialog).")
        body = set_line(body, "Parent UN", "UN-041")
        out = do_nfr(it, "NFR-2.5", body)
    elif n == 75:
        # Fixture Corpus: reclassify type:fr -> verification fixture.
        hdr = ("**Type:** Verification fixture (reclassified from type:fr in Phase 4)\n\n"
               "**Used by:** KPM-1.6, KPM-1.7, KPM-1.8, KPM-1.10 (labeled reference "
               "set for measuring dedup FP rate, naming validity, scoring determinism, "
               "and session-grouping precision).\n\n"
               "**Location:** `tests/fixtures/` + `corpus/`\n\n")
        out = hdr + body.strip() + "\n"
    elif rid in un:
        out = do_un(it, rid, body)
    elif rid in fr:
        out = do_fr(it, rid, body)
    elif rid in nfr:
        out = do_nfr(it, rid, body)
    elif rid in kpm:
        out = do_kpm(it, rid, body)
    else:
        out = do_out(it, body)
    (OUT / f"{n:03d}.md").write_text(out, encoding="utf-8")

# ── NEW Issue: NFR-2.2 Resource Budget (created on apply) ──
nfr22 = (
    "**Parent UN:** UN-030\n\n"
    "**Specification:** Resource budget for the full scoring pipeline on the "
    "i7-7500U target:\n"
    "- Peak RSS <= 1.5 GB during the score stage (CLIP + YOLO + Florence-2 INT8 "
    "all resident)\n"
    "- Peak CPU <= 80% of available logical cores (leave headroom for the "
    "Darktable UI)\n\n"
    "**Linked Budget:** NONE (this NFR *is* the resource budget)\n\n"
    "**Verified By:**\n- (none yet)\n\n"
    "**Validated By:**\n- (none yet)\n\n"
    "_Created in Phase 4 to parent KPM-1.3 (Peak RSS) and KPM-1.9 (CPU Cap), "
    "which previously cited a nonexistent NFR-2.2. Constraint defined in "
    "CLAUDE.md (NFR-2.2)._\n"
)
(OUT / "NEW-NFR-2.2.md").write_text(nfr22, encoding="utf-8")

print(f"Generated {len(issues)} bodies + 1 new (NFR-2.2). (preserve+append)")
