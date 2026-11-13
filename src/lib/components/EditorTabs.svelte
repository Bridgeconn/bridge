<script lang="ts">
  /** One group's tab strip (2026-11-14), after VS Code: a tab per pane of
   *  the group (the verse list or a docked side panel), each the rail's icon,
   *  the pane's name and a close button. The chosen tab's pane fills the
   *  group. A tab drags to another group or to a group's edge to split it
   *  (EditorWorkspace owns the drag). Left and Right arrows move between the
   *  group's tabs; a middle click closes one; the button at the strip's end
   *  splits the chosen tab off to the right. In a narrow group the names
   *  shorten with an ellipsis. */
  import { getContext } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import type { EditorDockContext } from "../editorDocking";
  import { EDITOR_TABS, closeTab, selectTab, splitTab, tabLayout, type EditorTabId } from "../editorTabs";

  export let group: string;

  const docking = getContext<EditorDockContext | undefined>("editor-docking");
  let strip: HTMLElement;
  $: tabs = $tabLayout.groups[group]?.tabs ?? [];
  $: current = $tabLayout.groups[group]?.active;
  $: focused = $tabLayout.focused === group;

  function onKey(event: KeyboardEvent, id: EditorTabId): void {
    const at = tabs.indexOf(id);
    const to = event.key === "ArrowRight" ? tabs[(at + 1) % tabs.length]
      : event.key === "ArrowLeft" ? tabs[(at - 1 + tabs.length) % tabs.length]
      : event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[tabs.length - 1] : undefined;
    if (to === undefined) {
      if (event.key === "Delete") { event.preventDefault(); closeTab(id); }
      return;
    }
    event.preventDefault();
    selectTab(to);
    strip?.querySelector<HTMLElement>(`[data-tab="${to}"]`)?.focus();
  }
</script>

{#if tabs.length}
  <div class="editor-tabs no-print" class:focused bind:this={strip}>
    <div class="tab-list" role="tablist" aria-label="Open panels">
      {#each tabs as id (id)}
        <div class="tab" class:current={current === id}>
          <button type="button" class="tab-main" role="tab" data-tab={id} aria-selected={current === id}
            aria-controls={id === "editor" ? "editor-verses-pane" : `side-panel-${id}`} tabindex={current === id ? 0 : -1}
            title={`${EDITOR_TABS[id].title}. Drag to another group, or to an edge to split`}
            on:pointerdown={(event) => docking?.beginMove(id, event)}
            on:click={() => selectTab(id)} on:keydown={(event) => onKey(event, id)}
            on:auxclick={(event) => { if (event.button === 1) { event.preventDefault(); closeTab(id); } }}>
            <UiIcon name={EDITOR_TABS[id].icon} /><span class="tab-name">{EDITOR_TABS[id].label}</span>
          </button>
          <button type="button" class="tab-close" aria-label={`Close ${EDITOR_TABS[id].label}`} tabindex="-1"
            use:tooltip={`Close ${EDITOR_TABS[id].label}`} on:click={() => closeTab(id)}><UiIcon name="close" /></button>
        </div>
      {/each}
    </div>
    {#if tabs.length > 1 && current}
      <button type="button" class="strip-tool" aria-label={`Split ${EDITOR_TABS[current].label} to the right`}
        use:tooltip={`Split right: show ${EDITOR_TABS[current].label} beside the other tabs`}
        on:click={() => current && splitTab(current, group, "right")}><UiIcon name="split" /></button>
    {/if}
  </div>
{/if}

<style>
  /* The strip is the frame's grey; the chosen tab is the pane's white, joined
     to the pane below it. No lines: the two colours are the edge. Heights are
     multiples of 4 px, whole device pixels at 125% and 150% display scale; a
     fractional height left a hairline of grey between the tab and its pane. */
  .editor-tabs { display: flex; align-items: flex-end; min-width: 0; height: 36px; box-sizing: border-box; padding: 4px 6px 0; background: var(--bg); overflow: hidden; }
  .tab-list { flex: 1 1 auto; display: flex; align-items: flex-end; gap: 2px; min-width: 0; height: 32px; overflow-x: auto; overflow-y: hidden; scrollbar-width: none; }
  .tab-list::-webkit-scrollbar { display: none; }
  .strip-tool { flex: none; align-self: center; display: grid; place-items: center; width: 24px; height: 24px; margin: 0 0 4px 4px; padding: 0; border: 0; border-radius: 6px;
    background: transparent; color: var(--text-3); cursor: pointer; transition: color .15s, background .15s; }
  .strip-tool :global(svg) { width: 15px; height: 15px; }
  .strip-tool:hover, .strip-tool:focus-visible { background: var(--surface); color: var(--text); }
  .tab { position: relative; flex: 0 1 auto; min-width: 44px; max-width: 200px; display: flex; align-items: center; height: 32px; box-sizing: border-box;
    border: 0; border-radius: 8px 8px 0 0; color: var(--text-2); transition: color .15s, background .15s; }
  .tab:hover { background: var(--surface-2); color: var(--text); }
  .tab.current, .tab.current:hover { background: var(--surface); color: var(--text); }
  /* Whatever rounding is left at the tab's foot is painted white. */
  .tab.current::after { content: ""; position: absolute; left: 0; right: 0; bottom: -2px; height: 4px; background: var(--surface); pointer-events: none; }
  /* Icon, name and close share one centre line: every box is centred, the
     text has no extra line height, and the name is lifted the pixel its
     font sits low by. */
  .tab-main { flex: 1 1 auto; min-width: 0; display: flex; align-items: center; gap: 7px; height: 100%; padding: 0 0 0 10px; border: 0; background: transparent;
    color: inherit; font: inherit; font-size: var(--fs-2xs); font-weight: 600; line-height: 1; cursor: pointer; border-radius: 8px 0 0 0; }
  .tab-main :global(svg) { display: block; width: 15px; height: 15px; flex: none; color: var(--text-3); }
  /* The group in use has its chosen tab's icon in the accent colour. */
  .focused .tab.current .tab-main :global(svg) { color: var(--accent); }
  .tab-main { touch-action: none; }
  .tab-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; line-height: 1.25; position: relative; top: -1px; }
  .tab-main:focus-visible { outline: 2px solid var(--accent); outline-offset: -3px; }
  /* The same close as the breadcrumb's: grey, red on a red tint when pointed at. */
  .tab-close { flex: none; display: grid; place-items: center; width: 20px; height: 20px; margin: 0 6px 0 10px; padding: 0; border: 0; border-radius: 6px;
    background: transparent; color: var(--text-3); cursor: pointer; opacity: 0; transition: color .15s, background .15s; }
  .tab-close :global(svg) { display: block; width: 13px; height: 13px; }
  .tab:hover .tab-close, .tab.current .tab-close, .tab-close:focus-visible { opacity: 1; }
  .tab-close:hover, .tab-close:focus-visible { background: var(--danger-bg); color: var(--danger); }
  @media (prefers-reduced-motion: reduce) { .tab, .tab-close { transition: none; } }
</style>
