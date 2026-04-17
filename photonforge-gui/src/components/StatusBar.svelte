<script lang="ts">
  import { deviceState } from "../stores/devices";
</script>

<div class="status-bar">
  <span class="indicator" class:ok={$deviceState.ssd_mounted}>
    SSD: {$deviceState.ssd_mounted
      ? ($deviceState.ssd_label ?? "mounted")
      : "No cartridge"}
  </span>
  <span class="indicator" class:ok={$deviceState.sd_mounted}>
    SD: {$deviceState.sd_mounted ? "SD ready" : "No SD card"}
  </span>
</div>

<style>
  .status-bar {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 40px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 2rem;
    padding: 0 1rem;
    z-index: 100;
  }
  .indicator {
    color: var(--text-muted);
    font-size: 0.875rem;
  }
  .indicator.ok {
    color: var(--ok);
  }
</style>
