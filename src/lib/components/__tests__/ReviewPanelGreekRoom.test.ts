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
import { checkGroupsByVerse, currentChapter, findingsByVerse, project, selectedVerse } from "../../stores";

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
