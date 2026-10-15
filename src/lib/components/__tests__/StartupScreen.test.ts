import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

import StartupScreen from "../StartupScreen.svelte";
import type { EngineStartupStage } from "../../api/bridgeClient";

const stage = (seq: number, name: string, label: string): EngineStartupStage => ({
  seq, stage: name, label, tsMs: 1_700_000_000_000 + seq * 1000,
});

const paths = {
  logPath: "C:\\logs\\engine-events.log",
  dataDir: "C:\\Bridge\\data",
  resourceDir: "C:\\Bridge\\resources",
  exePath: "C:\\Bridge\\Bridge.exe",
};

describe("StartupScreen (#233)", () => {
  it("shows the wordmark, the version and the latest real stage while loading", () => {
    render(StartupScreen, {
      props: {
        version: "0.14.0",
        stages: [stage(1, "spawning", "Starting the engine process"), stage(2, "modules", "Loading engine modules")],
        failure: "",
        log: [],
        paths,
        onRetry: vi.fn(),
      },
    });
    expect(screen.getByText("Bridge")).toBeInTheDocument();
    expect(screen.getByTestId("startup-version")).toHaveTextContent("Version 0.14.0");
    expect(screen.getByTestId("startup-stage")).toHaveTextContent("Loading engine modules");
    const listed = screen.getByTestId("startup-stages").querySelectorAll("li");
    expect(Array.from(listed).map((li) => li.textContent)).toEqual([
      "Starting the engine process", "Loading engine modules",
    ]);
    expect(screen.queryByText("Retry")).not.toBeInTheDocument();
  });

  it("falls back to a plain status line before any stage has arrived", () => {
    render(StartupScreen, { props: { version: "", stages: [], failure: "", log: [], paths: null, onRetry: vi.fn() } });
    expect(screen.getByTestId("startup-stage")).toHaveTextContent("Starting Bridge");
    expect(screen.getByTestId("startup-version")).toHaveTextContent("");
  });

  it("on failure shows the message, Retry, the log behind Show details, and copies diagnostics", async () => {
    const onRetry = vi.fn();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(StartupScreen, {
      props: {
        version: "0.14.0",
        stages: [stage(1, "spawning", "Starting the engine process"), stage(2, "exited", "The engine process exited during startup (code 1)")],
        failure: "The engine process exited during startup (code 1)",
        log: [
          { ts_ms: 1_700_000_000_000, level: "info", message: "Sidecar started" },
          { ts_ms: 1_700_000_001_000, level: "error", message: "Sidecar process terminated: code 1" },
        ],
        paths,
        onRetry,
      },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Bridge could not start its engine.");
    expect(screen.getByTestId("startup-failure")).toHaveTextContent("The engine process exited during startup (code 1)");
    expect(screen.queryByTestId("startup-stage")).not.toBeInTheDocument();

    expect(screen.queryByTestId("startup-details")).not.toBeInTheDocument();
    await fireEvent.click(screen.getByText("Show details"));
    const details = screen.getByTestId("startup-details");
    expect(details).toHaveTextContent("Sidecar process terminated: code 1");
    // Newest first, like the diagnostics panel.
    expect(details.textContent?.indexOf("terminated")).toBeLessThan(details.textContent?.indexOf("Sidecar started") ?? -1);
    await fireEvent.click(screen.getByText("Hide details"));
    expect(screen.queryByTestId("startup-details")).not.toBeInTheDocument();

    await fireEvent.click(screen.getByText("Copy diagnostics"));
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const text = writeText.mock.calls[0][0] as string;
    expect(text).toContain("Version: 0.14.0");
    expect(text).toContain("Problem: The engine process exited during startup (code 1)");
    expect(text).toContain("Engine log: C:\\logs\\engine-events.log");
    expect(text).toContain("exited    The engine process exited during startup (code 1)");
    expect(text).toContain("ERROR Sidecar process terminated: code 1");
    await vi.waitFor(() => expect(screen.getByText("Copied")).toBeInTheDocument());

    await fireEvent.click(screen.getByText("Retry"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("falls back to the selection copy when the async clipboard is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, "execCommand", { value: execCommand, configurable: true });
    render(StartupScreen, {
      props: { version: "0.14.0", stages: [], failure: "The engine did not answer within 30 seconds.", log: [], paths: null, onRetry: vi.fn() },
    });
    await fireEvent.click(screen.getByText("Copy diagnostics"));
    await vi.waitFor(() => expect(execCommand).toHaveBeenCalledWith("copy"));
    await vi.waitFor(() => expect(screen.getByText("Copied")).toBeInTheDocument());
  });
});
