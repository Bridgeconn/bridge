<script lang="ts">
  /** The editor's layout picker (2026-11-16, Joel): LayoutMenu with the work
   *  area's presets and actions. It is in the top bar, beside Sync and Export,
   *  not on each tab strip, because it acts on the whole work area; one group
   *  is split by dragging a tab or by its strip's Split right. Choosing a
   *  shape keeps the open panels and leaves the other places empty, to fill
   *  from the left rail or a dragged tab (editorTabs.ts `withLayoutPreset`). */
  import LayoutMenu from "./LayoutMenu.svelte";
  import { LAYOUT_PRESETS, applyLayoutPreset, currentPreset, tabLayout } from "../editorTabs";
  import { resetWorkspaceLayout } from "../projectWorkspace";
</script>

<LayoutMenu presets={LAYOUT_PRESETS} current={currentPreset($tabLayout)} onChoose={applyLayoutPreset} onReset={resetWorkspaceLayout}
  hint="Layout: split the work area into columns, rows or a grid" resetHint="Verses and Review side by side, the other panels closed" />
