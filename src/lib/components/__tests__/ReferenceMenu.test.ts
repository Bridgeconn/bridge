import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import { tick } from "svelte";

const { languageQaReference, panelWindow } = vi.hoisted(() => ({ languageQaReference: vi.fn(), panelWindow: vi.fn() }));
vi.mock("../../api/bridgeClient", () => ({ bridge: { languageQaReference } }));
vi.mock("../../panelWindow", () => ({ panelDesktop: () => true, panelWindow }));

import ActivityBar from "../ActivityBar.svelte";
import EditorTabs from "../EditorTabs.svelte";
import { REFERENCE_EXTRA_IDS, SIDE_PANEL_LIMITS, SIDE_PANEL_ORDER, setSidePanel, sidePanelRecency, sidePanels, versesOpen } from "../../editorPrefs";
import { closeTab, groupOf, openTabs, resetTabLayout, selectTab, tabLayout, visibleTabs } from "../../editorTabs";
import { addReference, canAddReference, projectReferenceName, referenceEntries, removeReference, tabLabels } from "../../referenceTabs";
import { currentChapter, project } from "../../stores";

// Verses and Review open, every reference closed and none added.
function reset(): void {
  for (const id of SIDE_PANEL_ORDER) {
    setSidePanel(id, { open: id === "review", width: SIDE_PANEL_LIMITS[id].initial, float: null, detached: false, folder: undefined });
  }
  sidePanelRecency.set([]);
  versesOpen.set(true);
  resetTabLayout();
}

const rail = () => screen.getByRole("button", { name: "Reference" });
const row = (name: string | RegExp) => screen.getByRole("menuitem", { name });
/** Each entry of the list as it reads: a reference's name and its "open" badge, or a Remove button's name. */
const rows = () => screen.getAllByRole("menuitem").map((item) => item.getAttribute("aria-label")
  ?? [item.querySelector(".entry")?.textContent, item.querySelector(".is-open")?.textContent].filter(Boolean).join(" "));

