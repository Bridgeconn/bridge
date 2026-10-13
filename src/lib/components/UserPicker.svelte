<script lang="ts">
  /** The startup display-name picker (#237, requirement 4). Shown before
   *  Project Home when the installation has several active users and none is
   *  chosen yet. Local mode: a name, no password. Picking a user makes it the
   *  signed-in user for every write; "New name" creates one. The role is
   *  shown so a reporter knows what the app will refuse. */
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import type { UserRole, WorkspaceUser } from "../types/finding";

  export let onDone: (user: WorkspaceUser) => void;

  let users: WorkspaceUser[] = [];
  let loading = true;
  let busy = false;
  let error = "";
  let newName = "";
  let newRole: UserRole = "editor";
  let creating = false;

  const ROLE_LABELS: Record<UserRole, string> = {
    project_admin: "project admin", editor: "editor", reporter: "reporter",
  };

  onMount(() => { void load(); });

  async function load() {
    loading = true;
    error = "";
    try {
      const listed = await bridge.usersList();
      users = listed.users.filter((user) => user.active);
      // The first installation has one user and nobody to choose between.
      if (users.length === 1 && !listed.currentUserId) await choose(users[0]);
    } catch (value) {
      error = message(value);
    } finally {
      loading = false;
    }
  }

  async function choose(user: WorkspaceUser) {
    busy = true;
    error = "";
    try {
      await bridge.usersSetCurrent(user.userId);
      onDone({ ...user, current: true });
    } catch (value) {
      error = message(value);
    } finally {
      busy = false;
    }
  }

  async function create() {
    const name = newName.trim();
    if (!name) return;
    busy = true;
    error = "";
    try {
      const created = await bridge.usersCreate(name, newRole);
      await bridge.usersSetCurrent(created.userId);
      onDone({ ...created, current: true });
    } catch (value) {
      error = message(value);
    } finally {
      busy = false;
    }
  }

  function message(value: unknown): string {
    return value instanceof Error ? value.message : String(value);
  }
</script>

<div class="picker" role="dialog" aria-labelledby="picker-title">
  <div class="card">
    <div class="eyebrow">WHO IS WORKING</div>
    <h1 id="picker-title">Pick your name</h1>
    <p class="intro">Every decision, edit and alignment you make is recorded under this name. No password: this is one machine, trusted by the team using it.</p>
    {#if loading}
      <p class="muted">Loading users…</p>
    {:else}
      {#if users.length > 0 && !creating}
        <ul class="users" aria-label="Users">
          {#each users as user (user.userId)}
            <li>
              <button class="user" on:click={() => choose(user)} disabled={busy}>
                <strong>{user.displayName}</strong>
                <span class="role">{ROLE_LABELS[user.role] ?? user.role}</span>
              </button>
            </li>
          {/each}
        </ul>
        <button class="link-button" on:click={() => (creating = true)} disabled={busy}>New name</button>
      {:else}
        <form class="new-user" on:submit|preventDefault={create}>
          <label>
            <span>Your name</span>
            <input bind:value={newName} placeholder="e.g. Rina" autocomplete="off" disabled={busy} />
          </label>
          <label>
            <span>Role</span>
            <select bind:value={newRole} disabled={busy}>
              <option value="editor">editor — checks, decisions, alignment</option>
              <option value="reporter">reporter — reads and reports only</option>
              <option value="project_admin">project admin — everything, including users</option>
            </select>
          </label>
          <div class="actions">
            {#if users.length > 0}
              <button type="button" class="link-button" on:click={() => (creating = false)} disabled={busy}>Back to the list</button>
            {/if}
            <button type="submit" class="primary" disabled={busy || !newName.trim()}>Continue</button>
          </div>
        </form>
      {/if}
    {/if}
    {#if error}<p class="error">{error}</p>{/if}
  </div>
</div>

<style>
  .picker { position: absolute; inset: 0; z-index: 25; display: flex; align-items: center; justify-content: center; background: var(--surface); }
  .card { width: min(520px, calc(100% - 32px)); padding: 28px 32px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); }
  .eyebrow { color: var(--accent); font-size: var(--fs-2xs); letter-spacing: .12em; font-weight: 800; margin-bottom: 8px; }
  h1 { font-size: var(--fs-3xl); margin: 0 0 8px; color: var(--text); }
  .intro, .muted { color: var(--text-2); font-size: var(--fs-sm); margin: 0 0 16px; line-height: 1.5; }
  .users { list-style: none; margin: 0 0 12px; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  .user { width: 100%; display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface-2); color: var(--text); cursor: pointer; font: inherit; }
  .user:hover { border-color: var(--accent); }
  .role { font-size: var(--fs-2xs); color: var(--text-2); }
  .new-user { display: flex; flex-direction: column; gap: 12px; }
  .new-user label { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-xs); color: var(--text-2); }
  .new-user input, .new-user select { font: inherit; padding: 8px 10px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); }
  .actions { display: flex; justify-content: flex-end; gap: 10px; align-items: center; }
  .primary { font: inherit; font-weight: 700; padding: 8px 16px; border-radius: 8px; border: none; background: var(--accent); color: white; cursor: pointer; }
  .primary:disabled { opacity: .5; cursor: default; }
  .link-button { background: none; border: none; color: var(--accent); cursor: pointer; font: inherit; font-size: var(--fs-xs); padding: 0; }
  .error { color: var(--danger); font-size: var(--fs-xs); margin: 12px 0 0; }
</style>
