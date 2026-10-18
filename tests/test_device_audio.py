from contextlib import contextmanager
import asyncio
from concurrent.futures import ThreadPoolExecutor
import ctypes
import json
import time
import threading

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from core import providers, windows_audio, audio_intents
from core.api import create_app
from core.backups import Backups
from core.config import Settings
from core.device_audio import AudioAction, AudioTools, resolve, run_action
from core.storage import Store


@pytest.mark.parametrize("text, action, value", [
    ("Прибавь громкости.", "change_volume", 10),
    ("Прибавь мне громкости на десять", "change_volume", 10),
    ("Убавь громкости на пять", "change_volume", -5),
    ("Убавь в громкость.", "change_volume", -10),
    ("Убавь, громкость на 10.", "change_volume", -10),
    ("Убавь в громкость на десять.", "change_volume", -10),
    ("Давай, убавь громкость", "change_volume", -10),
    ("Добавь мне громкости", "change_volume", 10),
    ("Прибавь громкость на 10", "change_volume", 10),
    ("Убавь громкость на десять процентов", "change_volume", -10),
    ("Можешь прибавить громкость на десять?", "change_volume", 10),
    ("Ты можешь убавить громкость на двадцать процентов?", "change_volume", -20),
    ("Прибавь звук на 5", "change_volume", 5),
    ("Сделай потише на 15", "change_volume", -15),
    ("Уайли, сделай громче", "change_volume", 10),
    ("Можешь сделать тише?", "change_volume", -10),
    ("Ты можешь установить громкость на пятьдесят процентов?", "set_volume", 50),
    ("Убавь звук", "change_volume", -10),
    ("Сделай потише, пожалуйста!", "change_volume", -10),
    ("Установи громкость 35%", "set_volume", 35),
    ("Пожалуйста, громкость на тридцать пять процентов", "set_volume", 35),
    ("Поставь громкость сто", "set_volume", 100),
    ("Громкость ноль", "set_volume", 0),
    ("Уменьши громкость на пять процентов", "change_volume", -5),
    ("Сделай громче на двадцать один процент", "change_volume", 21),
    ("Тише на 12", "change_volume", -12),
    ("Какая громкость?", "status", None),
    ("Выключи звук", "mute", None),
    ("Включи звук", "unmute", None),
    ("Следующий трек", "next", None),
    ("Предыдущий трек", "previous", None),
    ("Переключи воспроизведение", "play_pause", None),
    ("Останови музыку", "stop", None),
])
def test_russian_audio_intents(text, action, value):
    assert resolve(text) == AudioAction(action=action, value=value)


@pytest.mark.parametrize("text", [
    "Привет", "Не выключай звук", "если скажу выключи звук", '"Выключи звук"',
    "Он сказал: выключи звук", "Объясни, как выключить звук", "Выключи звук?",
    "Выключи звук и открой блокнот", "Выключи звук\n", "Запомни: выключи звук",
    "Поставь паузу в разговоре", "Продолжай", '{"action":"mute"}',
])
def test_only_whole_unquoted_user_utterances_are_commands(text):
    assert resolve(text) is None


@pytest.mark.parametrize("text, delta", [
    ("Припав кромкость", 10), ("Припав громкость на 10", 10),
    ("Уайли, припай громкость на пятнадцать", 15), ("Убавь кромкость", -10),
    ("Упавь, громкость на 10.", -10), ("Упавь в громкость на 10.", -10),
])
def test_garbled_volume_is_only_a_confirmation_suggestion(text, delta):
    assert resolve(text) is None
    suggestion = audio_intents.suggest(text)
    assert suggestion.action == AudioAction(action="change_volume", value=delta)
    assert "пока не изменена" in suggestion.text


@pytest.mark.parametrize("text", [
    "Не припав кромкость", "если скажу припав кромкость", '«припав кромкость»',
    "Как прибавь громкость", "почему припай громкость", "Привет", "припав кромкость\n",
    "Он сказал припав кромкость", "припав кромкость?",
])
def test_audio_suggestions_do_not_reinterpret_mentions_or_negation(text):
    assert audio_intents.suggest(text) is None


