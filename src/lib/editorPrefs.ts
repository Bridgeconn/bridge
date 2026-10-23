import { get, writable, type Writable } from "svelte/store";

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
export type SidePanelId = "source" | "reference" | "languageQa" | "paratext" | "review";
export interface SidePanelState { open: boolean; width: number }
export type SidePanels = Record<SidePanelId, SidePanelState>;

/** Left to right, as they stand between the text and the rail. The source text
 * (#67) sits next to the verses it is the original of. */
/** Paratext notes (#357) sit beside Review, where findings are decided. */
export const SIDE_PANEL_ORDER: readonly SidePanelId[] = ["source", "reference", "languageQa", "paratext", "review"];
/** Panels a saved layout from before they existed lacks; they start closed
 * rather than throwing the reviewer's other widths away. */
const ADDED_LATER: readonly SidePanelId[] = ["source", "paratext"];
export const SIDE_PANEL_LIMITS: Record<SidePanelId, { min: number; max: number; initial: number }> = {
  source: { min: 220, max: 640, initial: 320 },
  reference: { min: 200, max: 640, initial: 300 },
  languageQa: { min: 320, max: 760, initial: 440 },
  paratext: { min: 260, max: 640, initial: 340 },
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
    source: { open: false, width: SIDE_PANEL_LIMITS.source.initial },
    reference: { open: legacy("bridge.editor.referencePanel.v1", isBoolean) ?? false,
                 width: width === undefined ? SIDE_PANEL_LIMITS.reference.initial : clampPanelWidth("reference", width) },
    languageQa: { open: false, width: SIDE_PANEL_LIMITS.languageQa.initial },
    paratext: { open: false, width: SIDE_PANEL_LIMITS.paratext.initial },
    review: { open: !(legacy("bridge.editor.reviewPanelCollapsed.v1", isBoolean) ?? false),
              width: SIDE_PANEL_LIMITS.review.initial },
  };
}

const isPanelState = (entry: unknown): entry is SidePanelState => {
  const state = entry as Partial<SidePanelState> | undefined;
  return !!state && typeof state.open === "boolean" && typeof state.width === "number" && Number.isFinite(state.width);
};

/** Every panel valid, except that one added later may be missing (it is filled
 * in below): a layout saved before #67 keeps its widths and open panels. */
const isSidePanels = (value: unknown): value is SidePanels =>
  typeof value === "object" && value !== null && SIDE_PANEL_ORDER.every((id) => {
    const entry = (value as Record<string, unknown>)[id];
    return isPanelState(entry) || (entry === undefined && ADDED_LATER.includes(id));
  });

export const sidePanels = persisted<SidePanels>("bridge.editor.sidePanels.v1", defaultSidePanels(), isSidePanels);
sidePanels.update((all) => {
  const missing = ADDED_LATER.filter((id) => !isPanelState(all[id]));
  if (!missing.length) return all;
  const filled = { ...all };
  for (const id of missing) filled[id] = { open: false, width: SIDE_PANEL_LIMITS[id].initial };
  return filled;
});

/**
 * The panels in the order they were last asked to open, most recent last
 * (#324). Not saved: it only decides which panel folds first when the window
 * is too narrow for all of them (panelFit.ts), so the one just opened is the
 * one shown. Asking an already open panel to open moves it to the end too,
 * which is how a folded panel is brought back.
 */
export const sidePanelRecency = writable<SidePanelId[]>([]);

function markOpened(id: SidePanelId): void {
  sidePanelRecency.update((order) => [...order.filter((other) => other !== id), id]);
}

export function setSidePanel(id: SidePanelId, patch: Partial<SidePanelState>): void {
  if (patch.open) markOpened(id);
  sidePanels.update((all) => ({
    ...all,
    [id]: { ...all[id], ...patch, ...(patch.width === undefined ? {} : { width: clampPanelWidth(id, patch.width) }) },
  }));
}

/** Open a panel and make sure it is the one shown, even if it was already
 * open but folded for width; an open panel's saved state is left as it is. */
export function revealSidePanel(id: SidePanelId): void {
  if (get(sidePanels)[id].open) markOpened(id);
  else setSidePanel(id, { open: true });
}

export function toggleSidePanel(id: SidePanelId): void {
  if (!get(sidePanels)[id].open) markOpened(id);
  sidePanels.update((all) => ({ ...all, [id]: { ...all[id], open: !all[id].open } }));
}

/** The dashboard's Collection QA panel folded to its header row. Folded by
 * default (#380); a saved choice wins, and a run in progress always shows
 * its table, whatever this says. */
export const collectionQaCollapsed = persisted("bridge.dashboard.collectionQaCollapsed.v1", true, isBoolean);

/** The dashboard's project details block (eyebrow, book heading, Paratext
 * strip) folded to one row: the name and the subtitle (#374). Open by
 * default; remembered per device. */
export const projectDetailsCollapsed = persisted("bridge.dashboard.projectDetailsCollapsed.v1", false, isBoolean);

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

/** The elective checks (#251): which boxes are ticked, by box id
 * (checkSelection.ts). The editor's runs share one selection; Collection QA
 * keeps its own, with Greek Room in it, as it is the unattended whole-Bible
 * pass (#252). A saved selection with no known box falls back to the default. */
export const editorChecks = persisted<string[]>("bridge.editor.checks.v1",
  ["tN", "tW", "alignment", "text", "languageQa"], isStringArray);
export const collectionChecks = persisted<string[]>("bridge.dashboard.collectionChecks.v1",
  ["tN", "tW", "alignment", "text", "languageQa", "greekroom"], isStringArray);
