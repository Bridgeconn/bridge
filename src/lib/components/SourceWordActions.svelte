<script lang="ts">
  import type { AlignmentToken } from "../types/finding";
  export let token: AlignmentToken;
  export let disabled = false;
  export let onSeparate: (direction: "left" | "right") => void;
  let menu: HTMLDetailsElement;
</script>
<details bind:this={menu} class="word-actions">
  <summary aria-label={`Separate ${token.word} (${token.occurrence}/${token.occurrences})`} title={`Separate this word from its group: ${token.word}`}>&#x2194;</summary>
  <div class="choices">
    <button type="button" {disabled} aria-label={`Separate ${token.word} left`} on:click|stopPropagation={() => { menu.open = false; onSeparate("left"); }}>&#x2190; Separate left</button>
    <button type="button" {disabled} aria-label={`Separate ${token.word} right`} on:click|stopPropagation={() => { menu.open = false; onSeparate("right"); }}>Separate right &#x2192;</button>
  </div>
</details>
<style>
  .word-actions { position: absolute; inset-inline-end: 2px; top: 1px; direction: ltr; font-family: var(--font-ui); }
  summary { list-style: none; cursor: pointer; color: var(--accent); background: var(--surface); border: 1px solid var(--border); border-radius: 3px; padding: 0 2px; font-size: 11px; line-height: 15px; }
  summary::-webkit-details-marker { display: none; }
  .choices { position: absolute; inset-inline-end: 0; top: 18px; display: flex; flex-direction: column; background: var(--surface); padding: 4px; border: 1px solid var(--border-strong); border-radius: 5px; box-shadow: 0 3px 12px #0003; min-width: 132px; }
  button { font: inherit; font-size: var(--fs-xs); color: var(--text); background: var(--surface); border: 0; padding: 5px; white-space: nowrap; cursor: pointer; }
  button:hover:not(:disabled) { background: var(--accent-bg); }
  button:disabled { opacity: .5; cursor: default; }
</style>
