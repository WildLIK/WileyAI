"""Dataset contract, scoring and standalone safety guard; no real action boundaries."""
from copy import deepcopy
import importlib.util
import hashlib
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("intent_suite", Path(__file__).resolve().parents[1] / "scripts/benchmark-intent-suite.py")
suite = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(suite)


def test_dataset_has_300_unique_cases_and_expected_categories():
    dataset = suite.load_dataset()
    assert len(dataset['cases']) == len({c['id'] for c in dataset['cases']}) == 300
    assert set(c['c'] for c in dataset['cases']) == suite.CATEGORIES
    original = {'meta':dataset['meta'],'cases':[{k:v for k,v in c.items() if k!='id'} for c in dataset['cases']]}
    assert hashlib.sha256(json.dumps(original,ensure_ascii=False,sort_keys=True).encode()).hexdigest() == '90ddb02cf083a2dd97f7c7a43ec6a42d937bd046327005d3bada8d5d40cd3501'


@pytest.mark.parametrize('fault', ['duplicate_id','missing_id','unknown_expect','invalid_turns','invalid_volume','missing_text','wrong_count'])
def test_invalid_datasets_are_rejected(tmp_path, fault):
    data = deepcopy(suite.load_dataset())
    if fault == 'duplicate_id': data['cases'][1]['id'] = data['cases'][0]['id']
    if fault == 'missing_id': data['cases'][0].pop('id')
    if fault == 'unknown_expect': data['cases'][0]['e'] = 'shell.execute'
    if fault == 'invalid_turns': data['cases'][0]['turns'] = 'да'
    if fault == 'invalid_volume': data['cases'][0]['qv'] = True
    if fault == 'missing_text': data['cases'][0]['t'] = ''
    if fault == 'wrong_count': data['cases'].pop()
    path = tmp_path / 'invalid.json'; path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError): suite.load_dataset(path)


def test_negative_action_is_counted_from_calls_even_if_reply_claims_refusal():
    rec = suite.Rec()
    rec.open.append(('app','fixture.exe','fixture'))
    result = suite.assess({'c':'negations','e':'prohibit'}, ['Не буду открывать.'], rec)
    assert result['false_action'] and result['verdict'] == 'fail'


def test_compound_search_is_partial_dispatch_even_if_reply_says_clarify():
    rec = suite.Rec()
    rec.media.append(('search','song','Яндекс Музыка','и включи вторую',None))
    result = suite.assess({'c':'compound','e':'clarify'}, ['Найдены песни. Уточните.'], rec)
    assert result['partial_execution'] and result['verdict'] == 'fail'


def test_clarification_is_graded_by_status_and_without_case_sensitive_wording():
    rec = suite.Rec()
    rec.events.append({'type':'speech_result','action':{'status':'needs_clarification'}})
    assert suite.assess({'c':'compound','e':'clarify'}, ['Уточните одну команду.'], rec)['verdict']=='pass'
    assert suite.assess({'c':'compound','e':'clarify'}, ['Слишком много действий.'], rec)['verdict']=='pass'


def test_argument_error_and_unnecessary_clarification_are_separate():
    rec = suite.Rec(); rec.audio.append(('set_volume',20))
    result = suite.assess({'c':'base','e':'audio.volume.set','qv':40}, ['Готово'], rec)
    assert result['argument_error'] and not result['unnecessary_clarification']
    rec = suite.Rec(); rec.events.append({'type':'speech_result','action':{'status':'needs_clarification'}})
    result = suite.assess({'c':'base','e':'media.play'}, ['Уточните плеер'], rec)
    assert result['unnecessary_clarification'] and not result['argument_error']


def test_boundary_guard_blocks_and_restores_native_and_network_functions():
    import subprocess
    import httpx
    original = subprocess.Popen
    with suite.isolated_boundaries() as blocked:
        with pytest.raises(RuntimeError,match='Unmocked'): subprocess.Popen(['must-not-run'])
        with pytest.raises(RuntimeError,match='Unmocked'): httpx.get('https://example.invalid')
        assert blocked == ['Popen','httpx.Client.send']
    assert subprocess.Popen is original
