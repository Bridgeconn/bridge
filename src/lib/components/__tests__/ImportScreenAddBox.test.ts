import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/svelte";

// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";

const { listProjects } = vi.hoisted(() => ({ listProjects: vi.fn() }));
vi.mock("../../api/bridgeClient", () => ({ bridge: { listProjects, pickFile: vi.fn(), pickFolder: vi.fn() } }));
import ImportScreen from "../ImportScreen.svelte";

// 2026-11-16 (Joel): the Projects page's "Add a project" is one box, which is
// also where a file or folder is dropped. It replaced a page title with a
// count, a heading, two cards, a hint line and a link, each on its own row.
describe("the Projects page's Add a project box", () => {
  beforeEach(() => { vi.clearAllMocks(); listProjects.mockResolvedValue({ projects: [] }); });

  it("holds the three ways to add a project in one box, with no page title row", async () => {
    render(ImportScreen, { props: { onOpened: vi.fn() } });
    const box = await screen.findByRole("region", { name: "Add a project" });
    expect(box).toHaveAttribute("data-import-drop");
    // Three icon tiles: a full name for screen readers, one word under the icon, the rest in the hint.
    const tiles = within(box).getAllByRole("button");
    expect(tiles.map((tile) => tile.getAttribute("aria-label"))).toEqual(["Import a file", "Import a folder", "Open an existing project"]);
    expect(tiles.map((tile) => tile.textContent?.trim())).toEqual(["File", "Folder", "Existing"]);
    for (const tile of tiles) expect(tile.querySelector("svg")).not.toBeNull();
    await fireEvent.mouseEnter(tiles[0]);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Import a file: USFM, SFM, TXT, TCORE, TSTUDIO or ZIP");
    await fireEvent.mouseLeave(tiles[0]);
    expect(box).toHaveTextContent("Drag a file or folder into this area, or pick a way to add one.");
    // The drawing on the left is not a control.
    expect(box.querySelector(".add-art")?.closest("button")).toBeNull();
    // The page still has its heading for screen readers; nothing is drawn for it.
    expect(screen.getByRole("heading", { name: "Projects" })).toHaveClass("sr-only");
    expect(document.querySelector(".project-count")).toBeNull();
    expect(screen.queryByText(/anywhere in this window/)).toBeNull();
  });

  it("shows that it is the place to drop while something is dragged, and when it is over the box", async () => {
    const view = render(ImportScreen, { props: { onOpened: vi.fn() } });
    const box = await screen.findByRole("region", { name: "Add a project" });
    expect(box).toHaveTextContent("Add a project");
    await view.component.$set({ dragging: true });
    expect(box).toHaveClass("dragging");
    expect(box).toHaveTextContent("Drop it here");
    await view.component.$set({ dragOver: true });
    expect(box).toHaveClass("over");
    expect(box).toHaveTextContent("Drop to add this project");
  });

  // The wiring is App's, which no test mounts: pinned as written.
  it("takes a drop only on the box, and says so for a drop anywhere else", () => {
    const app: string = readFileSync(resolve("src/App.svelte"), "utf8");
    expect(app).toMatch(/handleDroppedPaths\(paths, onDropBox\(at\)\)/);
    expect(app).toContain('document.querySelector<HTMLElement>("[data-import-drop]")');
    expect(app).toContain("Drop the file or folder inside the “Add a project” box.");
    expect(app).not.toContain("global-drop");
  });
});