// #519: several reference Bibles. The rail's Reference button opens the
// project's reference tab at first, and a list once one is open or added.
describe("ReferenceMenu (the rail's Reference button)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set({ path: "/p", bookId: "rut", projectId: "p1" } as never);
    currentChapter.set("1");
    reset();
    projectReferenceName.set("");
    languageQaReference.mockResolvedValue({ ready: true, configured: true, source: { path: "D:/bibles/esv", label: "esv", origin: "project" }, verses: [] });
    panelWindow.mockResolvedValue(undefined);
  });

  it("with no reference open and none added, a click opens the project's reference tab and shows no list", async () => {
    render(ActivityBar);
    expect(rail()).toHaveAttribute("aria-pressed", "false");
    expect(rail()).not.toHaveAttribute("aria-haspopup");
    await fireEvent.click(rail());
    expect(screen.queryByRole("menu")).toBeNull();
    expect(get(sidePanels).reference.open).toBe(true);
    expect(get(visibleTabs).has("reference")).toBe(true);
    expect(rail()).toHaveClass("open");
    expect(rail()).toHaveClass("active");
    expect(languageQaReference).not.toHaveBeenCalled();
  });

  it("once a reference is open, a click opens the list: the reference, marked open, and Add new reference", async () => {
    render(ActivityBar);
    await fireEvent.click(rail());
    expect(rail()).toHaveAttribute("aria-haspopup", "menu");
    await fireEvent.click(rail());
    expect(screen.getByRole("menu", { name: "Reference Bibles" })).toBeInTheDocument();
    // Its name is read as the list opens (the tab may be closed, or changed in Settings).
    await waitFor(() => expect(row(/^esv/)).toBeInTheDocument());
    expect(languageQaReference).toHaveBeenCalledWith("/p", "1");
    expect(rows()).toEqual(["esv open", "Add new reference"]);
    // The click did not close the tab: the list never closes one.
    expect(get(sidePanels).reference.open).toBe(true);
    // A second click, or Escape, puts the list away.
    await fireEvent.click(rail());
    expect(screen.queryByRole("menu")).toBeNull();
    await fireEvent.click(rail());
    await fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(get(sidePanels).reference.open).toBe(true);
  });

  it("choosing a reference that is behind another tab shows it, and one that is closed opens it", async () => {
    render(ActivityBar);
    await fireEvent.click(rail());
    selectTab("editor");
    expect(get(visibleTabs).has("reference")).toBe(false);
    await fireEvent.click(rail());
    await fireEvent.click(await screen.findByRole("menuitem", { name: /^esv/ }));
    expect(screen.queryByRole("menu")).toBeNull();
    expect(get(visibleTabs).has("reference")).toBe(true);
    // Closed, with an added reference keeping the list: its row has no badge, and opens it.
    setSidePanel("reference2", { folder: "D:/bibles/niv" });
    closeTab("reference");
    expect(get(sidePanels).reference.open).toBe(false);
    await fireEvent.click(rail());
    await waitFor(() => expect(rows()).toEqual(["esv", "niv", "Remove niv from this list", "Add new reference"]));
    await fireEvent.click(row(/^esv$/));
    expect(get(sidePanels).reference.open).toBe(true);
    expect(get(visibleTabs).has("reference")).toBe(true);
  });

  it("Add new reference opens a new, empty reference tab; it is named once it has a folder", async () => {
    render(ActivityBar);
    await fireEvent.click(rail());
    await fireEvent.click(rail());
    await fireEvent.click(row("Add new reference"));
    expect(screen.queryByRole("menu")).toBeNull();
    expect(get(sidePanels).reference2).toMatchObject({ open: true });
    expect(get(sidePanels).reference2.folder).toBeUndefined();
    expect(get(visibleTabs).has("reference2")).toBe(true);
    // Both reference tabs are tabs of the same group, each with its own id.
    expect(get(openTabs)).toEqual(["editor", "reference", "reference2", "review"]);
    expect(get(tabLayout).groups[groupOf(get(tabLayout), "reference2")!].tabs).toEqual(["editor", "reference", "reference2"]);
    await fireEvent.click(rail());
    await waitFor(() => expect(rows()).toEqual(["esv open", "New reference open", "Remove New reference from this list", "Add new reference"]));
    setSidePanel("reference2", { folder: "D:\\bibles\\niv" });
    await waitFor(() => expect(rows()).toEqual(["esv open", "niv open", "Remove niv from this list", "Add new reference"]));
    expect(get(tabLabels)).toMatchObject({ reference: "esv", reference2: "niv", reference3: "Reference", source: "Source", editor: "Verses" });
  });

  it("an added reference stays in the list after its tab is closed, reopens from it, and goes when removed", async () => {
    render(ActivityBar);
    setSidePanel("reference2", { open: true, folder: "D:/bibles/niv" });
    closeTab("reference2");
    expect(get(sidePanels).reference2).toMatchObject({ open: false, folder: "D:/bibles/niv" });
    // Every reference tab is closed, but one was added: still the list.
    await fireEvent.click(rail());
    await waitFor(() => expect(rows()).toEqual(["esv", "niv", "Remove niv from this list", "Add new reference"]));
    await fireEvent.click(row(/^niv$/));
    expect(get(sidePanels).reference2.open).toBe(true);
    expect(get(visibleTabs).has("reference2")).toBe(true);
    await fireEvent.click(rail());
    await fireEvent.click(await screen.findByRole("menuitem", { name: "Remove niv from this list" }));
    expect(get(sidePanels).reference2).toMatchObject({ open: false, detached: false });
    expect(get(sidePanels).reference2.folder).toBeUndefined();
    expect(get(openTabs)).not.toContain("reference2");
    // Nothing open and nothing added: the list goes, and the button opens the tab again.
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    expect(rail()).not.toHaveAttribute("aria-haspopup");
  });

  it("allows four references in all, and says so on a fifth", async () => {
    render(ActivityBar);
    setSidePanel("reference", { open: true });
    expect(addReference()).toBe("reference2");
    setSidePanel("reference2", { folder: "D:/a" });
    closeTab("reference2");
    // A closed one with its folder still holds its place.
    expect(addReference()).toBe("reference3");
    expect(addReference()).toBe("reference4");
    expect(get(canAddReference)).toBe(false);
    expect(addReference()).toBeNull();
    await fireEvent.click(rail());
    const add = screen.getByRole("menuitem", { name: "Add new reference" });
    expect(add).toBeDisabled();
    await fireEvent.mouseEnter(add);
    // (The row the list opened on, which has the focus, shows its own hint too.)
    expect(screen.getAllByRole("tooltip").map((hint) => hint.textContent).join(" | ")).toContain("Four references at most. Remove one from this list first");
    await fireEvent.mouseLeave(add);
    // An empty one that is closed gives its place back; so does a removed one.
    closeTab("reference4");
    expect(get(canAddReference)).toBe(true);
    removeReference("reference2");
    expect(get(referenceEntries).map((entry) => entry.id)).toEqual(["reference", "reference3"]);
    expect(REFERENCE_EXTRA_IDS).toHaveLength(3);
  });

  it("a reference in its own window is marked open, and choosing it brings the window forward where it stands", async () => {
    render(ActivityBar);
    setSidePanel("reference2", { open: true, detached: true, folder: "D:/bibles/niv" });
    expect(get(openTabs)).not.toContain("reference2");
    await tick();
    expect(rail()).toHaveClass("open");
    expect(rail()).not.toHaveClass("active");
    await fireEvent.click(rail());
    await waitFor(() => expect(rows()).toEqual(["esv", "niv open", "Remove niv from this list", "Add new reference"]));
    await fireEvent.click(row(/^niv/));
    expect(panelWindow).toHaveBeenCalledWith("reference2", "focus");
    // Still its own window: not pulled back into a tab.
    expect(get(sidePanels).reference2).toMatchObject({ open: true, detached: true });
  });

  it("names the project's reference when none is chosen, and moves through the list by keyboard", async () => {
    languageQaReference.mockResolvedValue({ ready: false, configured: false, source: null, verses: [] });
    render(ActivityBar);
    await fireEvent.click(rail());
    await fireEvent.click(rail());
    await waitFor(() => expect(languageQaReference).toHaveBeenCalled());
    expect(rows()).toEqual(["Reference Bible open", "Add new reference"]);
    await waitFor(() => expect(document.activeElement).toBe(row(/^Reference Bible/)));
    await fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(row("Add new reference"));
    await fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(row(/^Reference Bible/));
  });
});