@pytest.mark.parametrize("text", ["Припай фиг громкость", "Припав кромкость на 999", "Припав кромкость и открой блокнот"])
def test_unclear_volume_does_not_prepare_an_action(text):
    suggestion = audio_intents.suggest(text)
    assert suggestion.action is None
    assert "не изменена" in suggestion.text


@pytest.mark.parametrize("body", [
    {"action": "set_volume", "value": -1}, {"action": "set_volume", "value": 101},
    {"action": "set_volume", "value": True}, {"action": "set_volume", "value": "30"},
    {"action": "set_volume"}, {"action": "change_volume", "value": -101},
    {"action": "mute", "value": 1}, {"action": "shell"},
    {"action": "next", "target": "notepad.exe"},
])
def test_typed_arguments(body):
    with pytest.raises(ValidationError):
        AudioAction.model_validate(body)


@pytest.mark.parametrize("text", ["громкость 101", "громкость минус пять", "громкость пятьдесят пятьдесят", "громкость пять и открой блокнот"])
def test_invalid_levels_are_rejected(text):
    with pytest.raises(ValueError):
        resolve(text)


@pytest.fixture
def audio(tmp_path, monkeypatch):
    monkeypatch.setattr("core.windows_media.perform", lambda action="read": {"available": False})
    class FakeEndpoint:
        volume = 40
        muted = False
        calls = []

        def read(self):
            time.sleep(0.001)
            return {"volume": self.volume, "muted": self.muted}

        def set_volume(self, value):
            self.calls.append(("volume", value))
            self.volume = value

        def set_mute(self, value):
            self.calls.append(("mute", value))
            self.muted = value

    device = FakeEndpoint()
    @contextmanager
    def endpoint():
        yield device
    monkeypatch.setattr(windows_audio, "endpoint", endpoint)
    monkeypatch.setattr(windows_audio, "send_media", lambda action: device.calls.append(("media", action)))
    async def forbidden_model(*args, **kwargs):
        raise AssertionError("Audio commands must not call the model")
        yield ""
    monkeypatch.setattr(providers, "chat", forbidden_model)
    app = create_app(tmp_path, "audio-tests-0123456789abcdef")
    with TestClient(app, headers={"Authorization": "Bearer audio-tests-0123456789abcdef"}) as client:
        yield client, app.state.store, device


def test_api_and_chat_use_same_adapter_without_model(audio):
    api, store, device = audio
    assert api.get("/device/audio").json() == {"available": True, "enabled": True, "volume": 40, "muted": False}
    assert api.post("/device/audio", json={"action": "set_volume", "value": 65}).json()["volume"] == 65
    response = api.post("/chat", json={"text": "Уайли, сделай тише", "mode": "conversation"})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "done" and "55%" in events[-1]["message"]["content"]
    assert api.post("/device/audio", json={"action": "mute"}).json()["muted"] is True
    assert api.post("/commands", json={"text": "включи звук", "dry_run": False}).json()["muted"] is False
    assert device.calls == [("volume", 65), ("volume", 55), ("mute", True), ("mute", False)]
    assert all(item["kind"] == "device.audio" for item in store.list("actions"))


def audio_chat(api, text, **fields):
    response = api.post("/chat", json={"text": text, **fields})
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "done", events
    return events[-1]["message"]["content"]


def test_garbled_volume_requires_confirmation_and_can_be_cancelled(audio):
    api, store, device = audio
    assert "Выполнить?" in audio_chat(api, "Припав кромкость на 10", mode="conversation")
    assert device.calls == [] and store.list("actions") == []
    assert "50%" in audio_chat(api, "да")
    assert device.calls == [("volume", 50)]
    audio_chat(api, "Убавь кромкость")
    assert "отменено" in audio_chat(api, "отмена")
    assert device.calls == [("volume", 50)]
    assert "60%" in audio_chat(api, "Прибавь громкость на 10")
    assert "не изменена" in audio_chat(api, "Припай фиг громкость")
    assert device.calls == [("volume", 50), ("volume", 60)]


