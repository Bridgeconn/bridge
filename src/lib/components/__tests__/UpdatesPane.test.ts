import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";

const { setSettings, configureUpdates, checkForUpdates } = vi.hoisted(() => ({ setSettings: vi.fn(), configureUpdates: vi.fn(), checkForUpdates: vi.fn() }));
vi.mock("../../api/bridgeClient", () => ({ bridge: { setSettings } }));
vi.mock("../../updates", () => ({ configureUpdates, checkForUpdates, updateStatus: writable({ phase: "available", version: "1.2.3", message: "An update is available." }) }));
import UpdatesPane from "../UpdatesPane.svelte";

beforeEach(() => {
  vi.clearAllMocks();
  setSettings.mockImplementation(async ({ automaticUpdates }) => ({ automaticUpdates }));
  configureUpdates.mockResolvedValue(undefined);
});

it("defaults on and persists an immediate opt out", async () => {
  render(UpdatesPane);
  const toggle = screen.getByRole("checkbox", { name: "Automatically update Bridge" });
  expect(toggle).toBeChecked();
  await fireEvent.click(toggle);
  await waitFor(() => expect(configureUpdates).toHaveBeenCalledWith(false));
  expect(setSettings).toHaveBeenCalledWith({ automaticUpdates: false });
  expect(toggle).not.toBeChecked();
});

it("offers manual checks and explicit downloading when automatic updates are off", async () => {
  render(UpdatesPane, { enabled: false });
  await fireEvent.click(screen.getByRole("button", { name: "Check for updates" }));
  expect(checkForUpdates).toHaveBeenCalledWith();
  await fireEvent.click(screen.getByRole("button", { name: "Download and install when Bridge closes" }));
  expect(checkForUpdates).toHaveBeenCalledWith(true);
});
