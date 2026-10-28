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


def grounded_claims(schema, text, source=None):
    return {"claims": {name: {"text": text, "sources": [source if source is not None else spec["properties"]["sources"]["items"]["enum"][0]]}
            for name, spec in schema["properties"]["claims"]["properties"].items()}}


def grounded_reply(messages, schema=None):
    prompt, data = messages[0]["content"], messages[-1]["content"]
    if prompt in {summary.READ_PROMPT, summary.MERGE_PROMPT}:
        rows = json.loads(data)
        ids = [rows[0]["id"], rows[-1]["id"]] if len(rows) > 1 and prompt == summary.READ_PROMPT else [rows[0]["id"]]
        return json.dumps({"ids": ids})
    if prompt == summary.ANSWER_PROMPT:
        return json.dumps(grounded_claims(schema, "В финале возвращение домой."))
    if prompt == summary.VERIFY_PROMPT:
        return json.dumps({"supported": [row["id"] for row in json.loads(data)]})
    raise AssertionError(prompt)


@pytest.mark.parametrize("text,expected", [
    ('{"mode":"full"}', "full"),
    ('```json\n{"mode": "fragments"}\n```', "fragments"),
    ('Я готова прочитать файл.\nВыберите режим: {"mode":"full"}', "full"),
    ('{"mode":"full","path":"private.txt"}', None),
    ('{"mode":"open_app"}', None),
    ('{"mode":', None),
    ('[{"mode":"full"}]', None),
    ('{"mode":"full"} {"mode":"fragments"}', None),
    ('Прочитай файл', None),
])
def test_internal_mode_is_validated_and_prose_around_it_stays_internal(text, expected):
    if expected is None:
        with pytest.raises(ValueError): summary.parse_mode(text)
    else:
        assert summary.parse_mode(text) == expected


@pytest.mark.parametrize("failure", [providers.ResponseLimitReached, ValueError])
def test_ordinary_text_streams_after_mode_selection_and_partial_json_is_preserved(monkeypatch, failure):
    async def ordinary(*args):
        yield "Обычный ответ"
        pytest.fail("First text must be visible without waiting for another chunk")
    monkeypatch.setattr(providers, "chat", ordinary)
    async def first():
        output = summary.respond(Settings(), [], [], "Вопрос")
        assert await anext(output) == {"type": "delta", "text": "Обычный ответ"}
        await output.aclose()
    asyncio.run(first())
    async def partial(*args):
        yield '{"answer":"частичный'
        raise failure("Обрыв")
    monkeypatch.setattr(providers, "chat", partial)
    async def second():
        visible = []
        with pytest.raises(failure):
            async for update in summary.respond(Settings(), [], [], "Вопрос"):
                visible.append(update["text"])
        assert visible == ['{"answer":"частичный']
    asyncio.run(second())


@pytest.mark.parametrize("question", [
    "ну как бы,  мне нужно было краткий пересказ от начала до конца",
    "Можешь кратко рассказать всю историю, включая финал?",
    "Мне хотелось бы узнать общую картину книги",
    "прочитай",
])
def test_model_decides_to_read_after_a_free_form_followup(tmp_path, monkeypatch, question):
    initial = []
    async def decision(config, messages, schema, **kwargs):
        if messages[0]["content"] != summary.MODE_PROMPT:
            return grounded_reply(messages, schema)
        initial.append(messages)
        assert config.response_tokens == 64 and config.context_tokens == 4096
        assert schema == summary.MODE_SCHEMA
        return 'Я готова прочитать документ. Выберите режим: {"mode":"full"}'
    async def model(config, messages):
        if messages[0]["content"] in {summary.READ_PROMPT, summary.MERGE_PROMPT}:
            yield "Сначала кража, затем расследование, в финале возвращение домой."
        else:
            yield "История началась с кражи. В финале герой вернулся домой."
    monkeypatch.setattr(providers, "chat", model)
    monkeypatch.setattr(providers, "structured", decision)
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
        assert all(row["purpose"] == "summary_evidence" for row in done["document_context"])


