import { writable, type Writable } from "svelte/store";

/**
 * Per-browser editor preferences (indic-qa keeps the same ones in the
 * browser): whether the reference panel is open, the raw USFM view, and the
 * verse text size. Saved to localStorage, best effort: a private window or a
 * blocked store just starts from the defaults.
 */
function persisted<T>(key: string, fallback: T, valid: (value: unknown) => value is T): Writable<T> {
  let initial = fallback;
  try {
    const raw = localStorage.getItem(key);
    if (raw !== null) {
      const value: unknown = JSON.parse(raw);
      if (valid(value)) initial = value;
    }
  } catch {
    // unreadable: keep the default
  }
  const store = writable<T>(initial);
  store.subscribe((value) => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // not saved: the preference lasts for this session only
    }
  });
  return store;
}

const isBoolean = (value: unknown): value is boolean => typeof value === "boolean";

/**
 * The editor's side panels: each a column right of the text with its own
 * width, opened from the rail at the far right and closed from the rail, its
 * Close button, or by dragging its left edge to the right past its minimum
 * (Benz, 2026-10-09). Several may be open side by side.
 */
export type SidePanelId = "reference" | "languageQa" | "review";
export interface SidePanelState { open: boolean; width: number }
export type SidePanels = Record<SidePanelId, SidePanelState>;

/** Left to right, as they stand between the text and the rail. */
export const SIDE_PANEL_ORDER: readonly SidePanelId[] = ["reference", "languageQa", "review"];
export const SIDE_PANEL_LIMITS: Record<SidePanelId, { min: number; max: number; initial: number }> = {
  reference: { min: 200, max: 640, initial: 300 },
  languageQa: { min: 320, max: 760, initial: 440 },
  review: { min: 300, max: 720, initial: 400 },
};

export function clampPanelWidth(id: SidePanelId, px: number): number {
  const { min, max } = SIDE_PANEL_LIMITS[id];
  return Math.round(Math.min(max, Math.max(min, px)));
}

function legacy<T>(key: string, valid: (value: unknown) => value is T): T | undefined {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return undefined;
    const value: unknown = JSON.parse(raw);
    return valid(value) ? value : undefined;
  } catch {
    return undefined;
  }
}

/** The first default carries over the earlier per-panel preferences (the
 * folded review panel, the reference toggle and its width). */
function defaultSidePanels(): SidePanels {
  const width = legacy("bridge.editor.referencePanelWidth.v1",
    (v): v is number => typeof v === "number" && Number.isFinite(v));
  return {
    reference: { open: legacy("bridge.editor.referencePanel.v1", isBoolean) ?? false,
                 width: width === undefined ? SIDE_PANEL_LIMITS.reference.initial : clampPanelWidth("reference", width) },
    languageQa: { open: false, width: SIDE_PANEL_LIMITS.languageQa.initial },
    review: { open: !(legacy("bridge.editor.reviewPanelCollapsed.v1", isBoolean) ?? false),
              width: SIDE_PANEL_LIMITS.review.initial },
  };
}

const isSidePanels = (value: unknown): value is SidePanels =>
  typeof value === "object" && value !== null && SIDE_PANEL_ORDER.every((id) => {
    const entry = (value as Record<string, unknown>)[id] as Partial<SidePanelState> | undefined;
    return !!entry && typeof entry.open === "boolean" && typeof entry.width === "number" && Number.isFinite(entry.width);
  });

export const sidePanels = persisted<SidePanels>("bridge.editor.sidePanels.v1", defaultSidePanels(), isSidePanels);

export function setSidePanel(id: SidePanelId, patch: Partial<SidePanelState>): void {
  sidePanels.update((all) => ({
    ...all,
    [id]: { ...all[id], ...patch, ...(patch.width === undefined ? {} : { width: clampPanelWidth(id, patch.width) }) },
  }));
}

export function toggleSidePanel(id: SidePanelId): void {
  sidePanels.update((all) => ({ ...all, [id]: { ...all[id], open: !all[id].open } }));
}

/** The dashboard's Collection QA panel folded to its header row. A run in
 * progress always shows its table, whatever this says. */
export const collectionQaCollapsed = persisted("bridge.dashboard.collectionQaCollapsed.v1", false, isBoolean);

/** The verse text exactly as stored, USFM markers and all, instead of the
 * reader's clean text. Marks stay on the same characters. */
export const rawView = persisted("bridge.editor.rawView.v1", false, isBoolean);

/** The verse text size, a multiple of the normal size (indic-qa's A− / A+). */
export const TEXT_SCALES = [0.85, 1, 1.15, 1.3, 1.5, 1.7] as const;
const isScale = (value: unknown): value is number => typeof value === "number" && (TEXT_SCALES as readonly number[]).includes(value);
export const textScale = persisted<number>("bridge.editor.textScale.v1", 1, isScale);

/** One step smaller (-1) or larger (+1), stopping at either end. */
export function bumpTextScale(step: -1 | 1): void {
  textScale.update((scale) => {
    const at = Math.max(0, (TEXT_SCALES as readonly number[]).indexOf(scale));
    return TEXT_SCALES[Math.min(TEXT_SCALES.length - 1, Math.max(0, at + step))];
  });
}

const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string");

/** Which sections of the Checker settings dialog are open, by section id. As
 * in the indic-qa web app, every section starts closed and stays as left. */
export const checkerSettingsOpen = persisted<string[]>("bridge.checkerSettings.open.v1", [], isStringArray);
