"""#506: Bridge's AI requests on a ChatGPT plan (`tc_ai_bridge.chatgpt_plan_client`).

The transport is a fake that answers as the plan route was seen to on the live
runs in docs/BUILD_LOG.md (2026-11-23): a string `input` refused, a reached
limit as a 429 with its own code, a stream ending in `response.completed`. No
RPC and no network here."""
from __future__ import annotations

import json
import time

import pytest
from tc_ai_bridge import chatgpt_signin as signin
from tc_ai_bridge.ai_client import AIError, AIPlanLimitError, AITransportError
from tc_ai_bridge.chatgpt_plan_client import (
    LIMIT_CODE, ChatGPTPlanClient, plan_payload, read_event_stream,
)
from tc_ai_bridge.chatgpt_session import LIMIT_MESSAGE, ChatGPTSession
from tests.support.chatgpt import FakeHttp, isolated_settings, signed_in_result, token_body

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def _session(tmp_path, *, http: FakeHttp | None = None, expires_in: float = 3600) -> ChatGPTSession:
    session = ChatGPTSession(isolated_settings(tmp_path), http=http or FakeHttp(),
                             sign_in=lambda **kwargs: signed_in_result(expires_in=expires_in))
    session.start_sign_in()
    deadline = time.monotonic() + 5
    while session.state()["status"] == "signingIn" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert session.is_signed_in()
    return session


def _answer(inp: int = 100, out: int = 20, cached: int = 0) -> tuple[int, bytes]:
    return 200, json.dumps({
        "output": [{"content": [{"type": "output_text", "text": json.dumps({"ok": True})}]}],
        "usage": {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out,
                  "input_tokens_details": {"cached_tokens": cached}},
    }).encode("utf-8")


def _error(status: int, code: str, param: str = "", message: str = "") -> tuple[int, bytes]:
    return status, json.dumps({"error": {"code": code, "param": param, "message": message}}).encode("utf-8")


class Recorder:
    def __init__(self, answers):
        self.answers = list(answers)
        self.sent: list[dict] = []
        self.tokens: list[str] = []

    def __call__(self, url, headers, body, timeout):
        self.sent.append(json.loads(body.decode("utf-8")))
        self.tokens.append(headers["Authorization"])
        assert url == "https://api.openai.com/v1/responses"
        return self.answers.pop(0)


def _events(*events: dict) -> list[bytes]:
    lines: list[bytes] = []
    for event in events:
        lines += [f"event: {event['type']}\n".encode(), f"data: {json.dumps(event)}\n".encode(), b"\n"]
    return lines


def test_payload_is_reshaped_for_plan_usage_and_nothing_else_changes():
    base = {"model": "gpt-5.6-terra", "store": True, "instructions": "Review.", "input": "the verse",
            "text": {"format": {"type": "json_schema"}}, "reasoning": {"effort": "medium"},
            "prompt_cache_key": "project-1", "temperature": 0.2, "max_output_tokens": 500}
    shaped = plan_payload(base)
    assert shaped["input"] == [{"role": "user", "content": "the verse"}]
    assert shaped["stream"] is True and shaped["store"] is False
    assert "temperature" not in shaped and "max_output_tokens" not in shaped
    for kept in ("model", "instructions", "text", "reasoning", "prompt_cache_key"):
        assert shaped[kept] == base[kept]
    assert base["input"] == "the verse"  # the caller's payload is not edited

    # A list input is left as it is; an effort no plan model lists is dropped.
    listed = plan_payload({"input": [{"role": "user", "content": "x"}], "reasoning": {"effort": "none"}})
    assert listed["input"] == [{"role": "user", "content": "x"}] and "reasoning" not in listed


def test_stream_is_complete_only_at_response_completed():
    response = {"output": [], "usage": {"input_tokens": 5}}
    status, body = read_event_stream(_events(
        {"type": "response.created"}, {"type": "response.output_text.delta", "delta": "{"},
        {"type": "response.completed", "response": response},
    ))
    assert (status, body) == (200, response)

    with pytest.raises(AITransportError):  # cut off: never answered
        read_event_stream(_events({"type": "response.created"}, {"type": "response.output_text.delta", "delta": "{"}))
    with pytest.raises(AITransportError):
        read_event_stream([])


def test_stream_failures_become_the_status_a_plain_call_would_have_given():
    limit = {"type": "response.failed", "response": {"error": {"code": LIMIT_CODE, "message": "limit"}}}
    assert read_event_stream(_events(limit))[0] == 429
    busy = {"type": "error", "error": {"code": "subscription_sharing_usage_unavailable"}}
    assert read_event_stream(_events(busy))[0] == 503
    other = {"type": "response.failed", "response": {"error": {"code": "model_not_found"}}}
    status, body = read_event_stream(_events(other))
    assert status == 400 and body["error"]["code"] == "model_not_found"
    assert read_event_stream(_events({"type": "response.incomplete"}))[0] == 422


