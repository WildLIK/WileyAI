"""Explicit home commands only. Model output and source text never reach this parser."""
import re
import time

from .home_assistant import HomeAction


def request(text, name="Уайли"):
    value = text.strip()
    if value.startswith(('"', '«', "'", "`")): return None
    value = re.sub(r"^" + re.escape(name) + r"\s*[,!:]\s*", "", value, flags=re.I)
    value = value.strip(" .!?")
    if re.fullmatch(r"подтверждаю\s+умный\s+дом", value, re.I): return {"kind": "confirm"}
    if re.fullmatch(r"(?:отмени|отмена)\s+умный\s+дом", value, re.I): return {"kind": "cancel"}
    if re.fullmatch(r"(?:проверь|покажи)\s+умный\s+дом|статус\s+умного\s+дома", value, re.I): return {"kind": "status", "query": ""}
    match = re.fullmatch(r"(?:умный\s+дом|home\s+assistant)\s*[:,]?\s*(.*)", value, re.I)
    if not match: return None
    command = match[1].strip()
    if command.casefold() in {"отмена", "отмени"}: return {"kind": "cancel"}
    if command.casefold() in {"", "статус", "устройства"}: return {"kind": "status", "query": ""}
    selected = re.fullmatch(r"(?:выбери|номер)\s+(\d{1,2})", command, re.I)
    if selected: return {"kind": "select", "index": int(selected[1])}
    for action, pattern in (("on", r"включи\s+(.+)"), ("off", r"выключи\s+(.+)"), ("status", r"(?:проверь|покажи)\s+(.+)")):
        found = re.fullmatch(pattern, command, re.I)
        if found: return {"kind": action, "query": found[1].strip(' "«»'), "value": None}
    found = re.fullmatch(r"(яркость|скорость)\s+(.+?)(?:\s+на)?\s+(\d{1,3})\s*(?:%|процентов)?", command, re.I)
    if found: return {"kind": "brightness" if found[1].casefold() == "яркость" else "speed", "query": found[2].strip(' "«»'), "value": int(found[3])}
    return {"kind": "help"}


def state_text(state):
    attributes = state["attributes"]
    value = {"on": "включено", "off": "выключено", "unavailable": "недоступно", "unknown": "неизвестно"}.get(state["state"], state["state"])
    if state.get("unit"): value += " " + state["unit"]
    if state["state"] == "on" and "brightness" in attributes: value += ", яркость " + str(round(attributes["brightness"] * 100 / 255)) + "%"
    if "percentage" in attributes: value += ", скорость " + str(attributes["percentage"]) + "%"
    return state["name"] + " (" + state["entity_id"] + "): " + value


async def handle(home, store, command, progress):
    key = store.conversation_id
    pending = home.chat_pending.pop(key, None)
    if not command: return None
    if command["kind"] == "help": return "Команды: «умный дом, включи Кухня», «умный дом, выключи Кухня», «умный дом, яркость Кухня на 30», «проверь умный дом». Действие сначала показывается для подтверждения."
    if command["kind"] == "cancel": return "Подготовленное действие умного дома отменено. Команда устройству не отправлялась."
    if command["kind"] in {"brightness", "speed"} and not 0 <= command["value"] <= 100: return "Укажите " + ("яркость" if command["kind"] == "brightness" else "скорость") + " в процентах от 0 до 100. Команда устройству не отправлялась."
    if pending and (pending["expires"] < time.monotonic() or pending["scope"] != store.scope_id or pending["epoch"] != home.read().get("epoch")): pending = None
    async with home.lock:
        if command["kind"] == "confirm":
            if not pending or pending["kind"] != "confirm": return "Нет подготовленного действия умного дома. Сначала назовите устройство и действие."
            return (await home.dispatch(store, pending["ticket"], True, progress))["text"]
        if command["kind"] == "select":
            if not pending or pending["kind"] != "select" or not 1 <= command["index"] <= len(pending["options"]): return "Нет такого варианта устройства. Повторите команду умного дома с его названием."
            entity_id = pending["options"][command["index"] - 1]
            command = pending["command"]
        else:
            binding = home.binding(store)
            selected = [row for row in (await home.entities(store))["entities"] if row["entity_id"] in binding["entities"]]
            query = command.get("query", "").casefold().replace("ё", "е")
            found = [row for row in selected if not query or query in row["name"].casefold().replace("ё", "е") or query == row["entity_id"]]
            if command["kind"] == "status":
                return "Home Assistant, проверено сейчас:\n" + "\n".join(state_text(row) for row in found[:20]) + ("\nПоказаны первые 20. Уточните название." if len(found) > 20 else "") if found else "Нет выбранных устройств с таким названием. Отметьте устройства текущего пространства в разделе «Интеграции»."
            exact = [row for row in found if query == row["name"].casefold().replace("ё", "е") or query == row["entity_id"]]
            found = exact or found
            if not found: return "Не найдено выбранное устройство. Уточните название или отметьте его в разделе «Интеграции»."
            if len(found) > 1:
                if len(found) > 10: return "Слишком много подходящих устройств. Назовите полное имя или entity_id из раздела «Интеграции»."
                home.chat_pending[key] = {"kind": "select", "scope": store.scope_id, "epoch": home.read()["epoch"], "expires": time.monotonic() + 300, "options": [row["entity_id"] for row in found], "command": command}
                return "Найдено несколько устройств. Пока ничего не изменено:\n" + "\n".join(str(index) + ". " + row["name"] + " — " + row["entity_id"] for index, row in enumerate(found, 1)) + "\nОтветьте «умный дом, выбери 1» с нужным номером."
            entity_id = found[0]["entity_id"]
        preview = await home.preview(store, HomeAction(entity_id=entity_id, action=command["kind"], value=command.get("value")))
        home.chat_pending[key] = {"kind": "confirm", "scope": store.scope_id, "epoch": home.read()["epoch"], "expires": time.monotonic() + 300, "ticket": preview["ticket"]}
        return "Подготовлено: " + preview["label"] + " — «" + preview["device"]["name"] + "» (" + entity_id + ")" + (" на " + str(preview["value"]) + "%" if preview["value"] is not None else "") + ".\nСейчас: " + state_text(preview["device"]) + ".\nКоманда ещё не отправлена. Скажите «подтверждаю умный дом» или «отмена умный дом»."