def test_screenshot_volume_typos_offer_one_specific_correction(audio):
    api, store, device = audio
    for phrase in ("Упавь, громкость на 10.", "Упавь в громкость на 10."):
        answer = audio_chat(api, phrase, mode="conversation")
        assert "«убавь громкость на 10»" in answer and "Выполнить?" in answer
        before = list(device.calls)
        assert "Windows" in audio_chat(api, "да, выполни")
        assert device.calls == before + [("volume", 40 - 10 * (len(before) + 1))]
    assert device.volume == 20


@pytest.mark.parametrize("phrase,action", [("Протоже музыку.", "play"), ("И Края Музыку.", "play"), ("Приостонови музыку", "pause")])
def test_unclear_music_is_proposed_and_requires_confirmation(audio, monkeypatch, phrase, action):
    api, store, device = audio
    calls = []
    monkeypatch.setattr("core.windows_media.perform", lambda command="read": calls.append(command) or {"available": False})
    answer = audio_chat(api, phrase, mode="conversation")
    assert "Выполнить?" in answer and "Команда ещё не выполнялась" in answer
    assert not calls
    audio_chat(api, "да")
    assert calls == [action] and not device.calls


@pytest.mark.parametrize("phrase", [
    "Не протоже музыку", "Яндекс Музыка, не продолжи музыку", "Он сказал протоже музыку",
    "Протоже музыку и открой блокнот", "Создай музыку", "Сочини музыку", "Про музыку",
    "Протоже песню Linkin Park", 'Яндекс Музыка, «протоже музыку»', "Если протоже музыку", "Протоже музыку?",
])
def test_music_correction_does_not_guess_other_requests(phrase):
    assert audio_intents.suggest(phrase, player="yandex") is None


def test_confirmation_rechecks_permission_and_expires(audio, monkeypatch):
    api, store, device = audio
    audio_chat(api, "Припав громкость")
    store.save_settings(Settings(allow_audio_control=False))
    response = api.post("/chat", json={"text": "да"})
    assert "Управление звуком отключено" in response.text and device.calls == []
    store.save_settings(Settings())
    audio_chat(api, "Припав громкость")
    original = audio_intents.time.time
    monkeypatch.setattr(audio_intents.time, "time", lambda: original() + 121)
    assert "устарело" in audio_chat(api, "да")
    assert device.calls == []


def test_restored_question_cannot_execute_without_its_pending_state(audio):
    api, store, device = audio
    audio_chat(api, "Припав громкость")
    store.save_dialogue({})  # Restoring a backup intentionally drops pending commands.
    assert "устарело" in audio_chat(api, "да")
    assert device.calls == []


def test_audio_confirmation_does_not_own_another_question_or_chat(audio):
    api, store, device = audio
    audio_chat(api, "Припав громкость")
    # A new task question takes ownership of the next short reply.
    assert "Когда" in audio_chat(api, "Напомни купить хлеб")
    assert "pending_audio" not in store.dialogue()
    assert "Выполнить?" in audio_chat(api, "Припав громкость")
    # A manually replaced last assistant message also invalidates a stale proposal.
    store.add_message("assistant", "Другая тема")
    assert "устарело" in audio_chat(api, "да")
    assert device.calls == []


def test_audio_confirmation_is_scoped_to_chat_and_survives_store_reopen(audio):
    from core.chatspaces import Spaces
    api, store, device = audio
    audio_chat(api, "Припав громкость")
    other = Spaces(store).create_chat()
    another_store = store.for_chat(other["id"])
    another_store.add_message("user", "да")
    assert audio_intents.consume(another_store, "да") is None
    # Reading the persisted proposal through a fresh Store must still validate
    # the original chat's last question; no in-memory global owns the choice.
    reopened = Store(store.root).for_chat(store.conversation_id)
    reopened.add_message("user", "да")
    result = audio_intents.consume(reopened, "да")
    assert result.action == AudioAction(action="change_volume", value=10)
    assert device.calls == []  # Consume only returns a typed action to the executor.