def test_every_character_is_read_in_order_with_paragraph_boundaries():
    text = ("Абзац. Описание с emoji 😺.\n" * 5000) + "ФИНАЛ: герой вернулся домой."
    parts = list(summary.chunks(text, 601))
    assert "".join(part for _, part in parts) == text
    assert parts[0][0] == 0 and all(len(part) <= 601 for _, part in parts)
    assert all(right[0] == left[0] + len(left[1]) for left, right in zip(parts, parts[1:]))
    assert parts[-1][1].endswith("вернулся домой.")


def test_large_document_reads_all_parts_then_reduces_with_bounded_context(monkeypatch):
    calls, inputs = [], []
    async def model(settings, messages, schema, **kwargs):
        calls.append((settings, messages))
        if messages[0]["content"] == summary.READ_PROMPT:
            inputs.extend(row["text"] for row in json.loads(messages[1]["content"]))
        return grounded_reply(messages, schema)
    monkeypatch.setattr(providers, "structured", model)
    original = Settings()
    content = ("Рейдж вышел из города и встретил Меланию.\n" * 15000) + "ФИНАЛ: герой вернулся домой."
    async def scenario():
        return [item async for item in summary.prepare(original, [{"name": "Книга.txt", "content": content}], 1400)]
    events = asyncio.run(scenario())
    assert "".join(inputs) == content
    final = events[-1]
    assert final["type"] == "prepared" and len(final["text"]) <= 1400
    assert "ФИНАЛ" in final["text"] and final["parts"] > 80
    assert any(item.get("phase") == "reducing" for item in events)
    reads = [item for item in events if item.get("phase") == "reading"]
    assert reads[0]["current"] == 0 and reads[-1]["current"] == reads[-1]["total"] == final["parts"]
    for config, payload in calls:
        assert config.context_tokens == original.context_tokens
        assert sum(len(item["content"]) for item in payload) <= (config.context_tokens - providers.response_limit(config)) * 2 - 256
    assert original.response_tokens == 2048


@pytest.mark.parametrize("failure", ["empty", "limit", "broken"])
def test_failed_intermediate_read_does_not_claim_complete(monkeypatch, failure):
    async def model(*args, **kwargs):
        if failure != "empty":
            raise (providers.ResponseLimitReached("лимит") if failure == "limit" else providers.IncompleteResponse("обрыв"))
        return ""
    monkeypatch.setattr(providers, "structured", model)
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
    async def decision(config, messages, schema, **kwargs):
        if messages[0]["content"] == summary.MODE_PROMPT:
            return json.dumps({"mode": "full" if "Перескажи этот файл" in messages[-1]["content"] else "fragments"})
        captured.append(messages)
        return grounded_reply(messages, schema)
    async def model(config, messages):
        captured.append(messages)
        if messages[0]["content"] in {summary.READ_PROMPT, summary.MERGE_PROMPT}:
            yield "Рейдж расследует кражу. В конце он возвращается домой."
        else:
            yield "В книге Рейдж расследует кражу и возвращается домой."
    monkeypatch.setattr(providers, "chat", model)
    monkeypatch.setattr(providers, "structured", decision)
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
        assert "возвращение домой" in done["content"] and done["document_context"]
        assert any(item.get("phase") == "reading" for item in result)
        assert any(item.get("phase") == "answering" for item in result)
        assert any("Все части выбранных файлов обработаны" in str(messages) for messages in captured)
        assert "Это только выбранные отрывки" not in captured[-1][0]["content"]
        assert len(captured[-1]) == 2  # Old inaccurate assistant answers are excluded.
        assert "По отрывку" not in str(captured[-1])
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
    async def structured(config, messages, schema, **kwargs):
        return grounded_reply(messages, schema)
    monkeypatch.setattr(providers, "structured", structured)
    monkeypatch.setattr(providers, "chat", model)
    app = create_app(tmp_path, TOKEN)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as api:
        store = app.state.store
        doc = Library(store).add("Файл.txt", "Текст документа")
        result = events(api.post("/chat", json={"text": "Запомни: вымышленный факт", "full_document": True, "document_ids": [doc["id"]]}))
        assert any(item["type"] == "done" for item in result)
        assert store.memories() == []


