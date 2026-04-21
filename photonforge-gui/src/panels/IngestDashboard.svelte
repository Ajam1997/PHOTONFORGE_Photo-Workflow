<script lang="ts">
  import { deviceState } from "../stores/devices";
  import { ingestState, resetIngest } from "../stores/ingest";
  import { runIngest, type SidecarEvent } from "../lib/sidecar";

  $: canStart = $deviceState.sd_mounted && $deviceState.ssd_mounted;
  $: sourceLabel = $deviceState.sd_path ?? "No SD card";
  $: destLabel = $deviceState.ssd_label ?? "No cartridge";

  const STEP_LABELS: Record<string, string> = {
    copying: "Copying files",
    scoring: "Scoring images",
    naming: "Generating names",
    darktable: "Syncing to Darktable",
    formatting: "Formatting cartridge",
  };

  async function startIngest() {
    if (!canStart) return;
    const sd = $deviceState.sd_path!;
    const ssd = $deviceState.ssd_mount_point!;
    const db = `${ssd}/library.db`;

    ingestState.update(s => ({
      ...s,
      phase: "running",
      step: "copying",
      current: 0,
      total: 0,
      errorMsg: "",
      summary: null,
      activeCmd: null,
    }));

    try {
      const cmd = await runIngest(sd, ssd, db, (event: SidecarEvent) => {
        if (event.type === "progress") {
          ingestState.update(s => ({ ...s, step: event.step, current: event.current, total: event.total }));
        } else if (event.type === "done") {
          ingestState.update(s => ({ ...s, phase: "done", summary: event.summary, activeCmd: null }));
        } else if (event.type === "error") {
          ingestState.update(s => ({ ...s, phase: "idle", errorMsg: event.message, activeCmd: null }));
        }
      });
      ingestState.update(s => ({ ...s, activeCmd: cmd }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      ingestState.update(s => ({ ...s, phase: "idle", errorMsg: `Failed to start: ${msg}`, activeCmd: null }));
    }
  }

  function cancelIngest() {
    $ingestState.activeCmd?.kill().catch(() => {});
    ingestState.update(s => ({ ...s, phase: "idle", activeCmd: null }));
  }
</script>

<div class="ingest-panel">
  {#if $ingestState.phase === "idle"}
    <div class="idle-view">
      <h2>Ingest Photos</h2>
      <div class="device-row">
        <span class="label">Source</span>
        <span class="value" class:missing={!$deviceState.sd_mounted}>
          {$deviceState.sd_mounted ? sourceLabel : "Insert SD card"}
        </span>
      </div>
      <div class="device-row">
        <span class="label">Destination</span>
        <span class="value" class:missing={!$deviceState.ssd_mounted}>
          {$deviceState.ssd_mounted ? destLabel : "No cartridge mounted"}
        </span>
      </div>
      {#if $ingestState.errorMsg}
        <p class="error">{$ingestState.errorMsg}</p>
      {/if}
      <button class="primary-btn" disabled={!canStart} on:click={startIngest}>
        Start Ingest
      </button>
    </div>

  {:else if $ingestState.phase === "running"}
    <div class="running-view">
      <h2>{STEP_LABELS[$ingestState.step] ?? $ingestState.step}…</h2>
      <p class="progress-numbers">{$ingestState.current} / {$ingestState.total}</p>
      <div class="progress-bar">
        <div
          class="progress-fill"
          style="width: {$ingestState.total > 0 ? ($ingestState.current / $ingestState.total) * 100 : 0}%"
        ></div>
      </div>
      <button class="cancel-btn" on:click={cancelIngest}>Cancel</button>
    </div>

  {:else if $ingestState.phase === "done" && $ingestState.summary}
    <div class="done-view">
      <h2>Ingest Complete</h2>
      <div class="summary-card">
        <div class="summary-row"><span>Total files</span><strong>{$ingestState.summary.total}</strong></div>
        <div class="summary-row"><span>Duplicates skipped</span><strong>{$ingestState.summary.duplicates_skipped}</strong></div>
        <div class="summary-row"><span>Images scored</span><strong>{$ingestState.summary.scored}</strong></div>
        <div class="summary-row"><span>Elapsed</span><strong>{$ingestState.summary.elapsed_seconds.toFixed(1)}s</strong></div>
      </div>
      <button class="primary-btn" on:click={resetIngest}>New Ingest</button>
    </div>
  {/if}
</div>

<style>
  .ingest-panel {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 1.5rem;
    padding: 2rem;
  }
  .idle-view, .running-view, .done-view {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1rem;
    width: 100%;
    max-width: 480px;
  }
  h2 { color: var(--text-primary, #fff); font-size: 1.5rem; margin: 0; }
  .device-row {
    display: flex;
    justify-content: space-between;
    width: 100%;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--border, #333);
  }
  .label { color: var(--text-muted, #888); }
  .value { color: var(--text-primary, #fff); }
  .value.missing { color: var(--warning, #f59e0b); }
  .primary-btn {
    padding: 0.75rem 2rem;
    background: var(--accent, #6366f1);
    color: #fff;
    border: none;
    border-radius: 0.5rem;
    font-size: 1rem;
    cursor: pointer;
    width: 100%;
  }
  .primary-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .cancel-btn {
    padding: 0.75rem 2rem;
    background: transparent;
    color: var(--warning, #f59e0b);
    border: 1px solid var(--warning, #f59e0b);
    border-radius: 0.5rem;
    font-size: 1rem;
    cursor: pointer;
    width: 100%;
  }
  .progress-bar {
    width: 100%;
    height: 8px;
    background: var(--border, #333);
    border-radius: 4px;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    background: var(--accent, #6366f1);
    transition: width 0.2s ease;
  }
  .progress-numbers { color: var(--text-muted, #888); }
  .summary-card {
    width: 100%;
    background: var(--surface, #1a1a1a);
    border-radius: 0.5rem;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .summary-row {
    display: flex;
    justify-content: space-between;
    color: var(--text-muted, #888);
  }
  .summary-row strong { color: var(--text-primary, #fff); }
  .error { color: var(--error, #ef4444); }
</style>