describe("a reference tab's name in the tab strip (#519)", () => {
  beforeEach(() => { reset(); projectReferenceName.set(""); });

  it("is its reference's name, on the tab, its close button and Split right; \"Reference\" until one is chosen", async () => {
    setSidePanel("reference", { open: true });
    setSidePanel("reference2", { open: true });
    render(EditorTabs, { props: { group: groupOf(get(tabLayout), "editor")! } });
    expect(screen.getAllByRole("tab").map((item) => item.textContent?.trim())).toEqual(["Verses", "Reference", "Reference"]);
    projectReferenceName.set("esv");
    setSidePanel("reference2", { folder: "D:/bibles/Hindi OV/" });
    await waitFor(() => expect(screen.getAllByRole("tab").map((item) => item.textContent?.trim())).toEqual(["Verses", "esv", "Hindi OV"]));
    expect(screen.getByRole("tab", { name: "Hindi OV" })).toHaveAttribute("aria-controls", "side-panel-reference2");
    expect(screen.getByRole("button", { name: "Split Hindi OV to the right" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Close Hindi OV" }));
    // Closed, not forgotten: its folder is kept for the rail's list.
    expect(get(sidePanels).reference2).toMatchObject({ open: false, folder: "D:/bibles/Hindi OV/" });
    expect(get(sidePanels).reference.open).toBe(true);
  });
});
