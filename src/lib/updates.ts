import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { writable } from "svelte/store";

export interface UpdateStatus {
  phase: "idle" | "checking" | "downloading" | "available" | "ready" | "current" | "error" | "unavailable";
  version?: string | null;
  notes?: string | null;
  message: string;
}

export const updateStatus = writable<UpdateStatus>({ phase: "idle", message: "" });
const desktop = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
let timer: ReturnType<typeof setInterval> | undefined;
let automaticEnabled = true;
let disposed = false;
let unsubscribe: (() => void) | undefined;

/** This preference is persisted by settings.set in the existing workspace DB. */
export async function configureUpdates(enabled: boolean): Promise<void> {
  automaticEnabled = enabled;
  if (timer) clearInterval(timer);
  timer = undefined;
  if (!desktop() || disposed) return;
  await invoke("configure_updates", { enabled });
  if (enabled && !disposed && automaticEnabled) {
    void checkForUpdates(true, true);
    timer = setInterval(() => void checkForUpdates(true, true), 6 * 60 * 60 * 1000);
  }
}

export async function checkForUpdates(download = false, automatic = false): Promise<void> {
  if (!desktop()) {
    updateStatus.set({ phase: "unavailable", message: "Updates are available in the installed desktop app." });
    return;
  }
  try {
    await invoke("check_updates", { download, automatic });
    if (!disposed) updateStatus.set(await invoke<UpdateStatus>("update_status"));
  } catch (error) {
    // Native status includes a useful failure message; update failures never
    // reject startup or the editor's promise chain.
    console.warn("Bridge update check failed", error);
    if (!disposed) {
      try { updateStatus.set(await invoke<UpdateStatus>("update_status")); }
      catch { updateStatus.set({ phase: "error", message: "Could not check for updates. You can keep working and try again later." }); }
    }
  }
}

export async function startUpdates(enabled: boolean): Promise<void> {
  disposed = false;
  if (!desktop()) return;
  if (!unsubscribe) {
    const stop = await listen<UpdateStatus>("bridge-update", ({ payload }) => {
      if (!disposed) updateStatus.set(payload);
    });
    if (disposed) { stop(); return; }
    unsubscribe = stop;
  }
  await configureUpdates(enabled);
}

export function stopUpdates(): void {
  disposed = true;
  if (timer) clearInterval(timer);
  timer = undefined;
  unsubscribe?.();
  unsubscribe = undefined;
}
