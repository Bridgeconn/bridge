<script lang="ts">
  import EditorWorkspace from "../../EditorWorkspace.svelte";
  import SidePanel from "../../SidePanel.svelte";
  import PanelHeader from "../../PanelHeader.svelte";
</script>
<EditorWorkspace let:editorFrame>
  <div data-editor-pane="editor" style={editorFrame}><input aria-label="Editor draft" /></div>
  <SidePanel id="paratext" label="Language QA"><PanelHeader id="paratext" title="Language QA" /><input aria-label="QA filter" /></SidePanel>
  <SidePanel id="reference" label="Reference"><PanelHeader id="reference" title="Reference" /></SidePanel>
</EditorWorkspace>
