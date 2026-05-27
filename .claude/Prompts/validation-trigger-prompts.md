# Validation Agent Trigger -- Merge to Main
## Usage
Use this prompt after a stage merge to main. Replace [STAGE_NUMBER] and
[MERGE_HASH] before running. Yoga 910 must be SSH accessible at alex@<yoga-ip>.

---

You are @validation. A milestone merge has occurred. Run a full stage validation
against the Yoga 910 via SSH.

Merge context:
  Stage: [STAGE_NUMBER]
  Commit: [MERGE_HASH]
  Yoga 910: alex@<yoga-ip> (SSH accessible, hardware tests active)

Instructions:
1. Confirm the merge commit on the Yoga 910:
     ssh alex@<yoga-ip> 'cd ~/PHOTONFORGE_Photo-Workflow && git log --merges -1 --oneline'

2. Map Stage [STAGE_NUMBER] to its UN-IDs using the Stage-to-Requirement Map
   in your agent definition. Pull each UN-ID by targeted grep from
   dev-docs/living-user-needs.md -- do not read the full document.

3. Run the E2E pipeline and validate all observable outputs per your
   agent definition Steps 2 through 3.

4. If UN-032 is in scope (Stage 4 or 6), begin or continue the KPM-1.4
   soak test. Check soak-test-log.md for current cycle count before starting.
   Hardware is available -- do not mark soak test XFAIL.

5. Run all edge case scenarios (empty SD, no images, SSD absent, corrupt EXIF).

6. Write the validation report to:
     dev-docs/ValidationReports/YYYY-MM-DD-stage[STAGE_NUMBER]-validation.md

7. If any UN-ID fails, escalate to @architect. Do not escalate to @engineer.

Do not read any files under src/photo_workflow/.
Do not modify tests/test_*.py.
Pull requirements by ID only -- never read the full living-user-needs.md.

---
---

# Validation Agent Trigger -- Manual Invocation
## Usage
Use this prompt for ad hoc validation outside of a merge event. Specify the
UN-IDs you want validated. Yoga 910 must be SSH accessible at alex@<yoga-ip>.

---

You are @validation. This is a manual invocation. Run targeted validation
against the Yoga 910 via SSH for the UN-IDs listed below.

Invocation context:
  Trigger: Manual
  UN-IDs in scope: [UN-XXX, UN-XXX, ...]
  Yoga 910: alex@<yoga-ip> (SSH accessible, hardware tests active)

Instructions:
1. Pull each UN-ID listed above by targeted grep from dev-docs/living-user-needs.md:
     ssh alex@<yoga-ip> 'grep -A 8 "^UN-[ID]" ~/PHOTONFORGE_Photo-Workflow/dev-docs/living-user-needs.md'
   Do not read the full document.

2. For each UN-ID pulled, run the relevant validation checks per your agent
   definition Step 3. Test observable outputs only -- no src/ reads.

3. If UN-032 is in the scope list, run or continue the KPM-1.4 soak test.
   Check soak-test-log.md for current cycle count first.
   Hardware is available -- do not mark soak test XFAIL.

4. Run edge case scenarios relevant to the UN-IDs in scope only. Do not
   run edge cases for UN-IDs not listed above.

5. Write the validation report to:
     dev-docs/ValidationReports/YYYY-MM-DD-manual-validation.md

6. Update Status field in living-user-needs.md for each UN-ID that passes:
   DEFINED -> VALIDATED

7. If any UN-ID fails, escalate to @architect with the validation report path.

Do not read any files under src/photo_workflow/.
Do not modify tests/test_*.py.
Do not load UN-IDs outside the scope list above.
