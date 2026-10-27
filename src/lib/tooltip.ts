let nextTooltipId = 0;

/** Immediate hover/focus hints, rendered outside scroll containers. */
export function tooltip(node: HTMLElement, text: string) {
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
    update(value: string) { text = value; if (hint) show(); },
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
