<script lang="ts">
  import StatusBar from "./components/StatusBar.svelte";
  import BottomNav from "./components/BottomNav.svelte";
  import IngestDashboard from "./panels/IngestDashboard.svelte";
  import LibraryBrowser from "./panels/LibraryBrowser.svelte";
  import DarktableLauncher from "./panels/DarktableLauncher.svelte";
  import ExportShare from "./panels/ExportShare.svelte";
  import CartridgeManager from "./panels/CartridgeManager.svelte";
  import Settings from "./panels/Settings.svelte";

  let activeIdx = 0;
</script>

<StatusBar />

<main class="panel-area">
  {#if activeIdx === 0}
    <IngestDashboard />
  {:else if activeIdx === 1}
    <LibraryBrowser />
  {:else if activeIdx === 2}
    <DarktableLauncher />
  {:else if activeIdx === 3}
    <ExportShare />
  {:else if activeIdx === 4}
    <CartridgeManager />
  {:else}
    <Settings />
  {/if}
</main>

<BottomNav {activeIdx} on:select={(e) => (activeIdx = e.detail)} />

<style>
  .panel-area {
    position: fixed;
    top: 40px;
    bottom: 56px;
    left: 0;
    right: 0;
    overflow-y: auto;
    background: var(--bg);
  }
</style>
