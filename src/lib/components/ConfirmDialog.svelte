<script lang="ts">
  import { onMount, tick } from "svelte";
  import { answerConfirmation, confirmRequest } from "../confirmAction";

  // The in-app confirmation (#372): one question, two buttons, nothing else.
  // Mounted once in App while confirmRequest holds a question; the answer
  // goes back through answerConfirmation. Cancel has focus by default and
  // Escape is Cancel, so a stray Enter never runs a paid or destructive
  // action. Above every app dialog (Settings opens it), like the scoped
  // Language QA confirmation.
  let cancelButton: HTMLButtonElement | null = null;
  let previouslyFocused: Element | null = null;

  $: request = $confirmRequest;

  // Escape is heard in the capture phase, before the dialog under this one
  // (Settings closes on Escape too, and its window listener was registered
  // first): the question is answered no, the event is marked handled, and
  // nothing else closes. Seen in the 0.21.0 walk: Escape here also shut
  // Settings.
  function onKeydown(event: KeyboardEvent): void {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    answerConfirmation(false);
  }

  onMount(() => {
    previouslyFocused = document.activeElement;
    void tick().then(() => cancelButton?.focus());
    window.addEventListener("keydown", onKeydown, true);
    return () => {
      window.removeEventListener("keydown", onKeydown, true);
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
    };
  });
</script>

{#if request}
  <div class="overlay" role="presentation">
    <div class="dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-body">
      <h2 id="confirm-title">{request.title}</h2>
      <p id="confirm-body">{request.body}</p>
      <div class="actions">
        <button type="button" bind:this={cancelButton} on:click={() => answerConfirmation(false)}>{request.cancelLabel ?? "Cancel"}</button>
        <button type="button" class="primary" class:danger={request.danger} on:click={() => answerConfirmation(true)}>{request.confirmLabel}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .overlay { position: fixed; inset: 0; z-index: var(--z-dialog-over-dialog); display: grid; place-items: center; background: rgba(15, 20, 26, 0.45); }
  .dialog { width: min(440px, calc(100vw - 32px)); box-sizing: border-box; background: var(--surface); color: var(--text);
    border-radius: 14px; padding: 20px 24px; box-shadow: 0 20px 50px rgba(0, 0, 0, .25); }
  h2 { font-size: var(--fs-lg); margin: 0 0 6px; }
  p { font-size: var(--fs-sm); color: var(--text-2); margin: 0 0 16px; line-height: 1.5; }
  .actions { display: flex; justify-content: flex-end; gap: 10px; }
  button { font: inherit; font-size: var(--fs-sm); font-weight: 600; padding: 8px 14px; border-radius: 6px;
    border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  button.primary.danger { background: var(--danger); border-color: var(--danger); }
  button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
