import { derived, type Readable } from "svelte/store";

import { setSidePanel, sidePanels, toggleSidePanel } from "./editorPrefs";

/**
 * Whether Language QA is on in the View menu (#488), and the one name both the
 * View menu and the Review panel's Language QA tab (#487) build against.
 *
 * Today it is the docked Language QA column's saved open state, so it
 * survives a restart exactly as before. When #487 folds that panel into the
 * Review panel, the tab reads `languageQaShown` and nothing else here changes
 * for it; what backs the flag is this file's business.
 */
export const languageQaShown: Readable<boolean> = derived(sidePanels, (panels) => panels.languageQa.open);

export function setLanguageQaShown(on: boolean): void {
  setSidePanel("languageQa", { open: on });
}

export function toggleLanguageQaShown(): void {
  toggleSidePanel("languageQa");
}
