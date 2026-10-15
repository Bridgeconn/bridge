<script lang="ts">
  // The splash window (#287): the brand, the version and the latest startup
  // stage the shell reported, in a small borderless window. It only watches;
  // the hidden main window connects to the engine, and on success or failure
  // asks the shell to show itself and close this window. A failure is shown
  // there, on the full loading card (#233), not here.
  import { onDestroy, onMount } from "svelte";
  import { bridge, type EngineStartupStage } from "../api/bridgeClient";
  import { currentStageLabel, mergeStage } from "../startup";

  let version = "";
  let stages: EngineStartupStage[] = [];
  let unlisten: (() => void) | null = null;
  let disposed = false;

  onMount(() => {
    void (async () => {
      // Listen first, then catch up, merged by seq (as App.svelte does).
      try {
        const stop = await bridge.onEngineStage((stage) => { stages = mergeStage(stages, stage); });
        if (disposed) stop();
        else unlisten = stop;
      } catch (error) {
        console.error("Splash: could not subscribe to engine startup stages", error);
      }
      try {
        const state = await bridge.engineStartupState();
        if (disposed) return;
        version = state.version;
        for (const stage of state.stages) stages = mergeStage(stages, stage);
      } catch (error) {
        console.error("Splash: could not read engine startup state", error);
      }
    })();
  });
  onDestroy(() => {
    disposed = true;
    unlisten?.();
  });

  $: label = currentStageLabel(stages);
</script>

<div class="splash" data-tauri-drag-region data-testid="splash-screen">
  <div class="brand" data-tauri-drag-region>
    <svg class="mark" viewBox="0 0 64 64" aria-hidden="true">
      <defs>
        <linearGradient id="bridge-splash-gradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#2F6FED" />
          <stop offset="1" stop-color="#15A34A" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14" fill="url(#bridge-splash-gradient)" />
      <path d="M13 41 C 24 20, 40 20, 51 41" stroke="#fff" stroke-width="5" fill="none" stroke-linecap="round" />
      <path d="M13 46 H51" stroke="#fff" stroke-width="4" stroke-linecap="round" />
    </svg>
    <div data-tauri-drag-region>
      <div class="name" data-tauri-drag-region>Bridge</div>
      <div class="version" data-testid="splash-version" data-tauri-drag-region>{version ? `Version ${version}` : ""}</div>
    </div>
  </div>
  <div class="status" role="status" aria-live="polite" data-tauri-drag-region>
    <span class="spinner" aria-hidden="true"></span>
    <span data-testid="splash-stage" data-tauri-drag-region>{label}</span>
  </div>
</div>

<style>
  .splash { position: fixed; inset: 0; box-sizing: border-box; background: var(--surface); padding: 28px 32px; display: flex; flex-direction: column; justify-content: center; gap: 22px; cursor: default; user-select: none; }
  .brand { display: flex; align-items: center; gap: 16px; }
  .mark { width: 56px; height: 56px; flex-shrink: 0; }
  .name { font-size: var(--fs-4xl); font-weight: 800; color: var(--text); letter-spacing: -0.01em; line-height: 1.1; }
  .version { font-size: var(--fs-xs); color: var(--text-3); min-height: 1.2em; }
  .status { display: flex; align-items: center; gap: 12px; font-size: var(--fs-md); color: var(--text); }
  .spinner { width: 16px; height: 16px; border-radius: 50%; border: 2px solid var(--border-strong); border-top-color: var(--accent); animation: spin 0.9s linear infinite; flex-shrink: 0; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
