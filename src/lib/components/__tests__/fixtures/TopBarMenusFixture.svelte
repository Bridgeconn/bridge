<script lang="ts">
  // TopBar with something in its "menus" slot, as App fills it (#488).
  import TopBar from "../../TopBar.svelte";
  export let screen: "home" | "dashboard" | "validation" | "review" | "editor" | "report" = "editor";
  const noop = () => {};
</script>

<TopBar {screen} projectName="Philippians" onGoHome={noop} onGoToDashboard={noop} onOpenSettings={noop}
  onOpenConnections={noop} onOpenExport={noop} onGotoVerse={noop} onChapterChange={noop} onBookChange={noop}
  exportEnabled>
  <svelte:fragment slot="menus"><button type="button">View</button></svelte:fragment>
</TopBar>
