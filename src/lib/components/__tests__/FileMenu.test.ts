import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import FileMenu from "../FileMenu.svelte";

async function openMenu(props: Record<string, unknown> = {}) {
  const view = render(FileMenu, { props });
  await fireEvent.click(screen.getByRole("button", { name: "File ▾" }));
  return view;
}

describe("FileMenu", () => {
  it("lists Close editor, Close project, Export project, Settings and Exit, in that order", async () => {
    await openMenu();
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent?.trim())).toEqual(
      ["Close editor", "Close project", "Export project…", "Settings…", "Exit"]);
  });

  it("each entry runs its action and closes the menu", async () => {
    const actions = { onCloseEditor: vi.fn(), onCloseProject: vi.fn(), onExport: vi.fn(), onSettings: vi.fn(), onExit: vi.fn() };
    const entries: Array<[string, keyof typeof actions]> = [["Close editor", "onCloseEditor"], ["Close project", "onCloseProject"],
      ["Export project…", "onExport"], ["Settings…", "onSettings"], ["Exit", "onExit"]];
    render(FileMenu, { props: actions });
    for (const [name, action] of entries) {
      await fireEvent.click(screen.getByRole("button", { name: "File ▾" }));
      await fireEvent.click(screen.getByRole("menuitem", { name }));
      expect(actions[action]).toHaveBeenCalledOnce();
      expect(screen.queryByRole("menu")).toBeNull();
    }
  });

  it("Export is disabled with no project, and Close editor while a book is being opened", async () => {
    const onExport = vi.fn(), onCloseEditor = vi.fn();
    await openMenu({ onExport, onCloseEditor, exportDisabled: true, busy: true });
    expect(screen.getByRole("menuitem", { name: "Export project…" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Close editor" })).toBeDisabled();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Export project…" }));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Close editor" }));
    expect(onExport).not.toHaveBeenCalled();
    expect(onCloseEditor).not.toHaveBeenCalled();
    expect(screen.getByRole("menuitem", { name: "Close project" })).toBeEnabled();
  });

  it("closes on Escape and returns focus to its button", async () => {
    await openMenu();
    await fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.getByRole("button", { name: "File ▾" })).toHaveFocus();
  });
});
