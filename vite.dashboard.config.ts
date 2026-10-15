import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { resolve } from "node:path";

/** The team dashboard (#81): a second, browser-only entry the hub serves at
 *  "/" (`bridge-engine --serve`). It shares nothing with Tauri at runtime and
 *  builds into `dist-dashboard/`, which `bridge_server.default_dashboard_dir`
 *  finds beside the engine. */
export default defineConfig({
  root: resolve(__dirname, "dashboard"),
  base: "./",
  // The root is dashboard/, so the repo's Svelte config (TypeScript preprocessing)
  // has to be named explicitly.
  plugins: [svelte({ configFile: resolve(__dirname, "svelte.config.js") })],
  build: {
    outDir: resolve(__dirname, "dist-dashboard"),
    emptyOutDir: true,
  },
});
