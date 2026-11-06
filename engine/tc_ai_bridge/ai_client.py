from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import time
from dataclasses import dataclass
from typing import Any, Callable

from . import ai_http
from .alignment_engine import apply_proposal, make_inventory, validate_proposal, validate_preparation_proposal
from .alignment_reliability import compile_link_proposal
from .models import AICheckReview, QAIssue, VerseAlignment
from .tc_project import TranslationCoreProject
from .model_router import estimate_cost
from .cache_engine import dependency_snapshot
from .security import ai_payload_manifest
from .plugins import PluginRegistry
from .review_policy import gate_ai_issues, gate_check_reviews
from .usfm import strip_usfm
from .semantic_mapping_bridge import prepare_semantic_mappings_for_review
from .semantic_alignment_guard import cross_verse_alignment_exclusions, guard_alignment_response
from .semantic_review_policy import apply_semantic_review_policy_all


class AIError(RuntimeError):
    pass


class AITransportError(AIError, ai_http.TransportFailure):
    """The provider was never reached (see `ai_http.TransportFailure`). Still an
    AIError, so every existing `except AIError` handles it unchanged."""


_QUOTED_TEXT = re.compile(
    r'"([^"\r\n]+)"|\'([^\'\r\n]+)\'|“([^”\r\n]+)”|‘([^’\r\n]+)’'
)


def _recover_quoted_target_selections(rationale: str, target_text: str) -> list[dict[str, Any]]:
    """Resolve an omitted AI selection only from an exact, unambiguous quote.

    Some providers correctly identify a target rendering in their rationale but
    still return ``nothing_to_select=true``. We may safely recover that phrase
    when it is quoted, occurs exactly once in the current target verse, and does
    not overlap another recovered quote. Repeated or ambiguous text remains a
    human-review item; Bridge never guesses an occurrence.
    """
    verse_text = strip_usfm(target_text)
    matches: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for match in _QUOTED_TEXT.finditer(str(rationale or '')):
        candidate = next((value for value in match.groups() if value is not None), '').strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        ranges = TranslationCoreProject._selection_ranges(verse_text, candidate)
        if len(ranges) == 1:
            start, end = ranges[0]
            matches.append((start, end, candidate))

    # Prefer the most informative phrase when the model quoted both a phrase
    # and one of its component words. Independent non-overlapping quotes remain
    # separate tC selections.
    accepted: list[tuple[int, int, str]] = []
    for start, end, candidate in sorted(matches, key=lambda item: (-(item[1] - item[0]), item[0])):
        if any(start < other_end and other_start < end for other_start, other_end, _ in accepted):
            continue
        accepted.append((start, end, candidate))
    accepted.sort(key=lambda item: item[0])
    return [
        {'text': candidate, 'occurrence': 1, 'occurrences': 1}
        for _, _, candidate in accepted
    ]


# #470: a reviewer's past decision contributes *what was decided* to a verse
# review -- the check, the verdict and the target words chosen -- never who
# decided it, when, what they wrote about it, which model proposed it, or where
# the evidence lived on disk. These are the only keys the two project-history
# lists may carry; `security.ai_payload_manifest` reports a record outside this
# shape as `containsReviewerIdentity: true`.
REVIEWER_DECISION_FIELDS = ('reference', 'tool', 'groupId', 'checkId', 'decision', 'selectionText')
PROJECT_RENDERING_FIELDS = ('reference', 'source_quote', 'selections', 'nothingToSelect', 'invalidated')


# #471: the whole-verse QA used to carry the full text of thirteen Translation
# Academy "checking" articles (49,695 chars serialised, about half of every
# request) as evidence items, resent for every verse. The model is asked to
# review one verse; it needs the method, not the articles. This digest is the
# method, written once as static instruction text so the provider's prefix
# cache can hold it (#472). The articles themselves stay on disk and
# `TranslationHelpsKnowledgeBase.global_checking_evidence()` still reads them
# for any caller that wants the text; they are simply no longer sent.
CHECKING_METHOD_DIGEST = (
    'CHECKING METHOD (digest of the unfoldingWord Translation Academy "Checking" articles: '
    'Accuracy Check, Complete, Clear, Natural, Acceptable Style, Spelling, Punctuation, Formatting, '
    'Alignment Checking, translationNotes Check, translationWords Check, Language Community Check, '
    'Quality Checker Evaluation). '
    'Accuracy: compare the translation with the original-language passage, never with an English gloss. '
    'Does the translation add anything to the original meaning (implicit information is part of the original meaning)? '
    'Is any part of the meaning left out? Has the meaning changed? Was everything mentioned in the source also '
    'mentioned in the flow of the translation? Does the message, not necessarily the wording or the order, follow '
    'the source? Are the same participants doing the same things, and is it easy to see who did what? Do the key '
    'terms used match the source concepts? Check a difficult sentence part by part; a different order of ideas can '
    'still be accurate. Ask of the translation alone: who did what, when, where, how and why. '
    'Complete: nothing is missing: every event, every verse, no place where something seems left out or the '
    'message differs from the source. Verse-numbering differences (bridged verses, verses moved to a footnote) do '
    'not by themselves make a translation incomplete. '
    'Clear: the words and phrases make the message understandable; the community\'s own words rather than borrowings '
    'from a national language; a style that fits the intended audience; a reader can follow without re-reading, and '
    'each part fits what precedes and follows it. '
    'Natural: it sounds as if written by a member of the language community, not by a foreigner; judged as speech, '
    'without reference to the source: would people say it this way when talking about such a thing? '
    'Acceptable style: understood by young and old; the formality the community prefers; not too many borrowed '
    'words; a form of the language the wider community understands, not one dialect only. '
    'Spelling: one agreed spelling used consistently through the book, especially for names of people and places. '
    'Punctuation: one agreed system (quotation marks, pauses, sentence ends) applied consistently. '
    'Formatting: alphabet, spelling and punctuation are decided before translating; versification and section '
    'headings are checked after a book is finished. '
    'Alignment checking: every target word is aligned to the original-language word or words it renders; a word with '
    'no counterpart is a question to raise, and the alignment shows where meaning was added, omitted or shifted. '
    'translationNotes check: for each Note, find the target rendering of the quoted word or phrase, select it, and '
    'judge whether it makes sense in context and handles the issue the Note raises; a problem becomes an edit or a '
    'comment for a reviewer, never a silent pass. '
    'translationWords check: for each key term, find and select the target rendering; judge it in context against '
    'the term\'s definition; allow contextually justified variation; note inconsistency across the book. '
    'Language community check and quality checker evaluation: community members not involved in the translation '
    'must be able to answer comprehension questions from the translation alone, and church leaders affirm accuracy, '
    'clarity, acceptable style and community approval. Those are human steps: prepare evidence for them, do not '
    'replace them. This digest is method, not evidence: cite only evidence_catalog items as evidence.'
)


