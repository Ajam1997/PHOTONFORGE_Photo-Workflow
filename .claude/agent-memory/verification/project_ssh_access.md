---
name: Yoga 910 SSH access status
description: SSH key photonforge_yoga is accepted by Yoga 910; access confirmed working as of 2026-04-17
type: project
---

SSH access to `alex@10.27.27.10` (Yoga 910) is working.

Key: `photonforge_yoga` at `~/.ssh/photonforge_yoga` on the dev machine.
The key is present in `~/.ssh/authorized_keys` on the Yoga 910.

**Why:** A previous key was rejected due to an `authorized_keys` mismatch.
The new key (`photonforge_yoga`) was provisioned and verified on 2026-04-17.

**How to apply:** Use `-i ~/.ssh/photonforge_yoga` in all SSH commands targeting
`alex@10.27.27.10`. All agent definitions (verification.md, validation.md) include
this flag explicitly.
