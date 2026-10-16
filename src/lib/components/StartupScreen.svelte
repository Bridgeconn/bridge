<script lang="ts">
  // The loading screen (#233): the first thing the window shows, until the
  // engine answers. The status line is the latest real stage the shell
  // reported, never an animation standing in for one. On failure: plain
  // words, the engine log behind "Show details", a one-click diagnostics
  // copy, and Retry.
  import { onDestroy, onMount } from "svelte";
  import type { EngineLogEntry, EngineStartupStage } from "../api/bridgeClient";
  import { buildDiagnosticsText, copyToClipboard, currentStageLabel, type StartupPaths } from "../startup";

  export let version = "";
  export let stages: EngineStartupStage[] = [];
  /** Non-empty once startup has failed; the text is shown as given. */
  export let failure = "";
  export let log: EngineLogEntry[] = [];
  export let paths: StartupPaths | null = null;
  export let onRetry: () => void;

  let showDetails = false;
  let copied: "idle" | "done" | "failed" = "idle";
  let copiedTimer: ReturnType<typeof setTimeout> | undefined;
  let elapsedSeconds = 0;
  let elapsedTimer: ReturnType<typeof setInterval> | undefined;
  const mountedAt = Date.now();

  onMount(() => {
    elapsedTimer = setInterval(() => { elapsedSeconds = Math.floor((Date.now() - mountedAt) / 1000); }, 1000);
  });
  onDestroy(() => {
    if (elapsedTimer) clearInterval(elapsedTimer);
    if (copiedTimer) clearTimeout(copiedTimer);
  });

  $: label = currentStageLabel(stages);
  $: logTail = log.slice(Math.max(0, log.length - 200)).reverse();

  function diagnosticsText(): string {
    return buildDiagnosticsText({
      version,
      platform: typeof navigator !== "undefined" ? navigator.platform : "",
      userAgent: typeof navigator !== "undefined" ? navigator.userAgent : "",
      failure,
      paths,
      stages,
      log,
      capturedAt: new Date(),
    });
  }

  async function copyDiagnostics(): Promise<void> {
    const ok = await copyToClipboard(diagnosticsText());
    copied = ok ? "done" : "failed";
    if (copiedTimer) clearTimeout(copiedTimer);
    copiedTimer = setTimeout(() => { copied = "idle"; }, 3000);
  }

  function formatTime(tsMs: number): string {
    return new Date(tsMs).toLocaleTimeString(undefined, { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }
</script>

<div class="startup" data-testid="startup-screen">
  <div class="card" class:failed={Boolean(failure)}>
    <div class="brand">
      <svg class="mark" viewBox="0 0 64 64" aria-hidden="true">
        <defs>
          <linearGradient id="bridge-mark-gradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="#2F6FED" />
            <stop offset="1" stop-color="#15A34A" />
          </linearGradient>
        </defs>
        <rect width="64" height="64" rx="14" fill="url(#bridge-mark-gradient)" />
        <path d="M13 41 C 24 20, 40 20, 51 41" stroke="#fff" stroke-width="5" fill="none" stroke-linecap="round" />
        <path d="M13 46 H51" stroke="#fff" stroke-width="4" stroke-linecap="round" />
      </svg>
      <div>
        <div class="name">Bridge</div>
        <div class="version" data-testid="startup-version">{version ? `Version ${version}` : ""}</div>
      </div>
    </div>

    {#if failure}
      <div class="problem" role="alert">
        <p class="headline">Bridge could not start its engine.</p>
        <p class="detail" data-testid="startup-failure">{failure}</p>
        <p class="hint">
          Retry starts the engine again. If it keeps failing, copy the diagnostics and send them to
          the maintainer; they include this app's version, the paths it used and the engine's log.
        </p>
      </div>
      <div class="actions">
        <button class="primary" on:click={onRetry}>Retry</button>
        <button on:click={() => (showDetails = !showDetails)} aria-expanded={showDetails}>
          {showDetails ? "Hide details" : "Show details"}
        </button>
        <button on:click={() => void copyDiagnostics()}>
          {copied === "done" ? "Copied" : copied === "failed" ? "Copy failed" : "Copy diagnostics"}
        </button>
      </div>
      {#if showDetails}
        <div class="details" data-testid="startup-details">
          {#if logTail.length === 0}
            <p class="muted">The engine log is empty.</p>
          {:else}
            {#each logTail as entry, index (index)}
              <div class="entry {entry.level}">
                <span class="time">{formatTime(entry.ts_ms)}</span>
                <span class="level">{entry.level}</span>
                <span class="message">{entry.message}</span>
              </div>
            {/each}
          {/if}
        </div>
      {/if}
    {:else}
      <div class="status" role="status" aria-live="polite">
        <span class="spinner" aria-hidden="true" />
        <span class="stage" data-testid="startup-stage">{label}</span>
        <span class="elapsed">{elapsedSeconds > 0 ? `${elapsedSeconds} s` : ""}</span>
      </div>
      {#if stages.length > 1}
        <ol class="stages" data-testid="startup-stages">
          {#each stages as stage (stage.seq)}
            <li class:current={stage.seq === stages[stages.length - 1].seq}>{stage.label}</li>
          {/each}
        </ol>
      {/if}
    {/if}
  </div>
</div>

<style>
  .startup { position: absolute; inset: 0; z-index: var(--z-startup); background: var(--bg); display: grid; place-items: center; padding: 24px; }
  .card { width: min(560px, 100%); background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 28px 32px; box-shadow: 0 12px 40px rgba(0,0,0,.08); display: flex; flex-direction: column; gap: 18px; }
  .brand { display: flex; align-items: center; gap: 16px; }
  .mark { width: 56px; height: 56px; flex-shrink: 0; }
  .name { font-size: var(--fs-4xl); font-weight: 800; color: var(--text); letter-spacing: -0.01em; line-height: 1.1; }
  .version { font-size: var(--fs-xs); color: var(--text-3); min-height: 1.2em; }
  .status { display: flex; align-items: center; gap: 12px; font-size: var(--fs-md); color: var(--text); }
  .stage { flex: 1; }
  .elapsed { font-size: var(--fs-xs); color: var(--text-3); font-variant-numeric: tabular-nums; }
  .spinner { width: 16px; height: 16px; border-radius: 50%; border: 2px solid var(--border-strong); border-top-color: var(--accent); animation: spin 0.9s linear infinite; flex-shrink: 0; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .stages { margin: 0; padding: 0 0 0 18px; font-size: var(--fs-xs); color: var(--text-3); display: flex; flex-direction: column; gap: 3px; }
  .stages li.current { color: var(--text-2); font-weight: 600; }
  .problem { display: flex; flex-direction: column; gap: 6px; }
  .headline { margin: 0; font-size: var(--fs-lg); font-weight: 700; color: var(--danger); }
  .detail { margin: 0; font-size: var(--fs-sm); color: var(--text); overflow-wrap: anywhere; }
  .hint { margin: 0; font-size: var(--fs-xs); color: var(--text-2); line-height: 1.5; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; }
  .actions button { font-size: var(--fs-xs); font-weight: 650; padding: 8px 14px; border-radius: 8px; border: 1px solid var(--border-strong); background: var(--surface-2); color: var(--text); cursor: pointer; }
  .actions button:hover { background: var(--accent-bg); }
  .actions button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  .details { max-height: 240px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: var(--fs-2xs); }
  .muted { color: var(--text-3); margin: 6px 0; }
  .entry { display: flex; gap: 8px; align-items: baseline; padding: 3px 0; border-bottom: 1px solid var(--border); }
  .entry:last-child { border-bottom: none; }
  .time { color: var(--text-3); flex-shrink: 0; }
  .level { text-transform: uppercase; font-size: var(--fs-3xs); font-weight: 700; color: var(--text-2); flex-shrink: 0; }
  .entry.error .level, .entry.error .message { color: var(--danger); }
  .entry.warn .level { color: var(--warning); }
  .message { color: var(--text); overflow-wrap: anywhere; white-space: pre-wrap; }
</style>
