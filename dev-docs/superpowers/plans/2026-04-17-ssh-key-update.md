# SSH Key Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every reference to the old `PhotonForge_new` SSH key with the new `photonforge_yoga` key across config, agent definitions, agent memory, and the verification report.

**Architecture:** Pure find-and-replace across six files. No code is written or deleted — only key names, path strings, and status prose are updated. All changes land in one commit at the end.

**Tech Stack:** Git, plain text editing. No Python, no tests.

---

## File Map

| File | Change Type |
|------|-------------|
| `.claude/settings.local.json` | Replace `PhotonForge_new` → `photonforge_yoga` (key name in allowlisted Bash commands) |
| `.claude/agents/verification.md` | Add `-i ~/.ssh/photonforge_yoga` to every `ssh alex@10.27.27.10` call |
| `.claude/agents/validation.md` | Add `-i ~/.ssh/photonforge_yoga` to every `ssh alex@10.27.27.10` call |
| `.claude/agent-memory/verification/project_ssh_access.md` | Rewrite body: key resolved, new key name |
| `.claude/agent-memory/verification/MEMORY.md` | Update index entry: resolved state |
| `docs/VerificationReports/2026-04-17-verification-report.md` | Prepend RESOLVED note to BLOCKER section |

---

### Task 1: Update settings.local.json

**Files:**
- Modify: `.claude/settings.local.json`

- [ ] **Step 1: Read the file and confirm all occurrences of `PhotonForge_new`**

Run:
```bash
grep -n "PhotonForge_new" .claude/settings.local.json
```
Expected: ~10 lines referencing `PhotonForge_new` in allowlisted Bash commands.

- [ ] **Step 2: Replace all occurrences**

Use the Edit tool with `replace_all: true`:
- `old_string`: `PhotonForge_new`
- `new_string`: `photonforge_yoga`

Apply to `.claude/settings.local.json`.

- [ ] **Step 3: Verify no old key name remains**

Run:
```bash
grep -n "PhotonForge_new" .claude/settings.local.json
```
Expected: no output.

- [ ] **Step 4: Verify new key name is present**

Run:
```bash
grep -c "photonforge_yoga" .claude/settings.local.json
```
Expected: count >= 10.

---

### Task 2: Update verification.md agent definition

**Files:**
- Modify: `.claude/agents/verification.md`

- [ ] **Step 1: Read the file and count bare `ssh alex@10.27.27.10` occurrences**

Run:
```bash
grep -n "ssh alex@10.27.27.10" .claude/agents/verification.md
```
Expected: ~8 lines, none with `-i` flag yet.

- [ ] **Step 2: Replace all bare ssh calls with keyed calls**

Use the Edit tool with `replace_all: true`:
- `old_string`: `ssh alex@10.27.27.10`
- `new_string`: `ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10`

Apply to `.claude/agents/verification.md`.

- [ ] **Step 3: Verify no bare calls remain**

Run:
```bash
grep -n "ssh alex@" .claude/agents/verification.md | grep -v "\-i ~/.ssh/photonforge_yoga"
```
Expected: no output.

---

### Task 3: Update validation.md agent definition

**Files:**
- Modify: `.claude/agents/validation.md`

- [ ] **Step 1: Read the file and count bare `ssh alex@10.27.27.10` occurrences**

Run:
```bash
grep -n "ssh alex@10.27.27.10" .claude/agents/validation.md
```
Expected: ~25 lines, none with `-i` flag yet.

- [ ] **Step 2: Replace all bare ssh calls with keyed calls**

Use the Edit tool with `replace_all: true`:
- `old_string`: `ssh alex@10.27.27.10`
- `new_string`: `ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10`

Apply to `.claude/agents/validation.md`.

- [ ] **Step 3: Verify no bare calls remain**

Run:
```bash
grep -n "ssh alex@" .claude/agents/validation.md | grep -v "\-i ~/.ssh/photonforge_yoga"
```
Expected: no output.

---

### Task 4: Rewrite agent memory — project_ssh_access.md

**Files:**
- Modify: `.claude/agent-memory/verification/project_ssh_access.md`

