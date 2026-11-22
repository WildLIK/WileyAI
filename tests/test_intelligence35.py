"""HTTP regression corpus; the neutral fake model cannot supply correct tool IDs."""
import importlib.util
from pathlib import Path
import json
import pytest

spec=importlib.util.spec_from_file_location("intel35_benchmark",Path(__file__).resolve().parents[1]/"scripts/benchmark-intelligence35.py")
bench=importlib.util.module_from_spec(spec);spec.loader.exec_module(bench)
CASES=json.loads((Path(__file__).parent/"fixtures/intelligence35.json").read_text(encoding="utf-8"))

@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    with bench.harness(tmp_path_factory.mktemp("intelligence35")) as value:yield value

@pytest.mark.parametrize("case",CASES,ids=[case["text"] for case in CASES])
def test_corpus(case,ctx):
    client,state=ctx
    result=bench.run_case(client,state,case)
    assert result["passed"],result

def test_retry_same_request_id_cannot_repeat_a_completed_launch(ctx):
    client,state=ctx;state['opened']=[]
    body=dict(text='Открой Blender',request_id='idempotent-35',mode='conversation')
    assert client.post('/chat',json=body).status_code==200
    assert client.post('/chat',json=body).status_code==409
    assert len(state['opened'])==1

def test_sequential_is_new_default_and_all_queue_modes_persist(ctx):
    client,_=ctx
    config=client.get('/settings').json()
    assert config['conversation_queue_mode']=='sequential'
    for mode in ('latest','queue','sequential'):
        assert client.put('/settings',json={**config,'conversation_queue_mode':mode}).json()['conversation_queue_mode']==mode

def test_generic_category_choices_are_verified_and_named_yandex_never_substitutes_chrome(ctx):
    client,state=ctx
    for query,expected in [('Открой мне браузер',{'Chrome','Яндекс Браузер','Firefox'}),('Открой программу для рисования',{'Krita','Paint'})]:
        case={'text':query,'expected_type':'clarify','parameters':{}}
        result=bench.run_case(client,state,case)
        assert not result['structured'] and not result['opened']
        messages=client.app.state.store.list('messages',10)
        # Corpus requests have their own scopes: inspect the most recent pending.
        with client.app.state.store.db() as db:
            pending=[json.loads(row['value']).get('pending_open') for row in db.execute('select value from chat_dialogue')]
        assert any(p and expected=={x['label'].split(' · ')[0] for x in p['choices']} for p in pending)
    result=bench.run_case(client,state,{'text':'Открой Яндекс Браузер','expected_type':'open','parameters':{'name':'Яндекс Браузер'}})
    assert result['opened'][0].startswith('Яндекс Браузер')

def test_indirect_purpose_uses_installed_candidates_without_a_canned_model_answer(ctx):
    client,state=ctx
    result=bench.run_case(client,state,{'text':'Хочу что-нибудь нарисовать','expected_type':'clarify','parameters':{}})
    assert result['proposed'] and all(any(name in label for name in ('Krita','Paint')) for label in result['proposed'])
    assert result['structured']==0 and result['ordinary']==0 and result['opened']==[]

def test_purpose_target_after_first_forty_catalog_entries_is_not_lost(ctx,tmp_path,monkeypatch):
    client,state=ctx;scanner=client.app.state.applications
    originals=scanner.valid_items();noise=[]
    for i in range(80):
        target=tmp_path/f'Utility{i}.exe';target.touch()
        noise.append(dict(id=f'noise{i}',name=f'Utility{i}',target=str(target),category='other',source='fixture',aliases=[]))
    monkeypatch.setattr(scanner,'valid_items',lambda:noise+originals)
    result=bench.run_case(client,state,{'text':'Хочу что-нибудь нарисовать','expected_type':'clarify','parameters':{}})
    assert len(result['proposed'])==2 and result['structured']==0 and not result['opened']
    from core.app_catalog import CATEGORIES
    assert 'games' in CATEGORIES
    noise[-1]['category']='games'
    game=bench.run_case(client,state,{'text':'Открой игру','expected_type':'clarify','parameters':{}})
    assert len(game['proposed'])==1 and not game['opened'] and game['structured']==0

def test_unknown_purpose_metadata_keeps_semantic_fallback_instead_of_false_absence(ctx,monkeypatch):
    client,state=ctx
    monkeypatch.setattr(client.app.state.applications,'purpose_matches',lambda _:[])
    result=bench.run_case(client,state,{'text':'Хочу что-нибудь нарисовать','expected_type':'clarify','parameters':{}})
    assert result['structured']==1 and not result['opened'] and not result['proposed']