def test_preview_does_not_touch_hardware(audio):
    api, store, device = audio
    result = api.post("/commands", json={"text": "громкость 95 процентов"})
    assert result.status_code == 200 and "не выполнялось" in result.json()["text"]
    assert device.volume == 40 and not device.calls
    assert store.list("actions")[0]["status"] == "preview"


@pytest.mark.parametrize("text", ["Включи мне музыку.", "Включи музыку", "Можешь включить мне музыку?", "Уайли, поставь какую-нибудь музыку"])
def test_starting_unspecified_music_never_fabricates_playback(audio, text):
    api, store, device = audio
    answer = audio_chat(api, text)
    assert "нужен источник" in answer and "не отправлялась" in answer
    assert device.calls == [] and store.list("actions") == []


def test_media_acknowledges_delivery_without_claiming_playback(audio):
    api, store, device = audio
    result = api.post("/device/audio", json={"action": "next"})
    assert "медиаклавишу" in result.json()["text"] and "проигрывателя" in result.json()["text"]
    assert device.calls == [("media", "next")]
    assert store.list("actions")[0]["target"] == "next"


def test_permission_checked_every_time_and_restored_durably(audio):
    api, store, device = audio
    access = api.get("/tools").json()["access"]
    access["allow_audio_control"] = False
    assert api.put("/tools/access", json=access).status_code == 200
    assert api.get("/device/audio").json()["enabled"] is False
    for route, body in [("/device/audio", {"action": "mute"}), ("/commands", {"text": "выключи звук", "dry_run": False})]:
        result = api.post(route, json=body)
        assert result.status_code == 400 and "отключено" in result.json()["detail"]
    response = api.post("/chat", json={"text": "следующий трек"})
    assert "отключено" in response.text and not device.calls
    assert Store(store.root).settings().allow_audio_control is False
    assert not next(item for item in api.get("/tools").json()["tools"] if item["id"] == "windows.audio.mute")["enabled"]


def test_limits_and_muting_are_independent(audio):
    api, _, device = audio
    for delta, expected in [(100, 100), (-100, 0), (-5, 0)]:
        assert api.post("/device/audio", json={"action": "change_volume", "value": delta}).json()["volume"] == expected
    api.post("/device/audio", json={"action": "mute"})
    assert api.post("/device/audio", json={"action": "set_volume", "value": 25}).json()["muted"] is True
    assert device.volume == 25


def test_concurrent_relative_changes_do_not_lose_updates(audio):
    _, store, device = audio
    tools = AudioTools(store)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: tools.execute(AudioAction(action="change_volume", value=1)), range(12)))
    assert device.volume == 52


def test_missing_device_has_readable_error_and_failed_audit(audio, monkeypatch):
    api, store, device = audio
    @contextmanager
    def unavailable():
        raise ValueError("Устройство воспроизведения не найдено")
        yield
    monkeypatch.setattr(windows_audio, "endpoint", unavailable)
    result = api.get("/device/audio").json()
    assert result["available"] is False and "не найдено" in result["error"]
    assert api.post("/device/audio", json={"action": "set_volume", "value": 50}).status_code == 400
    assert store.list("actions")[0]["status"] == "error" and not device.calls


def test_old_settings_and_backups_cannot_enable_disabled_audio(audio, tmp_path):
    _, target, _ = audio
    source = Store(tmp_path / "source")
    bundle = json.loads(Backups(source).export())
    bundle["settings"].pop("allow_audio_control")
    target.save_settings(Settings(allow_audio_control=False))
    manager = Backups(target)
    manager.restore(manager.preview(json.dumps(bundle).encode())["ticket"], connections=True)
    assert not target.settings().allow_audio_control


def test_abi_matches_windows_sdk():
    assert ctypes.sizeof(windows_audio.GUID) == 16
    assert ctypes.sizeof(windows_audio.Input) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