- [ ] **Step 1: Read the current file**

Read `.claude/agent-memory/verification/project_ssh_access.md` to confirm it describes the old blocked state.

- [ ] **Step 2: Overwrite with resolved content**

Write the following to `.claude/agent-memory/verification/project_ssh_access.md`:

```markdown
---
name: Yoga 910 SSH access status
description: SSH key photonforge_yoga is accepted by Yoga 910; access confirmed working as of 2026-04-17
type: project
---

SSH access to `alex@10.27.27.10` (Yoga 910) is working.

Key: `photonforge_yoga` at `~/.ssh/photonforge_yoga` on the dev machine.
The key is present in `~/.ssh/authorized_keys` on the Yoga 910.

**Why:** The previous key (`PhotonForge_new`) was rejected due to an `authorized_keys`
mismatch. The new key was provisioned and verified on 2026-04-17.

**How to apply:** Use `-i ~/.ssh/photonforge_yoga` in all SSH commands targeting
`alex@10.27.27.10`. All agent definitions (verification.md, validation.md) include
this flag explicitly.
```

---

### Task 5: Update agent memory index — MEMORY.md

**Files:**
- Modify: `.claude/agent-memory/verification/MEMORY.md`

- [ ] **Step 1: Read the current MEMORY.md**

Read `.claude/agent-memory/verification/MEMORY.md` to see the current index entry.

- [ ] **Step 2: Update the stale index line**

Use the Edit tool:
- `old_string`: the existing line referencing `project_ssh_access.md` (will contain "rejected" or "blocked" language)
- `new_string`: `- [Yoga 910 SSH access status](project_ssh_access.md) — SSH working; key is photonforge_yoga at ~/.ssh/photonforge_yoga`

---

### Task 6: Annotate the 2026-04-17 verification report

**Files:**
- Modify: `docs/VerificationReports/2026-04-17-verification-report.md`

- [ ] **Step 1: Read the BLOCKER section heading location**

Run:
```bash
grep -n "BLOCKER" docs/VerificationReports/2026-04-17-verification-report.md
```
Expected: one line with `## BLOCKER: SSH Access Failure`.

- [ ] **Step 2: Insert RESOLVED note immediately after the heading**

Use the Edit tool:
- `old_string`:
```
## BLOCKER: SSH Access Failure

**All remote test execution
```
- `new_string`:
```
## BLOCKER: SSH Access Failure

> **RESOLVED 2026-04-17:** SSH access restored. New key: `~/.ssh/photonforge_yoga`. Re-trigger @verification to execute blocked tests and KPM benchmarks.

**All remote test execution
```

- [ ] **Step 3: Verify the note appears correctly**

Run:
```bash
grep -A 3 "## BLOCKER" docs/VerificationReports/2026-04-17-verification-report.md
```
Expected: heading, then the RESOLVED blockquote, then the original text.

---

### Task 7: Final verification and commit

- [ ] **Step 1: Confirm no remaining references to the old key name**

Run:
```bash
grep -rn "PhotonForge_new" .claude/ docs/VerificationReports/
```
Expected: no output.

- [ ] **Step 2: Confirm new key name is present in all expected files**

Run:
```bash
grep -rln "photonforge_yoga" .claude/ docs/VerificationReports/
```
Expected: 5 files listed —
`.claude/settings.local.json`,
`.claude/agents/verification.md`,
`.claude/agents/validation.md`,
`.claude/agent-memory/verification/project_ssh_access.md`,
`docs/VerificationReports/2026-04-17-verification-report.md`

(MEMORY.md does not contain the key path itself, only a prose description — that is correct.)

- [ ] **Step 3: Stage and commit all six files**

```bash
git add .claude/settings.local.json \
        .claude/agents/verification.md \
        .claude/agents/validation.md \
        .claude/agent-memory/verification/project_ssh_access.md \
        .claude/agent-memory/verification/MEMORY.md \
        docs/VerificationReports/2026-04-17-verification-report.md
git commit -m "config: update SSH key references PhotonForge_new → photonforge_yoga"
```
