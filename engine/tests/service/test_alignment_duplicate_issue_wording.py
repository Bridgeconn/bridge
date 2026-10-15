"""
#149: a duplicated target token is reported once, by the per-group line that
says where it is, not a second time as a bare count from `_alignment_context`.
Real TranslationCoreProject fixture on disk, real BridgeEngine dispatch.
"""
import json
from pathlib import Path

from bridge_service import BridgeEngine
from tests.support.projects import call


def _top(word: str, strong: str) -> dict:
    return {"word": word, "strong": strong, "occurrence": 1, "occurrences": 1}


def _bottom(word: str) -> dict:
    return {"word": word, "occurrence": 1, "occurrences": 1}


def _write_book(root: Path, text: str, alignment: dict) -> None:
    (root / "rut").mkdir(parents=True)
    align_dir = root / ".apps" / "translationCore" / "alignmentData" / "rut"
    align_dir.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "rut", "name": "RUT"},
        "target_language": {"id": "tam", "name": "Tamil"},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    }), encoding="utf-8")
    (root / "rut" / "1.json").write_text(json.dumps({"1": text}, ensure_ascii=False), encoding="utf-8")
    (align_dir / "1.json").write_text(json.dumps({"1": alignment}, ensure_ascii=False), encoding="utf-8")
    (root / "rut.usfm").write_text("\\id RUT\n", encoding="utf-8")


def test_duplicate_target_token_is_reported_once_with_its_groups(tmp_path):
    root = tmp_path / "rut"
    _write_book(root, "தேவன் படைத்தார்", {
        "alignments": [
            {"topWords": [_top("אֱלֹהִ֑ים", "H430")], "bottomWords": [_bottom("தேவன்")]},
            {"topWords": [_top("בָּרָ֣א", "H1254")], "bottomWords": [_bottom("தேவன்"), _bottom("படைத்தார்")]},
        ],
        "wordBank": [],
    })
    engine = BridgeEngine()
    opened = call(engine, "project.open", {"path": str(root)})
    assert opened["success"] is True, opened

    issues = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]["issues"]

    duplicate_lines = [issue for issue in issues if "more than once" in issue]
    assert duplicate_lines == ["target token 'தேவன்' occurs more than once (group 1 and group 2)"]
