"""C3/C4 through /chat with fake audio, apps, sessions and CDP executors."""
import json
import time

import pytest

from core.device_audio import request_form
from core.launch_verification import ExecutionText
from core.media_manager import parse
from core.music_intents import resolve, compound_request
from tests.test_media_manager import ctx


@pytest.fixture
def natural(ctx, monkeypatch):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    app.state.store.patch_settings({'music_player': 'yandex', 'voice_diagnostics': True})
    monkeypatch.setattr(app.state.music, 'status', lambda: {'connected': True})
    monkeypatch.setattr(app.state.applications, 'saved', lambda: {'items': apps})
    rows[0]['commands'].append('previous')
    calls = {'opened': [], 'audio': [], 'model': []}
    monkeypatch.setattr('core.commands.execute', lambda command, **kw: calls['opened'].append(command) or ExecutionText('Fixture launch', {'status': 'process_started'}))
    def audio(self, command, **kw):
        calls['audio'].append(command)
        return {'text': 'Fixture volume verified', 'state': {'volume': 40}}
    monkeypatch.setattr('core.device_audio.AudioTools.execute', audio)
    def forbidden(*args, **kwargs): pytest.fail('Real endpoint must not be used')
    monkeypatch.setattr('core.windows_audio.endpoint', forbidden)
    async def conversation(*args, **kwargs):
        calls['model'].append(1)
        yield 'Ответ без действий'
    monkeypatch.setattr('core.providers.chat', conversation)
    return client, app, rows, mixer, sent, writes, special, apps, calls


def chat(client, text, **kwargs):
    response = client.post('/chat', json={'text': text, 'mode': 'conversation', **kwargs})
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert any(e['type'] == 'done' for e in events)
    return events


@pytest.mark.parametrize('text,query,action', [
    ('Включи Linkin Park Numb', 'Linkin Park Numb', 'search_play'),
    ('Поставь Rammstein', 'Rammstein', 'search_play'),
    ('Запусти Noize MC Вояджер', 'Noize MC Вояджер', 'search_play'),
    ('Воспроизведи Linkin Park In the End', 'Linkin Park In the End', 'search_play'),
    ('Поставь джаз', 'джаз', 'search_play'),
    ('Включи лёгкую музыку', 'лёгкую музыку', 'search_play'),
    ('Включи Xylophonic Fox Unreleased Song', 'Xylophonic Fox Unreleased Song', 'search_play'),
    ('Включи в Яндекс Музыке НеведомыйАртист', 'НеведомыйАртист', 'search_play'),
    ('Поставь ac/dc', 'ac/dc', 'search_play'),
    ('Поставь Ёлка', 'Ёлка', 'search_play'),
    ('Включи в Яндекс Музыке песню Numb', 'Numb', 'search_play'),
    ('Найди в Яндекс Музыке Numb', 'Numb', 'search'),
    ('Поставь на Yandex Music Rammstein', 'Rammstein', 'search_play'),
    ('Включи в Яндекс Музыке Linkin Park Numb', 'Linkin Park Numb', 'search_play'),
    ('Включи Город в огне', 'Город в огне', 'search_play'),
    ('Поставь песню «В Яндекс Музыке»', 'В Яндекс Музыке', 'search_play'),
    ('Включим Linkin Park Numb', 'Linkin Park Numb', 'search_play'),
])
def test_free_queries_keep_arguments_and_history_without_llm(natural, text, query, action):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    events = chat(client, text)
    assert [(c.action, c.query) for c in special] == [(action, query)]
    assert next(e['message']['content'] for e in events if e['type'] == 'user') == text
    assert not sent and not writes and not any(calls.values())


@pytest.mark.parametrize('text', ['Подкрути звук', 'Давай сделаем погромче', 'Сделаем потише', 'Давай убавим звук', 'Тише сделай', 'Погромче звук'])
def test_general_volume_remains_windows(natural, text):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    chat(client, text)
    assert len(calls['audio']) == 1 and calls['audio'][0].action == 'change_volume'
    assert not sent and not writes and not special and not calls['model']


@pytest.mark.parametrize('text', ['Музыку погромче', 'Погромче музыку', 'Музыку погромче, пожалуйста', 'Включи музыку погромче', 'Прибавь музыку', 'Прибавь музыкашку'])
def test_musical_volume_is_selected_player_not_windows(natural, text):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    app.state.store.patch_settings({'media_source': 'smtc:AIMP'})
    chat(client, text)
    assert writes == [('mix', apps[0]['target'], 10)]
    assert not special and not sent and not any(calls.values())


