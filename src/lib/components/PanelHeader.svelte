<script lang="ts">
  // #379 (Benz's item 7): the one header bar every editor side panel shows,
  // with a line under it. Title on the left, the panel's own actions (follow
  // box, Change, Pause, the (i)) in the slot, then the layout controls (#389:
  // ◂ ▸ move the column, ⧉ undocks it into a box inside the window, ⇲ docks
  // it back), and a ✕ Close on the right that does what the View menu's entry does.
  // One padding, one title size, one background.
  //
  // Each panel mounts this as its first child rather than SidePanel drawing
  // it: a Svelte 4 slot can be filled only by the component that writes the
  // markup, and the actions are bound to each panel's own state (its follow
  // box, its Pause), which the column cannot reach. The bar is the same
  // component in every panel, so every panel gets the same header.
  import { getContext } from "svelte";
  import { tooltip } from "../tooltip";
  import UiIcon from "./UiIcon.svelte";
  import IconButton from "./IconButton.svelte";
  import OverflowMenu from "./OverflowMenu.svelte";
  import { editorTree, type EditorDockContext } from "../editorDocking";
  import { dockSidePanel, movePanel, setSidePanel, sidePanelOrder, sidePanels, undockSidePanel } from "../editorPrefs";
  import type { SidePanelId } from "../editorPrefs";

  export let id: SidePanelId;
  /** The bar's text, e.g. "Source · Hebrew / Aramaic", "Review PHP 1:6". */
  export let title: string;
  /** What the Close button closes, for its accessible name: "Close {label}". */
  export let label: string = title;
  /** The title's tooltip, where the bar's text is cut or stands for a path. */
  export let hint: string = "";
  /** What Close does when it is not simply closing the column (the floating
   *  Language QA box). Default: close the column, as the View menu does. */
  export let onClose: (() => void) | null = null;
  /** The ◂ ▸ / undock controls: only where the bar heads an editor column or
   *  an undocked box, not the Language QA box of the other screens. */
  export let layout = true;

  const docking = getContext<EditorDockContext | undefined>("editor-docking");
  const native = getContext<{ dock: () => void; close: () => void } | undefined>("panel-window");
  $: actions = native ? [{ id: "return", label: "Dock in Bridge" }] : [
    ...(!$editorTree ? [
      { id: "left", label: "Move panel left", disabled: at <= 0 },
      { id: "right", label: "Move panel right", disabled: at >= $sidePanelOrder.length - 1 },
    ] : []),
    { id: "float", label: floating ? "Dock in column" : "Float inside Bridge" },
    { id: "detach", label: "Move to separate window", disabled: !("__TAURI_INTERNALS__" in window) },
    ...(docking ? (["left", "right", "top", "bottom"] as const).map(edge => ({ id: `edge-${edge}`, label: `Dock ${edge === "top" ? "above" : edge === "bottom" ? "below" : edge + " of"}`,
      submenu: ["editor", ...$sidePanelOrder.filter(other => other !== id)].map(target => ({ id: `dock:${target}:${edge}`, label: target === "editor" ? "Scripture editor" : target })) })) : []),
  ];
  function arrange(action: string) {
    if (action === "return") native?.dock();
    else if (action === "left") movePanel(id, -1);
    else if (action === "right") movePanel(id, 1);
    else if (action === "detach") setSidePanel(id, { detached: true, open: true });
    else if (action === "float") { if (floating) dockSidePanel(id); else undock(); }
    else if (action.startsWith("dock:")) { const [, target, edge] = action.split(":"); docking?.dock(id, target, edge as "left" | "right" | "top" | "bottom"); }
  }
  $: at = $sidePanelOrder.indexOf(id);
  $: floating = Boolean($sidePanels[id].float);

  function close(): void {
    if (native) native.close();
    else if (onClose) onClose();
    else setSidePanel(id, { open: false });
  }

  /** Undock where the column stands, so the box appears over its own place. */
  function undock(): void {
    const column = typeof document === "undefined" ? null : document.getElementById(`side-panel-${id}`);
    const rect = column?.getBoundingClientRect();
    undockSidePanel(id, rect && rect.width > 0 ? { x: rect.left, y: rect.top, width: rect.width, height: rect.height } : undefined);
  }
</script>

<div class="panel-bar" data-panel-bar={id}>
    {#if docking && !native}<button type="button" class="panel-grip" aria-label={`Move ${label}`} use:tooltip={"Drag to move or dock this panel; use the tools menu for keyboard placement"} on:pointerdown={(event) => docking.beginMove(id, event)}><UiIcon name="grip" /></button>{/if}
  <h2 class="panel-title" title={hint || title}>{title}</h2>
  {#if $$slots.default}
    <div class="panel-actions"><slot /></div>
  {/if}
  {#if layout || native}
    <OverflowMenu label={`${label} panel tools`} {actions} on:action={(event) => arrange(event.detail.id)} />
  {/if}
  <button type="button" class="panel-close" on:click={close}
    aria-label={`Close ${label}`} title="Close (the View menu opens it again)">✕</button>
</div>

<style>
  /* Shared compact editor/panel height; retain comfortable icon hit targets. */
  .panel-bar { flex-shrink: 0; display: flex; align-items: center; gap: 4px; min-width: 0; padding: 0 8px;
    box-sizing: border-box; height: 36px; min-height: 36px;
    border-bottom: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); font-size: var(--fs-2xs); }
  .panel-actions :global(button:not(.info-btn)) { box-sizing: border-box; height: 24px; padding-top: 0; padding-bottom: 0; }
  .panel-title { flex: 1; min-width: 0; margin: 0; font-size: var(--fs-xs); font-weight: 500; text-align: center; color: var(--text);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .panel-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; min-width: 0; }
  /* #389: the layout controls, the size of Close, no gap between them so the
     bar stays one line at 260px. Plain glyphs (gotcha 9) with the action as
     the accessible name and tooltip. */
  .panel-grip { display: flex; align-items: center; padding: 0; width: 22px; height: 28px; border: 0; background: transparent; color: var(--text-3); cursor: move; touch-action: none; }
  .panel-grip:focus-visible { outline: 2px solid var(--text-2); }
</style>
