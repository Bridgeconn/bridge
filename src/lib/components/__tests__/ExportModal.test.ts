import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

const { pickSavePath, exportAligned, exportNonAligned } = vi.hoisted(() => ({
  pickSavePath: vi.fn(), exportAligned: vi.fn(), exportNonAligned: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({ bridge: { pickSavePath, exportAligned, exportNonAligned } }));

import ExportModal from "../ExportModal.svelte";

describe("ExportModal publication gate (layered-rules 4.5)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pickSavePath.mockResolvedValue("/out/rut.usfm");
    exportNonAligned
      .mockResolvedValueOnce({ written: false, blocked: true, path: "/out/rut.usfm", gate: {
        blocking: true, counts: { languageQa: 1 },
        items: [{ source: "languageQa", reference: "1:1", summary: "project/terminology.deprecated-form: தேவன்" }] } })
      .mockResolvedValueOnce({ written: true, path: "/out/rut.usfm", chapters: 4, overridden: true });
  });

  it("shows what blocks, exports only after the override is ticked, and says it was recorded", async () => {
    render(ExportModal, { props: { onClose: vi.fn() } });
    await fireEvent.click(screen.getByText("Non-aligned USFM"));
    expect(await screen.findByText(/Not exported: 1 item\(s\) block publication/)).toBeInTheDocument();
    expect(screen.getByText(/terminology.deprecated-form: தேவன்/)).toBeInTheDocument();
    const anyway = screen.getByRole("button", { name: "Export anyway" });
    expect(anyway).toBeDisabled();
    await fireEvent.click(screen.getByRole("checkbox"));
    await fireEvent.click(anyway);
    expect(exportNonAligned).toHaveBeenLastCalledWith("/out/rut.usfm", true);
    expect(await screen.findByText(/override is recorded/)).toBeInTheDocument();
    expect(pickSavePath).toHaveBeenCalledTimes(1);  // the override reuses the chosen path
  });
});

describe("ExportModal Escape (#321)", () => {
  it("closes on Escape, as Close does, and returns focus to the invoker", async () => {
    const opener = document.createElement("button");
    opener.textContent = "Export";
    document.body.appendChild(opener);
    opener.focus();
    const onClose = vi.fn();
    const { unmount } = render(ExportModal, { props: { onClose } });
    await fireEvent.keyDown(window, { key: "Enter" });
    expect(onClose).not.toHaveBeenCalled();
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
    unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});

describe("ExportModal aligned export with lettered segments (#307)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pickSavePath.mockResolvedValue("/out/jon-aligned.usfm");
  });

  it("says which verses were written without alignment", async () => {
    exportAligned.mockResolvedValueOnce({ written: true, path: "/out/jon-aligned.usfm", chapters: 1,
      unalignedVerses: ["5a", "5b"].map((verse) => ({ reference: `1:${verse}`, chapter: "1", verse,
        reason: "no-source-tokens", detail: "No original-language source tokens" })) });
    render(ExportModal, { props: { onClose: vi.fn() } });
    await fireEvent.click(screen.getByText("Aligned USFM 3"));
    expect(await screen.findByText(/Wrote 1 chapter\(s\)/)).toBeInTheDocument();
    expect(screen.getByText("2 verse(s) written without alignment (no original-language source): 1:5a, 1:5b"))
      .toBeInTheDocument();
  });

  it("names a verse whose alignment data could not be written apart from the no-source ones (#339)", async () => {
    exportAligned.mockResolvedValueOnce({ written: true, path: "/out/jon-aligned.usfm", chapters: 1,
      unalignedVerses: [
        { reference: "1:5a", chapter: "1", verse: "5a", reason: "no-source-tokens", detail: "No source tokens" },
        { reference: "1:2", chapter: "1", verse: "2", reason: "alignment-not-serializable",
          detail: "Alignment target tokens do not exactly match the current verse text." },
      ] });
    render(ExportModal, { props: { onClose: vi.fn() } });
    await fireEvent.click(screen.getByText("Aligned USFM 3"));
    expect(await screen.findByText(/Wrote 1 chapter\(s\)/)).toBeInTheDocument();
    expect(screen.getByText(/1 verse\(s\) written without alignment \(no original-language source\): 1:5a/)).toBeInTheDocument();
    expect(screen.getByText(/1 verse\(s\) written without alignment \(alignment data could not be written; recheck the verse in Align Words\): 1:2/)).toBeInTheDocument();
  });

  it("adds no line when every verse could carry alignment", async () => {
    exportAligned.mockResolvedValueOnce({ written: true, path: "/out/jon-aligned.usfm", chapters: 1, unalignedVerses: [] });
    render(ExportModal, { props: { onClose: vi.fn() } });
    await fireEvent.click(screen.getByText("Aligned USFM 3"));
    expect(await screen.findByText(/Wrote 1 chapter\(s\)/)).toBeInTheDocument();
    expect(screen.queryByText(/written without alignment/)).not.toBeInTheDocument();
  });
});
