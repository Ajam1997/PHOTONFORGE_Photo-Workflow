<script lang="ts">
  import { deviceState } from "../stores/devices";
  import { listCartridges, listDrives, provisionCartridge, reformatCartridge, type CartridgeInfo, type DriveInfo, type ProvisionEvent, type SidecarEvent } from "../lib/sidecar";

  let cartridges: CartridgeInfo[] = [];
  let loading = false;

  // Provision state
  let showProvisionSheet = false;
  let availableDrives: DriveInfo[] = [];
  let drivesLoading = false;
  let provisionDevice = "";
  let provisionLabel = "";
  let provisionForceRepartition = false;
  let provisionDryRun = false;
  let provisionRunning = false;
  let provisionStep = "";
  let provisionCurrent = 0;
  let provisionTotal = 5;
  let provisionError = "";

  $: nextId = calculateNextId(cartridges);
  $: selectedDrive = availableDrives.find((d) => d.device === provisionDevice) ?? null;

  function calculateNextId(carts: CartridgeInfo[]): string {
    const existing = carts.map((c) => {
      const match = c.label.match(/PHOTON-(\d{3})/);
      return match ? parseInt(match[1], 10) : 0;
    });
    for (let i = 1; i < 1000; i++) {
      if (!existing.includes(i)) return `PHOTON-${String(i).padStart(3, "0")}`;
    }
    return "PHOTON-999";
  }

  async function openProvision() {
    provisionDevice = "";
    provisionLabel = nextId;
    provisionForceRepartition = false;
    provisionDryRun = false;
    provisionError = "";
    showProvisionSheet = true;
    drivesLoading = true;
    try {
      availableDrives = await listDrives();
    } finally {
      drivesLoading = false;
    }
  }

  function closeProvision() {
    showProvisionSheet = false;
    provisionRunning = false;
    provisionStep = "";
    provisionError = "";
  }

  async function confirmProvision() {
    if (!provisionDevice || !provisionLabel) return;
    provisionRunning = true;
    provisionError = "";

    try {
      await provisionCartridge(
        provisionDevice,
        provisionLabel,
        provisionForceRepartition,
        provisionDryRun,
        (event: ProvisionEvent) => {
          if (event.type === "progress") {
            provisionStep = event.step;
            provisionCurrent = event.current;
            provisionTotal = event.total;
          } else if (event.type === "provision_done") {
            provisionRunning = false;
            closeProvision();
            fetchCartridges();
          } else if (event.type === "error") {
            provisionError = event.message;
            provisionRunning = false;
          }
        },
      );
    } catch (err) {
      provisionError = err instanceof Error ? err.message : String(err);
      provisionRunning = false;
    }
  }

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
  <div class="panel-header">
    <h2>Cartridge Manager</h2>
    <button class="provision-new-btn" on:click={openProvision}>+ Provision New</button>
  </div>

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

  {#if showProvisionSheet}
    <div class="sheet-overlay" role="dialog" aria-modal="true">
      <div class="sheet">
        {#if provisionRunning}
          <h3>Provisioning {provisionLabel}…</h3>
          <p class="muted">{provisionStep}</p>
          <div class="progress-bar">
            <div class="progress-fill" style="width: {(provisionCurrent / provisionTotal) * 100}%"></div>
          </div>
          <p class="progress-text">{provisionCurrent} / {provisionTotal}</p>
          <button class="cancel-btn" on:click={closeProvision}>Cancel</button>
        {:else}
          <h3>Provision New Cartridge</h3>
          {#if provisionError}
            <p class="error">{provisionError}</p>
          {/if}

          <div class="form-group">
            <label for="provision-device">Drive to provision:</label>
            {#if drivesLoading}
              <p class="muted">Scanning for USB drives…</p>
            {:else if availableDrives.length === 0}
              <p class="warning">No USB drives detected. Insert a drive and reopen this dialog.</p>
            {:else}
              <div class="drive-picker">
                {#each availableDrives as drive}
                  <button
                    class="drive-option"
                    class:selected={provisionDevice === drive.device}
                    on:click={() => (provisionDevice = drive.device)}
                  >
                    <span class="drive-model">{drive.model}</span>
                    <span class="drive-meta">{drive.device} · {formatBytes(drive.size_bytes)}</span>
                    {#if drive.label}
                      <span class="drive-label-badge">{drive.label}</span>
                    {/if}
                  </button>
                {/each}
              </div>
            {/if}
          </div>

          {#if selectedDrive}
            <div class="selected-summary">
              Formatting <strong>{selectedDrive.device}</strong> ({selectedDrive.model}, {formatBytes(selectedDrive.size_bytes)}) — <span class="warning">all data will be erased</span>
            </div>
          {/if}

          <div class="form-group">
            <label for="provision-label">Label:</label>
            <input id="provision-label" bind:value={provisionLabel} placeholder="PHOTON-001" />
          </div>
          <div class="form-group">
            <label>
              <input type="checkbox" bind:checked={provisionForceRepartition} />
              Force repartition (erase existing data)
            </label>
          </div>
          <div class="form-group">
            <label>
              <input type="checkbox" bind:checked={provisionDryRun} />
              Dry run (simulate without touching disk)
            </label>
          </div>
          <div class="sheet-actions">
            <button class="cancel-btn" on:click={closeProvision}>Cancel</button>
            <button class="primary-btn" disabled={!provisionDevice || !provisionLabel} on:click={confirmProvision}>Start Provisioning</button>
          </div>
        {/if}
      </div>
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
    padding: 2.5rem 3rem;
    gap: 1.25rem;
  }
  .panel-header { display: flex; justify-content: space-between; align-items: center; }
  h2 { color: var(--text-primary, #fff); margin: 0; }
  .provision-new-btn {
    padding: 0.5rem 1rem;
    background: var(--accent, #6366f1); color: #fff;
    border: none; border-radius: 0.375rem; cursor: pointer; font-size: 0.9rem;
  }
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
    display: flex; align-items: center; justify-content: center;
    z-index: 100;
  }
  .sheet {
    background: var(--surface-elevated, #222);
    border-radius: 1rem;
    padding: 2rem;
    width: 90%;
    max-width: 560px;
    max-height: 80vh;
    overflow-y: auto;
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
  .primary-btn {
    flex: 1; padding: 0.75rem;
    background: var(--accent, #6366f1); color: #fff;
    border: none; border-radius: 0.375rem; cursor: pointer;
  }
  .form-group { display: flex; flex-direction: column; gap: 0.5rem; }
  .form-group label { color: var(--text-muted, #888); font-size: 0.9rem; }
  .form-group input[type="checkbox"] { margin-right: 0.5rem; }
  .progress-bar {
    height: 6px; background: var(--border, #333); border-radius: 3px; overflow: hidden;
  }
  .progress-fill { height: 100%; background: var(--accent, #6366f1); transition: width 0.3s; }
  .progress-text { color: var(--text-muted, #888); font-size: 0.9rem; text-align: center; }
  .drive-picker { display: flex; flex-direction: column; gap: 0.5rem; }
  .drive-option {
    display: flex; flex-direction: column; gap: 0.2rem;
    padding: 0.75rem 1rem;
    background: var(--surface, #1a1a1a);
    border: 1px solid var(--border, #333);
    border-radius: 0.5rem;
    cursor: pointer; text-align: left; width: 100%;
  }
  .drive-option:hover { border-color: var(--accent, #6366f1); }
  .drive-option.selected { border-color: var(--accent, #6366f1); background: rgba(99,102,241,0.1); }
  .drive-model { color: var(--text-primary, #fff); font-size: 0.95rem; font-weight: 500; }
  .drive-meta { color: var(--text-muted, #888); font-size: 0.8rem; font-family: monospace; }
  .drive-label-badge {
    display: inline-block; font-size: 0.75rem;
    padding: 0.1rem 0.4rem;
    background: rgba(245,158,11,0.2); color: var(--warning, #f59e0b);
    border-radius: 0.25rem;
  }
  .selected-summary {
    font-size: 0.85rem; color: var(--text-muted, #888);
    padding: 0.5rem 0.75rem;
    background: rgba(239,68,68,0.08);
    border-radius: 0.375rem;
    border-left: 3px solid var(--error, #ef4444);
  }
</style>
