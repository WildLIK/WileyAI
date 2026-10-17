import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading

from fastapi.testclient import TestClient
import pytest

from core import document_summary as summary, providers
from core.api import create_app
from core.config import Settings
from core.document_library import Library
from core.chatspaces import Spaces

TOKEN = "document-summary-tests-0123456789"


@pytest.mark.parametrize("text,expected", [
    ('{"wiley_document_action":"read_all"}', True),
    ('```json\n{"wiley_document_action": "read_all"}\n```', True),
    ('```\n{"wiley_document_action": "read_all"}\n```', True),
    ('{"wiley_document_action":"read_all","path":"private.txt"}', False),
    ('{"wiley_document_action":"open_app"}', False),
    ('[{"wiley_document_action":"read_all"}]', False),
    ('{"wiley_document_action":', False),
    ('Пример: {"wiley_document_action":"read_all"}', False),
    ('Перескажи этот файл', False),
])
def test_only_the_exact_model_read_request_is_accepted(text, expected):
    assert summary.read_action(text) is expected


@pytest.mark.parametrize("fenced", [None, "json", ""])
def test_streamed_read_request_is_hidden_and_closes_the_initial_model_stream(monkeypatch, fenced):
    closed = []
    action = json.dumps(summary.READ_ACTION)
    if fenced is not None:
        action = "```" + fenced + "\n" + action + "\n```"
    async def model(*args):
        try:
            for char in action:
                yield char
            pytest.fail("A completed read request must close this stream immediately")
        finally:
            closed.append(True)
    monkeypatch.setattr(providers, "chat", model)
    async def scenario():
        visible = []
        with pytest.raises(summary.ReadAllRequested):
            async for delta in summary.answer_stream(Settings(), [], True):
                visible.append(delta)
        assert visible == [] and closed == [True]
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [providers.ResponseLimitReached, ValueError])
def test_ordinary_text_streams_immediately_and_partial_json_is_preserved(monkeypatch, failure):
    async def ordinary(*args):
        yield "Обычный ответ"
        pytest.fail("First text must be visible without waiting for another chunk")
    monkeypatch.setattr(providers, "chat", ordinary)
    async def first():
        output = summary.answer_stream(Settings(), [], True)
        assert await anext(output) == "Обычный ответ"
        await output.aclose()
    asyncio.run(first())
    async def partial(*args):
        yield '{"answer":"частичный'
        raise failure("Обрыв")
    monkeypatch.setattr(providers, "chat", partial)
    async def second():
        visible = []
        with pytest.raises(failure):
            async for delta in summary.answer_stream(Settings(), [], True):
                visible.append(delta)
        assert visible == ['{"answer":"частичный']
    asyncio.run(second())


@pytest.mark.parametrize("question", [
    "ну как бы,  мне нужно было краткий пересказ от начала до конца",
    "Можешь кратко рассказать всю историю, включая финал?",
    "Мне хотелось бы узнать общую картину книги",
])
def test_model_decides_to_read_after_a_free_form_followup(tmp_path, monkeypatch, question):
    initial = []
    async def model(config, messages):
        if summary.READ_TOOL in messages[0]["content"]:
            initial.append(messages)
            for char in json.dumps(summary.READ_ACTION):
                yield char
        elif messages[0]["content"] in {summary.READ_PROMPT, summary.MERGE_PROMPT}:
            yield "Сначала кража, затем расследование, в финале возвращение домой."
        else:
            yield "История началась с кражи. В финале герой вернулся домой."
    monkeypatch.setattr(providers, "chat", model)
    app = create_app(tmp_path, TOKEN)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as api:
        store = app.state.store
        store.add_message("user", "Про что этот файл?")
        store.add_message("assistant", "По отрывку видно начало расследования.")
        doc = Library(store).add("Книга.txt", "Кража. " * 1000 + "В финале возвращение домой.")
        result = events(api.post("/chat", json={"text": question, "document_ids": [doc["id"]]}))
        assert len(initial) == 1 and question in initial[0][-1]["content"]
        assert any(item.get("phase") == "reading" for item in result)
        done = next(item["message"] for item in result if item["type"] == "done")
        assert "обработан весь извлечённый текст" in done["content"]
        assert "wiley_document_action" not in str(result)
        assert "document_context" not in done


