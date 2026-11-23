"""Sign in with ChatGPT: the protocol, and nothing of Bridge's state (#506).

OpenAI lets an open-source app that runs on the person's own computer spend a
ChatGPT Plus or Pro plan's allowance through the Responses API. This module is
the sign-in half: an authorization-code flow with PKCE and a loopback redirect,
a one-time dynamic client registration, token refresh and revocation, the model
catalogue, and verification of the ID token. `chatgpt_session.py` owns what is
kept between calls; `chatgpt_plan_client.py` sends the requests.

Written from OpenAI's documented contract and from what
`scripts/spike_chatgpt_signin.py` saw on live runs (docs/BUILD_LOG.md,
2026-11-23). OpenAI's reference client is under a noncommercial licence and none
of it is here.

What the live runs showed that the pages do not say, and this module relies on:

- A Free account is let through the whole browser sign-in and is refused only at
  the code exchange, with a bare `invalid_grant`. `SignInError.for_exchange`
  turns that into a sentence about the plan.
- `ext_agent_host_id` is not needed; the registration works without it.
- Signing in again with the saved client id does not register a second client.

Stdlib only: the frozen engine must not grow a dependency for an optional
feature, so the ID token's RS256 signature is checked here in plain integers
(`pow(s, e, n)` and an exact comparison with the expected padded digest).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit

from . import ai_http

ISSUER = 'https://auth.openai.com'
AUTHORIZE_URL = f'{ISSUER}/api/accounts/authorize'
TOKEN_URL = f'{ISSUER}/api/accounts/oauth/token'
REVOKE_URL = f'{ISSUER}/api/accounts/oauth/revoke'
JWKS_URL = f'{ISSUER}/.well-known/jwks.json'
API_BASE = 'https://api.openai.com/v1'
RESOURCE = API_BASE
PLAN_SCOPE = 'chatgpt.tokens.use.direct'
SCOPES = f'openid profile email offline_access resource.invoke {PLAN_SCOPE}'
REGISTRATION_CLIENT = 'dynamic_agent_client'
APP_NAME = 'Bridge'
CALLBACK_PATH = '/auth/callback'
# The port OpenAI's examples use. Tried first; any free port is used when it is
# taken (another app's sign-in, usually).
PREFERRED_PORT = 1455
USER_AGENT = 'Bridge'
USAGE_URL = 'https://chatgpt.com/settings/usage'

# What a refused refresh means: the saved sign-in can no longer be renewed.
REAUTH_CODES = frozenset({
    'invalid_grant', 'invalid_refresh_token', 'token_expired', 'refresh_token_expired',
    'refresh_token_invalidated', 'refresh_token_reused',
})


class SignInError(RuntimeError):
    """A sign-in step failed. `code` is the provider's word for it (or ours);
    the message is written for the person in front of Settings."""

    def __init__(self, code: str, message: str, *, reauth: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.reauth = reauth

    @classmethod
    def for_exchange(cls, status: int, body: dict[str, Any]) -> 'SignInError':
        code = _error_code(body) or f'http_{status}'
        if code == 'invalid_grant':
            return cls(code, (
                'ChatGPT did not complete the sign-in for this account. Using a ChatGPT plan in '
                'Bridge needs ChatGPT Plus or Pro; a Free account is refused at this step. '
                'Sign in with a Plus or Pro account, or use an API key instead.'
            ))
        return cls(code, f'ChatGPT refused the sign-in ({code}). Try signing in again.')

    @classmethod
    def for_refresh(cls, status: int, body: dict[str, Any]) -> 'SignInError':
        code = str(body.get('error_reason') or '') or _error_code(body) or f'http_{status}'
        if code in REAUTH_CODES or _error_code(body) in REAUTH_CODES:
            return cls(code, (
                'Your ChatGPT sign-in has expired and could not be renewed. '
                'Sign in again in Settings > AI provider.'
            ), reauth=True)
        return cls(code, f'ChatGPT could not renew the sign-in just now ({code}). Try again shortly.')


def _error_code(body: dict[str, Any]) -> str:
    error = body.get('error')
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        return str(error.get('code') or error.get('type') or '')
    return ''


# -- HTTP ------------------------------------------------------------------

class Http:
    """The three calls sign-in makes. Tests pass a fake."""

    def post_form(self, url: str, fields: dict[str, str], timeout: float = 30.0) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            url, data=urlencode(fields).encode('ascii'), method='POST',
            headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json',
                     'User-Agent': USER_AGENT},
        )
        return self._send(request, timeout)

    def get_json(self, url: str, bearer: str = '', timeout: float = 30.0) -> tuple[int, dict[str, Any]]:
        headers = {'Accept': 'application/json', 'User-Agent': USER_AGENT}
        if bearer:
            headers['Authorization'] = f'Bearer {bearer}'
        return self._send(urllib.request.Request(url, headers=headers, method='GET'), timeout)

    @staticmethod
    def _send(request: urllib.request.Request, timeout: float) -> tuple[int, dict[str, Any]]:
        try:
            with ai_http.urlopen_no_redirect(request, timeout) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        except (urllib.error.URLError, OSError) as error:
            raise SignInError('network_error', (
                'Could not reach ChatGPT. Check the internet connection and try again.'
            )) from error
        try:
            value = json.loads(raw.decode('utf-8')) if raw else {}
        except Exception:
            value = {}
        return status, value if isinstance(value, dict) else {}


# -- PKCE and the authorization address --------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def random_value() -> str:
    return _b64url(secrets.token_bytes(32))


def pkce_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode('ascii')).digest())


def authorize_url(*, client_id: str, redirect_uri: str, state: str, nonce: str, challenge: str,
                  login_hint: str = '') -> str:
    """`client_id` empty registers this computer; the callback then carries the
    client id OpenAI issued for it."""
    params = {
        'client_id': client_id or REGISTRATION_CLIENT,
        'response_type': 'code',
        'redirect_uri': redirect_uri,
        'scope': SCOPES,
        'resource': RESOURCE,
        'state': state,
        'nonce': nonce,
        'code_challenge_method': 'S256',
        'code_challenge': challenge,
    }
    if not client_id:
        params['agent_name_hint'] = APP_NAME
    if login_hint:
        params['login_hint'] = login_hint
    return f'{AUTHORIZE_URL}?{urlencode(params)}'


# -- the loopback listener --------------------------------------------------

_DONE_PAGE = (
    '<!doctype html><html lang="en"><meta charset="utf-8"><title>Return to Bridge</title>'
    '<body style="font:17px system-ui;max-width:32rem;margin:18vh auto;padding:24px">'
    '<h1 style="font-size:24px">Return to Bridge</h1>'
    '<p>Bridge is finishing the sign-in. You can close this tab.</p></body></html>'
).encode('utf-8')


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 -- http.server's name
        server: Any = self.server
        parsed = urlsplit(self.path)
        expected_host = f'127.0.0.1:{server.server_address[1]}'
        if parsed.path != CALLBACK_PATH or self.headers.get('Host') != expected_host:
            self.send_error(404)
            return
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        # A stray or repeated request must not use up, or replace, the answer.
        if server.answered.is_set() or not hmac.compare_digest(params.get('state', ''), server.state):
            self.send_error(400, 'Invalid sign-in state')
            return
        server.answer = params
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(_DONE_PAGE)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(_DONE_PAGE)
        server.answered.set()

    def log_message(self, *args: Any) -> None:  # the query carries the code: never log it
        pass


class CallbackListener:
    """Listens on 127.0.0.1 for the one redirect that carries this attempt's
    `state`. Bound before the browser opens; closed by `close()`."""

    def __init__(self, state: str, port: int = PREFERRED_PORT) -> None:
        try:
            self._server = ThreadingHTTPServer(('127.0.0.1', port), _CallbackHandler)
        except OSError:
            try:
                self._server = ThreadingHTTPServer(('127.0.0.1', 0), _CallbackHandler)
            except OSError as error:
                raise SignInError('callback_port_unavailable', (
                    'Bridge could not open a local port for the sign-in to return to.'
                )) from error
        self._server.daemon_threads = True
        self._server.state = state  # type: ignore[attr-defined]
        self._server.answer = {}  # type: ignore[attr-defined]
        self._server.answered = threading.Event()  # type: ignore[attr-defined]
        self.redirect_uri = f'http://127.0.0.1:{self._server.server_address[1]}{CALLBACK_PATH}'
        threading.Thread(target=self._server.serve_forever, daemon=True, name='chatgpt-signin-callback').start()

    def wait(self, timeout: float, cancel: threading.Event | None = None) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        answered: threading.Event = self._server.answered  # type: ignore[attr-defined]
        while not answered.wait(0.2):
            if cancel is not None and cancel.is_set():
                raise SignInError('cancelled', 'Sign-in was cancelled.')
            if time.monotonic() >= deadline:
                raise SignInError('timed_out', (
                    'The sign-in was not finished in the browser in time. Start it again when you are ready.'
                ))
        return dict(self._server.answer)  # type: ignore[attr-defined]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


# -- the ID token -----------------------------------------------------------

# DER prefix of DigestInfo for SHA-256 (RFC 8017, 9.2 note 1).
_SHA256_DIGEST_INFO = bytes.fromhex('3031300d060960864801650304020105000420')


def _rs256_valid(signing_input: bytes, signature: bytes, n: int, e: int) -> bool:
    """RSASSA-PKCS1-v1_5 with SHA-256: rebuild the padded digest the signer
    must have produced and compare all of it. Parsing the decrypted block
    instead is how forged signatures get accepted."""
    size = (n.bit_length() + 7) // 8
    if n.bit_length() < 2048 or e < 3 or e % 2 == 0 or len(signature) != size:
        return False
    value = int.from_bytes(signature, 'big')
    if value >= n:
        return False
    digest = _SHA256_DIGEST_INFO + hashlib.sha256(signing_input).digest()
    expected = b'\x00\x01' + b'\xff' * (size - len(digest) - 3) + b'\x00' + digest
    return hmac.compare_digest(pow(value, e, n).to_bytes(size, 'big'), expected)


def verify_id_token(id_token: str, *, client_id: str, jwks: dict[str, Any], nonce: str = '',
                    now: float | None = None) -> dict[str, Any]:
    """The ID token's claims, once its signature and claims check out. `nonce`
    is checked when given (a sign-in); a refresh has none to check."""
    invalid = SignInError('invalid_id_token', 'The ChatGPT identity could not be verified. Please sign in again.')
    try:
        header_b64, payload_b64, signature_b64 = id_token.split('.')
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(payload_b64))
        signature = _b64url_decode(signature_b64)
    except Exception as error:
        raise invalid from error
    if not isinstance(header, dict) or not isinstance(claims, dict) or header.get('alg') != 'RS256':
        raise invalid
    keys = [key for key in (jwks.get('keys') or []) if isinstance(key, dict) and key.get('kty') == 'RSA']
    kid = header.get('kid')
    candidates = [key for key in keys if key.get('kid') == kid] if kid else keys
    signing_input = f'{header_b64}.{payload_b64}'.encode('ascii')
    verified = False
    for key in candidates:
        try:
            n = int.from_bytes(_b64url_decode(str(key['n'])), 'big')
            e = int.from_bytes(_b64url_decode(str(key['e'])), 'big')
        except Exception:
            continue
        if _rs256_valid(signing_input, signature, n, e):
            verified = True
            break
    if not verified:
        raise invalid
    now = time.time() if now is None else now
    audience = claims.get('aud')
    audiences = audience if isinstance(audience, list) else [audience]
    if (claims.get('iss') != ISSUER or client_id not in audiences
            or (len(audiences) > 1 and claims.get('azp') != client_id)
            or (claims.get('azp') is not None and claims.get('azp') != client_id)
            or not isinstance(claims.get('exp'), (int, float)) or claims['exp'] < now - 5
            or not isinstance(claims.get('sub'), str) or not claims['sub']
            or (nonce and claims.get('nonce') != nonce)):
        raise invalid
    return claims


# -- tokens -----------------------------------------------------------------

@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    id_token: str
    expires_at: float
    scopes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {'access_token': self.access_token, 'refresh_token': self.refresh_token,
                'id_token': self.id_token, 'expires_at': self.expires_at, 'scopes': list(self.scopes)}

    @classmethod
    def from_json(cls, value: Any) -> 'Tokens | None':
        if not isinstance(value, dict) or not value.get('refresh_token'):
            return None
        try:
            return cls(str(value.get('access_token') or ''), str(value['refresh_token']),
                       str(value.get('id_token') or ''), float(value.get('expires_at') or 0),
                       [str(scope) for scope in (value.get('scopes') or [])])
        except Exception:
            return None


def _tokens_from_response(body: dict[str, Any], *, fallback_scopes: list[str], previous_id_token: str = '',
                          now: float | None = None) -> Tokens:
    access = body.get('access_token')
    refresh = body.get('refresh_token')
    expires_in = body.get('expires_in')
    if (not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh
            or not isinstance(expires_in, (int, float)) or expires_in <= 0):
        raise SignInError('invalid_token_response', 'ChatGPT returned incomplete credentials. Please sign in again.')
    scope = body.get('scope')
    scopes = scope.split() if isinstance(scope, str) and scope.strip() else list(fallback_scopes)
    if PLAN_SCOPE not in scopes:
        raise SignInError('plan_use_not_granted', (
            'The sign-in did not include permission to use the ChatGPT plan. '
            'Sign in again and allow Bridge to use your plan.'
        ))
    id_token = body.get('id_token') if isinstance(body.get('id_token'), str) else ''
    return Tokens(access, refresh, id_token or previous_id_token,
                  (time.time() if now is None else now) + float(expires_in), scopes)


@dataclass
class SignInResult:
    client_id: str
    tokens: Tokens
    subject: str
    email: str
    name: str
    new_registration: bool


def sign_in(*, http: Http, open_browser: Callable[[str], Any], client_id: str = '', login_hint: str = '',
            expected_subject: str = '', cancel: threading.Event | None = None, timeout: float = 600.0,
            on_url: Callable[[str], None] | None = None,
            on_registration: Callable[[str], None] | None = None) -> SignInResult:
    """Run one sign-in to the end. Blocks until the person finishes in the
    browser, `cancel` is set, or `timeout` passes.

    `client_id` is the one saved from an earlier sign-in on this computer;
    empty registers it. `on_registration` is called with a newly issued client
    id BEFORE the code exchange, because the exchange can fail (a Free account)
    after the registration has succeeded, and the next attempt must reuse it."""
    state, nonce, verifier = random_value(), random_value(), random_value()
    listener = CallbackListener(state)
    try:
        url = authorize_url(client_id=client_id, redirect_uri=listener.redirect_uri, state=state, nonce=nonce,
                            challenge=pkce_challenge(verifier), login_hint=login_hint)
        if on_url is not None:
            on_url(url)
        try:
            open_browser(url)
        except Exception:
            pass  # the address is shown in Settings for the person to open
        answer = listener.wait(timeout, cancel)
    finally:
        listener.close()

    if answer.get('error'):
        if answer['error'] == 'access_denied':
            raise SignInError('access_denied', 'Sign-in was not completed. You can try again when you are ready.')
        raise SignInError(answer['error'], f'ChatGPT did not complete the sign-in ({answer["error"]}).')
    code = answer.get('code', '')
    issued = answer.get('client_id', '')
    if not code:
        raise SignInError('registration_incomplete', 'ChatGPT did not complete the sign-in. Please try again.')
    new_registration = not client_id
    if new_registration:
        if not issued or issued == REGISTRATION_CLIENT:
            raise SignInError('registration_incomplete', 'ChatGPT did not register Bridge on this computer. Please try again.')
        client_id = issued
        if on_registration is not None:
            on_registration(client_id)
    elif issued and issued != client_id:
        raise SignInError('registration_mismatch', 'The sign-in answered for a different app registration. Please try again.')

    status, body = http.post_form(TOKEN_URL, {
        'grant_type': 'authorization_code',
        'client_id': client_id,
        'code': code,
        'code_verifier': verifier,
        'redirect_uri': listener.redirect_uri,
        'resource': RESOURCE,
    })
    if status != 200:
        raise SignInError.for_exchange(status, body)
    tokens = _tokens_from_response(body, fallback_scopes=str(answer.get('scope') or '').split())
    if not tokens.id_token:
        raise SignInError('invalid_id_token', 'ChatGPT did not return a verifiable identity. Please sign in again.')
    claims = verify_id_token(tokens.id_token, client_id=client_id, jwks=fetch_jwks(http), nonce=nonce)
    if expected_subject and claims['sub'] != expected_subject:
        raise SignInError('account_mismatch', (
            'This sign-in was for a different ChatGPT account than the one Bridge was signed in to. '
            'Sign out first to switch accounts.'
        ))
    return SignInResult(client_id, tokens, str(claims['sub']), str(claims.get('email') or ''),
                        str(claims.get('name') or ''), new_registration)


def fetch_jwks(http: Http) -> dict[str, Any]:
    status, body = http.get_json(JWKS_URL, timeout=15.0)
    if status != 200 or not isinstance(body.get('keys'), list):
        raise SignInError('identity_verification_unavailable', (
            'ChatGPT identity verification is temporarily unavailable. Try signing in again shortly.'
        ))
    return body


def refresh(*, http: Http, client_id: str, tokens: Tokens, now: float | None = None) -> Tokens:
    """A renewed token set. The refresh token ROTATES: the caller must store
    the returned one before using it, or the sign-in is lost. `now` is the
    caller's clock, which the new expiry is counted from."""
    status, body = http.post_form(TOKEN_URL, {
        'grant_type': 'refresh_token',
        'client_id': client_id,
        'refresh_token': tokens.refresh_token,
        'resource': RESOURCE,
    })
    if status != 200:
        raise SignInError.for_refresh(status, body)
    return _tokens_from_response(body, fallback_scopes=tokens.scopes, previous_id_token=tokens.id_token, now=now)


