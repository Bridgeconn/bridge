<script lang="ts">
  import { onMount } from "svelte";
  import { engineLog } from "../stores";
  import type { EngineLogEntry } from "../api/bridgeClient";
  import {
    perfRunnerAvailable, perfSamples, perfSummary, perfTableMarkdown, runPerfSample, type PerfRunProgress,
  } from "../perf";

  export let onClose: () => void;

  // #321: Escape does what the × does, and focus goes back to the button that
  // opened the panel (the CheckerSettingsDialog pattern).
  let openedFrom: Element | null = null;
  onMount(() => {
    openedFrom = document.activeElement;
    return () => { if (openedFrom instanceof HTMLElement && openedFrom.isConnected) openedFrom.focus(); };
  });

  function onWindowKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape" && !event.defaultPrevented) onClose();
  }

  let filter: "all" | "warn" | "error" = "all";

  // #232: the responsiveness table from this session's samples, and the
  // runner that repeats the drivable actions 20 times for the measurement day.
  let perfRunning = false;
  let perfProgress: PerfRunProgress | null = null;
  let perfError = "";
  let perfCopied = false;
  $: perfRows = perfSummary($perfSamples);
  $: perfMeasured = perfRows.filter((row) => row.samples > 0);

  async function runPerf() {
    perfRunning = true;
    perfError = "";
    try {
      await runPerfSample(20, (progress) => { perfProgress = progress; });
    } catch (error) {
      perfError = error instanceof Error ? error.message : String(error);
    } finally {
      perfRunning = false;
      perfProgress = null;
    }
  }

  async function copyPerfTable() {
    try {
      await navigator.clipboard.writeText(perfTableMarkdown(perfRows));
      perfCopied = true;
      setTimeout(() => { perfCopied = false; }, 1500);
    } catch (error) {
      perfError = error instanceof Error ? error.message : String(error);
    }
  }

  $: visible = ([...$engineLog] as EngineLogEntry[])
    .reverse()
    .filter((entry) => filter === "all" || entry.level === filter);

  function formatTime(tsMs: number): string {
    return new Date(tsMs).toLocaleTimeString(undefined, { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }
</script>

<svelte:window on:keydown={onWindowKeydown} />

<div class="modal-overlay">
  <div class="diagnostics-modal">
    <button class="close-btn" on:click={onClose} aria-label="Close diagnostics">✕</button>
    <div class="header">
      <div class="title">Engine diagnostics</div>
      <p class="desc">
        Sidecar lifecycle events (start, restart, crash), request timeouts, and the Python engine's
        own error output. If the engine ever restarts mid-session, reopen your project — its
        in-memory state does not carry over.
      </p>
      <div class="filters">
        <button class:active={filter === "all"} on:click={() => (filter = "all")}>All ({$engineLog.length})</button>
        <button class:active={filter === "warn"} on:click={() => (filter = "warn")}>Warnings</button>
        <button class:active={filter === "error"} on:click={() => (filter = "error")}>Errors</button>
      </div>
    </div>
    <section class="perf" aria-label="Responsiveness">
      <div class="perf-head">
        <span class="perf-title">Responsiveness (p95 this session)</span>
        <button class="perf-btn" on:click={runPerf} disabled={perfRunning || !perfRunnerAvailable()}
          title="Repeat each action App can drive 20 times with a book open in the editor">
          {perfRunning && perfProgress ? `Running ${perfProgress.step} ${perfProgress.done}/${perfProgress.total}…` : "Measure 20× each"}
        </button>
        <button class="perf-btn" on:click={copyPerfTable} disabled={perfMeasured.length === 0}>{perfCopied ? "Copied" : "Copy table"}</button>
      </div>
      {#if perfError}<p class="muted perf-error">{perfError}</p>{/if}
      {#if perfMeasured.length === 0}
        <p class="muted">No actions timed yet. Navigate, open a chapter or a menu, or press Measure with a book open.</p>
      {:else}
        <table class="perf-table">
          <thead><tr><th>Action</th><th>Tier</th><th>n</th><th>Responded p95</th><th>Complete p95</th><th>Budget</th><th>Result</th></tr></thead>
          <tbody>
            {#each perfMeasured as row (row.action)}
              <tr class:fail={row.pass === false}>
                <td>{row.label}</td><td>{row.tier}</td><td>{row.samples}</td>
                <td>{row.respondedP95} ms</td><td>{row.completeP95} ms</td>
                <td>{row.tier === "A" ? "100 / 300" : "100 / 2000"} ms</td>
                <td>{row.samples < 20 ? `only ${row.samples}` : row.pass ? "pass" : "FAIL"}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>
    <div class="log-body">
      {#if visible.length === 0}
        <p class="muted">No {filter === "all" ? "" : filter} entries yet.</p>
      {:else}
        {#each visible as entry, index (index)}
          <div class="entry {entry.level}">
            <span class="time">{formatTime(entry.ts_ms)}</span>
            <span class="level-badge {entry.level}">{entry.level}</span>
            <span class="message">{entry.message}</span>
          </div>
        {/each}
      {/if}
    </div>
  </div>
</div>

<style>
  .modal-overlay { position: absolute; inset: 0; background: rgba(15, 20, 26, 0.45); display: flex; align-items: center; justify-content: center; z-index: var(--z-dialog); }
  .diagnostics-modal { width: 720px; height: 520px; background: var(--surface); border-radius: 14px; display: flex; flex-direction: column; overflow: hidden; position: relative; }
  .close-btn { position: absolute; top: 10px; right: 10px; z-index: 2; width: 28px; height: 28px; border-radius: 6px; border: none; background: transparent; color: var(--text-2); font-size: var(--fs-lg); cursor: pointer; }
  .close-btn:hover { background: var(--surface-2); }
  .header { padding: 20px 24px 12px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
  .title { font-size: var(--fs-lg); font-weight: 700; color: var(--text); margin-bottom: 4px; }
  .desc { font-size: var(--fs-xs); line-height: 1.5; color: var(--text-2); margin: 0 0 12px; max-width: 560px; }
  .filters { display: flex; gap: 6px; }
  .filters button { font-size: var(--fs-2xs); font-weight: 650; padding: 5px 10px; border-radius: 999px; border: 1px solid var(--border-strong); background: var(--surface-2); color: var(--text-2); cursor: pointer; }
  .filters button.active { background: var(--accent-bg); color: var(--accent); border-color: var(--accent); }
  .perf { flex-shrink: 0; padding: 10px 24px; border-bottom: 1px solid var(--border); max-height: 220px; overflow-y: auto; }
  .perf-head { display: flex; align-items: center; gap: 8px; }
  .perf-title { font-size: var(--fs-xs); font-weight: 700; color: var(--text); flex: 1; }
  .perf-btn { font-size: var(--fs-2xs); font-weight: 650; padding: 5px 10px; border-radius: 999px; border: 1px solid var(--border-strong); background: var(--surface-2); color: var(--text-2); cursor: pointer; }
  .perf-btn:disabled { opacity: .5; cursor: default; }
  .perf-error { color: var(--danger); }
  .perf-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: var(--fs-2xs); font-family: ui-monospace, "SF Mono", Consolas, monospace; }
  .perf-table th, .perf-table td { text-align: left; padding: 3px 6px; border-bottom: 1px solid var(--border); color: var(--text); }
  .perf-table th { color: var(--text-2); font-weight: 650; }
  .perf-table tr.fail td:last-child { color: var(--danger); font-weight: 700; }
  .log-body { flex: 1; overflow-y: auto; padding: 8px 24px 20px; font-family: ui-monospace, "SF Mono", Consolas, monospace; }
  .muted { font-size: var(--fs-sm); color: var(--text-3); padding: 12px 0; }
  .entry { display: flex; align-items: baseline; gap: 8px; padding: 5px 0; border-bottom: 1px solid var(--border); font-size: var(--fs-xs); }
  .entry:last-child { border-bottom: none; }
  .time { color: var(--text-3); flex-shrink: 0; }
  .level-badge { flex-shrink: 0; text-transform: uppercase; font-size: var(--fs-3xs); font-weight: 700; padding: 2px 6px; border-radius: 4px; background: var(--surface-2); color: var(--text-2); }
  .level-badge.warn { color: var(--warning); background: var(--warning-bg); }
  .level-badge.error { color: var(--danger); background: var(--danger-bg); }
  .message { color: var(--text); overflow-wrap: anywhere; white-space: pre-wrap; }
  .entry.error .message { color: var(--danger); }
</style>
