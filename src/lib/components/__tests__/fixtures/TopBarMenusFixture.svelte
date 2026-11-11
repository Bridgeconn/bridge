<script lang="ts">
  // TopBar with something in its "menus" slot, as App fills it (#488).
  import TopBar from "../../TopBar.svelte";
  export let screen: "home" | "dashboard" | "validation" | "review" | "editor" | "report" = "editor";
  export let onGoToDashboard: () => void = () => {};
  const noop = () => {};
</script>

<TopBar {screen} projectName="Philippians" onGoHome={noop} {onGoToDashboard} onOpenSettings={noop}
  onOpenConnections={noop}>
  <svelte:fragment slot="menus"><button type="button">View</button></svelte:fragment>
</TopBar>
