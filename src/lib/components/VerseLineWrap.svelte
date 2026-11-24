<script lang="ts">
  import { lineClass } from "../utils/verseLines";

  /**
   * One paragraph or poetry line of a verse (#507). VerseList gives every
   * line of a verse to this component and keeps the pieces' markup (marks,
   * note buttons, handlers) itself, in the slot.
   *
   * `wrap` is false for a verse that is one line of ordinary running text.
   * Its pieces are then put straight into the verse body with no element
   * round them, so such a verse is drawn exactly as it was before there were
   * lines. A verse with poetry, a title or more than one paragraph gets one
   * block per line, classed by the line's marker (`pl-q1`, `pl-q2`, `pl-d`).
   */
  export let wrap = false;
  /** The USFM paragraph marker of this line, without its backslash. */
  export let marker = "";
  /** A stanza break (`\b`) comes before this line. */
  export let gap = false;
</script>

{#if wrap}<span class="vline {lineClass(marker)}" class:gap><slot /></span>{:else}<slot />{/if}

<style>
  /* Logical properties throughout, so a right-to-left project indents from
     the right. */
  /* flow-root is a block that also contains its own floats: a "Selah" that
     drops under a full line stays inside this line, not over the next one. */
  .vline { display: flow-root; }
  .vline.gap { margin-top: 0.7em; }
  /* The label of a note, flag or history button inside an indented line must
     not be pushed sideways by the line's own text-indent. */
  .vline :global(button) { text-indent: 0; }

  /* Poetry. Each level starts 1.5em further in than the one above it, and a
     line too long for the column continues 1.5em further in than it started,
     so a wrapped \q1 line is never mistaken for a new \q2 line. */
  .pl-q, .pl-q1, .pl-qm, .pl-qm1 { padding-inline-start: 2.5em; text-indent: -1.5em; }
  .pl-q2, .pl-qm2 { padding-inline-start: 4em; text-indent: -1.5em; }
  .pl-q3, .pl-qm3 { padding-inline-start: 5.5em; text-indent: -1.5em; }
  .pl-q4 { padding-inline-start: 7em; text-indent: -1.5em; }
  .pl-qr { text-align: end; }
  .pl-qc, .pl-pc { text-align: center; }
  /* \qa: the letter over an acrostic stanza. \qd: a note closing a psalm. */
  .pl-qa { font-weight: 700; padding-inline-start: 1em; }
  .pl-qd { font-style: italic; padding-inline-start: 1em; }
  /* \d: a psalm's title. It is the translation's own text, so it keeps the
     verse's colour; italic is what sets it apart from the lines under it. */
  .pl-d { font-style: italic; }

  /* Indented prose, right-aligned closings and lists. */
  .pl-pi, .pl-pi1, .pl-mi, .pl-pm, .pl-pmo, .pl-pmc { padding-inline-start: 1.5em; }
  .pl-pi2 { padding-inline-start: 3em; }
  .pl-pi3 { padding-inline-start: 4.5em; }
  .pl-pr, .pl-pmr, .pl-cls { text-align: end; }
  .pl-ph, .pl-ph1, .pl-li, .pl-li1, .pl-lim, .pl-lim1, .pl-lh, .pl-lf { padding-inline-start: 2.5em; text-indent: -1em; }
  .pl-ph2, .pl-li2, .pl-lim2 { padding-inline-start: 4em; text-indent: -1em; }
  .pl-ph3, .pl-li3, .pl-lim3 { padding-inline-start: 5.5em; text-indent: -1em; }
  .pl-li4, .pl-lim4 { padding-inline-start: 7em; text-indent: -1em; }
</style>
