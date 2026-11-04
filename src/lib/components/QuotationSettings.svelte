<script lang="ts">
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import { nudgeLanguageQa } from "../languageQaInline";
  import type { QuotationRules, QuotationRulesSettings } from "../types/languageQa";

  export let projectPath: string;
  let model: QuotationRulesSettings | null = null;
  let rules: QuotationRules | null = null;
  let busy = false;
  let error = "";
  let message = "";
  const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
  const styles: ("target" | "reference")[] = ["target", "reference"];
  onMount(() => {
    let disposed = false;
    bridge.languageQaQuotationRulesGet(projectPath).then((value) => {
      if (!disposed) { model = value; rules = copy(value.rules); }
    }).catch((e) => { if (!disposed) error = String(e); });
    return () => { disposed = true; };
  });
  function preview(name: "target" | "reference"): string {
    const pairs = rules?.[name].pairs ?? [];
    return pairs.reduceRight((text, pair) => `${pair.open}${text}${pair.close}`, "quotation");
  }
  async function save(): Promise<void> {
    if (!rules) return;
    busy = true; error = ""; message = "";
    try {
      model = await bridge.languageQaQuotationRulesSet(projectPath, rules);
      rules = copy(model.rules);
      message = "Saved. Language QA is checking the updated rules.";
      nudgeLanguageQa();
    } catch (e) { error = String(e); }
    finally { busy = false; }
  }
</script>

<section aria-label="Quotation rules">
  <h3>Quotation rules</h3>
  {#if model && rules}
    <p>Saved for this {model.scope}, including every book. Quotations may continue across verses and chapters.</p>
    <label><input type="checkbox" bind:checked={rules.enabled} disabled={busy} /> Check quotations</label>
    <label><input type="checkbox" bind:checked={rules.referenceEnabled} disabled={busy} /> Compare with the local Reference Bible</label>
    <p>Reference differences are possible missing quotations for human review. No marks are inserted automatically. Choose the reference Bible above.</p>
    {#each styles as key}
      <fieldset disabled={busy}>
        <legend>{key === "target" ? "Target language" : "Reference Bible"} conventions</legend>
        <p>Pairs in outer-to-inner order. English defaults use “…” outside and ‘…’ inside. Straight quotes and other punctuation pairs are supported.</p>
        {#each rules[key].pairs as pair, i}
          <div class="pair">
            <label>{i === 0 ? "Outer" : `Nested ${i}`} opening
              <input aria-label={`${key} level ${i + 1} opening`} type="text" bind:value={pair.open} maxlength="8" />
            </label>
            <label>Closing
              <input aria-label={`${key} level ${i + 1} closing`} type="text" bind:value={pair.close} maxlength="8" />
            </label>
            {#if i > 0}<button type="button" on:click={() => { if (rules) rules[key].pairs = rules[key].pairs.filter((_, index) => index !== i); }}>Remove level {i + 1}</button>{/if}
          </div>
        {/each}
        <button type="button" disabled={rules[key].pairs.length >= 4} on:click={() => { if (rules) rules[key].pairs = [...rules[key].pairs, { open: "", close: "" }]; }}>Add nesting level</button>
        <label>Paragraph continuation
          <select aria-label={`${key} paragraph continuation`} bind:value={rules[key].continuation}>
            <option value="repeat-opening">Allow repeated opening mark at paragraph/verse start</option>
            <option value="none">No repeated opening mark</option>
          </select>
        </label>
        <p class="preview">Preview: {preview(key)}</p>
      </fieldset>
    {/each}
    <div class="actions">
      <button type="button" disabled={busy} on:click={() => { if (model) { rules = copy(model.defaults); message = "English defaults restored in this form. Save to apply."; } }}>Restore English defaults</button>
      <button type="button" disabled={busy} on:click={save}>{busy ? "Saving…" : "Save quotation rules"}</button>
    </div>
  {:else if !error}
    <p>Loading quotation rules…</p>
  {/if}
  {#if error}<p role="alert">{error}</p>{/if}
  {#if message}<p role="status">{message}</p>{/if}
</section>

<style>
  section { margin: 1.2rem 0; font-size: .85rem; }
  h3 { font-size: .95rem; }
  p { color: var(--text-muted, #64748b); line-height: 1.5; }
  fieldset { margin: .8rem 0; border: 1px solid var(--border, #cbd5e1); border-radius: 6px; padding: .7rem; min-width: 0; }
  label { display: block; margin: .5rem 0; }
  .pair { display: flex; flex-wrap: wrap; gap: .6rem; align-items: end; }
  .pair label { flex: 1; min-width: 5rem; }
  input[type="text"] { display: block; width: 100%; box-sizing: border-box; padding: .3rem; }
  select { display: block; max-width: 100%; margin-top: .3rem; }
  .actions { display: flex; flex-wrap: wrap; gap: .5rem; }
  button { padding: .3rem .6rem; border: 1px solid var(--border, #cbd5e1); border-radius: 4px; }
  .preview { font-size: 1rem; }
  [role="alert"] { color: #b91c1c; }
</style>
