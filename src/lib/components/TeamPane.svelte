<script lang="ts">
  /** Settings > Team (#80): join a team hub with a join code, link the open
   *  book, see when it last synced, and settle conflicts. Optional: nothing
   *  here is needed to work, and the app never waits on the hub. A conflict
   *  is another person's change to a decision you also changed; yours stays,
   *  theirs is shown, and nothing is overwritten. */
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import type { HubConflict, HubStatus } from "../types/finding";

  let status: HubStatus | null = null;
  let conflicts: HubConflict[] = [];

  /** What the other device changed. A Language QA overrides row (#277) is
   *  named for what it is: their Checker settings for a pack, with the rules
   *  they switched off. Yours stay in the Checker settings dialog. */
  function conflictLabel(item: HubConflict): string {
    const payload = item.theirPayload ?? {};
    if (item.table === "project_state" && typeof payload.pack === "string" && "document" in payload) {
      const rules = (payload.document as { rules?: Record<string, { enabled?: boolean }> } | null)?.rules ?? {};
      const off = Object.entries(rules).filter(([, rule]) => rule?.enabled === false).map(([id]) => id);
      return `Language QA checker settings (${payload.pack})`
        + (payload.document ? (off.length ? `: switched off ${off.join(", ")}` : "") : ": back to the defaults");
    }
    return String(payload.decision ?? item.table);
  }
  let url = "";
  let joinCode = "";
  let displayName = "";
  let busy = false;
  let error = "";
  let notice = "";

  onMount(() => { void refresh(); });

  async function refresh() {
    try {
      status = await bridge.hubStatus();
      if (status.linkedHubProjectId) conflicts = (await bridge.hubConflicts()).conflicts;
      else conflicts = [];
    } catch (value) {
      error = message(value);
    }
  }

  async function run(label: string, action: () => Promise<unknown>) {
    busy = true;
    error = "";
    notice = "";
    try {
      await action();
      await refresh();
      notice = label;
    } catch (value) {
      error = message(value);
    } finally {
      busy = false;
    }
  }

  function join() {
    void run("Joined the hub.", () => bridge.hubJoin(url.trim(), joinCode.trim(), displayName.trim()));
  }

  function message(value: unknown): string {
    return value instanceof Error ? value.message : String(value);
  }

  function when(value: string | null | undefined): string {
    if (!value) return "never";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  }
</script>

<h3>Team</h3>
<p class="desc">
  Optional. A team hub on your local network shares decisions, alignment links and assignments between
  everyone working on the same book. Scripture text never travels, and Bridge never waits for the hub:
  everything works the same when it is unreachable.
</p>

{#if status && status.joined}
  <div class="row"><span class="label">Hub</span><span>{status.url}</span></div>
  <div class="row"><span class="label">Joined as</span><span>{status.identity.displayName ?? ""} ({status.identity.role ?? ""})</span></div>
  {#if status.linkedHubProjectId}
    <div class="row"><span class="label">This book</span><span>linked</span></div>
    <div class="row"><span class="label">Last synced</span>
      <span>{when(status.sync?.lastPullAt)}{status.syncing ? " · syncing now" : ""}</span></div>
    {#if status.sync?.lastError}<p class="error">Last attempt: {status.sync.lastError}</p>{/if}
    <div class="actions">
      <button class="small-button" on:click={() => run("Sync started.", () => bridge.hubSyncNow())} disabled={busy}>Sync now</button>
    </div>
    {#if conflicts.length > 0}
      <h4>Conflicts ({conflicts.length})</h4>
      <p class="desc">Someone else changed a decision you also changed. Yours is kept; theirs is shown here so you can decide again.</p>
      <ul class="conflicts">
        {#each conflicts as item (item.id)}
          <li>
            <span><strong>{item.theirActorName || item.theirActorId || "Someone"}</strong> ·
              {conflictLabel(item)} · {when(item.theirCreatedAt)}</span>
            <button class="small-button" disabled={busy}
              on:click={() => run("Kept your decision.", () => bridge.hubResolveConflict(item.id, "kept-mine"))}>Keep mine</button>
          </li>
        {/each}
      </ul>
    {/if}
  {:else}
    <p class="desc">This book is not linked. Linking shares its decisions with the hub; the first device to link a book defines it for everyone.</p>
    <div class="actions">
      <button class="small-button primary" on:click={() => run("Book linked.", () => bridge.hubLink())} disabled={busy}>Link this book</button>
    </div>
  {/if}
  <div class="actions">
    <button class="small-button danger" on:click={() => run("Left the hub; nothing on this device was removed.", () => bridge.hubLeave())} disabled={busy}>Leave the hub</button>
  </div>
{:else}
  <form class="join" on:submit|preventDefault={join}>
    <label><span>Hub address</span><input bind:value={url} placeholder="http://team-hub:8765" aria-label="Hub address" disabled={busy} /></label>
    <label><span>Join code</span><input bind:value={joinCode} placeholder="1A2B-3C4D-5E6F" aria-label="Join code" disabled={busy} /></label>
    <label><span>Your name on the team</span><input bind:value={displayName} placeholder="Your display name" aria-label="Your name on the team" disabled={busy} /></label>
    <button type="submit" class="small-button primary" disabled={busy || !url.trim() || !joinCode.trim()}>Join</button>
  </form>
{/if}
{#if notice}<p class="notice">{notice}</p>{/if}
{#if error}<p class="error">{error}</p>{/if}

<style>
  h3 { margin: 0 0 6px; }
  h4 { margin: 14px 0 4px; font-size: var(--fs-sm); }
  .desc { color: var(--text-2); font-size: var(--fs-xs); line-height: 1.5; margin: 0 0 12px; }
  .row { display: flex; gap: 12px; font-size: var(--fs-xs); margin: 4px 0; color: var(--text); }
  .label { width: 110px; color: var(--text-2); flex-shrink: 0; }
  .actions { display: flex; gap: 8px; margin: 10px 0; }
  .join { display: flex; flex-direction: column; gap: 10px; max-width: 420px; }
  .join label { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-2xs); color: var(--text-2); }
  .join input { font: inherit; padding: 6px 8px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); }
  .conflicts { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-xs); }
  .conflicts li { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
  .small-button { border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); padding: 6px 10px; cursor: pointer; font-size: var(--fs-2xs); align-self: flex-start; }
  .small-button.primary { background: var(--accent); color: white; border-color: var(--accent); }
  .small-button.danger { color: var(--danger); }
  .small-button:disabled { opacity: .5; cursor: default; }
  .notice { color: var(--pass); font-size: var(--fs-xs); }
  .error { color: var(--danger); font-size: var(--fs-xs); }
</style>
