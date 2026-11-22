"""C2 candidates and CDP protocol, with fake renderers and isolated stores."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import threading

import pytest

from core.music_entity import rank, confident, alternatives, words
from core.music_intents import MusicAction
from core.media_manager import MediaRequest, consume, remember
from tests.test_yandex_music import controller
from tests.test_music_natural_c3_c4 import natural, chat
from tests.test_media_manager import ctx


def row(id, title, artist): return {'id': str(id), 'title': title, 'artists': artist}


@pytest.mark.parametrize('query, expected', [
    ('Noize MC Вояджер', '1'), ('Носим Сип Вояджер', '1'), ('Нойз эм си Вояджер', '1'),
    ('Linkin Park Numb', '2'), ('Линкин парк Numb', '2'), ('Билли айлиш бэд гай', '3'),
    ('Rammstein Du Hast', '4'), ('Рамштайн ду хаст', '4'), ('Имидж Дрэгонс Believer', '5'),
    ('Imagine Dragons Believer', '5'), ('Кино Группа крови', '6'), ('Кино — Группа крови', '6'),
])
def test_new_and_exact_entities_rank_catalogue_metadata(query, expected):
    rows=[row(1,'Вояджер','Noize MC'),row(2,'Numb','Linkin Park'),row(3,'Bad Guy','Billie Eilish'),
          row(4,'Du Hast','Rammstein'),row(5,'Believer','Imagine Dragons'),row(6,'Группа крови','Кино')]
    assert rank(query,rows)[0]['id']==expected
    assert rows[0]['artists']=='Noize MC'
    assert 'score' not in rows[0] and 'match' not in rows[0]


def test_phonetic_only_evidence_is_not_autoplay_permission():
    rows=[row(1,'Bad Guy','Billie Eilish'),row(2,'Bad Guy (Live)','Billie Eilish')]
    found=rank('билли айлиш бэд гай',rows)
    assert found[0]['id']=='1' and not confident(found)
    assert not found[0]['match']['autoplay_safe']


def test_exact_artist_not_replaced_with_phonetic_neighbour():
    rows=[row(2,'Black Star','Metallika'),row(1,'Black Star','Metallica')]
    found=rank('Metallica Black Star',rows)
    assert found[0]['id']=='1' and confident(found)
    assert found[1]['match']['artist_conflict']
    assert not confident(rank('Металика блэк стар',rows))


def test_same_title_different_artists_needs_choice():
    rows=[row(1,'Numb','Linkin Park'),row(2,'Numb','U2')]
    assert not confident(rank('Numb',rows))
    assert rank('U2 — Numb',rows)[0]['id']=='2'
    assert not confident(rank('Unlisted Artist — Numb',rows))


def test_versions_and_requested_version_are_distinct():
    rows=[row(1,'Numb','Linkin Park'),row(2,'Numb (Live)','Linkin Park'),row(3,'Numb (Remix)','Linkin Park'),row(4,'Numb (Cover)','Linkin Park')]
    assert rank('Linkin Park Numb',rows)[0]['id']=='1'
    assert rank('Linkin Park Numb Live',rows)[0]['id']=='2'
    assert rank('Linkin Park Numb Remix',rows)[0]['id']=='3'
    assert rank('Linkin Park Numb Cover',rows)[0]['id']=='4'


def test_music_numbers_and_cyrillic_letters_not_lost():
    assert words('Мой')!=words('Мои')
    assert words('Björk')==words('Bjork')
    found=rank('Artist — Track 2024',[row(1,'Track 2023','Artist')])
    assert not confident(found) and not found[0]['match']['plausible']
    assert rank('Artist Track 2024',[row(1,'Track 2023','Artist'),row(2,'Track 2024','Artist')])[0]['id']=='2'


def test_empty_malformed_and_unrelated_candidates_are_not_matches():
    assert rank('',[row(1,'Song','Artist')])==[]
    assert rank('Song',[])==[]
    assert rank('Song',[{'id':'evil','title':'Song','artists':'Artist'}])==[]
    assert not confident(rank('Different artist — Missing title',[row(1,'Numb','Linkin Park')]))


def test_alternatives_are_bounded_readable_and_metadata_grounded():
    q='Линкин парк виз ю'
    choices=alternatives(q,rank(q,[row(1,'With You','Linkin Park')]))
    assert 0<len(choices)<=2
    assert choices[0]=='Linkin Park With You'
    assert alternatives('QZX nowhere',[])==[]


def test_original_query_first_and_plausible_results_do_not_trigger_extra_search(controller):
    player,page=controller
    page.rows=[row(1,'Вояджер','Noize MC')]
    original='Носим Сип Вояджер'
    result=player.execute(MusicAction(action='search_play',query=original))
    assert result['query']==original and not result['confirmed']
    assert result['candidates'][0]['id']=='1'
    searches=[args['query'] for action,args in page.calls if action=='search']
    assert searches==[original]
    assert not any(action=='select_target' for action,args in page.calls)


def test_fallback_query_retained_for_exact_selection_and_raw_text_preserved(controller, monkeypatch):
    player,page=controller
    original='Линкин парк виз ю'
    active=['']
    old=page.action
    def action(kind,**args):
        if kind=='search': active[0]=args['query']
        if kind=='results': return {'ready':True,'rows':[row(7,'With You','Linkin Park')] if active[0]=='Linkin Park With You' else []}
        if kind=='select_target': assert args['query']==active[0]
        return old(kind,**args)
    monkeypatch.setattr(page,'action',action)
    result=player.execute(MusicAction(action='search',query=original))
    assert result['query']==original
    assert [args['query'] for kind,args in page.calls if kind=='search']==[original,'Linkin Park With You']
    candidate=result['candidates'][0]
    selected={key:candidate[key] for key in ('id','title','artists','search_id','retrieval_query')}
    assert selected['retrieval_query']=='Linkin Park With You'
    confirmed=player.execute(MusicAction(action='select',query=original,selection=selected))
    assert confirmed['confirmed'] and page.state['id']=='7'


def test_empty_search_stops_without_guessing_new_artist(controller):
    player,page=controller; page.rows=[]
    with pytest.raises(ValueError,match='подходящие треки не найдены'):
        player.execute(MusicAction(action='search_play',query='Unknown QZX artist'))
    assert sum(kind=='search' for kind,args in page.calls)==1
    assert not any(kind=='select_target' for kind,args in page.calls)


def test_failed_fallback_does_not_repeat_search_or_play(controller):
    player,page=controller; page.rows=[]
    with pytest.raises(ValueError): player.execute(MusicAction(action='search_play',query='Линкин парк виз ю'))
    queries=[args['query'] for kind,args in page.calls if kind=='search']
    assert len(queries)==len(set(queries))<=3
    assert not any(kind=='select_target' for kind,args in page.calls)


def test_cancellation_between_retrieval_attempts(controller,monkeypatch):
    player,page=controller; stop=threading.Event(); old=page.action
    def action(kind,**args):
        if kind=='results': stop.set(); return {'ready':True,'rows':[]}
        return old(kind,**args)
    monkeypatch.setattr(page,'action',action)
    with pytest.raises(ValueError): player.execute(MusicAction(action='search',query='Линкин парк виз ю'),stop)
    assert sum(kind=='search' for kind,args in page.calls)==1


def test_media_selection_preserves_query_and_freshness(controller):
    player,page=controller; store=player.store
    store.add_message('user','Найди песню Линкин парк виз ю')
    assistant=store.add_message('assistant','Выберите песню')
    request=MediaRequest('search','song','Яндекс Музыка',query='Линкин парк виз ю')
    candidate={**row(1,'With You','Linkin Park'),'search_id':'a'*32,'retrieval_query':'Linkin Park With You'}
    remember(store,assistant['id'],request=request,candidates=[candidate])
    store.add_message('user','включи первую')
    result=consume(store,'включи первую','Уайли')
    assert result['request'].query==request.query
    assert result['request'].selection['retrieval_query']==candidate['retrieval_query']
    assert consume(store,'включи первую','Уайли') is None


@pytest.mark.parametrize('text',['Не включай Linkin Park Numb','«Включи Linkin Park Numb»','Если включи Linkin Park Numb','Включи Linkin Park Numb и поставь на паузу'])
def test_non_commands_and_c5_do_not_reach_search(natural,text):
    client,app,rows,mixer,sent,writes,special,apps,calls=natural
    chat(client,text)
    assert not special and not sent and not writes and not calls['opened'] and not calls['audio']


def test_fixture_separation_and_sealed_metadata():
    root=Path(__file__).parent/'fixtures/music-entity'
    records=json.loads((root/'catalogue.json').read_text(encoding='utf-8'))['records']
    assert sum(r['language']=='ru' for r in records)>=100
    assert sum(r['language']=='foreign_mixed' for r in records)>=100
    groups={s:{r['group'] for r in records if r['split']==s} for s in ('tune','holdout')}
    assert not groups['tune'] & groups['holdout']
    artists={s:{a for r in records if r['split']==s for a in r['artist_mbids']} for s in ('tune','holdout')}
    assert not artists['tune'] & artists['holdout']
    recordings={s:{r['mbid'] for r in records if r['split']==s} for s in ('tune','holdout')}
    assert not recordings['tune'] & recordings['holdout']
    seal=json.loads((root/'sealed.json').read_text())
    for split,digest in seal.items():
        path=root/(split+'.json')
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
        assert json.loads(path.read_text(encoding='utf-8'))['meta']['catalogue_sha256']==hashlib.sha256((root/'catalogue.json').read_bytes()).hexdigest()


def test_chat_ranks_then_selects_through_existing_manager(natural,controller,monkeypatch):
    from core.yandex_music import YandexMusic
    client,app,rows,mixer,sent,writes,special,apps,calls=natural
    player,page=controller; page.rows=[row(8,'Вояджер','Noize MC')]
    pointers=[]; old_pointer=page.pointer
    monkeypatch.setattr(page,'pointer',lambda *args:pointers.append(args) or old_pointer(*args))
    monkeypatch.setattr(app.state.music,'renderer',player.renderer)
    monkeypatch.setattr(app.state.music,'execute',YandexMusic.execute.__get__(app.state.music))
    query='Включи Носим Сип Вояджер'
    events=chat(client,query)
    assert not any(kind=='select_target' for kind,args in page.calls)
    assert next(e['message']['content'] for e in events if e['type']=='user')==query
    assert app.state.store.dialogue()['pending_media']['candidates'][0]['retrieval_query']=='Носим Сип Вояджер'
    chat(client,'включи первую',request_id='c2-selected-once')
    assert page.state['id']=='8' and page.state['playing']
    assert len(pointers)==1
    assert client.post('/chat',json={'text':'включи первую','request_id':'c2-selected-once'}).status_code==409
    assert not sent and not writes and not calls['model']


def test_fallback_does_not_turn_phonetics_into_auto_permission(controller,monkeypatch):
    player,page=controller; old=page.action; active=['']
    def action(kind,**args):
        if kind=='search': active[0]=args['query']
        if kind=='results': return {'ready':True,'rows':[] if active[0]=='Носим Сип Вояджер' else [row(8,'Вояджер','Noize MC')]}
        return old(kind,**args)
    monkeypatch.setattr(page,'action',action)
    monkeypatch.setattr('core.yandex_music.entity_alternatives',lambda q,r:['Noize MC Вояджер'])
    result=player.execute(MusicAction(action='search_play',query='Носим Сип Вояджер'))
    assert not result['confirmed'] and result['candidates'][0]['retrieval_query']=='Noize MC Вояджер'
    assert not any(kind=='select_target' for kind,args in page.calls)


@pytest.mark.parametrize('reason',['expired','stopped','end_session'])
def test_fallback_query_cannot_bypass_stale_choice_guards(controller,reason):
    import time
    from core.media_manager import end_session
    player,page=controller; store=player.store
    store.add_message('user','Найди песню Линкин парк виз ю')
    assistant=store.add_message('assistant','Выберите песню')
    candidate={**row(1,'With You','Linkin Park'),'search_id':'a'*32,'retrieval_query':'Linkin Park With You'}
    remember(store,assistant['id'],request=MediaRequest('search','song','Яндекс Музыка',query='Линкин парк виз ю'),candidates=[candidate],request_id='old-query')
    if reason=='expired':
        state=store.dialogue();state['pending_media']['created']=time.time()-301;store.save_dialogue(state)
    if reason=='end_session': end_session(store)
    store.add_message('user','включи первую')
    result=consume(store,'включи первую','Уайли',{'old-query':1} if reason=='stopped' else {})
    assert not result or 'request' not in result
