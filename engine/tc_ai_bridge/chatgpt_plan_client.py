"""Bridge's AI requests on a ChatGPT plan instead of an API key (#506).

`ChatGPTPlanClient` is `OpenAIResponsesClient` with four differences, each one
seen on a live run (docs/BUILD_LOG.md, 2026-11-23) or required by OpenAI's
pages for plan usage:

- the credential is the signed-in session's access token, renewed when it is
  about to lapse and once more when the provider answers 401;
- every request is streamed (`stream: true`), with `store: false`, and a string
  `input` is wrapped in a one-message list, because plan usage refuses a string;
- a reached plan limit is never retried: it raises `AIPlanLimitError`, and the
  session then holds every later request back for a few minutes;
- a call is not billed in dollars, so its estimated cost is zero. Tokens are
  still counted.

Everything else, the prompts, the answer schemas, the parsing, the usage
ledger, is inherited unchanged. `stream_transport` reads the event stream to
its `response.completed` event and hands back that event's response object,
which is the same JSON a non-streamed call returns, so `_post_text` reads it as
it always has.
"""
from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from typing import Any, Iterable

from . import ai_http
from .ai_client import AIError, AIPlanLimitError, AITransportError, OpenAIResponsesClient, Transport
from .chatgpt_session import LIMIT_MESSAGE, ChatGPTSession
from .chatgpt_signin import SignInError

LIMIT_CODE = 'subscription_sharing_usage_limit_exceeded'
UNSUPPORTED_CODE = 'subscription_sharing_unsupported_capability'
# Request fields OpenAI's pages say plan usage refuses. Bridge sends none of
# them today; dropped here so a later change to the base client cannot break
# every signed-in user at once.
OMITTED_FIELDS = frozenset({
    'background', 'conversation', 'max_output_tokens', 'max_tool_calls', 'metadata', 'moderation',
    'multi_agent', 'previous_response_id', 'prompt', 'prompt_cache_retention', 'safety_identifier',
    'temperature', 'top_logprobs', 'top_p', 'truncation', 'user',
})
# Bridge's settings also offer 'none', which no plan model lists.
PLAN_REASONING_EFFORTS = frozenset({'low', 'medium', 'high', 'xhigh', 'max'})
MAX_STREAM_BYTES = 32 * 1024 * 1024

_MESSAGES = {
    'subscription_sharing_user_not_eligible':
        'This ChatGPT account or workspace cannot use its plan in other apps. ChatGPT Plus or Pro is needed.',
    'subscription_sharing_usage_unavailable': 'ChatGPT could not check the plan usage just now. Try again shortly.',
    'subscription_sharing_user_unavailable': 'The ChatGPT account is temporarily unavailable. Try again shortly.',
    'subscription_sharing_invalid_user':
        'ChatGPT could not validate this sign-in. Sign out and in again in Settings > AI provider.',
    'model_not_found':
        'This model is not available for your ChatGPT sign-in. Choose another in Settings > AI provider.',
}


def plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """`payload` as plan usage accepts it."""
    out = {key: value for key, value in payload.items() if key not in OMITTED_FIELDS}
    out['store'] = False
    out['stream'] = True
    if isinstance(out.get('input'), str):
        out['input'] = [{'role': 'user', 'content': out['input']}]
    reasoning = out.get('reasoning')
    if isinstance(reasoning, dict) and reasoning.get('effort') not in PLAN_REASONING_EFFORTS:
        out.pop('reasoning')
    return out


def _error_fields(value: Any) -> dict[str, str]:
    """`{code, param, message}` from an error body, a failed event, or the
    `{"detail": ...}` body the plan route answers with before a stream starts."""
    if not isinstance(value, dict):
        return {'code': '', 'param': '', 'message': ''}
    error = value.get('error')
    if isinstance(value.get('response'), dict) and isinstance(value['response'].get('error'), dict):
        error = value['response']['error']
    if isinstance(error, dict):
        return {'code': str(error.get('code') or ''), 'param': str(error.get('param') or ''),
                'message': str(error.get('message') or '')}
    if isinstance(error, str):
        return {'code': error, 'param': '', 'message': str(value.get('error_description') or '')}
    detail = value.get('detail')
    return {'code': '', 'param': '', 'message': detail if isinstance(detail, str) else ''}


