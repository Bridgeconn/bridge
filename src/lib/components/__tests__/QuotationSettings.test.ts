import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const { getRules, setRules, nudge } = vi.hoisted(() => ({ getRules: vi.fn(), setRules: vi.fn(), nudge: vi.fn() }));
vi.mock("../../api/bridgeClient", () => ({ bridge: { languageQaQuotationRulesGet: getRules, languageQaQuotationRulesSet: setRules } }));
vi.mock("../../languageQaInline", () => ({ nudgeLanguageQa: nudge }));
import QuotationSettings from "../QuotationSettings.svelte";

const defaults = { version: 1, enabled: true, referenceEnabled: true,
  target: { pairs: [{ open: "“", close: "”" }, { open: "‘", close: "’" }], continuation: "repeat-opening" },
  reference: { pairs: [{ open: "“", close: "”" }, { open: "‘", close: "’" }], continuation: "repeat-opening" } };
beforeEach(() => {
  vi.clearAllMocks();
  getRules.mockResolvedValue({ rules: structuredClone(defaults), defaults, scope: "collection", books: ["mat", "mrk"] });
  setRules.mockImplementation(async (_path, rules) => ({ rules, defaults, scope: "collection", books: ["mat", "mrk"] }));
});
afterEach(cleanup);

it("saves target rules separately from reference conventions and refreshes QA", async () => {
  render(QuotationSettings, { projectPath: "C:/project" });
  const opening = await screen.findByLabelText("target level 1 opening");
  expect(screen.getByText(/Saved for this collection/)).toBeTruthy();
  await fireEvent.input(opening, { target: { value: "«" } });
  await fireEvent.input(screen.getByLabelText("target level 1 closing"), { target: { value: "»" } });
  expect(screen.getByText("Preview: «‘quotation’»")).toBeTruthy();
  await fireEvent.click(screen.getByRole("button", { name: "Save quotation rules" }));
  await waitFor(() => expect(setRules).toHaveBeenCalled());
  expect(setRules.mock.calls[0][1].reference).toEqual(defaults.reference);
  expect(nudge).toHaveBeenCalledOnce();
});

it("restores English defaults only when the user saves", async () => {
  render(QuotationSettings, { projectPath: "C:/project" });
  await screen.findByLabelText("target level 1 opening");
  await fireEvent.input(screen.getByLabelText("target level 1 opening"), { target: { value: "«" } });
  await fireEvent.click(screen.getByRole("button", { name: "Restore English defaults" }));
  expect((screen.getByLabelText("target level 1 opening") as HTMLInputElement).value).toBe("“");
  expect(setRules).not.toHaveBeenCalled();
});

it("shows validation errors without reporting a successful save", async () => {
  setRules.mockRejectedValue(new Error("quotation pairs overlap"));
  render(QuotationSettings, { projectPath: "C:/project" });
  await screen.findByLabelText("target level 1 opening");
  await fireEvent.click(screen.getByRole("button", { name: "Save quotation rules" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("quotation pairs overlap");
  expect(nudge).not.toHaveBeenCalled();
});