@pytest.mark.parametrize('text,action', [('Следующую', 'next'), ('Дальше', 'next'), ('Крутани дальше', 'next'), ('Верни предыдущую песню', 'previous'), ('Включим следующую', 'next'), ('Переключим на следующую', 'next')])
def test_directional_commands_use_selected_player_once(natural, text, action):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    app.state.store.patch_settings({'media_source': 'smtc:AIMP'})
    chat(client, text)
    assert sent == [('smtc:AIMP', action)] and not special and not writes and not any(calls.values())


@pytest.mark.parametrize('text', ['Следующую', 'Дальше', 'Крутани дальше'])
def test_short_direction_without_context_does_not_guess(natural, text):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    app.state.store.patch_settings({'music_player': 'auto', 'media_source': 'auto'})
    # A random open session is not an established musical conversation.
    events = chat(client, text)
    assert any(e.get('action', {}).get('status') == 'needs_clarification' for e in events)
    assert not sent and not writes and not special and not any(calls.values())


@pytest.mark.parametrize('text', ['Уйми музыку', 'Давай тишину', 'Музыку совсем убери'])
def test_pause_or_mute_ambiguity_is_local_and_retires_old_proposal(natural, text):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    app.state.store.save_dialogue({'pending_media': {'created': time.time()}, 'media_choice': {'id': 'smtc:AIMP', 'created': time.time()}})
    events = chat(client, text)
    assert any('паузу или выключить звук' in e.get('text', '') for e in events)
    assert 'pending_media' not in app.state.store.dialogue()
    assert app.state.store.dialogue()['media_choice']['id'] == 'smtc:AIMP'
    assert not sent and not writes and not special and not any(calls.values())


@pytest.mark.parametrize('text', ['Не включай Linkin Park', 'Если включи Linkin Park', 'Как включить песню?', 'Он сказал включи музыку', '«Включи Linkin Park»', 'Включи Linkin Park?', 'Включи в Яндекс Музыке Numb?', 'Не подкрути звук', 'Сделаем потише?', 'Почему дальше?'])
def test_non_action_language_does_not_execute(natural, text):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    chat(client, text)
    assert not sent and not writes and not special and not calls['audio'] and not calls['opened']


@pytest.mark.parametrize('text', ['Включи Numb и поставь на паузу', 'Подкрути звук и открой Blender', 'Музыку погромче и запусти Blender', 'Дальше и открой Blender', 'Включи Numb и крутани дальше', 'Включи Numb и дальше', 'Поставь Rammstein, теперь погромче', 'Поставь Rammstein, а теперь давай откроем Blender', 'Сделаем потише и продолжим музыку', 'Найди песню Numb и включи'])
def test_c5_guards_new_grammars_before_every_executor(natural, text):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    assert compound_request(text)
    events = chat(client, text)
    assert any(e.get('action', {}).get('status') == 'needs_clarification' for e in events)
    assert not sent and not writes and not special and not any(calls.values())


@pytest.mark.parametrize('text', ['Включи Bluetooth', 'Включи свет', 'Включи звук', 'Включи Blender', 'Включи Яндекс Музыку', 'Включи её', 'Включи что-нибудь'])
def test_non_musical_targets_never_become_search(natural, text):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    chat(client, text)
    assert not any(c.action in {'search', 'search_play', 'select'} for c in special)


def test_user_alias_and_unknown_catalog_app_veto_free_search(natural):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    apps.append({'name': 'Xylophonic Fox', 'target': apps[0]['target'], 'id': 'custom'})
    app.state.store.add_alias('Moon Client', 'app', apps[0]['target'])
    chat(client, 'Включи Xylophonic Fox')
    chat(client, 'Включи Moon Client')
    assert not special


@pytest.mark.parametrize('context', ['explicit', 'fresh', 'expired', 'missing'])
def test_free_queries_do_not_replace_selected_source_with_yandex(natural, context):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    store = app.state.store
    if context in {'explicit', 'missing'}: store.patch_settings({'media_source': 'smtc:AIMP'})
    if context == 'missing': rows.clear()
    if context in {'fresh', 'expired'}:
        store.save_dialogue({'media_choice': {'id': 'smtc:AIMP', 'created': time.time() - (301 if context == 'expired' else 0)}})
    chat(client, 'Поставь Rammstein')
    assert len(special) == (1 if context == 'expired' else 0)
    assert not sent and not writes and not any(calls.values())