def test_a_request_carries_the_session_token_and_costs_no_dollars(tmp_path):
    transport = Recorder([_answer(inp=2075, out=153, cached=1792)])
    client = ChatGPTPlanClient(_session(tmp_path), model="gpt-5.6-terra", transport=transport)

    result = client._post_structured("Review this.", "the verse text", "probe", SCHEMA, prompt_cache_key="p-1")

    assert result == {"ok": True}
    [sent] = transport.sent
    assert transport.tokens == ["Bearer access-1"]
    assert sent["input"] == [{"role": "user", "content": "the verse text"}]
    assert sent["stream"] is True and sent["store"] is False
    assert sent["reasoning"] == {"effort": "medium"} and sent["prompt_cache_key"] == "p-1"
    assert sent["text"]["format"]["strict"] is True
    # Tokens are counted as on an API key; the plan is not billed per call.
    assert client.last_usage.total_tokens == 2228 and client.last_usage.cached_input_tokens == 1792
    assert client.last_cost_usd == 0.0


def test_a_reached_plan_limit_is_not_retried_and_then_holds_requests_back(tmp_path):
    session = _session(tmp_path)
    transport = Recorder([_error(429, LIMIT_CODE, message="limit reached"), _answer()])
    client = ChatGPTPlanClient(session, model="gpt-5.6-terra", transport=transport)

    with pytest.raises(AIPlanLimitError) as stopped:
        client._post_structured("Review.", "verse", "probe", SCHEMA)

    assert str(stopped.value) == LIMIT_MESSAGE
    assert len(transport.sent) == 1  # the base client would have sent it three times
    # The next verse of a job is refused before anything is sent.
    with pytest.raises(AIPlanLimitError):
        ChatGPTPlanClient(session, model="gpt-5.6-terra", transport=transport)._post_structured(
            "Review.", "next verse", "probe", SCHEMA)
    assert len(transport.sent) == 1
    assert isinstance(stopped.value, AIError)  # every existing `except AIError` still sees it


def test_an_ordinary_429_is_still_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    transport = Recorder([_error(429, "rate_limit_exceeded", message="slow down"), _answer()])
    client = ChatGPTPlanClient(_session(tmp_path), model="gpt-5.6-terra", transport=transport)
    assert client._post_structured("Review.", "verse", "probe", SCHEMA) == {"ok": True}
    assert len(transport.sent) == 2


def test_a_401_renews_the_token_once_and_sends_again(tmp_path):
    http = FakeHttp()
    http.queue_post(signin.TOKEN_URL, 200, token_body(access="access-2", refresh="refresh-2", with_id_token=False))
    transport = Recorder([(401, json.dumps({"detail": "token expired"}).encode()), _answer()])
    client = ChatGPTPlanClient(_session(tmp_path, http=http), model="gpt-5.6-terra", transport=transport)

    assert client._post_structured("Review.", "verse", "probe", SCHEMA) == {"ok": True}
    assert transport.tokens == ["Bearer access-1", "Bearer access-2"]

    # Refused again with the fresh token: reported, not looped.
    still = Recorder([(401, json.dumps({"detail": "no"}).encode()), (401, json.dumps({"detail": "no"}).encode())])
    again = ChatGPTPlanClient(_session(tmp_path / "second", http=http), model="gpt-5.6-terra", transport=still)
    with pytest.raises(AIError, match="HTTP 401: no"):
        again._post_structured("Review.", "verse", "probe", SCHEMA)
    assert len(still.sent) == 2


def test_a_lapsed_sign_in_stops_the_request_before_it_is_sent(tmp_path):
    http = FakeHttp()
    http.queue_post(signin.TOKEN_URL, 400, {"error": "invalid_grant", "error_reason": "refresh_token_invalidated"})
    transport = Recorder([_answer()])
    client = ChatGPTPlanClient(_session(tmp_path, http=http, expires_in=10), model="gpt-5.6-terra", transport=transport)
    with pytest.raises(AIPlanLimitError, match="Sign in again"):
        client._post_structured("Review.", "verse", "probe", SCHEMA)
    assert transport.sent == []


def test_a_field_the_plan_refuses_is_dropped_once_by_the_existing_fallback(tmp_path):
    transport = Recorder([
        _error(400, "subscription_sharing_unsupported_capability", param="prompt_cache_key"), _answer(),
    ])
    client = ChatGPTPlanClient(_session(tmp_path), model="gpt-5.6-terra", transport=transport)
    assert client._post_structured("Review.", "verse", "probe", SCHEMA, prompt_cache_key="p-1") == {"ok": True}
    assert "prompt_cache_key" in transport.sent[0] and "prompt_cache_key" not in transport.sent[1]
    assert client.prompt_cache_key_unsupported is True


def test_refusals_are_reported_in_words_a_reviewer_can_act_on(tmp_path):
    cases = {
        "Choose another in Settings": _error(400, "model_not_found"),
        "ChatGPT Plus or Pro is needed": _error(403, "subscription_sharing_user_not_eligible"),
        "Input must be a list": (400, json.dumps({"detail": "Input must be a list"}).encode()),
    }
    for index, (expected, answer) in enumerate(cases.items()):
        client = ChatGPTPlanClient(_session(tmp_path / str(index)), model="gpt-5.6-terra",
                                   transport=Recorder([answer]))
        with pytest.raises(AIError, match=expected):
            client._post_structured("Review.", "verse", "probe", SCHEMA)