def test_complete_small_document_needs_no_separate_decision(monkeypatch):
    async def unexpected(*args):
        pytest.fail("The entire file is already visible")
    async def model(*args):
        yield "Содержание небольшого файла."
    monkeypatch.setattr(providers, "structured", unexpected)
    monkeypatch.setattr(providers, "chat", model)
    doc = {"id": "doc", "name": "Файл.txt", "content": "Весь текст 😺"}
    sources = [{"document_id": "doc", "offset": 0, "text": doc["content"]}]
    async def scenario():
        result = [item async for item in summary.respond(Settings(), [], [doc], "Что в файле?", sources=sources)]
        assert result == [{"type": "delta", "text": "Содержание небольшого файла."}]
    asyncio.run(scenario())
    assert summary.fully_visible([doc], [sources[0], sources[0]])
    assert not summary.fully_visible([doc], [{"document_id": "doc", "offset": 1, "text": doc["content"][1:]}])


def test_stopping_the_internal_decision_cancels_it_without_showing_its_text(tmp_path, monkeypatch):
    started, cancelled = threading.Event(), threading.Event()
    async def decision(*args):
        started.set()
        try:
            await asyncio.sleep(3600)
            return '{"mode":"full"}'
        finally:
            cancelled.set()
    async def unexpected(*args):
        pytest.fail("No answer or reading after cancellation")
        yield ""
    monkeypatch.setattr(providers, "structured", decision)
    monkeypatch.setattr(providers, "chat", unexpected)
    app = create_app(tmp_path, TOKEN)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as api:
        doc = Library(app.state.store).add("Книга.txt", "Текст " * 2000)
        with ThreadPoolExecutor() as pool:
            pending = pool.submit(api.post, "/chat", json={"text": "прочитай", "document_ids": [doc["id"]], "request_id": "mode-turn"})
            assert started.wait(5)
            assert api.post("/chat/stop", json={"request_id": "mode-turn"}).status_code == 200
            result = events(pending.result(timeout=5))
        assert cancelled.is_set() and not any(item["type"] in {"delta", "done"} for item in result)


def test_invalid_internal_decision_is_not_published_as_an_answer(tmp_path, monkeypatch):
    async def decision(*args):
        return 'Я готова прочитать документ. {"mode":"full","path":"unknown.txt"}'
    async def unexpected(*args):
        pytest.fail("An invalid decision cannot start reading or an answer")
        yield ""
    monkeypatch.setattr(providers, "structured", decision)
    monkeypatch.setattr(providers, "chat", unexpected)
    app = create_app(tmp_path, TOKEN)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as api:
        doc = Library(app.state.store).add("Книга.txt", "Текст " * 2000)
        result = events(api.post("/chat", json={"text": "прочитай", "document_ids": [doc["id"]]}))
        assert any(item["type"] == "error" for item in result)
        assert not any(item["type"] in {"delta", "done"} for item in result)
        assert "unknown.txt" not in str(result)
        assert [item["role"] for item in app.state.store.messages()] == ["user"]


@pytest.mark.parametrize("full", [False, True])
def test_stop_cancels_reading_without_saving_notes_as_finished_answer(tmp_path, monkeypatch, full):
    started, cancelled = threading.Event(), threading.Event()
    async def decision(config, messages, schema, **kwargs):
        if messages[0]["content"] == summary.MODE_PROMPT:
            return '{"mode":"full"}'
        started.set()
        try:
            await asyncio.sleep(3600)
            return "Недоступный поздний ответ"
        finally:
            cancelled.set()
    monkeypatch.setattr(providers, "structured", decision)
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
    async def scenario():
        with pytest.raises(ValueError, match="мало места"):
            [item async for item in summary.prepare(Settings(), [{"name": "Книга.txt", "content": "Текст"}], 300)]
    asyncio.run(scenario())


@pytest.mark.parametrize("raw", [
    '{"ids":[999]}', '{"ids":[true]}', '{"ids":[1,1]}', '{"ids":[]}',
    '{"ids":["1"]}', '{"ids":[1],"note":"Новый персонаж"}',
    'Конспект: {"ids":[1]}', '[]',
])
def test_reader_cannot_invent_or_rewrite_source_excerpts(raw):
    with pytest.raises(ValueError):
        summary.parse_ids(raw, "ids", [1, 2], 2)


