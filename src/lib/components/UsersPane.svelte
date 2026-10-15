<script lang="ts">
  /** The Users screen (#237, requirement 4), a pane of Settings for a
   *  project_admin: add a user, rename one, change a role, deactivate one.
   *  Renaming never splits history: the stable user id stays, every row that
   *  person wrote re-labels. Deactivating keeps the rows and the name they
   *  carry. Anyone else sees the list read-only, with why. */
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import type { UserRole, WorkspaceUser } from "../types/finding";
  import { project } from "../stores";
  import { refreshProjectRoles } from "../projectRole";

  export let myRole: UserRole = "project_admin";

  let users: WorkspaceUser[] = [];
  let currentUserId = "";
  let loading = true;
  let busy = false;
  let error = "";
  let notice = "";
  let newName = "";
  let newRole: UserRole = "editor";
  let renamingId = "";
  let renameDraft = "";
  let showInactive = false;
  /** #279: each user's role on the open project; null is their installation role. */
  let projectRoles: Record<string, UserRole | null> | null = null;

  const ROLES: UserRole[] = ["project_admin", "editor", "reporter"];
  const ROLE_LABELS: Record<UserRole, string> = {
    project_admin: "project admin", editor: "editor", reporter: "reporter",
  };

  $: canManage = myRole === "project_admin";

  /** "an editor", "a reporter", "a project admin". */
  function aRole(role: UserRole): string {
    const label = ROLE_LABELS[role];
    return `${/^[aeiou]/.test(label) ? "an" : "a"} ${label}`;
  }
  $: visible = users.filter((user) => showInactive || user.active);
  $: inactiveCount = users.filter((user) => !user.active).length;

  onMount(() => { void load(); });

  async function load() {
    loading = true;
    error = "";
    try {
      const listed = await bridge.usersList();
      users = listed.users;
      currentUserId = listed.currentUserId;
      projectRoles = $project
        ? Object.fromEntries((await bridge.teamRoles()).users.map((u) => [u.userId, u.projectRole]))
        : null;
    } catch (value) {
      error = message(value);
    } finally {
      loading = false;
    }
  }

  async function run(label: string, action: () => Promise<unknown>) {
    busy = true;
    error = "";
    notice = "";
    try {
      await action();
      await load();
      notice = label;
    } catch (value) {
      error = message(value);
    } finally {
      busy = false;
    }
  }

  function add() {
    const name = newName.trim();
    if (!name) return;
    void run(`${name} added.`, async () => {
      await bridge.usersCreate(name, newRole);
      newName = "";
    });
  }

  function startRename(user: WorkspaceUser) {
    renamingId = user.userId;
    renameDraft = user.displayName;
  }

  function commitRename(user: WorkspaceUser) {
    const name = renameDraft.trim();
    renamingId = "";
    if (!name || name === user.displayName) return;
    void run(`${user.displayName} is now ${name}; their history is unchanged.`, () => bridge.usersRename(user.userId, name));
  }

  function setRole(user: WorkspaceUser, value: string) {
    const role = value as UserRole;
    if (role === user.role) return;
    void run(`${user.displayName} is now ${aRole(role)}.`, () => bridge.usersSetRole(user.userId, role));
  }

  function setProjectRole(user: WorkspaceUser, value: string) {
    const role = value ? (value as UserRole) : null;
    const where = $project?.bookName ? ` on ${$project.bookName}` : " on this project";
    void run(role ? `${user.displayName} is now ${aRole(role)}${where}.`
      : `${user.displayName} has their usual role${where} again.`, async () => {
      await bridge.teamSetRole(user.userId, role);
      await refreshProjectRoles(true);
    });
  }

  function deactivate(user: WorkspaceUser) {
    void run(`${user.displayName} deactivated; what they wrote stays under their name.`, () => bridge.usersDeactivate(user.userId));
  }

  function message(value: unknown): string {
    return value instanceof Error ? value.message : String(value);
  }
</script>