def test_native_endpoint_slots_and_hresult(monkeypatch):
    calls = []
    def invoke(pointer, slot, types, *args):
        calls.append((slot, args))
        if slot == 9:
            args[0]._obj.value = .35
        elif slot == 15:
            args[0]._obj.value = 1
    monkeypatch.setattr(windows_audio, "invoke", invoke)
    device = windows_audio.Endpoint(None)
    assert device.read() == {"volume": 35, "muted": True}
    device.set_volume(25)
    device.set_mute(False)
    assert [slot for slot, _ in calls] == [9, 15, 7, 14]
    assert calls[2][1] == (.25, None) and calls[3][1] == (0, None)
    with pytest.raises(ValueError, match="80070490"):
        windows_audio.check(-2147023728)


class NativeFunction:
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


@pytest.mark.parametrize("initialized,fail_slot,expected_releases,uninitialize", [
    (0, None, [3, 2, 1], True),
    (1, 4, [1], True),
    (-2147417850, None, [3, 2, 1], False),
    (0, 3, [2, 1], True),
])
def test_native_com_lifetime_on_own_or_existing_apartment(monkeypatch, initialized, fail_slot, expected_releases, uninitialize):
    released, closed = [], []
    class Ole:
        CoInitializeEx = NativeFunction(lambda *args: initialized)
        CoUninitialize = NativeFunction(lambda: closed.append(True))
        CoCreateInstance = NativeFunction(lambda *args: setattr(args[-1]._obj, "value", 1) or 0)
    def invoke(pointer, slot, types, *args):
        if slot == fail_slot:
            raise ValueError("Device unavailable")
        args[-1]._obj.value = 2 if slot == 4 else 3
    monkeypatch.setattr(windows_audio.c, "WinDLL", lambda *args, **kwargs: Ole(), raising=False)
    monkeypatch.setattr(windows_audio.os, "name", "nt")
    monkeypatch.setattr(windows_audio, "invoke", invoke)
    monkeypatch.setattr(windows_audio, "release", lambda pointer: released.append(pointer.value))
    if fail_slot:
        with pytest.raises(ValueError):
            with windows_audio.endpoint():
                pytest.fail("Incomplete COM initialization must not yield")
    else:
        with windows_audio.endpoint() as device:
            assert device.pointer.value == 3
    assert released == expected_releases and bool(closed) == uninitialize


@pytest.mark.parametrize("inserted", [0, 1, 2])
def test_native_media_input_pairs_and_partial_failure(monkeypatch, inserted):
    sent = []
    def send(count, inputs, size):
        assert size == ctypes.sizeof(windows_audio.Input)
        if count == 2:
            sent.extend((inputs[i].data.keyboard.vk, inputs[i].data.keyboard.flags) for i in range(count))
        else:
            sent.append((inputs._obj.data.keyboard.vk, inputs._obj.data.keyboard.flags))
        return inserted
    class User:
        SendInput = NativeFunction(send)
    monkeypatch.setattr(windows_audio.c, "WinDLL", lambda *args, **kwargs: User(), raising=False)
    monkeypatch.setattr(windows_audio.os, "name", "nt")
    if inserted == 2:
        windows_audio.send_media("next")
    else:
        with pytest.raises(ValueError, match="не приняла"):
            windows_audio.send_media("next")
    assert sent[:2] == [(0xB0, 0), (0xB0, 2)]
    assert len(sent) == (3 if inserted == 1 else 2)


def test_cancellation_waits_for_dispatched_action_and_records_its_result():
    started, finish = threading.Event(), threading.Event()
    class Tools:
        def execute(self, command):
            started.set()
            assert finish.wait(5)
            return {"text": "Громкость Windows: 35%."}
    async def scenario():
        progress = []
        task = asyncio.create_task(run_action(Tools(), AudioAction(action="set_volume", value=35), progress))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(.01)
            assert started.is_set()
            task.cancel()
            await asyncio.sleep(.02)
            assert not task.done()
        finally:
            finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert progress == ["Громкость Windows: 35%."]
    asyncio.run(scenario())
