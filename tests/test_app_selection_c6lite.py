"""C6-lite: purpose-based selection of installed apps. Fixtures only, read-only, never a launch."""
import sys

import pytest
from fastapi.testclient import TestClient

from core import app_discovery as discovery, commands
from core.api import create_app
from core.launch_verification import ExecutionText

PURPOSE_APPS = [
    ("Paint", "mspaint.exe"), ("IrfanView", "i_view64.exe"), ("GIMP", "gimp-2.10.exe"),
    ("Blender", "blender.exe"), ("OBS Studio", "obs64.exe"), ("SumatraPDF", "SumatraPDF.exe"),
    ("7-Zip", "7zFM.exe"), ("AIMP", "AIMP.exe"), ("VLC", "vlc.exe"), ("Notepad++", "notepad++.exe"),
]


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    paths, rows = {}, []
    for name, filename in PURPOSE_APPS:
        path = tmp_path / filename; path.touch(); paths[filename] = str(path)
        rows.append({"id": filename, "name": name, "category": "other", "target": str(path), "source": "фикстура", "aliases": []})
    monkeypatch.setattr(discovery, "discover", lambda: {"supported": True, "items": list(rows), "warnings": []})
    monkeypatch.setattr(discovery, "package_registered", lambda target: True)
    calls = []
    def execute(command, dry_run=False, **kwargs):
        if not dry_run: calls.append(command)
        return ExecutionText("Запуск проверен фикстурой", {"status": "process_started"})
    monkeypatch.setattr(commands, "execute", execute)
    async def forbidden(*args, **kwargs):
        import traceback
        pytest.fail("Purpose selection must not call an LLM\n" + "".join(traceback.format_stack()[-8:]))
        yield ""
    monkeypatch.setattr("core.providers.chat", forbidden)
    monkeypatch.setattr("core.providers.structured", forbidden)
    app = create_app(tmp_path, "app-selection-c6lite-token-012345")
    app.state.applications.scan()
    with TestClient(app, headers={"Authorization": "Bearer app-selection-c6lite-token-012345"}) as client:
        yield client, app, paths, rows, calls


def ask(client, text):
    result = client.post("/chat", json={"text": text})
    assert result.status_code == 200, result.text
    return result.text


@pytest.mark.parametrize("phrase,expected", [
    ("Найди программу для рисования", ("Paint", "GIMP")),
    ("Чем мне открыть PDF?", ("SumatraPDF",)),
    ("Чем можно открыть 3D-модель?", ("Blender",)),
    ("У меня есть что-нибудь для обработки фотографий?", ("GIMP",)),
    ("Покажи установленные видеоредакторы", None),  # fixture has no video editor: honest miss
    ("Какая программа подойдёт для записи экрана?", ("OBS Studio",)),
    ("Найди программу для просмотра изображений", ("Paint", "IrfanView")),
    ("Какой браузер установлен?", None),  # fixture has no browser: honest miss
    ("Чем послушать flac?", ("AIMP",)),
    ("Покажи установленные программы для готовки", None),
    ("Найди что-нибудь для нейросетей", None),
])
def test_purpose_phrases_return_installed_apps_without_launching(catalog, phrase, expected):
    client, app, paths, rows, calls = catalog
    answer = ask(client, phrase)
    if expected is None:
        assert "Найдено:" not in answer
        assert "Уточните" in answer or "не найдено" in answer
    else:
        assert "Найдено:" in answer
        for name in expected:
            assert name in answer, (phrase, answer)
    assert calls == [], "Purpose selection must never launch anything"


def test_multiple_candidates_are_listed_together(catalog):
    client, app, paths, rows, calls = catalog
    answer = ask(client, "Покажи установленные программы для рисования")
    assert "Paint" in answer and "GIMP" in answer
    assert "Запуск не выполнялся" in answer
    assert calls == []


def test_unknown_app_name_reports_checked_sources_only(catalog):
    client, app, paths, rows, calls = catalog
    answer = ask(client, "Проверь установлен ли Krita")
    assert "в проверенных источниках не найдено" in answer
    assert "Запуск не выполнялся" in answer
    assert calls == []


