<script lang="ts">
  import { createEventDispatcher } from "svelte";

  export let activeIdx: number = 0;

  const dispatch = createEventDispatcher<{ select: number }>();

  const TABS = [
    { label: "Ingest",     icon: "⬇" },
    { label: "Library",    icon: "◼" },
    { label: "Darktable",  icon: "●" },
    { label: "Export",     icon: "↑" },
    { label: "Cartridge",  icon: "▣" },
    { label: "Settings",   icon: "⚙" },
  ];
</script>

<nav class="bottom-nav">
  {#each TABS as tab, i}
    <button
      class="tab"
      class:active={i === activeIdx}
      on:click={() => dispatch("select", i)}
      aria-label={tab.label}
    >
      <span class="tab-icon" aria-hidden="true">{tab.icon}</span>
      <span class="tab-label">{tab.label}</span>
    </button>
  {/each}
</nav>

<style>
  .bottom-nav {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 56px;
    background: var(--surface);
    border-top: 1px solid var(--border);
    display: flex;
    z-index: 100;
  }
  .tab {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--text-muted);
    cursor: pointer;
    gap: 2px;
    min-height: 44px;
    padding: 0;
  }
  .tab.active {
    color: var(--accent);
    border-bottom-color: var(--accent);
  }
  .tab-icon { font-size: 1.2rem; }
  .tab-label { font-size: 0.7rem; }
</style>
