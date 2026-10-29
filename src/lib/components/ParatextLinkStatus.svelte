<script lang="ts">
  // #356: the open book's link to its Paratext project folder, on Project
  // Home. Nothing is shown for a book that was not imported from Paratext.
  // A missing or moved folder never blocks work; Relink points every book of
  // the collection at the right folder (the engine refuses a different Guid).
  import { onDestroy } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import type { ParatextLinkStatus } from "../types/paratext";

  /** Changes when another book opens, so the status is read again. */
  export let projectKey = "";

  let status: ParatextLinkStatus | null = null;
  let busy = false;
  let error = "";
  let poll: ReturnType<typeof setTimeout> | null = null;
  const POLL_MS = 2000;

  // #357: while the notes index builds, read the status again until it settles.
  function schedule(): void {
    if (poll) clearTimeout(poll);
    poll = null;
    const notes = status?.notesIndex?.state;
    if (status?.state === "linked" && (notes === "building" || notes === "stale")) {
      poll = setTimeout(() => void load(), POLL_MS);
    }
  }
  onDestroy(() => { if (poll) clearTimeout(poll); });

  function notesText(value: ParatextLinkStatus): string {
    const files = value.files.notes.count;
    const parts = [`${files} notes ${files === 1 ? "file" : "files"}`];
    const notes = value.notesIndex;
    if (notes?.state === "ready" || notes?.state === "stale") parts.push(`${notes.threads} note threads`);
    else if (notes?.state === "building") parts.push("reading notes…");
    else if (notes?.state === "error") parts.push("notes could not be read");
    return parts.join(" · ");
  }

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
    schedule();
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
    schedule();
  }

  async function chooseFolder(): Promise<void> {
    const folder = await bridge.pickFolder();
    if (folder) await run(() => bridge.paratextRelink(folder));
  }

  $: projectKey, void load();
</script>

{#if status && status.state !== "notParatext"}
  <div class="paratext-link" class:problem={status.state !== "linked"} data-testid="paratext-link-status">
    <span class="ui-chip" class:warning={status.state !== "linked"} class:pass={status.state === "linked"}
      use:tooltip={status.state === "linked" ? `Linked to the Paratext project ${status.name} at ${status.folder} · ${notesText(status)}` : ""}>
      <UiIcon name={status.state === "linked" ? "link" : "warning"} />
      {#if status.state === "linked"}
        Paratext · {status.name} · linked
      {:else if status.state === "folderMoved"}
        Paratext · {status.name} · folder moved
      {:else if status.state === "guidMismatch"}
        Paratext · {status.name} · different project in folder
      {:else}
        Paratext · {status.name} · folder not found
      {/if}
    </span>
    {#if status.state === "linked"}
      <span class="detail">{notesText(status)}</span>
      <button type="button" class="ui-btn small quiet" on:click={() => run(() => bridge.paratextRefresh())} disabled={busy}>Refresh</button>
    {:else if status.state === "folderMoved"}
      <span class="detail">No longer at {status.folder}; the same project is at {status.candidate}.</span>
      <button type="button" class="ui-btn small" on:click={() => status?.candidate && run(() => bridge.paratextRelink(status?.candidate ?? ""))} disabled={busy}>Relink</button>
      <button type="button" class="ui-btn small quiet" on:click={chooseFolder} disabled={busy}>Choose folder…</button>
    {:else if status.state === "guidMismatch"}
      <span class="detail">{status.folder} now holds a different Paratext project. Paratext data is not used until it is relinked.</span>
      <button type="button" class="ui-btn small" on:click={chooseFolder} disabled={busy}>Relink…</button>
    {:else}
      <span class="detail">Not found at {status.folder}. Paratext data is not used until it is relinked.</span>
      <button type="button" class="ui-btn small" on:click={chooseFolder} disabled={busy}>Relink…</button>
    {/if}
    {#if error}<span class="error" role="alert">{error}</span>{/if}
  </div>
{/if}

<style>
  .paratext-link { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; min-width: 0; }
  .detail { color: var(--text-2); font-size: var(--fs-3xs); overflow-wrap: anywhere; }
  .problem .detail { color: var(--warning); }
  .error { color: var(--danger); font-size: var(--fs-3xs); }
</style>