def read_event_stream(lines: Iterable[bytes], deadline: float | None = None) -> tuple[int, dict[str, Any]]:
    """The `(status, body)` a non-streamed call would have returned. Success is
    only `response.completed`; a stream that ends without it was never
    answered, which the caller's ledger records as such."""
    size = 0
    data_lines: list[str] = []

    def finish(data: str) -> tuple[int, dict[str, Any]] | None:
        try:
            event = json.loads(data)
        except Exception:
            return None
        if not isinstance(event, dict):
            return None
        kind = event.get('type')
        if kind == 'response.completed':
            response = event.get('response')
            return 200, response if isinstance(response, dict) else {}
        if kind in ('response.failed', 'error'):
            fields = _error_fields(event)
            if fields['code'] == LIMIT_CODE:
                status = 429
            elif fields['code'].endswith('_unavailable'):
                status = 503
            else:
                status = 400
            return status, {'error': fields}
        if kind == 'response.incomplete':
            return 422, {'error': {'code': 'response_incomplete', 'param': '',
                                   'message': 'ChatGPT stopped before completing the response.'}}
        return None

    for raw in lines:
        size += len(raw)
        if size > MAX_STREAM_BYTES:
            raise AITransportError('The ChatGPT response was too large to read.')
        if deadline is not None and time.monotonic() > deadline:
            raise AITransportError('The ChatGPT response took too long and was abandoned.')
        line = raw.decode('utf-8', 'replace').rstrip('\r\n')
        if line.startswith('data:'):
            data_lines.append(line[5:].lstrip())
        elif not line and data_lines:
            result = finish('\n'.join(data_lines))
            data_lines = []
            if result is not None:
                return result
    if data_lines:
        result = finish('\n'.join(data_lines))
        if result is not None:
            return result
    raise AITransportError('The ChatGPT response ended before it was complete.')


def stream_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, bytes]:
    """`ai_client.default_transport` for a streamed call. Redirects are not
    followed: the request carries the sign-in and the verse text."""
    request = urllib.request.Request(url, data=body, headers={**headers, 'Accept': 'text/event-stream'}, method='POST')
    deadline = time.monotonic() + timeout
    try:
        with ai_http.urlopen_no_redirect(request, timeout) as response:
            content_type = str(response.headers.get('Content-Type') or '').split(';')[0].strip().lower()
            if content_type == 'application/json':
                return response.status, response.read()
            # The plan route sends its events with no Content-Type at all, so
            # anything that is not JSON is read as a stream.
            status, value = read_event_stream(response, deadline)
            return status, json.dumps(value, ensure_ascii=False).encode('utf-8')
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except urllib.error.URLError as error:
        raise AITransportError(f'Network error contacting ChatGPT: {error.reason}') from error
    except (OSError, http.client.HTTPException) as error:
        raise AITransportError(f'Network error contacting ChatGPT: {error}') from error


class ChatGPTPlanClient(OpenAIResponsesClient):
    def __init__(self, session: ChatGPTSession, model: str, transport: Transport | None = None,
                 timeout: float = 240.0, reasoning_effort: str = 'medium') -> None:
        # The base class wants a non-empty key; the real credential is fetched
        # per request in `_request_json`. This placeholder is never sent.
        super().__init__('chatgpt-plan', model=model, transport=transport or stream_transport,
                         timeout=timeout, reasoning_effort=reasoning_effort)
        self.session = session

    def _model_supports_reasoning_effort(self) -> bool:
        return True  # every model the plan catalogue lists carries reasoning levels

    def _estimate_cost(self, input_tokens: int, output_tokens: int, cached_input_tokens: int) -> float:
        return 0.0

    def _should_retry(self, status: int, raw: bytes) -> bool:
        if status == 401:
            return False  # renewed and re-sent once in `_request_json`
        if status == 429:
            try:
                return _error_fields(json.loads(raw.decode('utf-8')))['code'] != LIMIT_CODE
            except Exception:
                return True
        return super()._should_retry(status, raw)

    def _request_json(
        self, payload: dict[str, Any], headers: dict[str, str], timeout: float | None = None,
    ) -> tuple[int, dict[str, Any]]:
        payload = plan_payload(payload)
        status: int = 0
        response: dict[str, Any] = {}
        for attempt in range(2):
            reason = self.session.halt_reason()
            if reason:
                raise AIPlanLimitError(reason)
            try:
                token = self.session.access_token(force_refresh=attempt == 1)
            except SignInError as error:
                if error.reauth:
                    raise AIPlanLimitError(str(error)) from error
                raise AIError(str(error)) from error
            status, response = super()._request_json(
                payload, {**headers, 'Authorization': f'Bearer {token}'}, timeout,
            )
            if status != 401:
                break
        if 200 <= status < 300:
            return status, response
        fields = _error_fields(response)
        if fields['code'] == LIMIT_CODE:
            self.session.note_limit_reached()
            raise AIPlanLimitError(LIMIT_MESSAGE)
        if fields['code'] == UNSUPPORTED_CODE:
            # In the words `_post_text` already recognises, so its one-field
            # retry (drop `reasoning`, drop `prompt_cache_key`) still applies.
            fields = {'code': 'unsupported_parameter', 'param': fields['param'],
                      'message': f'ChatGPT plan use does not support "{fields["param"] or "part of"}" in this request.'}
        elif fields['code'] in _MESSAGES:
            fields = {**fields, 'message': _MESSAGES[fields['code']]}
        elif not fields['message']:
            fields = {**fields, 'message': f'ChatGPT refused the request ({fields["code"] or "no reason given"}).'}
        return status, {'error': fields}