@pytest.mark.parametrize("phrase", ["Не открывай Blender", "Расскажи о Blender", "Найди песню Blender"])
def test_negations_info_and_music_never_reach_purpose_selection(catalog, phrase, monkeypatch):
    client, app, paths, rows, calls = catalog
    async def stub_chat(*args, **kwargs):
        yield ""
    monkeypatch.setattr("core.providers.chat", stub_chat)
    monkeypatch.setattr("core.providers.structured", stub_chat)
    answer = ask(client, phrase)
    assert "Найдено:" not in answer and "Запуск не выполнялся" not in answer
    assert calls == []


def test_opening_intent_stays_on_the_launch_route(catalog):
    client, app, paths, rows, calls = catalog
    answer = ask(client, "Открой программу для таблиц")
    # No office app in the fixture and no semantic router: an honest miss, never a launch.
    assert not calls
    assert "Запуск проверен" not in answer


def test_empty_catalog_reports_without_claiming_absence(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "discover", lambda: {"supported": True, "items": [], "warnings": []})
    monkeypatch.setattr(discovery, "package_registered", lambda target: True)
    monkeypatch.setattr(commands, "execute", lambda command, dry_run=False, **kwargs: ExecutionText("не используется", {}))
    app = create_app(tmp_path, "app-selection-empty-token-012345")
    with TestClient(app, headers={"Authorization": "Bearer app-selection-empty-token-012345"}) as client:
        answer = ask(client, "Найди программу для рисования")
        assert "в проверенных источниках не найдено" in answer
        assert "Запуск не выполнялся" in answer


@pytest.mark.parametrize("slot,expected", [
    ("видеоредакторы", "видеоредактор"),
    ("обработку фотографий", "обработка фотографий"),
    ("для записи экрана", "запись экрана"),
    ("для обработки фотографий", "обработка фотографий"),
    ("pdf", "просмотр pdf"),
    ("flac", "плеер"),
    ("3D-модель", "3d редактор"),
    ("для рисования", "графический редактор"),
    ("просмотр изображений", "просмотр изображений"),
    ("для готовки", None),
    ("нейросети", None),
    ("", None),
])
def test_purpose_resolution_units(slot, expected):
    assert discovery.purpose_key(slot) == expected


@pytest.mark.parametrize("phrase,slot", [
    ("Чем мне открыть PDF?", "PDF"),
    ("Чем можно открыть 3D-модель?", "3D-модель"),
    ("Чем послушать flac?", "flac"),
    ("Какая программа подойдёт для записи экрана?", "записи экрана"),
    ("У меня есть что-нибудь для обработки фотографий?", "для обработки фотографий"),
    ("Покажи установленные видеоредакторы", "видеоредакторы"),
    ("Покажи установленные программы для рисования", "для рисования"),
    ("Какой браузер установлен?", "браузер"),
])
def test_question_shapes_extract_slots(phrase, slot):
    assert commands.application_query(phrase) == slot


@pytest.mark.parametrize("phrase", [
    "Открой Blender", "Не открывай Blender", "Расскажи о Blender", "Найди песню Blender",
    "Открой программу для таблиц", "Открой программу для текста", "Не подскажешь, чем открыть PDF?",
    "найди песню монтажа", "включи музыку для рисования",
])
def test_other_intents_are_not_captured_as_purpose_queries(phrase):
    assert commands.application_query(phrase) is None


def test_purpose_matches_rank_known_names_before_category(tmp_path):
    targets = {}
    for name, filename in [("Unknown Viewer", "uv.exe"), ("IrfanView", "iv.exe")]:
        path = tmp_path / filename; path.touch(); targets[name] = path
    rows = [
        {"id": "1", "name": "Unknown Viewer", "category": "other", "target": str(targets["Unknown Viewer"]), "source": "s", "aliases": []},
        {"id": "2", "name": "IrfanView", "category": "other", "target": str(targets["IrfanView"]), "source": "s", "aliases": []},
    ]
    scanner = discovery.ApplicationScanner(tmp_path)
    scanner.saved = lambda: {"supported": True, "items": rows, "categories": {}, "warnings": [], "scanned_at": None}
    matches = scanner.purpose_matches("просмотр изображений")
    assert [item["name"] for item in matches] == ["IrfanView"]
