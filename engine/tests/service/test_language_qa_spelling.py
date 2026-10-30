"""The new spelling packs through the real project/status/decision flow."""
import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge.language_qa_jobs import LanguageQaManager
from tc_ai_bridge.secret_store import AppSettings
from tests.support.indic_qa import wait, write_project
from tests.support.projects import call


@pytest.mark.packs
def test_marathi_dictionary_finding_survives_the_real_review_and_rescan_flow(tmp_path):
    unknown = "माणूसमाणूसमाणूसमाणूस"
    path = write_project(tmp_path / "gen", "gen", {"1": {"1": f"देव {unknown}", "2": unknown}},
                         lang_id="mar", lang_name="Marathi")
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    engine._language_qa = LanguageQaManager(debounce=0, yield_seconds=0)
    try:
        assert call(engine, "project.open", {"path": str(path)})["success"]
        wait(engine._language_qa)
        response = call(engine, "languageQa.status", {"projectPath": str(path), "limit": 100})
        assert response["success"], response
        status = response["result"]
        assert status["language"]["pack"] == "mr-irv"
        categories = {row["category"] for row in status["coverage"]["inScope"]}
        assert "typo" in categories and "grammar" not in categories and "sandhi" not in categories
        [finding, other] = [f for f in status["findings"] if f["ruleId"] == "mr-irv/spelling.dictionary-miss"]
        assert finding["originalText"] == unknown
        words = call(engine, "languageQa.bookWords", {"projectPath": str(path), "minCount": 1})
        assert words["success"], words
        assert words["result"]["ready"] and words["result"]["words"][0]["word"] == unknown
        assert words["result"]["words"][0]["countBook"] == 2
        assert words["result"]["words"][0]["countIrv"] is None
        assert words["result"]["words"][0]["countOv"] is None
        issue = {key: finding[key] for key in ("source", "rule", "ruleId", "packVersion", "ruleRevision", "layer", "category")}
        response = call(engine, "verse.decide", {"chapter": "1", "verse": "1", "findingId": finding["id"],
                                                 "status": "ignored", "issue": issue})
        assert response["success"], response
        engine._language_qa.invalidate("1")
        wait(engine._language_qa)
        result = call(engine, "languageQa.status", {"projectPath": str(path), "limit": 100})["result"]
        assert finding["id"] not in {f["id"] for f in result["findings"]}
        assert other["id"] in {f["id"] for f in result["findings"]}
        response = call(engine, "languageQa.words.add", {"projectPath": str(path), "words": [unknown], "scope": "book"})
        assert response["success"], response
        wait(engine._language_qa)
        result = call(engine, "languageQa.status", {"projectPath": str(path), "limit": 100})["result"]
        assert not [f for f in result["findings"] if f["ruleId"] == "mr-irv/spelling.dictionary-miss"]
    finally:
        engine._language_qa.unbind()
