---
name: KPM measurement evidence as of 2026-04-18
description: First formal @verification measurements of KPM-1.2 and KPM-1.3; KPM-1.2 FAILING under cold-start
type: project
---

**KPM-1.2 (inference <= 2.5s/image) -- FAIL (as of 2026-04-18):**
- First formal @verification measurement on 2026-04-18 at commit 843e109.
- Cold-start (fresh process, ONNX sessions loaded from disk): 5.970s / 4.445s -- FAIL.
- Warm (second call in same process, sessions in memory): 2.232s -- PASS.
- Root cause: generate_name() reloads ONNX sessions on every call. No caching.
- Prior engineer-reported 1525ms figure was not reproduced; likely measured warm.
- Failure report: docs/VerificationReports/2026-04-18-failure-843e109.md
- Action: @engineer must implement ONNX session caching so a single fresh-process call is <= 2.5s.

**KPM-1.3 (RSS <= 1.5 GB) -- PASS (fixture scope only, 2026-04-18):**
- First formal @verification measurement on 2026-04-18 at commit 843e109.
- Measured: 68280 KB = 0.065 GB via /usr/bin/time -v over tests/fixtures/ (6 synthetic images).
- Well within 1.5 GB target, but note: naming fallback was active (no real Florence-2 inference).
- Formal measurement under live model load (real inference path) is still pending.
- Measurement method confirmed: /usr/bin/time -v, parse "Maximum resident set size".

**KPM-1.1 (ingest >= 80% USB 3.0 = 500 MB/s):**
- Not triggered by Stage 7.1 commits (ingest.py unchanged).
- Requires SD and SSD both mounted. Mark XFAIL-HARDWARE if either absent.

**Why:** SSH access was the blocking condition for all formal KPM measurement until 2026-04-17.
**How to apply:** Use ORT_NUM_THREADS=2 for KPM-1.2. Always measure cold-start (fresh process).
KPM-1.3 must be re-run once ONNX session caching is in place (to measure real inference RSS).
