"""User-confirmed names resolve only to freshly validated catalog entries."""
import hashlib
import re
import time
import uuid

from .app_discovery import normalized_name, safe_application_name
from .config import Pronunciation, Settings


def identity(name):
    return hashlib.sha256(normalized_name(name).encode("utf-8")).hexdigest()


def normalize(spoken):
    return re.sub(r"\s+", " ", spoken.casefold().replace("ё", "е")).strip(" .")


def candidates(scanner, rules, spoken):
    key = normalize(spoken)
    if not key or not safe_application_name(key):
        return []
    ids = {rule.application_id for rule in rules if rule.enabled and normalize(rule.spoken) == key}
    if not ids:
        return []
    # A logical identity intentionally excludes paths: multiple installs with
    # the same display name remain separate choices, never an automatic launch.
    return [item for item in scanner.valid_items() if identity(item["name"]) in ids]


def prompt_names(scanner, rules, limit=8):
    items = scanner.saved().get("items", [])
    available = {identity(item["name"]): item["name"] for item in items if safe_application_name(item.get("name", ""))}
    values = []
    for rule in rules:
        if rule.enabled and rule.application_id in available:
            values.extend((rule.spoken, available[rule.application_id]))
    # A small, deterministic sample of verified catalog categories supplies
    # context even before the first learned pronunciation; never the full list.
    seen_categories = set()
    for item in items:
        category = item.get("category", "other")
        if category == "other" or category in seen_categories or not safe_application_name(item.get("name", "")):
            continue
        seen_categories.add(category)
        values.append(item["name"])
        if len(seen_categories) == 4:
            break
    return list(dict.fromkeys(values))[:limit]


def consume_learning(store, scanner, text, assistant_name):
    state = store.dialogue()
    pending = state.pop("pending_pronunciation", None)
    if not pending:
        return None
    store.save_dialogue(state)
    value = re.sub(r"^" + re.escape(assistant_name) + r"[,! ]+", "", text.strip(), flags=re.I).casefold().strip(" .!?")
    if value not in {"да", "запомни", "подтверждаю", "нет", "отмена", "не надо"}:
        return None
    history = store.list("messages", 2)
    if len(history) != 2 or history[-2]["role"] != "assistant" or history[-2]["id"] != pending.get("assistant_id") or not 0 <= time.time() - pending.get("created", 0) <= 300:
        return "Предложение сохранить произношение устарело."
    if value in {"нет", "отмена", "не надо"}:
        return "Хорошо, не буду запоминать произношение."
    matches = [item for item in scanner.valid_items() if identity(item["name"]) == pending.get("application_id")]
    if len(matches) != 1:
        return "Приложение изменилось или найдено несколько вариантов. Проверьте его в настройках произношений."
    spoken = pending.get("spoken", "")
    if not safe_application_name(spoken) or not re.fullmatch(r"[\w .-]{1,100}", spoken):
        return "Не удалось сохранить это произношение."
    rule = Pronunciation(id=uuid.uuid4().hex, application_id=identity(matches[0]["name"]), application_name=matches[0]["name"], spoken=spoken)
    def update(current):
        if any(entry.application_id == rule.application_id and normalize(entry.spoken) == normalize(rule.spoken) for entry in current.pronunciations):
            return current
        return Settings.model_validate(current.model_dump() | {"pronunciations": [*current.pronunciations, rule]})
    store.update_settings(update)
    return f"Запомнила произношение «{spoken}» для {matches[0]['name']}."
