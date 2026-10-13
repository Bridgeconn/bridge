"""The inline threshold on its own (language_qa_drawn): which findings are
drawn in the verse text. No dispatcher, no pass."""
from types import SimpleNamespace

from tc_ai_bridge.language_qa import RULES
from tc_ai_bridge.language_qa_drawn import (InlinePolicy, drawn_rule_names, gated_rules, is_drawn, served,
                                            with_drawn)

GATED = {"hi-irv/a": {"rule": "a", "confidence": "high", "precision": 0.5, "labelled": 30},
         "hi-irv/b": {"rule": "b", "confidence": "medium", "precision": None, "labelled": 0},
         "hi-irv/c": {"rule": "c", "confidence": "low", "precision": 0.95, "labelled": 25}}


def finding(rule_id, inline=False):
    return {"ruleId": rule_id, "inline": inline}


def test_the_default_policy_draws_every_finding_whatever_its_rule():
    policy = InlinePolicy()
    assert all(is_drawn(finding(r), GATED, policy) for r in GATED)
    # A rule the table does not know (another pack, a read before the first
    # pass) is unmeasured: the default draws it too.
    assert is_drawn(finding("ta-irv/sandhi.x"), GATED, policy)
    assert is_drawn(finding("ta-irv/sandhi.x", inline=True), GATED, policy)


def test_an_unknown_rule_is_judged_on_the_findings_own_confidence():
    low = {"ruleId": "ta-irv/sandhi.x", "inline": False, "confidence": "low"}
    high = {**low, "confidence": "high"}
    policy = InlinePolicy.of(100, "medium")
    assert [is_drawn(low, {}, policy), is_drawn(high, {}, policy)] == [False, True]


def test_a_book_header_finding_is_never_drawn_even_when_reviewed_inline():
    header = {"ruleId": "common/header.missing", "inline": True, "context": "introduction"}
    assert not is_drawn(header, GATED, InlinePolicy())
    heading = {"ruleId": "hi-irv/b", "inline": False, "context": "heading"}
    assert is_drawn(heading, GATED, InlinePolicy()), "a heading is in the text the editor shows"


def test_precision_hides_measured_rules_below_it_and_never_an_unmeasured_one():
    policy = InlinePolicy.of(60, "low")
    assert [is_drawn(finding(r), GATED, policy) for r in ("hi-irv/a", "hi-irv/b", "hi-irv/c")] == [False, True, True]
    assert is_drawn(finding("hi-irv/b"), GATED, InlinePolicy.of(100, "low"))


def test_the_confidence_floor_and_the_slider_must_both_pass():
    assert [is_drawn(finding(r), GATED, InlinePolicy.of(0, "medium"))
            for r in ("hi-irv/a", "hi-irv/b", "hi-irv/c")] == [True, True, False]
    assert [is_drawn(finding(r), GATED, InlinePolicy.of(40, "high"))
            for r in ("hi-irv/a", "hi-irv/b", "hi-irv/c")] == [True, False, False]


def test_a_reviewed_inline_finding_is_drawn_whatever_the_threshold():
    assert is_drawn(finding("hi-irv/a", inline=True), GATED, InlinePolicy.of(100, "high"))


def test_out_of_range_input_falls_back_to_drawing_everything():
    assert InlinePolicy.of("x", None) == InlinePolicy(0, "low")
    assert InlinePolicy.of(-5, "HIGH") == InlinePolicy(0, "high")
    assert InlinePolicy.of(500, "certain") == InlinePolicy(100, "low")


def test_drawn_rule_names_and_with_drawn_agree_with_is_drawn():
    policy = InlinePolicy.of(60, "low")
    assert drawn_rule_names(["spacing.extra"], GATED, policy) == ["b", "c", "spacing.extra"]
    copies = with_drawn([finding("hi-irv/a"), finding("hi-irv/b")], GATED, policy)
    assert [f["drawn"] for f in copies] == [False, True]


def test_served_adds_the_rules_measured_precision_for_why():
    copy = served(finding("hi-irv/a"), GATED, InlinePolicy.of(60, "low"))
    assert (copy["drawn"], copy["rulePrecision"], copy["ruleLabelled"]) == (False, 0.5, 30)
    unknown = served(finding("ta-irv/sandhi.x"), GATED, InlinePolicy())
    assert (unknown["drawn"], unknown["rulePrecision"], unknown["ruleLabelled"]) == (True, None, 0)


def test_gated_rules_lists_every_enabled_rule_the_pass_can_report():
    rule = lambda id_, match_type="indic-qa", enabled=True, confidence="medium": SimpleNamespace(  # noqa: E731
        id=id_, name=id_, match_type=match_type, enabled=enabled, confidence=confidence)
    pack = SimpleNamespace(name="ta-irv", rules=[rule("indicqa.x"), rule("indicqa.off", enabled=False),
                                                   rule("sandhi.y", match_type="token-context", confidence="high")],
                           precision=lambda: {"ta-irv/indicqa.x": {"precision": 0.8, "labelled": 22}})
    gated = gated_rules(pack)
    assert gated["ta-irv/indicqa.x"] == {"rule": "indicqa.x", "confidence": "medium", "precision": 0.8, "labelled": 22}
    assert gated["ta-irv/sandhi.y"] == {"rule": "sandhi.y", "confidence": "high", "precision": None, "labelled": 0}
    assert "ta-irv/indicqa.off" not in gated
    # The non-pack rules (common checks, project house style) are decided too.
    common = {f"{meta.pack}/{name}" for name, meta in RULES.items() if meta.enabled}
    assert common <= set(gated) and common == set(gated_rules(None))
    assert gated["common/spacing.extra"]["confidence"] == RULES["spacing.extra"].confidence
