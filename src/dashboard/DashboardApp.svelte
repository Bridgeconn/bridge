<script lang="ts">
  /** The team dashboard served by the hub (#81, Option A of 2026-10-12):
   *  projects and book progress for everyone signed in, CSV export for
   *  reporters and up, assignments and users for project admins. A browser
   *  surface over the hub's own data, not a web workbench. */
  import { onMount } from "svelte";
  import {
    hubApi, projectsCsv, signOut, signedIn,
    type HubMe, type HubProject, type HubRole, type HubUser,
  } from "./hubApi";

  let me: HubMe | null = null;
  let projects: HubProject[] = [];
  let users: HubUser[] = [];
  let tab: "projects" | "users" = "projects";
  let loading = true;
  let error = "";
  let notice = "";
  let joinCode = "";
  let displayName = "";
  let assigning: HubProject | null = null;
  let inviteRole: HubRole = "editor";
  let invite = "";

  $: isAdmin = me?.role === "project_admin";

  onMount(() => { void load(); });

  async function load() {
    loading = true;
    error = "";
    try {
      if (!signedIn()) { me = null; return; }
      me = await hubApi.me();
      projects = (await hubApi.projects()).projects;
      users = me.role === "project_admin" ? (await hubApi.users()).users : [];
    } catch (value) {
      error = message(value);
      if (!signedIn()) me = null;
    } finally {
      loading = false;
    }
  }

  async function signIn() {
    error = "";
    try {
      me = await hubApi.join(joinCode.trim(), displayName.trim());
      joinCode = "";
      await load();
    } catch (value) {
      error = message(value);
    }
  }

  function leave() {
    signOut();
    me = null;
    projects = [];
    users = [];
  }

  async function assign(project: HubProject, chapter: string, userId: string) {
    error = "";
    notice = "";
    try {
      await hubApi.assign(project.hubProjectId, chapter, userId);
      projects = (await hubApi.projects()).projects;
      assigning = projects.find((p) => p.hubProjectId === project.hubProjectId) ?? null;
      notice = "Saved. Devices pick it up on their next sync.";
    } catch (value) {
      error = message(value);
    }
  }

  async function makeInvite() {
    error = "";
    try {
      invite = (await hubApi.joinCode(inviteRole)).joinCode;
    } catch (value) {
      error = message(value);
    }
  }

  function exportCsv() {
    const blob = new Blob([projectsCsv(projects)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "bridge-team-progress.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  function assigneeFor(project: HubProject, chapter: string): string {
    return project.assignments.find((a) => a.chapter === chapter)?.assigneeId ?? "";
  }

  function percent(part: number | undefined, total: number | undefined): number {
    return total ? Math.round(((part ?? 0) / total) * 100) : 0;
  }

  function when(value: string | null): string {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  }

  function message(value: unknown): string {
    return value instanceof Error ? value.message : String(value);
  }
</script>

<main class="dash">
  <header>
    <h1>Bridge team dashboard</h1>
    {#if me}
      <span class="who">{me.displayName} · {me.role.replace("_", " ")}</span>
      <button class="link" on:click={leave}>Sign out</button>
    {/if}
  </header>

  {#if loading}
    <p class="muted">Loading…</p>
  {:else if !me}
    <form class="signin" on:submit|preventDefault={signIn}>
      <p class="muted">Sign in with a join code from your project admin. No password: the code is the invitation.</p>
      <label>Join code <input bind:value={joinCode} aria-label="Join code" placeholder="1A2B-3C4D-5E6F" /></label>
      <label>Your name <input bind:value={displayName} aria-label="Your name" placeholder="Your display name" /></label>
      <button type="submit" class="primary" disabled={!joinCode.trim() || !displayName.trim()}>Sign in</button>
    </form>
  {:else}
    <nav>
      <button class:active={tab === "projects"} on:click={() => (tab = "projects")}>Projects</button>
      {#if isAdmin}<button class:active={tab === "users"} on:click={() => (tab = "users")}>Users</button>{/if}
      <span class="spacer"></span>
      {#if tab === "projects"}<button on:click={exportCsv} disabled={projects.length === 0}>Export CSV</button>{/if}
      <button on:click={load}>Refresh</button>
    </nav>

    {#if tab === "projects"}
      {#if projects.length === 0}
        <p class="muted">No book is linked to this hub yet. Link one from a desktop: Settings › Team › Link this book.</p>
      {:else}
        <table aria-label="Projects">
          <thead><tr><th>Book</th><th>Checked</th><th>Reviewed</th><th>Aligned</th><th>Assigned to</th><th>Last activity</th>{#if isAdmin}<th></th>{/if}</tr></thead>
          <tbody>
            {#each projects as p (p.hubProjectId)}
              <tr>
                <td><strong>{p.bookName}</strong>{#if p.projectName}<small> · {p.projectName}</small>{/if}</td>
                <td>{p.totals.checkedChapterCount ?? 0}/{p.totals.chapterCount ?? p.chapters.length} ch</td>
                <td>{percent(p.totals.reviewedVerseCount, p.totals.verseCount)}%</td>
                <td>{p.totals.alignedKnownVerseCount ? `${percent(p.totals.alignedVerseCount, p.totals.alignedKnownVerseCount)}%` : "—"}</td>
                <td>{p.assignments.map((a) => `${a.chapter ? `ch ${a.chapter}` : "book"}: ${a.assigneeName || a.assigneeId}`).join(" · ") || "—"}</td>
                <td>{when(p.lastActivityAt)}</td>
                {#if isAdmin}<td><button on:click={() => (assigning = p)}>Assign…</button></td>{/if}
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
      {#if assigning}
        <section class="assign" aria-label="Assign {assigning.bookName}">
          <h2>Assign {assigning.bookName}</h2>
          {#each ["", ...assigning.chapters] as chapter (chapter)}
            <label>
              <span>{chapter ? `Chapter ${chapter}` : "Whole book"}</span>
              <select aria-label="Assignee for {chapter ? `Chapter ${chapter}` : 'Whole book'}"
                value={assigneeFor(assigning, chapter)}
                on:change={(event) => assigning && assign(assigning, chapter, event.currentTarget.value)}>
                <option value="">— nobody —</option>
                {#each users as user (user.userId)}<option value={user.userId}>{user.displayName}</option>{/each}
              </select>
            </label>
          {/each}
          <button on:click={() => (assigning = null)}>Done</button>
        </section>
      {/if}
    {:else}
      <table aria-label="Users">
        <thead><tr><th>Name</th><th>Role</th><th>Devices</th><th>Last seen</th></tr></thead>
        <tbody>
          {#each users as user (user.userId)}
            <tr><td>{user.displayName}</td><td>{user.role.replace("_", " ")}</td><td>{user.devices}</td><td>{when(user.lastSeenAt)}</td></tr>
          {/each}
        </tbody>
      </table>
      <section class="invite">
        <label>Invite as
          <select bind:value={inviteRole} aria-label="Role for the invitation">
            <option value="editor">editor</option><option value="reporter">reporter</option><option value="project_admin">project admin</option>
          </select>
        </label>
        <button on:click={makeInvite}>Create join code</button>
        {#if invite}<p>Join code: <code>{invite}</code></p>{/if}
      </section>
    {/if}
  {/if}
  {#if notice}<p class="notice">{notice}</p>{/if}
  {#if error}<p class="error">{error}</p>{/if}
</main>

<style>
  :global(body) { margin: 0; font-family: system-ui, "Segoe UI", sans-serif; background: #f7f7f5; color: #1d2329; }
  .dash { max-width: 1100px; margin: 0 auto; padding: 20px; }
  header { display: flex; align-items: baseline; gap: 12px; }
  h1 { font-size: 22px; margin: 0 auto 0 0; }
  h2 { font-size: 16px; }
  .who { color: #5b6470; font-size: 13px; }
  nav { display: flex; gap: 8px; margin: 16px 0; }
  nav button.active { background: #2a5bd7; color: white; border-color: #2a5bd7; }
  .spacer { flex: 1; }
  button { font: inherit; font-size: 13px; padding: 6px 10px; border: 1px solid #c4cbd3; border-radius: 6px; background: white; cursor: pointer; }
  button.primary { background: #2a5bd7; color: white; border-color: #2a5bd7; }
  button.link { border: none; background: none; color: #2a5bd7; }
  button:disabled { opacity: .5; cursor: default; }
  table { width: 100%; border-collapse: collapse; background: white; font-size: 13px; }
  th, td { text-align: left; padding: 8px; border-bottom: 1px solid #e3e6ea; }
  th { color: #5b6470; font-weight: 600; }
  small { color: #5b6470; }
  .signin, .assign, .invite { display: flex; flex-direction: column; gap: 10px; max-width: 420px; margin-top: 16px; }
  .assign label { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
  input, select { font: inherit; padding: 6px 8px; border: 1px solid #c4cbd3; border-radius: 6px; }
  .muted { color: #5b6470; }
  .notice { color: #1d7a3e; }
  .error { color: #b3261e; }
  @media (prefers-color-scheme: dark) {
    :global(body) { background: #15191d; color: #e6e9ec; }
    table, button, input, select { background: #1e2328; color: #e6e9ec; border-color: #3a424b; }
    th, td { border-color: #2c333a; }
  }
</style>
