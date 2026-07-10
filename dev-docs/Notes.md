# Engineering Notes

Running notes on open bugs and known performance gaps. These are not specs — they're observations captured during development sessions for follow-up.

---

## Open Naming Bugs

**Status:** Bug 1 open; Bug 2 resolved as expected behavior (see below)
**Source:** Test batch run — see the historical ValidationReports test-output
capture (that `docs/` directory no longer exists; check git history if needed)

Two separate bugs observed during a real photo batch test:

### Bug 1 — Model outputs one of three fixed strings

The naming model outputs only one of:
- `"yes"`
- `"no"`
- `"answering does not require reading"`

instead of a genuine semantic caption. This is distinct from the earlier fix (which produced real output in isolation) — the batch run context or input preprocessing may be feeding the model differently.

### Bug 2 — File not renamed on disk

> **Resolved (2026-07-10): this is expected behavior per the current design.**
> The semantic name is written to the Darktable description field and the XMP
> `photon:SemanticName` field; files are deliberately **not renamed** on disk
> (see IF-3.2). The "expected behaviour" below is the superseded original
> expectation, kept for history.

The semantic name is written to the XMP sidecar but the actual file is not renamed. Originally expected behaviour:
- Original filename stored in XMP (e.g. `DSC04937.ARW`)
- New semantic filename stored in XMP (e.g. `cat-sitting-on-windowsill.ARW`)
- File renamed on disk to the semantic name
