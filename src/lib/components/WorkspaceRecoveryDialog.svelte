<script lang="ts">
  // #338: the one-time report that workspace.sqlite3 was damaged at startup
  // and what recovery did. A modal, not a banner (2026-10-29): a recovery is
  // rare and changes what the reviewer should expect to find, so it is read
  // once, in full, before the app is used. Never an error: nothing here is
  // red, and the one button just continues. Enter and Escape both continue;
  // there is no other answer to give.
  import { onMount, tick } from "svelte";
  import type { RecoverySummary } from "../workspaceRecovery";

  export let summary: RecoverySummary;
  export let onClose: () => void;

  let button: HTMLButtonElement | null = null;

  function onKeydown(event: KeyboardEvent): void {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    onClose();
  }

  onMount(() => {
    void tick().then(() => button?.focus());
    window.addEventListener("keydown", onKeydown, true);
    return () => window.removeEventListener("keydown", onKeydown, true);
  });
</script>

<div class="overlay" role="presentation" data-testid="workspace-recovery-dialog">
  <div class="dialog" role="alertdialog" aria-modal="true" aria-labelledby="recovery-title" aria-describedby="recovery-headline">
    <div class="head">
      <span class="badge" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 7a8 8 0 0 1 13.5-2.5L20 7M20 7V2m0 5h-5M20 17a8 8 0 0 1-13.5 2.5L4 17m0 0v5m0-5h5" />
        </svg>
      </span>
      <div>
        <h2 id="recovery-title">{summary.title}</h2>
        <p id="recovery-headline" class="headline">{summary.headline}</p>
      </div>
    </div>

    <dl class="facts">
      {#each summary.facts as fact (fact.label)}
        <dt>{fact.label}</dt>
        <dd><code>{fact.value}</code></dd>
      {/each}
    </dl>

    {#if summary.lost.length > 0}
      <div class="lost">
        <div class="lost-title">Not recovered</div>
        <ul>
          {#each summary.lost as item (item)}<li>{item}</li>{/each}
        </ul>
      </div>
    {/if}

    {#if summary.hub}
      <p class="hub" class:action={summary.needsAction}>{summary.hub}</p>
    {/if}

    <p class="foot">Nothing was deleted. The set-aside file stays in Bridge's data folder beside the workspace database.</p>

    <div class="actions">
      <button type="button" class="primary" bind:this={button} on:click={onClose}>Continue</button>
    </div>
  </div>
</div>

<style>
  .overlay { position: fixed; inset: 0; z-index: var(--z-dialog-over-dialog); display: grid; place-items: center; background: rgba(15, 20, 26, 0.45); animation: fade 0.18s ease-out; }
  .dialog { width: min(560px, calc(100vw - 32px)); max-height: calc(100vh - 48px); overflow: auto; box-sizing: border-box; background: var(--surface); color: var(--text);
    border-radius: 16px; padding: 24px 26px 20px; box-shadow: 0 24px 60px rgba(0, 0, 0, .28); animation: pop 0.22s cubic-bezier(0.2, 0.9, 0.3, 1.1); }
  @keyframes fade { from { opacity: 0; } }
  @keyframes pop { from { opacity: 0; transform: translateY(10px) scale(0.98); } }

  .head { display: flex; gap: 14px; align-items: flex-start; margin-bottom: 18px; }
  .badge { flex-shrink: 0; width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; background: var(--warning-bg); color: var(--warning); }
  .badge svg { width: 22px; height: 22px; }
  h2 { font-size: var(--fs-xl); font-weight: 700; margin: 2px 0 4px; letter-spacing: -0.01em; }
  .headline { font-size: var(--fs-sm); color: var(--text-2); margin: 0; line-height: 1.5; }

  .facts { display: grid; grid-template-columns: max-content 1fr; gap: 8px 16px; margin: 0 0 16px; padding: 12px 14px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--border); font-size: var(--fs-xs); }
  dt { color: var(--text-3); white-space: nowrap; }
  dd { margin: 0; min-width: 0; color: var(--text); overflow-wrap: anywhere; }
  dd code { font-family: inherit; font-weight: 600; }

  .lost { margin: 0 0 14px; font-size: var(--fs-xs); }
  .lost-title { font-weight: 600; color: var(--text-2); margin-bottom: 4px; }
  ul { margin: 0; padding-left: 18px; color: var(--text-2); line-height: 1.5; }

  .hub { font-size: var(--fs-xs); color: var(--text-2); margin: 0 0 14px; line-height: 1.5; }
  .hub.action { color: var(--warning); font-weight: 600; }
  .foot { font-size: var(--fs-2xs); color: var(--text-3); margin: 0 0 18px; line-height: 1.45; }

  .actions { display: flex; justify-content: flex-end; }
  button { font: inherit; font-size: var(--fs-sm); font-weight: 600; padding: 9px 18px; border-radius: 8px; border: 1px solid var(--accent); background: var(--accent); color: #fff; cursor: pointer; }
  button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

  @media (prefers-reduced-motion: reduce) { .overlay, .dialog { animation: none; } }
</style>
