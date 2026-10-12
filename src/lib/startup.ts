/**
 * The startup loading screen's logic (#233), kept out of the component so it
 * is testable without a DOM: merging the shell's stage events with the
 * catch-up state, the status line, the 30 s rule, and the diagnostics text
 * that "Copy diagnostics" puts on the clipboard.
 */
import type { EngineLogEntry, EngineStartupStage } from "./api/bridgeClient";

/** After this long without the engine's first answer the loading screen
 * shows the failure view. Matches the Rust request timeout for `ping`. */
export const STARTUP_TIMEOUT_MS = 30_000;

export interface StartupPaths {
  logPath: string;
  dataDir: string;
  resourceDir: string;
  exePath: string;
}

/** A stage can arrive twice: from `engineStartupState()` and as an
 * `engine-stage` event fired between the listener and that call. The shell's
 * `seq` makes them the same stage; order is by `seq`, never by arrival. */
export function mergeStage(stages: EngineStartupStage[], stage: EngineStartupStage): EngineStartupStage[] {
  if (stages.some((known) => known.seq === stage.seq)) return stages;
  return [...stages, stage].sort((a, b) => a.seq - b.seq);
}

/** The status line: the latest stage's own label, never an invented one. */
export function currentStageLabel(stages: EngineStartupStage[], fallback = "Starting Bridge"): string {
  const last = stages[stages.length - 1];
  return last ? last.label : fallback;
}

function clock(tsMs: number): string {
  const date = new Date(tsMs);
  const pad = (n: number, width = 2) => String(n).padStart(width, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
}

/** Plain text a maintainer can read from an email: version, platform, the
 * problem, where the files are, the stages with their times, and the engine
 * log's tail. Deterministic for a given input, so it is testable. */
export function buildDiagnosticsText(input: {
  version: string;
  platform: string;
  userAgent: string;
  failure: string;
  paths: StartupPaths | null;
  stages: EngineStartupStage[];
  log: EngineLogEntry[];
  capturedAt: Date;
  logLimit?: number;
}): string {
  const lines: string[] = [];
  lines.push("Bridge startup diagnostics");
  lines.push(`Version: ${input.version || "unknown"}`);
  lines.push(`Captured: ${input.capturedAt.toISOString()}`);
  lines.push(`Platform: ${input.platform || "unknown"}`);
  lines.push(`Browser engine: ${input.userAgent || "unknown"}`);
  lines.push(`Problem: ${input.failure || "none reported"}`);
  lines.push("");
  lines.push("Paths");
  if (input.paths) {
    lines.push(`  App: ${input.paths.exePath || "unknown"}`);
    lines.push(`  Engine log: ${input.paths.logPath || "unknown"}`);
    lines.push(`  Data: ${input.paths.dataDir || "unknown"}`);
    lines.push(`  Resources: ${input.paths.resourceDir || "unknown"}`);
  } else {
    lines.push("  (not available: the shell did not answer engine_startup_state)");
  }
  lines.push("");
  lines.push("Startup stages");
  if (input.stages.length === 0) lines.push("  (none reported)");
  for (const stage of input.stages) {
    lines.push(`  ${clock(stage.tsMs)}  ${stage.stage.padEnd(9)} ${stage.label}`);
  }
  lines.push("");
  const limit = input.logLimit ?? 200;
  const tail = input.log.slice(Math.max(0, input.log.length - limit));
  lines.push(`Engine log (last ${tail.length} of ${input.log.length})`);
  if (tail.length === 0) lines.push("  (empty)");
  for (const entry of tail) {
    lines.push(`  ${clock(entry.ts_ms)}  ${entry.level.toUpperCase().padEnd(5)} ${entry.message}`);
  }
  return lines.join("\n") + "\n";
}

/** Clipboard write that works in the Tauri webview without a plugin: the
 * async API where the page is a secure context (it is, on tauri.localhost),
 * the selection-and-copy fallback otherwise. Returns whether it worked. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the selection path.
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand("copy");
    area.remove();
    return copied;
  } catch {
    return false;
  }
}
