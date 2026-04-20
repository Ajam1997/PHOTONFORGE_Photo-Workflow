<script lang="ts">
  import { deviceState } from "../stores/devices";
  import { listCartridges, reformatCartridge, type CartridgeInfo, type SidecarEvent } from "../lib/sidecar";

  let cartridges: CartridgeInfo[] = [];
  let loading = false;

  // Reformat state
  let reformatTarget: CartridgeInfo | null = null;
  let confirmLabel = "";
  let reformatRunning = false;
  let reformatStep = "";
  let reformatError = "";

  async function fetchCartridges() {
    loading = true;
    try {
      cartridges = await listCartridges();
    } finally {
      loading = false;
    }
  }

  // Re-fetch on mount and whenever device state changes (e.g. cartridge plug/unplug).
  $: if ($deviceState) fetchCartridges();

  function formatBytes(bytes: number): string {
    if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(1)} TB`;
    if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
    return `${(bytes / 1e6).toFixed(0)} MB`;
  }

  function usedPercent(c: CartridgeInfo): number {
    return ((c.size_bytes - c.free_bytes) / c.size_bytes) * 100;
  }

  function openReformat(c: CartridgeInfo) {
    reformatTarget = c;
    confirmLabel = "";
    reformatError = "";
  }

  function closeReformat() {
    reformatTarget = null;
    reformatRunning = false;
    reformatStep = "";
    reformatError = "";
  }

  async function confirmReformat() {
    if (!reformatTarget || confirmLabel !== reformatTarget.label) return;
    reformatRunning = true;
    reformatError = "";
    const target = reformatTarget;

    await reformatCartridge(
      `/dev/disk/by-label/${target.label}`,
      target.label,
      (event: SidecarEvent) => {
        if (event.type === "progress") {
          reformatStep = event.step;
        } else if (event.type === "reformat_done") {
          reformatRunning = false;
          closeReformat();
          fetchCartridges();
        } else if (event.type === "error") {
          reformatError = event.message;
          reformatRunning = false;
        }
      },
    );
  }
</script>

<div class="cartridge-panel">
  <h2>Cartridge Manager</h2>

  {#if loading}
    <p class="muted">Loading cartridges…</p>
  {:else if cartridges.length === 0}
    <p class="muted">No PHOTON cartridges mounted.</p>
  {:else}
    <div class="cartridge-list">
      {#each cartridges as c (c.label)}
        <div class="cartridge-card">
          <div class="card-header">
            <span class="cartridge-label">{c.label}</span>
            <span class="mount-point">{c.mount_point}</span>
          </div>
          <div class="space-bar-row">
            <div class="space-bar">
              <div class="space-fill" style="width: {usedPercent(c)}%"></div>
            </div>
            <span class="space-text">
              {formatBytes(c.free_bytes)} free of {formatBytes(c.size_bytes)}
            </span>
          </div>
          <button class="reformat-btn" on:click={() => openReformat(c)}>
            Reformat
          </button>
        </div>
      {/each}
    </div>
  {/if}

  {#if reformatTarget}
    <div class="sheet-overlay" role="dialog" aria-modal="true">
      <div class="sheet">
        {#if reformatRunning}
          <h3>Reformatting {reformatTarget.label}…</h3>
          <p class="muted">{reformatStep}</p>
        {:else}
          <h3>Reformat {reformatTarget.label}?</h3>
          <p class="warning">All data will be erased. This cannot be undone.</p>
          {#if reformatError}
            <p class="error">{reformatError}</p>
          {/if}
          <label for="confirm-label">Type the cartridge label to confirm:</label>
          <input
            id="confirm-label"
            bind:value={confirmLabel}
            placeholder={reformatTarget.label}
            autocomplete="off"
          />
          <div class="sheet-actions">
            <button class="cancel-btn" on:click={closeReformat}>Cancel</button>
            <button
              class="danger-btn"
              disabled={confirmLabel !== reformatTarget.label}
              on:click={confirmReformat}
            >
              Confirm Reformat
            </button>
          </div>
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .cartridge-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    padding: 2rem;
    gap: 1rem;
  }
  h2 { color: var(--text-primary, #fff); margin: 0; }
  .muted { color: var(--text-muted, #888); }
  .cartridge-list { display: flex; flex-direction: column; gap: 1rem; }
  .cartridge-card {
    background: var(--surface, #1a1a1a);
    border-radius: 0.5rem;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }
  .card-header { display: flex; justify-content: space-between; align-items: baseline; }
  .cartridge-label { color: var(--text-primary, #fff); font-weight: 600; }
  .mount-point { color: var(--text-muted, #888); font-size: 0.85rem; }
  .space-bar-row { display: flex; align-items: center; gap: 0.75rem; }
  .space-bar { flex: 1; height: 6px; background: var(--border, #333); border-radius: 3px; overflow: hidden; }
  .space-fill { height: 100%; background: var(--accent, #6366f1); }
  .space-text { color: var(--text-muted, #888); font-size: 0.8rem; white-space: nowrap; }
  .reformat-btn {
    padding: 0.5rem 1rem;
    background: transparent;
    color: var(--error, #ef4444);
    border: 1px solid var(--error, #ef4444);
    border-radius: 0.375rem;
    cursor: pointer;
    align-self: flex-end;
  }
  .sheet-overlay {
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.7);
    display: flex; align-items: flex-end; justify-content: center;
    z-index: 100;
  }
  .sheet {
    background: var(--surface-elevated, #222);
    border-radius: 1rem 1rem 0 0;
    padding: 2rem;
    width: 100%;
    max-width: 600px;
    display: flex; flex-direction: column; gap: 1rem;
  }
  h3 { color: var(--text-primary, #fff); margin: 0; }
  .warning { color: var(--warning, #f59e0b); }
  .error { color: var(--error, #ef4444); }
  label { color: var(--text-muted, #888); font-size: 0.9rem; }
  input {
    padding: 0.6rem;
    background: var(--surface, #1a1a1a);
    border: 1px solid var(--border, #333);
    border-radius: 0.375rem;
    color: var(--text-primary, #fff);
    font-size: 1rem;
  }
  .sheet-actions { display: flex; gap: 0.75rem; }
  .cancel-btn {
    flex: 1; padding: 0.75rem;
    background: transparent; color: var(--text-muted, #888);
    border: 1px solid var(--border, #333); border-radius: 0.375rem; cursor: pointer;
  }
  .danger-btn {
    flex: 1; padding: 0.75rem;
    background: var(--error, #ef4444); color: #fff;
    border: none; border-radius: 0.375rem; cursor: pointer;
  }
  .danger-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
