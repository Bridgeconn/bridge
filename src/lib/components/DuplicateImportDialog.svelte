<script context="module" lang="ts">
  export interface RelatedImportProject {
    id: string;
    label: string;
    path: string;
    projectId: string;
    missing: boolean;
    exactBooks: string[];
    possibleBooks: string[];
  }
</script>

<script lang="ts">
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";

  export let projects: RelatedImportProject[];
  export let exact = false;
  export let busy = false;
  export let error: string | null = null;
  export let onOpen: (project: RelatedImportProject) => void;
  export let onCreate: () => void;

  function modal(node: HTMLDialogElement) {
    const previousFocus = document.activeElement;
    // showModal supplies background inertness and focus containment in WebView2.
    // The fallback keeps component tests usable in DOMs without dialog support.
    if (typeof node.showModal === "function") node.showModal();
    else node.setAttribute("open", "");
    node.querySelector<HTMLElement>("h2")?.focus();
    const preventCancel = (event: Event) => event.preventDefault();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); }
      if (event.key !== "Tab") return;
      const buttons = [...node.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
      const first = buttons[0];
      const last = buttons[buttons.length - 1];
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || !buttons.includes(document.activeElement as HTMLButtonElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    };
    node.addEventListener("cancel", preventCancel);
    node.addEventListener("keydown", onKey);
    return { destroy() {
      node.removeEventListener("cancel", preventCancel);
      node.removeEventListener("keydown", onKey);
      if (typeof node.close === "function") node.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    } };
  }
</script>

<dialog class="duplicate-dialog" aria-modal="true" aria-labelledby="duplicate-title" aria-describedby="duplicate-description" use:modal>
  <header>
    <span class="dialog-icon" aria-hidden="true"><UiIcon name="archive" /></span>
    <div>
      <h2 id="duplicate-title" tabindex="-1">{exact ? "This source is already imported" : "Related projects found"}</h2>
      <p id="duplicate-description">Open a project below, or create a new project with a separate copy.</p>
    </div>
  </header>
  <div class="related-heading"><h3>Related projects</h3><span>{projects.length}</span></div>
  <div class="related-list" role="group" aria-label="Related projects">
    {#each projects as project (project.id)}
      <article class="related-project">
        <div class="related-copy">
          <strong>{project.label}</strong>
          <small class="match-label" use:tooltip={(project.exactBooks.length ? "Same source: " + project.exactBooks.join(", ") : "Related books: " + project.possibleBooks.join(", "))}>
            {project.exactBooks.length ? (project.exactBooks.length <= 4 ? `Same source: ${project.exactBooks.join(", ")}` : `Same source · ${project.exactBooks.length} books`) : `Related metadata · ${project.possibleBooks.length} ${project.possibleBooks.length === 1 ? "book" : "books"}`}
          </small>
          <small class="project-path">{project.path}</small>
          {#if project.missing}<small class="missing-label">Project folder is missing</small>{/if}
        </div>
        <button class="open-project" aria-label={`Open ${project.label}`} use:tooltip={`Open ${project.label}`} disabled={busy || project.missing} on:click={() => onOpen(project)}><UiIcon name="open" /></button>
      </article>
    {/each}
  </div>
  <footer>
    {#if error}<p class="dialog-error" role="alert">{error}</p>{/if}
    <button class="create-project" disabled={busy} on:click={onCreate}>Create a new project <span aria-hidden="true">→</span></button>
    <p>Existing projects and source files stay unchanged.</p>
  </footer>
</dialog>

<style>
  .duplicate-dialog { width: min(680px, calc(100% - 32px)); max-height: min(720px, calc(100dvh - 40px)); padding: 0; border: 1px solid var(--border); border-radius: 18px; background: var(--surface); color: var(--text); box-shadow: 0 24px 80px rgb(0 0 0 / 20%); overflow: hidden; }
  .duplicate-dialog[open] { display: flex; flex-direction: column; }
  .duplicate-dialog::backdrop { background: rgb(15 23 42 / 38%); backdrop-filter: blur(3px); }
  header { display: flex; align-items: flex-start; gap: 14px; padding: 24px 24px 20px; flex-shrink: 0; }
  header > div { min-width: 0; }
  .dialog-icon { display: grid; place-items: center; width: 40px; height: 40px; flex-shrink: 0; border-radius: 12px; color: var(--accent); background: var(--accent-bg); }
  h2 { margin: 0; font-size: var(--fs-2xl); line-height: 1.4; }
  h2:focus { outline: none; }
  header p { margin: 6px 0 0; color: var(--text-2); font-size: var(--fs-xs); line-height: 1.6; }
  .related-heading { display: flex; align-items: center; gap: 8px; padding: 0 24px 12px; flex-shrink: 0; }
  h3 { margin: 0; font-size: var(--fs-sm); font-weight: 600; }
  .related-heading > span { color: var(--text-2); background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: 2px 7px; font-size: var(--fs-3xs); }
  .related-list { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; padding: 0 18px 8px 24px; }
  .related-project { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 11px; margin-bottom: 8px; }
  .related-copy { display: flex; flex: 1; min-width: 0; flex-direction: column; gap: 2px; }
  strong { font-size: var(--fs-sm); overflow-wrap: anywhere; }
  small { font-size: var(--fs-3xs); line-height: 1.35; }
  .match-label { color: var(--accent); }
  .project-path { color: var(--text-2); overflow-wrap: anywhere; }
  .missing-label, .dialog-error { color: var(--danger); }
  button { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 36px; padding: 8px 12px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); color: var(--text); cursor: pointer; font: inherit; font-size: var(--fs-2xs); font-weight: 600; }
  .open-project { flex-shrink: 0; width: 34px; height: 34px; min-height: 34px; padding: 0; color: var(--accent); border: 0; background: transparent; transition: color .15s, background .15s; }
  .open-project:hover:not(:disabled), .open-project:focus-visible { background: var(--accent-bg); color: var(--accent); }
  button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  button:disabled { cursor: not-allowed; opacity: .5; }
  footer { flex-shrink: 0; padding: 16px 24px 20px; border-top: 1px solid var(--border); }
  .create-project { width: 100%; min-height: 42px; background: var(--accent); color: white; border-color: var(--accent); }
  .create-project:hover:not(:disabled) { filter: brightness(.95); }
  footer p { color: var(--text-2); font-size: var(--fs-3xs); text-align: center; margin: 10px 0 0; line-height: 1.5; }
  footer .dialog-error { margin: 0 0 12px; text-align: left; }
  @media (max-width: 480px) {
    header { padding: 18px 16px 16px; gap: 10px; }
    h2 { font-size: var(--fs-lg); }
    .related-heading { padding-left: 16px; padding-right: 16px; }
    .related-list { padding-left: 16px; padding-right: 10px; }
    .related-project { gap: 10px; padding: 10px; }
    .open-project { margin-left: auto; }
    footer { padding: 14px 16px; }
  }
  @media (max-height: 480px) {
    header { padding-top: 12px; padding-bottom: 12px; }
    footer { padding-top: 10px; padding-bottom: 10px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .open-project { transition: none; }
  }
</style>
