"""#506: Sign in with ChatGPT through the engine's protocol.

The five `ai.chatgpt.*` methods, what `settings.get` says about readiness, and
which client `_ai_client` builds for each provider. The session's provider is a
fake and its browser sign-in an injected function (tests/support/chatgpt.py);
the request path of the plan client is in tests/ai/test_chatgpt_plan_client.py."""
from __future__ import annotations

import time

import pytest
from bridge_service import BridgeEngine
from tc_ai_bridge.ai_client import AIError, OpenAIResponsesClient
from tc_ai_bridge.chatgpt_plan_client import ChatGPTPlanClient
from tc_ai_bridge.chatgpt_session import ChatGPTSession
from tc_ai_bridge.chatgpt_signin import SignInError
from tests.support import chatgpt as fake
from tests.support.projects import call


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    engine = BridgeEngine(settings=fake.isolated_settings(tmp_path))
    engine._chatgpt = ChatGPTSession(
        engine.settings, http=fake.FakeHttp(), sign_in=lambda **kwargs: fake.signed_in_result(),
    )
    return engine


def rpc(engine, method, params=None):
    response = call(engine, method, params)
    assert response.get("error") is None, response
    return response["result"]


def _sign_in(engine) -> dict:
    assert rpc(engine, "ai.chatgpt.signIn")["status"] in {"signingIn", "signedIn"}
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = rpc(engine, "ai.chatgpt.status")
        if state["status"] != "signingIn":
            return state
        time.sleep(0.01)
    raise AssertionError("sign-in did not finish")


def test_settings_report_ai_readiness_separately_from_the_api_key(engine):
    settings = rpc(engine, "settings.get")
    assert settings["hasApiKey"] is False and settings["aiReady"] is False
    assert settings["chatgpt"]["status"] == "signedOut"

    rpc(engine, "settings.set", {"apiKey": "sk-test-key-000000"})
    settings = rpc(engine, "settings.get")
    assert settings["hasApiKey"] is True and settings["aiReady"] is True

    # On the ChatGPT account an API key alone does not make AI ready.
    rpc(engine, "settings.set", {"provider": "chatgpt"})
    settings = rpc(engine, "settings.get")
    assert settings["hasApiKey"] is True and settings["aiReady"] is False


def test_sign_in_makes_ai_ready_and_switches_the_client(engine):
    rpc(engine, "settings.set", {"provider": "chatgpt"})
    with pytest.raises(AIError, match="Sign in with ChatGPT"):
        engine._ai_client()

    state = _sign_in(engine)

    assert state["status"] == "signedIn" and state["email"] == fake.EMAIL
    settings = rpc(engine, "settings.get")
    assert settings["aiReady"] is True and settings["hasApiKey"] is False
    assert settings["chatgpt"]["email"] == fake.EMAIL
    client = engine._ai_client("review")
    assert isinstance(client, ChatGPTPlanClient) and client.model == engine.settings.model
    assert client.session is engine.chatgpt_session


def test_an_api_key_provider_is_untouched_by_a_chatgpt_sign_in(engine):
    _sign_in(engine)
    rpc(engine, "settings.set", {"provider": "openai", "apiKey": "sk-test-key-000000"})
    client = engine._ai_client()
    assert type(client) is OpenAIResponsesClient and client.api_key == "sk-test-key-000000"
    assert engine._ai_halt_reason() == ""


def test_models_are_listed_for_the_signed_in_account(engine):
    rpc(engine, "settings.set", {"provider": "chatgpt"})
    signed_out = rpc(engine, "ai.chatgpt.models")
    assert signed_out["models"] == [] and signed_out["error"]["code"] == "signed_out"

    _sign_in(engine)
    listed = rpc(engine, "ai.chatgpt.models")
    assert listed["error"] is None
    assert [model["slug"] for model in listed["models"]] == ["gpt-6.2-sol", "gpt-5.6-terra"]


def test_sign_out_ends_ai_readiness(engine):
    rpc(engine, "settings.set", {"provider": "chatgpt"})
    _sign_in(engine)
    state = rpc(engine, "ai.chatgpt.signOut")
    assert state["status"] == "signedOut" and state["email"] == ""
    assert rpc(engine, "settings.get")["aiReady"] is False
    with pytest.raises(AIError):
        engine._ai_client()


def test_a_refused_sign_in_is_reported_on_status_not_raised(engine):
    def free_account(**kwargs):
        raise SignInError.for_exchange(400, {"error": "invalid_grant"})

    engine._chatgpt = ChatGPTSession(engine.settings, http=fake.FakeHttp(), sign_in=free_account)
    state = _sign_in(engine)
    assert state["status"] == "signedOut" and "Plus or Pro" in state["error"]["message"]


def test_the_plan_limit_is_the_reason_a_job_would_stop(engine):
    rpc(engine, "settings.set", {"provider": "chatgpt"})
    _sign_in(engine)
    assert engine._ai_halt_reason() == ""
    engine.chatgpt_session.note_limit_reached()
    assert "plan limit" in engine._ai_halt_reason()
    assert rpc(engine, "ai.chatgpt.status")["limitReached"] is True


def test_cancelling_when_nothing_is_running_is_harmless(engine):
    assert rpc(engine, "ai.chatgpt.cancelSignIn")["status"] == "signedOut"
