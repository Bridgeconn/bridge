"""Shared pieces for the Sign in with ChatGPT tests (#506): a fake of the
provider's HTTP endpoints, a throwaway RSA key to sign ID tokens with, and a
settings object in a temp folder. No test here touches the network."""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from tc_ai_bridge import chatgpt_signin as signin
from tc_ai_bridge.secret_store import AppSettings

# A 2048-bit RSA key generated for these tests and used nowhere else. It signs
# the fake provider's ID tokens; `JWKS` is its public half.
TEST_KEY_N = int(
    "c333f51fd8fd0a55b5266cb6d9a13e80f17c47b89a1ee8d73c3ab0c767abf6ad142ca24aa0a47652cf406c0044fd29d9"
    "ab358b4719eabc2829a61b867f5532d52fdc7cbd9361bfeda1d0bedf008a7a6bb9dadc7af306c040b84721feba4a3a1f"
    "c9929c914f96de588765c191f7411502582ef1ecef36f284b3e0872cc86b2c9cb0f1de15314b7c091c3b403a6a092aa9"
    "465b54a37bab3b8f1745987deb979405de9eeff91b6a1e200c861b6da06933793277e7da317791bf350833c30cfd1258"
    "43578e4eb0465571df88f2b97e49b4722b51cec6e92440bef678701e184b84059998a2cfa1dbee7df654a52b222cd95f"
    "85aa55574fca17380c534561c0415ef3"
    , 16)
TEST_KEY_D = int(
    "54932f72840666b2e9d0e32b7a3195ae3272e174473a7b31be43c3923205dcd3f2b8bffc4b8bd6445ccd91bdb0266c3a"
    "8626a5d8c18ee5c514fe865088dcf6304e135eec986db2c597e5a4bd64339b850f3a976aa1df5beeeea8cb3edda2097a"
    "fa500e8c1b0ac7fd5d74a620c31b2caa1e6100aae29e51075414451d0f1cf86f8cf18d68020c1b772c03e9d790089f4a"
    "9f64aa9a76acf8493f6a76b157cf2476f71ed867592a95bb08187d3d66632cbfa95c792c50d2a11d0d58629f4ce00861"
    "8f390cefdcdf5bddd1ee1b646ee7be78d89c24a7f879888eeeedf3610fff672e8aa20c7e71b635c29767bb5b625bdb2b"
    "a933083e7fed08989934d579fa059b39"
    , 16)
TEST_KEY_E = 65537
KEY_ID = "test-key-1"
CLIENT_ID = "oaiapp_test_client"
SUBJECT = "user-123"
EMAIL = "translator@example.org"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _int_b64(value: int) -> str:
    return b64url(value.to_bytes((value.bit_length() + 7) // 8, "big"))


JWKS: dict[str, Any] = {"keys": [{"kty": "RSA", "kid": KEY_ID, "alg": "RS256", "use": "sig",
                                  "n": _int_b64(TEST_KEY_N), "e": _int_b64(TEST_KEY_E)}]}


def sign_id_token(claims: dict[str, Any], *, kid: str = KEY_ID, alg: str = "RS256") -> str:
    header = b64url(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode("utf-8"))
    payload = b64url(json.dumps(claims).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    size = (TEST_KEY_N.bit_length() + 7) // 8
    digest = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(signing_input).digest()
    padded = b"\x00\x01" + b"\xff" * (size - len(digest) - 3) + b"\x00" + digest
    signature = pow(int.from_bytes(padded, "big"), TEST_KEY_D, TEST_KEY_N).to_bytes(size, "big")
    return f"{header}.{payload}.{b64url(signature)}"


def id_token(*, nonce: str = "", client_id: str = CLIENT_ID, subject: str = SUBJECT, email: str = EMAIL,
             expires_in: float = 3600, **extra: Any) -> str:
    claims: dict[str, Any] = {"iss": signin.ISSUER, "aud": client_id, "sub": subject, "email": email,
                              "name": "Test Translator", "iat": time.time(), "exp": time.time() + expires_in}
    if nonce:
        claims["nonce"] = nonce
    claims.update(extra)
    return sign_id_token(claims)


def token_body(*, access: str = "access-1", refresh: str = "refresh-1", nonce: str = "",
               scope: str = signin.SCOPES, expires_in: int = 3600, with_id_token: bool = True) -> dict[str, Any]:
    body: dict[str, Any] = {"access_token": access, "refresh_token": refresh, "token_type": "Bearer",
                            "expires_in": expires_in, "scope": scope}
    if with_id_token:
        body["id_token"] = id_token(nonce=nonce)
    return body


MODEL_ROWS = [
    {"slug": "gpt-6.2-sol", "display_name": "GPT-6.2-Sol", "visibility": "list", "context_window": 500000,
     "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"}, {"effort": "high"}]},
    {"slug": "gpt-5.6-terra", "display_name": "GPT-5.6-Terra", "visibility": "list", "context_window": 272000,
     "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"}]},
    {"slug": "internal-only", "display_name": "Hidden", "visibility": "hide"},
]


class FakeHttp(signin.Http):
    """Answers from queues keyed by URL, and records what was asked. A URL with
    nothing queued answers 500, so an unexpected call fails the test loudly."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, str]]] = []
        self.gets: list[tuple[str, str]] = []
        self.post_answers: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        self.get_answers: dict[str, list[tuple[int, dict[str, Any]]]] = {
            signin.JWKS_URL: [(200, JWKS)],
            f"{signin.API_BASE}/models": [(200, {"models": MODEL_ROWS})],
        }

    def queue_post(self, url: str, status: int, body: dict[str, Any]) -> None:
        self.post_answers.setdefault(url, []).append((status, body))

    def queue_get(self, url: str, status: int, body: dict[str, Any]) -> None:
        self.get_answers.setdefault(url, []).append((status, body))

    @staticmethod
    def _next(answers: list[tuple[int, dict[str, Any]]] | None) -> tuple[int, dict[str, Any]]:
        if not answers:
            return 500, {"error": "nothing queued for this call"}
        # The last queued answer repeats, so a test need not count calls.
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def post_form(self, url: str, fields: dict[str, str], timeout: float = 30.0) -> tuple[int, dict[str, Any]]:
        self.posts.append((url, dict(fields)))
        return self._next(self.post_answers.get(url))

    def get_json(self, url: str, bearer: str = "", timeout: float = 30.0) -> tuple[int, dict[str, Any]]:
        self.gets.append((url, bearer))
        return self._next(self.get_answers.get(url))

    def posted(self, url: str) -> list[dict[str, str]]:
        return [fields for sent_url, fields in self.posts if sent_url == url]


def isolated_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(path=tmp_path / "settings.json")


def signed_in_result(*, access: str = "access-1", refresh: str = "refresh-1", expires_in: float = 3600,
                     new_registration: bool = True) -> signin.SignInResult:
    tokens = signin.Tokens(access, refresh, id_token(), time.time() + expires_in, signin.SCOPES.split())
    return signin.SignInResult(CLIENT_ID, tokens, SUBJECT, EMAIL, "Test Translator", new_registration)
