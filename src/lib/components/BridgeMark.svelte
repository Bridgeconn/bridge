<script lang="ts">
  // The Bridge mark: a blue-to-green rounded square with a white arch and
  // deck. One source for every place it appears in the app -- the splash
  // window and the top bar today -- so the two cannot drift apart. The
  // taskbar / window icon is the same drawing, rendered to src-tauri/icons/
  // from src-tauri/icons/bridge-mark.svg by `npx tauri icon`.
  //
  // `animate` draws the arch and then the deck once on mount (the splash);
  // everywhere else the mark is static. The gradient id is unique per
  // instance because two marks may be on one page and SVG ids are global.
  export let animate = false;
  export let size: number | string = 24;

  const gradientId = `bridge-mark-gradient-${Math.random().toString(36).slice(2, 8)}`;
  $: px = typeof size === "number" ? `${size}px` : size;
</script>

<svg class="bridge-mark" class:animate viewBox="0 0 64 64" width={px} height={px} aria-hidden="true" focusable="false">
  <defs>
    <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#2F6FED" />
      <stop offset="1" stop-color="#15A34A" />
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="14" fill="url(#{gradientId})" />
  <path class="arc" d="M13 41 C 24 20, 40 20, 51 41" stroke="#fff" stroke-width="5" fill="none" stroke-linecap="round" />
  <path class="deck" d="M13 46 H51" stroke="#fff" stroke-width="4" stroke-linecap="round" />
</svg>

<style>
  .bridge-mark { display: block; flex-shrink: 0; }
  /* The arc draws itself left to right, then the deck underneath it. Dash
     lengths are a little over each path's true length so the ends never clip. */
  .animate .arc { stroke-dasharray: 52; stroke-dashoffset: 52; animation: draw 0.7s ease-out 0.35s forwards; }
  .animate .deck { stroke-dasharray: 40; stroke-dashoffset: 40; animation: draw 0.4s ease-out 0.85s forwards; }
  @keyframes draw { to { stroke-dashoffset: 0; } }
  @media (prefers-reduced-motion: reduce) {
    .animate .arc, .animate .deck { animation: none; stroke-dashoffset: 0; }
  }
</style>
