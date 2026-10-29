<script lang="ts">
  export let name: string;
  const paths: Record<string, string> = {
    open: "M10 17l5-5-5-5M4 12h11M14 3h5a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5",
    rename: "m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15v5Z",
    archive: "M3 3h18v5H3zM5 8v13h14V8M9 12h6",
    unarchive: "M3 3h18v5H3zM5 8v13h14V8M12 18v-7m-3 3 3-3 3 3",
    delete: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7",
    close: "M6 6l12 12M6 18 18 6",
    assign: "M16 11a4 4 0 1 0-8 0 4 4 0 0 0 8 0ZM4 21a8 8 0 0 1 12-6.9M19 16v6m-3-3h6",
    play: "M7 4v16l13-8z",
    pause: "M7 4h4v16H7zM13 4h4v16h-4z",
    stop: "M6 6h12v12H6z",
    check: "m5 12 5 5 9-10",
    chevronDown: "m6 9 6 6 6-6",
    link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.5 1.5M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.5-1.5",
    warning: "M12 3 2 20h20L12 3Zm0 6v5m0 3v1",
    folder: "M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Z",
    report: "M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8l-5-5ZM14 3v5h5M9 13h6M9 17h6",
    viewReport: "M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8l-5-5ZM14 3v5h5M8 17v-3m4 3v-6m4 6v-4",
    rebuild: "M21 12a9 9 0 0 1-15.5 6.2M3 12a9 9 0 0 1 15.5-6.2M18.5 2v4h-4M5.5 22v-4h4",
    addBooks: "M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8l-5-5ZM14 3v5h5M12 11v6M9 14h6",
    back: "m12 5-7 7 7 7M5 12h15",
    sync: "M20 7h-5m5 0V2M4 17h5m-5 0v5M5 7a8 8 0 0 1 13-2l2 2M4 17l2 2a8 8 0 0 0 13-2",
    settings: "m10 3-.6 2.2-2 .9-2-.6-2 3.5 1.5 1.6v2.3L3.4 15l2 3.5 2-.6 2 .9.6 2.2h4l.6-2.2 2-.9 2 .6 2-3.5-1.5-1.6v-2.3L20.6 9l-2-3.5-2 .6-2-.9L14 3h-4ZM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z",
  };
</script>

<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d={paths[name] || paths.open} /></svg>
