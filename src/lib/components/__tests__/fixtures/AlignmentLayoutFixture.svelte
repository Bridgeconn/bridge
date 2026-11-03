<script lang="ts">
  import AlignmentWorkspace from "../../AlignmentWorkspace.svelte";
  import AlignmentPane from "../../AlignmentPane.svelte";
</script>
<AlignmentWorkspace>
  <AlignmentPane id="read" label="Read"><input aria-label="Reading draft" /></AlignmentPane>
  <AlignmentPane id="source" label="Source">Source fixture</AlignmentPane>
  <AlignmentPane id="target" label="Target">Target fixture</AlignmentPane>
</AlignmentWorkspace>
