// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// #288: named stacking layers. jsdom does not paint, so what is pinned here is
// the order of the layers and which layer each surface declares; the
// "Settings above the floating Language QA panel" fact follows from the two.
// Read from disk: vitest serves a CSS import as an empty module, and under
// jsdom import.meta.url is not a file URL. Vitest runs from the repo root.
const indexCss = readFileSync(resolve(process.cwd(), "src/index.css"), "utf-8");
const component = (name: string): string =>
  readFileSync(resolve(process.cwd(), "src/lib/components", `${name}.svelte`), "utf-8");

function token(name: string): number {
  const match = indexCss.match(new RegExp(`--${name}:\\s*(\\d+);`));
  if (!match) throw new Error(`index.css defines no --${name}`);
  return Number(match[1]);
}

/** The declaration block of the first rule whose selector list contains `selector`. */
function rule(source: string, selector: string): string {
  const match = source.match(new RegExp(`${selector.replace(/[.\-]/g, "\\$&")}[^{}]*\\{([^}]*)\\}`));
  return match?.[1] ?? "";
}

describe("stacking layers (#288)", () => {
  it("defines the layers in order: dropdown, panel, dialog, dialog-over-dialog, popover, toast, startup", () => {
    const order = ["z-dropdown", "z-panel", "z-dialog", "z-dialog-over-dialog", "z-popover", "z-toast", "z-startup"];
    const values = order.map(token);
    for (let at = 1; at < values.length; at += 1) expect(values[at], order[at]).toBeGreaterThan(values[at - 1]);
  });

  it("puts every app dialog on --z-dialog, above the floating Language QA panel", () => {
    expect(rule(component("LanguageQaPanel"), ".language-qa")).toContain("z-index: var(--z-panel)");
    for (const [name, selector] of [
      ["SettingsModal", ".modal-overlay"], ["ExportModal", ".modal-overlay"], ["DiagnosticsPanel", ".modal-overlay"],
      ["AlignmentModal", ".overlay"], ["CrossVerseAlignmentModal", ".overlay"], ["CorrectionReviewPanel", ".confirm-backdrop"],
    ]) {
      expect(rule(component(name), selector), `${name} ${selector}`).toContain("z-index: var(--z-dialog)");
    }
  });

  it("puts a dialog or popup opened from a dialog on --z-dialog-over-dialog", () => {
    for (const [name, selector] of [
      ["CheckerSettingsDialog", ".overlay"], ["LanguageQaHistoryPopup", ".overlay"], ["LexiconPopup", ".overlay"],
      ["FlagDialog", ".overlay"], ["ScopeConfirmDialog", ".overlay"], ["OccurrencesPopup", ".overlay"],
      ["VerseNotesPopup", ".overlay"], ["CrossVerseAlignmentModal", ".menu-overlay"],
    ]) {
      expect(rule(component(name), selector), `${name} ${selector}`).toContain("z-index: var(--z-dialog-over-dialog)");
    }
  });

  it("puts pointer-anchored popovers and drag ghosts on --z-popover, notices on --z-toast, anchored menus on --z-dropdown", () => {
    for (const [name, selector] of [
      ["FindingContextMenu", ".finding-menu"], ["FlagPopover", ".popover"], ["VerseHistoryPopover", ".popover"],
      ["AlignmentModal", ".drag-ghost"], ["CrossVerseAlignmentModal", ".drag-ghost"],
    ]) {
      expect(rule(component(name), selector), `${name} ${selector}`).toContain("z-index: var(--z-popover)");
    }
    expect(rule(component("ScopeNotice"), ".scope-notice")).toContain("z-index: var(--z-toast)");
    expect(rule(component("VerseList"), ".context-notice")).toContain("z-index: var(--z-toast)");
    for (const [name, selector] of [
      ["CheckMenu", ".panel"], ["ProjectReportScreen", ".export .menu"], ["ImportScreen", ".language-menu"],
    ]) {
      expect(rule(component(name), selector), `${name} ${selector}`).toContain("z-index: var(--z-dropdown)");
    }
  });

  it("leaves no overlay, panel, popover or toast on a bare number in the converted components", () => {
    // A literal z-index may only order things inside one component (a sticky
    // header, a close button, a resize handle): small, single digits.
    for (const name of [
      "SettingsModal", "ExportModal", "DiagnosticsPanel", "AlignmentModal", "CrossVerseAlignmentModal",
      "CorrectionReviewPanel", "CheckerSettingsDialog", "LanguageQaHistoryPopup", "LexiconPopup", "FlagDialog",
      "ScopeConfirmDialog", "OccurrencesPopup", "VerseNotesPopup", "FindingContextMenu", "FlagPopover",
      "VerseHistoryPopover", "ScopeNotice", "VerseList", "CheckMenu", "ProjectReportScreen", "ImportScreen",
      "LanguageQaPanel", "SidePanel",
    ]) {
      const literals = [...component(name).matchAll(/z-index:\s*(\d+)/g)].map((m) => Number(m[1]));
      for (const value of literals) expect(value, `${name} z-index: ${value}`).toBeLessThan(10);
    }
  });

  it("sizes Settings at 1.5x the old dialog, capped at 80% of the window", () => {
    const settings = rule(component("SettingsModal"), ".settings-modal");
    expect(settings).toContain("width: min(960px, 80vw)");
    expect(settings).toContain("height: min(720px, 80vh)");
    // The pane scrolls inside the dialog; the nav keeps its width.
    expect(rule(component("SettingsModal"), ".settings-body")).toContain("overflow-y: auto");
    expect(rule(component("SettingsModal"), ".settings-nav")).toContain("flex-shrink: 0");
  });
});
