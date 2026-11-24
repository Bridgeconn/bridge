import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const { languageQaReference, languageQaRelated, languageQaSetReference, pickFolder } = vi.hoisted(() => ({
  languageQaReference: vi.fn(),
  languageQaRelated: vi.fn(),
  languageQaSetReference: vi.fn(),
  pickFolder: vi.fn(),
}));
vi.mock("../../api/bridgeClient", () => ({
  bridge: { languageQaReference, languageQaRelated, languageQaSetReference, pickFolder },
}));

import ReferencePanel from "../ReferencePanel.svelte";
import RelatedWords from "../RelatedWords.svelte";
import { currentChapter, project, selectedVerse } from "../../stores";
import { projectReferenceName } from "../../referenceNames";
import { referenceTextScale, textScale } from "../../editorPrefs";
import { get } from "svelte/store";

const READY = {
  ready: true, configured: true, source: { path: "D:/OV", label: "Old Version", kind: "tsv" },
  verses: [{ verse: "1", text: "நியாயாதிபதிகள் நியாயம் விசாரித்துவரும் நாட்களில்" }, { verse: "2", text: "அந்த மனுஷனுடைய பேர்" }],
};

describe("ReferencePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set({ path: "/p", bookId: "rut" } as never);
    currentChapter.set("1");
    selectedVerse.set("2");
  });

  afterEach(() => selectedVerse.set(null));

  it("shows the chapter with the selected verse marked, and a click selects that verse in the text", async () => {
    languageQaReference.mockResolvedValue(READY);
    const onSelectVerse = vi.fn();
    render(ReferencePanel, { props: { onSelectVerse } });
    expect(await screen.findByText("Old Version")).toBeTruthy();
    expect(languageQaReference).toHaveBeenCalledWith("/p", "1");
    expect(document.querySelector('[data-ref-verse="2"]')?.classList.contains("current")).toBe(true);
    await fireEvent.click(screen.getByRole("button", { name: /Verse 1 in the reference/ }));
    expect(onSelectVerse).toHaveBeenCalledWith("1");
  });

  // #289: one reference Bible per project, chosen from the panel itself.
  it("with nothing chosen, Browse opens the folder picker, saves the folder for the project and reads it", async () => {
    languageQaReference
      .mockResolvedValueOnce({ ready: false, configured: false, source: null, verses: [], pack: null })
      .mockResolvedValue({ ...READY, source: { path: "D:/OV Hindi", label: "OV Hindi", origin: "project", kind: "usfm" } });
    pickFolder.mockResolvedValue("D:/OV Hindi");
    languageQaSetReference.mockResolvedValue({ folder: "D:/OV Hindi", origin: "project", label: "OV Hindi", path: "D:/OV Hindi" });
    render(ReferencePanel);
    expect(await screen.findByText("No reference Bible is chosen for this project.")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "Browse for a reference Bible on this computer" }));
    await waitFor(() => expect(languageQaSetReference).toHaveBeenCalledWith("/p", "D:/OV Hindi"));
    expect(await screen.findByText("OV Hindi")).toBeTruthy();
    expect(languageQaReference).toHaveBeenCalledTimes(2);
  });

  it("does nothing when the picker is cancelled", async () => {
    languageQaReference.mockResolvedValue({ ready: false, configured: false, source: null, verses: [], pack: null });
    pickFolder.mockResolvedValue(null);
    render(ReferencePanel);
    await fireEvent.click(await screen.findByRole("button", { name: "Browse for a reference Bible on this computer" }));
    await waitFor(() => expect(pickFolder).toHaveBeenCalled());
    expect(languageQaSetReference).not.toHaveBeenCalled();
  });

  it("shows Change once a Bible is set, and names a bundled one as built in", async () => {
    languageQaReference.mockResolvedValue({ ...READY, source: { path: "x", label: "Old Version (bundled)", origin: "bundled" } });
    pickFolder.mockResolvedValue("D:/Other");
    languageQaSetReference.mockResolvedValue({ folder: "D:/Other", origin: "project", label: "Other", path: "D:/Other" });
    render(ReferencePanel);
    expect(await screen.findByText("Built in: Old Version")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "Change" }));
    await waitFor(() => expect(languageQaSetReference).toHaveBeenCalledWith("/p", "D:/Other"));
  });

  it("keeps Change beside a folder that cannot be read, and Settings stays reachable", async () => {
    languageQaReference.mockResolvedValue({ ready: false, configured: true, verses: [],
      source: { path: "D:/empty", label: "empty", origin: "project" }, error: "ValueError: D:/empty holds no verses.tsv and no USFM books." });
    render(ReferencePanel);
    expect(await screen.findByText(/could not be read: ValueError/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Change" })).toBeTruthy();
  });

  it("links to Settings › Language QA when nothing is chosen", async () => {
    languageQaReference.mockResolvedValue({ ready: false, configured: false, source: null, verses: [], pack: null });
    const onOpenSettings = vi.fn();
    render(ReferencePanel, { props: { onOpenSettings } });
    await fireEvent.click(await screen.findByRole("button", { name: /manage it in Settings/ }));
    expect(onOpenSettings).toHaveBeenCalled();
  });

  it("asks again while the folder is still being read", async () => {
    vi.useFakeTimers();
    try {
      languageQaReference.mockResolvedValueOnce({ ready: false, configured: true, source: READY.source, verses: [] })
        .mockResolvedValue(READY);
      render(ReferencePanel);
      await vi.waitFor(() => expect(screen.getByText(/Reading the reference Bible/)).toBeTruthy());
      await vi.advanceTimersByTimeAsync(1100);
      await vi.waitFor(() => expect(languageQaReference).toHaveBeenCalledTimes(2));
    } finally {
      vi.useRealTimers();
    }
    expect(await screen.findByText(/அந்த மனுஷனுடைய/)).toBeTruthy();
  });

  it("follows a newly selected verse unless Follow is off", async () => {
    languageQaReference.mockResolvedValue(READY);
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    render(ReferencePanel);
    await screen.findByText("Old Version");
    selectedVerse.set("1");
    await waitFor(() => expect(scrolled).toHaveBeenCalled());
    // Let every scroll already queued (each waits a tick) land before counting again.
    await new Promise((resolve) => setTimeout(resolve, 20));
    scrolled.mockClear();
    // #519: an icon switch with an instant hint, not a ticked box and the word.
    const follow = screen.getByRole("button", { name: "Follow the selected verse" });
    expect(follow).toHaveAttribute("aria-pressed", "true");
    expect(follow.textContent?.trim()).toBe("");
    expect(follow.querySelector("svg")).not.toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    await fireEvent.mouseEnter(follow);
    expect(screen.getByRole("tooltip")).toHaveTextContent(/^Following: the selected verse is kept in view here/);
    await fireEvent.mouseLeave(follow);
    await fireEvent.click(follow);
    expect(follow).toHaveAttribute("aria-pressed", "false");
    await fireEvent.mouseEnter(follow);
    expect(screen.getByRole("tooltip")).toHaveTextContent(/^Not following/);
    await fireEvent.mouseLeave(follow);
    selectedVerse.set("2");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(scrolled).not.toHaveBeenCalled();
  });

  // #519: the bar is laid out as the Verses header is.
  it("has the chapter picker and arrows at the left, the name centred, then text size, follow, Change and the window tool", async () => {
    project.set({ path: "/p", bookId: "rut", chapters: ["1", "2", "3", "4"] } as never);
    currentChapter.set("2");
    languageQaReference.mockResolvedValue(READY);
    const onChapterChange = vi.fn();
    render(ReferencePanel, { props: { onChapterChange } });
    const title = await screen.findByRole("heading", { level: 2, name: "Old Version" });
    const bar = document.querySelector("[data-panel-bar='reference']") as HTMLElement;
    const nav = screen.getByRole("group", { name: "Chapter navigation" });
    expect(bar.firstElementChild).toContainElement(nav);
    expect(nav).toHaveTextContent(/^Chapter\s*2\s*of 4/);
    expect(title).toHaveClass("centred");
    expect(nav.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // No Go to box here: that is the Verses header's.
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(Array.from(bar.querySelectorAll("button")).map((item) => item.getAttribute("aria-label"))).toEqual([
      "Chapter 2: choose a chapter", "Previous chapter", "Next chapter",
      "Smaller text", "Larger text", "Follow the selected verse", "Change", "Move to separate window"]);
    // The arrows and the picker go through the caller's chapter switch, the Verses header's.
    await fireEvent.click(screen.getByRole("button", { name: "Next chapter" }));
    expect(onChapterChange).toHaveBeenLastCalledWith("3");
    await fireEvent.click(screen.getByRole("button", { name: "Previous chapter" }));
    expect(onChapterChange).toHaveBeenLastCalledWith("1");
    await fireEvent.click(screen.getByRole("button", { name: /^Chapter 2/ }));
    await fireEvent.click(screen.getByRole("option", { name: "4" }));
    expect(onChapterChange).toHaveBeenLastCalledWith("4");
    // The panel reads the chapter the text is on.
    languageQaReference.mockClear();
    currentChapter.set("3");
    await waitFor(() => expect(languageQaReference).toHaveBeenCalledWith("/p", "3"));
  });

  it("Change is an icon with an instant hint, and A− and A+ size the reference text only", async () => {
    referenceTextScale.set(1);
    textScale.set(1);
    languageQaReference.mockResolvedValue(READY);
    render(ReferencePanel);
    await screen.findByText("Old Version");
    const change = screen.getByRole("button", { name: "Change" });
    expect(change.textContent?.trim()).toBe("");
    expect(change.querySelector("svg")).not.toBeNull();
    expect(change).not.toHaveAttribute("title");
    await fireEvent.mouseEnter(change);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Change: choose another reference Bible folder for this project");
    await fireEvent.mouseLeave(change);
    const panel = document.querySelector(".reference-panel") as HTMLElement;
    expect(panel.style.getPropertyValue("--verse-scale")).toBe("1");
    await fireEvent.click(screen.getByRole("button", { name: "Larger text" }));
    expect(get(referenceTextScale)).toBe(1.15);
    expect(panel.style.getPropertyValue("--verse-scale")).toBe("1.15");
    expect(localStorage.getItem("bridge.editor.referenceTextScale.v1")).toBe("1.15");
    // The verse text keeps its own size.
    expect(get(textScale)).toBe(1);
    await fireEvent.mouseEnter(screen.getByRole("button", { name: "Larger text" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Larger text (now 115%)");
    await fireEvent.mouseLeave(screen.getByRole("button", { name: "Larger text" }));
    await fireEvent.click(screen.getByRole("button", { name: "Smaller text" }));
    await fireEvent.click(screen.getByRole("button", { name: "Smaller text" }));
    expect(get(referenceTextScale)).toBe(0.85);
    expect(screen.getByRole("button", { name: "Smaller text" })).toBeDisabled();
    referenceTextScale.set(1);
  });
});

// #519: a reference tab a reviewer added. It reads the folder it is given and
// never touches the project's reference Bible, the one Language QA uses.
describe("ReferencePanel, an added reference tab", () => {
  const ESV = { ready: true, configured: true, source: { path: "D:/bibles/esv", label: "esv", origin: "viewer", kind: "usfm" },
    verses: [{ verse: "1", text: "In the days when the judges ruled" }] };

  beforeEach(() => {
    vi.clearAllMocks();
    project.set({ path: "/p", bookId: "rut" } as never);
    currentChapter.set("1");
    selectedVerse.set("1");
  });
  afterEach(() => selectedVerse.set(null));

  it("with no folder yet asks for one, reads nothing, and Browse hands the folder to the tab, not to the project", async () => {
    pickFolder.mockResolvedValue("D:/bibles/esv");
    const onChooseFolder = vi.fn();
    render(ReferencePanel, { props: { id: "reference2", onChooseFolder } });
    expect(await screen.findByText("No reference Bible is chosen for this tab.")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Reference" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Change" })).toBeNull();
    expect(screen.queryByRole("button", { name: /manage it in Settings/ })).toBeNull();
    expect(languageQaReference).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole("button", { name: "Browse for a reference Bible on this computer" }));
    await waitFor(() => expect(onChooseFolder).toHaveBeenCalledWith("D:/bibles/esv"));
    expect(languageQaSetReference).not.toHaveBeenCalled();
  });

  it("reads its own folder, is named after it, and Change picks another folder for the tab only", async () => {
    languageQaReference.mockResolvedValue(ESV);
    pickFolder.mockResolvedValue("D:/bibles/niv");
    const onChooseFolder = vi.fn();
    const { component } = render(ReferencePanel, { props: { id: "reference2", folder: "D:/bibles/esv", onChooseFolder } });
    expect(await screen.findByText("In the days when the judges ruled")).toBeTruthy();
    expect(languageQaReference).toHaveBeenCalledWith("/p", "1", "D:/bibles/esv");
    expect(screen.getByRole("heading", { level: 2, name: "esv" }).getAttribute("title")).toBe("D:/bibles/esv");
    expect(document.querySelector("[data-panel-bar='reference2']")).not.toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Change" }));
    await waitFor(() => expect(onChooseFolder).toHaveBeenCalledWith("D:/bibles/niv"));
    expect(languageQaSetReference).not.toHaveBeenCalled();
    // The tab keeps the folder and hands it back: the panel reads the new one.
    languageQaReference.mockResolvedValue({ ...ESV, source: { ...ESV.source, path: "D:/bibles/niv", label: "niv" }, verses: [{ verse: "1", text: "In the days when the judges governed" }] });
    component.$set({ folder: "D:/bibles/niv" });
    expect(await screen.findByText("In the days when the judges governed")).toBeTruthy();
    expect(languageQaReference).toHaveBeenLastCalledWith("/p", "1", "D:/bibles/niv");
    expect(screen.getByRole("heading", { level: 2, name: "niv" })).toBeTruthy();
  });

  it("keeps Change beside a folder that is gone, named after the folder", async () => {
    languageQaReference.mockResolvedValue({ ready: false, configured: true, verses: [],
      source: { path: "E:\\gone\\esv", label: "esv", origin: "viewer" }, error: "E:\\gone\\esv: no such folder on this computer" });
    render(ReferencePanel, { props: { id: "reference3", folder: "E:\\gone\\esv\\" } });
    expect(await screen.findByText(/could not be read: E:\\gone\\esv: no such folder/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Change" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "esv" })).toBeTruthy();
  });

  it("the project's own tab still reads with no folder, and gives its name to the tab and the rail's list", async () => {
    languageQaReference.mockResolvedValue({ ...READY, source: { path: "x", label: "Old Version (bundled)", origin: "bundled" } });
    render(ReferencePanel);
    expect(await screen.findByText("Built in: Old Version")).toBeTruthy();
    expect(languageQaReference).toHaveBeenCalledWith("/p", "1");
    expect(get(projectReferenceName)).toBe("Built in: Old Version");
    // Another project: the name is not carried over.
    project.set({ path: "/q", bookId: "rut" } as never);
    expect(get(projectReferenceName)).toBe("");
  });
});

describe("RelatedWords", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the OV equivalents with counts and offers both occurrence lists", async () => {
    languageQaRelated.mockResolvedValue({
      word: "विरासत", ready: true, irv: 24, ov: 0, versesAligned: 31102,
      equivalents: [{ w: "मीरास", n: 18, source: "OV", ref: "ECC 7:11", irv: 0, ov: 19 }],
      family: [{ w: "विरासतें", irv: 1, ov: 0 }],
    });
    const onShowOccurrences = vi.fn();
    render(RelatedWords, { props: { projectPath: "/p", word: "विरासत", onShowOccurrences } });
    expect(await screen.findByText("मीरास")).toBeTruthy();
    expect(screen.getByText(/18× · OV · e.g. ECC 7:11/)).toBeTruthy();
    expect(screen.getByText(/This text uses it 24×; the reference 0×/)).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "Show OV occurrences" }));
    expect(onShowOccurrences).toHaveBeenCalledWith("विरासत", "ov");
  });

  it("says when it is turned off or has no reference to compare with", async () => {
    languageQaRelated.mockResolvedValueOnce({ word: "x", ready: false, off: true, equivalents: [], family: [] });
    const { unmount } = render(RelatedWords, { props: { projectPath: "/p", word: "x", onShowOccurrences: vi.fn() } });
    expect(await screen.findByText(/Turned off in Settings/)).toBeTruthy();
    unmount();
    languageQaRelated.mockResolvedValueOnce({ word: "x", ready: false, configured: false, equivalents: [], family: [] });
    render(RelatedWords, { props: { projectPath: "/p", word: "x", onShowOccurrences: vi.fn() } });
    expect(await screen.findByText(/No reference Bible is chosen for this project \(Reference panel › Browse\)/)).toBeTruthy();
  });
});
