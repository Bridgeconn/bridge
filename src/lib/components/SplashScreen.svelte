<script lang="ts">
  // The splash window (#287): the brand, the version and the latest startup
  // stage the shell reported, in a small borderless window. It only watches;
  // the hidden main window connects to the engine, and on success or failure
  // asks the shell to show itself and close this window. A failure is shown
  // there, on the full loading card (#233), not here.
  //
  // Motion, in order of appearance: the mark's arc draws itself once, the
  // brand text rises in behind it, each new stage label crossfades over the
  // last, and a thin track at the foot advances by STARTUP_STAGE_ORDER with
  // a slow sheen so a long stage still reads as alive. Everything is CSS;
  // nothing here waits on an animation, and `prefers-reduced-motion`
  // switches it all off.
  import { onDestroy, onMount } from "svelte";
  import { bridge, type EngineStartupStage } from "../api/bridgeClient";
  import { currentStageLabel, mergeStage, startupProgress } from "../startup";

  let version = "";
  let stages: EngineStartupStage[] = [];
  let unlisten: (() => void) | null = null;
  let disposed = false;

  onMount(() => {
    void (async () => {
      // Listen first, then catch up, merged by seq (as App.svelte does).
      try {
        const stop = await bridge.onEngineStage((stage) => { stages = mergeStage(stages, stage); });
        if (disposed) stop();
        else unlisten = stop;
      } catch (error) {
        console.error("Splash: could not subscribe to engine startup stages", error);
      }
      try {
        const state = await bridge.engineStartupState();
        if (disposed) return;
        version = state.version;
        for (const stage of state.stages) stages = mergeStage(stages, stage);
      } catch (error) {
        console.error("Splash: could not read engine startup state", error);
      }
    })();
  });
  onDestroy(() => {
    disposed = true;
    unlisten?.();
  });

  $: label = currentStageLabel(stages);
  $: progress = startupProgress(stages);
</script>

