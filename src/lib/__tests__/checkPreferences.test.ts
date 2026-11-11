import { afterEach, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const key = "bridge.editor.checks.v1";
afterEach(() => { localStorage.removeItem(key); vi.resetModules(); });

it("starts a new profile with Language QA only", async () => {
  localStorage.removeItem(key); vi.resetModules();
  const { editorChecks } = await import("../editorPrefs");
  expect(get(editorChecks)).toEqual(["languageQa"]);
});

it("keeps the user's saved selection when a new app session initializes", async () => {
  localStorage.setItem(key, JSON.stringify(["tW", "alignment", "greekroom"]));
  vi.resetModules();
  const first = await import("../editorPrefs");
  expect(get(first.editorChecks)).toEqual(["tW", "alignment", "greekroom"]);
  first.editorChecks.set(["text", "languageQa"]);
  vi.resetModules();
  const reopened = await import("../editorPrefs");
  expect(get(reopened.editorChecks)).toEqual(["text", "languageQa"]);
});