# #472: everything that is the same for every verse of every project comes
# first, byte-identical, so the provider's prefix cache (first 1,024+ tokens
# must match) can hold it; the language pair, the editorial categories and
# the check count follow as a short tail. The static block is built once at
# import. Sentence content is the pre-#472 prompt's; only the order and the
# two language-name mentions ("target-language" instead of the name, which
# the tail supplies) changed.
REVIEW_INSTRUCTIONS_STATIC = (
    'You are a senior Bible translation reviewer operating translationCore checks. '
    'The human reviewer should not have to read every resource or manually find/select target words: do that preparation now, then present concise evidence-backed final results. '
    'Return exactly one check_reviews row for EVERY supplied translationCore check. Use every supplied check_id exactly once; do not omit, combine, duplicate, rename, or invent checks. '
    'For each check, read its evidence_catalog items, understand the source quote and note/key-term concept, examine EVERY supplied target bottomWord (including inflected and compound surface forms), locate the exact existing target-language bottomWord IDs that represent it, and return those IDs. '
    'Use ONLY supplied target-language selection IDs; never invent/normalize/rewrite tokens. '
    'A correct translation still requires selection_ids for the exact target word or phrase that carries the checked meaning. '
    'Do not set nothing_to_select merely because the verdict is pass or because you think selecting text is optional. '
    'A genuinely absent or incorrectly rendered checked meaning is a problem: return verdict=problem, empty selection_ids, and nothing_to_select=false so the issue remains unresolved. '
    'Set nothing_to_select=true only when the check is structurally not applicable. A source key term that is translated by a suffix-bearing or compound target token is applicable and must select that entire supplied token ID. '
    'If the rationale names or quotes a target rendering, include every corresponding supplied target ID in selection_ids. '
    'For Translation Notes, apply the linked Translation Academy method/principle and judge whether the target translation handles the specific issue. '
    'For Translation Words, use the Translation Word article, TWL occurrence, source morphology, and approved project renderings; allow contextually justified variation. '
    'Then perform whole-verse QA following the CHECKING METHOD below: accuracy/completeness first, including omission, unsupported addition, wrong lexical meaning, negation/scope, participants/pronouns, number/person, commands/questions, semantic relations, figures, terminology, and stale/misaligned meaning. '
    'Separately evaluate only the language-appropriate editorial categories listed at the end of these instructions. '
    'False-positive discipline: before reporting a missing-rendering or wrong-lexical-meaning issue, inspect every supplied target token for a valid inflected, suffixed, compounded, transliterated, or contextually equivalent rendering. Do not call a rendering absent merely because it differs from an English gloss or citation form. Test the strongest plausible explanation that the target rendering is valid, consult existing alignment/approved decisions/terminology, and report only one finding for one underlying problem. '
    'Critical findings require very high confidence and explicit evidence. Low-confidence possibilities should be review-level or omitted, not exaggerated. '
    'Reference only evidence IDs that exist in evidence_catalog. Reference Bibles/English are secondary aids, never authority over source data. '
    'Do not propose a correction merely because a literal rendering differs. Human/community final approval remains human. Return only the schema. '
    'IMPORTANT STAGE 3 LOCATION RULES: source and target verse numbers are reference anchors, not mandatory semantic boundaries. '
    'Use semantic_passage_mappings to determine where each checked source meaning is realized. '
    'selection_ids can encode ONLY the current verse bottom IDs. '
    'When a check state is found_another_verse or split_across_verses, return an empty selection_ids array and nothing_to_select=false; do not invent a current-verse token. '
    'When represented_implicitly, return empty selection_ids and nothing_to_select=false because Bridge records an explicit semantic state. '
    'When needs_passage_review, needs_extended_passage_review, target_not_located, source_anchor_unresolved, or mapping_error, do not infer omission merely from non-location; use verdict=review unless independent supplied evidence securely demonstrates a problem. '
    'Never encode found-in-another-verse as Nothing to Select. '
    + CHECKING_METHOD_DIGEST
)


def review_instructions(language: Any, check_count: int) -> str:
    """The full-review instructions: the static block, then the per-project
    and per-verse tail (#472). `language` is a plugin language context
    (`source_name`, `target_name`, `qa_categories`, `prompt_guidance`)."""
    tail = (
        f' PROJECT: this is a {language.source_name} → {language.target_name} project; '
        f'the target language is {language.target_name}. '
        f'Language-appropriate editorial categories for this project: {", ".join(language.qa_categories)}. '
        f'{language.prompt_guidance} '
        f'THIS VERSE: {check_count} input checks require exactly {check_count} result rows.'
    )
    return REVIEW_INSTRUCTIONS_STATIC + tail


def review_prompt_cache_key(project: Any) -> str:
    """The provider-side cache key for one project's review calls (#472): the
    registered project id, so every verse of a chapter or book run shares a
    prefix cache. Empty when the project has no identity (never sent)."""
    identity = getattr(project, 'workbench_identity', None)
    return str(getattr(identity, 'project_id', '') or '')


def usage_dict(usage: AIUsage) -> dict[str, int]:
    """The usage of one or more calls as stored on a review and shown in the
    AI tab (#472). `cachedInputTokens` is the part of `inputTokens` the
    provider served from its prefix cache at a tenth of the input price.
    `calls` is every request sent (#476: the semantic mapping, the gap-fill
    alignment and the review, not the review alone); `unansweredCalls` the
    ones the provider never answered, whose input is an estimate from the
    request body and whose output is unknown (counted as 0)."""
    return {
        'inputTokens': int(usage.input_tokens), 'cachedInputTokens': int(usage.cached_input_tokens),
        'outputTokens': int(usage.output_tokens), 'totalTokens': int(usage.total_tokens),
        'calls': int(usage.calls), 'unansweredCalls': int(usage.unanswered_calls),
    }


