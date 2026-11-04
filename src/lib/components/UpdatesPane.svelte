<script lang="ts">
  import { bridge } from "../api/bridgeClient";
  import { checkForUpdates, configureUpdates, updateStatus } from "../updates";

  export let enabled = true;
  let saving = false;
  let error = "";
  $: busy = $updateStatus.phase === "checking" || $updateStatus.phase === "downloading";

  async function toggle(next: boolean): Promise<void> {
    saving = true;
    error = "";
    try {
      const settings = await bridge.setSettings({ automaticUpdates: next });
      enabled = settings.automaticUpdates ?? true;
      await configureUpdates(enabled);
    } catch (e) {
      error = `Could not change automatic updates: ${String(e)}`;
    } finally {
      saving = false;
    }
  }
</script>

<h3>App updates</h3>
<label>
  <input type="checkbox" checked={enabled} disabled={saving} on:change={(e) => toggle(e.currentTarget.checked)} />
  Automatically update Bridge
</label>
<p>Enabled by default. Bridge checks GitHub Releases in the background and downloads signed updates.
  Downloaded updates install when you close Bridge. Save your work before closing.</p>
<p>You can continue working without an internet connection. Automatic update checks run at startup and every six hours.</p>
<button on:click={() => checkForUpdates()} disabled={busy || saving}>Check for updates</button>
{#if $updateStatus.phase === "available"}
  <button on:click={() => checkForUpdates(true)} disabled={busy || saving}>Download and install when Bridge closes</button>
{/if}
{#if $updateStatus.version}<p>Version {$updateStatus.version}</p>{/if}
<p role="status">{$updateStatus.message}</p>
{#if $updateStatus.notes}
  <details><summary>Release notes</summary><pre>{$updateStatus.notes}</pre></details>
{/if}
{#if error}<p role="alert">{error}</p>{/if}

<style>
  h3 { margin: 0 0 18px; }
  label { display: flex; align-items: center; gap: 8px; font-weight: 600; }
  p { color: #4b5563; line-height: 1.5; }
  button { padding: 8px 12px; margin: 4px 8px 4px 0; border: 1px solid #d1d5db; border-radius: 6px; background: white; cursor: pointer; }
  button:disabled { opacity: .6; cursor: default; }
  pre { white-space: pre-wrap; font: inherit; }
</style>
