<script lang="ts">
  import { onMount, setContext } from "svelte";
  import { derived } from "svelte/store";
  import { arrange, dockPane, without, resizeDivider, type Divider, type LayoutNode, type DockEdge } from "../alignmentLayout";
  import { editorTree, defaultEditorTree, type EditorDockContext } from "../editorDocking";
  import { SIDE_PANEL_ORDER, sidePanels, sidePanelOrder, setSidePanel, undockSidePanel, type SidePanelId } from "../editorPrefs";
  export let onDetach: (id: SidePanelId) => void = () => {};
  let node: HTMLDivElement;
  let width = 1000, height = 600;
  const frames = derived([editorTree, sidePanels], ([tree, panels]) => arrange(tree ? without(tree,
    SIDE_PANEL_ORDER.filter(id => !panels[id].open || !!panels[id].float || panels[id].detached)) : null).frames);
  $: visibleTree = $editorTree ? without($editorTree, SIDE_PANEL_ORDER.filter(id => !$sidePanels[id].open || !!$sidePanels[id].float || $sidePanels[id].detached)) : null;
  function minimum(tree: LayoutNode | null): { width: number; height: number } {
    if (!tree) return { width: 0, height: 0 };
    if (typeof tree === "string") return { width: tree === "editor" ? 340 : 260, height: 200 };
    const a = minimum(tree.first), b = minimum(tree.second);
    return tree.axis === "horizontal" ? { width: Math.max(a.width / tree.ratio, b.width / (1 - tree.ratio)), height: Math.max(a.height, b.height) }
      : { width: Math.max(a.width, b.width), height: Math.max(a.height / tree.ratio, b.height / (1 - tree.ratio)) };
  }
  $: minSize = minimum(visibleTree);
  $: dividers = arrange(visibleTree).dividers;
  const style = (frame: any) => frame ? `position:absolute;left:${frame.x}%;top:${frame.y}%;width:${frame.width}%;height:${frame.height}%;min-width:0` : "";
  $: editorFrame = style($frames.editor);
  let moving: { id: SidePanelId; x: number; y: number; startX: number; startY: number; moved: boolean } | null = null;
  let candidate: { target: string; edge: DockEdge; left: number; top: number; width: number; height: number } | null = null;
  let sizing: Divider | null = null;
  let beforeResize: LayoutNode | null = null;
  function dock(id: SidePanelId, target: string, edge: DockEdge) {
    editorTree.set(dockPane($editorTree ?? defaultEditorTree(), id, target, edge));
    setSidePanel(id, { open: true, float: null, detached: false });
    if (SIDE_PANEL_ORDER.includes(target as SidePanelId)) setSidePanel(target as SidePanelId, { open: true, float: null, detached: false });
  }
  function beginMove(id: SidePanelId, event: PointerEvent) {
    if (event.button !== 0) return;
    event.preventDefault(); (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    moving = { id, x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY, moved: false };
  }
  function move(event: PointerEvent) {
    if (sizing && $editorTree) {
      const bounds = node.getBoundingClientRect(), horizontal = sizing.axis === "horizontal";
      const position = horizontal ? (event.clientX - bounds.left) / bounds.width * 100 : (event.clientY - bounds.top) / bounds.height * 100;
      editorTree.set(resizeDivider($editorTree, sizing.id, (position - (horizontal ? sizing.bounds.x : sizing.bounds.y)) / (horizontal ? sizing.bounds.width : sizing.bounds.height)));
    }
    if (!moving) return;
    moving = { ...moving, x: event.clientX, y: event.clientY, moved: moving.moved || Math.hypot(event.clientX - moving.startX, event.clientY - moving.startY) > 5 };
    candidate = null;
    if (!moving.moved || event.altKey) return;
    const target = document.elementsFromPoint(event.clientX, event.clientY).map(el => el.closest<HTMLElement>("[data-editor-pane]"))
      .find(el => el && el.dataset.editorPane !== moving!.id && node.contains(el));
    if (!target) return;
    const r = target.getBoundingClientRect(), b = node.getBoundingClientRect();
    const x = (event.clientX - r.left) / r.width, y = (event.clientY - r.top) / r.height;
    const edges: [DockEdge, number][] = [["left", x], ["right", 1 - x], ["top", y], ["bottom", 1 - y]];
    const [edge, distance] = edges.sort((a, b) => a[1] - b[1])[0];
    if (distance > .25) return;
    candidate = { target: target.dataset.editorPane!, edge, left: r.left - b.left + (edge === "right" ? r.width / 2 : 0),
      top: r.top - b.top + (edge === "bottom" ? r.height / 2 : 0), width: ["left", "right"].includes(edge) ? r.width / 2 : r.width,
      height: ["top", "bottom"].includes(edge) ? r.height / 2 : r.height };
  }
  function finish() {
    if (moving?.moved) {
      if (candidate) dock(moving.id, candidate.target, candidate.edge);
      else if (moving.x <= 0 || moving.x >= window.innerWidth || moving.y <= 0 || moving.y >= window.innerHeight) onDetach(moving.id);
      else undockSidePanel(moving.id, { x: moving.x - 40, y: moving.y - 12, width: 440, height: 480 });
    }
    moving = null; candidate = null; sizing = null; beforeResize = null;
  }
  function cancel() { if (sizing) editorTree.set(beforeResize); moving = null; candidate = null; sizing = null; beforeResize = null; }
  function resizeKey(d: Divider, event: KeyboardEvent) {
    const negative = d.axis === "horizontal" ? "ArrowLeft" : "ArrowUp", positive = d.axis === "horizontal" ? "ArrowRight" : "ArrowDown";
    if (!$editorTree || ![negative, positive, "Home", "End"].includes(event.key)) return;
    event.preventDefault(); editorTree.set(resizeDivider($editorTree, d.id, event.key === "Home" ? .15 : event.key === "End" ? .85 : d.ratio + (event.key === negative ? -.02 : .02) * (event.shiftKey ? 3 : 1)));
  }
  setContext<EditorDockContext>("editor-docking", { frames, beginMove, dock, cancelMove: () => {
    if (!moving && !sizing) return false;
    cancel(); return true;
  } });
  onMount(() => {
    const measure = () => { width = node.parentElement?.clientWidth || width; height = node.parentElement?.clientHeight || height; };
    measure(); if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure); observer.observe(node.parentElement!); return () => observer.disconnect();
  });
