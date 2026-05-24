# Engineering Notes

Running notes on open bugs and known performance gaps. These are not specs — they're observations captured during development sessions for follow-up.

---

## KPM-1.2 Performance Gap — Florence-2 Inference Speed

**Status:** Open
**Target:** ≤ 2.5s / image (KPM-1.2)
**Measured:** 6.7s on i7-7500U

`generate_name()` is working — it produces real semantic slugs (e.g. `DSC04937.JPG` → `answering-does-not-require-reading`). The functional fix is done. The speed is the problem.

**Root cause:** No KV-cache. The current implementation uses `decoder_model` for every step, which is O(n²) in sequence length. Each token generation re-processes all previous tokens from scratch.

**Investigation path:** Switch to `decoder_with_past_model_int8.onnx` for step 2+ (generate one token with `decoder_model`, then feed the returned `past_key_values` into `decoder_with_past` for subsequent steps). This is blocked by a fixed 16-token input dimension in the `decoder_with_past` model — needs reshaping or re-export.

**Commits that fixed the functional output:**

| Commit | Fix |
|---|---|
| `7edfc51` | Added `_build_empty_past_kv` — resolved missing past_key_values on step 0 |
| `95e9cd4` | Switched from broken merged decoder to `decoder_model` + `decoder_with_past` split pair |
| `14dbd13` | Dropped padded `decoder_with_past` (garbled output); `decoder_model` for all steps |
| `1728f72` | Fixed decoder seed from BOS=0 to `[decoder_start=2, forced_bos=0]` |
| `b3aae18` | Root cause: replaced `<CAPTION>` (subword-decomposed) with `<cap>` (id=51269, registered special token) |

---

## Open Naming Bugs

**Status:** Open
**Source:** Test batch run — see `docs/ValidationReports/PhotoWorkFlowTestOutput` (deleted; check git history if needed)

Two separate bugs observed during a real photo batch test:

### Bug 1 — Model outputs one of three fixed strings

The naming model outputs only one of:
- `"yes"`
- `"no"`
- `"answering does not require reading"`

instead of a genuine semantic caption. This is distinct from the earlier fix (which produced real output in isolation) — the batch run context or input preprocessing may be feeding the model differently.

### Bug 2 — File not renamed on disk

The semantic name is written to the XMP sidecar but the actual file is not renamed. Expected behaviour:
- Original filename stored in XMP (e.g. `DSC04937.ARW`)
- New semantic filename stored in XMP (e.g. `cat-sitting-on-windowsill.ARW`)
- File renamed on disk to the semantic name
