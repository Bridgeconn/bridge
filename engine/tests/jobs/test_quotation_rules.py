"""#456: book-wide quotation policy and conservative reference evidence."""
import copy

import pytest

from tc_ai_bridge.quotation_rules import DEFAULTS, quotation_findings, validate
from tc_ai_bridge.language_packs.reference_text import ReferenceText


def check(chapters, rules=None, reference=None):
    return quotation_findings('mat', chapters, rules, reference=reference)


def ref(chapters):
    return ReferenceText('Local English', 'usfm', 'local/reference', {'MAT': chapters})


def test_matthew_5_to_7_is_one_quotation():
    chapters = {'5': {'3': 'He said, “Blessed are the poor.'},
                '6': {'1': 'Take care.'}, '7': {'27': 'And it fell.”'}}
    assert check(chapters)[0] == []
    broken = copy.deepcopy(chapters)
    broken['7']['27'] = 'And it fell.'
    finding = check(broken)[0][0]
    assert finding['chapter'] == '5' and finding['verse'] == '3'
    assert finding['originalText'] == '“' and 'closing ”' in finding['message']
    assert finding['category'] == 'quotation' and not finding['suggestions']


def test_nested_quotes_and_apostrophes_in_words():
    assert check({'1': {'1': '“Don’t say ‘can’t’.”'}})[0] == []
    assert check({'1': {'1': '“Jesus’ disciples said ‘come’.”'}})[0] == []
    assert check({'1': {'1': 'Jesus’ disciples came.'}}, reference=ref({'1': {'1': '“Jesus’ disciples.”'}}))[0]
    assert check({'1': {'1': '“Don’t say ‘can’t”.'}})[0]
    findings = check({'1': {'1': '‘Unclosed inner quote.'}})[0]
    assert len(findings) == 1  # nesting and missing-closer messages share one stable anchor/id
    assert 'expected “' in findings[0]['message'] and 'no closing ’' in findings[0]['message']


def test_target_rules_can_use_straight_or_reversed_quotes():
    rules = copy.deepcopy(DEFAULTS)
    rules['target']['pairs'] = [{'open': '"', 'close': '"'}, {'open': "'", 'close': "'"}]
    assert check({'1': {'1': '"Don\'t say \'hello\'."'}}, rules)[0] == []
    rules['target']['pairs'] = [{'open': '»', 'close': '«'}]
    assert check({'1': {'1': '»தமிழ்«'}}, rules)[0] == []


def test_continuation_at_paragraph_or_verse_start_is_configurable():
    chapters = {'1': {'1': '“First.', '2': '\\p “Second.”'}}
    assert check(chapters)[0] == []
    rules = copy.deepcopy(DEFAULTS)
    rules['target']['continuation'] = 'none'
    assert check(chapters, rules)[0]
    assert check({'1': {'1': '“First.', '2': '“Second.”'}})[0] == []
    assert check({'1': {'1': '“First.', '2': 'Then “Second.”'}})[0]


def test_inline_usfm_and_raw_unicode_spans():
    raw = 'தமிழ் \\add சொல்\\add* “வா\\f + \\ft “note\\f*'
    f = check({'1': {'3-4': raw}})[0][0]
    assert f['verse'] == '3-4' and raw[f['start']:f['end']] == '“'
    assert f['start'] == raw.index('“')
    assert check({'1': {'3a': '\\f + \\ft “note\\f* ordinary'}})[0] == []


def test_nested_and_symmetric_continuation_keep_the_original_opener():
    assert check({'5': {'3': '“He said ‘Come.'}, '6': {'1': '“ ‘Follow me.’”'}})[0] == []
    rules = copy.deepcopy(DEFAULTS)
    rules['target']['pairs'] = [{'open': '"', 'close': '"'}]
    assert check({'5': {'3': '"Come.'}, '6': {'1': '"Follow me."'}}, rules)[0] == []


def test_reference_detects_both_marks_missing_and_explains_evidence():
    reference = ref({'5': {'3': 'He said “Blessed.', '4': 'Those who mourn.”'}})
    findings, notes = check({'5': {'3': 'அவர் சொன்னார்.', '4': 'ஆறுதல்.'}}, reference=reference)
    assert not notes and len(findings) == 1
    f = findings[0]
    assert f['rule'] == 'quotation.reference-missing' and f['category'] == 'quotation'
    assert 'Possible missing' in f['message'] and 'MAT 5:3–5:4' in f['message']
    assert f['referenceEvidence']['label'] == 'Local English' and f['suggestedReplacement'] is None


def test_reference_and_target_can_have_different_conventions():
    rules = copy.deepcopy(DEFAULTS)
    rules['target']['pairs'] = [{'open': '«', 'close': '»'}]
    rules['reference']['pairs'] = [{'open': '"', 'close': '"'}]
    reference = ref({'1': {'1': '"Come."'}})
    assert check({'1': {'1': '«வா»'}}, rules, reference)[0] == []
    assert check({'1': {'1': 'வா'}}, rules, reference)[0][0]['rule'] == 'quotation.reference-missing'


def test_reference_passage_inside_a_larger_target_quotation_is_not_missing():
    reference = ref({'1': {'2': '“Come.”'}})
    assert check({'1': {'1': '“First.', '2': 'Come.', '3': 'Last.”'}}, reference=reference)[0] == []


@pytest.mark.parametrize('target', [{'1': {'1': 'Text'}}, {'1': {'1-2': 'Text'}}, {'1': {'1': 'Text', '2': ''}}])
def test_missing_or_ambiguous_correspondence_is_a_limitation(target):
    reference = ref({'1': {'1': '“First.', '2': 'Last.”'}})
    found, notes = check(target, reference=reference)
    assert found == [] and any('correspondence' in n for n in notes)


def test_exact_matching_bridges_and_segments_are_supported():
    reference = ref({'1': {'3-4': '“First.', '5a': 'Last.”'}})
    assert check({'1': {'3-4': 'First.', '5a': 'Last.'}}, reference=reference)[0]


def test_unbalanced_and_absent_reference_are_reported_as_limits():
    assert 'unavailable' in check({'1': {'1': 'Text'}})[1][0]
    assert 'unbalanced' in check({'1': {'1': 'Text'}}, reference=ref({'1': {'1': '“Text'}}))[1][0]
    assert 'unverified' in check({'1': {'1': 'Text'}}, reference=ref({'1': {'1': 'Text'}}))[1][0]


def test_rules_are_disabled_without_losing_the_configuration():
    rules = copy.deepcopy(DEFAULTS)
    rules['enabled'] = False
    assert check({'1': {'1': '“Text'}}, rules) == ([], [])


def test_rule_change_preserves_identity_but_reopens_the_review_version():
    chapters = {'1': {'1': '“Text'}}
    rules = copy.deepcopy(DEFAULTS)
    before = check(chapters, rules)[0][0]
    rules['target']['pairs'][0]['close'] = '»'
    after = check(chapters, rules)[0][0]
    assert before['id'] == after['id'] and before['packVersion'] != after['packVersion']


@pytest.mark.parametrize('pairs', [[], [{'open': '', 'close': '”'}],
    [{'open': '“', 'close': '”'}, {'open': '“', 'close': '’'}],
    [{'open': 'a', 'close': 'b'}], [{'open': '<<', 'close': '<'}]])
def test_invalid_or_ambiguous_settings_are_refused(pairs):
    rules = copy.deepcopy(DEFAULTS)
    rules['target']['pairs'] = pairs
    with pytest.raises(ValueError):
        validate(rules)
