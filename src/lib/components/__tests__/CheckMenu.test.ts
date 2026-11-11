import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";

import CheckMenu from "../CheckMenu.svelte";
import { editorChecks } from "../../editorPrefs";
import { selectedEditorChecks } from "../../checkSelection";

function mount(overrides: Record<string, unknown> = {}) {
  const props = {
    chapter: "2", verse: "2:3", onRunChapter: vi.fn(), onRunBook: vi.fn(), onRunGreekRoom: vi.fn(), ...overrides,
  };
  render(CheckMenu, { props });
  return props;
}

const trigger = () => screen.getByRole("button", { name: /^Check ▾/ });

describe("CheckMenu in the top bar (#488)", () => {
  beforeEach(() => editorChecks.set(["languageQa"]));

  it("offers Check whole book first and runs the book with it", async () => {
    const props = mount();
    await fireEvent.click(trigger());
    const group = screen.getByRole("group", { name: "Check" });
    expect(group.querySelector("button")).toHaveTextContent("Check whole book");
    await fireEvent.click(screen.getByRole("button", { name: "Check whole book" }));
    expect(props.onRunBook).toHaveBeenCalledOnce();
    expect(screen.queryByRole("group", { name: "Check" })).toBeNull();
  });

  it("ticks change the saved selection the run uses, and the last one cannot be unticked", async () => {
    mount();
    await fireEvent.click(trigger());
    const lqa = screen.getByRole("checkbox", { name: "Language QA" });
    expect(lqa).toBeChecked();
    expect(lqa).toBeDisabled();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Alignment" }));
    expect(get(selectedEditorChecks)).toEqual(["alignment", "languageQa"]);
    expect(JSON.parse(localStorage.getItem("bridge.editor.checks.v1") ?? "[]")).toContain("alignment");
    expect(lqa).not.toBeDisabled();
  });

  it("disables the runs while a check is running", async () => {
    mount({ disabled: true });
    await fireEvent.click(trigger());
    expect(screen.getByRole("button", { name: "Check whole book" })).toBeDisabled();
  });

  it("Escape closes the menu and returns focus to its button", async () => {
    mount();
    await fireEvent.click(trigger());
    await fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Check" })).toBeNull();
    expect(document.activeElement).toBe(trigger());
  });
});
