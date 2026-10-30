"""Separate verified action evidence, visible diagnostics and spoken wording."""
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActionResponse:
    action: str
    status: str
    target: str
    display: str
    spoken: str
    details: dict[str, Any] = field(default_factory=dict)

    def event(self):
        # Evidence remains in the display/journal; never send it as TTS text.
        return asdict(self)


def target_name(value):
    value = (value or "").split(" · ")[0].strip()
    if not value or len(value) > 100 or any(ch in value for ch in "\\/:\n\r"):
        return "приложение"
    return value


def open_result(outcome, display, gender):
    name = target_name(outcome.get("target", ""))
    action, status = outcome.get("action", "app"), outcome.get("status", "error")
    if status == "denied":
        spoken = "Доступ к открытию отключён."
    elif status == "error":
        spoken = f"Не удалось открыть {name}."
    elif action == "app" and status == "already_running":
        spoken = f"{name} уже запущен."
    elif action == "app" and status == "process_started":
        spoken = f"Процесс {name} запущен."
    else:
        verb = {"feminine": "Отправила команду", "masculine": "Отправил команду", "neutral": "Отправлена команда"}.get(gender, "Отправлена команда")
        spoken = f"{verb} открытия {name}. Результат не подтверждён."
    return ActionResponse(action, status, name, display, spoken, outcome.get("details") or {})


def audio_result(outcome, display, gender):
    action, data = outcome.get("action", ""), outcome.get("result", {})
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    if action in {"volume", "change_volume"} and data.get("confirmed") and isinstance(state.get("volume"), (int, float)):
        return ActionResponse("audio", "confirmed", action, display, f"Громкость — {round(state['volume'])} процентов.")
    if "volume" in data:
        if action in {"mute", "unmute"} and isinstance(data.get("muted"), bool):
            spoken = "Звук выключен." if data["muted"] else "Звук включён."
        else:
            spoken = f"Громкость — {data['volume']} процентов."
            if data.get("muted") is True: spoken += " Звук выключен."
        return ActionResponse("audio", "confirmed", action, display, spoken)
    media = data.get("media", data)
    if data.get("candidates"):
        spoken, status = "Нашлось несколько вариантов. Уточните исполнителя или название.", "clarification"
    elif "media" in data and not media.get("available"):
        spoken, status = "Не удалось найти работающий проигрыватель.", "unavailable"
    elif media.get("confirmed"):
        spoken = {"play": "Воспроизведение подтверждено.", "pause": "Пауза подтверждена.", "next": "Трек переключён.", "previous": "Предыдущий трек выбран."}.get(action, "Состояние проигрывателя проверено.")
        status = "confirmed"
    else:
        spoken = "Результат команды проигрывателя не подтверждён."
        status = "unconfirmed"
    return ActionResponse("audio", status, action, display, spoken)


def choices_result(choices, display, gender):
    names = [target_name(choice.get("label", "")) for choice in choices[:3]]
    prefix = {"feminine": "Нашла", "masculine": "Нашёл", "neutral": "Найдено"}.get(gender, "Найдено")
    if len(names) == 1:
        spoken = f"{prefix}: {names[0]}. Открыть?"
    else:
        spoken = f"{prefix} несколько вариантов: " + "; ".join(f"{index}. {name}" for index, name in enumerate(names, 1)) + ". Какой открыть?"
    return ActionResponse("open", "clarification", "", display, spoken)