@pytest.mark.parametrize("failure", ["rejected", "bad_citation", "malformed", "interrupted"])
def test_unsupported_draft_is_neither_published_nor_spoken_and_quotes_are_kept(tmp_path, monkeypatch, failure):
    seen, drafts = [], []
    async def model(config, messages, schema, **kwargs):
        prompt = messages[0]["content"]
        seen.append(prompt)
        if prompt == summary.ANSWER_PROMPT:
            if failure == "malformed":
                return "Сборник историй с Мартином и Таносом."
            return json.dumps(grounded_claims(schema, "Мартин победил Таноса в дуэли.", 999 if failure == "bad_citation" else 1))
        if prompt == summary.VERIFY_PROMPT:
            drafts.extend(json.loads(messages[-1]["content"]))
            if failure == "interrupted":
                raise providers.ResponseLimitReached("Лимит проверки")
            return '{"supported":[]}'
        return grounded_reply(messages, schema)
    monkeypatch.setattr(providers, "structured", model)
    app = create_app(tmp_path, TOKEN)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as api:
        doc = Library(app.state.store).add("Книга.txt", "Рейдж нашёл пропавшую книгу. Затем он вернулся домой.")
        result = events(api.post("/chat", json={"text": "Перескажи целиком", "document_ids": [doc["id"]], "full_document": True}))
        answer = next(item["message"] for item in result if item["type"] == "done")
        visible = "".join(item["text"] for item in result if item["type"] == "delta")
        assert visible == answer["content"]
        assert "не прошёл проверку" in visible and "Рейдж нашёл" in visible
        assert all(term not in visible for term in ("Мартин", "Танос", "дуэли"))
        assert answer["document_context"][0]["purpose"] == "summary_evidence"
        if failure in {"rejected", "interrupted"}:
            assert drafts and drafts[0]["quotes"] == ["Рейдж нашёл пропавшую книгу. Затем он вернулся домой."]
        else:
            assert summary.VERIFY_PROMPT not in seen


def test_only_original_text_from_selected_file_can_reach_summary_even_with_foreign_history(tmp_path, monkeypatch):
    inputs = []
    async def model(config, messages, schema, **kwargs):
        inputs.append(messages)
        if messages[0]["content"] == summary.ANSWER_PROMPT:
            return json.dumps(grounded_claims(schema, "Рейдж нашёл книгу и вернулся домой."))
        return grounded_reply(messages, schema)
    monkeypatch.setattr(providers, "structured", model)
    app = create_app(tmp_path, TOKEN)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as api:
        store = app.state.store
        Library(store).add("Другой.txt", "Мартин встретил Таноса.")
        store.add_message("assistant", "Выдуманный пересказ: Мартин встретил Таноса.")
        book = "Рейдж нашёл книгу и вернулся домой.\n" * 150
        doc = Library(store).add("Выбранный.txt", book)
        result = events(api.post("/chat", json={"text": "Перескажи целиком", "full_document": True, "document_ids": [doc["id"]]}))
        answer = next(item["message"] for item in result if item["type"] == "done")
        assert "не прошёл проверку" not in answer["content"]
        assert all("Танос" not in str(messages) and "Мартин" not in str(messages) for messages in inputs)
        for source in answer["document_context"]:
            assert source["document_id"] == doc["id"] and source["purpose"] == "summary_evidence"
            assert book[source["offset"]:source["offset"] + len(source["text"])] == source["text"]
        assert "[1]" in answer["content"]


def test_sources_from_different_files_cannot_be_combined_into_one_event(monkeypatch):
    async def model(config, messages, schema, **kwargs):
        value = grounded_claims(schema, "Рейдж победил Таноса.")
        value["claims"]["part_6"]["sources"] = [6, 7]
        return json.dumps(value)
    monkeypatch.setattr(providers, "structured", model)
    evidence = [{"file": 1, "text": "Рейдж ушёл домой."}] * 6 + [{"file": 2, "text": "Танос остался."}]
    with pytest.raises(ValueError, match="разных файлов"):
        asyncio.run(summary.verified_answer(Settings(), "Перескажи", "Контекст", evidence))


