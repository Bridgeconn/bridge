import { describe, expect, it } from "vitest";

import { STARTUP_TIMEOUT_MS, buildDiagnosticsText, currentStageLabel, mergeStage, startupProgress } from "../startup";
import type { EngineStartupStage } from "../api/bridgeClient";

const stage = (seq: number, name: string, label: string): EngineStartupStage => ({
  seq, stage: name, label, tsMs: 1_700_000_000_000 + seq * 1000,
});

describe("startup stages (#233)", () => {
  it("merges a stage seen both from the catch-up call and as an event once, ordered by seq", () => {
    const fromEvent = stage(3, "modules", "Loading engine modules");
    let stages = mergeStage([], fromEvent);
    stages = mergeStage(stages, stage(1, "spawning", "Starting the engine process"));
    stages = mergeStage(stages, stage(2, "spawned", "Engine process started, loading Python"));
    stages = mergeStage(stages, { ...fromEvent });
    expect(stages.map((s) => s.seq)).toEqual([1, 2, 3]);
  });

  it("uses the latest stage's own label as the status line, with a fallback before any arrives", () => {
    expect(currentStageLabel([])).toBe("Starting Bridge");
    expect(currentStageLabel([stage(1, "spawning", "Starting the engine process"), stage(2, "engine", "Starting the engine")]))
      .toBe("Starting the engine");
  });

  it("positions the splash progress track by the furthest known stage, ignoring names it does not know", () => {
    expect(startupProgress([])).toBe(0);
    expect(startupProgress([stage(1, "spawning", "Starting the engine process")])).toBeCloseTo(0.2);
    expect(startupProgress([stage(1, "spawning", "Starting"), stage(3, "modules", "Loading engine modules")])).toBeCloseTo(0.6);
    expect(startupProgress([stage(3, "modules", "Loading"), stage(4, "failed", "The engine process exited")])).toBeCloseTo(0.6);
    expect(startupProgress([stage(5, "ready", "Engine ready")])).toBe(1);
  });

  it("gives the engine 30 seconds, the same as the ping request timeout", () => {
    expect(STARTUP_TIMEOUT_MS).toBe(30_000);
  });

  it("builds a diagnostics text with the version, problem, paths, stages and the log tail", () => {
    const text = buildDiagnosticsText({
      version: "0.14.0",
      platform: "Win32",
      userAgent: "Mozilla/5.0 Edg/130",
      failure: "The engine process exited during startup (code 1)",
      paths: {
        logPath: "C:\\Users\\me\\AppData\\Local\\org.translationcore.aibridge\\logs\\engine-events.log",
        dataDir: "C:\\Users\\me\\AppData\\Local\\Bridge\\data",
        resourceDir: "C:\\Program Files\\Bridge\\resources",
        exePath: "C:\\Program Files\\Bridge\\Bridge.exe",
      },
      stages: [stage(1, "spawning", "Starting the engine process"), stage(2, "exited", "The engine process exited during startup (code 1)")],
      log: [
        { ts_ms: 1_700_000_000_000, level: "info", message: "Sidecar started" },
        { ts_ms: 1_700_000_001_000, level: "error", message: "Sidecar process terminated: code 1" },
      ],
      capturedAt: new Date("2026-10-12T10:00:00Z"),
    });
    expect(text).toContain("Version: 0.14.0");
    expect(text).toContain("Captured: 2026-10-12T10:00:00.000Z");
    expect(text).toContain("Platform: Win32");
    expect(text).toContain("Problem: The engine process exited during startup (code 1)");
    expect(text).toContain("Engine log: C:\\Users\\me\\AppData\\Local\\org.translationcore.aibridge\\logs\\engine-events.log");
    expect(text).toContain("Data: C:\\Users\\me\\AppData\\Local\\Bridge\\data");
    expect(text).toContain("spawning  Starting the engine process");
    expect(text).toContain("Engine log (last 2 of 2)");
    expect(text).toContain("ERROR Sidecar process terminated: code 1");
    expect(text.endsWith("\n")).toBe(true);
  });

  it("says so when the shell never answered for the paths, and keeps only the log's tail", () => {
    const log = Array.from({ length: 250 }, (_, i) => ({ ts_ms: i, level: "info" as const, message: `entry ${i}` }));
    const text = buildDiagnosticsText({
      version: "", platform: "", userAgent: "", failure: "", paths: null, stages: [], log,
      capturedAt: new Date(0),
    });
    expect(text).toContain("Version: unknown");
    expect(text).toContain("Problem: none reported");
    expect(text).toContain("(not available: the shell did not answer engine_startup_state)");
    expect(text).toContain("(none reported)");
    expect(text).toContain("Engine log (last 200 of 250)");
    expect(text).not.toContain("entry 49\n");
    expect(text).toContain("entry 249");
  });
});
