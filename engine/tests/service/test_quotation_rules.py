"""Quotation settings through the dispatcher and collection-run inputs."""
import copy

from bridge_service import BridgeEngine
from tc_ai_bridge.language_qa_jobs import LanguageQaManager
from tc_ai_bridge.quotation_rules import DEFAULTS, RELATIVE_PATH, load
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.project_import import import_source, materialize_lazy_project
from tests.support.indic_qa import write_project
from tests.support.language_qa import wait
from tests.support.projects import call, link_collection


def test_collection_settings_persist_isolate_and_validate(tmp_path):
    roots = {b: write_project(tmp_path / b, b, {'1': {'1': '“Hello'}}, lang_id='eng', lang_name='English')
             for b in ('mat', 'mrk', 'luk')}
    link_collection({b: roots[b] for b in ('mat', 'mrk')})
    lazy = tmp_path / 'jhn'
    lazy.mkdir()
    link_collection({'mat': roots['mat'], 'mrk': roots['mrk'], 'jhn': lazy})
    (lazy / '.bridge/lazy-import.json').write_text('{}', encoding='utf-8')
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / 'settings/settings.json'))
    engine._language_qa = LanguageQaManager(debounce=0, yield_seconds=0)
    try:
        assert call(engine, 'project.open', {'path': str(roots['mat'])})['success']
        wait(engine._language_qa)
        path = str(roots['mat'])
        original = call(engine, 'languageQa.quotationRules.get', {'projectPath': path})['result']
        assert original['scope'] == 'collection'
        before = engine._quotation_book_hash({'path': path, 'bookId': 'mat'})
        rules = copy.deepcopy(DEFAULTS)
        rules['referenceEnabled'] = False
        rules['target']['pairs'] = [{'open': '«', 'close': '»'}]
        saved = call(engine, 'languageQa.quotationRules.set', {'projectPath': path, 'rules': rules})
        assert saved['success'], saved
        wait(engine._language_qa)
        assert not any(f['category'] == 'quotation' for f in engine._language_qa.status()['findings'])
        assert load(roots['mat']) == load(roots['mrk']) == rules
        assert load(lazy) == rules
        assert not (lazy / '.apps/translationCoreAI/bridge-workbench.sqlite3').exists()
        assert load(roots['luk']) == DEFAULTS
        assert engine._quotation_book_hash({'path': path, 'bookId': 'mat'}) != before
        rules['target']['pairs'][0]['open'] = ''
        refused = call(engine, 'languageQa.quotationRules.set', {'projectPath': path, 'rules': rules})
        assert not refused['success'] and load(roots['mat'])['target']['pairs'][0]['open'] == '«'
        assert not call(engine, 'languageQa.quotationRules.get', {'projectPath': str(roots['luk'])})['success']
        assert call(engine, 'project.open', {'path': str(roots['mrk'])})['success']
        got = call(engine, 'languageQa.quotationRules.get', {'projectPath': str(roots['mrk'])})
        assert got['result']['rules']['target']['pairs'][0]['open'] == '«'
        assert (roots['mrk'] / RELATIVE_PATH).is_file()
    finally:
        engine._language_qa.unbind()


def test_reference_changes_recheck_findings_and_collection_hash(tmp_path):
    root = write_project(tmp_path / 'mat', 'mat', {'1': {'1': 'Come.'}}, lang_id='eng', lang_name='English')
    folder = tmp_path / 'ref'
    folder.mkdir()
    tsv = folder / 'verses.tsv'
    header = 'ref\tbook\tbook_idx\tchapter\tverse\tseg\ttext\n'
    tsv.write_text(header + 'MAT 1:1\tMAT\t40\t1\t1\tv\t“Come.”\n', encoding='utf-8')
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / 'settings/settings.json'))
    engine._language_qa = LanguageQaManager(debounce=0, yield_seconds=0)
    try:
        assert call(engine, 'project.open', {'path': str(root)})['success']
        assert call(engine, 'languageQa.setReference', {'projectPath': str(root), 'folder': str(folder)})['success']
        status = wait(engine._language_qa)
        assert any(f['rule'] == 'quotation.reference-missing' for f in status['findings'])
        book = {'path': str(root), 'bookId': 'mat'}
        before = engine._quotation_book_hash(book)
        tsv.write_text(header + 'MAT 1:1\tMAT\t40\t1\t1\tv\tOrdinary narration.\n', encoding='utf-8')
        assert engine._quotation_book_hash(book) != before
        engine._language_qa.invalidate('1')
        assert not any(f['rule'] == 'quotation.reference-missing' for f in wait(engine._language_qa)['findings'])
    finally:
        engine._language_qa.unbind()


def test_rules_saved_to_a_real_lazy_import_survive_materialization(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    for book in ('MAT', 'MRK'):
        (source / f'{book}.usfm').write_text(f'\\id {book}\n\\h {book}\n\\c 1\n\\v 1 Text.\n', encoding='utf-8')
    imported = import_source(source, tmp_path / 'projects', {
        'languageId': 'eng', 'languageName': 'English', 'languageDirection': 'ltr',
        'projectName': 'Quotation test', 'bibleName': 'Local test',
    })
    first, lazy = imported['projects']
    assert lazy['lazy']
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / 'settings/settings.json'))
    engine._language_qa = LanguageQaManager(debounce=0, yield_seconds=0)
    try:
        assert call(engine, 'project.open', {'path': first['path']})['success']
        rules = copy.deepcopy(DEFAULTS)
        rules['enabled'] = False
        assert call(engine, 'languageQa.quotationRules.set', {'projectPath': first['path'], 'rules': rules})['success']
        assert load(lazy['path']) == rules
        assert materialize_lazy_project(lazy['path'])
        assert load(lazy['path']) == rules
    finally:
        engine._language_qa.unbind()
