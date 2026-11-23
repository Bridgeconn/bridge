"""The ChatGPT sign-in this installation holds (#506).

One per engine. It keeps what `chatgpt_signin` returns (tokens DPAPI-wrapped in
settings.json, the issued client id and the signed-in identity in the settings
store), hands `chatgpt_plan_client` an access token that is good right now,
runs the browser sign-in on a worker thread so the Settings dialog can poll it,
and remembers when the plan's limit was reached so a long job stops asking.

Nothing here is on a path a translator hits without choosing it: the session is
touched only when Settings > AI provider is on "ChatGPT account" and an AI
feature is used, or the sign-in buttons are pressed.
"""
from __future__ import annotations

import threading
import time
import webbrowser
from typing import Any, Callable

from . import chatgpt_signin as signin
from .chatgpt_signin import SignInError, Tokens

# Renew this long before the access token's stated expiry, so a request never
# starts with a token about to lapse.
REFRESH_MARGIN_SECONDS = 300
# After the plan's limit is reached, nothing is sent for this long. OpenAI
# gives no reset time and no way to read the allowance, so this is only a
# pause between attempts, long enough that a whole-book job stops rather than
# sending one refused request per verse.
LIMIT_PAUSE_SECONDS = 300
MODELS_CACHE_SECONDS = 600
SIGN_IN_TIMEOUT_SECONDS = 600

LIMIT_MESSAGE = (
    'Your ChatGPT plan limit has been reached, so Bridge has stopped sending AI requests. '
    f'Check your usage at {signin.USAGE_URL}, then run it again later; '
    'what was already finished is kept.'
)
SIGNED_OUT_MESSAGE = 'Sign in with ChatGPT in Settings > AI provider before using AI.'


