<script lang="ts">
  import { onMount } from "svelte";
  import { writable } from "svelte/store";
  import { setContext } from "svelte";
  export let kind = "word";
  const layout = writable({ order: ["read", "source", "target"], floating: [] as string[] });
  let dragged = "";
  function save() { try { localStorage.setItem(`bridge.alignment.layout.${kind}`, JSON.stringify($layout)); } catch { /* session only */ } }
  function move(id: string, direction: number) {
    const order = [...$layout.order];
    const index = order.indexOf(id), next = index + direction;
    if (next < 0 || next >= order.length) return;
    [order[index], order[next]] = [order[next], order[index]];
    layout.set({ ...$layout, order }); save();
  }
  function float(id: string) {
    layout.set({ ...$layout, floating: $layout.floating.includes(id) ? $layout.floating.filter((v) => v !== id) : [...$layout.floating, id] }); save();
  }
  function drop(id: string) {
    if (!dragged || dragged === id) return;
    const order = $layout.order.filter((v) => v !== dragged);
    order.splice(order.indexOf(id), 0, dragged);
    layout.set({ ...$layout, order }); dragged = ""; save();
  }
  setContext("alignment-layout", { layout, move, float, drop, kind, start: (id: string) => { dragged = id; } });
  onMount(() => {
    try {
      const value = JSON.parse(localStorage.getItem(`bridge.alignment.layout.${kind}`) || "null");
      if (value && [...value.order].sort().join() === "read,source,target" && Array.isArray(value.floating)) layout.set(value);
    } catch { /* default layout */ }
  });
  let reset = 0;
</script>

<div class="layout-toolbar"><button type="button" on:click={() => { layout.set({ order: ["read", "source", "target"], floating: [] }); for (const id of ["read", "source", "target"]) { try { localStorage.removeItem(`bridge.alignment.pane.${kind}.${id}`); } catch { /* session only */ } } reset += 1; save(); }}>Reset layout</button><small>Move areas with their handles or arrow buttons. Undock to position freely.</small></div>
<div class="alignment-layout" class:cross={kind === "cross"} class:has-floating={$layout.floating.length > 0}>
  {#key reset}<slot />{/key}
</div>

<style>
  .layout-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
  button { font: inherit; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); border-radius: 6px; padding: 5px 9px; cursor: pointer; }
  small { color: var(--text-3); }
  .alignment-layout { position: relative; display: flex; flex-direction: column; gap: 12px; min-height: 0; flex: 1; overflow: auto; padding: 3px; }
  .has-floating { min-height: min(360px, 55vh); }
  .cross { flex-direction: row; flex-wrap: wrap; align-content: flex-start; }
</style>