def test_cancel_during_fact_check_keeps_unchecked_draft_out_of_history(tmp_path, monkeypatch):
    started, cancelled = threading.Event(), threading.Event()
    async def model(config, messages, schema, **kwargs):
        if messages[0]["content"] != summary.VERIFY_PROMPT:
            return grounded_reply(messages, schema)
        started.set()
        try:
            await asyncio.sleep(3600)
        finally:
            cancelled.set()
    monkeypatch.setattr(providers, "structured", model)
    app = create_app(tmp_path, TOKEN)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as api:
        doc = Library(app.state.store).add("Книга.txt", "Текст книги.")
        with ThreadPoolExecutor() as pool:
            pending = pool.submit(api.post, "/chat", json={"text": "Перескажи", "full_document": True, "document_ids": [doc["id"]], "request_id": "checking-turn"})
            assert started.wait(5)
            assert api.post("/chat/stop", json={"request_id": "checking-turn"}).status_code == 200
            result = events(pending.result(timeout=5))
        assert cancelled.is_set() and not any(item["type"] in {"delta", "done"} for item in result)
        assert [row["role"] for row in app.state.store.messages()] == ["user"]


def test_selection_biased_to_first_id_cannot_erase_the_middle_of_a_long_book(monkeypatch):
    async def model(settings, messages, schema, **kwargs):
        rows = json.loads(messages[-1]["content"])
        return json.dumps({"ids": [rows[0]["id"]]})
    monkeypatch.setattr(providers, "structured", model)
    content = "".join(f"Сцена {i}: Рейдж продолжил путешествие по дороге.\n" for i in range(7000))
    async def run():
        return [item async for item in summary.prepare(Settings(), [{"name": "Книга.txt", "content": content}], 4000)]
    prepared = asyncio.run(run())[-1]
    evidence = prepared["evidence"]
    assert len(prepared["text"]) <= 4000 and len(evidence) <= 20
    assert {min(3, row["offset"] * 4 // len(content)) for row in evidence} == {0, 1, 2, 3}
    assert all(row["text"] == content[row["offset"]:row["offset"] + len(row["text"])] for row in evidence)


def test_final_draft_must_cover_each_assigned_timeline_section():
    schema = summary.answer_schema(12)
    value = grounded_claims(schema, "Подтверждённое событие.")
    claims = summary.parse_claims(json.dumps(value), 12)
    assert [claim["sources"] for claim in claims] == [[1], [3], [5], [7], [9], [11]]
    value["claims"]["part_6"]["sources"] = [1]
    with pytest.raises(ValueError, match="другой участок"):
        summary.parse_claims(json.dumps(value), 12)
    del value["claims"]["part_6"]
    with pytest.raises(ValueError, match="хронологические"):
        summary.parse_claims(json.dumps(value), 12)


@pytest.mark.parametrize("sources", [[1, 1, 1], [True, 1], [1.0, 1], [999]])
def test_duplicate_citations_are_normalized_only_after_strict_validation(sources):
    value = grounded_claims(summary.answer_schema(1), "Событие.")
    value["claims"]["part_1"]["sources"] = sources
    if sources == [1, 1, 1] and all(type(source) is int for source in sources):
        assert summary.parse_claims(json.dumps(value), 1)[0]["sources"] == [1]
    else:
        with pytest.raises(ValueError):
            summary.parse_claims(json.dumps(value), 1)


def test_many_files_with_more_than_twenty_anchors_do_not_break_bucketing(monkeypatch):
    async def model(settings, messages, schema, **kwargs):
        rows = json.loads(messages[-1]["content"])
        return json.dumps({"ids": [rows[0]["id"]]})
    monkeypatch.setattr(providers, "structured", model)
    documents = [{"name": f"Глава {n}.txt", "content": "".join(f"Глава {n}, сцена {i}: дорога продолжилась.\n" for i in range(40))} for n in range(8)]
    async def run():
        return [item async for item in summary.prepare(Settings(), documents, 12000)]
    prepared = asyncio.run(run())[-1]
    assert prepared["type"] == "prepared"
    assert 20 < len(prepared["evidence"]) <= summary.evidence_limit(documents)
