from __future__ import annotations

import json

import pytest

from tc_ai_bridge.ai_client import AIError, OpenAIResponsesClient


def _success(result: dict) -> bytes:
    return json.dumps({
        'output_text': json.dumps(result),
        'usage': {
            'input_tokens': 5,
            'output_tokens': 3,
            'total_tokens': 8,
            'input_tokens_details': {'cached_tokens': 0},
        },
    }).encode('utf-8')


def test_retries_once_without_reasoning_when_provider_explicitly_rejects_it():
    requests: list[dict] = []

    def transport(url, headers, body, timeout):
        payload = json.loads(body)
        requests.append(payload)
        if len(requests) == 1:
            return 400, json.dumps({'error': {
                'message': "Unsupported parameter: 'reasoning.effort' is not supported with this model.",
                'type': 'invalid_request_error',
                'param': 'reasoning.effort',
                'code': 'unsupported_parameter',
            }}).encode('utf-8')
        return 200, _success({'links': []})

    # Use a model Bridge expects to support reasoning so this test exercises the
    # provider-rejection fallback. Known non-reasoning models omit the parameter
    # proactively and therefore correctly make only one request.
    client = OpenAIResponsesClient('test-key', model='gpt-5.6', transport=transport)
    result = client._post_structured('instructions', 'input', 'test_schema', {
        'type': 'object', 'properties': {'links': {'type': 'array'}}, 'required': ['links'],
    })

    assert result == {'links': []}
    assert requests[0]['reasoning'] == {'effort': 'medium'}
    assert 'reasoning' not in requests[1]
    assert client.last_reasoning_effort is None
    assert client._effective_reasoning_effort() == 'provider-default'


def test_does_not_retry_an_unrelated_bad_request():
    requests: list[dict] = []

    def transport(url, headers, body, timeout):
        requests.append(json.loads(body))
        return 400, json.dumps({'error': {
            'message': "Unsupported parameter: 'text.format'.",
            'param': 'text.format',
            'code': 'unsupported_parameter',
        }}).encode('utf-8')

    client = OpenAIResponsesClient('test-key', transport=transport)

    with pytest.raises(AIError, match=r"Unsupported parameter: 'text\.format'"):
        client._post_structured('instructions', 'input', 'test_schema', {'type': 'object'})

    assert len(requests) == 1


def test_does_not_retry_reasoning_error_without_explicit_unsupported_signal():
    requests: list[dict] = []

    def transport(url, headers, body, timeout):
        requests.append(json.loads(body))
        return 400, json.dumps({'error': {
            'message': 'reasoning.effort must be one of the allowed values',
            'param': 'reasoning.effort',
            'code': 'invalid_value',
        }}).encode('utf-8')

    client = OpenAIResponsesClient('test-key', transport=transport)

    with pytest.raises(AIError, match='allowed values'):
        client._post_structured('instructions', 'input', 'test_schema', {'type': 'object'})

    assert len(requests) == 1


def test_prompt_cache_key_is_sent_and_dropped_for_the_session_when_rejected():
    """#472: the review sends `prompt_cache_key`; an OpenAI-compatible endpoint
    that rejects it explicitly gets one retry without it, and no later call of
    the session sends it again. An unrelated 400 is not retried."""
    requests: list[dict] = []

    def transport(url, headers, body, timeout):
        payload = json.loads(body)
        requests.append(payload)
        if 'prompt_cache_key' in payload:
            return 400, json.dumps({'error': {
                'message': "Unknown parameter: 'prompt_cache_key'.",
                'type': 'invalid_request_error',
                'param': 'prompt_cache_key',
                'code': 'unknown_parameter',
            }}).encode('utf-8')
        return 200, _success({'links': []})

    client = OpenAIResponsesClient('test-key', model='gpt-4o', transport=transport)
    schema = {'type': 'object', 'properties': {'links': {'type': 'array'}}, 'required': ['links']}

    assert client._post_structured('i', 'x', 'test_schema', schema, prompt_cache_key='project-1') == {'links': []}
    assert requests[0]['prompt_cache_key'] == 'project-1'
    assert 'prompt_cache_key' not in requests[1]
    assert client.prompt_cache_key_unsupported is True

    client._post_structured('i', 'y', 'test_schema', schema, prompt_cache_key='project-1')
    assert len(requests) == 3 and 'prompt_cache_key' not in requests[2]

    # No key requested: never sent, and nothing about the session changes.
    fresh = OpenAIResponsesClient('test-key', model='gpt-4o', transport=lambda *a: (200, _success({'links': []})))
    fresh._post_structured('i', 'x', 'test_schema', schema)
    assert fresh.prompt_cache_key_unsupported is False


def test_review_instructions_put_every_static_sentence_before_the_project_tail():
    """#472: the provider's prefix cache needs the first 1,024+ tokens of
    the prompt byte-identical across calls, so two projects with different
    languages and verses with different check counts must share the whole
    static block, and only the tail may differ."""
    from types import SimpleNamespace
    from tc_ai_bridge.ai_client import CHECKING_METHOD_DIGEST, REVIEW_INSTRUCTIONS_STATIC, review_instructions

    hindi = SimpleNamespace(source_name='Hebrew', target_name='Hindi', qa_categories=['spelling'], prompt_guidance='Hindi guidance.')
    tamil = SimpleNamespace(source_name='Greek', target_name='Tamil', qa_categories=['sandhi'], prompt_guidance='Tamil guidance.')

    a, b, c = review_instructions(hindi, 8), review_instructions(hindi, 3), review_instructions(tamil, 8)
    for text in (a, b, c):
        assert text.startswith(REVIEW_INSTRUCTIONS_STATIC)
    assert len(REVIEW_INSTRUCTIONS_STATIC) > 4000
    assert CHECKING_METHOD_DIGEST in REVIEW_INSTRUCTIONS_STATIC
    assert 'Hindi' not in REVIEW_INSTRUCTIONS_STATIC and 'Tamil' not in REVIEW_INSTRUCTIONS_STATIC
    assert '8 input checks require exactly 8 result rows' in a
    assert '3 input checks require exactly 3 result rows' in b
    assert 'Tamil guidance.' in c and 'Hindi guidance.' in a
    assert a.index('PROJECT:') > a.index('CHECKING METHOD')
