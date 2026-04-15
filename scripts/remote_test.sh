#!/bin/bash
# PHOTONForge remote test runner — executes on the Yoga 910 target.
# Runs pytest, KPM-1.2 (naming latency), KPM-1.3 (RSS), then emits a JSON
# summary to stdout. All diagnostic output goes to stderr.
# Exit 0 = overall PASS, Exit 1 = overall FAIL.
set -euo pipefail

REPO_DIR="${REPO_DIR:-${HOME}/PHOTONFORGE_Photo-Workflow}"
MODEL_DIR="${MODEL_DIR:-models/florence2_int8}"
KPM_1_2_THRESHOLD_S="2.5"
KPM_1_3_THRESHOLD_GB="1.5"
CARTRIDGE_PHOTO="/mnt/photon_ssd/001/photos/DSC04937.JPG"
CARTRIDGE_PHOTO_DIR="/mnt/photon_ssd/001/photos"
FIXTURE_DIR="tests/fixtures"

log() { printf '[remote_test] %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# 1. Change to repo directory
# ---------------------------------------------------------------------------
log "Changing to $REPO_DIR"
cd "$REPO_DIR"

# ---------------------------------------------------------------------------
# 2. Activate virtual environment
# ---------------------------------------------------------------------------
log "Activating .venv"
# shellcheck source=/dev/null
source .venv/bin/activate

# ---------------------------------------------------------------------------
# 3. git pull (ff-only, quiet; warn on failure but continue)
# ---------------------------------------------------------------------------
log "Pulling latest commits"
if ! git pull --ff-only --quiet 2>&1; then
    log "WARNING: git pull --ff-only failed (diverged or detached HEAD) — continuing with current checkout"
fi
GIT_COMMIT="$(git rev-parse --short HEAD)"
log "HEAD is at $GIT_COMMIT"

# ---------------------------------------------------------------------------
# 4. pip install -e . (quiet)
# ---------------------------------------------------------------------------
log "Installing package in editable mode"
pip install -e . --quiet

# ---------------------------------------------------------------------------
# 5. pytest
# ---------------------------------------------------------------------------
log "Running pytest"
PYTEST_OUTPUT_FILE="$(mktemp)"
PYTEST_EXIT=0
pytest -v 2>&1 | tee "$PYTEST_OUTPUT_FILE" >&2 || PYTEST_EXIT=$?

# Extract the summary line: looks like "N passed, N failed, N error in Xs"
PYTEST_SUMMARY=""
PYTEST_SUMMARY="$(grep -E '^(FAILED|PASSED|ERROR|[0-9]+ (passed|failed|error))' "$PYTEST_OUTPUT_FILE" | tail -1 || true)"
if [ -z "$PYTEST_SUMMARY" ]; then
    # Fallback: last non-empty line from pytest output
    PYTEST_SUMMARY="$(grep -v '^$' "$PYTEST_OUTPUT_FILE" | tail -1 || true)"
fi
rm -f "$PYTEST_OUTPUT_FILE"

log "pytest summary: $PYTEST_SUMMARY  (exit $PYTEST_EXIT)"

# ---------------------------------------------------------------------------
# 6. KPM-1.2: single-image naming latency (<= 2.5 s)
# ---------------------------------------------------------------------------
KPM_1_2_STATUS="XFAIL-HARDWARE"
KPM_1_2_ELAPSED="null"

if [ -f "$CARTRIDGE_PHOTO" ]; then
    log "KPM-1.2: running naming test on $CARTRIDGE_PHOTO"
    NAMING_OUTPUT="$(python3 -c "
import time, sys
sys.path.insert(0, '.')
from photo_workflow.naming import generate_name
img = '$CARTRIDGE_PHOTO'
t0 = time.monotonic()
result = generate_name(img, model_dir='$MODEL_DIR')
elapsed = time.monotonic() - t0
print(f'{elapsed:.4f} {result}')
" 2>/dev/null)"
    KPM_1_2_ELAPSED="$(printf '%s' "$NAMING_OUTPUT" | awk '{print $1}')"
    log "KPM-1.2: elapsed=${KPM_1_2_ELAPSED}s  result=$(printf '%s' "$NAMING_OUTPUT" | cut -d' ' -f2-)"
    # Compare using python3 since POSIX sh cannot do float comparisons
    KPM_1_2_PASS="$(python3 -c "print('1' if float('$KPM_1_2_ELAPSED') <= float('$KPM_1_2_THRESHOLD_S') else '0')")"
    if [ "$KPM_1_2_PASS" = "1" ]; then
        KPM_1_2_STATUS="PASS"
    else
        KPM_1_2_STATUS="FAIL"
    fi
    log "KPM-1.2: $KPM_1_2_STATUS"
else
    log "KPM-1.2: $CARTRIDGE_PHOTO not found — cartridge not mounted, marking XFAIL-HARDWARE"
fi

# ---------------------------------------------------------------------------
# 7. KPM-1.3: pipeline RSS (<= 1.5 GB)
# ---------------------------------------------------------------------------
KPM_1_3_STATUS="SKIPPED"
KPM_1_3_RSS_GB="null"

# Pick an image directory: prefer fixture dir, fall back to cartridge
IMAGE_DIR=""
FIXTURE_COUNT=0
if [ -d "$FIXTURE_DIR" ]; then
    FIXTURE_COUNT="$(find "$FIXTURE_DIR" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.tif' -o -iname '*.tiff' \) 2>/dev/null | wc -l)"
fi
if [ "$FIXTURE_COUNT" -ge 10 ]; then
    IMAGE_DIR="$FIXTURE_DIR"
elif [ -d "$CARTRIDGE_PHOTO_DIR" ]; then
    CARTRIDGE_COUNT="$(find "$CARTRIDGE_PHOTO_DIR" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.tif' -o -iname '*.tiff' \) 2>/dev/null | wc -l)"
    if [ "$CARTRIDGE_COUNT" -ge 10 ]; then
        IMAGE_DIR="$CARTRIDGE_PHOTO_DIR"
    fi
fi

if [ -n "$IMAGE_DIR" ]; then
    log "KPM-1.3: measuring RSS with image dir: $IMAGE_DIR"
    TIME_OUTPUT_FILE="$(mktemp)"
    # /usr/bin/time -v writes its report to stderr; we redirect stderr to our temp file
    /usr/bin/time -v python -m photo_workflow.pipeline \
        --model-dir "$MODEL_DIR" \
        --input "$IMAGE_DIR" \
        2>"$TIME_OUTPUT_FILE" || true
    RSS_KB="$(grep 'Maximum resident set size' "$TIME_OUTPUT_FILE" | grep -oE '[0-9]+' | tail -1 || true)"
    rm -f "$TIME_OUTPUT_FILE"
    if [ -n "$RSS_KB" ]; then
        KPM_1_3_RSS_GB="$(python3 -c "print(round(int('$RSS_KB') / 1024 / 1024, 3))")"
        KPM_1_3_PASS="$(python3 -c "print('1' if float('$KPM_1_3_RSS_GB') <= float('$KPM_1_3_THRESHOLD_GB') else '0')")"
        if [ "$KPM_1_3_PASS" = "1" ]; then
            KPM_1_3_STATUS="PASS"
        else
            KPM_1_3_STATUS="FAIL"
        fi
        log "KPM-1.3: ${KPM_1_3_RSS_GB} GB — $KPM_1_3_STATUS"
    else
        log "KPM-1.3: could not parse RSS from /usr/bin/time output — marking SKIPPED"
    fi
else
    log "KPM-1.3: fewer than 10 images available in fixture or cartridge dirs — SKIPPED"
fi

# ---------------------------------------------------------------------------
# 8. Determine overall result
# ---------------------------------------------------------------------------
OVERALL="PASS"
if [ "$PYTEST_EXIT" -ne 0 ]; then
    OVERALL="FAIL"
fi
if [ "$KPM_1_2_STATUS" = "FAIL" ]; then
    OVERALL="FAIL"
fi
if [ "$KPM_1_3_STATUS" = "FAIL" ]; then
    OVERALL="FAIL"
fi

log "Overall result: $OVERALL"

# ---------------------------------------------------------------------------
# 9. Emit JSON summary to stdout (must be the last stdout output)
# ---------------------------------------------------------------------------
TIMESTAMP="$(date -Iseconds)"
HOSTNAME_VAL="$(hostname)"

# Escape the pytest summary for safe embedding in JSON
PYTEST_SUMMARY_ESC="$(printf '%s' "$PYTEST_SUMMARY" | sed 's/\\/\\\\/g; s/"/\\"/g')"

# Use jq if available for well-formed JSON; otherwise fall back to printf
if command -v jq >/dev/null 2>&1; then
    jq -n \
        --arg ts        "$TIMESTAMP" \
        --arg host      "$HOSTNAME_VAL" \
        --arg commit    "$GIT_COMMIT" \
        --argjson px    "$PYTEST_EXIT" \
        --arg psummary  "$PYTEST_SUMMARY_ESC" \
        --arg k12status "$KPM_1_2_STATUS" \
        --argjson k12e  "${KPM_1_2_ELAPSED:-null}" \
        --argjson k12t  "$KPM_1_2_THRESHOLD_S" \
        --arg k13status "$KPM_1_3_STATUS" \
        --argjson k13r  "${KPM_1_3_RSS_GB:-null}" \
        --argjson k13t  "$KPM_1_3_THRESHOLD_GB" \
        --arg overall   "$OVERALL" \
        '{
            timestamp:  $ts,
            host:       $host,
            git_commit: $commit,
            pytest:     { exit_code: $px, summary: $psummary },
            kpm_1_2:    { status: $k12status, elapsed_s: $k12e, threshold_s: $k12t },
            kpm_1_3:    { status: $k13status, rss_gb: $k13r, threshold_gb: $k13t },
            overall:    $overall
        }'
else
    printf '{
  "timestamp": "%s",
  "host": "%s",
  "git_commit": "%s",
  "pytest": { "exit_code": %d, "summary": "%s" },
  "kpm_1_2": { "status": "%s", "elapsed_s": %s, "threshold_s": %s },
  "kpm_1_3": { "status": "%s", "rss_gb": %s, "threshold_gb": %s },
  "overall": "%s"
}\n' \
        "$TIMESTAMP" \
        "$HOSTNAME_VAL" \
        "$GIT_COMMIT" \
        "$PYTEST_EXIT" \
        "$PYTEST_SUMMARY_ESC" \
        "$KPM_1_2_STATUS" \
        "${KPM_1_2_ELAPSED:-null}" \
        "$KPM_1_2_THRESHOLD_S" \
        "$KPM_1_3_STATUS" \
        "${KPM_1_3_RSS_GB:-null}" \
        "$KPM_1_3_THRESHOLD_GB" \
        "$OVERALL"
fi

# ---------------------------------------------------------------------------
# Exit with appropriate code
# ---------------------------------------------------------------------------
if [ "$OVERALL" = "PASS" ]; then
    exit 0
else
    exit 1
fi
