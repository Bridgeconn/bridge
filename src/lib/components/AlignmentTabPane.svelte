<script lang="ts">
  /** The editor's two alignment tabs (2026-11-15, Joel): "Word alignment",
   *  the editor of one verse, and "Cross-verse", the cross-verse page. Each is
   *  drawn in its own tab group's frame like any other pane, so the two split,
   *  drag and resize apart and can be open side by side. They were one dialog
   *  over the whole window, then one tab that held either. AlignmentHost
   *  decides the verse (`alignmentPane`); this only draws it. Behind another
   *  tab a pane stays mounted, hidden, so the work in it is kept. */
  import { getContext } from "svelte";
  import type { EditorDockContext } from "../editorDocking";
  import { alignmentPane, closeCrossVerse, closeWordAlignment, crossVerseInitialVerses, detachAlignment } from "../alignmentUi";
  import { paneStyle, visibleTabs } from "../editorTabs";
  import AlignmentModal from "./AlignmentModal.svelte";
  import CrossVerseAlignmentModal from "./CrossVerseAlignmentModal.svelte";

  const docking = getContext<EditorDockContext | undefined>("editor-docking");
  const frames = docking?.frames;
  $: wordFrame = frames ? $frames?.alignment : undefined;
  $: crossFrame = frames ? $frames?.crossVerse : undefined;
  $: pane = $alignmentPane;
</script>

{#if pane?.word}
  <section data-editor-pane="alignment" id="editor-alignment-pane" class="alignment-pane" aria-label="Word alignment"
    hidden={!$visibleTabs.has("alignment")} style={paneStyle(wordFrame)}>
    {#key `${pane.path}:${pane.chapter}:${pane.verse}`}
      <AlignmentModal embedded chapter={pane.chapter} verse={pane.verse} onClose={closeWordAlignment}
        onDetach={pane.canDetach ? () => detachAlignment("word") : null} />
    {/key}
  </section>
{/if}
{#if pane?.cross}
  <section data-editor-pane="crossVerse" id="editor-cross-verse-pane" class="alignment-pane" aria-label="Cross-verse alignment"
    hidden={!$visibleTabs.has("crossVerse")} style={paneStyle(crossFrame)}>
    {#key `${pane.path}:${pane.chapter}:${pane.verse}`}
      <CrossVerseAlignmentModal embedded chapter={pane.chapter} verse={pane.verse} initialVerses={$crossVerseInitialVerses} onClose={closeCrossVerse}
        onDetach={pane.canDetach ? () => detachAlignment("cross") : null} />
    {/key}
  </section>
{/if}

<style>
  .alignment-pane { position: relative; min-width: 0; min-height: 0; overflow: hidden; background: var(--surface); }
  .alignment-pane[hidden] { display: none; }
</style>