class ChatGPTSession:
    def __init__(self, settings: Any, *, http: signin.Http | None = None,
                 open_browser: Callable[[str], Any] | None = None,
                 clock: Callable[[], float] = time.time,
                 sign_in: Callable[..., signin.SignInResult] | None = None) -> None:
        self.settings = settings
        self.http = http or signin.Http()
        self._open_browser = open_browser or webbrowser.open
        self._clock = clock
        self._sign_in = sign_in or signin.sign_in
        self._lock = threading.RLock()
        self._attempt: dict[str, Any] | None = None
        self._last_error: dict[str, str] | None = None
        self._limit_until = 0.0
        self._models: list[dict[str, Any]] = []
        self._models_at = 0.0

    # -- what is stored ------------------------------------------------------

    def _tokens(self) -> Tokens | None:
        return Tokens.from_json(self.settings.get_chatgpt_tokens())

    def is_signed_in(self) -> bool:
        return self._tokens() is not None and bool(self.settings.chatgpt_connection.get('clientId'))

    def state(self) -> dict[str, Any]:
        """Safe to send to the UI: no token, no client id."""
        with self._lock:
            connection = self.settings.chatgpt_connection
            attempt = self._attempt
            if attempt is not None and attempt['thread'].is_alive():
                status = 'signingIn'
            elif self.is_signed_in():
                status = 'signedIn'
            elif connection.get('reauthRequired'):
                status = 'reauthRequired'
            else:
                status = 'signedOut'
            limited = self._clock() < self._limit_until
            return {
                'status': status,
                'email': str(connection.get('email') or ''),
                'name': str(connection.get('name') or ''),
                # Shown while signing in, for a browser that did not open.
                'signInUrl': str(attempt.get('url') or '') if status == 'signingIn' and attempt else '',
                'error': dict(self._last_error) if self._last_error and status != 'signingIn' else None,
                'limitReached': limited,
                'limitMessage': LIMIT_MESSAGE if limited else '',
                'usageUrl': signin.USAGE_URL,
            }

    # -- sign-in and sign-out --------------------------------------------------

    def start_sign_in(self) -> dict[str, Any]:
        with self._lock:
            if self._attempt is not None and self._attempt['thread'].is_alive():
                return self.state()
            attempt: dict[str, Any] = {'cancel': threading.Event(), 'url': ''}
            attempt['thread'] = threading.Thread(
                target=self._run_sign_in, args=(attempt,), daemon=True, name='chatgpt-signin',
            )
            self._attempt = attempt
            self._last_error = None
            attempt['thread'].start()
        return self.state()

    def cancel_sign_in(self) -> dict[str, Any]:
        with self._lock:
            attempt = self._attempt
        if attempt is not None:
            attempt['cancel'].set()
            attempt['thread'].join(timeout=3.0)
        return self.state()

    def _run_sign_in(self, attempt: dict[str, Any]) -> None:
        connection = self.settings.chatgpt_connection

        def remember_registration(client_id: str) -> None:
            with self._lock:
                kept = self.settings.chatgpt_connection
                kept['clientId'] = client_id
                self.settings.set_chatgpt_connection(kept)

        try:
            result = self._sign_in(
                http=self.http, open_browser=self._open_browser,
                client_id=str(connection.get('clientId') or ''),
                login_hint=str(connection.get('email') or ''),
                cancel=attempt['cancel'], timeout=SIGN_IN_TIMEOUT_SECONDS,
                on_url=lambda url: attempt.__setitem__('url', url),
                on_registration=remember_registration,
            )
        except SignInError as error:
            with self._lock:
                self._last_error = None if error.code == 'cancelled' else {'code': error.code, 'message': str(error)}
            return
        except Exception as error:  # a worker thread must not die silently
            with self._lock:
                self._last_error = {'code': 'sign_in_failed', 'message': f'Sign-in failed: {error}'}
            return
        with self._lock:
            self.settings.set_chatgpt_tokens(result.tokens.to_json())
            self.settings.set_chatgpt_connection({
                'clientId': result.client_id, 'subject': result.subject,
                'email': result.email, 'name': result.name,
                'signedInAt': self._clock(),
            })
            self._last_error = None
            self._limit_until = 0.0
            self._models, self._models_at = [], 0.0

    def sign_out(self) -> dict[str, Any]:
        """Ends the sign-in here whatever the provider answers. The issued
        client id is kept, so signing in again does not register a second app."""
        self.cancel_sign_in()
        with self._lock:
            tokens = self._tokens()
            connection = self.settings.chatgpt_connection
            client_id = str(connection.get('clientId') or '')
            confirmed = True
            if tokens is not None and client_id:
                confirmed = signin.revoke(http=self.http, client_id=client_id, tokens=tokens)
            self.settings.set_chatgpt_tokens(None)
            self.settings.set_chatgpt_connection({'clientId': client_id} if client_id else None)
            self._models, self._models_at = [], 0.0
            self._limit_until = 0.0
            self._last_error = None if confirmed else {
                'code': 'revocation_unconfirmed',
                'message': ('Signed out on this computer, but ChatGPT did not confirm it. '
                            'You can also disconnect Bridge in ChatGPT Settings.'),
            }
            return self.state()

    # -- tokens for a request --------------------------------------------------

    def access_token(self, force_refresh: bool = False) -> str:
        """A token good for a request now, renewing it first when it is close
        to expiry. Raises `SignInError` (`reauth=True` when the person must sign
        in again)."""
        with self._lock:  # one renewal at a time: the refresh token is single-use
            tokens = self._tokens()
            client_id = str(self.settings.chatgpt_connection.get('clientId') or '')
            if tokens is None or not client_id:
                raise SignInError('signed_out', SIGNED_OUT_MESSAGE, reauth=True)
            if not force_refresh and tokens.access_token and tokens.expires_at - self._clock() > REFRESH_MARGIN_SECONDS:
                return tokens.access_token
            try:
                renewed = signin.refresh(http=self.http, client_id=client_id, tokens=tokens, now=self._clock())
            except SignInError as error:
                if error.reauth:
                    self._require_sign_in(str(error), error.code)
                raise
            # Stored before it is used: the old refresh token is now spent.
            self.settings.set_chatgpt_tokens(renewed.to_json())
            return renewed.access_token

    def _require_sign_in(self, message: str, code: str) -> None:
        connection = self.settings.chatgpt_connection
        connection['reauthRequired'] = True
        self.settings.set_chatgpt_tokens(None)
        self.settings.set_chatgpt_connection(connection)
        self._last_error = {'code': code, 'message': message}

    # -- the plan's limit --------------------------------------------------------

    def note_limit_reached(self) -> None:
        with self._lock:
            self._limit_until = self._clock() + LIMIT_PAUSE_SECONDS

    def halt_reason(self) -> str:
        """Non-empty while nothing should be sent: the plan's limit was just
        reached, or the sign-in is gone. A job stops on this instead of failing
        every remaining verse one request at a time."""
        with self._lock:
            if self._clock() < self._limit_until:
                return LIMIT_MESSAGE
            if not self.is_signed_in():
                error = self._last_error or {}
                return str(error.get('message') or SIGNED_OUT_MESSAGE)
            return ''

    # -- models --------------------------------------------------------------------

    def models(self, refresh: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            if not refresh and self._models and self._clock() - self._models_at < MODELS_CACHE_SECONDS:
                return [dict(model) for model in self._models]
        token = self.access_token()
        try:
            models = signin.list_models(http=self.http, access_token=token)
        except SignInError as error:
            if not error.reauth:
                raise
            models = signin.list_models(http=self.http, access_token=self.access_token(force_refresh=True))
        with self._lock:
            self._models, self._models_at = models, self._clock()
        return [dict(model) for model in models]
