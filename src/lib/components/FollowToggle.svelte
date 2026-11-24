<script lang="ts">
  /** "Follow" for a panel that shows the open chapter beside the text (the
   *  Source and Reference panels): on, the verse selected in the text is kept
   *  in view here; off, the panel stays where it was scrolled. An icon switch
   *  with an instant hint (#519), in place of a ticked box and the word: the
   *  Word alignment tab's pair, the arrow while following and the pin while
   *  not, and the accent colour while on, as the header's other switches. */
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";

  export let follow = true;
</script>

<button type="button" class="ui-icon-btn follow-toggle" aria-label="Follow the selected verse" aria-pressed={follow}
  use:tooltip={follow ? "Following: the selected verse is kept in view here. Click to stop"
    : "Not following: this panel stays where you scrolled it. Click to keep the selected verse in view"}
  on:click={() => (follow = !follow)}><UiIcon name={follow ? "follow" : "pin"} /></button>
