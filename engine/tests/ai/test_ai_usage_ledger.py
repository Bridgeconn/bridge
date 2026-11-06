"""#476: the client's call ledger. Every request sent gets an entry -- an
answered one with the provider's counts, an unanswered one (a transport failure
after the request went out) with its input estimated from the body -- and
`usage_since(mark)` sums them, so a caller that makes several calls for one
verse can report them all. No RPC here; the job-level sums are in
tests/service/test_ai_usage_accounting.py."""
from __future__ import annotations

import json

import pytest
from tc_ai_bridge.ai_client import (
    AITransportError, AIUsage, OpenAIResponsesClient, estimate_input_tokens, usage_dict,
)
from tc_ai_bridge.model_router import estimate_cost

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def _answer(inp: int, out: int, cached: int = 0) -> tuple[int, bytes]:
    return 200, json.dumps({
        "output_text": json.dumps({"ok": True}),
        "usage": {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out,
                  "input_tokens_details": {"cached_tokens": cached}},
    }).encode("utf-8")


def test_estimate_input_tokens_weighs_non_ascii_script_heavier():
    ascii_only = b"a" * 400
    assert estimate_input_tokens(ascii_only) == 100
    hindi = "उत्पत्ति".encode("utf-8")  # 8 code points
    assert estimate_input_tokens(hindi) == 16
    assert estimate_input_tokens(b"") == 1
    assert estimate_input_tokens(b"\xff\xfe\xfd\xfc\xfb\xfa\xf9\xf8") == 2  # undecodable: bytes / 4


def test_usage_since_sums_answered_and_unanswered_calls():
    answers = [_answer(1000, 100), _answer(300, 30), "timeout", _answer(200, 80, cached=50)]
    bodies: list[bytes] = []

    def transport(url, headers, body, timeout):
        bodies.append(body)
        nxt = answers.pop(0)
        if nxt == "timeout":
            raise AITransportError("Network error contacting OpenAI: The read operation timed out")
        return nxt

    client = OpenAIResponsesClient("sk-test", model="gpt-5.6", transport=transport)
    assert client.usage_mark() == 0
    client._post_structured("i", "one", "s", SCHEMA)
    mark = client.usage_mark()
    assert mark == 1
    client._post_structured("i", "two", "s", SCHEMA)
    with pytest.raises(AITransportError):
        client._post_structured("i", "three", "s", SCHEMA)
    # The unanswered call is the most recent one, estimated, flagged.
    estimated = estimate_input_tokens(bodies[2])
    assert client.last_usage == AIUsage(estimated, 0, estimated, 0, calls=1, unanswered_calls=1)
    assert client.last_cost_usd == estimate_cost("gpt-5.6", estimated, 0)
    client._post_structured("i", "four", "s", SCHEMA)
    assert client.last_usage == AIUsage(200, 80, 280, 50, calls=1)

    since, cost = client.usage_since(mark)
    assert since == AIUsage(300 + estimated + 200, 30 + 80, 330 + estimated + 280, 50, calls=3, unanswered_calls=1)
    assert cost == pytest.approx(
        estimate_cost("gpt-5.6", 300, 30) + estimate_cost("gpt-5.6", estimated, 0)
        + estimate_cost("gpt-5.6", 200, 80, 50),
    )
    everything, _ = client.usage_since(0)
    assert everything.calls == 4 and everything.input_tokens == 1000 + 300 + estimated + 200
    assert usage_dict(since) == {
        "inputTokens": since.input_tokens, "cachedInputTokens": 50,
        "outputTokens": 110, "totalTokens": since.total_tokens,
        "calls": 3, "unansweredCalls": 1,
    }
