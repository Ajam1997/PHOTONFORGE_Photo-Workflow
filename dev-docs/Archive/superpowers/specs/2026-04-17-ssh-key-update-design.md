# SSH Key Update — Design Spec

**Date:** 2026-04-17
**Status:** Approved
**Author:** Alex Meyer
**Scope:** Replace old `PhotonForge_new` SSH key with `photonforge_yoga` across config and agent definitions

---

## Problem

The `PhotonForge_new` ED25519 key used for SSH access to the Yoga 910 (`alex@10.27.27.10`) has been replaced with a new key at `~/.ssh/photonforge_yoga`. References to the old key name exist in six places across the project. The 2026-04-17 verification report recorded a full SSH blocker due to the old key; that blocker is now resolved but the record will mislead future agents unless annotated.

---

## Scope

Six files, one commit.

| File | Change |
|------|--------|
| `.claude/settings.local.json` | Replace all `PhotonForge_new` → `photonforge_yoga` |
| `.claude/agents/verification.md` | Add `-i ~/.ssh/photonforge_yoga` to every `ssh alex@10.27.27.10` call |
| `.claude/agents/validation.md` | Add `-i ~/.ssh/photonforge_yoga` to every `ssh alex@10.27.27.10` call |
| `.claude/agent-memory/verification/project_ssh_access.md` | Rewrite as resolved: key is `photonforge_yoga`, SSH working |
| `.claude/agent-memory/verification/MEMORY.md` | Update index line to reflect resolved state |
| `docs/VerificationReports/2026-04-17-verification-report.md` | Append RESOLVED addendum to BLOCKER section |

---

## Change Details

### settings.local.json
All allowlisted `Bash(ssh ...)` entries and `ssh-keygen` commands reference `~/.ssh/PhotonForge_new`. Replace the key name in-place. No structural changes.

### verification.md / validation.md
Pattern: `ssh alex@10.27.27.10` → `ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10`.
Applied to every occurrence. The `-i` flag is added immediately after `ssh` and before any other flags or the host. No other changes to command structure.

### project_ssh_access.md
Replace the entire body. New content: key is `photonforge_yoga`, located at `~/.ssh/photonforge_yoga` on the dev machine, accepted by Yoga 910 `authorized_keys`, SSH access confirmed working as of 2026-04-17. Remove the blocker guidance (action items, remediation steps).

### MEMORY.md
Update the single index entry for `project_ssh_access.md` from the "rejected / blocked" description to "SSH access confirmed working; key is photonforge_yoga."

### 2026-04-17-verification-report.md
Prepend a one-line `> **RESOLVED 2026-04-17:** SSH access restored. New key: \`~/.ssh/photonforge_yoga\`.` blockquote immediately after the `## BLOCKER: SSH Access Failure` heading. The rest of the section is preserved as historical record.

---

## Out of Scope

- No changes to `scripts/remote_test.sh` (uses the SSH target but not a key flag — relies on agent invocation context).
- No changes to `CLAUDE.md` (SSH target IP is correct, no key reference).
- No changes to `photonforge-architecture.md` (no key reference).
- The old key (`PhotonForge_new`) is not deleted from `~/.ssh/` — that is a host-side action outside this repo.
