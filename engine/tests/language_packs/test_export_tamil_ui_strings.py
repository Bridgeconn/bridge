"""scripts/export_tamil_ui_strings.py: the committed review table is current (#235).

docs/TAMIL_UI_STRINGS.md is what the native reviewer reads, and the next
review round is its diff, so a Tamil string that changes without the table
being regenerated would slip past review (`external` marker: imports a script).
"""
from export_tamil_ui_strings import collect, main

from tc_ai_bridge import language_qa


def test_the_committed_table_matches_the_strings_in_the_code():
    assert main(["--check"]) == 0, "run: python scripts/export_tamil_ui_strings.py"


def test_every_tamil_coverage_string_is_in_the_table():
    tamil = {row["tamil"] for row in collect()}
    cov = language_qa.coverage()
    expected = {item["labelTa"] for item in cov["inScope"] if item["labelTa"]}
    expected |= {item[k] for item in cov["outOfScope"] for k in ("labelTa", "reasonTa") if item[k]}
    assert expected <= tamil


def test_row_ids_are_unique():
    ids = [row["id"] for row in collect()]
    assert len(ids) == len(set(ids))