def estimate_input_tokens(body: bytes) -> int:
    """A rough token count for a request body the provider never answered
    (#476), so the call is not counted as free: ~4 ASCII characters per token
    and ~2 tokens per non-ASCII character (Devanagari, Tamil, Hebrew and Greek
    script are several bytes each under a byte-pair tokenizer). An estimate,
    and reported as one through `AIUsage.unanswered_calls`."""
    try:
        text = body.decode('utf-8')
    except UnicodeDecodeError:
        return max(1, len(body) // 4)
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return max(1, ascii_chars // 4 + (len(text) - ascii_chars) * 2)


def project_reviewer_decision(record: dict[str, Any]) -> dict[str, Any]:
    """Project one `human_decisions` check record to the fields the prompt uses.

    Dropped on purpose: `note` (free text), `model`, `evidenceProvenance`
    (resource paths), `modifiedTimestamp`, `selectionIds` (verse-local opaque
    ids), `bookId`, `app`, `schemaVersion`. A record's author and device are
    row columns, not payload keys, so they were never here; the note was."""
    return {
        'reference': f"{record.get('chapter', '')}:{record.get('verse', '')}",
        'tool': str(record.get('tool') or ''),
        'groupId': str(record.get('groupId') or ''),
        'checkId': str(record.get('checkId') or ''),
        'decision': str(record.get('decision') or ''),
        'selectionText': [str(x) for x in (record.get('selectionText') or []) if isinstance(x, (str, int, float))],
    }


def project_term_rendering(record: dict[str, Any]) -> dict[str, Any]:
    """Project one `project_term_renderings` entry to its rendering: where, for
    which source words, which target words. The selection's occurrence
    counters are verse-local and are dropped."""
    selections = record.get('selections')
    texts: list[str] = []
    if isinstance(selections, list):
        for item in selections:
            if isinstance(item, dict) and item.get('text') not in (None, ''):
                texts.append(str(item['text']))
            elif isinstance(item, str) and item:
                texts.append(item)
    return {
        'reference': str(record.get('reference') or ''),
        'source_quote': str(record.get('source_quote') or ''),
        'selections': texts,
        'nothingToSelect': bool(record.get('nothingToSelect', False)),
        'invalidated': bool(record.get('invalidated', False)),
    }


@dataclass
class AIUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    # #476: requests sent, and of those the ones never answered (a transport
    # failure after the request went out; the provider may still bill it).
    calls: int = 0
    unanswered_calls: int = 0

    def __add__(self, other: 'AIUsage') -> 'AIUsage':
        return AIUsage(
            self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens,
            self.total_tokens + other.total_tokens, self.cached_input_tokens + other.cached_input_tokens,
            self.calls + other.calls, self.unanswered_calls + other.unanswered_calls,
        )


Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]


def default_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with ai_http.urlopen(req, timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        raise AITransportError(f'Network error contacting OpenAI: {e.reason}') from e
    except (OSError, http.client.HTTPException) as e:
        # #480: a timeout or a dropped connection while the body is being read
        # arrives raw, not wrapped in URLError (urllib wraps only the connect
        # and the wait for headers). It is the same thing: the provider never
        # answered, and the request may still be billed (#476).
        raise AITransportError(f'Network error contacting OpenAI: {e}') from e


class OpenAIResponsesClient:
    ENDPOINT = 'https://api.openai.com/v1/responses'
    MODELS_ENDPOINT = 'https://api.openai.com/v1/models'

    def __init__(self, api_key: str, model: str = 'gpt-5.6', transport: Transport = default_transport, timeout: float = 240.0, reasoning_effort: str = 'medium', base_url: str = ''):
        if not api_key.strip():
            raise AIError('No OpenAI API key is configured.')
        self.api_key = api_key.strip()
        self.model = model.strip() or 'gpt-5.6'
        self.transport = transport
        self.timeout = timeout
        self.reasoning_effort = reasoning_effort if reasoning_effort in ('none','low','medium','high','xhigh','max') else 'medium'
        self.last_reasoning_effort: str | None = self.reasoning_effort
        self.last_usage = AIUsage()
        # Bridge Settings lets a person point this at any OpenAI-compatible
        # endpoint (Azure OpenAI, a self-hosted vLLM/LM Studio/Ollama
        # server, OpenRouter, etc) via api_base_url — empty means use the
        # class default above. This only changes the URL; the request
        # payload is still the OpenAI Responses API shape, so "any API"
        # here means "any OpenAI-Responses-API-compatible endpoint," not
        # literally any provider's native schema (e.g. raw Anthropic).
        if base_url.strip():
            base = base_url.strip().rstrip('/')
            self.endpoint = f'{base}/responses'
            self.models_endpoint = f'{base}/models'
        else:
            self.endpoint = self.ENDPOINT
            self.models_endpoint = self.MODELS_ENDPOINT
        self.last_cost_usd = 0.0
        # #476: one entry per request sent, answered or not, with its cost.
        # `usage_mark` / `usage_since` sum a verse's calls (mapping, gap-fill,
        # review) so none is left out of the stored usage or the lifetime
        # counter; `last_usage` is still the most recent call alone.
        self.call_log: list[tuple[AIUsage, float]] = []
        self.last_privacy_manifest: dict[str, Any] = {}
        # #472: set once a provider has rejected `prompt_cache_key`, so a
        # chapter run pays the 400 once, not once per verse.
        self.prompt_cache_key_unsupported = False

    def _model_supports_reasoning_effort(self) -> bool:
        name = self.model.lower()
        # Reasoning-family models (o1/o3/o4-mini, gpt-5.x incl. this app's
        # own gpt-5.6 tiers) accept 'reasoning.effort'. Non-reasoning chat
        # models (gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-4, gpt-3.5, ...) do
        # not and return HTTP 400 if it's present.
        if name.startswith(('o1', 'o3', 'o4')):
            return True
        if name.startswith('gpt-5'):
            return True
        return False

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        # Some wrappers expose output_text. Raw Responses API uses output[].content[].text.
        direct = data.get('output_text')
        if isinstance(direct, str) and direct:
            return direct
        parts: list[str] = []
        for item in data.get('output', []) if isinstance(data.get('output'), list) else []:
            if not isinstance(item, dict): continue
            for content in item.get('content', []) if isinstance(item.get('content'), list) else []:
                if isinstance(content, dict) and isinstance(content.get('text'), str):
                    parts.append(content['text'])
        return ''.join(parts)

    def _request_json(
        self, payload: dict[str, Any], headers: dict[str, str],
    ) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        status = 0
        raw = b''
        # Retry only transient transport/server failures. Schema/auth/input
        # errors fail immediately and are handled by the caller.
        for attempt in range(3):
            try:
                status, raw = self.transport(self.endpoint, headers, body, self.timeout)
            except ai_http.TransportFailure:
                # #476: the request went out and was never answered (a read
                # timeout, a dropped connection). The provider may bill the
                # input, so it is logged as an unanswered call with the input
                # estimated from the body, never as a free call.
                estimated = estimate_input_tokens(body)
                self.last_usage = AIUsage(estimated, 0, estimated, 0, calls=1, unanswered_calls=1)
                self.last_cost_usd = estimate_cost(self.model, estimated, 0)
                self.call_log.append((self.last_usage, self.last_cost_usd))
                raise
            if status not in (408, 409, 429, 500, 502, 503, 504):
                break
            if attempt < 2:
                time.sleep(1.0 * (2 ** attempt))
        try:
            response = json.loads(raw.decode('utf-8'))
        except Exception as exc:
            raise AIError(f'OpenAI returned a non-JSON response (HTTP {status}).') from exc
        if not isinstance(response, dict):
            raise AIError(f'OpenAI returned an unexpected JSON response (HTTP {status}).')
        return status, response

    @staticmethod
    def _reasoning_parameter_unsupported(status: int, response: dict[str, Any]) -> bool:
        """Recognize only an explicit optional-reasoning compatibility error.

        OpenAI-compatible providers and non-reasoning models may reject the
        optional Responses API ``reasoning`` object. Do not retry arbitrary
        input errors: that could conceal a real schema/prompt problem.
        """
        if status != 400:
            return False
        error = response.get('error')
        if not isinstance(error, dict):
            return False
        parameter = str(error.get('param') or '').strip().lower()
        code = str(error.get('code') or '').strip().lower()
        message = str(error.get('message') or '').strip().lower()
        reasoning_parameter = parameter in {
            'reasoning', 'reasoning.effort', 'reasoning_effort',
        }
        explicitly_unsupported = (
            code in {'unsupported_parameter', 'unsupported_value'}
            or 'not supported' in message
            or 'unsupported parameter' in message
        )
        mentions_reasoning = 'reasoning.effort' in message or 'reasoning_effort' in message
        return explicitly_unsupported and (reasoning_parameter or mentions_reasoning)

    @staticmethod
    def _prompt_cache_key_unsupported(status: int, response: dict[str, Any]) -> bool:
        """Recognize only an explicit rejection of the optional ``prompt_cache_key``
        (#472), with the same discipline as the reasoning guard: an arbitrary
        400 is a real problem and is not retried."""
        if status != 400:
            return False
        error = response.get('error')
        if not isinstance(error, dict):
            return False
        parameter = str(error.get('param') or '').strip().lower()
        code = str(error.get('code') or '').strip().lower()
        message = str(error.get('message') or '').strip().lower()
        explicitly_unsupported = (
            code in {'unsupported_parameter', 'unsupported_value', 'unknown_parameter'}
            or 'not supported' in message
            or 'unsupported parameter' in message
            or 'unknown parameter' in message
            or 'unrecognized request argument' in message
        )
        return explicitly_unsupported and (parameter == 'prompt_cache_key' or 'prompt_cache_key' in message)

    def _effective_reasoning_effort(self) -> str:
        return self.last_reasoning_effort or 'provider-default'

    def usage_mark(self) -> int:
        """A position in the call log, for `usage_since`."""
        return len(self.call_log)

    def usage_since(self, mark: int) -> tuple[AIUsage, float]:
        """The summed usage and estimated cost of every request sent since
        `mark` (#476), answered or not."""
        total = AIUsage()
        cost = 0.0
        for usage, call_cost in self.call_log[mark:]:
            total = total + usage
            cost += call_cost
        return total, cost

    def _post_text(
        self, instructions: str, input_text: str, schema_name: str, schema: dict[str, Any],
        prompt_cache_key: str | None = None,
    ) -> str:
        """Issue one Responses API call and return its raw output text.

        Split out of _post_structured so a caller that must tolerate a
        provider ignoring the JSON schema (fenced output, a bare array, a
        preamble) can parse defensively instead of taking _post_structured's
        hard AIError. Everything about the request — the reasoning guard, the
        unsupported-parameter retry, usage and cost accounting — is shared;
        only the parse differs.
        """
        payload: dict[str, Any] = {
            'model': self.model,
            'store': False,
            'instructions': instructions,
            'input': input_text,
            'text': {
                'format': {
                    'type': 'json_schema',
                    'name': schema_name,
                    'strict': True,
                    'schema': schema,
                }
            },
        }
        # The 'reasoning' parameter is only accepted by reasoning-family
        # models (o-series, gpt-5.x). Non-reasoning chat models such as
        # gpt-4o-mini reject it with HTTP 400 "Unsupported parameter", so
        # only attach it when the configured model is known to support it.
        if self._model_supports_reasoning_effort():
            payload['reasoning'] = {'effort': self.reasoning_effort}
        # #472: the provider caches an identical prompt prefix and charges it
        # at a tenth of the input price; the key routes every call of one
        # project to the same cache. Optional, and dropped for the session the
        # first time an OpenAI-compatible endpoint rejects it.
        if prompt_cache_key and not self.prompt_cache_key_unsupported:
            payload['prompt_cache_key'] = str(prompt_cache_key)
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'translationCore-AI-Bridge/0.9.6',
        }
        self.last_reasoning_effort = self.reasoning_effort
        status, response = self._request_json(payload, headers)
        if self._reasoning_parameter_unsupported(status, response):
            payload = dict(payload)
            payload.pop('reasoning', None)
            status, response = self._request_json(payload, headers)
            self.last_reasoning_effort = None
        if 'prompt_cache_key' in payload and self._prompt_cache_key_unsupported(status, response):
            payload = dict(payload)
            payload.pop('prompt_cache_key', None)
            self.prompt_cache_key_unsupported = True
            status, response = self._request_json(payload, headers)
        if status < 200 or status >= 300:
            err = response.get('error', {})
            msg = err.get('message') if isinstance(err, dict) else None
            raise AIError(f'OpenAI API error HTTP {status}: {msg or "request failed"}')
        usage = response.get('usage', {})
        input_details=usage.get('input_tokens_details', {}) if isinstance(usage,dict) else {}
        cached=int(input_details.get('cached_tokens',0) or 0) if isinstance(input_details,dict) else 0
        self.last_usage = AIUsage(
            int(usage.get('input_tokens', 0) or 0),
            int(usage.get('output_tokens', 0) or 0),
            int(usage.get('total_tokens', 0) or 0),
            cached,
            calls=1,
        )
        self.last_cost_usd=estimate_cost(self.model,self.last_usage.input_tokens,self.last_usage.output_tokens,self.last_usage.cached_input_tokens)
        self.call_log.append((self.last_usage, self.last_cost_usd))
        text = self._extract_text(response)
        if not text:
            raise AIError('OpenAI response contained no output text.')
        return text

    def _post_structured(
        self, instructions: str, input_text: str, schema_name: str, schema: dict[str, Any],
        prompt_cache_key: str | None = None,
    ) -> dict[str, Any]:
        text = self._post_text(instructions, input_text, schema_name, schema, prompt_cache_key=prompt_cache_key)
        try:
            result = json.loads(text)
        except json.JSONDecodeError as e:
            raise AIError('OpenAI output was not valid structured JSON.') from e
        if not isinstance(result, dict):
            raise AIError('OpenAI structured output was not an object.')
        return result

    # Schema for one AI-triage batch. Strict json_schema is still sent (it is
    # what OpenAI itself honours), but tc_ai_bridge/triage.py parses the raw
    # text defensively because OpenAI-compatible endpoints behind
    # api_base_url frequently ignore it.
    TRIAGE_SCHEMA: dict[str, Any] = {
        'type': 'object',
        'additionalProperties': False,
        'required': ['results'],
        'properties': {
            'results': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': ['finding_id', 'verdict', 'confidence', 'reason'],
                    'properties': {
                        'finding_id': {'type': 'string'},
                        'verdict': {
                            'type': 'string',
                            'enum': ['true_positive', 'false_positive', 'uncertain'],
                        },
                        'confidence': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                        'reason': {'type': 'string'},
                    },
                },
            },
        },
    }

    def triage_batch(self, instructions: str, input_text: str) -> str:
        """One AI-triage batch. Returns raw output text for the caller to parse."""
        return self._post_text(instructions, input_text, 'finding_triage', self.TRIAGE_SCHEMA)

    def propose_cross_verse_links(
        self, instructions: str, input_text: str, schema: dict[str, Any],
    ) -> dict[str, Any]:
        """One cross-verse link proposal batch (#146).

        Deliberately thin, and the prompt and schema come from the caller: the
        domain knowledge -- which ids the model may use, why a same-verse pair is
        meaningless, what gates an automatic link -- belongs with the proposal
        logic in `cross_verse_ai_proposals.py`, not in the transport. Same split
        as `triage_batch`. Structured rather than raw text because, unlike triage,
        every field here is resolved back against a Bridge-built id table, so a
        provider that ignores the schema should fail loudly rather than be parsed
        defensively into a guess.
        """
        return self._post_structured(instructions, input_text, 'cross_verse_links', schema)

    def propose_window_alignment(
        self, instructions: str, input_text: str, schema: dict[str, Any], direction: str,
    ) -> dict[str, Any]:
        """One pass of the automatic window alignment (#219). Thin on purpose,
        like `propose_cross_verse_links`: the prompt, the schema and the
        agreement rules belong to `alignment_window` / `alignment_agreement`.
        Structured, so a provider that ignores the schema fails loudly rather
        than being parsed into a guess."""
        name = 'window_alignment_' + ''.join(ch if ch.isalnum() else '_' for ch in direction)
        return self._post_structured(instructions, input_text, name, schema)

    def test_connection(self) -> dict[str, Any]:
        """Authenticate the API key and confirm the configured model is accessible without generating tokens."""
        url = f'{self.models_endpoint}/{urllib.parse.quote(self.model, safe="")}'
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {self.api_key}',
            'User-Agent': 'translationCore-AI-Bridge/0.9.6',
        }, method='GET')
        try:
            with ai_http.urlopen(req, min(self.timeout, 30.0)) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        except urllib.error.URLError as e:
            raise AIError(f'Network error contacting OpenAI: {e.reason}') from e
        try:
            data = json.loads(raw.decode('utf-8'))
        except Exception as e:
            raise AIError(f'OpenAI returned a non-JSON response while testing API access (HTTP {status}).') from e
        if status < 200 or status >= 300:
            err = data.get('error', {}) if isinstance(data, dict) else {}
            msg = err.get('message') if isinstance(err, dict) else None
            raise AIError(f'OpenAI API connection test failed HTTP {status}: {msg or "request failed"}')
        if not isinstance(data, dict) or not data.get('id'):
            raise AIError('OpenAI API connection test returned an unexpected model response.')
        return data

    def propose_alignment(
        self, project: TranslationCoreProject, chapter: str, verse: str,
        alignment: VerseAlignment, mode: str = 'gap_fill',
        semantic_mapping_pack: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ask AI only for linguistic token links; compile legal tC groups deterministically.

        mode='gap_fill' protects every existing non-empty alignment group and primarily asks AI
        about unresolved source/target tokens. mode='audit' is read-only analysis of the whole
        verse and may propose an alternative complete grouping for human inspection.
        """
        inv = make_inventory(alignment)
        current_reference = f'{project.book_id} {chapter}:{verse}'
        semantic_exclusions = cross_verse_alignment_exclusions(
            alignment=alignment,
            semantic_pack=semantic_mapping_pack,
            current_reference=current_reference,
        )
        protected_cross_verse_top_ids = set(semantic_exclusions.get('top_ids', []))
        language = PluginRegistry().detect_project(project, alignment, project.target_verse_text(chapter, verse))

        protected_top: set[str] = set(); protected_bottom: set[str] = set()
        existing_groups = []
        for group in alignment.alignments:
            top_ids=[inv.top_sig_to_id[x.signature] for x in group.top_words if x.signature in inv.top_sig_to_id]
            bottom_ids=[inv.bottom_sig_to_id[x.signature] for x in group.bottom_words if x.signature in inv.bottom_sig_to_id]
            if top_ids and bottom_ids:
                protected_top.update(top_ids); protected_bottom.update(bottom_ids)
            existing_groups.append({'top_ids':top_ids,'bottom_ids':bottom_ids})

        # Give the model the full verse as context, but explicitly mark unresolved IDs. This is
        # necessary for target-only gaps that legitimately attach to an existing source group.
        # The deterministic compiler, not the model, decides whether an extension is safe.
        top_ids_for_ai = list(inv.top_ids)
        bottom_ids_for_ai = list(inv.bottom_ids)
        unresolved_top_ids = [x for x in inv.top_ids if x not in protected_top]
        unresolved_bottom_ids = [x for x in inv.bottom_ids if x not in protected_bottom]

        top = [
            {'id': tid, 'word': inv.top_ids[tid].word, 'occurrence': inv.top_ids[tid].occurrence,
             'occurrences': inv.top_ids[tid].occurrences, 'strong': inv.top_ids[tid].strong,
             'lemma': inv.top_ids[tid].lemma, 'morph': inv.top_ids[tid].morph}
            for tid in top_ids_for_ai
        ]
        bottom = [
            {'id': tid, 'word': inv.bottom_ids[tid].word, 'occurrence': inv.bottom_ids[tid].occurrence,
             'occurrences': inv.bottom_ids[tid].occurrences}
            for tid in bottom_ids_for_ai
        ]
        tc_checks = []
        for e in project.checks_for_verse(chapter, verse):
            c = e.get('contextId', {})
            tc_checks.append({
                'tool': c.get('tool'), 'groupId': c.get('groupId'), 'quoteString': c.get('quoteString'),
                'occurrenceNote': c.get('occurrenceNote'), 'existingSelections': e.get('selections'),
            })
        input_obj = {
            'reference': f'{project.book_id} {chapter}:{verse}',
            'mode': mode,
            'target_verse': project.target_verse_text(chapter, verse),
            'source_tokens_to_consider': top,
            'target_tokens_to_consider': bottom,
            # Backwards-compatible payload aliases retained for existing tests/plugins. In v0.7.4
            # these arrays contain only the tokens the AI is allowed to consider in gap-fill mode.
            'hebrew_topWords': top,
            'tamil_bottomWords': bottom,
            'protected_existing_groups': existing_groups if mode == 'gap_fill' else [],
            'unresolved_source_ids': unresolved_top_ids if mode == 'gap_fill' else list(inv.top_ids),
            'unresolved_target_ids': unresolved_bottom_ids if mode == 'gap_fill' else list(inv.bottom_ids),
            'translationCore_checks': tc_checks,
            'language_context': language.to_dict(),
            'semantic_mapping_alignment_exclusions': semantic_exclusions,
        }
        self.last_privacy_manifest = ai_payload_manifest(input_obj['reference'], input_obj)
        schema = {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                'links': {
                    'type': 'array',
                    'items': {
                        'type': 'object', 'additionalProperties': False,
                        'properties': {
                            'top_id': {'type': 'string'},
                            'bottom_id': {'type': 'string'},
                            'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                            'reason': {'type': 'string'},
                        },
                        'required': ['top_id','bottom_id','confidence','reason'],
                    },
                },
                'implicit_top_ids': {'type': 'array', 'items': {'type': 'string'}},
                'target_only_ids': {'type': 'array', 'items': {'type': 'string'}},
                'review_notes': {'type': 'array', 'items': {'type': 'string'}},
            },
            'required': ['links','implicit_top_ids','target_only_ids','review_notes'],
        }
        scope = (
            'Existing non-empty alignment groups are protected project evidence. Focus on unresolved IDs. Emit a link involving a protected token only when needed to attach an unresolved token; never bridge/remap two established groups. '
            'you may restate a protected relationship only if needed for reasoning, but do not propose remapping it.'
            if mode == 'gap_fill' else
            'Audit the whole verse. This is read-only: propose the strongest linguistic links for human comparison with existing alignment.'
        )
        instructions = (
            f'You are a Bible translation word-alignment reviewer for {language.source_name} → {language.target_name}. '
            'Return INDIVIDUAL linguistic links, not translationCore alignment groups. The application will compile links deterministically into legal 1:1, 1:many, many:1, or many:many groups. '
            f'Use ONLY the supplied existing {language.source_name} top IDs and {language.target_name} bottom IDs. Never invent, normalize, respell, merge text values, or create tokens. '
            'It is valid for several source tokens to link to the same target token and for one source token to link to several target tokens; return each linguistic edge separately. '
            'Confidence belongs to that individual edge. Do not use a weak speculative edge merely to force coverage. Mark a source token in implicit_top_ids only when its meaning is genuinely represented grammatically/implicitly with no separate target token. Mark a target token in target_only_ids only when it is legitimate target-language grammatical/natural material with no separate source token; do not force an artificial source link. '
            f'{scope} Respect occurrence metadata, morphology, idioms, particles, grammatical encoding, and discontinuous phrases. '
            f'{language.prompt_guidance} English/reference word order is secondary and must not control source-to-target alignment. Return only the schema.'
        )
        instructions += (
            ' Stage 3 semantic passage mappings are authoritative for target LOCATION. '
            'Any source top ID listed in semantic_mapping_alignment_exclusions.top_ids has an overt target realization in another target verse/range. '
            'Do not link that source ID to a current-verse bottom ID and do not mark it implicit merely to force verse-local coverage.'
        )
        raw = self._post_structured(instructions, json.dumps(input_obj, ensure_ascii=False), 'tc_alignment_proposal', schema)
        raw = guard_alignment_response(raw, protected_cross_verse_top_ids)
        # Older mocks/cached responses may still use the pre-v0.7.4 groups schema. The compiler
        # normalizer accepts those for backwards compatibility, while real v0.7.4 requests use links.
        lock_policy = 'hard' if mode == 'gap_fill' and project.alignment_lock_state(chapter, verse) == 'HARD_LOCK' else 'protected'
        return compile_link_proposal(alignment, raw, mode=mode, lock_policy=lock_policy)

    def run_quality_review(self, project: TranslationCoreProject, chapter: str, verse: str, alignment: VerseAlignment) -> tuple[list[QAIssue], str]:
        inv = make_inventory(alignment)
        language = PluginRegistry().detect_project(project, alignment, project.target_verse_text(chapter, verse))
        tc_checks = []
        for e in project.checks_for_verse(chapter, verse):
            c = e.get('contextId', {})
            tc_checks.append({
                'checkId': c.get('checkId'), 'tool': c.get('tool'), 'groupId': c.get('groupId'),
                'source_quote': c.get('quoteString'), 'note': c.get('occurrenceNote'),
                'tamil_selection': e.get('selections'), 'nothingToSelect': e.get('nothingToSelect'), 'invalidated': e.get('invalidated'),
            })
        aligned = []
        for g in alignment.alignments:
            aligned.append({
                'hebrew': [{'word': x.word, 'lemma': x.lemma, 'morph': x.morph, 'strong': x.strong} for x in g.top_words],
                'tamil': [x.word for x in g.bottom_words],
            })
        input_obj = {
            'reference': f'{project.book_id} {chapter}:{verse}',
            'tamil_verse': project.target_verse_text(chapter, verse),
            'alignment_groups': aligned,
            'unaligned_tamil': [x.word for x in alignment.word_bank],
            'translationCore_checks': tc_checks,
            'language_context': language.to_dict(),
            'target_verse': project.target_verse_text(chapter, verse),
        }
        issue_schema = {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                'severity': {'type': 'string', 'enum': ['critical', 'high', 'medium', 'editorial', 'info']},
                'category': {'type': 'string'},
                'title': {'type': 'string'},
                'detail': {'type': 'string'},
                'evidence': {'type': 'string'},
                'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                'check_id': {'type': 'string'},
                'group_id': {'type': 'string'},
            },
            'required': ['severity', 'category', 'title', 'detail', 'evidence', 'confidence', 'check_id', 'group_id'],
        }
        schema = {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                'summary': {'type': 'string'},
                'issues': {'type': 'array', 'items': issue_schema},
            },
            'required': ['summary', 'issues'],
        }
        instructions = (
            f'You are a senior Bible translation QA reviewer working from {language.source_name} → {language.target_name} alignment data and translationCore checks. '
            'Prioritize source meaning accuracy over style. Flag likely omissions, unsupported additions, wrong lexical meaning, negation/scope, participant/pronoun errors, number/person/tense relationships, key-term inconsistencies, figures of speech, note requirements, alignment meaning gaps, and target-language editorial problems only when evidence is strong. '
            f'{language.prompt_guidance} Do not demand literal correspondence when the target language naturally encodes source morphology in suffixes or phrases. '
            'Before reporting a problem, actively consider a plausible target-language explanation and existing project decisions. Do not duplicate the same underlying concern under multiple labels. '
            'Do not fabricate source evidence. A critical issue must plausibly change/reverse source meaning or corrupt data and should be reported only with high confidence. Return only the schema.'
        )
        result = self._post_structured(instructions, json.dumps(input_obj, ensure_ascii=False), 'tc_quality_review', schema)
        issues: list[QAIssue] = []
        for item in result.get('issues', []):
            evidence = str(item.get('evidence', '')).strip()
            detail = str(item.get('detail', '')).strip()
            if evidence:
                detail = f'{detail}\nEvidence: {evidence}'
            issues.append(QAIssue(
                code=f'AI_{str(item.get("category", "QA")).upper().replace(" ", "_")}',
                severity=item.get('severity', 'medium'),
                title=str(item.get('title', 'AI review item')),
                detail=detail,
                source='OpenAI',
                check_id=str(item.get('check_id', '')),
                group_id=str(item.get('group_id', '')),
                confidence=float(item.get('confidence', 0) or 0),
            ))
        issues, suppressed = gate_ai_issues(issues)
        summary = str(result.get('summary', ''))
        if suppressed:
            summary += f' · {len(suppressed)} low-confidence/duplicate AI finding(s) suppressed by reviewer-noise gate.'
        return issues, summary

    def run_full_review(
        self, project: TranslationCoreProject, chapter: str, verse: str,
        alignment: VerseAlignment, knowledge_base=None, progress_callback=None,
        expected_input_fingerprint: str | None = None,
        semantic_mapping_pack: dict[str, Any] | None = None,
    ) -> tuple[list[AICheckReview], list[QAIssue], str, dict[str, Any]]:
        """AI performs the resource reading + target selection work, human reviews final evidence-backed results."""
        from .knowledge_base import TranslationHelpsKnowledgeBase

        kb = knowledge_base or TranslationHelpsKnowledgeBase(project)
        language = PluginRegistry().detect_project(project, alignment, project.target_verse_text(chapter, verse))
        if progress_callback: progress_callback(48, 'Building verse evidence package')
        inv = make_inventory(alignment)
        bottom_tokens = [
            {'id': tid, 'word': t.word, 'occurrence': t.occurrence, 'occurrences': t.occurrences}
            for tid, t in inv.bottom_ids.items()
        ]
        top_tokens = [
            {'id': tid, 'word': t.word, 'occurrence': t.occurrence, 'occurrences': t.occurrences,
             'strong': t.strong, 'lemma': t.lemma, 'morph': t.morph}
            for tid, t in inv.top_ids.items()
        ]
        aligned = []
        for g in alignment.alignments:
            aligned.append({
                'hebrew': [{'word': x.word, 'lemma': x.lemma, 'morph': x.morph, 'strong': x.strong,
                            'occurrence': x.occurrence, 'occurrences': x.occurrences} for x in g.top_words],
                'tamil': [{'word': x.word, 'occurrence': x.occurrence, 'occurrences': x.occurrences} for x in g.bottom_words],
            })

        pack = kb.evidence_pack_for_verse(chapter, verse, max_chars=42000)
        if progress_callback: progress_callback(58, 'Translation Helps evidence resolved')
        evidence_catalog: dict[str, dict[str, Any]] = {}
        check_inputs = []
        ev_n = 1
        for c in pack.get('checks', []):
            ev_ids = []
            for ev in c.get('evidence', []):
                eid = f'E{ev_n:03d}'; ev_n += 1
                evidence_catalog[eid] = ev
                ev_ids.append(eid)
            group = str(c.get('groupId') or '')
            history = (
                [project_term_rendering(r) for r in kb.project_term_renderings(group, 120)]
                if c.get('tool') == 'translationWords' else []
            )
            check_inputs.append({
                'tool': c.get('tool'), 'groupId': group, 'checkId': c.get('checkId'),
                'source_quote': c.get('source_quote'), 'occurrence': c.get('occurrence'),
                'occurrenceNote': c.get('occurrenceNote'), 'existingSelections': c.get('existingSelections'),
                'nothingToSelect': c.get('nothingToSelect'), 'invalidated': c.get('invalidated'),
                'evidence_ids': ev_ids, 'approved_project_renderings': history,
            })
        # The Translation Academy checking articles are no longer catalogued
        # here (#471): the method is `CHECKING_METHOD_DIGEST` in the
        # instructions, so a `qa_issues` row cites verse evidence only.
        for rb in pack.get('reference_bibles', []):
            eid=f'E{ev_n:03d}'; ev_n += 1; evidence_catalog[eid]=rb

        # #476: everything from here to the review's answer is this review's
        # usage -- the mapping call below when this runs on its own (from
        # prepare_verse_review the mapping and the gap-fill came before and
        # are summed there), then the review call.
        usage_mark = self.usage_mark()
        if semantic_mapping_pack is None:
            semantic_mapping_pack = prepare_semantic_mappings_for_review(
                project=project,
                client=self,
                chapter=chapter,
                verse=verse,
            )

        # Each token list and the verse go once, under the language-neutral
        # names (#471). The `tamil_verse` / `hebrew_topWords` /
        # `tamil_bottomWords` aliases were a second copy of the same data for
        # old tests and plugins; nothing reads them from this payload now
        # (the alignment proposal in `propose_alignment` has its own fields).
        # Key order is the serialised order (#472): the project-level constants
        # first so the input's prefix is identical from verse to verse, the
        # verse itself last.
        input_obj = {
            'resource_provenance': pack.get('resource_provenance', {}),
            'language_context': language.to_dict(),
            # Ordered by the timestamp, which is then dropped with the rest of
            # the record's identity (#470, `project_reviewer_decision`).
            'project_reviewer_decisions': [
                project_reviewer_decision(d)
                for d in sorted(project.project_decisions(), key=lambda d: str(d.get('modifiedTimestamp', '')))[-100:]
            ],
            'reference': f'{project.book_id} {chapter}:{verse}',
            'target_verse': project.target_verse_text(chapter, verse),
            'source_topWords': top_tokens,
            'target_bottomWords': bottom_tokens,
            'current_alignment_groups': aligned,
            'translationCore_checks': check_inputs,
            'evidence_catalog': evidence_catalog,
            'semantic_passage_mappings': semantic_mapping_pack.get('mappings', []) if semantic_mapping_pack else [],
            'semantic_mapping_check_states': semantic_mapping_pack.get('checkStates', []) if semantic_mapping_pack else [],
            'semantic_mapping_unresolved': semantic_mapping_pack.get('unresolved', []) if semantic_mapping_pack else [],
        }
        self.last_privacy_manifest = ai_payload_manifest(input_obj['reference'], input_obj)

        check_schema = {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                'tool': {'type': 'string'}, 'group_id': {'type': 'string'}, 'check_id': {'type': 'string'},
                'source_quote': {'type': 'string'},
                'selection_ids': {'type': 'array', 'items': {'type': 'string'}},
                'nothing_to_select': {'type': 'boolean'},
                'verdict': {'type': 'string', 'enum': ['pass','review','problem','not_applicable']},
                'severity': {'type': 'string', 'enum': ['critical','high','medium','editorial','info']},
                'rationale': {'type': 'string'}, 'suggested_correction': {'type': 'string'},
                'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                'evidence_ids': {'type': 'array', 'items': {'type': 'string'}},
            },
            'required': ['tool','group_id','check_id','source_quote','selection_ids','nothing_to_select','verdict','severity','rationale','suggested_correction','confidence','evidence_ids'],
        }
        issue_schema = {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                'severity': {'type': 'string', 'enum': ['critical','high','medium','editorial','info']},
                'category': {'type': 'string'}, 'title': {'type': 'string'}, 'detail': {'type': 'string'},
                'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                'check_id': {'type': 'string'}, 'group_id': {'type': 'string'},
                'evidence_ids': {'type': 'array', 'items': {'type': 'string'}},
            },
            'required': ['severity','category','title','detail','confidence','check_id','group_id','evidence_ids'],
        }
        schema = {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                'summary': {'type': 'string'},
                # Strict structured-output providers can enforce complete coverage before
                # Bridge receives the response. Parser validation below remains the safety
                # net for compatible providers that do not enforce JSON Schema fully.
                'check_reviews': {
                    'type': 'array',
                    'items': check_schema,
                    'minItems': len(check_inputs),
                    'maxItems': len(check_inputs),
                },
                'qa_issues': {'type': 'array', 'items': issue_schema},
            },
            'required': ['summary','check_reviews','qa_issues'],
        }
        instructions = review_instructions(language, len(check_inputs))
        if progress_callback: progress_callback(64, 'AI reviewing Notes, Words and whole verse')
        result = self._post_structured(
            instructions, json.dumps(input_obj, ensure_ascii=False), 'tc_full_review', schema,
            prompt_cache_key=review_prompt_cache_key(project),
        )
        review_usage, review_cost = self.usage_since(usage_mark)
        if progress_callback: progress_callback(88, 'Validating AI selections and evidence')

        reviews: list[AICheckReview] = []
        known_ids = set(inv.bottom_ids)
        for item in result.get('check_reviews', []):
            ids = [str(x) for x in item.get('selection_ids', [])]
            unknown = [x for x in ids if x not in known_ids]
            if unknown:
                raise AIError(f'AI check review referenced unknown target-language token ID(s): {", ".join(unknown)}')
            if len(ids) != len(set(ids)):
                raise AIError('AI check review duplicated a target-language token ID in one selection.')
            nothing = bool(item.get('nothing_to_select', False))
            if nothing and ids:
                raise AIError('AI check review returned both selection_ids and nothing_to_select=true.')
            verdict = str(item.get('verdict','review'))
            rationale = str(item.get('rationale',''))
            texts = [inv.bottom_ids[x].word for x in ids]
            selections = [
                {
                    'text': inv.bottom_ids[x].word,
                    'occurrence': inv.bottom_ids[x].occurrence,
                    'occurrences': inv.bottom_ids[x].occurrences,
                }
                for x in ids
            ]
            if nothing and not ids and verdict != 'not_applicable':
                recovered = _recover_quoted_target_selections(
                    rationale, project.target_verse_text(chapter, verse),
                )
                if recovered:
                    nothing = False
                    selections = recovered
                    texts = [selection['text'] for selection in recovered]
                    rationale = (
                        rationale
                        + '\n\nSelection consistency gate: Bridge resolved the exact target text '
                          'quoted in the AI rationale because it occurs once in this verse.'
                    ).strip()
                elif verdict in {'pass', 'review'}:
                    # A pass with neither an exact selection nor an explicit
                    # not-applicable conclusion is not a completed tC check.
                    # Keep it pending and prevent both Basic auto-application
                    # and Advanced "Apply AI proposal" from saving a false NTS.
                    nothing = False
                    verdict = 'review'
                    rationale = (
                        rationale
                        + '\n\nSelection consistency gate: no exact, unambiguous target text '
                          'was proposed. Select it manually or rerun the AI review.'
                    ).strip()
                elif verdict == 'problem':
                    # Missing/incorrect meaning is unresolved reviewer work. It
                    # must never be persisted as translationCore's completed
                    # Nothing-to-Select decision merely because there is no
                    # target span to select.
                    nothing = False
                    rationale = (
                        rationale
                        + '\n\nSelection consistency gate: a reported translation problem is '
                          'not a Nothing-to-Select decision. The check remains unresolved.'
                    ).strip()
            evidence_ids = [str(x) for x in item.get('evidence_ids', [])]
            unknown_evidence = [x for x in evidence_ids if x not in evidence_catalog]
            if unknown_evidence:
                raise AIError(f'AI check review referenced unknown evidence ID(s): {", ".join(unknown_evidence)}')
            evs = [evidence_catalog[x] for x in evidence_ids]
            reviews.append(AICheckReview(
                tool=str(item.get('tool','')), group_id=str(item.get('group_id','')), check_id=str(item.get('check_id','')),
                source_quote=str(item.get('source_quote','')), proposed_selection_ids=ids, proposed_selection_text=texts,
                proposed_selections=selections,
                nothing_to_select=nothing, verdict=verdict, severity=item.get('severity','medium'),
                rationale=rationale, suggested_correction=str(item.get('suggested_correction','')),
                confidence=float(item.get('confidence',0) or 0), evidence_used=evs,
            ))
        # Ensure AI did not silently omit or fabricate a supplied check. Missing model rows
        # become explicit review items rather than causing the entire verse/batch to disappear.
        expected_map = {str(c.get('checkId')): c for c in check_inputs if c.get('checkId')}
        returned_ids = [x.check_id for x in reviews if x.check_id]
        extras = sorted(set(returned_ids) - set(expected_map))
        if extras:
            raise AIError(f'AI full review returned unknown translationCore check(s): {", ".join(extras[:8])}')
        if len(returned_ids) != len(set(returned_ids)):
            raise AIError('AI full review duplicated a translationCore check result.')
        for review in reviews:
            expected = expected_map.get(review.check_id)
            if expected and (
                review.tool != str(expected.get('tool') or '')
                or review.group_id != str(expected.get('groupId') or '')
            ):
                raise AIError(
                    f'AI full review changed the native identity of check {review.check_id}.'
                )
        missing = sorted(set(expected_map) - set(returned_ids))
        for check_id in missing:
            c = expected_map[check_id]
            evs = [evidence_catalog[x] for x in c.get('evidence_ids', []) if x in evidence_catalog]
            reviews.append(AICheckReview(
                tool=str(c.get('tool','')), group_id=str(c.get('groupId','')), check_id=check_id,
                source_quote=str(c.get('source_quote') or ''), proposed_selection_ids=[], proposed_selection_text=[],
                nothing_to_select=False, verdict='review', severity='high',
                rationale='AI response omitted this translationCore check. No automatic conclusion was accepted; rerun this verse/check or review it manually.',
                suggested_correction='', confidence=0.0, evidence_used=evs,
            ))

        issues: list[QAIssue] = []
        for item in result.get('qa_issues', []):
            evidence_ids = [str(x) for x in item.get('evidence_ids', [])]
            unknown_evidence = [x for x in evidence_ids if x not in evidence_catalog]
            if unknown_evidence:
                raise AIError(f'AI QA issue referenced unknown evidence ID(s): {", ".join(unknown_evidence)}')
            evs=[evidence_catalog[x] for x in evidence_ids]
            evidence_text='\n'.join(f"• {e.get('title','Evidence')}: {str(e.get('content',''))[:900]}" for e in evs)
            detail=str(item.get('detail','')).strip()
            if evidence_text:
                detail += '\nEvidence used:\n' + evidence_text
            issues.append(QAIssue(
                code=f'AI_{str(item.get("category","QA")).upper().replace(" ","_")}',
                severity=item.get('severity','medium'), title=str(item.get('title','AI review item')), detail=detail,
                source='OpenAI+KnowledgeBase', check_id=str(item.get('check_id','')), group_id=str(item.get('group_id','')),
                confidence=float(item.get('confidence',0) or 0),
            ))

        reviews = gate_check_reviews(reviews)
        reviews = apply_semantic_review_policy_all(reviews, semantic_mapping_pack)
        active_issues, suppressed_issues = gate_ai_issues(issues)
        issues = active_issues
        summary = str(result.get('summary',''))
        if suppressed_issues:
            summary += f' · {len(suppressed_issues)} low-confidence/duplicate AI finding(s) suppressed.'
        if expected_input_fingerprint is not None and project.review_input_fingerprint(chapter, verse) != expected_input_fingerprint:
            raise AIError('Verse/project data changed while AI was working; stale AI review was discarded.')
        saved = project.record_ai_review_result(chapter, verse, {
            'summary': summary,
            'model': self.model,
            'reasoningEffort': self._effective_reasoning_effort(),
            'estimatedCostUSD': review_cost,
            'dependencySnapshot': dependency_snapshot(project, chapter, verse, knowledge_base, self.model),
            'resourceProvenance': pack.get('resource_provenance', {}),
            'privacyManifest': self.last_privacy_manifest,
            'usage': usage_dict(review_usage),
            'checkReviews': [x.to_dict() for x in reviews],
            'qaIssues': [x.to_dict() for x in issues],
            'suppressedQaIssues': [x.to_dict() for x in suppressed_issues],
            'languageContext': language.to_dict(),
            'semanticMapping': semantic_mapping_pack,
        })
        return reviews, issues, summary, {'resource_provenance': pack.get('resource_provenance', {}), 'saved_to': str(saved), 'evidence_catalog': evidence_catalog, 'model': self.model, 'reasoning_effort': self._effective_reasoning_effort(), 'estimated_cost_usd': review_cost, 'usage': usage_dict(review_usage), 'privacy_manifest': self.last_privacy_manifest, 'language_context': language.to_dict(), 'suppressed_qa_count': len(suppressed_issues), 'semantic_mapping': semantic_mapping_pack}

    def prepare_verse_review(self, project: TranslationCoreProject, chapter: str, verse: str, alignment: VerseAlignment, knowledge_base=None, progress_callback=None) -> tuple[dict[str, Any] | None, VerseAlignment, list[AICheckReview], list[QAIssue], str, dict[str, Any]]:
        """
        One-click preparation for the human final reviewer.

        If alignment is incomplete, AI first proposes/validates a complete token alignment in memory.
        It then performs the evidence-backed tC check review and whole-verse QA against that proposed
        alignment. Nothing is written to translationCore alignmentData or checkData.
        """
        start_input_fingerprint = project.review_input_fingerprint(chapter, verse)
        # #476: the semantic mapping, the gap-fill alignment and the review
        # are all this verse's calls; the stored usage, the job's cost line
        # and the lifetime counter get their sum, not the review alone (on
        # #469 the review alone was 70-75% of the bill).
        usage_mark = self.usage_mark()
        if progress_callback: progress_callback(5, 'Preparing verse review')
        if progress_callback:
            progress_callback(7, 'Mapping source meanings across target passage')
        semantic_mapping_pack = prepare_semantic_mappings_for_review(
            project=project,
            client=self,
            chapter=chapter,
            verse=verse,
        )
        needs_alignment = bool(alignment.word_bank) or any(g.top_words and not g.bottom_words for g in alignment.alignments)
        proposal: dict[str, Any] | None = None
        review_alignment = alignment
        if needs_alignment:
            if progress_callback: progress_callback(12, 'AI preparing incomplete alignment')
            proposal = self.propose_alignment(project, chapter, verse, alignment, mode='gap_fill', semantic_mapping_pack=semantic_mapping_pack)
            # Automatic final-review preparation may fill gaps, but it must never
            # rewrite already-established project alignment relationships.
            validate_preparation_proposal(alignment, proposal)
            review_alignment = apply_proposal(alignment, proposal)
            if progress_callback: progress_callback(38, 'Alignment proposal validated locally')
        else:
            if progress_callback: progress_callback(38, 'Existing alignment ready')
        if project.review_input_fingerprint(chapter, verse) != start_input_fingerprint:
            raise AIError('Verse/project data changed while AI was preparing alignment; stale result was discarded.')
        reviews, issues, summary, meta = self.run_full_review(project, chapter, verse, review_alignment, knowledge_base, progress_callback=progress_callback, expected_input_fingerprint=start_input_fingerprint, semantic_mapping_pack=semantic_mapping_pack)
        prepare_usage, total_cost = self.usage_since(usage_mark)
        meta = dict(meta)
        meta['alignment_was_ai_proposed'] = proposal is not None
        meta['total_tokens_for_prepare'] = prepare_usage.total_tokens
        meta['usage'] = usage_dict(prepare_usage)
        meta['estimated_cost_usd'] = total_cost
        meta['model'] = self.model
        meta['reasoning_effort'] = self._effective_reasoning_effort()
        meta['privacy_manifest'] = self.last_privacy_manifest
        if project.review_input_fingerprint(chapter, verse) != start_input_fingerprint:
            raise AIError('Verse/project data changed before AI review could be recorded; stale result was discarded.')
        saved = project.record_ai_review_result(chapter, verse, {
            'summary': summary,
            'model': self.model,
            'reasoningEffort': self._effective_reasoning_effort(),
            'estimatedCostUSD': total_cost,
            'dependencySnapshot': dependency_snapshot(project, chapter, verse, knowledge_base, self.model),
            'resourceProvenance': meta.get('resource_provenance', {}),
            'privacyManifest': self.last_privacy_manifest,
            'usage': usage_dict(prepare_usage),
            'alignmentProposal': proposal,
            'alignmentWasAIProposed': proposal is not None,
            'reviewedAlignment': review_alignment.to_dict(),
            'checkReviews': [x.to_dict() for x in reviews],
            'qaIssues': [x.to_dict() for x in issues],
            'semanticMapping': semantic_mapping_pack,
        })
        meta['saved_to'] = str(saved)
        self.last_cost_usd = total_cost
        if progress_callback: progress_callback(100, 'Verse AI review complete')
        return proposal, review_alignment, reviews, issues, summary, meta

