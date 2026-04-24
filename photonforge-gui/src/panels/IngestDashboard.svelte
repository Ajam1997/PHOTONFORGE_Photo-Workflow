<script lang="ts">
  import { deviceState } from "../stores/devices";
  import { ingestState, resetIngest } from "../stores/ingest";
  import { pipelineSettings } from "../stores/pipeline";
  import { runIngest, type SidecarEvent, type StageDoneEvent } from "../lib/sidecar";

  $: canStart = $deviceState.sd_mounted && $deviceState.ssd_mounted;
  $: sourceLabel = $deviceState.sd_path ?? "No SD card";
  $: destLabel = $deviceState.ssd_label ?? "No cartridge";

  // Stage definitions — order matches execution order
  const STAGE_DEFS = [
    { key: "copy",      label: "Copy",           required: true  },
    { key: "dedup",     label: "Deduplication",  required: false },
    { key: "scoring",   label: "Scoring",        required: false },
    { key: "naming",    label: "AI Naming",      required: false },
    { key: "darktable", label: "Darktable sync", required: false },
  ] as const;

  type StageKey = typeof STAGE_DEFS[number]["key"];
  type StageStatus = "pending" | "active" | "done" | "skipped";

  interface StageEntry {
    key: StageKey;
    label: string;
    required: boolean;
    status: StageStatus;
    current: number;
    total: number;
    meta: Record<string, number> | undefined;
  }

  function isEnabled(key: StageKey): boolean {
    if (key === "copy") return true;
    return $pipelineSettings[key as keyof typeof $pipelineSettings] as boolean;
  }

  function stageStatus(key: StageKey): StageStatus {
    if (!isEnabled(key)) return "skipped";
    if ($ingestState.stageDone[key]) return "done";
    if ($ingestState.step === key) return "active";
    return "pending";
  }

  $: stageList = STAGE_DEFS.map((s): StageEntry => ({
    ...s,
    status: stageStatus(s.key),
    current: $ingestState.step === s.key ? $ingestState.current : 0,
    total: $ingestState.step === s.key ? $ingestState.total : 0,
    meta: $ingestState.stageDone[s.key],
  }));

  function stageMeta(entry: StageEntry): string {
    if (!entry.meta) return "";
    const m = entry.meta;
    if (entry.key === "copy")      return `${m.copied ?? 0} files`;
    if (entry.key === "dedup")     return `${m.dupes_found ?? 0} dupes removed`;
    if (entry.key === "scoring")   return `${m.scored ?? 0} scored`;
    if (entry.key === "naming")    return `${m.named ?? 0} named`;
    if (entry.key === "darktable") return `${m.xmp_written ?? 0} XMP, ${m.db_upserted ?? 0} DB rows`;
    return "";
  }

  function stageIcon(status: StageStatus): string {
    if (status === "done")    return "✓";
    if (status === "active")  return "▶";
    if (status === "skipped") return "—";
    return "○";
  }

  async function startIngest() {
    if (!canStart) return;
    const sd  = $deviceState.sd_path!;
    const ssd = $deviceState.ssd_mount_point!;
    const db  = `${ssd}/library.db`;

    ingestState.update(s => ({
      ...s,
      phase: "running",
      step: "copy",
      current: 0,
      total: 0,
      errorMsg: "",
      summary: null,
      activeCmd: null,
      stageDone: {},
      sdEjected: false,
    }));

    try {
      const cmd = await runIngest(sd, ssd, db, (event: SidecarEvent) => {
        if (event.type === "progress") {
          ingestState.update(s => ({ ...s, step: event.step, current: event.current, total: event.total }));
        } else if (event.type === "stage_done") {
          const e = event as StageDoneEvent;
          const meta: Record<string, number> = {};
          if (e.copied !== undefined) meta.copied = e.copied;
          if (e.dupes_found !== undefined) meta.dupes_found = e.dupes_found;
          if (e.scored !== undefined) meta.scored = e.scored;
          if (e.named !== undefined) meta.named = e.named;
          if (e.xmp_written !== undefined) meta.xmp_written = e.xmp_written;
          if (e.db_upserted !== undefined) meta.db_upserted = e.db_upserted;
          ingestState.update(s => ({
            ...s,
            stageDone: { ...s.stageDone, [e.stage]: meta },
          }));
        } else if (event.type === "sd_ejected") {
          ingestState.update(s => ({ ...s, sdEjected: true }));
        } else if (event.type === "done") {
          ingestState.update(s => ({ ...s, phase: "done", summary: event.summary, activeCmd: null }));
        } else if (event.type === "error") {
          ingestState.update(s => ({ ...s, phase: "idle", errorMsg: event.message, activeCmd: null }));
        }
      }, {
        skipDedup:     !$pipelineSettings.dedup,
        skipScoring:   !$pipelineSettings.scoring,
        skipNaming:    !$pipelineSettings.naming,
        skipDarktable: !$pipelineSettings.darktable,
      });
      ingestState.update(s => ({ ...s, activeCmd: cmd }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      ingestState.update(s => ({ ...s, phase: "idle", errorMsg: `Failed to start: ${msg}`, activeCmd: null }));
    }
  }

  function cancelIngest() {
    $ingestState.activeCmd?.kill().catch((err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err);
      ingestState.update(s => ({ ...s, errorMsg: `Cancel failed: ${msg}` }));
    });
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

      <div class="pipeline-section">
        <h3>Pipeline</h3>
        {#each STAGE_DEFS as stage}
          <div class="stage-checkbox-row">
            {#if stage.required}
              <input type="checkbox" checked disabled />
            {:else}
              <input
                type="checkbox"
                checked={$pipelineSettings[stage.key as keyof typeof $pipelineSettings]}
                on:change={(e) => pipelineSettings.update(s => ({ ...s, [stage.key]: e.currentTarget.checked }))}
              />
            {/if}
            <span class="stage-checkbox-label">{stage.label}</span>
            {#if stage.required}
              <span class="required-badge">Required</span>
            {/if}
          </div>
        {/each}
      </div>

      <button class="primary-btn" disabled={!canStart} on:click={startIngest}>
        Start Ingest
      </button>
    </div>

  {:else if $ingestState.phase === "running"}
    <div class="running-view">
      <h2>Processing…</h2>

      <div class="stage-list">
        {#each stageList as entry (entry.key)}
          <div class="stage-row"
            class:stage-active={entry.status === "active"}
            class:stage-done={entry.status === "done"}
            class:stage-skipped={entry.status === "skipped"}
          >
            <span class="stage-icon">{stageIcon(entry.status)}</span>
            <span class="stage-name">{entry.label}</span>
            {#if entry.status === "active"}
              <div class="stage-progress">
                <span class="stage-count">{entry.current} / {entry.total}</span>
                <div class="mini-bar">
                  <div class="mini-fill" style="width: {entry.total > 0 ? (entry.current / entry.total) * 100 : 0}%"></div>
                </div>
              </div>
            {:else if entry.status === "done"}
              <span class="stage-meta">{stageMeta(entry)}</span>
            {:else if entry.status === "skipped"}
              <span class="stage-meta">(skipped)</span>
            {/if}
          </div>
        {/each}

        {#if $ingestState.sdEjected}
          <div class="sd-ejected-row">
            <span class="stage-icon eject-icon">⏏</span>
            <span class="stage-name">SD card ejected</span>
            <span class="stage-meta">you can continue shooting</span>
          </div>
        {/if}
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
        <div class="summary-row"><span>Images named</span><strong>{$ingestState.summary.named}</strong></div>
        <div class="summary-row"><span>XMP written</span><strong>{$ingestState.summary.xmp_written}</strong></div>
        <div class="summary-row"><span>DB rows upserted</span><strong>{$ingestState.summary.db_upserted}</strong></div>
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
    padding: 2.5rem 3rem;
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
  h3 { color: var(--text-primary, #fff); font-size: 1rem; margin: 0; align-self: flex-start; }
  .device-row {
    display: flex; justify-content: space-between;
    width: 100%; padding: 0.5rem 0;
    border-bottom: 1px solid var(--border, #333);
  }
  .label { color: var(--text-muted, #888); }
  .value { color: var(--text-primary, #fff); }
  .value.missing { color: var(--warning, #f59e0b); }

  /* Pipeline checkboxes */
  .pipeline-section {
    width: 100%;
    background: var(--surface, #1a1a1a);
    border-radius: 0.5rem;
    padding: 1rem;
    display: flex; flex-direction: column; gap: 0.6rem;
  }
  .stage-checkbox-row {
    display: flex; align-items: center; gap: 0.6rem;
    color: var(--text-primary, #fff); font-size: 0.9rem;
  }
  .stage-checkbox-label { flex: 1; }
  .required-badge {
    font-size: 0.7rem; padding: 0.1rem 0.4rem;
    background: rgba(99,102,241,0.2); color: var(--accent, #6366f1);
    border-radius: 0.25rem;
  }

  /* Stage list */
  .stage-list { width: 100%; display: flex; flex-direction: column; gap: 0.5rem; }
  .stage-row {
    display: flex; align-items: center; gap: 0.75rem;
    padding: 0.5rem 0.75rem;
    border-radius: 0.375rem;
    background: var(--surface, #1a1a1a);
    font-size: 0.9rem;
  }
  .stage-row.stage-active  { background: rgba(99,102,241,0.1); border: 1px solid rgba(99,102,241,0.3); }
  .stage-row.stage-done    { opacity: 0.8; }
  .stage-row.stage-skipped { opacity: 0.4; }
  .stage-icon { width: 1.2rem; text-align: center; color: var(--text-muted, #888); }
  .stage-row.stage-done  .stage-icon { color: #4ade80; }
  .stage-row.stage-active .stage-icon { color: var(--accent, #6366f1); }
  .stage-name { flex: 1; color: var(--text-primary, #fff); }
  .stage-meta { color: var(--text-muted, #888); font-size: 0.8rem; }
  .stage-progress { display: flex; align-items: center; gap: 0.5rem; }
  .stage-count { color: var(--text-muted, #888); font-size: 0.8rem; white-space: nowrap; }
  .mini-bar { width: 80px; height: 4px; background: var(--border, #333); border-radius: 2px; overflow: hidden; }
  .mini-fill { height: 100%; background: var(--accent, #6366f1); transition: width 0.2s; }
  .sd-ejected-row {
    display: flex; align-items: center; gap: 0.75rem;
    padding: 0.5rem 0.75rem;
    border-radius: 0.375rem;
    background: rgba(99,102,241,0.08);
    font-size: 0.9rem;
  }
  .eject-icon { color: var(--accent, #6366f1); }

  /* Buttons */
  .primary-btn {
    padding: 0.75rem 2rem; background: var(--accent, #6366f1);
    color: #fff; border: none; border-radius: 0.5rem;
    font-size: 1rem; cursor: pointer; width: 100%;
  }
  .primary-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .cancel-btn {
    padding: 0.75rem 2rem; background: transparent;
    color: var(--warning, #f59e0b); border: 1px solid var(--warning, #f59e0b);
    border-radius: 0.5rem; font-size: 1rem; cursor: pointer; width: 100%;
  }

  /* Summary */
  .summary-card {
    width: 100%; background: var(--surface, #1a1a1a);
    border-radius: 0.5rem; padding: 1rem;
    display: flex; flex-direction: column; gap: 0.5rem;
  }
  .summary-row { display: flex; justify-content: space-between; color: var(--text-muted, #888); }
  .summary-row strong { color: var(--text-primary, #fff); }
  .error { color: var(--error, #ef4444); }
</style>
