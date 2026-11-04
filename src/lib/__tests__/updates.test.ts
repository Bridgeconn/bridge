import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const { invoke, listen, stop } = vi.hoisted(() => ({ invoke: vi.fn(), listen: vi.fn(), stop: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
import { checkForUpdates, configureUpdates, startUpdates, stopUpdates, updateStatus } from "../updates";

describe("optional background app updates", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true });
    listen.mockResolvedValue(stop);
    invoke.mockImplementation(async (command: string) => command === "update_status" ? { phase: "current", message: "Up to date" } : undefined);
  });
  afterEach(() => { stopUpdates(); vi.useRealTimers(); delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__; });

  it("automatically downloads at startup and every six hours, and stops on opt out", async () => {
    await startUpdates(true);
    expect(invoke).toHaveBeenCalledWith("check_updates", { download: true, automatic: true });
    await vi.advanceTimersByTimeAsync(6 * 60 * 60 * 1000);
    expect(invoke.mock.calls.filter(([name]) => name === "check_updates")).toHaveLength(2);
    await configureUpdates(false);
    await vi.advanceTimersByTimeAsync(12 * 60 * 60 * 1000);
    expect(invoke.mock.calls.filter(([name]) => name === "check_updates")).toHaveLength(2);
    expect(invoke).toHaveBeenCalledWith("configure_updates", { enabled: false });
  });

  it("never checks automatically when disabled, but allows a manual check", async () => {
    await startUpdates(false);
    expect(invoke).not.toHaveBeenCalledWith("check_updates", expect.anything());
    await checkForUpdates();
    expect(invoke).toHaveBeenCalledWith("check_updates", { download: false, automatic: false });
  });

  it("does not call native commands in the browser", async () => {
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
    await startUpdates(true);
    await checkForUpdates();
    expect(invoke).not.toHaveBeenCalled();
    expect(get(updateStatus).phase).toBe("unavailable");
  });

  it("leaves startup usable when the update request fails", async () => {
    await startUpdates(false);
    invoke.mockRejectedValueOnce(new Error("offline"));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    await expect(checkForUpdates()).resolves.toBeUndefined();
    warn.mockRestore();
  });
});
