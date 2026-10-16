import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";

import type { EngineStartupStage } from "../../api/bridgeClient";

const stage = (seq: number, name: string, label: string): EngineStartupStage => ({
  seq, stage: name, label, tsMs: 1_700_000_000_000 + seq * 1000,
});

const { onEngineStage, engineStartupState, emit } = vi.hoisted(() => {
  const listeners: Array<(stage: EngineStartupStage) => void> = [];
  return {
    onEngineStage: vi.fn(async (handler: (stage: EngineStartupStage) => void) => {
      listeners.push(handler);
      return () => {};
    }),
    engineStartupState: vi.fn(),
    emit: (stage: EngineStartupStage) => listeners[listeners.length - 1]?.(stage),
  };
});

vi.mock("../../api/bridgeClient", () => ({
  bridge: { onEngineStage, engineStartupState },
}));

import SplashScreen from "../SplashScreen.svelte";

describe("SplashScreen (#287)", () => {
  it("shows the version and the latest stage, the catch-up and live events merged by seq", async () => {
    engineStartupState.mockResolvedValue({
      version: "0.18.0", ready: false, failed: null,
      stages: [stage(1, "spawning", "Starting the engine process"), stage(2, "spawned", "Engine process started, loading Python")],
    });
    render(SplashScreen);

    await waitFor(() => expect(screen.getByTestId("splash-version")).toHaveTextContent("Version 0.18.0"));
    expect(screen.getByTestId("splash-stage")).toHaveTextContent("Engine process started, loading Python");

    emit(stage(2, "spawned", "Engine process started, loading Python")); // seen both ways: counted once
    emit(stage(3, "modules", "Loading engine modules"));
    await waitFor(() => expect(screen.getByTestId("splash-stage")).toHaveTextContent("Loading engine modules"));
  });

  it("shows a plain status line when the shell has reported nothing", async () => {
    engineStartupState.mockRejectedValue(new Error("no shell"));
    render(SplashScreen);
    await waitFor(() => expect(engineStartupState).toHaveBeenCalled());
    expect(screen.getByTestId("splash-stage")).toHaveTextContent("Starting Bridge");
    expect(screen.getByTestId("splash-version")).toHaveTextContent("");
  });

  it("can be dragged by its body: the window has no title bar", () => {
    engineStartupState.mockResolvedValue({ version: "", ready: false, failed: null, stages: [] });
    render(SplashScreen);
    expect(screen.getByTestId("splash-screen")).toHaveAttribute("data-tauri-drag-region");
  });
});
