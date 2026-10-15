from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import os
import re
import subprocess
import webbrowser


@dataclass
class Command:
    kind: str
    target: str
    label: str


SITES = {"ютуб": "https://www.youtube.com", "youtube": "https://www.youtube.com", "гитхаб": "https://github.com", "github": "https://github.com", "яндекс": "https://ya.ru", "гугл": "https://www.google.com"}
APP_NAMES = {"блокнот": "notepad.exe", "калькулятор": "calc.exe", "проводник": "explorer.exe"}


def folders() -> dict[str, str]:
    home = Path.home()
    result = {"загрузки": str(home / "Downloads"), "документы": str(home / "Documents"), "рабочий стол": str(home / "Desktop"), "домашнюю папку": str(home)}
    if os.name == "nt":
        # Respect OneDrive/redirection rather than assuming all folders live under HOME.
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                for label, name in [("загрузки", "{374DE290-123F-4565-9164-39C4925E467B}"), ("документы", "Personal"), ("рабочий стол", "Desktop")]:
                    try:
                        result[label] = os.path.expandvars(winreg.QueryValueEx(key, name)[0])
                    except OSError:
                        pass
        except OSError:
            pass
    return result


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold().replace("ё", "е")).rstrip(".! ")


def resolve(text: str, aliases: list[dict]) -> Command | None:
    value = normalize(text)
    match = re.fullmatch(r"(?:пожалуйста,? )?(?:открой|запусти|покажи|открыть|запустить)(?:,? пожалуйста)?\s+(.+?)(?:,? пожалуйста)?", value)
    if not match or ("?" in text and not re.search(r"https?://", text)) or any(mark in text for mark in ('"', '«', '»', '“', '”', '\n')):
        return None
    target = match[1].strip()
    short = re.sub(r"^(?:папку|приложение|программу|сайт|файл)\s+", "", target)
    short = {"загрузок": "загрузки", "документов": "документы", "рабочего стола": "рабочий стол"}.get(short, short)
    for alias in aliases:
        if normalize(alias["name"]) in {target, short}:
            return Command(alias["kind"], alias["target"], alias["name"])
    if short in folders():
        return Command("folder", folders()[short], short)
    if short in SITES:
        return Command("url", SITES[short], short)
    if short in APP_NAMES:
        system32 = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"
        return Command("app", str(system32 / APP_NAMES[short]), short)
    if short in {"браузер", "браузер по умолчанию"}:
        return Command("url", "about:blank", "браузер")
    raw = re.sub(r"^(?:пожалуйста,? )?(?:открой|запусти|покажи|открыть|запустить)\s+(?:(?:папку|файл|сайт)\s+)?", "", text.strip(), flags=re.I).strip()
    raw = re.sub(r",? пожалуйста[.! ]*$", "", raw, flags=re.I)
    if re.fullmatch(r"https?://[^\s]+", raw):
        return Command("url", raw, raw)
    # A bare domain is useful for voice/text commands; never treat shell fragments as URLs.
    if re.fullmatch(r"[\w-]+(?:\.[\w-]+)+(?:/[^\s]*)?", raw) and not re.search(r"\.(exe|bat|cmd|ps1|vbs|js)$", raw, re.I):
        return Command("url", "https://" + raw, raw)
    path = Path(raw)
    if path.is_absolute():
        return Command("folder" if path.is_dir() else "file", str(path), path.name or str(path))
    return None


def validate(command: Command):
    if command.kind == "url":
        parsed = urlparse(command.target)
        if command.target != "about:blank" and (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password):
            raise ValueError("Можно открывать только HTTP/HTTPS-сайты без реквизитов в адресе")
        return
    path = Path(command.target)
    if not path.is_absolute() or not path.exists():
        raise ValueError("Файл или папка не найдены. Добавьте точный путь в настройках команд.")
    if command.kind == "folder" and not path.is_dir():
        raise ValueError("Этот путь не является папкой")
    if command.kind == "app" and path.suffix.casefold() not in {".exe", ".lnk"}:
        raise ValueError("Для приложения укажите EXE или ярлык LNK")
    if command.kind == "file" and path.suffix.casefold() in {".exe", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".scr", ".lnk"}:
        raise ValueError("Исполняемый файл нужно добавить как приложение в настройках команд")


def execute(command: Command, dry_run: bool = False) -> str:
    validate(command)
    if dry_run:
        return f"Проверено: {command.label}. Запуск не выполнялся."
    if os.name != "nt":
        raise ValueError("Открытие файлов и приложений доступно в Windows")
    if command.kind == "url":
        if not webbrowser.open(command.target):
            raise ValueError("Windows не подтвердила запуск браузера")
        return f"Передал браузеру: {command.label}."
    os.startfile(command.target)
    return f"Передал Windows команду открыть: {command.label}."
