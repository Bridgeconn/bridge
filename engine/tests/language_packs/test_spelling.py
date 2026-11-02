"""Affix-aware dictionary behaviour, Unicode identity and honest failures (#414)."""
import hashlib
import json
import unicodedata

import pytest

from tc_ai_bridge.language_packs import PackError, load_pack
from tc_ai_bridge.language_packs import spelling
from tc_ai_bridge.language_packs.loader import apply_overrides
from tc_ai_bridge.language_packs.registry import available
from tc_ai_bridge.language_qa import detect_language, scan_text


def synthetic(tmp_path, script="Deva", root="किताब", suffix="ें", *, extra=""):
    folder = tmp_path / "pack"
    folder.mkdir()
    aff = f"SET UTF-8\nSFX A Y 1\nSFX A 0 {suffix} .\n"
    dic = f"1\n{root}/A\n{extra}"
    files = {}
    for name, text in (("test.aff", aff), ("test.dic", dic)):
        data = text.encode("utf-8")
        (folder / name).write_bytes(data)
        files[name] = hashlib.sha256(data).hexdigest()
    (folder / "MANIFEST.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    meta = {"pack": "test-irv", "language": "xx", "version": "1.0.0", "rules": ["rule.json"],
            "spellingDictionary": {"path": "test", "manifest": "MANIFEST.json"}}
    rule = {"id": "spelling.dictionary-miss", "version": 1, "category": "typo", "layer": "lexicon",
            "severity": "low", "confidence": "low", "inline": False, "message": {"en": "Review {span}"},
            "match": {"type": "dictionary-lookup", "script": script}}
    (folder / "pack.json").write_text(json.dumps(meta), encoding="utf-8")
    (folder / "rule.json").write_text(json.dumps(rule), encoding="utf-8")
    return folder


def scan(pack, text):
    return [f for f in scan_text(text, book="gen", chapter="1", verse="3-4", pack=pack)["findings"]
            if f["rule"] == "spelling.dictionary-miss"]


@pytest.mark.parametrize("script,root,suffix,unknown", [
    ("Deva", "किताब", "ें", "किताबकिताबकिताब"),
    ("Beng", "কথা", "গুলো", "কথাকথাকথা"),
])
def test_affixes_are_accepted_and_unknown_forms_are_only_review_candidates(tmp_path, script, root, suffix, unknown):
    pack = load_pack(directory=synthetic(tmp_path, script, root, suffix))
    assert scan(pack, root + " " + root + suffix) == []
    [finding] = scan(pack, unknown)
    assert finding["status"] == "review-needed"
    assert finding["confidence"] == "low" and finding["inline"] is False
    assert finding["suggestedReplacement"] is None and not finding["suggestions"]
    assert finding["verse"] == "3-4"


def test_offsets_identity_and_note_exclusion_use_the_existing_scan_path(tmp_path):
    pack = load_pack(directory=synthetic(tmp_path))
    unknown = "किताबकिताबकिताब"
    text = f'😀 किताब \\f + \\ft {unknown}\\f* \\w {unknown}|lemma="{unknown}"\\w*'
    [finding] = scan(pack, text)
    assert text[finding["start"]:finding["end"]] == unknown
    assert finding["start"] == text.index(unknown, text.index("\\w "))
    [shifted] = scan(pack, "😀 " + text)
    assert finding["id"] == shifted["id"] and finding["textHash"] != shifted["textHash"]


def test_nfd_is_looked_up_canonically_without_changing_the_original_span(tmp_path):
    pack = load_pack(directory=synthetic(tmp_path, "Knda", "ದೇವರು", "ಗಳು"))
    assert scan(pack, unicodedata.normalize("NFD", "ದೇವರು")) == []
    raw = unicodedata.normalize("NFD", "ದೇವರುದೇವರುದೇವರು")
    [finding] = scan(pack, raw)
    assert finding["originalText"] == raw
    assert raw[finding["start"]:finding["end"]] == raw


def test_joiner_linked_words_are_not_split_into_false_dictionary_misses(tmp_path):
    word = "क्\u200dष"
    pack = load_pack(directory=synthetic(tmp_path, root=word))
    assert scan(pack, word) == []
    [finding] = scan(pack, word * 3)
    assert finding["originalText"] == word * 3


def test_foreign_and_mixed_script_words_are_not_judged_by_the_wrong_dictionary(tmp_path):
    pack = load_pack(directory=synthetic(tmp_path))
    assert scan(pack, "English தமிழ் किताबEnglish") == []


def test_narrowing_override_disables_the_lookup(tmp_path):
    pack = load_pack(directory=synthetic(tmp_path))
    narrowed = apply_overrides(pack, {"rules": {"spelling.dictionary-miss": {"enabled": False}}})
    assert scan(pack, "किताबकिताबकिताब")
    assert scan(narrowed, "किताबकिताबकिताब") == []


@pytest.mark.parametrize("damage", ["missing", "corrupt", "outside"])
def test_missing_corrupt_or_outside_data_refuses_the_pack_explicitly(tmp_path, damage):
    folder = synthetic(tmp_path)
    if damage == "missing":
        (folder / "test.dic").unlink()
    elif damage == "corrupt":
        (folder / "test.dic").write_text("1\nchanged", encoding="utf-8")
    else:
        meta = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
        meta["spellingDictionary"]["path"] = "../outside"
        (folder / "pack.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(PackError, match="spelling dictionary unavailable"):
        load_pack(directory=folder)


def test_changed_data_invalidates_the_scan_fingerprint_and_never_uses_old_lookup(tmp_path):
    folder = synthetic(tmp_path)
    pack = load_pack(directory=folder)
    before = pack.fingerprint()
    (folder / "test.dic").write_text("1\nchanged", encoding="utf-8")
    assert pack.fingerprint() != before
    with pytest.raises(ValueError, match="integrity"):
        spelling.dictionary(pack)


@pytest.mark.parametrize("code,alias,word", [
    ("as", "asm", "ঈশ্বৰ"), ("bn", "ben", "ঈশ্বর"), ("gu", "guj", "ઈશ્વર"),
    ("kn", "kan", "ದೇವರು"), ("mr", "mar", "देव"), ("ne", "npi", "मानिस"), ("te", "tel", "దేవుడు"),
])
@pytest.mark.packs
def test_shipped_dictionary_lookup_and_language_resolution(code, alias, word):
    pack = load_pack(f"{code}-irv")
    assert scan(pack, word) == []
    assert scan(pack, unicodedata.normalize("NFD", word)) == []
    assert scan(pack, word * 4)
    detection = detect_language(word * 12, alias)
    assert detection["pack"] == f"{code}-irv"
    assert "dictionary" in detection["message"]
    if code in {"as", "bn", "mr", "ne"}:
        assert detect_language(word * 12)["pack"] == "common"  # shared script is not a language


def test_registry_contains_the_requested_twelve_languages():
    assert {"hi", "mr", "bn", "as", "pa", "gu", "or", "ta", "te", "kn", "ml", "ne"} <= {p["language"] for p in available()}