def test_every_character_is_read_in_order_with_paragraph_boundaries():
    text = ("Абзац. Описание с emoji 😺.\n" * 5000) + "ФИНАЛ: герой вернулся домой."
    parts = list(summary.chunks(text, 601))
    assert "".join(part for _, part in parts) == text
    assert parts[0][0] == 0 and all(len(part) <= 601 for _, part in parts)
    assert all(right[0] == left[0] + len(left[1]) for left, right in zip(parts, parts[1:]))
    assert parts[-1][1].endswith("вернулся домой.")


def test_large_document_reads_all_parts_then_reduces_with_bounded_context(monkeypatch):
    calls, inputs = [], []
    async def model(settings, messages):
        calls.append((settings, messages))
        if messages[0]["content"] == summary.READ_PROMPT:
            inputs.append(messages[1]["content"].split("\n", 1)[1])
        marker = " ФИНАЛ: герой вернулся домой." if "ФИНАЛ" in messages[1]["content"] else ""
        yield "Последовательность событий и важные решения. " * 9 + marker
    monkeypatch.setattr(providers, "chat", model)
    original = Settings()
    content = ("Рейдж вышел из города и встретил Меланию.\n" * 15000) + "ФИНАЛ: герой вернулся домой."
    async def scenario():
        return [item async for item in summary.prepare(original, [{"name": "Книга.txt", "content": content}], 1400)]
    events = asyncio.run(scenario())
    assert "".join(inputs) == content
    final = events[-1]
    assert final["type"] == "prepared" and len(final["text"]) <= 1400
    assert "ФИНАЛ" in final["text"] and final["parts"] == len(inputs) > 80
    assert any(item.get("phase") == "reducing" for item in events)
    reads = [item for item in events if item.get("phase") == "reading"]
    assert reads[0]["current"] == 0 and reads[-1]["current"] == reads[-1]["total"] == len(inputs)
    for config, payload in calls:
        assert config.context_tokens == original.context_tokens
        assert sum(len(item["content"]) for item in payload) <= (config.context_tokens - providers.response_limit(config)) * 2 - 256
    assert original.response_tokens == 2048


