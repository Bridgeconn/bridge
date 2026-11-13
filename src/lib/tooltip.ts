let nextTooltipId = 0;

export type TooltipInput = string | { text: string; side?: "below" | "right" };

/** Immediate hover/focus hints, rendered outside scroll containers. A hint
 *  sits below its control (above when there is no room); `side: "right"` is
 *  for a column of icons, where a hint below would cover the next one. */
export function tooltip(node: HTMLElement, input: TooltipInput) {
  let text = typeof input === "string" ? input : input.text;
  let side = typeof input === "string" ? "below" : input.side ?? "below";
  let hint: HTMLDivElement | undefined;
  const id = `bridge-tooltip-${++nextTooltipId}`;
  const hide = () => {
    hint?.remove();
    hint = undefined;
    const remaining = (node.getAttribute("aria-describedby") || "").split(" ").filter((part) => part && part !== id);
    if (remaining.length) node.setAttribute("aria-describedby", remaining.join(" "));
    else node.removeAttribute("aria-describedby");
  };
  const show = () => {
    hide();
    if (!text) return;
    hint = document.createElement("div");
    hint.id = id;
    hint.setAttribute("role", "tooltip");
    hint.setAttribute("data-bridge-tooltip", "");
    hint.textContent = text;
    // Native modal dialogs paint above every body-level z-index. Keep their
    // hints in the same top layer, outside the dialog's scrolling list.
    (node.closest("dialog[open]") ?? document.body).append(hint);
    node.setAttribute("aria-describedby", [node.getAttribute("aria-describedby"), id].filter(Boolean).join(" "));
    const anchor = node.getBoundingClientRect();
    const box = hint.getBoundingClientRect();
    if (side === "right" && anchor.right + 8 + box.width + 8 < window.innerWidth) {
      hint.style.left = `${anchor.right + 8}px`;
      hint.style.top = `${Math.max(8, Math.min(anchor.top + (anchor.height - box.height) / 2, window.innerHeight - box.height - 8))}px`;
      return;
    }
    hint.style.left = `${Math.max(8, Math.min(anchor.left + (anchor.width - box.width) / 2, window.innerWidth - box.width - 8))}px`;
    hint.style.top = `${anchor.bottom + box.height + 8 < window.innerHeight ? anchor.bottom + 6 : Math.max(8, anchor.top - box.height - 6)}px`;
  };
  const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") hide(); };
  node.addEventListener("mouseenter", show);
  node.addEventListener("mouseleave", hide);
  node.addEventListener("focus", show);
  node.addEventListener("blur", hide);
  node.addEventListener("pointerdown", hide);
  node.addEventListener("keydown", onKey);
  window.addEventListener("resize", hide);
  window.addEventListener("scroll", hide, true);
  return {
    update(value: TooltipInput) {
      text = typeof value === "string" ? value : value.text;
      side = typeof value === "string" ? "below" : value.side ?? "below";
      if (hint) show();
    },
    destroy() {
      hide();
      node.removeEventListener("mouseenter", show);
      node.removeEventListener("mouseleave", hide);
      node.removeEventListener("focus", show);
      node.removeEventListener("blur", hide);
      node.removeEventListener("pointerdown", hide);
      node.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", hide);
      window.removeEventListener("scroll", hide, true);
    },
  };
}
