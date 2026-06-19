# Engineering Notes

Running notes on open bugs and known performance gaps. These are not specs — they're observations captured during development sessions for follow-up.

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