<div class="splash" data-tauri-drag-region data-testid="splash-screen">
  <div class="wash wash-a" aria-hidden="true"></div>
  <div class="wash wash-b" aria-hidden="true"></div>

  <div class="brand" data-tauri-drag-region>
    <div class="mark-wrap" data-tauri-drag-region>
      <div class="halo" aria-hidden="true"></div>
      <svg class="mark" viewBox="0 0 64 64" aria-hidden="true">
        <defs>
          <linearGradient id="bridge-splash-gradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="#2F6FED" />
            <stop offset="1" stop-color="#15A34A" />
          </linearGradient>
        </defs>
        <rect width="64" height="64" rx="14" fill="url(#bridge-splash-gradient)" />
        <path class="arc" d="M13 41 C 24 20, 40 20, 51 41" stroke="#fff" stroke-width="5" fill="none" stroke-linecap="round" />
        <path class="deck" d="M13 46 H51" stroke="#fff" stroke-width="4" stroke-linecap="round" />
      </svg>
    </div>
    <div class="words" data-tauri-drag-region>
      <div class="name" data-tauri-drag-region>Bridge</div>
      <div class="version" data-testid="splash-version" data-tauri-drag-region>{version ? `Version ${version}` : ""}</div>
    </div>
  </div>

  <div class="status" role="status" aria-live="polite" data-tauri-drag-region>
    <span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>
    {#key label}
      <span class="label" data-testid="splash-stage" data-tauri-drag-region>{label}</span>
    {/key}
  </div>

  <div class="track" aria-hidden="true">
    <div class="fill" style="transform: scaleX({progress})"></div>
    <div class="sheen"></div>
  </div>
</div>

<style>
  .splash {
    position: fixed; inset: 0; box-sizing: border-box; overflow: hidden;
    background: var(--surface); padding: 30px 34px 0;
    display: flex; flex-direction: column; justify-content: center; gap: 24px;
    cursor: default; user-select: none;
  }

  /* Two soft colour washes in the brand's own blue and green, drifting slowly
     so the white card never reads as a dialog box. Blurred ellipses, not a
     gradient on the card, so the type underneath stays on a clean surface. */
  .wash { position: absolute; border-radius: 50%; filter: blur(42px); pointer-events: none; opacity: 0.55; }
  .wash-a { width: 300px; height: 220px; top: -120px; right: -60px; background: #2F6FED; animation: drift-a 9s ease-in-out infinite alternate; opacity: 0.22; }
  .wash-b { width: 240px; height: 200px; bottom: -130px; left: -40px; background: #15A34A; animation: drift-b 11s ease-in-out infinite alternate; opacity: 0.18; }
  @keyframes drift-a { to { transform: translate(-30px, 24px); } }
  @keyframes drift-b { to { transform: translate(36px, -18px); } }

  .brand { position: relative; display: flex; align-items: center; gap: 18px; }
  .mark-wrap { position: relative; width: 60px; height: 60px; flex-shrink: 0; }
  .halo {
    position: absolute; inset: -8px; border-radius: 22px;
    background: radial-gradient(closest-side, rgba(47, 111, 237, 0.35), transparent);
    animation: halo 2.6s ease-in-out infinite;
  }
  @keyframes halo { 0%, 100% { opacity: 0.35; transform: scale(0.92); } 50% { opacity: 0.8; transform: scale(1.06); } }
  .mark { position: relative; width: 60px; height: 60px; display: block; filter: drop-shadow(0 6px 14px rgba(47, 111, 237, 0.28)); animation: mark-in 0.55s cubic-bezier(0.2, 0.9, 0.3, 1.2) both; }
  @keyframes mark-in { from { opacity: 0; transform: scale(0.7) rotate(-6deg); } to { opacity: 1; transform: none; } }
  /* The arc draws itself left to right, then the deck underneath it. Dash
     lengths are a little over each path's true length so the ends never clip. */
  .arc { stroke-dasharray: 52; stroke-dashoffset: 52; animation: draw 0.7s ease-out 0.35s forwards; }
  .deck { stroke-dasharray: 40; stroke-dashoffset: 40; animation: draw 0.4s ease-out 0.85s forwards; }
  @keyframes draw { to { stroke-dashoffset: 0; } }

  .words { animation: rise 0.6s ease-out 0.25s both; }
  @keyframes rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
  .name {
    font-size: var(--fs-5xl); font-weight: 800; letter-spacing: -0.02em; line-height: 1.1;
    background: linear-gradient(100deg, var(--text) 0%, var(--text) 55%, var(--accent) 100%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .version { font-size: var(--fs-xs); color: var(--text-3); min-height: 1.2em; margin-top: 2px; letter-spacing: 0.01em; }

  .status { position: relative; display: flex; align-items: center; gap: 12px; font-size: var(--fs-sm); color: var(--text-2); min-height: 1.4em; }
  .dots { display: inline-flex; gap: 4px; flex-shrink: 0; }
  .dots i { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: dot 1.2s ease-in-out infinite; }
  .dots i:nth-child(2) { animation-delay: 0.15s; }
  .dots i:nth-child(3) { animation-delay: 0.3s; }
  @keyframes dot { 0%, 80%, 100% { opacity: 0.25; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-3px); } }
  .label { animation: label-in 0.3s ease-out both; }
  @keyframes label-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }

  /* The progress track sits on the window's bottom edge. The fill scales to
     the furthest known stage; the sheen keeps sliding across the whole width
     so a slow stage (PyInstaller unpacking on a cold disk) still looks live. */
  .track { position: absolute; left: 0; right: 0; bottom: 0; height: 4px; background: var(--border); overflow: hidden; }
  .fill { position: absolute; inset: 0; transform-origin: left; background: linear-gradient(90deg, var(--accent), var(--pass)); transition: transform 0.6s cubic-bezier(0.2, 0.7, 0.2, 1); }
  .sheen { position: absolute; top: 0; bottom: 0; width: 30%; background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.7), transparent); animation: sheen 1.8s ease-in-out infinite; }
  @keyframes sheen { from { transform: translateX(-120%); } to { transform: translateX(420%); } }

  @media (prefers-reduced-motion: reduce) {
    .wash, .halo, .mark, .arc, .deck, .words, .dots i, .label, .sheen { animation: none; }
    .arc, .deck { stroke-dashoffset: 0; }
    .fill { transition: none; }
    .halo { opacity: 0.5; }
  }
</style>
