<script lang="ts">
  // #356: the open book's link to its Paratext project folder, on Project
  // Home. Nothing is shown for a book that was not imported from Paratext.
  // A missing or moved folder never blocks work; Relink points every book of
  // the collection at the right folder (the engine refuses a different Guid).
  import { bridge } from "../api/bridgeClient";
  import type { ParatextLinkStatus } from "../types/paratext";

  /** Changes when another book opens, so the status is read again. */
  export let projectKey = "";

  let status: ParatextLinkStatus | null = null;
  let busy = false;
  let error = "";

  function message(value: unknown): string {
    if (value instanceof Error) return value.message;
    if (typeof value === "object" && value && "message" in value) return String((value as { message: unknown }).message);
    return String(value);
  }

  async function load(): Promise<void> {
    error = "";
    try {
      status = await bridge.paratextLinkStatus();
    } catch (value) {
      status = null;
      error = message(value);
    }
  }

  async function run(action: () => Promise<ParatextLinkStatus>): Promise<void> {
    busy = true;
    error = "";
    try {
      status = await action();
    } catch (value) {
      error = message(value);
    } finally {
      busy = false;
    }
  }

  async function chooseFolder(): Promise<void> {
    const folder = await bridge.pickFolder();
    if (folder) await run(() => bridge.paratextRelink(folder));
  }

  $: projectKey, void load();
</script>

{#if status && status.state !== "notParatext"}
  <div class="paratext-link" class:problem={status.state !== "linked"} data-testid="paratext-link-status">
    {#if status.state === "linked"}
      <span>Paratext <strong>{status.name}</strong> · linked · {status.files.notes.count} notes {status.files.notes.count === 1 ? "file" : "files"}</span>
      <button type="button" on:click={() => run(() => bridge.paratextRefresh())} disabled={busy}>Refresh</button>
    {:else if status.state === "folderMoved"}
      <span>Paratext <strong>{status.name}</strong> is no longer at {status.folder}; the same project is at {status.candidate}.</span>
      <button type="button" on:click={() => status?.candidate && run(() => bridge.paratextRelink(status?.candidate ?? ""))} disabled={busy}>Relink</button>
      <button type="button" on:click={chooseFolder} disabled={busy}>Choose folder…</button>
    {:else if status.state === "guidMismatch"}
      <span>{status.folder} now holds a different Paratext project, not <strong>{status.name}</strong>. Paratext data is not used until it is relinked.</span>
      <button type="button" on:click={chooseFolder} disabled={busy}>Relink…</button>
    {:else}
      <span>Paratext folder for <strong>{status.name}</strong> not found ({status.folder}). Paratext data is not used until it is relinked.</span>
      <button type="button" on:click={chooseFolder} disabled={busy}>Relink…</button>
    {/if}
    {#if error}<span class="error" role="alert">{error}</span>{/if}
  </div>
{/if}

<style>
  .paratext-link { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; margin: 0 0 10px; padding: 6px 10px;
    border: 1px solid var(--border); border-radius: 7px; background: var(--surface-2); color: var(--text-2); font-size: var(--fs-2xs); }
  .paratext-link.problem { border-color: var(--warning); background: var(--warning-bg); }
  .paratext-link span { overflow-wrap: anywhere; }
  .paratext-link button { border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text);
    padding: 3px 9px; font-size: var(--fs-2xs); cursor: pointer; }
  .paratext-link button:disabled { opacity: .6; cursor: default; }
  .error { color: var(--danger); }
</style>
