<script lang="ts">
  /** The editor's work area (2026-11-14): tab groups, after VS Code. Each
   *  group is a frame with its own tab strip (EditorTabs) and shows one pane;
   *  the panes themselves are the slot's (the verse list and the SidePanels),
   *  each placed in its group's frame or hidden behind another tab.
   *
   *  A tab drags: over the middle or the strip of a group
   *  it joins that group; near an edge it splits the group on that side; a
   *  tinted box shows which before release. Released outside the Bridge
   *  window, a side panel opens in its own window.
   *  The line between two groups drags, or takes arrow keys, to resize. */
  import { setContext } from "svelte";
  import { derived, get } from "svelte/store";
  import { alignmentBusy, alignmentDesktop } from "../alignmentWindow";
  import { detachAlignment } from "../alignmentUi";
  import { arrange, type Divider, type DockEdge, type Frame, type LayoutNode } from "../alignmentLayout";
  import type { EditorDockContext } from "../editorDocking";
  import type { SidePanelId } from "../editorPrefs";
  import {
    TAB_STRIP_HEIGHT, closeGroup, focusGroup, groupOf, moveTab, paneStyle, resizeSplit, splitTab, tabLayout, type EditorTabId,
  } from "../editorTabs";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import EditorTabs from "./EditorTabs.svelte";

  export let onDetach: (id: SidePanelId) => void = () => {};
  let node: HTMLDivElement;

  $: arranged = arrange($tabLayout.tree);
  $: groupFrames = arranged.frames;
  $: dividers = arranged.dividers;
  $: groupIds = Object.keys($tabLayout.groups);
  // Each showing pane's frame is its group's.
  const frames = derived(tabLayout, (layout) => {
    const byGroup = arrange(layout.tree).frames;
    const out: Partial<Record<string, Frame>> = {};
    for (const gid of Object.keys(layout.groups)) { const active = layout.groups[gid].active; if (active) out[active] = byGroup[gid]; }
    return out;
  });
  $: editorFrame = paneStyle($frames.editor);
  const box = (frame: Frame | undefined): string =>
    frame ? `left:${frame.x}%;top:${frame.y}%;width:${frame.width}%;height:${frame.height}%` : "display:none";

  type Drop = { group: string; edge: DockEdge | null; index?: number; left: number; top: number; width: number; height: number };
  let moving: { id: EditorTabId; x: number; y: number; startX: number; startY: number; moved: boolean } | null = null;
  let candidate: Drop | null = null;
  let sizing: Divider | null = null;
  let beforeResize: LayoutNode | null = null;

  function beginMove(id: EditorTabId, event: PointerEvent): void {
    if (event.button !== 0) return;
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    moving = { id, x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY, moved: false };
  }
  function dropAt(x: number, y: number): Drop | null {
    if (!moving) return null;
    // By geometry, not elementsFromPoint: a group's frame lets the pointer
    // through to its pane (pointer-events: none), so hit testing skips it.
    const frame = Array.from(node.querySelectorAll<HTMLElement>("[data-tab-group]")).find((el) => {
      const rect = el.getBoundingClientRect();
      return x >= rect.left && x < rect.right && y >= rect.top && y < rect.bottom;
    });
    if (!frame) return null;
    const gid = frame.dataset.tabGroup!;
    const group = $tabLayout.groups[gid];
    if (!group) return null;
    const own = groupOf($tabLayout, moving.id) === gid;
    // An empty group takes the tab whole, wherever it is dropped on it.
    if (!group.tabs.length) { const r = frame.getBoundingClientRect(), b = node.getBoundingClientRect(); return { group: gid, edge: null, left: r.left - b.left, top: r.top - b.top, width: r.width, height: r.height }; }
    const r = frame.getBoundingClientRect(), b = node.getBoundingClientRect();
    const whole = { left: r.left - b.left, top: r.top - b.top, width: r.width, height: r.height };
    // Over the strip: into this group, before the tab under the pointer.
    if (y - r.top <= TAB_STRIP_HEIGHT) {
      const tabs = Array.from(frame.querySelectorAll<HTMLElement>("[data-tab]"));
      const before = tabs.findIndex((tab) => { const t = tab.getBoundingClientRect(); return x < t.left + t.width / 2; });
      return { group: gid, edge: null, index: before < 0 ? undefined : before, ...whole };
    }
    const px = (x - r.left) / r.width, py = (y - r.top - TAB_STRIP_HEIGHT) / Math.max(1, r.height - TAB_STRIP_HEIGHT);
    const edges: [DockEdge, number][] = [["left", px], ["right", 1 - px], ["top", py], ["bottom", 1 - py]];
    const [edge, distance] = edges.sort((first, second) => first[1] - second[1])[0];
    if (distance > 0.3) return own ? null : { group: gid, edge: null, ...whole };
    // The only tab of its own group has nothing to split from.
    if (own && group.tabs.length === 1) return null;
    return { group: gid, edge,
      left: whole.left + (edge === "right" ? r.width / 2 : 0), top: whole.top + (edge === "bottom" ? r.height / 2 : 0),
      width: edge === "left" || edge === "right" ? r.width / 2 : r.width, height: edge === "top" || edge === "bottom" ? r.height / 2 : r.height };
  }
  function move(event: PointerEvent): void {
    if (sizing) {
      const bounds = node.getBoundingClientRect(), horizontal = sizing.axis === "horizontal";
      const position = horizontal ? (event.clientX - bounds.left) / bounds.width * 100 : (event.clientY - bounds.top) / bounds.height * 100;
      resizeSplit(sizing.id, (position - (horizontal ? sizing.bounds.x : sizing.bounds.y)) / (horizontal ? sizing.bounds.width : sizing.bounds.height));
    }
    if (!moving) return;
    moving = { ...moving, x: event.clientX, y: event.clientY, moved: moving.moved || Math.hypot(event.clientX - moving.startX, event.clientY - moving.startY) > 5 };
    candidate = moving.moved ? dropAt(event.clientX, event.clientY) : null;
  }
  function finish(): void {
    if (moving?.moved) {
      const { id, x, y } = moving;
      if (candidate?.edge) splitTab(id, candidate.group, candidate.edge);
      else if (candidate) moveTab(id, candidate.group, candidate.index);
      // Released outside the Bridge window: its own window. Anywhere else
      // that is not a group (the rail, the bars): nothing, as in VS Code.
      else if (x <= 0 || x >= window.innerWidth || y <= 0 || y >= window.innerHeight) {
        if (id === "alignment" || id === "crossVerse") { if (alignmentDesktop() && !get(alignmentBusy)) detachAlignment(id === "crossVerse" ? "cross" : "word"); }
        else if (id !== "editor") onDetach(id);
      }
    }
    moving = null; candidate = null; sizing = null; beforeResize = null;
  }
  function cancel(): void {
    if (sizing && beforeResize) tabLayout.update((layout) => ({ ...layout, tree: beforeResize }));
    moving = null; candidate = null; sizing = null; beforeResize = null;
  }
  function resizeKey(d: Divider, event: KeyboardEvent): void {
    const negative = d.axis === "horizontal" ? "ArrowLeft" : "ArrowUp", positive = d.axis === "horizontal" ? "ArrowRight" : "ArrowDown";
    if (![negative, positive, "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    resizeSplit(d.id, event.key === "Home" ? .15 : event.key === "End" ? .85 : d.ratio + (event.key === negative ? -.02 : .02) * (event.shiftKey ? 3 : 1));
  }
  setContext<EditorDockContext>("editor-docking", { frames, beginMove, cancelMove: () => {
    if (!moving && !sizing) return false;
    cancel(); return true;
  } });
</script>

<svelte:window on:pointermove={move} on:pointerup={finish} on:pointercancel={cancel} on:keydown={(event) => { if (event.key === "Escape" && (moving || sizing)) { event.preventDefault(); event.stopImmediatePropagation(); cancel(); } }} />
<div class="layout-scroll"><div class="editor-layout" class:moving={!!moving?.moved} class:sizing={!!sizing} bind:this={node}>
  {#each groupIds as gid (gid)}
    <div class="group-frame" data-tab-group={gid} style={box(groupFrames[gid])}>
      <EditorTabs group={gid} />
    </div>
    {#if !$tabLayout.groups[gid].tabs.length}
      <!-- A layout preset's empty place (2026-11-16): a click makes it the
           one the next panel opens in; a tab can be dropped on it. -->
      <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
      <div class="empty-group" class:focused={$tabLayout.focused === gid} data-empty-group={gid} style={paneStyle(groupFrames[gid])} on:click={() => focusGroup(gid)}>
        <p class="empty-title">Empty</p>
        <p class="empty-text">Click a panel on the left to open it here, or drag a tab in.</p>
        <button type="button" class="empty-close" aria-label="Remove this empty area" use:tooltip={"Remove this empty area"}
          on:click|stopPropagation={() => closeGroup(gid)}><UiIcon name="close" /></button>
      </div>
    {/if}
  {/each}
  <slot {editorFrame} />
  {#each dividers as d (d.id)}
    <div class="divider" class:vertical={d.axis === "horizontal"} role="slider" tabindex="0"
      aria-label={d.axis === "horizontal" ? "Resize panel widths" : "Resize panel heights"}
      aria-orientation={d.axis === "horizontal" ? "vertical" : "horizontal"} aria-valuenow={Math.round(d.ratio * 100)} aria-valuemin="15" aria-valuemax="85"
      style:left={`${d.axis === "horizontal" ? d.at : d.bounds.x}%`} style:top={`${d.axis === "vertical" ? d.at : d.bounds.y}%`}
      style:width={d.axis === "horizontal" ? "8px" : `${d.bounds.width}%`} style:height={d.axis === "vertical" ? "8px" : `${d.bounds.height}%`}
      on:pointerdown={(event) => { event.preventDefault(); event.currentTarget.setPointerCapture?.(event.pointerId); sizing = d; beforeResize = $tabLayout.tree; }}
      on:keydown={(event) => resizeKey(d, event)} />
  {/each}
  {#if candidate}<div class="drop-preview" style:left={`${candidate.left}px`} style:top={`${candidate.top}px`} style:width={`${candidate.width}px`} style:height={`${candidate.height}px`} />{/if}
</div></div>

<style>
  .layout-scroll { flex: 1; min-width: 0; min-height: 0; display: flex; overflow: hidden; }
  .editor-layout { position: relative; flex: 1; min-width: 0; min-height: 0; }
  .moving, .sizing { user-select: none; }
  .moving { cursor: grabbing; }
  /* A group's frame holds only its tab strip; the pane is a sibling placed
     in the same frame, below the strip. The frame lets the pointer through
     to the pane except on the strip. */
  .group-frame { position: absolute; box-sizing: border-box; pointer-events: none; overflow: hidden; }
  .group-frame > :global(*) { pointer-events: auto; }
  /* A docked panel is a full tab: no line down its left side. */
  .editor-layout > :global(.side-panel) { border-left: 0; }
  .empty-group { box-sizing: border-box; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; padding: 16px; overflow: hidden;
    text-align: center; background: var(--surface); border: 1px dashed transparent; cursor: pointer; }
  .empty-group.focused { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 4%, var(--surface)); }
  .empty-title { margin: 0; font-size: var(--fs-xs); font-weight: 700; color: var(--text-2); }
  .empty-text { margin: 0; max-width: 240px; font-size: var(--fs-2xs); line-height: 1.4; color: var(--text-3); }
  .empty-close { position: absolute; top: 6px; right: 6px; display: grid; place-items: center; width: 24px; height: 24px; padding: 0; border: 0; border-radius: 6px; background: transparent; color: var(--text-3); cursor: pointer; }
  .empty-close :global(svg) { width: 14px; height: 14px; }
  .empty-close:hover, .empty-close:focus-visible { background: var(--danger-bg); color: var(--danger); }
  .divider { position: absolute; z-index: 6; background: transparent; cursor: row-resize; transform: translateY(-50%); touch-action: none; }
  .divider.vertical { cursor: col-resize; transform: translateX(-50%); }
  .divider::after { content: ""; position: absolute; left: 0; right: 0; top: 50%; height: 1px; background: var(--border); pointer-events: none; transition: background .15s, height .15s, width .15s; }
  .divider.vertical::after { left: 50%; right: auto; top: 0; bottom: 0; width: 1px; height: auto; }
  /* As in VS Code: the line between two groups thickens in the accent
     colour while it is pointed at or dragged. */
  .divider:hover::after, .divider:focus-visible::after, .sizing .divider:active::after { background: var(--accent); height: 3px; margin-top: -1px; }
  .divider.vertical:hover::after, .divider.vertical:focus-visible::after, .sizing .divider.vertical:active::after { width: 3px; height: auto; margin-top: 0; margin-left: -1px; }
  .divider:focus-visible { outline: none; }
  .drop-preview { position: absolute; z-index: 30; pointer-events: none; box-sizing: border-box; background: color-mix(in srgb, var(--accent) 16%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); border-radius: 6px; transition: left .08s, top .08s, width .08s, height .08s; }
  @media (prefers-reduced-motion: reduce) { .drop-preview, .divider::after { transition: none; } }
</style>
