"""#506: the ChatGPT sign-in an installation holds (`tc_ai_bridge.chatgpt_session`).

The provider is a fake and the browser sign-in is an injected function, so
these cover what Bridge keeps and decides: where tokens are stored, when one is
renewed, what happens when a renewal is refused, and the pause after the plan's
limit. The protocol itself is in test_chatgpt_signin.py."""
from __future__ import annotations

import os
import threading
import time

import pytest
from tc_ai_bridge import chatgpt_signin as signin
from tc_ai_bridge.chatgpt_session import LIMIT_MESSAGE, LIMIT_PAUSE_SECONDS, ChatGPTSession
from tc_ai_bridge.chatgpt_signin import SignInError
from tc_ai_bridge.secret_store import AppSettings
from tests.support.chatgpt import CLIENT_ID, EMAIL, FakeHttp, isolated_settings, signed_in_result, token_body


def _wait_until_done(session: ChatGPTSession, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = session.state()
        if state["status"] != "signingIn":
            return state
        time.sleep(0.01)
    raise AssertionError("sign-in did not finish")


def _signed_in(tmp_path, *, expires_in: float = 3600, http: FakeHttp | None = None, clock=time.time):
    settings = isolated_settings(tmp_path)
    session = ChatGPTSession(settings, http=http or FakeHttp(), clock=clock,
                             sign_in=lambda **kwargs: signed_in_result(expires_in=expires_in))
    session.start_sign_in()
    assert _wait_until_done(session)["status"] == "signedIn"
    return settings, session


def test_signed_out_until_a_sign_in_completes(tmp_path):
    settings = isolated_settings(tmp_path)
    session = ChatGPTSession(settings, http=FakeHttp(), sign_in=lambda **kwargs: signed_in_result())
    assert session.state()["status"] == "signedOut"
    assert not session.is_signed_in()

    session.start_sign_in()
    state = _wait_until_done(session)

    assert state["status"] == "signedIn" and state["email"] == EMAIL and state["error"] is None
    assert session.access_token() == "access-1"
    # Nothing the UI is sent names a token or the client id.
    assert "access-1" not in str(state) and "refresh-1" not in str(state) and CLIENT_ID not in str(state)


def test_tokens_are_never_written_in_plain_text(tmp_path):
    settings, _session = _signed_in(tmp_path)
    on_disk = (tmp_path / "settings.json").read_text("utf-8")
    assert "access-1" not in on_disk and "refresh-1" not in on_disk
    # The identity and the issued client id are ordinary settings, not secrets.
    assert settings.chatgpt_connection["clientId"] == CLIENT_ID

    reopened = AppSettings(path=tmp_path / "settings.json")
    assert reopened.chatgpt_connection["email"] == EMAIL
    if os.name == "nt":  # DPAPI: the sign-in survives a restart
        assert ChatGPTSession(reopened, http=FakeHttp()).is_signed_in()
        assert reopened.get_chatgpt_tokens()["refresh_token"] == "refresh-1"
    else:  # no DPAPI: held for the session only, like the API key
        assert reopened.get_chatgpt_tokens() == {}


def test_the_address_is_shown_while_signing_in_and_a_second_start_does_not_restart_it(tmp_path):
    release = threading.Event()
    starts: list[int] = []

    def slow_sign_in(**kwargs):
        starts.append(1)
        kwargs["on_url"]("https://auth.example/authorize?state=abc")
        assert release.wait(5)
        return signed_in_result()

    session = ChatGPTSession(isolated_settings(tmp_path), http=FakeHttp(), sign_in=slow_sign_in)
    session.start_sign_in()
    deadline = time.monotonic() + 5
    while not session.state()["signInUrl"] and time.monotonic() < deadline:
        time.sleep(0.01)
    state = session.start_sign_in()
    assert state["status"] == "signingIn" and state["signInUrl"].startswith("https://auth.example/")
    release.set()
    assert _wait_until_done(session)["status"] == "signedIn"
    assert starts == [1]


def test_a_refused_sign_in_shows_why_and_keeps_the_registration(tmp_path):
    settings = isolated_settings(tmp_path)

    def free_account(**kwargs):
        kwargs["on_registration"](CLIENT_ID)
        raise SignInError.for_exchange(400, {"error": "invalid_grant"})

    session = ChatGPTSession(settings, http=FakeHttp(), sign_in=free_account)
    session.start_sign_in()
    state = _wait_until_done(session)

    assert state["status"] == "signedOut"
    assert state["error"]["code"] == "invalid_grant" and "Plus or Pro" in state["error"]["message"]
    assert settings.chatgpt_connection == {"clientId": CLIENT_ID}

    # The next attempt signs in with the client id already issued.
    seen: dict = {}
    retry = ChatGPTSession(settings, http=FakeHttp(),
                           sign_in=lambda **kwargs: seen.update(kwargs) or signed_in_result())
    retry.start_sign_in()
    assert _wait_until_done(retry)["status"] == "signedIn"
    assert seen["client_id"] == CLIENT_ID


def test_a_cancelled_sign_in_is_not_an_error(tmp_path):
    def wait_for_cancel(**kwargs):
        assert kwargs["cancel"].wait(5)
        raise SignInError("cancelled", "Sign-in was cancelled.")

    session = ChatGPTSession(isolated_settings(tmp_path), http=FakeHttp(), sign_in=wait_for_cancel)
    session.start_sign_in()
    state = session.cancel_sign_in()
    assert state["status"] == "signedOut" and state["error"] is None


def test_a_fresh_token_is_reused_and_one_near_expiry_is_renewed_and_stored_first(tmp_path):
    http = FakeHttp()
    settings, session = _signed_in(tmp_path, http=http)
    assert session.access_token() == "access-1"
    assert http.posted(signin.TOKEN_URL) == []

    now = [time.time()]
    http = FakeHttp()
    http.queue_post(signin.TOKEN_URL, 200, token_body(access="access-2", refresh="refresh-2", with_id_token=False))
    settings, session = _signed_in(tmp_path / "expiring", expires_in=3600, http=http, clock=lambda: now[0])
    now[0] += 3600 - 60  # inside the renewal margin

    assert session.access_token() == "access-2"
    assert http.posted(signin.TOKEN_URL)[0]["refresh_token"] == "refresh-1"
    # The rotated refresh token is what is stored: the old one is spent.
    assert settings.get_chatgpt_tokens()["refresh_token"] == "refresh-2"
    assert session.access_token() == "access-2"
    assert len(http.posted(signin.TOKEN_URL)) == 1


def test_a_lapsed_sign_in_asks_for_sign_in_again_and_stops_jobs(tmp_path):
    http = FakeHttp()
    http.queue_post(signin.TOKEN_URL, 400, {"error": "invalid_grant", "error_reason": "refresh_token_invalidated"})
    settings, session = _signed_in(tmp_path, expires_in=10, http=http)

    with pytest.raises(SignInError) as lapsed:
        session.access_token()

    assert lapsed.value.reauth
    state = session.state()
    assert state["status"] == "reauthRequired" and "Sign in again" in state["error"]["message"]
    assert settings.get_chatgpt_tokens() == {}
    assert "Sign in again" in session.halt_reason()
    # The registration and the identity are kept for the next sign-in.
    assert settings.chatgpt_connection["clientId"] == CLIENT_ID and state["email"] == EMAIL


def test_a_passing_outage_does_not_sign_the_person_out(tmp_path):
    http = FakeHttp()
    http.queue_post(signin.TOKEN_URL, 503, {"error": "temporarily_unavailable"})
    _settings, session = _signed_in(tmp_path, expires_in=10, http=http)
    with pytest.raises(SignInError) as later:
        session.access_token()
    assert not later.value.reauth
    assert session.state()["status"] == "signedIn"


def test_the_plan_limit_pauses_requests_and_then_lets_one_through(tmp_path):
    now = [1_000_000.0]
    _settings, session = _signed_in(tmp_path, clock=lambda: now[0])
    assert session.halt_reason() == ""

    session.note_limit_reached()

    assert session.halt_reason() == LIMIT_MESSAGE
    state = session.state()
    assert state["limitReached"] and state["limitMessage"] == LIMIT_MESSAGE and state["usageUrl"]
    now[0] += LIMIT_PAUSE_SECONDS + 1
    assert session.halt_reason() == "" and not session.state()["limitReached"]


def test_sign_out_revokes_the_current_token_and_keeps_the_registration(tmp_path):
    http = FakeHttp()
    http.queue_post(signin.REVOKE_URL, 200, {})
    settings, session = _signed_in(tmp_path, http=http)

    state = session.sign_out()

    assert state["status"] == "signedOut" and state["error"] is None and state["email"] == ""
    assert http.posted(signin.REVOKE_URL)[0]["token"] == "refresh-1"
    assert settings.get_chatgpt_tokens() == {} and settings.chatgpt_connection == {"clientId": CLIENT_ID}
    with pytest.raises(SignInError):
        session.access_token()


def test_sign_out_ends_the_sign_in_here_even_when_the_provider_does_not_confirm(tmp_path):
    settings, session = _signed_in(tmp_path)  # nothing queued for the revoke call: it answers 500
    state = session.sign_out()
    assert state["status"] == "signedOut" and state["error"]["code"] == "revocation_unconfirmed"
    assert settings.get_chatgpt_tokens() == {}


def test_models_are_fetched_once_and_cached(tmp_path):
    http = FakeHttp()
    _settings, session = _signed_in(tmp_path, http=http)
    assert [model["slug"] for model in session.models()] == ["gpt-6.2-sol", "gpt-5.6-terra"]
    session.models()
    assert len([url for url, _ in http.gets if url.endswith("/models")]) == 1
    session.models(refresh=True)
    assert len([url for url, _ in http.gets if url.endswith("/models")]) == 2
