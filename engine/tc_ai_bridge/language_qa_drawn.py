"""Which Language QA findings are drawn in the verse text.

A finding carries two separate answers, and they are kept apart on purpose
(DECISIONS 2026-10-07, "indic-qa findings are drawn inline by default", widened
to every rule on 2026-10-13, #250):

- `inline` is the **reviewed** flag. It comes from the pack (`rule_versions.json`,
  `indic_qa_rules.json`, the JSON rules) or from INLINE_RULES. The CI human
  gate (`language_qa_benchmark.human_inline_rules`) reads it and fails any
  inline rule with fewer than 20 labels or below 0.90 precision. It never
  changes here.
- `drawn` is what the reader sees. A reviewed-inline finding is always drawn.
  Every other finding -- a pack rule, an indic-qa rule (a profile pack or
  ta-irv's layer), a common check or a project house-style rule -- is drawn
  too, unless the user's threshold in Settings > Language QA hides it. A rule
  is hidden when its measured reviewer precision is below the slider, or its
  confidence is below the floor. A rule with no labels has no measured
  precision and passes the slider. A book-header finding (`context:
  "introduction"`, #253) is never drawn: it is not in the verse text.

The threshold is applied when a request is served, never during a pass. Moving
the slider therefore rescans nothing, touches no cache key, and changes no
finding id or decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .language_qa import RULES

CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
CONFIDENCE_FLOORS = tuple(CONFIDENCE_RANK)
# Findings outside the verse text and its headings: listed, never drawn.
UNDRAWN_CONTEXTS = frozenset({"introduction"})


@dataclass(frozen=True)
class InlinePolicy:
    """The user's threshold. The defaults draw every finding."""
    min_precision: int = 0        # percent, 0-100
    min_confidence: str = "low"   # "low" | "medium" | "high"

    @classmethod
    def of(cls, min_precision: Any = 0, min_confidence: Any = "low") -> "InlinePolicy":
        try:
            precision = int(min_precision)
        except (TypeError, ValueError):
            precision = 0
        floor = str(min_confidence or "low").lower()
        return cls(max(0, min(100, precision)), floor if floor in CONFIDENCE_RANK else "low")


def _meta(rule: str, confidence: str, row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    return {"rule": rule, "confidence": confidence,
            "precision": row.get("precision"), "labelled": int(row.get("labelled") or 0)}


def gated_rules(pack: Any) -> dict[str, dict[str, Any]]:
    """ruleId -> {"rule", "confidence", "precision", "labelled"} for every
    enabled rule a pass under this pack can report: the non-pack rules
    (language_qa.RULES, "common/..." and "project/...") and every enabled rule
    of the pack, its indic-qa layer included. Precision comes from the pack's
    `rule_precision.json`; a rule it does not list is unmeasured."""
    table = pack.precision() if pack is not None else {}
    out = {f"{meta.pack}/{name}": _meta(name, meta.confidence, table.get(f"{meta.pack}/{name}"))
           for name, meta in RULES.items() if meta.enabled}
    for rule in (pack.rules if pack is not None else ()):
        if rule.enabled:
            rule_id = f"{pack.name}/{rule.id}"
            out[rule_id] = _meta(rule.name, rule.confidence, table.get(rule_id))
    return out


def rule_passes(meta: dict[str, Any], policy: InlinePolicy) -> bool:
    precision = meta.get("precision")
    if precision is not None and precision * 100 < policy.min_precision:
        return False
    return CONFIDENCE_RANK.get(str(meta.get("confidence")), 0) >= CONFIDENCE_RANK[policy.min_confidence]


def _rule_meta(finding: dict[str, Any], gated: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The finding's rule in the table; a rule the table does not know (a pass
    under another pack, a cache read before the first pass) is unmeasured at
    the finding's own confidence."""
    return gated.get(str(finding.get("ruleId") or "")) or _meta(
        str(finding.get("rule") or ""), str(finding.get("confidence") or "low"), None)


def is_drawn(finding: dict[str, Any], gated: dict[str, dict[str, Any]], policy: InlinePolicy) -> bool:
    if finding.get("context") in UNDRAWN_CONTEXTS:
        return False
    if finding.get("inline"):
        return True
    return rule_passes(_rule_meta(finding, gated), policy)


def served(finding: dict[str, Any], gated: dict[str, dict[str, Any]], policy: InlinePolicy) -> dict[str, Any]:
    """A copy of the finding as a request serves it: its `drawn` answer, and
    its rule's measured reviewer precision (`rulePrecision`, 0-1 or None) and
    label count (`ruleLabelled`), which the editor's "Why" shows."""
    meta = _rule_meta(finding, gated)
    return {**finding, "drawn": is_drawn(finding, gated, policy),
            "rulePrecision": meta["precision"], "ruleLabelled": meta["labelled"]}


def with_drawn(findings: Iterable[dict[str, Any]], gated: dict[str, dict[str, Any]],
               policy: InlinePolicy) -> list[dict[str, Any]]:
    """Copies of the findings, each as served()."""
    return [served(f, gated, policy) for f in findings]


def drawn_rule_names(inline_rules: Iterable[str], gated: dict[str, dict[str, Any]],
                     policy: InlinePolicy) -> list[str]:
    """The `rule` names drawn under this threshold: the reviewed-inline ones
    plus every other rule that passes it."""
    return sorted(set(inline_rules) | {meta["rule"] for meta in gated.values() if rule_passes(meta, policy)})