def test_no_context_does_not_infer_unknown_artist(natural):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    app.state.store.patch_settings({'music_player': 'auto', 'media_source': 'auto'})
    chat(client, 'Включи Xylophonic Fox')
    assert not special and not sent and not writes and not calls['audio'] and not calls['opened']
    assert request_form('Включим Xylophonic Fox') == 'Включим Xylophonic Fox'


def test_explicit_source_works_without_preference(natural):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    app.state.store.patch_settings({'music_player': 'auto', 'media_source': 'auto'})
    chat(client, 'Найди в Яндекс Музыке Numb')
    assert len(special) == 1 and special[0].action == 'search' and special[0].query == 'Numb'


def test_atomic_search_and_play_is_not_split(natural):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    chat(client, 'Найди и включи песню Numb')
    assert len(special) == 1 and special[0].action == 'search_play' and special[0].query == 'Numb'


def test_ambiguous_candidates_use_existing_selection_and_cancellation(natural, monkeypatch):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    def execute(command, cancel=None):
        special.append(command)
        if command.action in {'search', 'search_play'}:
            return {'confirmed': False, 'text': 'Выберите песню', 'candidates': [{'id': str(n), 'title': f'Numb {n}', 'artists': 'Linkin Park', 'search_id': 'a' * 32} for n in (1, 2)]}
        return {'confirmed': True, 'text': 'Выбранный трек подтверждён'}
    monkeypatch.setattr(app.state.music, 'execute', execute)
    chat(client, 'Включи Linkin Park Numb')
    assert [c.action for c in special] == ['search_play']
    chat(client, 'включи вторую')
    assert special[-1].action == 'select' and special[-1].selection.id == '2'
    chat(client, 'Включи Linkin Park Numb')
    chat(client, 'отмена')
    assert [c.action for c in special] == ['search_play', 'select', 'search_play']
    assert not sent and not writes and not any(calls.values())


def test_dedup_and_permissions_are_preserved(natural):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    chat(client, 'Включи Linkin Park Numb', request_id='natural-once')
    repeated = client.post('/chat', json={'text': 'Включи Linkin Park Numb', 'request_id': 'natural-once'})
    assert repeated.status_code == 409 and len(special) == 1
    app.state.store.patch_settings({'allow_audio_control': False})
    chat(client, 'Поставь Rammstein')
    assert len(special) == 1


def test_command_preview_uses_same_bounded_grammars(natural):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    response = client.post('/commands', json={'text': 'Включи Linkin Park Numb', 'dry_run': True})
    assert response.status_code == 200 and response.json()['target']['query'] == 'Linkin Park Numb'
    response = client.post('/commands', json={'text': 'Давай тишину'})
    assert response.status_code == 200 and response.json()['status'] == 'needs_clarification'
    assert not sent and not writes and not special and not any(calls.values())


@pytest.mark.parametrize('text', ['Что там играет-то?', 'Какая песня?'])
def test_contextual_status_questions_are_read_only(natural, text):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    chat(client, text)
    assert [c.action for c in special] == ['status']
    assert not sent and not writes and not any(calls.values())


def test_vague_volume_level_requires_clarification(natural):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    events = chat(client, 'Сделай нормальную громкость')
    assert any(e.get('action', {}).get('status') == 'needs_clarification' for e in events)
    assert not sent and not writes and not special and not any(calls.values())


@pytest.mark.parametrize('text', ['Запусти зуму', 'Запусти офис', 'Включи йцукен', 'Включи ту самую песню', 'Поставь побыстрее музыку', 'Включи Рамштайн'])
def test_unknown_single_names_pronouns_and_modifiers_are_not_guessed(natural, text):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    chat(client, text)
    assert not sent and not writes and not special and not calls['audio'] and not calls['opened']


@pytest.mark.parametrize('text', ['Убавь, громкость музыки на 10.', 'Убавим, громкость музыки на 10.'])
def test_asr_volume_comma_does_not_become_a_secondary_action(natural, text):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    assert not compound_request(text)
    chat(client, text)
    assert writes == [('mix', apps[0]['target'], -10)]
    assert not sent and not special and not any(calls.values())


def test_named_player_overrides_preference_for_colloquial_direction(natural):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    chat(client, 'Крутани дальше в AIMP')
    assert sent == [('smtc:AIMP', 'next')] and not special and not any(calls.values())


def test_status_respects_selected_session_instead_of_preferred_yandex(natural):
    client, app, rows, mixer, sent, writes, special, apps, calls = natural
    app.state.store.patch_settings({'media_source': 'smtc:AIMP'})
    events = chat(client, 'Какая песня?')
    assert any(e.get('action', {}).get('status') == 'read' for e in events)
    assert not sent and not writes and not special and not any(calls.values())
