import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

// #252: Greek Room no longer runs when a verse is selected (it did, live, on
// every selection); the Review panel's Greek Room tab runs it on demand.
const { runVerseChecks, known } = vi.hoisted(() => ({
  runVerseChecks: vi.fn(),
  known: {} as Record<string, unknown>,
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: new Proxy(known, {
    get: (target, name: string) => {
      if (name === "runVerseChecks") return runVerseChecks;
      if (!(name in target)) target[name] = vi.fn().mockResolvedValue({ items: [], findings: [], hidden: [] });
      return target[name];
    },
  }),
}));

import ReviewPanel from "../ReviewPanel.svelte";
import { chapterVerseNums, checkGroupsByVerse, currentChapter, findingsByVerse, project, selectedVerse } from "../../stores";

describe("ReviewPanel Greek Room tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set({ path: "/p", bookId: "php" } as never);
    currentChapter.set("1");
    findingsByVerse.set({});
    checkGroupsByVerse.set({});
    runVerseChecks.mockResolvedValue([{ id: "w1", engine: "wildebeest", check: "wildebeest", status: "open",
      severity: "medium", category: "unicode", check_type: "wildebeest.x", explanation: "Mixed script", evidence: [] }]);
  });

  afterEach(() => selectedVerse.set(null));

  it("selecting verses runs nothing; the button runs Greek Room on the verse", async () => {
    render(ReviewPanel);
    selectedVerse.set("1");
    selectedVerse.set("2");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(runVerseChecks).not.toHaveBeenCalled();
    expect(screen.getByText(/Not run on this verse yet/)).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("button", { name: "Run Greek Room on this verse" }));
    await waitFor(() => expect(runVerseChecks).toHaveBeenCalledWith("1", "2", ["greekroom"]));
    expect(await screen.findByText("Mixed script")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Greek Room again" })).toBeInTheDocument();
  });

  it("shows an earlier decision recorded under another id, without applying it (#273)", async () => {
    findingsByVerse.set({ "1:3": [{ id: "w2", engine: "wildebeest", check: "wildebeest", status: "open",
      severity: "medium", category: "unicode", check_type: "wildebeest.x", explanation: "Mixed script", evidence: [],
      unmatched_decision: { decision: "ignored", note: "", decidedAt: null, findingId: "old" } } as never] });
    render(ReviewPanel);
    selectedVerse.set("3");
    expect(await screen.findByText(/An earlier decision on this item \(ignored\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Ignore/ })).toBeInTheDocument();
  });
});

describe("ReviewPanel Greek Room landing (#202)", () => {
  const finding = (id: string, engine = "wildebeest") => ({ id, engine, check: engine, status: "open",
    severity: "medium", category: "unicode", check_type: "wildebeest.zero_width",
    explanation: "Contains a zero-width/invisible character: ZERO WIDTH SPACE.", evidence: [] }) as never;

  beforeEach(() => {
    vi.clearAllMocks();
    project.set({ path: "/p", bookId: "tst" } as never);
    currentChapter.set("1");
    chapterVerseNums.set({ "1": ["1", "2", "3"] });
    findingsByVerse.set({});
    checkGroupsByVerse.set({});
    runVerseChecks.mockResolvedValue([finding("zw-2")]);
  });

  afterEach(() => selectedVerse.set(null));

  function activeTab(): string {
    return (document.querySelector('[role="tab"][aria-selected="true"]') as HTMLElement).textContent?.trim() ?? "";
  }

  it("comes back to the Greek Room tab when the verse's run finishes while another tab is up", async () => {
    let finish: (value: unknown) => void = () => undefined;
    runVerseChecks.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    render(ReviewPanel);
    selectedVerse.set("2");
    await fireEvent.click(await screen.findByRole("button", { name: "Run Greek Room on this verse" }));
    await fireEvent.click(screen.getByRole("tab", { name: /Language QA/ }));
    expect(activeTab()).toMatch(/^Language QA/);
    finish([finding("zw-2")]);
    await waitFor(() => expect(activeTab()).toMatch(/^Greek Room/));
    expect(await screen.findByText(/ZERO WIDTH SPACE/)).toBeInTheDocument();
  });

  it("switches when a chapter job writes the selected verse's result, and not on selecting a verse that ran earlier", async () => {
    checkGroupsByVerse.set({ "1:1": ["wildebeest"] });
    findingsByVerse.set({ "1:1": [finding("zw-1")] });
    render(ReviewPanel);
    selectedVerse.set("2");
    await fireEvent.click(await screen.findByRole("tab", { name: /Language QA/ }));
    // Selecting verse 1, which ran earlier, leaves the reader on their tab.
    selectedVerse.set("1");
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(activeTab()).toMatch(/^Language QA/);
    // Back on verse 2, a chapter job lands its result: the Greek Room tab opens.
    selectedVerse.set("2");
    await new Promise((resolve) => setTimeout(resolve, 10));
    findingsByVerse.update((all) => ({ ...all, "1:2": [finding("zw-2")] }));
    checkGroupsByVerse.update((all) => ({ ...all, "1:2": ["wildebeest"] }));
    await waitFor(() => expect(activeTab()).toMatch(/^Greek Room/));
  });

  it("states the chapter's result under the run button", async () => {
    render(ReviewPanel);
    selectedVerse.set("3");
    expect((await screen.findByTestId("greek-room-chapter-summary")).textContent).toMatch(/not run in this chapter/);
    findingsByVerse.set({ "1:1": [finding("zw-1")], "1:2": [finding("zw-2"), finding("tn-2", "local")] });
    checkGroupsByVerse.set({ "1:1": ["wildebeest"], "1:2": ["wildebeest"] });
    await waitFor(() => expect(screen.getByTestId("greek-room-chapter-summary").textContent?.replace(/\s+/g, " "))
      .toMatch(/Greek Room: 2 open in this chapter · 2 of 3 verses checked/));
  });
});