</script>

<svelte:window on:pointermove={move} on:pointerup={finish} on:pointercancel={cancel} on:keydown={(event) => { if (event.key === "Escape" && (moving || sizing)) { event.preventDefault(); event.stopImmediatePropagation(); cancel(); } }} />
<div class="layout-scroll"><div class="editor-layout" class:arranged={!!$editorTree} class:moving={!!moving}
  style:min-width={$editorTree ? `${Math.max(width, minSize.width)}px` : null}
  style:min-height={$editorTree ? `${Math.max(height, minSize.height)}px` : null} bind:this={node}>
  <slot {editorFrame} />
  {#each dividers as d (d.id)}
    <div class="divider" class:vertical={d.axis === "horizontal"} role="slider" tabindex="0"
      aria-label={d.axis === "horizontal" ? "Resize panel widths" : "Resize panel heights"}
      aria-orientation={d.axis === "horizontal" ? "vertical" : "horizontal"} aria-valuenow={Math.round(d.ratio * 100)} aria-valuemin="15" aria-valuemax="85"
      style:left={`${d.axis === "horizontal" ? d.at : d.bounds.x}%`} style:top={`${d.axis === "vertical" ? d.at : d.bounds.y}%`}
      style:width={d.axis === "horizontal" ? "8px" : `${d.bounds.width}%`} style:height={d.axis === "vertical" ? "8px" : `${d.bounds.height}%`}
      on:pointerdown={(event) => { event.preventDefault(); event.currentTarget.setPointerCapture?.(event.pointerId); sizing = d; beforeResize = $editorTree; }}
      on:keydown={(event) => resizeKey(d, event)} />
  {/each}
  {#if candidate}<div class="dock-preview" style:left={`${candidate.left}px`} style:top={`${candidate.top}px`} style:width={`${candidate.width}px`} style:height={`${candidate.height}px`}>Dock {candidate.edge}</div>{/if}
  {#if moving?.moved}<div class="drag-label" style:left={`${moving.x + 12}px`} style:top={`${moving.y + 12}px`}>{candidate ? "Dock here" : "Float here · outside Bridge opens a separate window"}</div>{/if}
</div></div>

<style>
  .layout-scroll { flex: 1; min-width: 0; min-height: 0; display: flex; overflow: auto; }
  .editor-layout { position: relative; flex: 1; min-width: 0; min-height: 0; display: flex; }
  .editor-layout.arranged { display: block; }
  .moving { user-select: none; }
  .divider { position: absolute; z-index: 6; background: transparent; cursor: row-resize; transform: translateY(-50%); touch-action: none; }
  .divider.vertical { cursor: col-resize; transform: translateX(-50%); }
  .divider::after { content: ""; position: absolute; left: 0; right: 0; top: 50%; height: 1px; background: var(--border); pointer-events: none; }
  .divider.vertical::after { left: 50%; right: auto; top: 0; bottom: 0; width: 1px; height: auto; }
  .divider:focus-visible { outline: 1px solid var(--text-3); outline-offset: -2px; }
  .dock-preview { position: absolute; z-index: 30; display: grid; place-items: center; pointer-events: none; background: #80808066; border: 2px solid var(--text-3); color: var(--text); box-sizing: border-box; }
  .drag-label { position: fixed; z-index: 1000; background: var(--text-2); color: var(--surface); padding: 6px; pointer-events: none; }
</style>
