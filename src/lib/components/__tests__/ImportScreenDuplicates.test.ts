import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import ImportScreen, { forgetHandledDrops } from "../ImportScreen.svelte";
import type { DuplicateMatch, ImportPreview } from "../../types/finding";
import { project } from "../../stores";

const { inspectImport, importStart, importStatus, openProject } = vi.hoisted(() => ({
  inspectImport: vi.fn(), importStart: vi.fn(), importStatus: vi.fn(), openProject: vi.fn(),
}));
vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    listProjects: vi.fn(async () => ({ projects: [] })), inspectImport, importStart, importStatus, openProject,
  },
}));

const SOURCE = "C:/sources/TIT.usfm";
function match(index: number, overrides: Partial<DuplicateMatch> = {}): DuplicateMatch {
  return { match: "exact", reason: "sourceFingerprint", groupId: `g-${index}`, projectId: `p-${index}`,
    path: `C:/projects/copy-${index}`, bookId: "tit", bookName: "Titus", projectName: `Review ${index}`, missing: false,
    ...overrides };
}
function preview(matches: DuplicateMatch[] = [match(1), match(2)]): ImportPreview {
  return {
    sourcePath: SOURCE, kind: "usfm",
    metadata: { languageId: "eng", languageName: "English", languageDirection: "ltr", projectName: "New review", bibleName: "Test Bible" },
    books: [{ bookId: "tit", bookName: "Titus", sourceFile: SOURCE, verseCount: 3, hasAlignments: false }],
    missingFields: [], warnings: [],
    duplicates: { classification: matches.length ? "exactDuplicate" : "new", matches, inputBookCount: 1,
      exactBookCount: matches.length ? 1 : 0, missingExactBookCount: 0, possibleBookCount: 0, overlapBookCount: matches.length ? 1 : 0,
      matchingGroupCount: new Set(matches.map((item) => item.groupId)).size, exactMatchGroupId: matches[0]?.groupId || "",
      sourceFingerprints: { tit: "source-hash" }, collectionFingerprint: "collection-hash" },
  };
}
async function mount() {
  const onOpened = vi.fn();
  render(ImportScreen, { props: { onOpened, droppedPath: SOURCE, dropSequence: 1 } });
  await screen.findByText("Confirm project details");
  return onOpened;
}
const dialog = () => screen.getByRole("dialog");

