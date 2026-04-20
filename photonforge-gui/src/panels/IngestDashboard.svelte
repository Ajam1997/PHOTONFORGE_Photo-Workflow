<script lang="ts">
  import { deviceState } from "../stores/devices";
  import { runIngest, type SidecarEvent, type DoneEvent } from "../lib/sidecar";
  import type { Command } from "@tauri-apps/plugin-shell";

  type IngestState = "idle" | "running" | "done";

  let state: IngestState = "idle";
  let step = "";
  let current = 0;
  let total = 0;
  let summary: DoneEvent["summary"] | null = null;
  let activeCmd: Command<string> | null = null;
  let errorMsg = "";

  const STEP_LABELS: Record<string, string> = {
    copying: "Copying files",
    scoring: "Scoring images",
    naming: "Generating names",
    darktable: "Syncing to Darktable",
    formatting: "Formatting cartridge",
  };

  $: canStart = $deviceState.sd_mounted && $deviceState.ssd_mounted;
  $: sourceLabel = $deviceState.sd_path ?? "No SD card";
  $: destLabel = $deviceState.ssd_label ?? "No cartridge";

  async function startIngest() {
    if (!canStart) return;
    const sd = $deviceState.sd_path!;
    const ssd = $deviceState.ssd_mount_point!;
    const db = `${ssd}/library.db`;

    state = "running";
    step = "copying";
    current = 0;
    total = 0;
    errorMsg = "";
    summary = null;

    activeCmd = await runIngest(sd, ssd, db, (event: SidecarEvent) => {
      if (event.type === "progress") {
        step = event.step;
        current = event.current;
        total = event.total;
      } else if (event.type === "done") {
        summary = event.summary;
        state = "done";
        activeCmd = null;
      } else if (event.type === "error") {
        errorMsg = event.message;
        state = "idle";
        activeCmd = null;
      }
    });
  }

  function cancelIngest() {
    activeCmd?.kill().catch(() => {});
    activeCmd = null;
    state = "idle";
  }

  function reset() {
    state = "idle";
    summary = null;
    errorMsg = "";
  }
</script>

<div class="ingest-panel">
  {#if state === "idle"}
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
      {#if errorMsg}
        <p class="error">{errorMsg}</p>
      {/if}
      <button class="primary-btn" disabled={!canStart} on:click={startIngest}>
        Start Ingest
      </button>
    </div>

  {:else if state === "running"}
    <div class="running-view">
      <h2>{STEP_LABELS[step] ?? step}…</h2>
      <p class="progress-numbers">{current} / {total}</p>
      <div class="progress-bar">
        <div
          class="progress-fill"
          style="width: {total > 0 ? (current / total) * 100 : 0}%"
        ></div>
      </div>
      <button class="cancel-btn" on:click={cancelIngest}>Cancel</button>
    </div>

  {:else if state === "done" && summary}
    <div class="done-view">
      <h2>Ingest Complete</h2>
      <div class="summary-card">
        <div class="summary-row"><span>Total files</span><strong>{summary.total}</strong></div>
        <div class="summary-row"><span>Duplicates skipped</span><strong>{summary.duplicates_skipped}</strong></div>
        <div class="summary-row"><span>Images scored</span><strong>{summary.scored}</strong></div>
        <div class="summary-row"><span>Elapsed</span><strong>{summary.elapsed_seconds.toFixed(1)}s</strong></div>
      </div>
      <button class="primary-btn" on:click={reset}>New Ingest</button>
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
