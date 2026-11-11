<script lang="ts">
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  export let icon: string;
  export let label: string;
  export let disabled = false;
  export let pressed: boolean | undefined = undefined;
</script>

<button type="button" class="icon-button" aria-label={label} aria-pressed={pressed}
  {disabled} use:tooltip={label} on:click on:keydown on:pointerdown><UiIcon name={icon} /></button>

<style>
  .icon-button { display: inline-flex; align-items: center; justify-content: center; flex: none;
    width: 28px; height: 28px; padding: 4px; border: 1px solid transparent; border-radius: 5px;
    background: transparent; color: var(--text-2); cursor: pointer; }
  .icon-button:hover:not(:disabled), .icon-button[aria-pressed="true"] { background: var(--surface-3, #e5e7eb); border-color: var(--border-strong); }
  .icon-button:focus-visible { outline: 2px solid var(--text-2); outline-offset: 1px; }
  .icon-button:disabled { opacity: .4; cursor: default; }
</style>
