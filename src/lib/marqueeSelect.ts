// Rubber-band ("marquee") selection for the alignment word bank (#410):
// press on empty space in the bank, drag a rectangle, and every unaligned
// word the rectangle touches is picked -- the way files are selected on a
// desktop. The picked words then move together with one drag or one column
// click, through the same `picked` selection Ctrl-click and Shift-click fill
// (#285); this module adds a third way to fill it, nothing else.
//
// Pointer events, not native drag, for the reason alignmentDrag.ts gives:
// the Tauri window's file drag-drop swallows the native drag protocol.
//
// The module owns the state machine only. Selectable items carry
// `data-marquee-item="<id>"`; a press that starts on one of them, or on any
// button, is not a marquee (the item's own pointerdown starts a drag).
import { writable, type Readable } from "svelte/store";

export interface MarqueeRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface MarqueeState {
  /** True from a qualifying pointerdown until pointerup. */
  active: boolean;
  /** True once the pointer has travelled past the threshold: a real
   *  selection, not a click. Only then is a rectangle drawn or a selection
   *  reported. */
  moved: boolean;
  /** The rectangle in viewport coordinates, or null while idle. */
  rect: MarqueeRect | null;
  /** Ids of the items the rectangle currently touches, in document order. */
  hits: string[];
}

export interface MarqueeOptions {
  /** Pixels of travel before a press counts as a marquee. Default 6. */
  threshold?: number;
  itemAttr?: string;
  /** Viewport rectangle of an element; injectable because jsdom lays nothing
   *  out and returns zeros from getBoundingClientRect. */
  rectOf?: (el: Element) => Pick<DOMRect, "left" | "top" | "right" | "bottom">;
  /** Fired once when the threshold is crossed. `additive` is true when the
   *  press held Ctrl or ⌘: the selection adds to what was picked. */
  onStart?: (additive: boolean) => void;
  /** Fired on every move after the threshold with the items the rectangle
   *  touches, so the selection follows the pointer. */
  onChange: (hits: string[], additive: boolean) => void;
  /** Fired on pointerup after a real marquee. */
  onEnd?: (hits: string[], additive: boolean) => void;
}

export interface Marquee {
  state: Readable<MarqueeState>;
  /** pointerdown on the bank. Ignores non-primary buttons and presses that
   *  start on an item or a button. */
  start(event: PointerEvent, container: Element): void;
  move(event: PointerEvent): void;
  up(): void;
  /** Register window-level pointermove/pointerup listeners; returns the
   *  detach function for onMount's teardown. */
  attach(target: Pick<Window, "addEventListener" | "removeEventListener">): () => void;
  /** After a real marquee the browser still fires `click` on the bank, whose
   *  handler would put the picked words down again. The handler asks this
   *  once; it answers true exactly once after a marquee. */
  consumeSuppressedClick(): boolean;
}

const IDLE: MarqueeState = { active: false, moved: false, rect: null, hits: [] };

function intersects(a: MarqueeRect, b: Pick<DOMRect, "left" | "top" | "right" | "bottom">): boolean {
  return a.left < b.right && a.left + a.width > b.left && a.top < b.bottom && a.top + a.height > b.top;
}

export function createMarquee(options: MarqueeOptions): Marquee {
  const threshold = options.threshold ?? 6;
  const itemAttr = options.itemAttr ?? "data-marquee-item";
  const rectOf = options.rectOf ?? ((el: Element) => el.getBoundingClientRect());

  const state = writable<MarqueeState>({ ...IDLE });
  let current: MarqueeState = { ...IDLE };
  let origin: { x: number; y: number } | null = null;
  let container: Element | null = null;
  let additive = false;
  let suppressClick = false;

  function set(next: MarqueeState) {
    current = next;
    state.set(next);
  }

  function start(event: PointerEvent, host: Element) {
    if (event.button !== 0) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest?.(`[${itemAttr}], button, select, input, a`)) return;
    origin = { x: event.clientX, y: event.clientY };
    container = host;
    additive = Boolean(event.ctrlKey || event.metaKey);
    set({ ...IDLE, active: true });
  }

  function move(event: PointerEvent) {
    if (!current.active || !origin || !container) return;
    let moved = current.moved;
    if (!moved && Math.hypot(event.clientX - origin.x, event.clientY - origin.y) > threshold) {
      moved = true;
      options.onStart?.(additive);
    }
    if (!moved) return;
    const rect: MarqueeRect = {
      left: Math.min(origin.x, event.clientX),
      top: Math.min(origin.y, event.clientY),
      width: Math.abs(event.clientX - origin.x),
      height: Math.abs(event.clientY - origin.y),
    };
    const hits: string[] = [];
    for (const el of container.querySelectorAll(`[${itemAttr}]`)) {
      if (intersects(rect, rectOf(el))) hits.push(el.getAttribute(itemAttr) ?? "");
    }
    set({ active: true, moved: true, rect, hits });
    options.onChange(hits, additive);
  }

  function up() {
    if (!current.active) return;
    const { moved, hits } = current;
    origin = null;
    container = null;
    set({ ...IDLE });
    if (!moved) return; // a plain click on the bank: its click handler runs as before
    suppressClick = true;
    // The click that follows this pointerup is the one to swallow; nothing
    // later should be.
    setTimeout(() => { suppressClick = false; }, 0);
    options.onEnd?.(hits, additive);
  }

  function attach(target: Pick<Window, "addEventListener" | "removeEventListener">) {
    const onMove = (event: Event) => move(event as PointerEvent);
    const onUp = () => up();
    target.addEventListener("pointermove", onMove);
    target.addEventListener("pointerup", onUp);
    return () => {
      target.removeEventListener("pointermove", onMove);
      target.removeEventListener("pointerup", onUp);
    };
  }

  function consumeSuppressedClick(): boolean {
    if (!suppressClick) return false;
    suppressClick = false;
    return true;
  }

  return { state, start, move, up, attach, consumeSuppressedClick };
}
