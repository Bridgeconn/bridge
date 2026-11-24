"""#506: the Sign in with ChatGPT protocol (`tc_ai_bridge.chatgpt_signin`).

Everything here runs against a fake of the provider (`tests/support/chatgpt.py`)
and a loopback listener on a free port; nothing reaches the network. What these
tests cannot show is that OpenAI behaves as the fake does: that was seen on the
live runs recorded in docs/BUILD_LOG.md (2026-11-23), which is where the fake's
behaviour comes from."""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from tc_ai_bridge import chatgpt_signin as signin
from tc_ai_bridge.chatgpt_signin import SignInError
from tests.support.chatgpt import (
    CLIENT_ID, EMAIL, JWKS, SUBJECT, FakeHttp, id_token, sign_id_token, token_body,
)


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def _get(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def _browser(answer: dict[str, str], seen: dict[str, str]):
    """A stand-in for the person's browser: reads the authorization address and
    calls the loopback redirect with `answer` plus the request's own state."""
    def open_browser(url: str) -> None:
        request = _query(url)
        seen.update(request)
        back = urlencode({"state": request["state"], **answer})
        threading.Thread(target=_get, args=(f"{request['redirect_uri']}?{back}",), daemon=True).start()
    return open_browser


def test_pkce_challenge_matches_the_rfc_7636_example():
    assert signin.pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == \
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_first_sign_in_registers_and_a_later_one_reuses_the_client_id():
    first = _query(signin.authorize_url(client_id="", redirect_uri="http://127.0.0.1:1455/auth/callback",
                                        state="s", nonce="n", challenge="c"))
    assert first["client_id"] == "dynamic_agent_client"
    assert first["agent_name_hint"] == "Bridge"
    assert first["scope"] == signin.SCOPES and first["resource"] == "https://api.openai.com/v1"
    assert first["code_challenge_method"] == "S256" and first["response_type"] == "code"
    # The live runs registered without it, as OpenAI's reference client does by default.
    assert "ext_agent_host_id" not in first

    again = _query(signin.authorize_url(client_id=CLIENT_ID, redirect_uri="http://127.0.0.1:1455/auth/callback",
                                        state="s", nonce="n", challenge="c", login_hint=EMAIL))
    assert again["client_id"] == CLIENT_ID
    assert "agent_name_hint" not in again
    assert again["login_hint"] == EMAIL


def test_listener_takes_the_first_answer_with_the_right_state_only():
    listener = signin.CallbackListener("right-state", port=0)
    try:
        assert listener.redirect_uri.startswith("http://127.0.0.1:")
        assert _get(f"{listener.redirect_uri}?state=wrong&code=stolen") == 400
        assert _get(listener.redirect_uri.replace("/auth/callback", "/other") + "?state=right-state&code=x") == 404
        assert _get(f"{listener.redirect_uri}?state=right-state&code=first") == 200
        assert _get(f"{listener.redirect_uri}?state=right-state&code=second") == 400
        assert listener.wait(2)["code"] == "first"
    finally:
        listener.close()


def test_listener_stops_waiting_when_cancelled_or_out_of_time():
    listener = signin.CallbackListener("state", port=0)
    try:
        with pytest.raises(SignInError) as timed_out:
            listener.wait(0.3)
        assert timed_out.value.code == "timed_out"
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(SignInError) as cancelled:
            listener.wait(5, cancel)
        assert cancelled.value.code == "cancelled"
    finally:
        listener.close()


def test_sign_in_exchanges_the_code_and_verifies_the_identity():
    http = FakeHttp()
    seen: dict[str, str] = {}
    registered: list[str] = []

    class NonceAwareHttp(FakeHttp):
        def post_form(self, url, fields, timeout=30.0):
            self.posts.append((url, dict(fields)))
            # The registration is reported before the code is exchanged.
            assert registered == [CLIENT_ID]
            return 200, token_body(nonce=seen["nonce"])

    http = NonceAwareHttp()
    result = signin.sign_in(
        http=http, open_browser=_browser({"code": "the-code", "client_id": CLIENT_ID, "scope": signin.SCOPES}, seen),
        on_registration=registered.append, timeout=5,
    )

    assert result.new_registration and result.client_id == CLIENT_ID
    assert (result.subject, result.email) == (SUBJECT, EMAIL)
    assert result.tokens.access_token == "access-1" and result.tokens.refresh_token == "refresh-1"
    assert signin.PLAN_SCOPE in result.tokens.scopes
    [exchange] = http.posted(signin.TOKEN_URL)
    assert exchange == {
        "grant_type": "authorization_code", "client_id": CLIENT_ID, "code": "the-code",
        "code_verifier": exchange["code_verifier"], "redirect_uri": seen["redirect_uri"],
        "resource": "https://api.openai.com/v1",
    }
    assert signin.pkce_challenge(exchange["code_verifier"]) == seen["code_challenge"]


def test_a_free_account_is_told_the_plan_it_needs_and_keeps_its_registration():
    """Seen live: a Free account passes the whole browser sign-in and is refused
    at the exchange with a bare invalid_grant."""
    http = FakeHttp()
    http.queue_post(signin.TOKEN_URL, 400, {"error": "invalid_grant"})
    registered: list[str] = []
    with pytest.raises(SignInError) as refused:
        signin.sign_in(http=http, open_browser=_browser({"code": "c", "client_id": CLIENT_ID}, {}),
                       on_registration=registered.append, timeout=5)
    assert refused.value.code == "invalid_grant"
    assert "Plus or Pro" in str(refused.value)
    assert registered == [CLIENT_ID]


def test_sign_in_refuses_a_denied_or_mismatched_answer():
    with pytest.raises(SignInError) as denied:
        signin.sign_in(http=FakeHttp(), open_browser=_browser({"error": "access_denied"}, {}), timeout=5)
    assert denied.value.code == "access_denied"

    with pytest.raises(SignInError) as incomplete:
        signin.sign_in(http=FakeHttp(), open_browser=_browser({"code": "c"}, {}), timeout=5)
    assert incomplete.value.code == "registration_incomplete"

    with pytest.raises(SignInError) as mismatch:
        signin.sign_in(http=FakeHttp(), client_id=CLIENT_ID,
                       open_browser=_browser({"code": "c", "client_id": "oaiapp_someone_else"}, {}), timeout=5)
    assert mismatch.value.code == "registration_mismatch"


def test_sign_in_refuses_a_different_account_than_the_one_signed_in():
    seen: dict[str, str] = {}

    class OtherAccount(FakeHttp):
        def post_form(self, url, fields, timeout=30.0):
            body = token_body()
            body["id_token"] = id_token(nonce=seen["nonce"], subject="someone-else")
            return 200, body

    with pytest.raises(SignInError) as mismatch:
        signin.sign_in(http=OtherAccount(), client_id=CLIENT_ID, expected_subject=SUBJECT,
                       open_browser=_browser({"code": "c"}, seen), timeout=5)
    assert mismatch.value.code == "account_mismatch"


def test_id_token_is_accepted_only_with_a_good_signature_and_claims():
    good = id_token(nonce="n-1")
    assert signin.verify_id_token(good, client_id=CLIENT_ID, jwks=JWKS, nonce="n-1")["sub"] == SUBJECT
    # A refresh has no nonce to check.
    assert signin.verify_id_token(good, client_id=CLIENT_ID, jwks=JWKS)["email"] == EMAIL

    header, payload, signature = good.split(".")
    flipped = signature[:-2] + ("AA" if not signature.endswith("AA") else "BB")
    forged_payload = id_token(nonce="n-1", subject="attacker").split(".")[1]
    bad = {
        "tampered signature": f"{header}.{payload}.{flipped}",
        "payload swapped under another signature": f"{header}.{forged_payload}.{signature}",
        "wrong nonce": id_token(nonce="other"),
        "another app's audience": id_token(nonce="n-1", client_id="oaiapp_other"),
        "expired": id_token(nonce="n-1", expires_in=-60),
        "wrong issuer": id_token(nonce="n-1", iss="https://example.com"),
        "unsigned algorithm": sign_id_token({"iss": signin.ISSUER, "aud": CLIENT_ID, "sub": SUBJECT,
                                             "exp": time.time() + 60, "nonce": "n-1"}, alg="none"),
        "unknown key": sign_id_token({"iss": signin.ISSUER, "aud": CLIENT_ID, "sub": SUBJECT,
                                      "exp": time.time() + 60, "nonce": "n-1"}, kid="not-published"),
        "not a token": "nonsense",
    }
    for name, token in bad.items():
        with pytest.raises(SignInError):
            signin.verify_id_token(token, client_id=CLIENT_ID, jwks=JWKS, nonce="n-1")
            pytest.fail(f"accepted: {name}")


def test_identity_cannot_be_verified_without_the_provider_keys():
    http = FakeHttp()
    http.get_answers[signin.JWKS_URL] = [(503, {})]
    with pytest.raises(SignInError) as unavailable:
        signin.fetch_jwks(http)
    assert unavailable.value.code == "identity_verification_unavailable"


def test_refresh_returns_the_rotated_token_set():
    http = FakeHttp()
    http.queue_post(signin.TOKEN_URL, 200, token_body(access="access-2", refresh="refresh-2", with_id_token=False))
    old = signin.Tokens("access-1", "refresh-1", "kept-id-token", time.time() + 10, signin.SCOPES.split())

    renewed = signin.refresh(http=http, client_id=CLIENT_ID, tokens=old)

    assert (renewed.access_token, renewed.refresh_token) == ("access-2", "refresh-2")
    assert renewed.id_token == "kept-id-token"
    assert renewed.expires_at > time.time() + 3000
    assert http.posted(signin.TOKEN_URL) == [{
        "grant_type": "refresh_token", "client_id": CLIENT_ID, "refresh_token": "refresh-1",
        "resource": "https://api.openai.com/v1",
    }]


def test_a_refused_refresh_says_whether_the_person_must_sign_in_again():
    tokens = signin.Tokens("a", "r", "", time.time(), signin.SCOPES.split())
    http = FakeHttp()
    # The shape other clients report after the token has sat unused for hours.
    http.queue_post(signin.TOKEN_URL, 400, {"error": "invalid_grant", "error_reason": "refresh_token_invalidated"})
    with pytest.raises(SignInError) as lapsed:
        signin.refresh(http=http, client_id=CLIENT_ID, tokens=tokens)
    assert lapsed.value.reauth and "Sign in again" in str(lapsed.value)

    busy = FakeHttp()
    busy.queue_post(signin.TOKEN_URL, 503, {"error": "temporarily_unavailable"})
    with pytest.raises(SignInError) as later:
        signin.refresh(http=busy, client_id=CLIENT_ID, tokens=tokens)
    assert not later.value.reauth


def test_tokens_without_plan_permission_are_refused():
    http = FakeHttp()
    http.queue_post(signin.TOKEN_URL, 200, token_body(scope="openid profile email offline_access"))
    with pytest.raises(SignInError) as refused:
        signin.refresh(http=http, client_id=CLIENT_ID,
                       tokens=signin.Tokens("a", "r", "", time.time(), ["openid"]))
    assert refused.value.code == "plan_use_not_granted"


def test_revoke_reports_whether_the_provider_confirmed():
    tokens = signin.Tokens("a", "refresh-9", "", time.time(), [])
    http = FakeHttp()
    http.queue_post(signin.REVOKE_URL, 200, {})
    assert signin.revoke(http=http, client_id=CLIENT_ID, tokens=tokens) is True
    assert http.posted(signin.REVOKE_URL) == [{
        "token": "refresh-9", "token_type_hint": "refresh_token", "client_id": CLIENT_ID,
    }]
    assert signin.revoke(http=FakeHttp(), client_id=CLIENT_ID, tokens=tokens) is False


def test_model_list_keeps_listed_models_in_the_provider_order():
    http = FakeHttp()
    models = signin.list_models(http=http, access_token="access-1")
    assert [model["slug"] for model in models] == ["gpt-6.2-sol", "gpt-5.6-terra"]
    assert models[0] == {"slug": "gpt-6.2-sol", "displayName": "GPT-6.2-Sol",
                         "reasoningEfforts": ["low", "medium", "high"], "contextWindow": 500000}
    assert http.gets[-1] == (f"{signin.API_BASE}/models", "access-1")

    refused = FakeHttp()
    refused.get_answers[f"{signin.API_BASE}/models"] = [(401, {"detail": "bad token"})]
    with pytest.raises(SignInError) as unauthorised:
        signin.list_models(http=refused, access_token="stale")
    assert unauthorised.value.reauth
