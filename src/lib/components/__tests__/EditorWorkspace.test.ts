import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { fireEvent, render, screen } from "@testing-library/svelte";
import Fixture from "./fixtures/EditorWorkspaceFixture.svelte";
import { editorTree, validEditorTree } from "../../editorDocking";
import { resetPanelLayout, setSidePanel, sidePanels } from "../../editorPrefs";
const original = document.elementsFromPoint;
beforeEach(() => { editorTree.set(null); resetPanelLayout(); setSidePanel("review", { open: false }); setSidePanel("languageQa", { open: true }); });
afterEach(() => { document.elementsFromPoint = original; editorTree.set(null); resetPanelLayout(); vi.unstubAllGlobals(); });
it("docks above Scripture through the keyboard menu without remounting its filter", async () => {
  render(Fixture); const draft = screen.getByLabelText("QA filter"); await fireEvent.input(draft, { target: { value: "keep me" } });
  await fireEvent.click(screen.getByRole("button", { name: "Language QA panel tools" }));
  await fireEvent.click(await screen.findByRole("menuitem", { name: "Dock above" }));
  await fireEvent.click(await screen.findByRole("menuitem", { name: "Scripture editor" }));
  expect(validEditorTree(get(editorTree))).toBe(true); expect(screen.getByLabelText("QA filter")).toBe(draft);
  expect(draft).toHaveValue("keep me");
  const splitter = screen.getByRole("slider", { name: "Resize panel heights" });
  await fireEvent.keyDown(splitter, { key: "ArrowDown" }); expect(splitter).toHaveAttribute("aria-valuenow", "52");
});
it("Escape cancels a drag without floating, closing or changing panel state", async () => {
  vi.stubGlobal("PointerEvent", MouseEvent); document.elementsFromPoint = () => [];
  render(Fixture); const before = structuredClone(get(sidePanels));
  await fireEvent.pointerDown(screen.getByRole("button", { name: "Move Language QA" }), { button: 0, clientX: 40, clientY: 30 });
  await fireEvent.pointerMove(window, { clientX: 300, clientY: 200 });
  await fireEvent.keyDown(window, { key: "Escape" }); await fireEvent.pointerUp(window);
  expect(get(sidePanels)).toEqual(before); expect(get(editorTree)).toBeNull();
});
it("Escape on a floating panel cancels its active move before the panel's ordinary close shortcut", async () => {
  vi.stubGlobal("PointerEvent", MouseEvent); document.elementsFromPoint = () => [];
  setSidePanel("languageQa", { float: { x: 20, y: 40, width: 440, height: 400 } });
  render(Fixture); const before = structuredClone(get(sidePanels));
  const grip = screen.getByRole("button", { name: "Move the Language QA panel" });
  await fireEvent.pointerDown(grip, { button: 0, clientX: 40, clientY: 50 });
  await fireEvent.pointerMove(window, { clientX: 300, clientY: 200 });
  await fireEvent.keyDown(grip, { key: "Escape" }); await fireEvent.pointerUp(window);
  expect(get(sidePanels)).toEqual(before);
});
