<script lang="ts">
  export let name: string;
  const paths: Record<string, string> = {
    open: "M10 17l5-5-5-5M4 12h11M14 3h5a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5",
    rename: "m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15v5Z",
    archive: "M3 3h18v5H3zM5 8v13h14V8M9 12h6",
    unarchive: "M3 3h18v5H3zM5 8v13h14V8M12 18v-7m-3 3 3-3 3 3",
    delete: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7",
    back: "m12 5-7 7 7 7M5 12h15",
    sync: "M20 7h-5m5 0V2M4 17h5m-5 0v5M5 7a8 8 0 0 1 13-2l2 2M4 17l2 2a8 8 0 0 0 13-2",
    settings: "m10 3-.6 2.2-2 .9-2-.6-2 3.5 1.5 1.6v2.3L3.4 15l2 3.5 2-.6 2 .9.6 2.2h4l.6-2.2 2-.9 2 .6 2-3.5-1.5-1.6v-2.3L20.6 9l-2-3.5-2 .6-2-.9L14 3h-4ZM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z",
  };
</script>

<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d={paths[name] || paths.open} /></svg>