@pytest.mark.parametrize("failure", ["empty", "limit", "broken"])
def test_failed_intermediate_read_does_not_claim_complete(monkeypatch, failure):
    async def model(*args):
        if failure != "empty":
            yield "Незавершённый конспект"
            raise (providers.ResponseLimitReached("лимит") if failure == "limit" else providers.IncompleteResponse("обрыв"))
        if False: yield ""
    monkeypatch.setattr(providers, "chat", model)
    async def scenario():
        events = []
        with pytest.raises(ValueError, match="Полный пересказ не подготовлен"):
            async for item in summary.prepare(Settings(), [{"name": "Книга.txt", "content": "Текст"}], 1400):
                events.append(item)
        assert not any(item["type"] == "prepared" for item in events)
    asyncio.run(scenario())


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_api_distinguishes_partial_context_from_full_read_and_keeps_project_scope(tmp_path, monkeypatch):
    captured = []
    async def model(config, messages):
        captured.append(messages)
        if summary.READ_TOOL in messages[0]["content"] and "Перескажи этот файл" in messages[-1]["content"]:
            yield json.dumps(summary.READ_ACTION)
        elif messages[0]["content"] in {summary.READ_PROMPT, summary.MERGE_PROMPT}:
            yield "Рейдж расследует кражу. В конце он возвращается домой."
        else:
            yield "В книге Рейдж расследует кражу и возвращается домой."
    monkeypatch.setattr(providers, "chat", model)
    app = create_app(tmp_path, TOKEN)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as api:
        store = app.state.store
        doc = Library(store).add("Книга.txt", "НАЧАЛО: кража. " + "Продолжение истории. " * 6000 + "ФИНАЛ: возвращение домой.")
        response = api.post("/chat", json={"text": "Про что этот файл?", "document_ids": [doc["id"]]})
        assert len(captured) == 1
        prompt = captured[-1][0]["content"]
        assert "конец отрывка НЕ означает конец файла" in prompt
        assert str(doc["characters"]) in prompt and "Полный извлечённый текст сохранён" in prompt
        normal = next(item["message"] for item in events(response) if item["type"] == "done")
        assert sum(len(part["text"]) for part in normal["document_context"]) < doc["characters"]
        captured.clear()
        response = api.post("/chat", json={"text": "Перескажи этот файл", "document_ids": [doc["id"]]})
        result = events(response)
        done = next(item["message"] for item in result if item["type"] == "done")
        assert "обработан весь извлечённый текст" in done["content"]
        assert "возвращается домой" in done["content"] and "document_context" not in done
        assert any(item.get("phase") == "reading" for item in result)
        assert any(item.get("phase") == "answering" for item in result)
        assert "Последовательное чтение завершено" in captured[-1][0]["content"]
        assert "Это только выбранные отрывки" not in captured[-1][0]["content"]
        assert len(captured[-1]) == 2  # Old inaccurate assistant answers are excluded.
        assert all("НАЧАЛО" not in str(message[0]) for message in captured[1:])
        assert "wiley_document_action" not in done["content"]
        assert store.memories() == []
        project = Spaces(store).create_project("Изолированный")
        other = Spaces(store).create_chat(project["id"])
        count = len(captured)
        denied = api.post("/chat", json={"text": "Перескажи", "full_document": True, "document_ids": [doc["id"]], "conversation_id": other["id"]})
        assert denied.status_code == 400 and len(captured) == count
        assert api.post("/chat", json={"text": "Перескажи", "full_document": True}).status_code == 400


def test_full_read_flag_does_not_execute_a_command_or_save_memory(tmp_path, monkeypatch):
    async def model(*args):
        yield "Сжатое описание всего документа."
    monkeypatch.setattr(providers, "chat", model)
    app = create_app(tmp_path, TOKEN)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as api:
        store = app.state.store
        doc = Library(store).add("Файл.txt", "Текст документа")
        result = events(api.post("/chat", json={"text": "Запомни: вымышленный факт", "full_document": True, "document_ids": [doc["id"]]}))
        assert any(item["type"] == "done" for item in result)
        assert store.memories() == []


@pytest.mark.parametrize("full", [False, True])
def test_stop_cancels_reading_without_saving_notes_as_finished_answer(tmp_path, monkeypatch, full):
    started, cancelled = threading.Event(), threading.Event()
    async def model(config, messages):
        if summary.READ_TOOL in messages[0]["content"]:
            yield json.dumps(summary.READ_ACTION)
            return
        started.set()
        try:
            await asyncio.sleep(3600)
            yield "Недоступный поздний ответ"
        finally:
            cancelled.set()
    monkeypatch.setattr(providers, "chat", model)
    app = create_app(tmp_path, TOKEN)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as api:
        doc = Library(app.state.store).add("Книга.txt", "Текст " * 5000)
        with ThreadPoolExecutor() as pool:
            pending = pool.submit(api.post, "/chat", json={"text": "Перескажи весь файл", "full_document": full, "document_ids": [doc["id"]], "request_id": "reading-turn"})
            assert started.wait(5)
            assert api.post("/chat/stop", json={"request_id": "reading-turn"}).status_code == 200
            result = events(pending.result(timeout=5))
        assert cancelled.is_set() and not any(item["type"] == "done" for item in result)
        assert [item["role"] for item in app.state.store.messages()] == ["user"]


def test_too_small_final_context_fails_before_any_model_request(monkeypatch):
    async def model(*args):
        pytest.fail("No model request expected")
        yield ""
    monkeypatch.setattr(providers, "chat", model)
    async def scenario():
        with pytest.raises(ValueError, match="мало места"):
            [item async for item in summary.prepare(Settings(), [{"name": "Книга.txt", "content": "Текст"}], 300)]
    asyncio.run(scenario())