def revoke(*, http: Http, client_id: str, tokens: Tokens) -> bool:
    """Whether the provider confirmed the sign-in is ended. The registration is
    not removed; the saved client id stays good for the next sign-in."""
    try:
        status, _ = http.post_form(REVOKE_URL, {
            'token': tokens.refresh_token, 'token_type_hint': 'refresh_token', 'client_id': client_id,
        }, timeout=10.0)
    except SignInError:
        return False
    return status == 200


def list_models(*, http: Http, access_token: str) -> list[dict[str, Any]]:
    """The models this account may use under its plan, in the provider's order:
    `{slug, displayName, reasoningEfforts, contextWindow}`."""
    status, body = http.get_json(f'{API_BASE}/models', bearer=access_token)
    rows = body.get('models')
    if status != 200 or not isinstance(rows, list):
        code = _error_code(body) or f'http_{status}'
        raise SignInError(code, f'ChatGPT did not return its model list ({code}). Try again shortly.',
                          reauth=status == 401)
    models: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get('visibility') != 'list':
            continue
        slug = str(row.get('slug') or '').strip()
        if not slug:
            continue
        levels = row.get('supported_reasoning_levels')
        efforts = [str(level.get('effort')) for level in levels if isinstance(level, dict) and level.get('effort')] \
            if isinstance(levels, list) else []
        models.append({
            'slug': slug,
            'displayName': str(row.get('display_name') or slug),
            'reasoningEfforts': efforts,
            'contextWindow': row.get('context_window') if isinstance(row.get('context_window'), int) else None,
        })
    return models