<h3>Users</h3>
<p class="desc">
  Everyone who works on this machine, by name. Each name is a stable identity: every decision, edit and
  alignment is recorded under it, a rename keeps that history, and deactivating keeps what was written.
  {#if !canManage}<strong>Only a project admin can change this list.</strong>{/if}
</p>

{#if loading}
  <p class="muted">Loading users…</p>
{:else}
  <table class="users" aria-label="Users">
    <thead><tr><th>Name</th><th>Role</th>{#if projectRoles}<th title="A role on the open project overrides the usual one there; managing users always follows the usual role">On this project</th>{/if}<th>Status</th><th></th></tr></thead>
    <tbody>
      {#each visible as user (user.userId)}
        <tr class:inactive={!user.active}>
          <td>
            {#if renamingId === user.userId}
              <input class="rename" aria-label="New name for {user.displayName}" bind:value={renameDraft}
                on:keydown={(event) => { if (event.key === "Enter") commitRename(user); if (event.key === "Escape") renamingId = ""; }}
                on:blur={() => commitRename(user)} />
            {:else}
              <strong>{user.displayName}</strong>{#if user.userId === currentUserId}<span class="you"> (you)</span>{/if}
            {/if}
          </td>
          <td>
            {#if canManage && user.active}
              <select aria-label="Role for {user.displayName}" value={user.role} disabled={busy}
                on:change={(event) => setRole(user, event.currentTarget.value)}>
                {#each ROLES as role}<option value={role}>{ROLE_LABELS[role]}</option>{/each}
              </select>
            {:else}
              {ROLE_LABELS[user.role] ?? user.role}
            {/if}
          </td>
          {#if projectRoles}
            <td>
              {#if canManage && user.active}
                <select aria-label="Role on this project for {user.displayName}" value={projectRoles[user.userId] ?? ""}
                  disabled={busy} on:change={(event) => setProjectRole(user, event.currentTarget.value)}>
                  <option value="">usual role</option>
                  {#each ROLES as role}<option value={role}>{ROLE_LABELS[role]}</option>{/each}
                </select>
              {:else}
                {@const scoped = projectRoles[user.userId]}
                {scoped ? ROLE_LABELS[scoped] : "usual role"}
              {/if}
            </td>
          {/if}
          <td>{user.active ? "active" : "deactivated"}</td>
          <td class="actions">
            {#if canManage && user.active}
              <button class="small-button" on:click={() => startRename(user)} disabled={busy}>Rename</button>
              <button class="small-button danger" on:click={() => deactivate(user)}
                disabled={busy || user.userId === currentUserId}
                title={user.userId === currentUserId ? "You cannot deactivate yourself" : "Keeps everything they wrote"}>Deactivate</button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if inactiveCount > 0}
    <label class="show-inactive"><input type="checkbox" bind:checked={showInactive} /> Show deactivated ({inactiveCount})</label>
  {/if}

  {#if canManage}
    <form class="add" on:submit|preventDefault={add}>
      <label><span>Add a user</span><input bind:value={newName} placeholder="Display name" aria-label="Display name" disabled={busy} /></label>
      <label><span>Role</span>
        <select bind:value={newRole} aria-label="Role for the new user" disabled={busy}>
          {#each ROLES as role}<option value={role}>{ROLE_LABELS[role]}</option>{/each}
        </select>
      </label>
      <button type="submit" class="small-button primary" disabled={busy || !newName.trim()}>Add</button>
    </form>
  {/if}
{/if}
{#if notice}<p class="notice">{notice}</p>{/if}
{#if error}<p class="error">{error}</p>{/if}

<style>
  h3 { margin: 0 0 6px; }
  .desc, .muted { color: var(--text-2); font-size: var(--fs-xs); line-height: 1.5; margin: 0 0 12px; }
  .users { width: 100%; border-collapse: collapse; font-size: var(--fs-xs); }
  .users th, .users td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); color: var(--text); vertical-align: middle; }
  .users th { color: var(--text-2); font-weight: 650; }
  tr.inactive td { color: var(--text-3); }
  .you { color: var(--text-2); font-weight: 400; }
  .rename { font: inherit; padding: 2px 6px; border: 1px solid var(--accent); border-radius: 4px; background: var(--surface); color: var(--text); }
  .users select, .add select, .add input { font: inherit; padding: 4px 8px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); }
  .actions { display: flex; gap: 6px; justify-content: flex-end; }
  .show-inactive { display: flex; align-items: center; gap: 6px; font-size: var(--fs-2xs); color: var(--text-2); margin: 8px 0; }
  .add { display: flex; gap: 10px; align-items: flex-end; margin-top: 14px; }
  .add label { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-2xs); color: var(--text-2); }
  .small-button { border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); padding: 6px 10px; cursor: pointer; font-size: var(--fs-2xs); }
  .small-button.primary { background: var(--accent); color: white; border-color: var(--accent); }
  .small-button.danger { color: var(--danger); }
  .small-button:disabled { opacity: .5; cursor: default; }
  .notice { color: var(--pass); font-size: var(--fs-xs); margin: 10px 0 0; }
  .error { color: var(--danger); font-size: var(--fs-xs); margin: 10px 0 0; }
</style>
