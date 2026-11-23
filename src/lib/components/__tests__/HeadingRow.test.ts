/**
 * #507: a heading above a verse, and editing its text in place. Section
 * headings (\s), major headings (\ms), reference lines (\r) and a psalm title
 * before verse 1 (\d) all go through this one component. jsdom does not lay
 * out, so stickiness and sizes are not checked here.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";

const { editHeading } = vi.hoisted(() => ({ editHeading: vi.fn() }));
vi.mock("../../api/bridgeClient", () => ({ bridge: { editHeading } }));

import HeadingRow from "../HeadingRow.svelte";
import { checkingProgress, headingsByVerse, verseKey } from "../../stores";

const idle = { running: false, percent: 0, label: "", jobId: "", state: "idle", error: "", scope: "chapter" } as const;

function show(tag: string, text: string, index = 0) {
  return render(HeadingRow, { props: { chapter: "3", verse: "1", index, heading: { tag, text } } });
}

beforeEach(() => {
  editHeading.mockReset();
  headingsByVerse.set({});
  checkingProgress.set({ ...idle });
});
afterEach(() => cleanup());

describe("HeadingRow reading", () => {
  it("names the heading by its text alone, though the edit button sits inside it", () => {
    show("s", "The Lord answers");
    const heading = screen.getByRole("heading", { name: "The Lord answers" });
    expect(heading.classList.contains("section-heading")).toBe(true);
    expect(heading.querySelector("button")).toBe(screen.getByLabelText("Edit the heading: The Lord answers"));
  });

  it("classes each kind, and marks the two that do not stick", () => {
    const cases: [string, string[]][] = [
      ["s", []], ["s2", []], ["ms", ["major"]], ["ms1", ["major"]],
      ["r", ["reference", "unstuck"]], ["mr", ["reference", "unstuck"]], ["d", ["title", "unstuck"]],
    ];
    for (const [tag, expected] of cases) {
      show(tag, "Text");
      const heading = screen.getByRole("heading", { name: "Text" });
      const found = ["major", "reference", "title", "unstuck"].filter((name) => heading.classList.contains(name));
      expect(found, tag).toEqual(expected);
      cleanup();
    }
  });

  it("cannot be edited while a check is running", () => {
    checkingProgress.set({ ...idle, running: true });
    show("s", "The Lord answers");
    expect(screen.getByLabelText("Edit the heading: The Lord answers")).toBeDisabled();
  });
});

describe("HeadingRow editing", () => {
  async function openEditor(tag = "s", text = "The Lord answers", index = 0): Promise<HTMLInputElement> {
    show(tag, text, index);
    await fireEvent.click(screen.getByRole("button", { name: new RegExp(`^Edit the .*: ${text}$`) }));
    return screen.getByRole("textbox") as HTMLInputElement;
  }

  it("opens a box holding the stored text and saves on Enter, then shows the heading the engine stored", async () => {
    const input = await openEditor("s", "The Lord answers", 1);
    expect(input.value).toBe("The Lord answers");
    expect(screen.queryByRole("heading")).toBeNull();
    const saved = [{ tag: "d", text: "A Psalm" }, { tag: "s", text: "The Lord replies" }];
    editHeading.mockResolvedValue({ chapter: "3", verse: "1", index: 1, headings: saved, warnings: [] });

    await fireEvent.input(input, { target: { value: "The Lord replies" } });
    await fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(get(headingsByVerse)[verseKey("3", "1")]).toEqual(saved));
    // chapter, verse, the heading's place, the new text, and the text the edit started from.
    expect(editHeading).toHaveBeenCalledWith("3", "1", 1, "The Lord replies", "The Lord answers");
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("saves from the button too, and a psalm title the same way", async () => {
    const input = await openEditor("d", "A Psalm of David");
    expect(screen.getByLabelText("Text of the psalm title")).toBe(input);
    editHeading.mockResolvedValue({ chapter: "3", verse: "1", index: 0, headings: [{ tag: "d", text: "A Psalm" }], warnings: [] });
    await fireEvent.input(input, { target: { value: "A Psalm" } });
    await fireEvent.click(screen.getByLabelText("Save the psalm title"));
    await waitFor(() => expect(editHeading).toHaveBeenCalledWith("3", "1", 0, "A Psalm", "A Psalm of David"));
  });

  it("writes nothing on Escape, on Cancel, or when the text was not changed", async () => {
    let input = await openEditor();
    await fireEvent.input(input, { target: { value: "Something else" } });
    await fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.getByRole("heading", { name: "The Lord answers" })).toBeInTheDocument();
    cleanup();

    input = await openEditor();
    await fireEvent.click(screen.getByLabelText("Cancel editing the heading"));
    expect(screen.queryByRole("textbox")).toBeNull();
    cleanup();

    input = await openEditor();
    await fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(editHeading).not.toHaveBeenCalled();
  });

  it("keeps the typed text and says why when the engine refuses", async () => {
    const input = await openEditor();
    editHeading.mockRejectedValueOnce(new Error("A heading is one paragraph: it cannot hold \\q1. Nothing was written."));
    await fireEvent.input(input, { target: { value: "A \\q1 B" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByRole("alert")).toHaveTextContent("cannot hold \\q1");
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("A \\q1 B");

    editHeading.mockRejectedValueOnce(new Error("REVISION_CONFLICT: the heading was changed after this edit was started; nothing was written."));
    await fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("changed after you started"));
    expect(get(headingsByVerse)).toEqual({});
  });

  it("reports marker problems in a saved heading without undoing the save", async () => {
    const input = await openEditor();
    editHeading.mockResolvedValue({
      chapter: "3", verse: "1", index: 0, headings: [{ tag: "s", text: "The \\nd Lord answers" }],
      warnings: ["Unbalanced \\nd: 1 open, 0 close"],
    });
    await fireEvent.input(input, { target: { value: "The \\nd Lord answers" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByRole("status")).toHaveTextContent("Saved, but check the markers: Unbalanced \\nd: 1 open, 0 close");
  });

  it("does not let an empty heading be saved", async () => {
    const input = await openEditor();
    await fireEvent.input(input, { target: { value: "   " } });
    expect(screen.getByLabelText("Save the heading")).toBeDisabled();
  });
});