describe("duplicate import choices (#407)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    forgetHandledDrops();
    project.set(null);
    inspectImport.mockResolvedValue(preview());
    openProject.mockResolvedValue({ path: "C:/projects/copy-2", bookId: "tit", chapters: ["1"] });
    importStart.mockResolvedValue({ jobId: "j-1", state: "queued", percent: 0 });
    importStatus.mockResolvedValue({ jobId: "j-1", state: "cancelled" });
  });

  it("opens the chosen project instead of the first duplicate match", async () => {
    const onOpened = await mount();
    const open = within(dialog()).getByRole("button", { name: "Open Review 2" });
    expect(open.textContent).toBe("");
    expect(open.querySelector("svg")).not.toBeNull();
    await fireEvent.mouseEnter(open);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Open Review 2");
    await fireEvent.mouseLeave(open);
    await fireEvent.click(open);
    await waitFor(() => expect(onOpened).toHaveBeenCalledOnce());
    expect(openProject).toHaveBeenCalledOnce();
    expect(openProject).toHaveBeenCalledWith("C:/projects/copy-2", "p-2", expect.any(Function));
    expect(importStart).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("lists every related project and requires a choice rather than outside-click or Escape dismissal", async () => {
    inspectImport.mockResolvedValue(preview(Array.from({ length: 12 }, (_, index) => match(index + 1))));
    await mount();
    const modal = dialog();
    expect(within(modal).getAllByRole("button", { name: /^Open Review/ })).toHaveLength(12);
    expect(within(modal).getByRole("heading", { name: "Related projects" })).toBeInTheDocument();
    expect(modal.querySelector(".related-list")).not.toContainElement(within(modal).getByRole("heading", { name: "Related projects" }));
    await fireEvent.click(modal, { clientX: -1, clientY: -1 });
    await fireEvent.keyDown(modal, { key: "Escape" });
    const cancel = new Event("cancel", { cancelable: true });
    modal.dispatchEvent(cancel);
    expect(cancel.defaultPrevented).toBe(true);
    expect(modal).toHaveAttribute("open");
    expect(openProject).not.toHaveBeenCalled();
    expect(importStart).not.toHaveBeenCalled();
    const create = within(modal).getByRole("button", { name: /Create a new project/ });
    create.focus();
    await fireEvent.keyDown(create, { key: "Tab" });
    expect(within(modal).getByRole("button", { name: "Open Review 1" })).toHaveFocus();
    await fireEvent.keyDown(document.activeElement!, { key: "Tab", shiftKey: true });
    expect(create).toHaveFocus();
  });

  it("continues to a single Import action after explicit new-project consent", async () => {
    await mount();
    await fireEvent.click(within(dialog()).getByRole("button", { name: /Create a new project/ }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: /Open existing project/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Import as a separate copy/ })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Import book" }));
    await waitFor(() => expect(importStart).toHaveBeenCalledWith(SOURCE, expect.objectContaining({ projectName: "New review" }), true));
    expect(importStart).toHaveBeenCalledOnce();
    expect(openProject).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("requires a choice for duplicates discovered during final validation", async () => {
    inspectImport.mockResolvedValueOnce(preview([])).mockResolvedValue(preview());
    await mount();
    expect(screen.queryByRole("dialog")).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Import book" }));
    await screen.findByRole("dialog");
    expect(importStart).not.toHaveBeenCalled();
    await fireEvent.click(within(dialog()).getByRole("button", { name: /Create a new project/ }));
    await fireEvent.click(screen.getByRole("button", { name: "Import book" }));
    await waitFor(() => expect(importStart).toHaveBeenCalledOnce());
  });

  it("asks again when the selected books change, then imports only that selection", async () => {
    const source = preview();
    source.books.push({ bookId: "phm", bookName: "Philemon", sourceFile: "C:/sources/PHM.usfm", verseCount: 1, hasAlignments: false });
    inspectImport.mockImplementation(async (_path, _metadata, selected) => selected
      ? { ...source, books: source.books.filter((book) => selected.includes(book.bookId)) } : source);
    await mount();
    await fireEvent.click(within(dialog()).getByRole("button", { name: /Create a new project/ }));
    await fireEvent.click(screen.getByRole("checkbox", { name: "Import Titus" }));
    await fireEvent.click(screen.getByRole("button", { name: "Import book" }));
    await screen.findByRole("dialog");
    expect(importStart).not.toHaveBeenCalled();
    await fireEvent.click(within(dialog()).getByRole("button", { name: /Create a new project/ }));
    await fireEvent.click(screen.getByRole("button", { name: "Import book" }));
    await waitFor(() => expect(importStart).toHaveBeenCalledWith(SOURCE, expect.anything(), true, ["phm"]));
  });

  it("does not reuse consent when final validation finds a different related project", async () => {
    inspectImport.mockResolvedValueOnce(preview([match(1)])).mockResolvedValue(preview([match(3)]));
    await mount();
    await fireEvent.click(within(dialog()).getByRole("button", { name: /Create a new project/ }));
    await fireEvent.click(screen.getByRole("button", { name: "Import book" }));
    await screen.findByRole("dialog");
    expect(within(dialog()).getByRole("button", { name: "Open Review 3" })).toBeInTheDocument();
    expect(importStart).not.toHaveBeenCalled();
  });

  it("keeps failed Open choices in the dialog so the user can try another project", async () => {
    openProject.mockRejectedValueOnce(new Error("Project unavailable"));
    const onOpened = await mount();
    await fireEvent.click(within(dialog()).getByRole("button", { name: "Open Review 1" }));
    expect(await within(dialog()).findByRole("alert")).toHaveTextContent("Project unavailable");
    await waitFor(() => expect(within(dialog()).getByRole("button", { name: "Open Review 2" })).toBeEnabled());
    await fireEvent.click(within(dialog()).getByRole("button", { name: "Open Review 2" }));
    await waitFor(() => expect(onOpened).toHaveBeenCalledOnce());
    expect(openProject).toHaveBeenLastCalledWith("C:/projects/copy-2", "p-2", expect.any(Function));
  });

  it("disables missing projects but opens an available member of a matching collection", async () => {
    inspectImport.mockResolvedValue(preview([
      match(1, { missing: true }), match(2, { groupId: "g-1" }), match(3, { missing: true }),
    ]));
    await mount();
    expect(within(dialog()).getByRole("button", { name: "Open Review 3" })).toBeDisabled();
    const available = within(dialog()).getByRole("button", { name: "Open Review 1" });
    expect(available).toBeEnabled();
    await fireEvent.click(available);
    await waitFor(() => expect(openProject).toHaveBeenCalledWith("C:/projects/copy-2", "p-2", expect.any(Function)));
  });

  it("opens language suggestions only on click or typing and displays only the selected name", async () => {
    inspectImport.mockResolvedValue(preview([]));
    await mount();
    const language = screen.getByRole("textbox", { name: "Language" });
    expect(screen.queryByRole("group", { name: "Language suggestions" })).toBeNull();
    await fireEvent.focus(language);
    expect(screen.queryByRole("group", { name: "Language suggestions" })).toBeNull();
    await fireEvent.click(language);
    expect(screen.getByRole("group", { name: "Language suggestions" })).toBeInTheDocument();
    await fireEvent.input(language, { target: { value: "English" } });
    await fireEvent.click(screen.getByRole("button", { name: "English eng" }));
    expect(language).toHaveValue("English");
    expect(screen.queryByRole("group", { name: "Language suggestions" })).toBeNull();
    await fireEvent.click(language);
    await fireEvent.focusOut(language, { relatedTarget: screen.getByRole("textbox", { name: "Project name" }) });
    expect(screen.queryByRole("group", { name: "Language suggestions" })).toBeNull();
  });

  it("closes import review and returns to Projects without opening or importing", async () => {
    inspectImport.mockResolvedValue(preview([]));
    await mount();
    await fireEvent.click(screen.getByRole("button", { name: "Close import review" }));
    await screen.findByRole("heading", { name: "Projects" });
    expect(screen.queryByText("Confirm project details")).toBeNull();
    expect(importStart).not.toHaveBeenCalled();
    expect(openProject).not.toHaveBeenCalled();
  });

  it("keeps clear form guidance and a direction control without opening an arbitrary project", async () => {
    const source = preview();
    source.metadata.languageId = "";
    source.metadata.languageName = "";
    inspectImport.mockResolvedValue(source);
    await mount();
    await fireEvent.click(within(dialog()).getByRole("button", { name: /Create a new project/ }));
    expect(screen.getByRole("button", { name: "Import book" })).toBeDisabled();
    expect(screen.getByText("To import, complete: language.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Language" })).toHaveFocus();
    expect(screen.queryByRole("group", { name: "Language suggestions" })).toBeNull();
    await fireEvent.input(screen.getByRole("textbox", { name: "Language" }), { target: { value: "English" } });
    await fireEvent.click(screen.getByRole("button", { name: "English eng" }));
    await fireEvent.click(screen.getByRole("button", { name: /Right to left/ }));
    expect(screen.getByRole("button", { name: /Right to left/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Left to right/ })).toHaveAttribute("aria-pressed", "false");
    await fireEvent.click(screen.getByRole("button", { name: "Import book" }));
    await waitFor(() => expect(importStart).toHaveBeenCalledWith(SOURCE, expect.objectContaining({ languageDirection: "rtl", languageId: "eng" }), true));
    expect(openProject).not.toHaveBeenCalled();
  });
});
